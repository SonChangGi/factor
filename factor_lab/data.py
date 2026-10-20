from __future__ import annotations

import csv
import hashlib
import json
import shutil
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import rfc8785

from .config import RunConfig
from .universe import (
    DEFAULT_UNIVERSE,
    DEFAULT_UNIVERSE_PATH,
    is_supported_symbol,
    normalize_symbol,
    universe_frame_for_symbols,
)

DEMO_GENERATOR_VERSION = "demo-v2"
RECORD_CANONICALIZATION_VERSION = "rfc8785-jcs-records-v1"
MATRIX_CANONICALIZATION_VERSION = "datetime64-ns-matrix-v2"
LEGACY_MATRIX_DATETIME_UNITS = ("s", "ms", "us", "ns")
LEGACY_SNAPSHOT_READ_CONTRACT = {
    "format": "gzip_csv",
    "indexColumn": 0,
    "parseDates": True,
    "pandasFloatPrecision": "round_trip",
    "recordCanonicalization": RECORD_CANONICALIZATION_VERSION,
    "note": (
        "Use pandas.read_csv(..., index_col=0, parse_dates=True, "
        "float_precision='round_trip') before recomputing canonical matrix hashes."
    ),
}
SNAPSHOT_READ_CONTRACT = {
    **LEGACY_SNAPSHOT_READ_CONTRACT,
    "candidateZeroVolumeClosePolicy": "mask_adjusted_and_raw_v1",
    "matrixCanonicalization": MATRIX_CANONICALIZATION_VERSION,
}
LIVE_SNAPSHOT_HASH_FIELDS_V2 = (
    "prices",
    "volumes",
    "dollarVolumes",
    "rawCloses",
    "requestedSymbols",
    "returnedSymbols",
    "universeRecords",
    "priceSources",
    "dataSources",
)
LIVE_SNAPSHOT_HASH_FIELDS_V3 = (*LIVE_SNAPSHOT_HASH_FIELDS_V2, "comparisonPrices")
LIVE_SNAPSHOT_HASH_FIELDS = (
    *LIVE_SNAPSHOT_HASH_FIELDS_V3,
    "marketCaps",
    "marketCapSources",
)


@dataclass(slots=True)
class MarketData:
    prices: pd.DataFrame
    volumes: pd.DataFrame
    dollar_volumes: pd.DataFrame
    raw_closes: pd.DataFrame
    eligibility_mask: pd.DataFrame
    quality: pd.DataFrame
    universe: pd.DataFrame
    as_of: pd.Timestamp
    source_mode: str
    source_label: str
    price_basis: str
    volume_basis: str
    input_sha256: dict[str, str | None]
    benchmark: str
    notes: list[str] = field(default_factory=list)
    requested_through: str | None = None
    requested_candidate_count: int | None = None
    provider_returned_candidate_count: int | None = None
    provider: str | None = None
    price_sources: pd.DataFrame = field(default_factory=pd.DataFrame)
    data_sources: pd.DataFrame = field(default_factory=pd.DataFrame)
    raw_close_proxy_symbol_count: int = 0
    comparison_prices: pd.DataFrame = field(default_factory=pd.DataFrame)
    market_caps: pd.DataFrame = field(default_factory=pd.DataFrame)
    market_cap_sources: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def candidate_symbols(self) -> list[str]:
        benchmark = normalize_symbol(self.benchmark)
        return [column for column in self.prices.columns if normalize_symbol(column) != benchmark]

    @property
    def comparison_symbols(self) -> list[str]:
        return [normalize_symbol(column) for column in self.comparison_prices.columns]


def _normalize_matrix(frame: pd.DataFrame, *, source: str) -> pd.DataFrame:
    if frame.empty:
        raise ValueError(f"{source} contains no rows")
    normalized = frame.copy()
    normalized.index = pd.to_datetime(normalized.index, errors="coerce")
    if normalized.index.isna().any():
        raise ValueError(f"{source} contains invalid dates")
    if getattr(normalized.index, "tz", None) is not None:
        normalized.index = normalized.index.tz_convert("UTC").tz_localize(None)
    normalized.index = normalized.index.normalize()
    if normalized.index.has_duplicates:
        raise ValueError(f"{source} contains duplicate dates")
    normalized = normalized.sort_index()

    symbols = [normalize_symbol(column) for column in normalized.columns]
    if any(not symbol for symbol in symbols):
        raise ValueError(f"{source} contains blank symbols")
    unsupported = [symbol for symbol in symbols if not is_supported_symbol(symbol)]
    if unsupported:
        rendered = ", ".join(repr(symbol) for symbol in sorted(set(unsupported)))
        raise ValueError(f"{source} contains unsupported security symbols: {rendered}")
    if len(set(symbols)) != len(symbols):
        raise ValueError(f"{source} contains duplicate normalized symbols")
    normalized.columns = symbols
    try:
        normalized = normalized.apply(pd.to_numeric, errors="raise")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{source} contains non-numeric observations") from exc
    if bool(np.isinf(normalized.to_numpy(dtype=float, na_value=np.nan)).any()):
        raise ValueError(f"{source} contains non-finite observations")
    return normalized.dropna(axis=0, how="all").dropna(axis=1, how="all")


def _validate_raw_csv_headers(path: Path) -> None:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        header = next(csv.reader(handle), None)
    if not header:
        raise ValueError(f"{path} contains no CSV header")
    duplicates = sorted(name for name, count in Counter(header).items() if count > 1)
    if duplicates:
        rendered = ", ".join(repr(name) for name in duplicates)
        raise ValueError(f"{path} contains duplicate raw CSV headers: {rendered}")


def _strict_numeric_column(
    values: pd.Series,
    *,
    path: Path,
    kind: str,
    dates: pd.Series,
    symbols: pd.Series | str,
) -> pd.Series:
    stripped = values.astype(str).str.strip()
    blank = stripped.eq("")
    parsed = pd.to_numeric(stripped.where(~blank, np.nan), errors="coerce")
    finite = pd.Series(
        np.isfinite(parsed.to_numpy(dtype=float, na_value=np.nan)),
        index=parsed.index,
    )
    invalid = ~blank & ~finite
    if bool(invalid.any()):
        position = int(np.flatnonzero(invalid.to_numpy())[0])
        csv_row = position + 2
        date = dates.iloc[position]
        symbol = symbols.iloc[position] if isinstance(symbols, pd.Series) else symbols
        value = values.iloc[position]
        raise ValueError(
            f"{kind} input {path} contains malformed or non-finite numeric value: "
            f"row={csv_row}, date={date!r}, symbol={symbol!r}, value={value!r}"
        )
    return parsed.astype(float)


def _read_local_matrix(path: Path, *, kind: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"{kind} file not found: {path}")
    if path.suffix.lower() not in {".csv", ".txt"}:
        raise ValueError(f"{kind} input must be CSV")
    _validate_raw_csv_headers(path)
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    lower = {str(column).strip().lower(): column for column in raw.columns}
    if len(lower) != len(raw.columns):
        raise ValueError(f"{kind} input {path} contains duplicate normalized CSV headers")
    date_column = lower.get("date") or lower.get("timestamp")
    symbol_column = lower.get("symbol") or lower.get("ticker")
    value_candidates = {
        "prices": ("price", "adjusted_close", "adj_close"),
        "volumes": ("volume", "share_volume"),
        "market_caps": ("market_cap", "marketcap", "value"),
    }.get(kind)
    if value_candidates is None:
        raise ValueError(f"unsupported local matrix kind: {kind}")
    value_column = next((lower[name] for name in value_candidates if name in lower), None)
    if date_column is not None and symbol_column is not None and value_column is not None:
        if raw.duplicated([date_column, symbol_column]).any():
            raise ValueError(f"{kind} long-form input has duplicate date/symbol rows")
        strict_values = _strict_numeric_column(
            raw[value_column],
            path=path,
            kind=kind,
            dates=raw[date_column],
            symbols=raw[symbol_column],
        )
        pivot_input = raw[[date_column, symbol_column]].copy()
        pivot_input[value_column] = strict_values
        matrix = pivot_input.pivot(
            index=date_column,
            columns=symbol_column,
            values=value_column,
        )
    elif date_column is not None and symbol_column is not None:
        accepted = ", ".join(value_candidates)
        raise ValueError(f"{kind} long-form input requires one of: {accepted}")
    else:
        if raw.shape[1] < 2:
            raise ValueError(
                f"{kind} wide-form input requires a date column and at least one symbol"
            )
        date_values = raw.iloc[:, 0]
        strict_columns = {
            column: _strict_numeric_column(
                raw[column],
                path=path,
                kind=kind,
                dates=date_values,
                symbols=str(column),
            )
            for column in raw.columns[1:]
        }
        matrix = pd.DataFrame(strict_columns, index=raw.index)
        matrix.index = date_values
    return _normalize_matrix(matrix, source=str(path))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_records_json_bytes(
    frame: pd.DataFrame | list[dict[str, object]],
) -> bytes:
    """Serialize tabular provenance as RFC 8785 canonical finite JSON records."""

    records = (
        json.loads(
            frame.to_json(
                orient="records",
                date_format="iso",
                date_unit="ns",
                double_precision=15,
                force_ascii=False,
            )
        )
        if isinstance(frame, pd.DataFrame)
        else json.loads(json.dumps(frame, ensure_ascii=False, allow_nan=False))
    )
    return rfc8785.dumps(records)


