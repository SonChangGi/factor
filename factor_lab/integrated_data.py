"""Frozen, auditable free-market inputs for the integrated research engine."""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import hashlib
import json
import pandas as pd
import numpy as np

RESOURCE = Path(__file__).parent / "resources" / "integrated_universe.json"
BENCHMARKS = ("SPY", "QQQ", "^IXIC")
FIELDS = (
    "prices",
    "raw_close",
    "raw_open",
    "raw_high",
    "raw_low",
    "volumes",
    "dividends",
    "splits",
    "eligibility",
)

PROVIDER_FIELDS = (
    "provider_close",
    "provider_open",
    "provider_high",
    "provider_low",
    "provider_volumes",
)
OPTIONAL_FIELDS = ("shape_valid", "valuation_prices")


@dataclass
class IntegratedMarket:
    prices: pd.DataFrame
    raw_close: pd.DataFrame
    raw_open: pd.DataFrame
    raw_high: pd.DataFrame
    raw_low: pd.DataFrame
    volumes: pd.DataFrame
    dividends: pd.DataFrame
    splits: pd.DataFrame
    eligibility: pd.DataFrame
    metadata: dict = field(default_factory=dict)

    provider_close: pd.DataFrame | None = None
    provider_open: pd.DataFrame | None = None
    provider_high: pd.DataFrame | None = None
    provider_low: pd.DataFrame | None = None
    provider_volumes: pd.DataFrame | None = None
    shape_valid: pd.DataFrame | None = None
    # Provider/evidence-backed marks for a non-trading session are valuation
    # inputs only. They never enter signal formation or execution prices.
    valuation_prices: pd.DataFrame | None = None

    # Shape factors retain the provider split basis across corporate actions.
    @property
    def split_close(self):
        return self.provider_close if self.provider_close is not None else self.raw_close

    @property
    def split_open(self):
        frame = self.provider_open if self.provider_open is not None else self.raw_open
        return frame.where(self.shape_valid) if self.shape_valid is not None else frame

    @property
    def split_high(self):
        frame = self.provider_high if self.provider_high is not None else self.raw_high
        return frame.where(self.shape_valid) if self.shape_valid is not None else frame

    @property
    def split_low(self):
        frame = self.provider_low if self.provider_low is not None else self.raw_low
        return frame.where(self.shape_valid) if self.shape_valid is not None else frame

    @property
    def dollar_volumes(self):
        return self.raw_close * self.volumes


def integrated_universe():
    return json.loads(RESOURCE.read_text())


def compute_eligibility(prices, raw_close, volumes, symbols=None):
    observed = prices.notna() & prices.gt(0)
    volume_ok = volumes.notna() & volumes.gt(0)
    dv = (raw_close * volumes).where(volume_ok)
    returns = prices.pct_change(fill_method=None)
    result = (
        observed
        & volume_ok
        & raw_close.ge(5)
        & observed.cumsum().ge(252)
        & observed.rolling(252, min_periods=252).mean().ge(0.95)
        & volume_ok.rolling(252, min_periods=252).mean().ge(0.90)
        & returns.abs().gt(0.8).rolling(252, min_periods=252).sum().eq(0)
        & dv.rolling(63, min_periods=42).mean().ge(5_000_000)
    )
    if symbols is not None:
        result.loc[:, ~result.columns.isin(symbols)] = False
    result.loc[:, result.columns.isin(BENCHMARKS)] = False
    return result.fillna(False)


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_integrated_market(market, directory, *, compression_level=9):
    directory = Path(directory)
    if (directory / "manifest.json").exists():
        raise FileExistsError("Immutable snapshot already exists")
    directory.mkdir(parents=True, exist_ok=True)
    manifest = dict(market.metadata)
    manifest.pop("snapshotId", None)
    manifest["schemaVersion"] = (
        "integrated-market-v4"
        if market.valuation_prices is not None
        else "integrated-market-v3"
        if market.shape_valid is not None
        else "integrated-market-v2"
        if market.provider_close is not None
        else "integrated-market-v1"
    )
    manifest["files"] = {}
    for name in FIELDS + PROVIDER_FIELDS + OPTIONAL_FIELDS:
        frame = getattr(market, name)
        if frame is None:
            continue
        if not frame.index.equals(market.prices.index) or not frame.columns.equals(
            market.prices.columns
        ):
            raise ValueError(f"{name}: axes mismatch")
        path = directory / f"{name}.csv.gz"
        frame.to_csv(path, compression={"method": "gzip", "mtime": 0,
                                        "compresslevel": compression_level})
        manifest["files"][path.name] = _hash(path)
    manifest["snapshotId"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True).encode()
    ).hexdigest()
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
    market.metadata = manifest
    return market


