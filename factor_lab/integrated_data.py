"""Frozen, auditable free-market inputs for the integrated research engine."""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import hashlib
import json
import time
from datetime import datetime, timezone
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
        frames[name] = pd.read_csv(path, index_col=0, parse_dates=True)
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


def collect_integrated_market(output_dir: Path, start="2010-01-01", end=None, symbols=None,
                              *, reference_coverage=None, archived_input_root=None):
    """Download in bounded batches; a finished snapshot is never overwritten.

    Failed symbols remain explicit missing columns. No synthetic prices or
    alternate-provider fields are substituted. Each cached batch has its own
    content hash, request contract and retrieval timestamp.
    """
    import yfinance as yf

    from .integrated_listing import listing_context, provider_symbols, batch_cache_key, normalize_provider_columns
    reference_coverage = reference_coverage or {}
    root = Path(output_dir)
    if (root / "manifest.json").exists():
        existing = load_integrated_market(root)
        previous = existing.metadata.get("request", {})
        if previous.get("start") != start or (
            end is not None and previous.get("endExclusive") != end
        ):
            raise ValueError("Immutable snapshot belongs to a different date request")
        expected = (
            sorted(set(symbols))
            if symbols is not None
            else sorted(r["symbol"] for r in integrated_universe()["symbols"])
        )
        if previous.get("symbols") != expected:
            raise ValueError("Immutable snapshot belongs to a different universe request")
        context = listing_context(expected, pd.Timestamp(previous['endExclusive']) - pd.Timedelta(days=1))
        if previous.get('listing') != context:
            raise ValueError('Immutable snapshot belongs to a different dated listing contract')
        for symbol, expected in reference_coverage.items():
            paired = pd.DataFrame({('Adj Close', symbol): existing.prices[symbol],
                                   ('Volume', symbol): existing.volumes[symbol]})
            if history_coverage_issue(paired, symbol, reference_coverage):
                raise ValueError(f'Immutable snapshot has truncated historical input: {symbol}')
        return existing
    root.mkdir(parents=True, exist_ok=True)
    universe = integrated_universe()
    requested = sorted(
        set(symbols if symbols is not None else [r["symbol"] for r in universe["symbols"]])
    )
    today = pd.Timestamp(datetime.now(timezone.utc).date())
    end = end or today.date().isoformat()
    # Historical output still requires all later corporate actions because
    # Yahoo retroactively split-adjusts the entire downloaded price history.
    download_end = max(pd.Timestamp(end), today + pd.Timedelta(days=1)).date().isoformat()
    context = listing_context(sorted(set(requested) | set(BENCHMARKS)), pd.Timestamp(end) - pd.Timedelta(days=1))
    request = {
        "listing": context,
        "start": start,
        "endExclusive": end,
        "providerEndExclusive": download_end,
        "symbols": requested,
        "provider": "Yahoo Finance",
        "autoAdjust": False,
    }
    contract = root / "request.json"
    if contract.exists() and json.loads(contract.read_text()) != request:
        raise ValueError("Resume request differs from existing collection")
    contract.write_text(json.dumps(request, indent=2) + "\n")
    cache = root / "downloads"
    cache.mkdir(exist_ok=True)
    all_symbols = sorted(set(requested) | set(BENCHMARKS))
    mapping = {
        "prices": "Adj Close",
        "raw_close": "Close",
        "raw_open": "Open",
        "raw_high": "High",
        "raw_low": "Low",
        "volumes": "Volume",
        "dividends": "Dividends",
        "splits": "Stock Splits",
    }
    collected = {k: {} for k in mapping}
    failures = {}
    receipts = []
    archive_symbols = set()
    for offset in range(0, len(all_symbols), 25):
        batch = all_symbols[offset : offset + 25]
        key = batch_cache_key(batch, context)
        provider_batch = list(provider_symbols(batch, context).values())
        path = cache / f"{key}.csv.gz"
        receipt = cache / f"{key}.json"
        data = None
        if path.exists() and receipt.exists():
            info = json.loads(receipt.read_text())
            if _hash(path) != info["sha256"]:
                raise ValueError(f"Corrupt download {key}")
            data = pd.read_csv(path, header=[0, 1], index_col=0, parse_dates=True)
        else:
            for attempt in range(3):
                try:
                    data = yf.download(
                        provider_batch,
                        start=start,
                        end=download_end,
                        auto_adjust=False,
                        actions=True,
                        repair=False,
                        keepna=True,
                        progress=False,
                        threads=False,
                        timeout=30,
                        group_by="column",
                    )
                    if data.empty:
                        raise ValueError("Empty provider response")
                    break
                except Exception as exc:
                    if attempt == 2:
                        failures.update({s: str(exc) for s in batch})
                        data = None
                    else:
                        time.sleep(1 + attempt)
            if data is not None:
                if not isinstance(data.columns, pd.MultiIndex):
                    data.columns = pd.MultiIndex.from_product([data.columns, provider_batch])
                data.index = pd.to_datetime(data.index).tz_localize(None).normalize()
                data.to_csv(path, compression={"method": "gzip", "mtime": 0})
                info = {
                    "symbols": batch,
                    "providerSymbols": provider_symbols(batch, context),
                    "listingVersion": context["version"],
                    "listingSourceHash": context["sourceHash"],
                    "retrievedAt": datetime.now(timezone.utc).isoformat(),
                    "sha256": _hash(path),
                }
                receipt.write_text(json.dumps(info, indent=2) + "\n")
        if data is None:
            continue
        expected_providers = provider_symbols(batch, context)
        if info.get('providerSymbols', dict(zip(batch, batch))) != expected_providers:
            raise ValueError('Cached provider identities differ from dated listing contract')
        data = normalize_provider_columns(data, batch, context)
        receipts.append(info)
        for symbol in batch:
            issue = history_coverage_issue(data, symbol, reference_coverage)
            missing = (('Adj Close', symbol) not in data or data[('Adj Close', symbol)].dropna().empty)
            if missing or issue:
                # Retry incomplete histories as well as wholly empty columns.
                # Keep the original batch and each rejected response immutable.
                stem = 'single-' + (hashlib.sha256(symbol.encode()).hexdigest()[:16] if expected_providers[symbol] == symbol else batch_cache_key([symbol], context))
                if issue:
                    stem += '-coverage'
                single_path = cache / (stem + '.csv.gz')
                single_receipt = single_path.with_suffix('.json')
                single = None
                if single_path.exists() and single_receipt.exists():
                    single_info = json.loads(single_receipt.read_text())
                    if _hash(single_path) != single_info['sha256']:
                        raise ValueError(f'Corrupt single-symbol download: {symbol}')
                    candidate = pd.read_csv(single_path, header=[0, 1], index_col=0, parse_dates=True)
                    if single_info.get('providerSymbols', {symbol: symbol}) != {symbol: expected_providers[symbol]}:
                        raise ValueError('Cached single-symbol provider identity differs')
                    candidate = normalize_provider_columns(candidate, [symbol], context)
                    if not history_coverage_issue(candidate, symbol, reference_coverage):
                        single = candidate
                if single is None:
                    for attempt in range(2):
                        try:
                            raw_candidate = yf.download([expected_providers[symbol]], start=start, end=download_end,
                                auto_adjust=False, actions=True, repair=False, keepna=True,
                                progress=False, threads=False, timeout=30, group_by='column')
                            candidate = normalize_provider_columns(raw_candidate, [symbol], context)
                            if ('Adj Close', symbol) not in candidate or candidate[('Adj Close', symbol)].dropna().empty:
                                raise ValueError('No adjusted price observations')
                            # A successful HTTP response may still be truncated.
                            # Record that response and reject it before analysis.
                            suffix = ''
                            sequence = 0
                            while (cache / (stem + suffix + '.csv.gz')).exists():
                                sequence += 1
                                suffix = '-attempt-' + str(sequence)
                            single_path = cache / (stem + suffix + '.csv.gz')
                            single_receipt = single_path.with_suffix('.json')
                            if not isinstance(raw_candidate.columns, pd.MultiIndex):
                                raw_candidate.columns = pd.MultiIndex.from_product([raw_candidate.columns, [expected_providers[symbol]]])
                            raw_candidate.to_csv(single_path, compression={'method':'gzip', 'mtime':0})
                            single_info = dict(symbols=[symbol], providerSymbols={symbol: expected_providers[symbol]},
                                listingVersion=context['version'], listingSourceHash=context['sourceHash'], retrievedAt=datetime.now(timezone.utc).isoformat(),
                                sha256=_hash(single_path), retryOf=key,
                                retryReason=issue or 'missing_adjusted_price')
                            bad = history_coverage_issue(candidate, symbol, reference_coverage)
                            if bad:
                                single_info['rejectedCoverage'] = bad
                            single_receipt.write_text(json.dumps(single_info, indent=2) + '\n')
                            if bad:
                                raise ValueError('Truncated positive-volume history after single-symbol retry')
                            single = candidate
                            break
                        except Exception as exc:
                            failures[symbol] = str(exc)
                            if attempt == 0:
                                time.sleep(1)
                if single is None:
                    if issue:
                        failure = dict(symbol=symbol, issue=issue, error=failures.get(symbol))
                        (root / 'history-coverage-failure.json').write_text(json.dumps(failure, indent=2)+'\n')
                        if archived_input_root is not None:
                            archive_symbols.add(symbol)
                            continue
                        raise ValueError(f'Truncated historical input remains after bounded retry: {symbol}')
                    continue
                failures.pop(symbol, None)
                receipts.append(single_info)
                source = single
            else:
                source = data
            for name, field_name in mapping.items():
                if (field_name, symbol) in source:
                    collected[name][symbol] = source[(field_name, symbol)]
    if "SPY" not in collected["prices"]:
        raise ValueError("SPY calendar unavailable; snapshot not published")
    spy_calendar = collected["prices"]["SPY"].dropna().index
    output_calendar = spy_calendar[(spy_calendar < pd.Timestamp(end)) & (spy_calendar < today)]
    if output_calendar.empty:
        raise ValueError("No completed SPY sessions in requested output interval")
    # Include action-only rows beyond the last completed market session while
    # inverting splits; those rows are removed from the published matrices.
    calendar = pd.DataFrame(collected["splits"]).index.union(spy_calendar).sort_values()
    frames = {
        k: pd.DataFrame(v).reindex(index=calendar, columns=all_symbols)
        for k, v in collected.items()
    }
    for k in ("prices", "raw_close", "raw_open", "raw_high", "raw_low"):
        frames[k] = frames[k].where(frames[k].gt(0))
    # A zero-volume provider bar is only a candidate valuation mark. Raw
    # downloads retain it, but an explicit dated amendment must admit it:
    # stale reports after a delisting must not silently complete held NAV.
    candidate_marks = frames["prices"].notna() & frames["volumes"].eq(0)
    good = frames["volumes"].gt(0)
    for k in ("prices", "raw_close", "raw_open", "raw_high", "raw_low"):
        frames[k] = frames[k].where(good)
    # A wholly failed batch must not bypass the same historical contract.
    for symbol in requested:
        paired = pd.DataFrame({('Adj Close', symbol): frames['prices'][symbol],
                               ('Volume', symbol): frames['volumes'][symbol]})
        issue = history_coverage_issue(paired, symbol, reference_coverage)
        if issue and symbol not in archive_symbols:
            if archived_input_root is None:
                (root / 'history-coverage-failure.json').write_text(json.dumps(dict(symbol=symbol, issue=issue), indent=2)+'\n')
                raise ValueError(f'Historical input coverage incomplete: {symbol}')
            archive_symbols.add(symbol)
    frames["eligibility"] = compute_eligibility(
        frames["prices"], frames["raw_close"], frames["volumes"], requested
    )
    metadata = {
        "requestedSymbols": requested,
        "listing": context,
        "failedSymbols": failures,
        "universeVersion": universe["version"],
        "dataAsOf": str(output_calendar[-1].date()),
        "providerAdjustmentHorizonEndExclusive": download_end,
        "request": request,
        "receipts": receipts,
        "inputCoverage": {symbol: {
            **positive_volume_coverage(pd.DataFrame({('Adj Close', symbol): frames['prices'][symbol],
                                                    ('Volume', symbol): frames['volumes'][symbol]}),
                                       symbol, str(output_calendar[-1].date())),
            'asOf': str(output_calendar[-1].date()),
            'basis': 'positive_adjusted_close_and_positive_provider_volume'}
            for symbol in requested},
        "inputCoverageReferenceHash": hashlib.sha256(json.dumps(reference_coverage, sort_keys=True).encode()).hexdigest(),
        "priceBasis": "Yahoo Adj Close: split and dividend adjusted; no separate dividend reinvestment",
        "ohlcvBasis": "Yahoo auto_adjust=False OHLC and volume; provider split-adjusted basis, not independently reconstructed as-traded observations",
        "dollarVolumeBasis": "Yahoo Close × Yahoo Volume; same paired provider basis",
        "universeSourceHash": _hash(RESOURCE),
    }
    market = reconstruct_as_traded(IntegratedMarket(**frames, metadata=metadata))
    market.valuation_prices = frames["prices"].copy()
    market.metadata["unadmittedNonTradingMarkCount"] = int(candidate_marks.loc[output_calendar].sum().sum())
    market.metadata["valuationBasis"] = (
        "Positive-volume total-return quotes by default. Raw zero-volume reports "
        "remain in immutable downloads; only explicit dated evidence amendments "
        "may admit non-trading holding valuations."
    )
    later_actions = market.splits.loc[market.splits.index > output_calendar[-1]].stack()
    market.metadata["splitActionsAfterOutputEnd"] = [
        {"date": str(date.date()), "symbol": symbol, "ratio": float(ratio)}
        for (date, symbol), ratio in later_actions.items()
        if ratio > 0
    ]
    for name in FIELDS + PROVIDER_FIELDS + OPTIONAL_FIELDS:
        frame = getattr(market, name)
        if frame is not None:
            setattr(market, name, frame.loc[output_calendar])
    if archive_symbols:
        from .integrated_archive import load_archived_columns, preserve_archived_columns
        archive = load_archived_columns(Path(archived_input_root) / 'raw', archive_symbols)
        market = preserve_archived_columns(market, archive, archive_symbols, reference_coverage)
        market.eligibility = compute_eligibility(market.prices, market.raw_close, market.volumes, requested)
    market.metadata['inputCoverage'] = {symbol: {
        **positive_volume_coverage(pd.DataFrame({('Adj Close', symbol): market.prices[symbol],
                                                ('Volume', symbol): market.volumes[symbol]}),
                                   symbol, str(output_calendar[-1].date())),
        'asOf': str(output_calendar[-1].date()),
        'basis': 'positive_adjusted_close_and_positive_provider_volume'} for symbol in requested}
    return save_integrated_market(apply_market_quality(market), root)
