from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Iterable
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from .config import RunConfig
from .data import build_eligibility_mask, latest_eligibility_exclusion_reasons
from .universe import (
    DEFAULT_UNIVERSE,
    build_public_universe_frame,
    is_known_etf_symbol,
    normalize_symbol,
    stock_only_universe_frame,
    universe_frame_for_symbols,
)
from .publication_security import (
    PUBLIC_CACHE_REFERENCE,
    redact_credential_like_text,
)


@dataclass(slots=True)
class MarketData:
    prices: pd.DataFrame
    volumes: pd.DataFrame
    provider: str
    fetched_at: datetime
    as_of: pd.Timestamp | None
    exclusions: pd.DataFrame
    candidate_universe: pd.DataFrame
    eligible_universe: pd.DataFrame
    price_sources: pd.DataFrame
    data_sources: pd.DataFrame
    live_error: str | None = None
    data_quality: pd.DataFrame = field(default_factory=pd.DataFrame)
    raw_prices: pd.DataFrame = field(default_factory=pd.DataFrame)
    raw_closes: pd.DataFrame = field(default_factory=pd.DataFrame)
    raw_volumes: pd.DataFrame = field(default_factory=pd.DataFrame)
    stock_splits: pd.DataFrame = field(default_factory=pd.DataFrame)


def _source_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    columns = [
        "source",
        "status",
        "records",
        "candidate_symbols",
        "requested_price_symbols",
        "returned_price_symbols",
        "eligible_price_symbols",
        "liquidity_eligible_symbols",
        "excluded_symbols",
        "subset_run",
        "point_in_time_universe",
        "universe_provenance",
        "cache_path",
        "retries",
        "error",
        "note",
        "benchmark_symbol",
        "benchmark_price_available",
        "chart_benchmark_symbol",
        "chart_benchmark_price_available",
        "additional_comparison_symbols",
        "additional_comparison_prices_available",
        "requested_download_symbols",
        "requested_symbols",
        "returned_symbols",
        "missing_symbols",
        "as_of_min",
        "as_of_max",
        "cache_hit",
        "provider_adjustment_note",
    ]
    if not rows:
        return pd.DataFrame(columns=columns)
    frame = pd.DataFrame(rows)
    for col in columns:
        if col not in frame:
            frame[col] = None
    return frame[columns]


def _sanitize_public_source_health(frame: pd.DataFrame) -> pd.DataFrame:
    """Remove local paths and credential-shaped provider diagnostics.

    Source-health rows are embedded in immutable public result artifacts and
    participate in their hashes. Local cache filenames are neither portable nor
    analytically meaningful; one such filename for ticker AVNS also matches the
    Aiven service-password prefix used by push protection.
    """

    sanitized = frame.copy()
    if "cache_path" in sanitized:
        stable_cache_references = {"", "disabled", "package-resource"}

        def sanitize_cache_path(value: object) -> object:
            if value is None or pd.isna(value):
                return value
            text = str(value)
            return text if text in stable_cache_references else PUBLIC_CACHE_REFERENCE

        sanitized["cache_path"] = sanitized["cache_path"].map(sanitize_cache_path)
    for column in sanitized.columns:
        dtype = sanitized[column].dtype
        if pd.api.types.is_object_dtype(dtype) or pd.api.types.is_string_dtype(dtype):
            sanitized[column] = sanitized[column].map(redact_credential_like_text)
    return sanitized