def load_integrated_market(snapshot_dir: Path):
    root = Path(snapshot_dir)
    manifest = json.loads((root / "manifest.json").read_text())
    payload = dict(manifest)
    identity = payload.pop("snapshotId")
    if identity != hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest():
        raise ValueError("Snapshot manifest hash mismatch")
    frames = {}
    names = list(FIELDS) + [
        name for name in PROVIDER_FIELDS + OPTIONAL_FIELDS if f"{name}.csv.gz" in manifest["files"]
    ]
    for name in names:
        path = root / f"{name}.csv.gz"
        if _hash(path) != manifest["files"][path.name]:
            raise ValueError(f"Snapshot hash mismatch: {name}")
        frames[name] = pd.read_csv(path, index_col=0, parse_dates=True, float_precision="round_trip")
    frames["eligibility"] = frames["eligibility"].astype(bool)
    if "shape_valid" in frames:
        frames["shape_valid"] = frames["shape_valid"].astype(bool)
    market = IntegratedMarket(**frames, metadata=manifest)
    for name in names:
        frame = frames[name]
        if not frame.index.equals(market.prices.index) or not frame.columns.equals(
            market.prices.columns
        ):
            raise ValueError(f"Snapshot axes mismatch: {name}")
    if market.prices.index.has_duplicates or not market.prices.index.is_monotonic_increasing:
        raise ValueError("Invalid observation calendar")
    return market


def reconstruct_as_traded(market: IntegratedMarket) -> IntegratedMarket:
    """Invert Yahoo's split basis; a split on t applies only to sessions < t.

    Corporate actions must cover the provider adjustment horizon. This
    derivation changes neither total-return prices nor split-basis shape inputs.
    Volume is inverse-scaled, never adjusted for cash dividends.
    """
    if market.provider_close is not None:
        raise ValueError("Market already has an as-traded reconstruction")
    actions = market.splits
    if ((actions < 0) | np.isinf(actions)).any().any():
        raise ValueError("Invalid split ratio")
    if (actions.isna() & market.prices.notna()).any().any():
        raise ValueError("Missing split-action field for observed price")
    ratios = actions.fillna(0).replace(0, 1)
    future = ratios.iloc[::-1].cumprod().iloc[::-1].shift(-1, fill_value=1.0)
    if not np.isfinite(future.to_numpy()).all() or future.le(0).any().any():
        raise ValueError("Invalid cumulative split adjustment")
    raw = {
        name: getattr(market, "raw_" + name) * future for name in ("close", "open", "high", "low")
    }
    volumes = market.volumes / future
    metadata = dict(market.metadata)
    metadata.pop("snapshotId", None)
    metadata.pop("files", None)
    metadata.update(
        parentSnapshotId=market.metadata.get("snapshotId"),
        transformationVersion="yahoo-split-inversion-v1",
        ohlcvBasis="Derived as-traded OHLC = provider OHLC × product of strictly future split ratios; volume = provider volume / same product. No dividend volume adjustment.",
        shapePriceBasis="Original Yahoo split-adjusted OHLC, preserved as provider_*",
        dollarVolumeBasis="As-traded close × as-traded volume; invariant to paired provider close × provider volume",
        eligibilityPriceBasis="as-traded close >= USD 5",
        basisEvidence=[
            "https://investor.apple.com/dividend-history/default.aspx",
            "https://www.sec.gov/Archives/edgar/data/1045810/000104581024000144/nvda-20240607.htm",
            "https://github.com/ranaroussi/yfinance/issues/2929",
            "https://matplotlib.org/1.5.1/Matplotlib.pdf",
        ],
    )
    result = IntegratedMarket(
        prices=market.prices,
        raw_close=raw["close"],
        raw_open=raw["open"],
        raw_high=raw["high"],
        raw_low=raw["low"],
        volumes=volumes,
        dividends=market.dividends,
        splits=market.splits,
        eligibility=compute_eligibility(
            market.prices, raw["close"], volumes, metadata.get("requestedSymbols")
        ),
        metadata=metadata,
        provider_close=market.raw_close,
        provider_open=market.raw_open,
        provider_high=market.raw_high,
        provider_low=market.raw_low,
        provider_volumes=market.volumes,
        valuation_prices=market.valuation_prices,
    )
    before = market.raw_close * market.volumes
    after = result.raw_close * result.volumes
    if not np.allclose(before.to_numpy(), after.to_numpy(), rtol=1e-12, atol=1e-6, equal_nan=True):
        raise ValueError("Dollar-volume conservation failed")
    return result