def canonical_records_sha256(frame: pd.DataFrame | list[dict[str, object]]) -> str:
    """Hash ordered provenance rows after deterministic finite JSON serialization."""

    return hashlib.sha256(_canonical_records_json_bytes(frame)).hexdigest()


def _validated_provenance_frames(
    price_sources: pd.DataFrame,
    data_sources: pd.DataFrame,
    candidate_symbols: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    normalized_prices = price_sources.copy()
    normalized_health = data_sources.copy()
    if (
        normalized_prices.empty
        or not {"symbol", "price_source"}.issubset(normalized_prices.columns)
        or normalized_health.empty
        or not {"source", "status"}.issubset(normalized_health.columns)
    ):
        raise ValueError("actual-market provider provenance is incomplete")
    normalized_prices["symbol"] = normalized_prices["symbol"].map(
        lambda value: "" if pd.isna(value) else normalize_symbol(str(value))
    )
    normalized_prices["price_source"] = normalized_prices["price_source"].map(
        lambda value: "" if pd.isna(value) else str(value).strip()
    )
    symbols = normalized_prices["symbol"].tolist()
    if (
        any(not symbol for symbol in symbols)
        or normalized_prices["price_source"].eq("").any()
        or len(set(symbols)) != len(symbols)
        or not set(candidate_symbols).issubset(symbols)
    ):
        raise ValueError("actual-market price-source coverage is invalid")
    normalized_health["source"] = normalized_health["source"].map(
        lambda value: "" if pd.isna(value) else str(value).strip()
    )
    normalized_health["status"] = normalized_health["status"].map(
        lambda value: "" if pd.isna(value) else str(value).strip()
    )
    if normalized_health["source"].eq("").any() or normalized_health["status"].eq("").any():
        raise ValueError("actual-market source-health rows are invalid")
    return normalized_prices, normalized_health


def _ordered_symbols_sha256(symbols: list[str]) -> str:
    payload = json.dumps(symbols, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _matrix_sha256(
    frame: pd.DataFrame,
    *,
    prefix: bytes,
    datetime_unit: str,
) -> str:
    """Hash ordered labels, canonical dates, missingness, and finite float64 values."""

    numeric = frame.to_numpy(dtype=np.float64, na_value=np.nan)
    missing = np.isnan(numeric)
    if bool((~missing & ~np.isfinite(numeric)).any()):
        raise ValueError("cannot hash a matrix containing non-finite non-missing values")
    stable_values = numeric.copy()
    stable_values[missing] = 0.0

    digest = hashlib.sha256()
    digest.update(prefix)
    digest.update(np.asarray(frame.shape, dtype="<i8").tobytes())
    for column in frame.columns:
        encoded = str(column).encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "little"))
        digest.update(encoded)
    dates = pd.DatetimeIndex(frame.index).as_unit(datetime_unit).asi8.astype("<i8", copy=False)
    digest.update(dates.tobytes())
    digest.update(np.packbits(missing.reshape(-1), bitorder="little").tobytes())
    digest.update(stable_values.astype("<f8", copy=False).tobytes(order="C"))
    return digest.hexdigest()


def _legacy_canonical_matrix_sha256(
    frame: pd.DataFrame,
    *,
    datetime_unit: str,
) -> str:
    if datetime_unit not in LEGACY_MATRIX_DATETIME_UNITS:
        raise ValueError("unsupported legacy matrix datetime unit")
    return _matrix_sha256(
        frame,
        prefix=b"momentum-factor-lab-matrix-v1\0",
        datetime_unit=datetime_unit,
    )


def _canonical_matrix_sha256(frame: pd.DataFrame) -> str:
    """Hash a matrix with a datetime-unit-invariant nanosecond date index."""

    return _matrix_sha256(
        frame,
        prefix=b"momentum-factor-lab-matrix-v2\0",
        datetime_unit="ns",
    )


def _business_dates(config: RunConfig) -> pd.DatetimeIndex:
    end = config.end_date or "2025-12-31"
    dates = pd.bdate_range(config.start_date, end)
    if len(dates) < config.min_history_days + 2:
        raise ValueError("demo date range is too short for the configured history requirement")
    return dates


def _resolved_demo_symbols(config: RunConfig) -> list[str]:
    benchmark = normalize_symbol(config.benchmark)
    available = [symbol for symbol in DEFAULT_UNIVERSE if symbol != benchmark]
    if len(available) < config.demo_symbol_count:
        available.extend(
            f"DEMO{i:04d}" for i in range(1, config.demo_symbol_count - len(available) + 1)
        )
    return available[: config.demo_symbol_count]