def _candidate_universe(config: RunConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    refresh_requested = config.universe_source_mode == "refresh" or config.universe_profile in {
        "extended_current",
        "aggressive_stock_only",
    }
    if refresh_requested:
        result = build_public_universe_frame(
            cache_dir=config.cache_dir / "universe",
            retry_count=config.retry_count,
            retry_backoff_seconds=config.retry_backoff_seconds,
            user_agent=config.sec_user_agent,
        )
        data_sources = result.data_sources.drop(
            columns=["tradable_universe_approved"],
            errors="ignore",
        ).copy()
        data_sources["universe_profile"] = config.universe_profile
        data_sources["universe_source_mode"] = "refresh"
        data_sources["point_in_time_universe"] = False
        return result.frame, data_sources
    frame = universe_frame_for_symbols(config.universe)
    source_name = (
        "packaged-default-universe"
        if list(config.universe) == list(DEFAULT_UNIVERSE)
        else "user-supplied-universe"
    )
    return frame, pd.DataFrame(
        [
            {
                "source": source_name,
                "status": "loaded",
                "records": len(frame),
                "candidate_symbols": len(frame),
                "point_in_time_universe": False,
                "universe_provenance": source_name.replace("-", " "),
                "universe_profile": config.universe_profile,
                "universe_source_mode": config.universe_source_mode,
                "cache_path": "package-resource",
                "retries": 0,
                "note": None,
            }
        ]
    )


def _comparator_symbols(config: RunConfig) -> list[str]:
    """Symbols fetched only for benchmark/comparison charts, never holdings."""

    return list(config.comparison_benchmarks)


def _requested_symbols(config: RunConfig, candidate: pd.DataFrame) -> tuple[list[str], bool]:
    comparators = _comparator_symbols(config)
    comparator_set = set(comparators)
    candidate_symbols = [
        symbol
        for symbol in candidate["symbol"].tolist()
        if symbol not in comparator_set and not is_known_etf_symbol(symbol)
    ]
    symbols = list(dict.fromkeys([*comparators, *candidate_symbols]))
    if config.max_price_symbols is not None and len(symbols) > config.max_price_symbols:
        # The smoke-test cap may reduce stock coverage, but comparison series are
        # part of the output contract and must never be silently dropped.
        candidate_slots = max(0, config.max_price_symbols - len(comparators))
        keep = [*comparators, *candidate_symbols[:candidate_slots]]
        return keep, True
    return symbols, False


DATA_QUALITY_COLUMNS = [
    "symbol",
    "role",
    "price_source",
    "provider",
    "first_price_date",
    "last_price_date",
    "observation_count",
    "missing_ratio",
    "volume_missing_ratio",
    "latest_price",
    "volume_obs_count",
    "avg_share_volume_63d",
    "avg_dollar_volume_63d",
    "non_positive_price_observations",
    "max_abs_daily_return",
    "extreme_return_observations",
    "full_history_max_abs_daily_return",
    "full_history_extreme_return_observations",
    "stale_days",
    "exclusion_reason",
    "data_quality_status",
    "data_quality_pass",
    "data_quality_warning",
]

YFINANCE_DOWNLOAD_TIMEOUT_SECONDS = 15
YAHOO_CHART_TIMEOUT_SECONDS = 20
PRICE_CACHE_VERSION = 4


def _exclusion_status(reason: object) -> str:
    text = str(reason or "").strip().lower()
    if not text:
        return "pass"
    if "missing from price" in text:
        return "missing_price"
    if "missing_or_below_min_price" in text:
        return "below_minimum_price"
    if "insufficient price history" in text or "insufficient_history" in text:
        return "insufficient_history"
    if "excessive missing price" in text:
        return "excessive_missing_price"
    if "recent_price_coverage" in text:
        return "excessive_missing_price"
    if "recent_volume_coverage" in text:
        return "excessive_missing_volume"
    if "excessive missing volume" in text:
        return "excessive_missing_volume"
    if "non-positive price" in text:
        return "non_positive_price"
    if "extreme adjusted daily return" in text:
        return "extreme_return_anomaly"
    if "recent_extreme_return" in text:
        return "extreme_return_anomaly"
    if "provider adjustment" in text or "provider-adjustment" in text:
        return "provider_adjustment_incompatible"
    if "stale" in text:
        return "stale_price"
    if "minimum price" in text:
        return "below_minimum_price"
    if "missing volume" in text:
        return "missing_volume"
    if "dollar-volume" in text or "share-volume" in text:
        return "below_liquidity_floor"
    if "liquidity_requirement" in text or "share_volume_requirement" in text:
        return "below_liquidity_floor"
    if "benchmark" in text:
        return "insufficient_benchmark_history"
    if "etf" in text:
        return "known_etf_excluded"
    if "not in stock candidate" in text:
        return "not_in_stock_candidate_universe"
    return "excluded"


def _matching_column(frame: pd.DataFrame, symbol: str) -> str | None:
    normalized = normalize_symbol(symbol)
    return next(
        (column for column in frame.columns if normalize_symbol(str(column)) == normalized), None
    )


def _price_source_map(price_sources: pd.DataFrame) -> dict[str, str]:
    if price_sources.empty or "symbol" not in price_sources or "price_source" not in price_sources:
        return {}
    return {
        normalize_symbol(str(row["symbol"])): str(row["price_source"])
        for _, row in price_sources.dropna(subset=["symbol"]).iterrows()
    }


def build_data_quality_frame(
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    requested_symbols: Iterable[str],
    candidate: pd.DataFrame,
    config: RunConfig,
    *,
    provider: str,
    price_sources: pd.DataFrame | None = None,
    exclusions: pd.DataFrame | None = None,
    as_of: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Build auditable per-symbol price/volume quality diagnostics.

    The manifest separates hard price-integrity evidence from advisory
    volume/liquidity/provider-compatibility warnings so broad live runs can keep
    coverage without hiding source quality limitations.
    """

    requested = list(dict.fromkeys(normalize_symbol(symbol) for symbol in requested_symbols))
    if not requested:
        return pd.DataFrame(columns=DATA_QUALITY_COLUMNS)
    prices = prices.sort_index()
    volumes = volumes.reindex(index=prices.index)
    benchmark = normalize_symbol(config.benchmark)
    comparator_symbols = set(_comparator_symbols(config))
    candidate_symbols = (
        set(candidate["symbol"].map(normalize_symbol)) if "symbol" in candidate else set()
    )
    price_source_frame = price_sources if price_sources is not None else pd.DataFrame()
    source_by_symbol = _price_source_map(price_source_frame)
    exclusions_by_symbol: dict[str, object] = {}
    if (
        exclusions is not None
        and not exclusions.empty
        and {"symbol", "reason"}.issubset(exclusions.columns)
    ):
        exclusions_by_symbol = {
            normalize_symbol(str(row["symbol"])): row["reason"]
            for _, row in exclusions.dropna(subset=["symbol"]).iterrows()
        }
    data_as_of = pd.Timestamp(as_of).normalize() if as_of is not None else None
    if data_as_of is None and not prices.empty:
        data_as_of = pd.Timestamp(prices.dropna(how="all").index.max()).normalize()

    rows: list[dict[str, object]] = []
    for symbol in requested:
        price_column = _matching_column(prices, symbol)
        volume_column = _matching_column(volumes, symbol)
        price_series = (
            pd.to_numeric(prices[price_column], errors="coerce")
            if price_column is not None
            else pd.Series(index=prices.index, dtype=float)
        )
        volume_series = (
            pd.to_numeric(volumes[volume_column], errors="coerce")
            if volume_column is not None
            else pd.Series(index=prices.index, dtype=float)
        )
        valid_prices = price_series.dropna()
        valid_volumes = volume_series.dropna()
        first_price_date = valid_prices.index.min() if not valid_prices.empty else None
        last_price_date = valid_prices.index.max() if not valid_prices.empty else None
        latest_price = float(valid_prices.iloc[-1]) if not valid_prices.empty else np.nan
        stale_days = (
            (data_as_of - pd.Timestamp(last_price_date).normalize()).days
            if data_as_of is not None and last_price_date is not None
            else np.nan
        )
        quality_prices = price_series.tail(config.data_quality_lookback_days)
        quality_volumes = volume_series.tail(config.data_quality_lookback_days)
        tail_prices = price_series.tail(63)
        tail_volumes = volume_series.tail(63)
        avg_share_volume = float(tail_volumes.mean()) if not tail_volumes.dropna().empty else np.nan
        avg_dollar_volume = (
            float(tail_prices.mul(tail_volumes).mean())
            if not tail_prices.dropna().empty and not tail_volumes.dropna().empty
            else np.nan
        )
        missing_ratio = (
            float(quality_prices.isna().mean())
            if len(quality_prices.index) > 0 and price_column is not None
            else np.nan
        )
        volume_missing_ratio = (
            float(quality_volumes.isna().mean())
            if len(quality_volumes.index) > 0 and volume_column is not None
            else np.nan
        )
        non_positive_prices = int(quality_prices.le(0).fillna(False).sum())
        daily_returns = (
            quality_prices.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).abs()
        )
        max_abs_daily_return = (
            float(daily_returns.max()) if not daily_returns.dropna().empty else np.nan
        )
        extreme_return_observations = int(
            daily_returns.gt(config.max_extreme_daily_return).fillna(False).sum()
        )
        full_history_returns = (
            price_series.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).abs()
        )
        full_history_max_abs_daily_return = (
            float(full_history_returns.max()) if not full_history_returns.dropna().empty else np.nan
        )
        full_history_extreme_return_observations = int(
            full_history_returns.gt(config.max_extreme_daily_return).fillna(False).sum()
        )
        exclusion_reason = exclusions_by_symbol.get(symbol)
        price_source = source_by_symbol.get(
            symbol, "unavailable" if price_column is None else provider
        )
        if symbol in comparator_symbols:
            if symbol == benchmark:
                role = "benchmark"
            elif symbol == config.chart_benchmark:
                role = "chart_benchmark"
            else:
                role = "comparison_benchmark"
            status = (
                "benchmark_comparator_only"
                if len(valid_prices) >= 2
                else "insufficient_benchmark_history"
            )
        elif price_column is None or valid_prices.empty:
            role = "missing"
            status = "missing_price"
            exclusion_reason = exclusion_reason or "missing from price providers"
        elif exclusion_reason:
            role = "excluded"
            status = _exclusion_status(exclusion_reason)
        elif symbol not in candidate_symbols or is_known_etf_symbol(symbol):
            role = "excluded"
            exclusion_reason = "not in stock candidate universe"
            status = _exclusion_status(exclusion_reason)
        else:
            role = "candidate"
            status = "pass"
            if pd.notna(stale_days) and int(stale_days) > config.stale_after_days:
                status = "stale_price"
            elif "close-fallback" in price_source:
                status = "provider_adjustment_incompatible"
            elif len(valid_prices) < config.min_history_days:
                status = "insufficient_history"
            elif non_positive_prices > 0:
                status = "non_positive_price"
            elif pd.notna(missing_ratio) and missing_ratio > config.max_price_missing_ratio:
                status = "excessive_missing_price"
            elif pd.isna(latest_price) or latest_price < config.min_price:
                status = "below_minimum_price"
            elif valid_volumes.empty:
                status = "missing_volume"
            elif (
                (config.min_avg_dollar_volume > 0 or config.min_avg_volume > 0)
                and pd.notna(volume_missing_ratio)
                and volume_missing_ratio > config.max_volume_missing_ratio
            ):
                status = "excessive_missing_volume"
            elif int(tail_volumes.count()) < config.min_liquidity_observations:
                status = "insufficient_liquidity_observations"
            elif config.min_avg_volume > 0 and avg_share_volume < config.min_avg_volume:
                status = "below_liquidity_floor"
            elif (
                config.min_avg_dollar_volume > 0
                and avg_dollar_volume < config.discovery_min_avg_dollar_volume
            ):
                status = "below_liquidity_floor"
            elif extreme_return_observations > 0:
                status = "extreme_return_anomaly"
            if status != "pass":
                role = "excluded"
                exclusion_reason = exclusion_reason or status

        warning = (
            "pass"
            if status in {"pass", "benchmark_comparator_only"}
            else f"{status}: inspect source data before practical use"
        )

        rows.append(
            {
                "symbol": symbol,
                "role": role,
                "price_source": price_source,
                "provider": provider,
                "first_price_date": first_price_date.date().isoformat()
                if first_price_date is not None
                else None,
                "last_price_date": last_price_date.date().isoformat()
                if last_price_date is not None
                else None,
                "observation_count": int(valid_prices.count()),
                "missing_ratio": missing_ratio,
                "volume_missing_ratio": volume_missing_ratio,
                "latest_price": latest_price,
                "volume_obs_count": int(valid_volumes.count()),
                "avg_share_volume_63d": avg_share_volume,
                "avg_dollar_volume_63d": avg_dollar_volume,
                "non_positive_price_observations": non_positive_prices,
                "max_abs_daily_return": max_abs_daily_return,
                "extreme_return_observations": extreme_return_observations,
                "full_history_max_abs_daily_return": full_history_max_abs_daily_return,
                "full_history_extreme_return_observations": full_history_extreme_return_observations,
                "stale_days": int(stale_days) if pd.notna(stale_days) else np.nan,
                "exclusion_reason": exclusion_reason,
                "data_quality_status": status,
                "data_quality_pass": status in {"pass", "benchmark_comparator_only"},
                "data_quality_warning": warning,
            }
        )
    return pd.DataFrame(rows, columns=DATA_QUALITY_COLUMNS)


def _extract_yfinance(
    download: pd.DataFrame,
    symbols: Iterable[str],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if download.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    symbols = list(symbols)
    if isinstance(download.columns, pd.MultiIndex):
        lvl0 = set(map(str, download.columns.get_level_values(0)))
        if "Close" in lvl0 or "Adj Close" in lvl0:
            adjusted_key = "Adj Close" if "Adj Close" in lvl0 else "Close"
            prices = download[adjusted_key].copy()
            raw_closes = download["Close"].copy() if "Close" in lvl0 else prices.copy()
            volumes = (
                download["Volume"].copy() if "Volume" in lvl0 else pd.DataFrame(index=prices.index)
            )
            stock_splits = (
                download["Stock Splits"].copy()
                if "Stock Splits" in lvl0
                else pd.DataFrame(index=prices.index)
            )
        else:
            price_cols = {}
            raw_close_cols = {}
            volume_cols = {}
            split_cols = {}
            for symbol in symbols:
                if symbol in download.columns.get_level_values(0):
                    sub = download[symbol]
                    if "Adj Close" in sub:
                        price_cols[symbol] = sub["Adj Close"]
                    elif "Close" in sub:
                        price_cols[symbol] = sub["Close"]
                    if "Close" in sub:
                        raw_close_cols[symbol] = sub["Close"]
                    if "Volume" in sub:
                        volume_cols[symbol] = sub["Volume"]
                    if "Stock Splits" in sub:
                        split_cols[symbol] = sub["Stock Splits"]
            prices = pd.DataFrame(price_cols)
            raw_closes = pd.DataFrame(raw_close_cols)
            volumes = pd.DataFrame(volume_cols)
            stock_splits = pd.DataFrame(split_cols)
    else:
        adjusted = download.get("Adj Close", download.get("Close"))
        raw_close = download.get("Close", download.get("Adj Close"))
        volume = download.get("Volume")
        split = download.get("Stock Splits")
        prices = pd.DataFrame({symbols[0]: adjusted}, index=download.index)
        raw_closes = pd.DataFrame({symbols[0]: raw_close}, index=download.index)
        volumes = pd.DataFrame(
            {
                symbols[0]: (
                    volume if volume is not None else pd.Series(np.nan, index=download.index)
                )
            },
            index=download.index,
        )
        stock_splits = pd.DataFrame(
            {symbols[0]: (split if split is not None else pd.Series(0.0, index=download.index))},
            index=download.index,
        )
    prices.index = pd.to_datetime(prices.index).tz_localize(None)
    raw_closes.index = pd.to_datetime(raw_closes.index).tz_localize(None)
    volumes.index = pd.to_datetime(volumes.index).tz_localize(None)
    stock_splits.index = pd.to_datetime(stock_splits.index).tz_localize(None)
    prices = prices.dropna(axis=1, how="all")
    return (
        prices,
        raw_closes.reindex(index=prices.index, columns=prices.columns),
        volumes.reindex(index=prices.index, columns=prices.columns),
        stock_splits.reindex(index=prices.index, columns=prices.columns).fillna(0.0),
    )


def _chunks(items: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _price_cache_path(config: RunConfig, provider: str, symbols: list[str]) -> Path:
    key = json.dumps(
        {
            "provider": provider,
            "symbols": symbols,
            "start_date": config.start_date,
            "end_date": config.effective_end_date,
            "download_end_date": (
                _yfinance_download_end_date(config)
                if provider == "yfinance"
                else config.effective_end_date
            ),
            "auto_adjust": False,
            "cache_version": PRICE_CACHE_VERSION,
        },
        sort_keys=True,
    )
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
    return config.cache_dir / "prices" / f"{provider}_{digest}.json"


def _price_cache_component_paths(metadata_path: Path) -> dict[str, Path]:
    return {
        "metadata": metadata_path,
        "prices": metadata_path.with_suffix(".prices.csv"),
        "raw_closes": metadata_path.with_suffix(".raw_closes.csv"),
        "volumes": metadata_path.with_suffix(".volumes.csv"),
        "stock_splits": metadata_path.with_suffix(".stock_splits.csv"),
    }


def _utc_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _cache_created_at_is_fresh(created_at: object, config: RunConfig) -> bool:
    if config.refresh_market_data:
        return False
    created = _utc_timestamp(created_at)
    if created is None:
        return False
    age = datetime.now(UTC) - created
    return timedelta(0) <= age <= timedelta(hours=config.market_cache_max_age_hours)


def _single_file_cache_is_fresh(path: Path, config: RunConfig) -> bool:
    if config.refresh_market_data or not path.exists():
        return False
    try:
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    except OSError:
        return False
    age = datetime.now(UTC) - modified
    return timedelta(0) <= age <= timedelta(hours=config.market_cache_max_age_hours)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _atomic_write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(value)
    temporary.replace(path)


def _observed_as_of(prices: pd.DataFrame) -> str | None:
    observed = prices.dropna(how="all")
    if observed.empty:
        return None
    return pd.Timestamp(observed.index.max()).date().isoformat()


def _read_price_cache(
    metadata_path: Path,
    *,
    config: RunConfig,
    provider: str,
    symbols: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame] | None:
    paths = _price_cache_component_paths(metadata_path)
    if not all(path.exists() for path in paths.values()):
        return None
    try:
        metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
        if (
            metadata.get("version") != PRICE_CACHE_VERSION
            or metadata.get("provider") != provider
            or metadata.get("symbols") != symbols
            or not _cache_created_at_is_fresh(metadata.get("createdAtUtc"), config)
        ):
            return None
        components = metadata.get("components")
        if not isinstance(components, dict):
            return None
        encoded_components: dict[str, bytes] = {}
        for name in ("prices", "raw_closes", "volumes", "stock_splits"):
            reference = components.get(name)
            if not isinstance(reference, dict):
                return None
            if reference.get("file") != paths[name].name:
                return None
            encoded = paths[name].read_bytes()
            if reference.get("bytes") != len(encoded):
                return None
            if reference.get("sha256") != _sha256_bytes(encoded):
                return None
            encoded_components[name] = encoded

        prices = pd.read_csv(
            StringIO(encoded_components["prices"].decode("utf-8")),
            index_col=0,
            parse_dates=True,
        )
        raw_closes = pd.read_csv(
            StringIO(encoded_components["raw_closes"].decode("utf-8")),
            index_col=0,
            parse_dates=True,
        )
        volumes = pd.read_csv(
            StringIO(encoded_components["volumes"].decode("utf-8")),
            index_col=0,
            parse_dates=True,
        )
        stock_splits = pd.read_csv(
            StringIO(encoded_components["stock_splits"].decode("utf-8")),
            index_col=0,
            parse_dates=True,
        )
        returned_symbols = metadata.get("returnedSymbols")
        if not isinstance(returned_symbols, list) or not all(
            isinstance(symbol, str) for symbol in returned_symbols
        ):
            return None
        if prices.columns.tolist() != returned_symbols:
            return None
        raw_closes = raw_closes.reindex(index=prices.index, columns=returned_symbols)
        volumes = volumes.reindex(index=prices.index, columns=returned_symbols)
        stock_splits = stock_splits.reindex(
            index=prices.index,
            columns=returned_symbols,
        ).fillna(0.0)
        if metadata.get("observedAsOf") != _observed_as_of(prices):
            return None
    except Exception:
        return None
    metadata["checkedAtUtc"] = datetime.now(UTC).isoformat()
    try:
        _atomic_write_bytes(
            paths["metadata"],
            json.dumps(metadata, indent=2, sort_keys=True).encode("utf-8"),
        )
    except OSError:
        pass
    return prices, raw_closes, volumes, stock_splits


def _write_price_cache(
    metadata_path: Path,
    prices: pd.DataFrame,
    raw_closes: pd.DataFrame,
    volumes: pd.DataFrame,
    stock_splits: pd.DataFrame,
    *,
    provider: str,
    symbols: list[str],
) -> None:
    paths = _price_cache_component_paths(metadata_path)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    returned_symbols = [str(symbol) for symbol in prices.columns]
    normalized_prices = prices.reindex(columns=returned_symbols)
    normalized_raw_closes = raw_closes.reindex(
        index=normalized_prices.index,
        columns=returned_symbols,
    )
    normalized_volumes = volumes.reindex(
        index=normalized_prices.index,
        columns=returned_symbols,
    )
    normalized_stock_splits = stock_splits.reindex(
        index=normalized_prices.index,
        columns=returned_symbols,
    ).fillna(0.0)
    encoded_components = {
        "prices": normalized_prices.to_csv().encode("utf-8"),
        "raw_closes": normalized_raw_closes.to_csv().encode("utf-8"),
        "volumes": normalized_volumes.to_csv().encode("utf-8"),
        "stock_splits": normalized_stock_splits.to_csv().encode("utf-8"),
    }
    timestamp = datetime.now(UTC).isoformat()
    metadata = {
        "version": PRICE_CACHE_VERSION,
        "provider": provider,
        "symbols": [str(symbol) for symbol in symbols],
        "returnedSymbols": returned_symbols,
        "format": "csv+json",
        "createdAtUtc": timestamp,
        "checkedAtUtc": timestamp,
        "observedAsOf": _observed_as_of(normalized_prices),
        "components": {
            name: {
                "file": paths[name].name,
                "sha256": _sha256_bytes(encoded),
                "bytes": len(encoded),
            }
            for name, encoded in encoded_components.items()
        },
    }
    for name, encoded in encoded_components.items():
        _atomic_write_bytes(paths[name], encoded)
    _atomic_write_bytes(
        paths["metadata"],
        json.dumps(metadata, indent=2, sort_keys=True).encode("utf-8"),
    )


def _yfinance_download_end_date(config: RunConfig) -> str | None:
    """Return the yfinance `end` argument for an inclusive user end date.

    yfinance treats `end` as an exclusive bound. The lab's CLI/config dates are
    user-facing analysis dates, and the offline/Stooq/FinanceDataReader paths
    already treat an explicit `end_date` as inclusive. Add one calendar day only
    for explicit yfinance downloads so the requested trading session can be
    included when the provider has it available.
    """

    if config.end_date is None:
        return None
    return (pd.Timestamp(config.end_date).date() + timedelta(days=1)).isoformat()


def _stooq_cache_path(config: RunConfig, symbol: str) -> Path:
    safe = symbol.replace("/", "_").replace("-", "_")
    return (
        config.cache_dir
        / "prices"
        / "stooq"
        / f"{safe}_{config.start_date}_{config.effective_end_date}.csv"
    )


def _yahoo_chart_cache_path(config: RunConfig, symbol: str) -> Path:
    safe = symbol.replace("/", "_").replace("-", "_").replace("^", "INDEX_")
    return (
        config.cache_dir
        / "prices"
        / "yahoo_chart"
        / f"{safe}_{config.start_date}_{config.effective_end_date}.csv"
    )


def _nasdaq_cache_path(config: RunConfig, symbol: str) -> Path:
    safe = symbol.replace("/", "_").replace("-", "_").replace("^", "INDEX_")
    return (
        config.cache_dir
        / "prices"
        / "nasdaq"
        / f"{safe}_{config.start_date}_{config.effective_end_date}.csv"
    )


def _finance_datareader_cache_path(config: RunConfig, symbol: str) -> Path:
    safe = symbol.replace("/", "_").replace("-", "_")
    return (
        config.cache_dir
        / "prices"
        / "finance_datareader"
        / f"{safe}_{config.start_date}_{config.effective_end_date}.csv"
    )


def _repair_yfinance_latest_session(
    symbols: list[str],
    config: RunConfig,
    frames: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame],
) -> tuple[tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame], dict[str, object]]:
    """Retry missing target quotes with a bounded one-session provider request.

    Yahoo can return the last session's OHLCV row with null Close/Adj Close in
    long-history requests while the one-session endpoint has the actual close.
    Preserve all historical rows and only accept a complete adjusted/raw/volume
    quote for the already resolved target. No price is inferred or carried forward.
    """
    if not config.require_current_session or config.end_date is None:
        return frames, {}
    import yfinance as yf

    target = pd.Timestamp(config.end_date).normalize()
    prices, raw_closes, volumes, splits = (frame.copy() for frame in frames)
    index = prices.index.union(pd.DatetimeIndex([target])).sort_values()
    prices, raw_closes, volumes, splits = (
        frame.reindex(index=index, columns=symbols) for frame in (prices, raw_closes, volumes, splits)
    )
    def missing_symbols() -> list[str]:
        return [symbol for symbol in symbols if not all(
            pd.notna(frame.at[target, symbol])
            and np.isfinite(frame.at[target, symbol])
            and frame.at[target, symbol] > 0
            for frame in (prices, raw_closes, volumes)
        )]

    pending = missing_symbols()
    originally_missing = len(pending)
    attempts = 0
    error_types: list[str] = []
    for attempt in range(config.retry_count + 1):
        if not pending:
            break
        attempts += 1
        try:
            raw = yf.download(
                tickers=pending, start=config.end_date, end=_yfinance_download_end_date(config),
                auto_adjust=False, group_by="column", progress=False, threads=False,
                actions=True, timeout=YFINANCE_DOWNLOAD_TIMEOUT_SECONDS,
            )
            repaired = _extract_yfinance(raw, pending)
            # A missing adjusted-close field is not evidence of an adjusted price.
            has_adjusted = (
                any("Adj Close" in level for level in raw.columns.to_list())
                if isinstance(raw.columns, pd.MultiIndex)
                else "Adj Close" in raw.columns
            )
            if has_adjusted:
                for symbol in pending:
                    if not all(
                        symbol in frame and target in frame.index
                        and pd.notna(frame.at[target, symbol])
                        and np.isfinite(frame.at[target, symbol])
                        and frame.at[target, symbol] > 0
                        for frame in repaired[:3]
                    ):
                        continue
                    for destination, source in zip((prices, raw_closes, volumes, splits), repaired):
                        destination.at[target, symbol] = source.at[target, symbol]
        except Exception as error:
            # The full-history result survives a transient latest-session error.
            error_types.append(type(error).__name__)
        pending = missing_symbols()
        if pending and attempt < config.retry_count:
            time.sleep(config.retry_backoff_seconds)
    prices = prices.dropna(axis=1, how="all")
    columns = prices.columns
    return (prices, raw_closes.reindex(columns=columns), volumes.reindex(columns=columns),
            splits.reindex(columns=columns).fillna(0.0)), {
        "latestSessionTarget": config.end_date,
        "latestSessionAttempts": attempts,
        "latestSessionRepairedCount": originally_missing - len(pending),
        "latestSessionMissingSymbols": pending,
        "latestSessionErrorTypes": error_types,
    }


def _download_yfinance_chunk(
    symbols: list[str],
    config: RunConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, object]]:
    cache_path = _price_cache_path(config, "yfinance", symbols)
    cached = _read_price_cache(
        cache_path,
        config=config,
        provider="yfinance",
        symbols=symbols,
    )
    if cached is not None:
        (prices, raw_closes, volumes, stock_splits), latest_diagnostics = (
            _repair_yfinance_latest_session(symbols, config, cached)
        )
        return (
            prices,
            raw_closes,
            volumes,
            stock_splits,
            {
                "status": "cache_hit",
                "retries": 0,
                "error": None,
                "cache_path": str(cache_path),
                "cache_format": "csv+json",
                "latest_session": latest_diagnostics,
            },
        )

    import yfinance as yf  # type: ignore

    last_error = None
    for attempt in range(config.retry_count + 1):
        try:
            raw = yf.download(
                tickers=symbols,
                start=config.start_date,
                end=_yfinance_download_end_date(config),
                auto_adjust=False,
                group_by="column",
                progress=False,
                threads=False,
                actions=True,
                timeout=YFINANCE_DOWNLOAD_TIMEOUT_SECONDS,
            )
            prices, raw_closes, volumes, stock_splits = _extract_yfinance(raw, symbols)
            (prices, raw_closes, volumes, stock_splits), latest_diagnostics = (
                _repair_yfinance_latest_session(
                    symbols, config, (prices, raw_closes, volumes, stock_splits)
                )
            )
            _write_price_cache(
                cache_path,
                prices,
                raw_closes,
                volumes,
                stock_splits,
                provider="yfinance",
                symbols=symbols,
            )
            return (
                prices,
                raw_closes,
                volumes,
                stock_splits,
                {
                    "status": "fetched",
                    "retries": attempt,
                    "error": None,
                    "cache_path": str(cache_path),
                    "cache_format": "csv+json",
                    "latest_session": latest_diagnostics,
                },
            )
        except Exception as exc:  # pragma: no cover - network dependent
            last_error = exc
            if attempt < config.retry_count:
                time.sleep(config.retry_backoff_seconds)
    return (
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        {
            "status": "failed",
            "retries": config.retry_count,
            "error": str(last_error),
            "cache_path": str(cache_path),
            "cache_format": "csv+json",
        },
    )


def _download_yfinance(
    symbols: list[str],
    config: RunConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    price_frames: list[pd.DataFrame] = []
    raw_close_frames: list[pd.DataFrame] = []
    volume_frames: list[pd.DataFrame] = []
    split_frames: list[pd.DataFrame] = []
    rows: list[dict[str, object]] = []
    for chunk in _chunks(symbols, config.price_chunk_size):
        prices, raw_closes, volumes, stock_splits, status = _download_yfinance_chunk(chunk, config)
        price_frames.append(prices)
        raw_close_frames.append(raw_closes)
        volume_frames.append(volumes)
        split_frames.append(stock_splits)
        returned = [symbol for symbol in chunk if symbol in prices.columns]
        missing = [symbol for symbol in chunk if symbol not in prices.columns]
        rows.append(
            {
                "source": "yfinance-adjusted-daily",
                "status": status["status"],
                "records": len(prices.columns),
                "requested_price_symbols": len(chunk),
                "requested_symbols": ",".join(chunk),
                "returned_symbols": ",".join(returned),
                "missing_symbols": ",".join(missing),
                "as_of_min": (
                    str(prices.dropna(how="all").index.min().date()) if not prices.empty else None
                ),
                "as_of_max": (
                    str(prices.dropna(how="all").index.max().date()) if not prices.empty else None
                ),
                "cache_hit": status["status"] == "cache_hit",
                "cache_path": status.get("cache_path"),
                "retries": status["retries"],
                "error": status["error"],
                "provider_adjustment_note": (
                    "yfinance Adj Close is used for factor returns; raw Close and raw Volume "
                    "are retained separately for historical dollar-volume evidence."
                ),
                "note": json.dumps(status.get("latest_session", {}), sort_keys=True),
            }
        )
    prices = pd.concat(price_frames, axis=1) if price_frames else pd.DataFrame()
    raw_closes = (
        pd.concat(raw_close_frames, axis=1)
        if raw_close_frames
        else pd.DataFrame(index=prices.index)
    )
    volumes = (
        pd.concat(volume_frames, axis=1) if volume_frames else pd.DataFrame(index=prices.index)
    )
    stock_splits = (
        pd.concat(split_frames, axis=1) if split_frames else pd.DataFrame(index=prices.index)
    )
    prices = prices.loc[:, ~prices.columns.duplicated()].sort_index()
    raw_closes = raw_closes.loc[:, ~raw_closes.columns.duplicated()].reindex(
        index=prices.index,
        columns=prices.columns,
    )
    volumes = volumes.loc[:, ~volumes.columns.duplicated()].reindex(
        index=prices.index, columns=prices.columns
    )
    stock_splits = (
        stock_splits.loc[:, ~stock_splits.columns.duplicated()]
        .reindex(
            index=prices.index,
            columns=prices.columns,
        )
        .fillna(0.0)
    )
    return prices, raw_closes, volumes, stock_splits, pd.DataFrame(rows)


def _unix_seconds_for_date(value: str, *, add_days: int = 0) -> int:
    timestamp = pd.Timestamp(value).normalize() + pd.Timedelta(days=add_days)
    return int(timestamp.tz_localize(UTC).timestamp())


def _yahoo_chart_symbol(symbol: str) -> str:
    # Yahoo chart expects Yahoo-style tickers. The project stores normalized
    # tickers, so only slash-class shares need translation back to Yahoo's dash
    # form here.
    return quote(symbol.replace("/", "-"), safe="")


def _frame_from_yahoo_chart_payload(
    payload: dict[str, object], symbol: str
) -> tuple[pd.DataFrame | None, str | None]:
    chart = payload.get("chart")
    if not isinstance(chart, dict):
        return None, "invalid Yahoo chart payload: missing chart object"
    errors = chart.get("error")
    if errors:
        return None, f"Yahoo chart error: {errors}"
    results = chart.get("result")
    if not isinstance(results, list) or not results:
        return None, "empty Yahoo chart response"
    result = results[0]
    if not isinstance(result, dict):
        return None, "invalid Yahoo chart response"
    timestamps = result.get("timestamp")
    indicators = result.get("indicators")
    if not isinstance(timestamps, list) or not timestamps or not isinstance(indicators, dict):
        return None, "empty Yahoo chart timestamp/indicator response"
    quotes = indicators.get("quote")
    adjcloses = indicators.get("adjclose")
    if not isinstance(quotes, list) or not quotes or not isinstance(quotes[0], dict):
        return None, "Yahoo chart response missing quote data"
    if not isinstance(adjcloses, list) or not adjcloses or not isinstance(adjcloses[0], dict):
        return None, "Yahoo chart response missing adjusted close data"
    adjusted = adjcloses[0].get("adjclose")
    if not isinstance(adjusted, list) or not adjusted:
        return None, "Yahoo chart response missing adjusted close values"
    volume = quotes[0].get("volume", [])
    if not isinstance(volume, list):
        volume = []
    dates = pd.to_datetime(timestamps, unit="s", utc=True).tz_convert(None).normalize()
    frame = pd.DataFrame(
        {
            "Date": dates,
            "Close": pd.to_numeric(pd.Series(adjusted), errors="coerce"),
            "Volume": pd.to_numeric(pd.Series(volume), errors="coerce"),
        }
    )
    frame = frame.dropna(subset=["Date", "Close"])
    if frame.empty:
        return None, f"Yahoo chart response for {symbol} had no numeric adjusted close rows"
    return frame, None


def _download_yahoo_chart_symbol(
    symbol: str,
    config: RunConfig,
) -> tuple[pd.Series | None, pd.Series | None, str | None, str, str, int]:
    cache_path = _yahoo_chart_cache_path(config, symbol)
    if _single_file_cache_is_fresh(cache_path, config):
        try:
            frame = pd.read_csv(cache_path)
            price, volume, error = _validated_provider_close_volume(
                frame, symbol, "Yahoo chart cache"
            )
            if price is None:
                return None, None, error, "cache_hit_invalid", str(cache_path), 0
            return price, volume, None, "cache_hit", str(cache_path), 0
        except Exception as exc:
            return (
                None,
                None,
                f"invalid Yahoo chart cache: {exc}",
                "cache_hit_invalid",
                str(cache_path),
                0,
            )

    params = urlencode(
        {
            "period1": _unix_seconds_for_date(config.start_date),
            "period2": _unix_seconds_for_date(config.effective_end_date, add_days=1),
            "interval": "1d",
            "events": "history",
            "includeAdjustedClose": "true",
        }
    )
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{_yahoo_chart_symbol(symbol)}?{params}"
    )
    last_error = None
    for attempt in range(config.retry_count + 1):
        try:
            with urlopen(
                Request(url, headers={"User-Agent": "factor/0.1"}),
                timeout=YAHOO_CHART_TIMEOUT_SECONDS,
            ) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
            frame, error = _frame_from_yahoo_chart_payload(payload, symbol)
            if frame is None:
                return None, None, error, "failed", str(cache_path), attempt
            price, volume, error = _validated_provider_close_volume(
                frame, symbol, "Yahoo chart response"
            )
            if price is None:
                return None, None, error, "failed", str(cache_path), attempt
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            frame.to_csv(cache_path, index=False)
            return price, volume, None, "fetched", str(cache_path), attempt
        except Exception as exc:  # pragma: no cover - network dependent
            last_error = exc
            if attempt < config.retry_count:
                time.sleep(config.retry_backoff_seconds)
    return None, None, str(last_error), "failed", str(cache_path), config.retry_count


def _apply_yahoo_chart_fallback(
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    symbols: list[str],
    config: RunConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    missing_all = _fallback_candidate_symbols(prices, volumes, symbols, config)
    limit = (
        len(missing_all)
        if config.yahoo_chart_fallback_limit is None
        else config.yahoo_chart_fallback_limit
    )
    missing = missing_all[:limit]
    rows = []
    for symbol in missing:
        price, volume, error, status, cache_path, retries = _download_yahoo_chart_symbol(
            symbol, config
        )
        if price is None:
            rows.append(
                {
                    "source": "yahoo-chart-adjusted-daily-fallback",
                    "symbol": symbol,
                    "status": "failed" if not status.startswith("cache") else status,
                    "records": 0,
                    "requested_price_symbols": 1,
                    "requested_symbols": symbol,
                    "returned_symbols": "",
                    "missing_symbols": symbol,
                    "cache_hit": status.startswith("cache"),
                    "cache_path": cache_path,
                    "retries": retries,
                    "error": error,
                    "provider_adjustment_note": "Yahoo chart fallback returned no usable adjusted-close series.",
                    "note": symbol,
                }
            )
            continue
        prices = prices.drop(columns=[symbol], errors="ignore").join(price, how="outer")
        volumes = volumes.drop(columns=[symbol], errors="ignore").join(volume, how="outer")
        rows.append(
            {
                "source": "yahoo-chart-adjusted-daily-fallback",
                "symbol": symbol,
                "status": status,
                "records": 1,
                "requested_price_symbols": 1,
                "requested_symbols": symbol,
                "returned_symbols": symbol,
                "missing_symbols": "",
                "as_of_min": str(price.dropna().index.min().date())
                if not price.dropna().empty
                else None,
                "as_of_max": str(price.dropna().index.max().date())
                if not price.dropna().empty
                else None,
                "cache_hit": status == "cache_hit",
                "cache_path": cache_path,
                "retries": retries,
                "error": None,
                "provider_adjustment_note": "Yahoo chart adjusted-close fallback; used when yfinance bulk data was stale, sparse, or missing.",
                "note": f"{symbol}; adjusted close from Yahoo chart endpoint",
            }
        )
    return prices.sort_index(), volumes.reindex(index=prices.sort_index().index), pd.DataFrame(rows)


def _parse_nasdaq_number(value: object) -> float:
    text = str(value or "").strip().replace("$", "").replace(",", "")
    if not text or text.lower() in {"n/a", "nan", "none", "--"}:
        return np.nan
    try:
        return float(text)
    except ValueError:
        return np.nan


def _frame_from_nasdaq_payload(
    payload: dict[str, object], symbol: str
) -> tuple[pd.DataFrame | None, str | None]:
    data = payload.get("data")
    if not isinstance(data, dict):
        return None, "invalid Nasdaq payload: missing data object"
    table = data.get("tradesTable")
    if not isinstance(table, dict):
        return None, "invalid Nasdaq payload: missing tradesTable"
    rows = table.get("rows")
    if not isinstance(rows, list) or not rows:
        return None, "empty Nasdaq historical response"
    parsed_rows: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        parsed_rows.append(
            {
                "Date": pd.to_datetime(row.get("date"), errors="coerce"),
                "Close": _parse_nasdaq_number(row.get("close")),
                "Volume": _parse_nasdaq_number(row.get("volume")),
            }
        )
    frame = pd.DataFrame(parsed_rows).dropna(subset=["Date", "Close"])
    if frame.empty:
        return None, f"Nasdaq historical response for {symbol} had no numeric close rows"
    return frame.sort_values("Date"), None


def _download_nasdaq_symbol(
    symbol: str,
    config: RunConfig,
) -> tuple[pd.Series | None, pd.Series | None, str | None, str, str, int]:
    cache_path = _nasdaq_cache_path(config, symbol)
    if _single_file_cache_is_fresh(cache_path, config):
        try:
            frame = pd.read_csv(cache_path)
            price, volume, error = _validated_provider_close_volume(frame, symbol, "Nasdaq cache")
            if price is None:
                return None, None, error, "cache_hit_invalid", str(cache_path), 0
            return price, volume, None, "cache_hit", str(cache_path), 0
        except Exception as exc:
            return (
                None,
                None,
                f"invalid Nasdaq cache: {exc}",
                "cache_hit_invalid",
                str(cache_path),
                0,
            )

    params = urlencode(
        {
            "assetclass": "stocks",
            "fromdate": config.start_date,
            "todate": config.effective_end_date,
            "limit": "9999",
        }
    )
    url = f"https://api.nasdaq.com/api/quote/{quote(symbol, safe='')}/historical?{params}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.nasdaq.com",
        "Referer": "https://www.nasdaq.com/",
    }
    last_error = None
    for attempt in range(config.retry_count + 1):
        try:
            with urlopen(
                Request(url, headers=headers), timeout=YAHOO_CHART_TIMEOUT_SECONDS
            ) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
            frame, error = _frame_from_nasdaq_payload(payload, symbol)
            if frame is None:
                return None, None, error, "failed", str(cache_path), attempt
            price, volume, error = _validated_provider_close_volume(
                frame, symbol, "Nasdaq historical response"
            )
            if price is None:
                return None, None, error, "failed", str(cache_path), attempt
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            frame.to_csv(cache_path, index=False)
            return price, volume, None, "fetched", str(cache_path), attempt
        except Exception as exc:  # pragma: no cover - network dependent
            last_error = exc
            if attempt < config.retry_count:
                time.sleep(config.retry_backoff_seconds)
    return None, None, str(last_error), "failed", str(cache_path), config.retry_count


def _repair_nasdaq_composite_gaps(
    prices: pd.DataFrame,
    raw_closes: pd.DataFrame,
    config: RunConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Recover missing ^IXIC observations from the publisher's COMP index.

    Unlike stock/ETF closes, this price index has no split/dividend adjustment.
    Require matching surrounding observations before accepting any missing cell;
    never overwrite Yahoo observations or infer a price/volume through a gap.
    """
    symbol = "^IXIC"
    if (not config.require_current_session or config.end_date is None
            or symbol not in config.comparison_benchmarks or symbol not in prices):
        return prices, raw_closes, pd.DataFrame()
    series = pd.to_numeric(prices[symbol], errors="coerce")
    valid = series.where(np.isfinite(series) & series.gt(0)).dropna()
    if valid.empty:
        return prices, raw_closes, pd.DataFrame()
    window = series.loc[valid.index.min():pd.Timestamp(config.end_date)]
    missing = window.index[~(np.isfinite(window) & window.gt(0))]
    if missing.empty:
        return prices, raw_closes, pd.DataFrame()
    # Bound recovery work. A broadly invalid series remains unavailable.
    if len(missing) > 31:
        return prices, raw_closes, _source_frame([{
            "source": "nasdaq-composite-history-repair", "status": "failed", "records": 0,
            "error": "more than 31 missing index sessions; bounded repair refused",
        }])
    start = max(pd.Timestamp(config.start_date), missing.min() - pd.Timedelta(days=7))
    end = min(pd.Timestamp(config.end_date), missing.max() + pd.Timedelta(days=7))
    params = urlencode({"assetclass": "index", "fromdate": str(start.date()),
                        "todate": str(end.date()), "limit": "9999"})
    url = f"https://api.nasdaq.com/api/quote/COMP/historical?{params}"
    error = "index history not received"
    for attempt in range(config.retry_count + 1):
        try:
            request = Request(url, headers={"User-Agent": "Mozilla/5.0",
                "Accept": "application/json", "Origin": "https://www.nasdaq.com",
                "Referer": "https://www.nasdaq.com/"})
            with urlopen(request, timeout=YAHOO_CHART_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if (payload.get("data", {}).get("symbol") != "COMP"
                    or payload.get("status", {}).get("rCode") != 200):
                raise ValueError("Nasdaq response is not successful COMP index history")
            frame, parse_error = _frame_from_nasdaq_payload(payload, "COMP")
            if frame is None:
                raise ValueError(parse_error)
            if frame["Date"].duplicated().any():
                raise ValueError("duplicate dates in COMP index history")
            official = frame.set_index("Date")["Close"].loc[start:end]
            overlap = official.index.intersection(valid.index)
            if len(overlap) < 2 or not np.allclose(
                official.loc[overlap], valid.loc[overlap], rtol=1e-7, atol=0.01
            ):
                raise ValueError("COMP history does not match adjacent Yahoo index observations")
            recovered = official.reindex(missing)
            if not (np.isfinite(recovered) & recovered.gt(0)).all():
                raise ValueError("COMP history does not cover every missing index session")
            repaired = prices.copy()
            raw = raw_closes.reindex(index=prices.index, columns=prices.columns).copy()
            repaired.loc[missing, symbol] = recovered
            raw.loc[missing, symbol] = recovered
            return repaired, raw, _source_frame([{
                "source": "nasdaq-composite-history-repair", "status": "fetched",
                "records": len(missing), "requested_symbols": symbol,
                "returned_symbols": symbol, "retries": attempt,
                "as_of_min": str(missing.min().date()), "as_of_max": str(missing.max().date()),
                "provider_adjustment_note": "Official COMP price-index close; no security adjustment or volume inference.",
                "note": json.dumps({"url": url, "fetchedAtUtc": datetime.now(UTC).isoformat(),
                    "overlapObservations": len(overlap),
                    "repairedCloses": {str(day.date()): float(value)
                                       for day, value in recovered.items()}}),
            }])
        except Exception as exc:
            error = str(exc)
            if attempt < config.retry_count:
                time.sleep(config.retry_backoff_seconds)
    return prices, raw_closes, _source_frame([{
        "source": "nasdaq-composite-history-repair", "status": "failed", "records": 0,
        "requested_symbols": symbol, "missing_symbols": symbol,
        "retries": config.retry_count, "error": error,
    }])


def _apply_nasdaq_latest_repair(
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    symbols: list[str],
    config: RunConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    fallback_all = [
        symbol
        for symbol in _fallback_candidate_symbols(prices, volumes, symbols, config)
        if symbol in prices.columns
        and not pd.to_numeric(prices[symbol], errors="coerce").dropna().empty
    ]
    limit = (
        len(fallback_all) if config.nasdaq_fallback_limit is None else config.nasdaq_fallback_limit
    )
    candidates = fallback_all[:limit]
    rows = []
    for symbol in candidates:
        before_price_full = pd.to_numeric(prices[symbol], errors="coerce").rename(symbol)
        before_price = before_price_full.dropna()
        before_last = before_price.index.max() if not before_price.empty else None
        before_volume = (
            pd.to_numeric(volumes[symbol], errors="coerce").rename(symbol)
            if symbol in volumes.columns
            else pd.Series(index=before_price_full.index, dtype=float, name=symbol)
        )
        price, volume, error, status, cache_path, retries = _download_nasdaq_symbol(symbol, config)
        if price is None:
            rows.append(
                {
                    "source": "nasdaq-latest-close-repair",
                    "symbol": symbol,
                    "status": "failed" if not status.startswith("cache") else status,
                    "records": 0,
                    "requested_price_symbols": 1,
                    "requested_symbols": symbol,
                    "returned_symbols": "",
                    "missing_symbols": symbol,
                    "cache_hit": status.startswith("cache"),
                    "cache_path": cache_path,
                    "retries": retries,
                    "error": error,
                    "provider_adjustment_note": "Nasdaq latest-close repair returned no usable close rows.",
                    "note": symbol,
                }
            )
            continue
        tail_price = (
            price[price.index > before_last].dropna()
            if before_last is not None
            else pd.Series(dtype=float, name=symbol)
        )
        tail_volume = (
            volume.reindex(tail_price.index)
            if volume is not None and not tail_price.empty
            else pd.Series(index=tail_price.index, dtype=float, name=symbol)
        )
        repaired_price = before_price_full.combine_first(tail_price).sort_index().rename(symbol)
        repaired_volume = before_volume.combine_first(tail_volume).sort_index().rename(symbol)
        after_last = (
            repaired_price.dropna().index.max() if not repaired_price.dropna().empty else None
        )
        added_dates = list(tail_price.index)
        if (
            after_last is None
            or before_last is None
            or after_last <= before_last
            or not added_dates
        ):
            rows.append(
                {
                    "source": "nasdaq-latest-close-repair",
                    "symbol": symbol,
                    "status": "no_newer_rows",
                    "records": 0,
                    "requested_price_symbols": 1,
                    "requested_symbols": symbol,
                    "returned_symbols": "",
                    "missing_symbols": symbol,
                    "as_of_min": str(price.dropna().index.min().date())
                    if not price.dropna().empty
                    else None,
                    "as_of_max": str(price.dropna().index.max().date())
                    if not price.dropna().empty
                    else None,
                    "cache_hit": status == "cache_hit",
                    "cache_path": cache_path,
                    "retries": retries,
                    "error": None,
                    "provider_adjustment_note": "Nasdaq response did not extend the existing adjusted-price history.",
                    "note": f"{symbol}; no fresher Nasdaq rows than existing series",
                }
            )
            continue
        prices = prices.drop(columns=[symbol], errors="ignore").join(repaired_price, how="outer")
        volumes = volumes.drop(columns=[symbol], errors="ignore").join(repaired_volume, how="outer")
        rows.append(
            {
                "source": "nasdaq-latest-close-repair",
                "symbol": symbol,
                "status": status,
                "records": int(len(added_dates)),
                "requested_price_symbols": 1,
                "requested_symbols": symbol,
                "returned_symbols": symbol,
                "missing_symbols": "",
                "as_of_min": str(repaired_price.dropna().index.min().date()),
                "as_of_max": str(repaired_price.dropna().index.max().date()),
                "cache_hit": status == "cache_hit",
                "cache_path": cache_path,
                "retries": retries,
                "error": None,
                "provider_adjustment_note": (
                    "Nasdaq historical close filled only dates missing from an existing Yahoo adjusted-price series; "
                    "historical adjusted prices were preserved."
                ),
                "note": f"{symbol}; added {len(added_dates)} newer close row(s) after {before_last.date()}",
            }
        )
    return prices.sort_index(), volumes.reindex(index=prices.sort_index().index), pd.DataFrame(rows)


def _stooq_symbol(symbol: str) -> str:
    return quote(symbol.lower().replace("/", ".").replace("-", ".") + ".us")


def _validated_provider_close_volume(
    frame: pd.DataFrame,
    symbol: str,
    provider_name: str,
) -> tuple[pd.Series | None, pd.Series | None, str | None]:
    if frame.empty or "Date" not in frame or "Close" not in frame:
        return None, None, f"empty {provider_name} payload"
    parsed = frame.copy()
    parsed["Date"] = pd.to_datetime(parsed["Date"], errors="coerce")
    parsed["Close"] = pd.to_numeric(parsed["Close"], errors="coerce")
    if "Volume" in parsed:
        parsed["Volume"] = pd.to_numeric(parsed["Volume"], errors="coerce")
    else:
        parsed["Volume"] = np.nan
    parsed = parsed.dropna(subset=["Date", "Close"]).set_index("Date").sort_index()
    if parsed.empty:
        return None, None, f"invalid {provider_name} payload: no numeric close prices"
    return (
        parsed["Close"].rename(symbol),
        parsed["Volume"].rename(symbol),
        None,
    )


def _download_stooq_symbol(
    symbol: str,
    config: RunConfig,
) -> tuple[pd.Series | None, pd.Series | None, str | None, str, str, int]:
    cache_path = _stooq_cache_path(config, symbol)
    if _single_file_cache_is_fresh(cache_path, config):
        try:
            frame = pd.read_csv(cache_path)
            price, volume, error = _validated_provider_close_volume(frame, symbol, "stooq cache")
            if price is None:
                return None, None, error, "cache_hit_invalid", str(cache_path), 0
            return price, volume, None, "cache_hit", str(cache_path), 0
        except Exception as exc:
            return (
                None,
                None,
                f"invalid stooq cache: {exc}",
                "cache_hit_invalid",
                str(cache_path),
                0,
            )

    start = config.start_date.replace("-", "")
    end = config.effective_end_date.replace("-", "")
    url = f"https://stooq.com/q/d/l/?s={_stooq_symbol(symbol)}&d1={start}&d2={end}&i=d"
    last_error = None
    for attempt in range(config.retry_count + 1):
        try:
            with urlopen(
                Request(url, headers={"User-Agent": "factor/0.1"}), timeout=20
            ) as response:
                text = response.read().decode("utf-8", errors="replace")
            frame = pd.read_csv(StringIO(text))
            price, volume, error = _validated_provider_close_volume(frame, symbol, "stooq response")
            if price is None:
                return None, None, error, "failed", str(cache_path), attempt
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            frame.to_csv(cache_path, index=False)
            return price, volume, None, "fetched", str(cache_path), attempt
        except Exception as exc:  # pragma: no cover - network dependent
            last_error = exc
            if attempt < config.retry_count:
                time.sleep(config.retry_backoff_seconds)
    return None, None, str(last_error), "failed", str(cache_path), config.retry_count


def _apply_stooq_fallback(
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    symbols: list[str],
    config: RunConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    missing_all = _fallback_candidate_symbols(prices, volumes, symbols, config)
    limit = len(missing_all) if config.stooq_fallback_limit is None else config.stooq_fallback_limit
    missing = missing_all[:limit]
    rows = []
    for symbol in missing:
        price, volume, error, status, cache_path, retries = _download_stooq_symbol(symbol, config)
        if price is None:
            rows.append(
                {
                    "source": "stooq-daily-close-fallback",
                    "symbol": symbol,
                    "status": "failed" if not status.startswith("cache") else status,
                    "records": 0,
                    "requested_price_symbols": 1,
                    "requested_symbols": symbol,
                    "returned_symbols": "",
                    "missing_symbols": symbol,
                    "cache_hit": status.startswith("cache"),
                    "cache_path": cache_path,
                    "retries": retries,
                    "error": error,
                    "provider_adjustment_note": "Stooq fallback returned no usable close series.",
                    "note": symbol,
                }
            )
            continue
        prices = prices.drop(columns=[symbol], errors="ignore").join(price, how="outer")
        volumes = volumes.drop(columns=[symbol], errors="ignore").join(volume, how="outer")
        rows.append(
            {
                "source": "stooq-daily-close-fallback",
                "symbol": symbol,
                "status": status,
                "records": 1,
                "requested_price_symbols": 1,
                "requested_symbols": symbol,
                "returned_symbols": symbol,
                "missing_symbols": "",
                "as_of_min": str(price.dropna().index.min().date())
                if not price.dropna().empty
                else None,
                "as_of_max": str(price.dropna().index.max().date())
                if not price.dropna().empty
                else None,
                "cache_hit": status == "cache_hit",
                "cache_path": cache_path,
                "retries": retries,
                "error": None,
                "provider_adjustment_note": "Stooq close-price fallback; adjusted-price compatibility may differ from yfinance.",
                "note": f"{symbol}; close-price compatibility may differ from yfinance auto-adjusted prices",
            }
        )
    return prices.sort_index(), volumes.reindex(index=prices.sort_index().index), pd.DataFrame(rows)


def _download_finance_datareader_symbol(
    symbol: str,
    config: RunConfig,
) -> tuple[pd.Series | None, pd.Series | None, str | None, str, str, int]:
    cache_path = _finance_datareader_cache_path(config, symbol)
    if _single_file_cache_is_fresh(cache_path, config):
        try:
            frame = pd.read_csv(cache_path)
            price, volume, error = _validated_provider_close_volume(
                frame, symbol, "FinanceDataReader cache"
            )
            if price is None:
                return None, None, error, "cache_hit_invalid", str(cache_path), 0
            return price, volume, None, "cache_hit", str(cache_path), 0
        except Exception as exc:
            return (
                None,
                None,
                f"invalid FinanceDataReader cache: {exc}",
                "cache_hit_invalid",
                str(cache_path),
                0,
            )

    try:
        import FinanceDataReader as fdr  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency
        return (
            None,
            None,
            f"FinanceDataReader unavailable: {exc}",
            "unavailable",
            str(cache_path),
            0,
        )

    last_error = None
    for attempt in range(config.retry_count + 1):
        try:
            frame = fdr.DataReader(symbol, config.start_date, config.effective_end_date)
            if frame is None or frame.empty or "Close" not in frame:
                return (
                    None,
                    None,
                    "empty FinanceDataReader response",
                    "failed",
                    str(cache_path),
                    attempt,
                )
            frame = frame.copy()
            frame.index = pd.to_datetime(frame.index).tz_localize(None)
            export = frame.reset_index().rename(columns={frame.index.name or "index": "Date"})
            if "Date" not in export.columns:
                export = export.rename(columns={export.columns[0]: "Date"})
            price, volume, error = _validated_provider_close_volume(
                export, symbol, "FinanceDataReader response"
            )
            if price is None:
                return None, None, error, "failed", str(cache_path), attempt
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            export.to_csv(cache_path, index=False)
            return price, volume, None, "fetched", str(cache_path), attempt
        except Exception as exc:  # pragma: no cover - network/provider dependent
            last_error = exc
            if attempt < config.retry_count:
                time.sleep(config.retry_backoff_seconds)
    return None, None, str(last_error), "failed", str(cache_path), config.retry_count


def _apply_finance_datareader_fallback(
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    symbols: list[str],
    config: RunConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    missing_all = _fallback_candidate_symbols(prices, volumes, symbols, config)
    limit = (
        len(missing_all)
        if config.finance_datareader_fallback_limit is None
        else config.finance_datareader_fallback_limit
    )
    missing = missing_all[:limit]
    rows = []
    for symbol in missing:
        price, volume, error, status, cache_path, retries = _download_finance_datareader_symbol(
            symbol, config
        )
        if price is None:
            rows.append(
                {
                    "source": "finance-datareader-close-fallback",
                    "symbol": symbol,
                    "status": status,
                    "records": 0,
                    "requested_price_symbols": 1,
                    "requested_symbols": symbol,
                    "returned_symbols": "",
                    "missing_symbols": symbol,
                    "cache_hit": status.startswith("cache"),
                    "cache_path": cache_path,
                    "retries": retries,
                    "error": error,
                    "provider_adjustment_note": "FinanceDataReader fallback returned no usable close series.",
                    "note": symbol,
                }
            )
            continue
        prices = prices.drop(columns=[symbol], errors="ignore").join(price, how="outer")
        volumes = volumes.drop(columns=[symbol], errors="ignore").join(volume, how="outer")
        rows.append(
            {
                "source": "finance-datareader-close-fallback",
                "symbol": symbol,
                "status": status,
                "records": 1,
                "requested_price_symbols": 1,
                "requested_symbols": symbol,
                "returned_symbols": symbol,
                "missing_symbols": "",
                "as_of_min": str(price.dropna().index.min().date())
                if not price.dropna().empty
                else None,
                "as_of_max": str(price.dropna().index.max().date())
                if not price.dropna().empty
                else None,
                "cache_hit": status == "cache_hit",
                "cache_path": cache_path,
                "retries": retries,
                "error": None,
                "provider_adjustment_note": "FinanceDataReader close fallback; adjusted-price compatibility may differ from yfinance.",
                "note": f"{symbol}; close-price compatibility may differ from yfinance auto-adjusted prices",
            }
        )
    return prices.sort_index(), volumes.reindex(index=prices.sort_index().index), pd.DataFrame(rows)


def _fallback_candidate_symbols(
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    symbols: list[str],
    config: RunConfig,
) -> list[str]:
    """Return symbols that deserve a free-provider fallback attempt.

    A yfinance column can exist while still being unusable for the current run
    because it is stale, too short, too sparse, non-positive, anomalous, or lacks
    enough liquidity evidence. Treat those cases like missing symbols so a free
    Configured free-provider fallbacks can improve coverage before the run falls closed,
    while source labels preserve adjusted-close compatibility evidence.
    """

    fallback: list[str] = []
    as_of = prices.dropna(how="all").index.max() if not prices.empty else None
    for symbol in symbols:
        if symbol not in prices.columns:
            fallback.append(symbol)
            continue
        series = pd.to_numeric(prices[symbol], errors="coerce").dropna()
        if series.empty:
            fallback.append(symbol)
            continue
        if len(series) < config.min_history_days:
            fallback.append(symbol)
            continue
        latest_date = series.index.max()
        if (
            as_of is not None
            and (pd.Timestamp(as_of).normalize() - pd.Timestamp(latest_date).normalize()).days
            > config.stale_after_days
        ):
            fallback.append(symbol)
            continue
        recent_prices = pd.to_numeric(
            prices[symbol].tail(config.data_quality_lookback_days), errors="coerce"
        )
        if recent_prices.le(0).fillna(False).any():
            fallback.append(symbol)
            continue
        if float(recent_prices.isna().mean()) > config.max_price_missing_ratio:
            fallback.append(symbol)
            continue
        recent_returns = (
            recent_prices.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).abs()
        )
        if recent_returns.gt(config.max_extreme_daily_return).fillna(False).any():
            fallback.append(symbol)
            continue
        if symbol in volumes.columns and config.min_liquidity_observations > 0:
            recent_volume = pd.to_numeric(volumes[symbol].tail(63), errors="coerce")
            if int(recent_volume.notna().sum()) < config.min_liquidity_observations:
                fallback.append(symbol)
                continue
        elif config.min_liquidity_observations > 0:
            fallback.append(symbol)
    return list(dict.fromkeys(fallback))


def _eligible_filter(
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    candidate: pd.DataFrame,
    config: RunConfig,
    *,
    dollar_volumes: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build the acquisition-stage view from the canonical latest date-t mask."""

    candidate_symbols = (
        set(candidate["symbol"].map(normalize_symbol)) if "symbol" in candidate else set()
    )
    comparator_symbols = set(_comparator_symbols(config))
    keep = [
        raw_symbol
        for raw_symbol in prices.columns
        if (normalize_symbol(raw_symbol) in candidate_symbols | comparator_symbols)
        and pd.to_numeric(prices[raw_symbol], errors="coerce").gt(0.0).any()
    ]
    price_keep = prices.reindex(columns=keep).mask(prices.reindex(columns=keep).le(0.0))
    price_keep = price_keep.dropna(axis=0, how="all")
    volume_keep = volumes.reindex(index=price_keep.index, columns=keep).mask(
        volumes.reindex(index=price_keep.index, columns=keep).lt(0.0)
    )
    dollar_keep = (
        dollar_volumes.reindex(index=price_keep.index, columns=keep)
        if dollar_volumes is not None and not dollar_volumes.empty
        else price_keep.mul(volume_keep)
    )
    mask = build_eligibility_mask(
        price_keep,
        volume_keep,
        config,
        dollar_volumes=dollar_keep,
    )
    reasons = latest_eligibility_exclusion_reasons(
        price_keep,
        volume_keep,
        config,
        dollar_volumes=dollar_keep,
    )
    latest = mask.iloc[-1] if not mask.empty else pd.Series(dtype=bool)
    normalized_eligible = {
        normalize_symbol(symbol)
        for symbol in keep
        if normalize_symbol(symbol) in candidate_symbols
        and normalize_symbol(symbol) not in comparator_symbols
        and bool(latest.get(symbol, False))
    }
    eligible = stock_only_universe_frame(
        candidate[candidate["symbol"].map(normalize_symbol).isin(normalized_eligible)]
    )
    exclusions: list[dict[str, object]] = []
    for symbol in candidate["symbol"].map(normalize_symbol):
        if symbol not in price_keep or price_keep[symbol].dropna().empty:
            exclusions.append(
                {"symbol": symbol, "reason": "missing from price providers", "observed": np.nan}
            )
            continue
        symbol_reasons = reasons.get(symbol, [])
        if symbol_reasons:
            exclusions.append(
                {
                    "symbol": symbol,
                    "reason": ",".join(symbol_reasons),
                    "observed": len(symbol_reasons),
                }
            )
    exclusions_df = pd.DataFrame(exclusions, columns=["symbol", "reason", "observed"])
    return price_keep, volume_keep, eligible, exclusions_df


def _has_positive_records(frame: pd.DataFrame | None) -> bool:
    if frame is None or frame.empty or "records" not in frame:
        return False
    return pd.to_numeric(frame["records"], errors="coerce").fillna(0).astype(int).gt(0).any()


def _provider_label_from_sources(
    stooq_sources: pd.DataFrame,
    finance_datareader_sources: pd.DataFrame | None = None,
    yfinance_sources: pd.DataFrame | None = None,
    yahoo_chart_sources: pd.DataFrame | None = None,
    nasdaq_sources: pd.DataFrame | None = None,
) -> str:
    providers: list[str] = []
    if yfinance_sources is None or _has_positive_records(yfinance_sources):
        providers.append("yfinance-free-public-data")
    yahoo_chart = yahoo_chart_sources if yahoo_chart_sources is not None else pd.DataFrame()
    yahoo_chart_records = (
        yahoo_chart.get("records", pd.Series(dtype=float))
        if not yahoo_chart.empty
        else pd.Series(dtype=float)
    )
    if not yahoo_chart.empty and yahoo_chart_records.fillna(0).astype(int).gt(0).any():
        providers.append("yahoo-chart-fallback")
    nasdaq = nasdaq_sources if nasdaq_sources is not None else pd.DataFrame()
    nasdaq_records = (
        nasdaq.get("records", pd.Series(dtype=float))
        if not nasdaq.empty
        else pd.Series(dtype=float)
    )
    if not nasdaq.empty and nasdaq_records.fillna(0).astype(int).gt(0).any():
        providers.append("nasdaq-latest-repair")
    records = (
        stooq_sources.get("records", pd.Series(dtype=float))
        if not stooq_sources.empty
        else pd.Series(dtype=float)
    )
    if not stooq_sources.empty and records.fillna(0).astype(int).gt(0).any():
        providers.append("stooq-fallback")
    fdr = finance_datareader_sources if finance_datareader_sources is not None else pd.DataFrame()
    fdr_records = (
        fdr.get("records", pd.Series(dtype=float)) if not fdr.empty else pd.Series(dtype=float)
    )
    if not fdr.empty and fdr_records.fillna(0).astype(int).gt(0).any():
        providers.append("finance-datareader-fallback")
    return "+".join(providers) if providers else "no-live-price-provider"


def download_live_data(config: RunConfig) -> MarketData:
    fetched_at = datetime.now(UTC)
    candidate, universe_sources = _candidate_universe(config)
    symbols, subset_run = _requested_symbols(config, candidate)
    prices = pd.DataFrame()
    raw_closes = pd.DataFrame()
    volumes = pd.DataFrame()
    stock_splits = pd.DataFrame()
    yf_sources = pd.DataFrame()
    try:
        import yfinance  # noqa: F401  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on optional extra
        yf_sources = _source_frame(
            [
                {
                    "source": "yfinance-adjusted-daily",
                    "status": "unavailable",
                    "records": 0,
                    "requested_price_symbols": len(symbols),
                    "requested_symbols": ",".join(symbols),
                    "returned_symbols": "",
                    "missing_symbols": ",".join(symbols),
                    "error": f"yfinance unavailable: {exc}",
                    "provider_adjustment_note": "yfinance import failed; configured free fallback providers were attempted.",
                }
            ]
        )
    else:
        try:
            prices, raw_closes, volumes, stock_splits, yf_sources = _download_yfinance(
                symbols,
                config,
            )
        except Exception as exc:  # pragma: no cover - network dependent
            yf_sources = _source_frame(
                [
                    {
                        "source": "yfinance-adjusted-daily",
                        "status": "failed",
                        "records": 0,
                        "requested_price_symbols": len(symbols),
                        "requested_symbols": ",".join(symbols),
                        "returned_symbols": "",
                        "missing_symbols": ",".join(symbols),
                        "error": f"yfinance download failed: {exc}",
                        "provider_adjustment_note": "yfinance failed; configured free fallback providers were attempted.",
                    }
                ]
            )

    try:
        if config.yahoo_chart_fallback_limit != 0:
            prices, volumes, yahoo_chart_sources = _apply_yahoo_chart_fallback(
                prices, volumes, symbols, config
            )
        else:
            yahoo_chart_sources = pd.DataFrame()
        if config.nasdaq_fallback_limit != 0:
            prices, volumes, nasdaq_sources = _apply_nasdaq_latest_repair(
                prices, volumes, symbols, config
            )
        else:
            nasdaq_sources = pd.DataFrame()
        if config.stooq_fallback_limit != 0:
            prices, volumes, stooq_sources = _apply_stooq_fallback(prices, volumes, symbols, config)
        else:
            stooq_sources = pd.DataFrame()
        if config.finance_datareader_fallback_limit != 0:
            prices, volumes, finance_datareader_sources = _apply_finance_datareader_fallback(
                prices, volumes, symbols, config
            )
        else:
            finance_datareader_sources = pd.DataFrame()
    except Exception as exc:  # pragma: no cover - network dependent
        raise RuntimeError(f"live download failed; synthetic fallback is forbidden: {exc}") from exc

    if prices.empty:
        raise RuntimeError("live download returned no prices; synthetic fallback is forbidden")

    prices, raw_closes, index_repair_sources = _repair_nasdaq_composite_gaps(
        prices, raw_closes, config
    )

    benchmark = normalize_symbol(config.benchmark)
    comparator_symbols = set(_comparator_symbols(config))
    requested_candidate_symbols = [
        symbol
        for symbol in symbols
        if symbol not in comparator_symbols and symbol in set(candidate["symbol"])
    ]
    downloaded_prices = prices.copy()
    downloaded_raw_closes = raw_closes.reindex(index=prices.index, columns=prices.columns).copy()
    downloaded_volumes = volumes.copy()
    effective_raw_closes = downloaded_raw_closes.combine_first(downloaded_prices)
    downloaded_dollar_volumes = effective_raw_closes.mul(downloaded_volumes)
    prices, volumes, eligible, exclusions = _eligible_filter(
        prices,
        volumes,
        candidate[candidate["symbol"].isin(requested_candidate_symbols)],
        config,
        dollar_volumes=downloaded_dollar_volumes,
    )
    stooq_symbols = set()
    if not stooq_sources.empty and "symbol" in stooq_sources:
        stooq_symbols = set(
            stooq_sources.loc[
                stooq_sources["records"].fillna(0).astype(int).gt(0), "symbol"
            ].astype(str)
        )
    yahoo_chart_symbols = set()
    if not yahoo_chart_sources.empty and "symbol" in yahoo_chart_sources:
        yahoo_chart_symbols = set(
            yahoo_chart_sources.loc[
                yahoo_chart_sources["records"].fillna(0).astype(int).gt(0),
                "symbol",
            ].astype(str)
        )
    nasdaq_symbols = set()
    if not nasdaq_sources.empty and "symbol" in nasdaq_sources:
        nasdaq_symbols = set(
            nasdaq_sources.loc[
                nasdaq_sources["records"].fillna(0).astype(int).gt(0),
                "symbol",
            ].astype(str)
        )
    finance_datareader_symbols = set()
    if not finance_datareader_sources.empty and "symbol" in finance_datareader_sources:
        finance_datareader_symbols = set(
            finance_datareader_sources.loc[
                finance_datareader_sources["records"].fillna(0).astype(int).gt(0),
                "symbol",
            ].astype(str)
        )
    price_source_rows = []
    for symbol in downloaded_prices.columns:
        if symbol in nasdaq_symbols:
            source = "nasdaq-latest-close-repair"
        elif symbol in yahoo_chart_symbols:
            source = "yahoo-chart-adjusted-daily-fallback"
        elif symbol in stooq_symbols:
            source = "stooq-daily-close-fallback"
        elif symbol in finance_datareader_symbols:
            source = "finance-datareader-close-fallback"
        else:
            source = "yfinance-adjusted-daily"
        if symbol == "^IXIC" and _has_positive_records(index_repair_sources):
            source += "+nasdaq-composite-history-repair"
        price_source_rows.append(
            {
                "symbol": symbol,
                "price_source": source,
            }
        )
    price_sources = pd.DataFrame(price_source_rows)
    as_of = prices.dropna(how="all").index.max() if not prices.empty else None
    data_quality = build_data_quality_frame(
        downloaded_prices,
        downloaded_volumes,
        symbols,
        candidate,
        config,
        provider=_provider_label_from_sources(
            stooq_sources,
            finance_datareader_sources,
            yf_sources,
            yahoo_chart_sources,
            nasdaq_sources,
        ),
        price_sources=price_sources,
        exclusions=exclusions,
        as_of=downloaded_prices.dropna(how="all").index.max()
        if not downloaded_prices.empty
        else None,
    )
    provider = _provider_label_from_sources(
        stooq_sources,
        finance_datareader_sources,
        yf_sources,
        yahoo_chart_sources,
        nasdaq_sources,
    )
    if _has_positive_records(index_repair_sources):
        provider += "+nasdaq-composite-history-repair"
        data_quality["provider"] = provider
    returned_symbols = [
        symbol
        for symbol in symbols
        if symbol in downloaded_prices.columns
        and pd.to_numeric(downloaded_prices[symbol], errors="coerce").gt(0.0).any()
    ]
    returned_candidate_symbols = [
        symbol for symbol in requested_candidate_symbols if symbol in returned_symbols
    ]
    missing_symbols = [symbol for symbol in symbols if symbol not in returned_symbols]
    summary = _source_frame(
        [
            {
                "source": "acquisition-run-diagnostics",
                "status": "partial_requested_subset" if subset_run else "full_requested_universe",
                "records": len(returned_symbols),
                "candidate_symbols": len(candidate),
                "requested_price_symbols": len(requested_candidate_symbols),
                "returned_price_symbols": len(returned_candidate_symbols),
                "eligible_price_symbols": len(eligible),
                "liquidity_eligible_symbols": None,
                "requested_download_symbols": len(symbols),
                "requested_symbols": ",".join(requested_candidate_symbols),
                "returned_symbols": ",".join(
                    symbol for symbol in returned_symbols if symbol not in comparator_symbols
                ),
                "missing_symbols": ",".join(
                    symbol for symbol in missing_symbols if symbol not in comparator_symbols
                ),
                "as_of_min": (
                    str(downloaded_prices.dropna(how="all").index.min().date())
                    if not downloaded_prices.empty
                    else None
                ),
                "as_of_max": (
                    str(downloaded_prices.dropna(how="all").index.max().date())
                    if not downloaded_prices.empty
                    else None
                ),
                "cache_hit": bool(
                    not yf_sources.empty
                    and "cache_hit" in yf_sources
                    and yf_sources["cache_hit"].fillna(False).astype(bool).all()
                ),
                "benchmark_symbol": benchmark,
                "benchmark_price_available": benchmark in prices.columns,
                "chart_benchmark_symbol": normalize_symbol(config.chart_benchmark),
                "chart_benchmark_price_available": normalize_symbol(config.chart_benchmark)
                in prices.columns,
                "additional_comparison_symbols": ",".join(config.additional_comparison_benchmarks),
                "additional_comparison_prices_available": ",".join(
                    symbol
                    for symbol in config.additional_comparison_benchmarks
                    if symbol in prices.columns
                    and pd.to_numeric(prices[symbol], errors="coerce").gt(0.0).any()
                ),
                "excluded_symbols": len(exclusions),
                "subset_run": subset_run,
                "point_in_time_universe": False,
                "provider_adjustment_note": (
                    "yfinance Adj Close plus separate raw Close/Volume; Yahoo chart adjusted-close, "
                    "Nasdaq latest-close repair, Stooq close, and FinanceDataReader close fallback "
                    "rows are separately labeled when used."
                ),
                "note": (
                    "Acquisition-stage diagnostics use the same causal latest-date history, price, "
                    "coverage, trailing-extreme-return, volume, and liquidity eligibility mask as "
                    "the canonical analysis. The dashboard data.funnel object is authoritative."
                ),
            }
        ]
    )
    data_sources = pd.concat(
        [
            universe_sources,
            yf_sources,
            yahoo_chart_sources,
            nasdaq_sources,
            index_repair_sources,
            stooq_sources,
            finance_datareader_sources,
            summary,
        ],
        ignore_index=True,
    )
    data_sources = _sanitize_public_source_health(data_sources)
    return MarketData(
        prices=prices,
        volumes=volumes,
        provider=provider,
        fetched_at=fetched_at,
        as_of=as_of,
        exclusions=exclusions,
        candidate_universe=candidate,
        eligible_universe=eligible,
        price_sources=price_sources,
        data_sources=data_sources,
        data_quality=data_quality,
        raw_prices=downloaded_prices,
        raw_closes=downloaded_raw_closes,
        raw_volumes=downloaded_volumes,
        stock_splits=stock_splits.reindex(
            index=downloaded_prices.index,
            columns=downloaded_prices.columns,
        ).fillna(0.0),
    )


def load_market_data(config: RunConfig) -> MarketData:
    return download_live_data(config)