def apply_market_quality(market: IntegratedMarket) -> IntegratedMarket:
    """Quarantine inconsistent range observations without rewriting source bars.

    Closing total-return observations remain a separate input contract. This
    does not assert that a contradictory row's closing print is independently
    verified, nor does it smooth or remove extreme observed returns.
    """
    close = market.provider_close if market.provider_close is not None else market.raw_close
    opening = market.provider_open if market.provider_open is not None else market.raw_open
    high = market.provider_high if market.provider_high is not None else market.raw_high
    low = market.provider_low if market.provider_low is not None else market.raw_low
    invalid = (
        high.lt(low - 1e-8)
        | opening.gt(high + 1e-8)
        | opening.lt(low - 1e-8)
        | close.gt(high + 1e-8)
        | close.lt(low - 1e-8)
    )
    market.shape_valid = ~invalid
    ledger = []
    rows, cols = np.where(invalid.to_numpy())
    for row, col in zip(rows, cols):
        ledger.append(
            {
                "date": str(close.index[row].date()),
                "symbol": str(close.columns[col]),
                "reason": "provider_OHLC_range_contradiction",
                "excludedInputs": ["open", "high", "low"],
                "provider": {
                    key: float(frame.iat[row, col]) if pd.notna(frame.iat[row, col]) else None
                    for key, frame in (
                        ("open", opening),
                        ("high", high),
                        ("low", low),
                        ("close", close),
                    )
                },
            }
        )
    previous = market.metadata.get("snapshotId")
    market.metadata = dict(market.metadata)
    if previous:
        market.metadata["parentSnapshotId"] = previous
    market.metadata.pop("snapshotId", None)
    market.metadata.pop("files", None)
    market.metadata["qualityVersion"] = "observed-OHLC-quarantine-v1"
    market.metadata["quarantinedOHLC"] = ledger
    market.metadata["closeInputContract"] = (
        "Observed positive-volume total-return close retained separately; contradictory OHLC ranges excluded only from open/high/low dependent signals. No inferred correction to close."
    )
    failures = dict(market.metadata.get("failedSymbols", {}))
    for symbol in market.metadata.get("requestedSymbols", market.prices.columns):
        if market.prices[symbol].notna().any():
            failures.pop(symbol, None)
        else:
            failures.setdefault(
                symbol, "No positive-volume price observations after quality filtering"
            )
    market.metadata["failedSymbols"] = failures
    return market


def positive_volume_coverage(data, symbol, asof=None):
    """Coverage of paired provider observations, never a reconstructed fill."""
    if ('Adj Close', symbol) not in data or ('Volume', symbol) not in data:
        return dict(observations=0, firstObservation=None)
    valid = data[('Adj Close', symbol)].gt(0) & data[('Volume', symbol)].gt(0)
    if asof is not None:
        valid &= data.index <= pd.Timestamp(asof)
    observed = data.index[valid]
    return dict(observations=int(valid.sum()),
                firstObservation=str(observed[0].date()) if len(observed) else None)


def history_coverage_issue(data, symbol, reference):
    expected = reference.get(symbol)
    if not expected or expected['observations'] == 0:
        return None
    observed = positive_volume_coverage(data, symbol, expected['asOf'])
    if (observed['observations'] < expected['observations'] or
            observed['firstObservation'] is None or
            observed['firstObservation'] > expected['firstObservation']):
        return dict(reason='truncated_positive_volume_history', expected=expected, observed=observed)
    return None