def _inject_demo_gaps(
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    symbols: list[str],
    config: RunConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if config.demo_missing_ratio == 0.0:
        return prices, volumes
    eligible_cells = (len(prices.index) - 1) * len(symbols)
    gap_count = min(
        eligible_cells,
        max(1, int(np.ceil(eligible_cells * config.demo_missing_ratio))),
    )
    seed_material = f"{DEMO_GENERATOR_VERSION}|missing|{config.demo_seed}".encode("utf-8")
    missing_seed = int.from_bytes(hashlib.sha256(seed_material).digest()[:8], "little")
    rng = np.random.default_rng(missing_seed)
    selected = rng.choice(eligible_cells, size=gap_count, replace=False)
    mask = np.zeros((len(prices.index), len(symbols)), dtype=bool)
    mask[:-1].flat[selected] = True

    prices = prices.copy()
    volumes = volumes.copy()
    prices.loc[:, symbols] = prices.loc[:, symbols].mask(mask)
    volumes.loc[:, symbols] = volumes.loc[:, symbols].mask(mask)
    return prices, volumes


def generate_demo_data(config: RunConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Generate a broad deterministic fixture for UI and regression testing.

    The paths are deliberately stylized and must never be described as observed
    prices or empirical factor evidence.
    """

    symbols = _resolved_demo_symbols(config)
    benchmark = normalize_symbol(config.benchmark)
    dates = _business_dates(config)
    rng = np.random.default_rng(config.demo_seed)
    common = rng.normal(0.00028, 0.009, len(dates))
    time = np.arange(len(dates), dtype=float)
    prices: dict[str, np.ndarray] = {}
    volumes: dict[str, np.ndarray] = {}

    benchmark_returns = common + rng.normal(0.0, 0.0025, len(dates))
    prices[benchmark] = 100.0 * np.exp(np.cumsum(benchmark_returns))
    volumes[benchmark] = rng.integers(30_000_000, 100_000_000, len(dates))

    for index, symbol in enumerate(symbols):
        cohort = index % 12
        drift = 0.00008 + 0.000025 * ((index % 7) - 3)
        idiosyncratic = rng.normal(drift, 0.010 + 0.001 * (index % 5), len(dates))
        regime = np.zeros(len(dates), dtype=float)
        if cohort == 0:
            regime += 0.00038
        elif cohort == 1:
            regime += 0.00034
            regime[-126:] -= 0.00095
        elif cohort == 2:
            regime[-63:] += 0.00110
        elif cohort == 3:
            regime += np.linspace(-0.00020, 0.00060, len(dates))
        elif cohort == 4:
            regime += np.linspace(0.00060, -0.00020, len(dates))
        elif cohort == 5:
            regime += 0.00042 * np.sin(time / 18.0)
        elif cohort == 6:
            regime += 0.00022
        elif cohort == 7:
            regime[-21:] += 0.00130
        elif cohort == 8:
            regime[-21:] -= 0.00130
        elif cohort == 9:
            regime += 0.00042 * np.sin(time / 45.0 + index)
        elif cohort == 10:
            idiosyncratic *= 0.70
            regime += 0.00018
        else:
            idiosyncratic *= 1.25
        returns = 0.42 * common + idiosyncratic + regime
        prices[symbol] = 35.0 * np.exp(np.cumsum(returns))
        base_volume = rng.integers(1_000_000, 18_000_000, len(dates)).astype(float)
        volumes[symbol] = base_volume * (1.0 + (index % 10) / 12.0)

    price_frame = pd.DataFrame(prices, index=dates).round(4)
    volume_frame = pd.DataFrame(volumes, index=dates).round(0)
    return _inject_demo_gaps(
        price_frame,
        volume_frame,
        symbols,
        config,
    )


def _slice_dates(frame: pd.DataFrame, config: RunConfig) -> pd.DataFrame:
    start = pd.Timestamp(config.start_date)
    end = pd.Timestamp(config.end_date) if config.end_date else None
    sliced = frame.loc[frame.index >= start]
    if end is not None:
        sliced = sliced.loc[sliced.index <= end]
    return sliced


def _rolling_observation_ratio(frame: pd.DataFrame, window: int) -> pd.DataFrame:
    counts = frame.notna().rolling(window, min_periods=1).sum()
    denominators = pd.Series(
        np.minimum(np.arange(1, len(frame.index) + 1), window),
        index=frame.index,
        dtype=float,
    )
    return counts.div(denominators, axis=0)


def _eligibility_components(
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    config: RunConfig,
    *,
    dollar_volumes: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """Return date-t eligibility components using only information known through t."""

    numeric_prices = prices.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    numeric_volumes = (
        volumes.reindex(index=prices.index, columns=prices.columns)
        .apply(pd.to_numeric, errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
    )
    observed = numeric_prices.notna()
    history_ok = observed.cumsum().ge(config.min_history_days)
    price_ok = numeric_prices.ge(config.min_price)
    price_coverage_ok = _rolling_observation_ratio(
        numeric_prices,
        config.data_quality_lookback_days,
    ).ge(1.0 - config.max_price_missing_ratio)
    exact_returns = numeric_prices.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)
    extreme_observed = exact_returns.abs().gt(config.max_extreme_daily_return)
    extreme_return_ok = ~extreme_observed.rolling(
        config.data_quality_lookback_days,
        min_periods=1,
    ).max().fillna(False).astype(bool)

    volume_required = config.min_avg_dollar_volume > 0.0 or config.min_avg_volume > 0.0
    if volume_required:
        volume_coverage_ok = _rolling_observation_ratio(
            numeric_volumes,
            config.data_quality_lookback_days,
        ).ge(1.0 - config.max_volume_missing_ratio)
    else:
        volume_coverage_ok = pd.DataFrame(True, index=prices.index, columns=prices.columns)

    share_volume_ok = pd.DataFrame(True, index=prices.index, columns=prices.columns)
    if config.min_avg_volume > 0.0:
        share_count = numeric_volumes.rolling(
            config.liquidity_lookback_days,
            min_periods=1,
        ).count()
        share_mean = numeric_volumes.rolling(
            config.liquidity_lookback_days,
            min_periods=1,
        ).mean()
        share_volume_ok = share_count.ge(config.min_liquidity_observations) & share_mean.ge(
            config.min_avg_volume
        )

    dollar_volume_ok = pd.DataFrame(True, index=prices.index, columns=prices.columns)
    if config.min_avg_dollar_volume > 0.0:
        supplied_dollar_volume = (
            dollar_volumes.reindex(index=prices.index, columns=prices.columns)
            if dollar_volumes is not None and not dollar_volumes.empty
            else pd.DataFrame()
        )
        dollar_volume = (
            supplied_dollar_volume
            if not supplied_dollar_volume.empty
            else numeric_prices.mul(numeric_volumes)
        )
        liquidity_count = dollar_volume.rolling(
            config.liquidity_lookback_days,
            min_periods=1,
        ).count()
        liquidity_mean = dollar_volume.rolling(
            config.liquidity_lookback_days,
            min_periods=1,
        ).mean()
        dollar_volume_ok = liquidity_count.ge(
            config.min_liquidity_observations
        ) & liquidity_mean.ge(config.min_avg_dollar_volume)
    return {
        "history_ok": history_ok.fillna(False),
        "price_ok": price_ok.fillna(False),
        "recent_price_coverage_ok": price_coverage_ok.fillna(False),
        "recent_extreme_return_ok": extreme_return_ok.fillna(False),
        "recent_volume_coverage_ok": volume_coverage_ok.fillna(False),
        "share_volume_ok": share_volume_ok.fillna(False),
        "dollar_volume_ok": dollar_volume_ok.fillna(False),
    }


def build_eligibility_mask(
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    config: RunConfig,
    *,
    dollar_volumes: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build causal date-t eligibility; an event can affect only t and later signals."""

    components = _eligibility_components(
        prices,
        volumes,
        config,
        dollar_volumes=dollar_volumes,
    )
    eligible = pd.DataFrame(True, index=prices.index, columns=prices.columns)
    for component in components.values():
        eligible &= component
    benchmark = normalize_symbol(config.benchmark)
    if benchmark in eligible:
        eligible[benchmark] = False
    return eligible.fillna(False).astype(bool)


def latest_eligibility_exclusion_reasons(
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    config: RunConfig,
    *,
    dollar_volumes: pd.DataFrame | None = None,
) -> dict[str, list[str]]:
    """Return stable, possibly overlapping reasons for the latest causal mask."""

    components = _eligibility_components(
        prices,
        volumes,
        config,
        dollar_volumes=dollar_volumes,
    )
    reason_by_component = {
        "history_ok": "insufficient_history",
        "price_ok": "missing_or_below_min_price",
        "recent_price_coverage_ok": "recent_price_coverage",
        "recent_extreme_return_ok": "recent_extreme_return",
        "recent_volume_coverage_ok": "recent_volume_coverage",
        "share_volume_ok": "share_volume_requirement",
        "dollar_volume_ok": "liquidity_requirement",
    }
    result: dict[str, list[str]] = {}
    for symbol in prices.columns:
        result[str(symbol)] = [
            reason_by_component[name]
            for name, component in components.items()
            if not bool(component.iloc[-1].get(symbol, False))
        ]
    return result


def _quality_frame(
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    dollar_volumes: pd.DataFrame,
    eligibility: pd.DataFrame,
    config: RunConfig,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    benchmark = normalize_symbol(config.benchmark)
    reasons_by_symbol = latest_eligibility_exclusion_reasons(
        prices,
        volumes,
        config,
        dollar_volumes=dollar_volumes,
    )
    for symbol in prices.columns:
        series = prices[symbol]
        valid = series.dropna()
        volume = volumes[symbol].dropna() if symbol in volumes else pd.Series(dtype=float)
        trailing_prices = series.tail(config.min_history_days)
        trailing_dollar_volume = (
            dollar_volumes[symbol].tail(config.liquidity_lookback_days)
            if symbol in dollar_volumes
            else pd.Series(dtype=float)
        )
        latest_price = pd.to_numeric(pd.Series([series.iloc[-1]]), errors="coerce").iloc[0]
        exclusion_reasons = reasons_by_symbol.get(str(symbol), []) if symbol != benchmark else []
        rows.append(
            {
                "symbol": symbol,
                "role": "benchmark" if symbol == benchmark else "candidate",
                "first_date": valid.index.min().date().isoformat() if not valid.empty else None,
                "last_date": valid.index.max().date().isoformat() if not valid.empty else None,
                "observations": int(valid.size),
                "latest_price": float(latest_price) if pd.notna(latest_price) else None,
                "recent_missing_ratio": float(trailing_prices.isna().mean()),
                "volume_observations": int(volume.size),
                "avg_dollar_volume": (
                    float(trailing_dollar_volume.mean())
                    if not trailing_dollar_volume.dropna().empty
                    else None
                ),
                "eligible_latest": bool(eligibility.iloc[-1].get(symbol, False)),
                "exclusion_reasons": exclusion_reasons,
            }
        )
    return pd.DataFrame(rows)


def _local_or_demo_inputs(
    config: RunConfig,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    str,
    str,
    str,
    str,
    dict[str, str | None],
    list[str],
]:
    if config.demo:
        prices, volumes = generate_demo_data(config)
        dollar_volumes = prices.mul(volumes)
        source_mode = "demo"
        source_label = f"deterministic demo ({config.demo_symbol_count} candidates)"
        price_basis = "synthetic_total_return_like"
        volume_basis = "synthetic_split_consistent"
        resolved_symbols = _resolved_demo_symbols(config)
        default_universe_sha256 = _sha256_file(DEFAULT_UNIVERSE_PATH)
        resolved_universe_sha256 = _ordered_symbols_sha256(resolved_symbols)
        generator_source_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        demo_specification = {
            "version": DEMO_GENERATOR_VERSION,
            "startDate": config.start_date,
            "endDate": config.end_date or "2025-12-31",
            "benchmark": normalize_symbol(config.benchmark),
            "candidateSymbolCount": config.demo_symbol_count,
            "seed": config.demo_seed,
            "missingRatio": config.demo_missing_ratio,
            "defaultUniverseFileSha256": default_universe_sha256,
            "resolvedOrderedUniverseSha256": resolved_universe_sha256,
            "generatorSourceSha256": generator_source_sha256,
        }
        specification_bytes = json.dumps(
            demo_specification,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        input_sha256 = {
            "prices": None,
            "volumes": None,
            "rawCloses": None,
            "dollarVolumes": None,
            "demoSpecification": hashlib.sha256(specification_bytes).hexdigest(),
            "generatorSource": generator_source_sha256,
            "defaultUniverseFile": default_universe_sha256,
            "resolvedOrderedUniverse": resolved_universe_sha256,
        }
        notes = [
            "Synthetic demo paths exist only for tests and explicitly labeled UI examples.",
            "Demo output must never replace a failed live-market run.",
        ]
        if config.demo_missing_ratio > 0.0:
            notes.append(
                f"Deterministic demo sparsity uses missing_ratio={config.demo_missing_ratio:g}; "
                "the final date is preserved."
            )
    else:
        assert config.prices_path is not None
        prices = _read_local_matrix(config.prices_path, kind="prices")
        volumes = (
            _read_local_matrix(config.volumes_path, kind="volumes")
            if config.volumes_path is not None
            else pd.DataFrame(index=prices.index)
        )
        dollar_volumes = (
            prices.mul(volumes) if not volumes.empty else pd.DataFrame(index=prices.index)
        )
        source_mode = "local_file"
        source_label = config.prices_path.name
        price_basis = "user_supplied_adjusted"
        volume_basis = "user_attested_split_adjusted" if config.volumes_path else "not_provided"
        input_sha256 = {
            "prices": _sha256_file(config.prices_path),
            "volumes": _sha256_file(config.volumes_path) if config.volumes_path else None,
            "rawCloses": None,
            "dollarVolumes": (
                _canonical_matrix_sha256(dollar_volumes) if not dollar_volumes.empty else None
            ),
        }
        notes = [
            "Local prices are interpreted as split- and distribution-adjusted research prices."
        ]
    return (
        prices,
        volumes,
        dollar_volumes,
        source_mode,
        source_label,
        price_basis,
        volume_basis,
        input_sha256,
        notes,
    )


def _live_inputs(
    config: RunConfig,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    str,
    dict[str, str | None],
    list[str],
    int,
]:
    from .live_data import download_live_data

    acquired = download_live_data(config)
    if acquired.live_error:
        raise RuntimeError("live acquisition did not return an actual-market dataset")
    full_prices = acquired.raw_prices if not acquired.raw_prices.empty else acquired.prices
    full_volumes = acquired.raw_volumes if not acquired.raw_volumes.empty else acquired.volumes
    raw_closes = acquired.raw_closes.reindex(index=full_prices.index, columns=full_prices.columns)
    comparison_symbols = list(config.comparison_benchmarks)
    comparison_set = set(comparison_symbols)
    candidate_symbols = {
        normalize_symbol(str(symbol))
        for symbol in acquired.candidate_universe.get("symbol", pd.Series(dtype=object))
        if normalize_symbol(str(symbol)) not in comparison_set
    }
    candidate_columns = [
        column
        for column in full_prices.columns
        if normalize_symbol(str(column)) in candidate_symbols
    ]
    non_positive_price_cells = int(full_prices.le(0.0).fillna(False).to_numpy().sum())
    non_positive_raw_close_cells = int(raw_closes.le(0.0).fillna(False).to_numpy().sum())
    negative_volume_cells = int(full_volumes.lt(0.0).fillna(False).to_numpy().sum())
    zero_volume_candidate = full_volumes.reindex(
        index=full_prices.index,
        columns=candidate_columns,
    ).eq(0.0)
    zero_volume_adjusted_price_cells = int(
        (zero_volume_candidate & full_prices.reindex(columns=candidate_columns).notna())
        .to_numpy()
        .sum()
    )
    zero_volume_raw_close_cells = int(
        (zero_volume_candidate & raw_closes.reindex(columns=candidate_columns).notna())
        .to_numpy()
        .sum()
    )
    # Public providers occasionally encode an unavailable quote as zero. A stock price
    # cannot be zero, so treating those cells as observations would create log(0),
    # artificial -100% returns, and ticker-reuse joins. Preserve the symbol and expose
    # the sanitation count, but keep the invalid cells missing in the canonical input.
    full_prices = full_prices.mask(full_prices.le(0.0))
    raw_closes = raw_closes.mask(raw_closes.le(0.0))
    full_volumes = full_volumes.mask(full_volumes.lt(0.0))
    # A provider can repeat the last sale indefinitely while reporting zero
    # traded shares during a suspension or halt.  Such a row is useful as a
    # stale reference mark but is not an observed, executable close.  Candidate
    # stock backtests therefore fail closed on it instead of selling at a
    # carried quote.  Comparison benchmarks are intentionally excluded because
    # index volume can be undefined and comparator prices are never executed.
    if candidate_columns:
        full_prices.loc[:, candidate_columns] = full_prices.loc[:, candidate_columns].mask(
            zero_volume_candidate
        )
        raw_closes.loc[:, candidate_columns] = raw_closes.loc[:, candidate_columns].mask(
            zero_volume_candidate
        )
    benchmark = normalize_symbol(config.benchmark)
    analysis_universe = acquired.candidate_universe.loc[
        ~acquired.candidate_universe["symbol"]
        .astype(str)
        .map(normalize_symbol)
        .isin(comparison_set)
    ].copy()
    candidate_symbols = set(analysis_universe["symbol"].astype(str))
    returned_candidates = [
        symbol
        for symbol in analysis_universe["symbol"].astype(str)
        if symbol not in comparison_set
        and symbol in full_prices
        and full_prices[symbol].notna().any()
    ]
    columns = ([benchmark] if benchmark in full_prices else []) + returned_candidates
    prices = (
        full_prices.reindex(columns=columns).dropna(axis=0, how="all").dropna(axis=1, how="all")
    )
    volumes = full_volumes.reindex(index=prices.index, columns=prices.columns)
    raw_closes = raw_closes.reindex(index=prices.index, columns=prices.columns)
    comparison_prices = full_prices.reindex(
        index=prices.index,
        columns=comparison_symbols,
    )
    raw_close_proxy = raw_closes.isna() & prices.notna()
    effective_raw_closes = raw_closes.combine_first(prices)
    dollar_volumes = effective_raw_closes.mul(volumes)
    # Keep the legacy snapshot slots deterministic without inventing a size
    # signal. The fixed public method uses only factor score and lagged raw
    # dollar volume, both reproducible in the scheduled Pages build.
    market_caps = pd.DataFrame(
        np.nan,
        index=prices.index,
        columns=prices.columns,
        dtype=float,
    )
    market_cap_sources = pd.DataFrame(
        [
            {
                "source": "not-used-by-score-liquidity-fixed-method",
                "status": "not_used",
                "records": 0,
                "point_in_time_market_cap": False,
                "note": (
                    "The fixed allocation method uses factor score and trailing raw dollar "
                    "volume only; no market-cap value is synthesized or copied backward."
                ),
            }
        ]
    )
    data_sources = pd.concat(
        [acquired.data_sources, market_cap_sources],
        ignore_index=True,
        sort=False,
    )
    proxy_symbol_count = int(raw_close_proxy.any(axis=0).sum())
    input_sha256 = {
        "prices": _canonical_matrix_sha256(prices),
        "volumes": _canonical_matrix_sha256(volumes),
        "rawCloses": _canonical_matrix_sha256(raw_closes),
        "dollarVolumes": _canonical_matrix_sha256(dollar_volumes),
        "requestedSymbols": _ordered_symbols_sha256(
            [symbol for symbol in analysis_universe["symbol"].astype(str)]
        ),
        "returnedSymbols": _ordered_symbols_sha256(returned_candidates),
        "universeRecords": canonical_records_sha256(analysis_universe),
        "priceSources": canonical_records_sha256(acquired.price_sources),
        "dataSources": canonical_records_sha256(data_sources),
        "comparisonPrices": _canonical_matrix_sha256(comparison_prices),
        "marketCaps": _canonical_matrix_sha256(market_caps),
        "marketCapSources": canonical_records_sha256(market_cap_sources),
    }
    notes = [
        "Actual-market analysis uses provider adjusted close for factor returns.",
        "Historical dollar volume uses provider raw close times raw share volume where available.",
        (
            f"{proxy_symbol_count} symbols required adjusted/close proxy dollar volume because a "
            "distinct raw close was unavailable; the count is disclosed."
        ),
        (
            "The fixed allocation method uses factor score and trailing raw dollar volume; "
            "market cap is not used, synthesized, or copied backward."
        ),
    ]
    if non_positive_price_cells or non_positive_raw_close_cells or negative_volume_cells:
        notes.append(
            "Invalid provider cells were treated as missing before hashing and analysis: "
            f"adjusted_price_non_positive={non_positive_price_cells}, "
            f"raw_close_non_positive={non_positive_raw_close_cells}, "
            f"share_volume_negative={negative_volume_cells}."
        )
    if zero_volume_adjusted_price_cells or zero_volume_raw_close_cells:
        notes.append(
            "Candidate zero-volume quotes were treated as stale/untradable missing "
            "closes before hashing and analysis: "
            f"adjusted_price_zero_volume={zero_volume_adjusted_price_cells}, "
            f"raw_close_zero_volume={zero_volume_raw_close_cells}. Comparison benchmarks were "
            "not masked by this stock execution rule."
        )
    returned_set = set(returned_candidates)
    missing_candidates = len(candidate_symbols - returned_set)
    if missing_candidates:
        notes.append(
            f"Provider returned no usable price history for {missing_candidates} candidates."
        )
    return (
        prices,
        volumes,
        dollar_volumes,
        raw_closes,
        comparison_prices,
        analysis_universe,
        acquired.price_sources,
        data_sources,
        market_caps,
        market_cap_sources,
        acquired.provider,
        input_sha256,
        notes,
        proxy_symbol_count,
    )


def _finalize_market_data(
    config: RunConfig,
    *,
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    dollar_volumes: pd.DataFrame,
    raw_closes: pd.DataFrame | None,
    source_mode: str,
    source_label: str,
    price_basis: str,
    volume_basis: str,
    input_sha256: dict[str, str | None],
    notes: list[str],
    comparison_prices: pd.DataFrame | None = None,
    universe: pd.DataFrame | None = None,
    requested_candidate_count: int | None = None,
    provider_returned_candidate_count: int | None = None,
    provider: str | None = None,
    price_sources: pd.DataFrame | None = None,
    data_sources: pd.DataFrame | None = None,
    market_caps: pd.DataFrame | None = None,
    market_cap_sources: pd.DataFrame | None = None,
    raw_close_proxy_symbol_count: int = 0,
) -> MarketData:
    prices = _slice_dates(prices, config).dropna(axis=0, how="all").dropna(axis=1, how="all")
    benchmark = normalize_symbol(config.benchmark)
    comparison_symbols = list(config.comparison_benchmarks)
    comparison_set = set(comparison_symbols)
    embedded_comparison_prices = prices.reindex(
        columns=[symbol for symbol in comparison_symbols if symbol in prices.columns]
    )
    analysis_columns = [
        column for column in prices.columns if column == benchmark or column not in comparison_set
    ]
    prices = prices.reindex(columns=analysis_columns)
    volumes = _slice_dates(volumes, config).reindex(index=prices.index, columns=prices.columns)
    dollar_volumes = _slice_dates(dollar_volumes, config).reindex(
        index=prices.index,
        columns=prices.columns,
    )
    canonical_market_caps = (
        _slice_dates(market_caps, config).reindex(index=prices.index, columns=prices.columns)
        if market_caps is not None and not market_caps.empty
        else pd.DataFrame(index=prices.index, columns=prices.columns, dtype=float)
    )
    canonical_raw_closes = (
        _slice_dates(raw_closes, config).reindex(index=prices.index, columns=prices.columns)
        if raw_closes is not None and not raw_closes.empty
        else pd.DataFrame(index=prices.index)
    )
    has_supplied_comparison = comparison_prices is not None and not comparison_prices.empty
    supplied_comparison_prices = (
        _slice_dates(comparison_prices, config).copy()
        if has_supplied_comparison
        else pd.DataFrame(index=prices.index)
    )
    if has_supplied_comparison:
        supplied_comparison_prices.columns = [
            normalize_symbol(column) for column in supplied_comparison_prices.columns
        ]
        if len(set(supplied_comparison_prices.columns)) != len(supplied_comparison_prices.columns):
            raise ValueError("comparison prices contain duplicate normalized symbols")
        comparison_symbols = list(supplied_comparison_prices.columns)
    canonical_comparison_prices = supplied_comparison_prices.reindex(
        index=prices.index,
        columns=comparison_symbols,
    ).combine_first(
        embedded_comparison_prices.reindex(
            index=prices.index,
            columns=comparison_symbols,
        )
    )
    if prices.empty or len(prices.index) < config.min_history_days + 2:
        raise ValueError("price input does not contain enough observed rows after date filtering")
    if not prices.index.is_monotonic_increasing or prices.index.has_duplicates:
        raise ValueError("price dates must be unique and increasing")
    if bool(prices.le(0.0).fillna(False).to_numpy().any()):
        raise ValueError("prices must be strictly positive when observed")
    if not volumes.empty and bool(volumes.lt(0.0).fillna(False).to_numpy().any()):
        raise ValueError("volumes must be non-negative when observed")
    if not canonical_raw_closes.empty and bool(
        canonical_raw_closes.le(0.0).fillna(False).to_numpy().any()
    ):
        raise ValueError("raw closes must be strictly positive when observed")
    if bool(canonical_market_caps.le(0.0).fillna(False).to_numpy().any()):
        raise ValueError("market caps must be strictly positive when observed")
    if bool(canonical_comparison_prices.le(0.0).fillna(False).to_numpy().any()):
        raise ValueError("comparison prices must be strictly positive when observed")
    candidate_columns = [column for column in prices.columns if column != benchmark]
    if len(candidate_columns) < config.top_n:
        raise ValueError(
            f"analyzed universe has {len(candidate_columns)} candidates but top_n={config.top_n}"
        )
    eligibility = build_eligibility_mask(
        prices,
        volumes,
        config,
        dollar_volumes=dollar_volumes,
    )
    quality = _quality_frame(prices, volumes, dollar_volumes, eligibility, config)
    resolved_universe = (
        universe if universe is not None else universe_frame_for_symbols(candidate_columns)
    )
    if config.min_avg_dollar_volume <= 0.0:
        notes.append("Liquidity filtering is disabled because min_avg_dollar_volume is 0.")
    elif dollar_volumes.empty:
        notes.append(
            "Liquidity filtering was requested but no dollar-volume evidence was supplied."
        )
    as_of = pd.Timestamp(prices.dropna(axis=0, how="all").index.max())
    return MarketData(
        prices=prices,
        volumes=volumes,
        dollar_volumes=dollar_volumes,
        raw_closes=canonical_raw_closes,
        eligibility_mask=eligibility,
        quality=quality,
        universe=resolved_universe,
        as_of=as_of,
        source_mode=source_mode,
        source_label=source_label,
        price_basis=price_basis,
        volume_basis=volume_basis,
        input_sha256=input_sha256,
        benchmark=benchmark,
        notes=notes,
        requested_through=config.effective_end_date,
        requested_candidate_count=(
            requested_candidate_count
            if requested_candidate_count is not None
            else len(candidate_columns)
        ),
        provider_returned_candidate_count=(
            provider_returned_candidate_count
            if provider_returned_candidate_count is not None
            else len(candidate_columns)
        ),
        provider=provider,
        price_sources=price_sources if price_sources is not None else pd.DataFrame(),
        data_sources=data_sources if data_sources is not None else pd.DataFrame(),
        raw_close_proxy_symbol_count=raw_close_proxy_symbol_count,
        comparison_prices=canonical_comparison_prices,
        market_caps=canonical_market_caps,
        market_cap_sources=(
            market_cap_sources if market_cap_sources is not None else pd.DataFrame()
        ),
    )


def load_market_data(config: RunConfig) -> MarketData:
    config.validate()
    if config.live:
        (
            prices,
            volumes,
            dollar_volumes,
            raw_closes,
            comparison_prices,
            universe,
            price_sources,
            data_sources,
            market_caps,
            market_cap_sources,
            provider,
            input_sha256,
            notes,
            proxy_symbol_count,
        ) = _live_inputs(config)
        return _finalize_market_data(
            config,
            prices=prices,
            volumes=volumes,
            dollar_volumes=dollar_volumes,
            raw_closes=raw_closes,
            comparison_prices=comparison_prices,
            source_mode="live_market",
            source_label=provider,
            price_basis="provider_adjusted_close",
            volume_basis="raw_close_x_raw_volume_with_disclosed_fallback_proxy",
            input_sha256=input_sha256,
            notes=notes,
            universe=universe,
            requested_candidate_count=len(universe),
            provider_returned_candidate_count=len(
                [
                    column
                    for column in prices.columns
                    if column != normalize_symbol(config.benchmark)
                ]
            ),
            provider=provider,
            price_sources=price_sources,
            data_sources=data_sources,
            market_caps=market_caps,
            market_cap_sources=market_cap_sources,
            raw_close_proxy_symbol_count=proxy_symbol_count,
        )
    (
        prices,
        volumes,
        dollar_volumes,
        source_mode,
        source_label,
        price_basis,
        volume_basis,
        input_sha256,
        notes,
    ) = _local_or_demo_inputs(config)
    finalized = _finalize_market_data(
        config,
        prices=prices,
        volumes=volumes,
        dollar_volumes=dollar_volumes,
        raw_closes=None,
        source_mode=source_mode,
        source_label=source_label,
        price_basis=price_basis,
        volume_basis=volume_basis,
        input_sha256=input_sha256,
        notes=notes,
    )
    if config.demo:
        candidate_columns = [
            column for column in finalized.prices.columns if column != finalized.benchmark
        ]
        demo_shares = pd.Series(
            {
                symbol: 50_000_000.0 * (1.0 + (index % 40))
                for index, symbol in enumerate(candidate_columns)
            },
            dtype=float,
        )
        finalized.market_caps = finalized.prices.mul(demo_shares, axis="columns").reindex(
            columns=finalized.prices.columns
        )
        finalized.market_cap_sources = pd.DataFrame(
            [
                {
                    "symbol": symbol,
                    "mapping": "deterministic_demo",
                    "taxonomy": "synthetic",
                    "tag": "demoSharesOutstanding",
                    "valueKind": "shares",
                    "latestMarketCapAvailable": True,
                }
                for symbol in candidate_columns
            ]
        )
        finalized.input_sha256["prices"] = _canonical_matrix_sha256(finalized.prices)
        finalized.input_sha256["volumes"] = _canonical_matrix_sha256(finalized.volumes)
        finalized.input_sha256["dollarVolumes"] = _canonical_matrix_sha256(finalized.dollar_volumes)
        finalized.input_sha256["marketCaps"] = _canonical_matrix_sha256(finalized.market_caps)
        finalized.input_sha256["marketCapSources"] = canonical_records_sha256(
            finalized.market_cap_sources
        )
    elif config.market_caps_path is not None:
        local_market_caps = _read_local_matrix(
            config.market_caps_path,
            kind="market_caps",
        )
        finalized.market_caps = _slice_dates(local_market_caps, config).reindex(
            index=finalized.prices.index,
            columns=finalized.prices.columns,
        )
        if bool(finalized.market_caps.le(0.0).fillna(False).to_numpy().any()):
            raise ValueError("local market caps must be strictly positive when observed")
        covered = finalized.market_caps.iloc[-1].drop(labels=[finalized.benchmark], errors="ignore")
        coverage = float(covered.notna().mean()) if len(covered) else 0.0
        if coverage < config.market_cap_min_universe_coverage:
            raise ValueError(
                "local point-in-time market-cap coverage is below the required threshold: "
                f"{coverage:.2%}"
            )
        finalized.market_cap_sources = pd.DataFrame(
            [
                {
                    "symbol": symbol,
                    "mapping": "user_supplied_point_in_time",
                    "taxonomy": "user_attested",
                    "tag": "marketCap",
                    "valueKind": "direct_cap",
                    "latestMarketCapAvailable": bool(pd.notna(value)),
                }
                for symbol, value in covered.items()
            ]
        )
        finalized.input_sha256["marketCaps"] = _canonical_matrix_sha256(finalized.market_caps)
        finalized.input_sha256["marketCapSources"] = canonical_records_sha256(
            finalized.market_cap_sources
        )
        finalized.notes.append(
            "Local market-cap values are treated as user-attested point-in-time observations."
        )
    return finalized


def write_market_data_snapshot(market: MarketData, output_dir: Path) -> dict[str, str]:
    """Persist the exact canonical input matrices for reproducible actual runs."""

    if market.source_mode != "live_market":
        raise ValueError("market-data snapshots require actual live-market data")
    universe = market.universe.copy()
    if universe.empty or "symbol" not in universe:
        raise ValueError("market-data snapshot universe must contain symbols")
    universe["symbol"] = universe["symbol"].map(lambda value: normalize_symbol(str(value)))
    universe_symbols = universe["symbol"].tolist()
    if any(not symbol for symbol in universe_symbols) or len(set(universe_symbols)) != len(
        universe_symbols
    ):
        raise ValueError("market-data snapshot universe symbols are blank or duplicated")
    candidate_symbols = market.candidate_symbols
    candidate_set = set(candidate_symbols)
    if [symbol for symbol in universe_symbols if symbol in candidate_set] != candidate_symbols:
        raise ValueError("market-data snapshot universe order differs from analyzed symbols")
    if market.requested_candidate_count != len(universe_symbols):
        raise ValueError("market-data snapshot requested count differs from its universe")
    if market.provider_returned_candidate_count != len(candidate_symbols):
        raise ValueError("market-data snapshot provider-returned count differs from prices")
    if market.source_mode == "live_market" and (
        not isinstance(market.source_label, str)
        or not market.source_label.strip()
        or not isinstance(market.provider, str)
        or not market.provider.strip()
        or not isinstance(market.price_basis, str)
        or not market.price_basis.strip()
        or not isinstance(market.volume_basis, str)
        or not market.volume_basis.strip()
        or not isinstance(market.requested_through, str)
        or not market.requested_through.strip()
        or not isinstance(market.raw_close_proxy_symbol_count, int)
        or isinstance(market.raw_close_proxy_symbol_count, bool)
        or not 0 <= market.raw_close_proxy_symbol_count <= len(candidate_symbols) + 1
    ):
        raise ValueError("live market snapshot metadata contract is incomplete")
    price_sources, data_sources = _validated_provenance_frames(
        market.price_sources,
        market.data_sources,
        candidate_symbols,
    )

    canonical_volumes = market.volumes.reindex(
        index=market.prices.index,
        columns=market.prices.columns,
    )
    canonical_dollar_volumes = market.dollar_volumes.reindex(
        index=market.prices.index,
        columns=market.prices.columns,
    )
    canonical_raw_closes = market.raw_closes.reindex(
        index=market.prices.index,
        columns=market.prices.columns,
    )
    canonical_market_caps = market.market_caps.reindex(
        index=market.prices.index,
        columns=market.prices.columns,
    )
    market_cap_sources = market.market_cap_sources.copy()
    if canonical_market_caps.empty or market_cap_sources.empty:
        raise ValueError("live market snapshot requires point-in-time market-cap evidence")
    candidate_zero_volume = canonical_volumes.reindex(columns=candidate_symbols).eq(0.0)
    if bool(
        (candidate_zero_volume & market.prices.reindex(columns=candidate_symbols).notna())
        .to_numpy()
        .any()
    ) or bool(
        (candidate_zero_volume & canonical_raw_closes.reindex(columns=candidate_symbols).notna())
        .to_numpy()
        .any()
    ):
        raise ValueError("live market violates the candidate zero-volume close policy")
    canonical_comparison_prices = market.comparison_prices.reindex(index=market.prices.index).copy()
    canonical_comparison_prices.columns = [
        normalize_symbol(column) for column in canonical_comparison_prices.columns
    ]
    comparison_symbols = list(canonical_comparison_prices.columns)
    if (
        canonical_comparison_prices.empty
        or market.benchmark not in comparison_symbols
        or any(not symbol for symbol in comparison_symbols)
        or len(set(comparison_symbols)) != len(comparison_symbols)
    ):
        raise ValueError("live market comparison-price contract is incomplete")
    input_hashes = {
        "prices": _canonical_matrix_sha256(market.prices),
        "volumes": _canonical_matrix_sha256(canonical_volumes),
        "dollarVolumes": _canonical_matrix_sha256(canonical_dollar_volumes),
        "requestedSymbols": _ordered_symbols_sha256(universe_symbols),
        "returnedSymbols": _ordered_symbols_sha256(candidate_symbols),
        "universeRecords": canonical_records_sha256(universe),
        "priceSources": canonical_records_sha256(price_sources),
        "dataSources": canonical_records_sha256(data_sources),
        "comparisonPrices": _canonical_matrix_sha256(canonical_comparison_prices),
        "marketCaps": _canonical_matrix_sha256(canonical_market_caps),
        "marketCapSources": canonical_records_sha256(market_cap_sources),
    }
    if market.source_mode == "live_market":
        input_hashes["rawCloses"] = _canonical_matrix_sha256(canonical_raw_closes)
        if set(market.input_sha256) != set(LIVE_SNAPSHOT_HASH_FIELDS):
            raise ValueError("live market input hash contract is incomplete")
        for field in LIVE_SNAPSHOT_HASH_FIELDS:
            if market.input_sha256.get(field) != input_hashes[field]:
                raise ValueError(f"live market input hash differs from observed {field}")

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    if output_dir.exists() and not output_dir.is_dir():
        raise ValueError("market-data snapshot destination must be a directory")
    staging_dir = Path(
        tempfile.mkdtemp(
            prefix=f".{output_dir.name}.staging-",
            dir=output_dir.parent,
        )
    )
    compression = {"method": "gzip", "compresslevel": 6, "mtime": 0}
    paths = {
        "prices": staging_dir / "adjusted_prices.csv.gz",
        "volumes": staging_dir / "share_volumes.csv.gz",
        "dollarVolumes": staging_dir / "dollar_volumes.csv.gz",
        "universe": staging_dir / "universe.json",
        "priceSources": staging_dir / "price_sources.json",
        "dataSources": staging_dir / "data_sources.json",
        "manifest": staging_dir / "market_data_manifest.json",
        "rawCloses": staging_dir / "raw_closes.csv.gz",
        "comparisonPrices": staging_dir / "comparison_adjusted_prices.csv.gz",
        "marketCaps": staging_dir / "point_in_time_market_caps.csv.gz",
        "marketCapSources": staging_dir / "market_cap_sources.json",
    }
    try:
        market.prices.to_csv(paths["prices"], compression=compression)
        canonical_volumes.to_csv(paths["volumes"], compression=compression)
        canonical_dollar_volumes.to_csv(paths["dollarVolumes"], compression=compression)
        paths["universe"].write_bytes(_canonical_records_json_bytes(universe))
        paths["priceSources"].write_bytes(_canonical_records_json_bytes(price_sources))
        paths["dataSources"].write_bytes(_canonical_records_json_bytes(data_sources))
        paths["marketCapSources"].write_bytes(_canonical_records_json_bytes(market_cap_sources))
        canonical_raw_closes.to_csv(
            paths["rawCloses"],
            compression=compression,
        )
        canonical_comparison_prices.to_csv(
            paths["comparisonPrices"],
            compression=compression,
        )
        canonical_market_caps.to_csv(paths["marketCaps"], compression=compression)
        manifest = {
            "schemaVersion": 4,
            "mode": market.source_mode,
            "sourceLabel": market.source_label,
            "provider": market.provider,
            "requestedThrough": market.requested_through,
            "actualAsOf": market.as_of.date().isoformat(),
            "requestedCandidateCount": market.requested_candidate_count,
            "providerReturnedCandidateCount": market.provider_returned_candidate_count,
            "latestEligibleCandidateCount": int(
                market.eligibility_mask.drop(columns=[market.benchmark], errors="ignore")
                .iloc[-1]
                .sum()
            ),
            "priceBasis": market.price_basis,
            "volumeBasis": market.volume_basis,
            "rawCloseProxySymbolCount": market.raw_close_proxy_symbol_count,
            "comparisonSymbols": comparison_symbols,
            "comparisonPriceBasis": market.price_basis,
            "comparisonAsOf": (
                canonical_comparison_prices.dropna(axis=0, how="all").index.max().date().isoformat()
                if not canonical_comparison_prices.dropna(axis=0, how="all").empty
                else None
            ),
            "readContract": SNAPSHOT_READ_CONTRACT,
            "matrixSha256": input_hashes,
            "fileSha256": {
                key: _sha256_file(path) for key, path in paths.items() if key != "manifest"
            },
            "files": {key: path.name for key, path in paths.items() if key != "manifest"},
            "notes": market.notes,
        }
        paths["manifest"].write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if output_dir.exists():
            backup_dir = Path(
                tempfile.mkdtemp(
                    prefix=f".{output_dir.name}.backup-",
                    dir=output_dir.parent,
                )
            )
            backup_dir.rmdir()
            output_dir.replace(backup_dir)
            try:
                staging_dir.replace(output_dir)
            except Exception:
                backup_dir.replace(output_dir)
                raise
            shutil.rmtree(backup_dir, ignore_errors=True)
        else:
            staging_dir.replace(output_dir)
    except Exception:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    return {key: str(output_dir / path.name) for key, path in paths.items()}


def read_market_data_snapshot(config: RunConfig, snapshot_dir: Path) -> MarketData:
    """Read and verify a previously exported actual-market snapshot.

    This is an explicit reproducibility path, not a provider or synthetic
    fallback. Every persisted file and canonical matrix digest is checked before
    the panels are admitted to the current research engine.
    """

    config.validate()
    if not config.live or config.demo or config.prices_path is not None:
        raise ValueError("actual-market snapshots require a live RunConfig")
    manifest_path = snapshot_dir / "market_data_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("market-data snapshot manifest is missing or invalid") from exc
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") not in {2, 3, 4}:
        raise ValueError("unsupported market-data snapshot manifest")
    schema_version = int(manifest["schemaVersion"])
    if manifest.get("mode") != "live_market":
        raise ValueError("market-data snapshot must contain actual live-market data")
    snapshot_read_contract = manifest.get("readContract")
    legacy_read_contract = snapshot_read_contract == LEGACY_SNAPSHOT_READ_CONTRACT
    if (
        snapshot_read_contract not in (SNAPSHOT_READ_CONTRACT, LEGACY_SNAPSHOT_READ_CONTRACT)
        or not isinstance(manifest.get("sourceLabel"), str)
        or not str(manifest["sourceLabel"]).strip()
        or not isinstance(manifest.get("provider"), str)
        or not str(manifest["provider"]).strip()
        or not isinstance(manifest.get("priceBasis"), str)
        or not str(manifest["priceBasis"]).strip()
        or not isinstance(manifest.get("volumeBasis"), str)
        or not str(manifest["volumeBasis"]).strip()
        or not isinstance(manifest.get("requestedThrough"), str)
        or not str(manifest["requestedThrough"]).strip()
        or (
            schema_version >= 3
            and (
                not isinstance(manifest.get("comparisonPriceBasis"), str)
                or not str(manifest["comparisonPriceBasis"]).strip()
                or not isinstance(manifest.get("comparisonSymbols"), list)
            )
        )
    ):
        raise ValueError("market-data snapshot metadata contract is incomplete")
    files = manifest.get("files")
    file_hashes = manifest.get("fileSha256")
    matrix_hashes = manifest.get("matrixSha256")
    if not isinstance(files, dict) or not isinstance(file_hashes, dict):
        raise ValueError("market-data snapshot file contract is incomplete")
    if not isinstance(matrix_hashes, dict):
        raise ValueError("market-data snapshot matrix hashes are missing")
    expected_hash_fields = {
        2: LIVE_SNAPSHOT_HASH_FIELDS_V2,
        3: LIVE_SNAPSHOT_HASH_FIELDS_V3,
        4: LIVE_SNAPSHOT_HASH_FIELDS,
    }[schema_version]
    if set(matrix_hashes) != set(expected_hash_fields) or any(
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
        for digest in matrix_hashes.values()
    ):
        raise ValueError("market-data snapshot input hash contract is incomplete")
    required = (
        "prices",
        "volumes",
        "dollarVolumes",
        "rawCloses",
        "universe",
        "priceSources",
        "dataSources",
    )
    if schema_version >= 3:
        required = (*required, "comparisonPrices")
    if schema_version == 4:
        required = (*required, "marketCaps", "marketCapSources")
    if set(files) != set(required) or set(file_hashes) != set(required):
        raise ValueError("market-data snapshot file contract is incomplete")
    paths: dict[str, Path] = {}
    for component in required:
        filename = files.get(component)
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise ValueError(f"market-data snapshot has an unsafe {component} filename")
        path = snapshot_dir / filename
        if not path.is_file() or _sha256_file(path) != file_hashes.get(component):
            raise ValueError(f"market-data snapshot {component} file hash mismatch")
        paths[component] = path

    def read_frame(field: str) -> pd.DataFrame:
        try:
            frame = pd.read_csv(
                paths[field],
                index_col=0,
                parse_dates=True,
                float_precision="round_trip",
            )
        except Exception as exc:
            raise ValueError(f"market-data snapshot {field} cannot be read") from exc
        frame.index = pd.to_datetime(frame.index).tz_localize(None).normalize()
        frame.columns = [normalize_symbol(column) for column in frame.columns]
        return frame.apply(pd.to_numeric, errors="coerce")

    benchmark = normalize_symbol(config.benchmark)
    prices = read_frame("prices")
    volumes = read_frame("volumes").reindex(index=prices.index, columns=prices.columns)
    dollar_volumes = read_frame("dollarVolumes").reindex(
        index=prices.index,
        columns=prices.columns,
    )
    raw_closes = read_frame("rawCloses").reindex(index=prices.index, columns=prices.columns)
    if schema_version >= 3:
        comparison_prices = read_frame("comparisonPrices").reindex(index=prices.index)
        comparison_symbols = [
            normalize_symbol(symbol) for symbol in manifest.get("comparisonSymbols", [])
        ]
        if (
            not comparison_symbols
            or any(not symbol for symbol in comparison_symbols)
            or len(set(comparison_symbols)) != len(comparison_symbols)
            or comparison_symbols != list(comparison_prices.columns)
            or benchmark not in comparison_symbols
        ):
            raise ValueError("market-data snapshot comparison symbol contract is invalid")
    else:
        comparison_prices = prices.reindex(columns=[benchmark])
    market_caps = (
        read_frame("marketCaps").reindex(index=prices.index, columns=prices.columns)
        if schema_version == 4
        else pd.DataFrame(index=prices.index, columns=prices.columns, dtype=float)
    )

    def read_records(field: str) -> pd.DataFrame:
        try:
            records = json.loads(paths[field].read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"market-data snapshot {field} cannot be read") from exc
        if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
            raise ValueError(f"market-data snapshot {field} must contain JSON records")
        return pd.DataFrame(records)

    universe = read_records("universe")
    price_sources = read_records("priceSources")
    data_sources = read_records("dataSources")
    market_cap_sources = read_records("marketCapSources") if schema_version == 4 else pd.DataFrame()
    if universe.empty or "symbol" not in universe:
        raise ValueError("market-data snapshot universe is missing symbols")
    universe["symbol"] = universe["symbol"].map(lambda value: normalize_symbol(str(value)))
    universe_symbols = universe["symbol"].tolist()
    if any(not symbol for symbol in universe_symbols) or len(set(universe_symbols)) != len(
        universe_symbols
    ):
        raise ValueError("market-data snapshot universe symbols are blank or duplicated")
    candidate_columns = [column for column in prices.columns if column != benchmark]
    candidate_set = set(candidate_columns)
    if [symbol for symbol in universe_symbols if symbol in candidate_set] != candidate_columns:
        raise ValueError("market-data snapshot universe order differs from price columns")
    price_sources, data_sources = _validated_provenance_frames(
        price_sources,
        data_sources,
        candidate_columns,
    )
    matrix_frames = {
        "prices": prices,
        "volumes": volumes,
        "dollarVolumes": dollar_volumes,
        "rawCloses": raw_closes,
    }
    if schema_version == 3:
        matrix_frames["comparisonPrices"] = comparison_prices
    elif schema_version == 4:
        matrix_frames["comparisonPrices"] = comparison_prices
        matrix_frames["marketCaps"] = market_caps
    non_matrix_hashes = {
        "requestedSymbols": _ordered_symbols_sha256(universe_symbols),
        "returnedSymbols": _ordered_symbols_sha256(candidate_columns),
        "universeRecords": canonical_records_sha256(universe),
        "priceSources": canonical_records_sha256(price_sources),
        "dataSources": canonical_records_sha256(data_sources),
    }
    if schema_version == 4:
        non_matrix_hashes["marketCapSources"] = canonical_records_sha256(market_cap_sources)
    for component, digest in non_matrix_hashes.items():
        if matrix_hashes.get(component) != digest:
            raise ValueError(f"market-data snapshot {component} matrix hash mismatch")
    if legacy_read_contract:
        legacy_datetime_unit = next(
            (
                unit
                for unit in LEGACY_MATRIX_DATETIME_UNITS
                if all(
                    matrix_hashes.get(component)
                    == _legacy_canonical_matrix_sha256(frame, datetime_unit=unit)
                    for component, frame in matrix_frames.items()
                )
            ),
            None,
        )
        if legacy_datetime_unit is None:
            raise ValueError(
                "legacy market-data snapshot matrix hashes have no common datetime unit"
            )
    else:
        for component, frame in matrix_frames.items():
            if matrix_hashes.get(component) != _canonical_matrix_sha256(frame):
                raise ValueError(f"market-data snapshot {component} matrix hash mismatch")
    upgraded_input_hashes = {
        **{
            component: _canonical_matrix_sha256(frame) for component, frame in matrix_frames.items()
        },
        **non_matrix_hashes,
    }
    candidate_zero_volume = volumes.reindex(columns=candidate_columns).eq(0.0)
    adjusted_close_violations = (
        candidate_zero_volume & prices.reindex(columns=candidate_columns).notna()
    )
    raw_close_violations = (
        candidate_zero_volume & raw_closes.reindex(columns=candidate_columns).notna()
    )
    if bool(adjusted_close_violations.to_numpy().any()) or bool(
        raw_close_violations.to_numpy().any()
    ):
        prefix = "legacy " if legacy_read_contract else ""
        raise ValueError(
            f"{prefix}market-data snapshot violates the candidate zero-volume close policy"
        )
    expected_as_of = str(manifest.get("actualAsOf") or "")
    observed_as_of = prices.index.max().date().isoformat() if not prices.empty else ""
    if observed_as_of != expected_as_of:
        raise ValueError("market-data snapshot actualAsOf does not match prices")

    requested_candidate_count = manifest.get("requestedCandidateCount")
    provider_returned_candidate_count = manifest.get("providerReturnedCandidateCount")
    latest_eligible_candidate_count = manifest.get("latestEligibleCandidateCount")
    if (
        not isinstance(requested_candidate_count, int)
        or isinstance(requested_candidate_count, bool)
        or requested_candidate_count != len(universe_symbols)
        or not isinstance(provider_returned_candidate_count, int)
        or isinstance(provider_returned_candidate_count, bool)
        or provider_returned_candidate_count != len(candidate_columns)
        or provider_returned_candidate_count > requested_candidate_count
        or not isinstance(latest_eligible_candidate_count, int)
        or isinstance(latest_eligible_candidate_count, bool)
        or not 0 <= latest_eligible_candidate_count <= provider_returned_candidate_count
    ):
        raise ValueError("market-data snapshot universe counts are inconsistent")
    raw_close_proxy_symbol_count = manifest.get("rawCloseProxySymbolCount")
    if (
        not isinstance(raw_close_proxy_symbol_count, int)
        or isinstance(raw_close_proxy_symbol_count, bool)
        or not 0 <= raw_close_proxy_symbol_count <= provider_returned_candidate_count + 1
    ):
        raise ValueError("market-data snapshot raw-close proxy count is inconsistent")
    market = _finalize_market_data(
        config,
        prices=prices,
        volumes=volumes,
        dollar_volumes=dollar_volumes,
        raw_closes=raw_closes,
        source_mode="live_market",
        source_label=str(manifest["sourceLabel"]),
        price_basis=str(manifest["priceBasis"]),
        volume_basis=str(manifest["volumeBasis"]),
        input_sha256=upgraded_input_hashes,
        notes=[
            *[str(note) for note in manifest.get("notes", []) if str(note).strip()],
            (
                f"Raw-close proxy count is {raw_close_proxy_symbol_count}; "
                "the fixed policy uses verified factor scores and trailing raw dollar volume."
            ),
            "Verified replay of an exported actual-market snapshot; no synthetic fallback used.",
            *(
                []
                if schema_version == 4
                else [
                    "Legacy snapshot has no point-in-time market-cap panel; that optional "
                    "diagnostic is not used by the current fixed allocation methodology."
                ]
            ),
            *(
                []
                if schema_version >= 3
                else [
                    "Legacy schema-v2 snapshot has no separate chart-comparator matrix; "
                    "only its primary benchmark can be replayed and other comparisons are unavailable."
                ]
            ),
        ],
        comparison_prices=comparison_prices,
        universe=universe,
        requested_candidate_count=requested_candidate_count,
        provider_returned_candidate_count=provider_returned_candidate_count,
        provider=str(manifest["provider"]),
        price_sources=price_sources,
        data_sources=data_sources,
        market_caps=market_caps,
        market_cap_sources=market_cap_sources,
        raw_close_proxy_symbol_count=raw_close_proxy_symbol_count,
    )
    market.requested_through = str(manifest["requestedThrough"])
    return market
