from __future__ import annotations

import hashlib
import json
import re
import time
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from .config import RunConfig
from .universe import effective_user_agent, normalize_symbol


SEC_MARKET_CAP_VERSION = "sec-pit-market-cap-v1"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_FRAME_URL = "https://data.sec.gov/api/xbrl/frames/{taxonomy}/{tag}/{uom}/{ccp}.json"
SEC_MASTER_URL = "https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{quarter}/master.zip"
SEC_REQUEST_INTERVAL_SECONDS = 0.12
DIRECT_CAP_MINIMUM = 1_000_000.0
DIRECT_CAP_MAXIMUM = 20_000_000_000_000.0


@dataclass(frozen=True, slots=True)
class FrameSpec:
    taxonomy: str
    tag: str
    uom: str
    context: str
    value_kind: str
    priority: int


FRAME_SPECS = (
    FrameSpec("dei", "EntityCommonStockSharesOutstanding", "shares", "instant", "shares", 60),
    FrameSpec("us-gaap", "CommonStockSharesOutstanding", "shares", "instant", "shares", 55),
    FrameSpec("ifrs-full", "NumberOfSharesOutstanding", "shares", "instant", "shares", 50),
    FrameSpec(
        "us-gaap",
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "shares",
        "duration",
        "shares",
        45,
    ),
    FrameSpec(
        "us-gaap",
        "WeightedAverageNumberOfSharesOutstandingBasic",
        "shares",
        "duration",
        "shares",
        40,
    ),
    FrameSpec("ifrs-full", "AdjustedWeightedAverageShares", "shares", "duration", "shares", 35),
    FrameSpec("ifrs-full", "WeightedAverageShares", "shares", "duration", "shares", 30),
    FrameSpec("dei", "EntityPublicFloat", "USD", "instant", "direct_cap", 20),
)


@dataclass(slots=True)
class MarketCapResult:
    market_caps: pd.DataFrame
    symbol_sources: pd.DataFrame
    source_health: pd.DataFrame
    observation_count: int
    covered_symbol_count: int
    coverage_ratio: float


_last_sec_request_at = 0.0


def _sec_cache_path(cache_dir: Path, category: str, name: str) -> Path:
    return cache_dir / "sec_market_cap" / category / name


def _cache_fresh(path: Path, config: RunConfig) -> bool:
    if config.refresh_market_data or not path.exists():
        return False
    age = datetime.now(UTC) - datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    return timedelta(0) <= age <= timedelta(hours=config.market_cache_max_age_hours)


def _fetch_bytes(
    url: str,
    path: Path,
    config: RunConfig,
    *,
    allow_not_found: bool = False,
) -> tuple[bytes | None, str]:
    if _cache_fresh(path, config):
        return path.read_bytes(), "cache_hit"
    global _last_sec_request_at
    last_error: Exception | None = None
    for attempt in range(config.retry_count + 1):
        elapsed = time.monotonic() - _last_sec_request_at
        if elapsed < SEC_REQUEST_INTERVAL_SECONDS:
            time.sleep(SEC_REQUEST_INTERVAL_SECONDS - elapsed)
        try:
            request = Request(
                url, headers={"User-Agent": effective_user_agent(config.sec_user_agent)}
            )
            with urlopen(request, timeout=45) as response:
                payload = response.read()
            _last_sec_request_at = time.monotonic()
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.tmp")
            temporary.write_bytes(payload)
            temporary.replace(path)
            return payload, "fetched"
        except HTTPError as error:
            _last_sec_request_at = time.monotonic()
            if allow_not_found and error.code == 404:
                return None, "not_found"
            last_error = error
        except Exception as error:  # pragma: no cover - depends on public endpoints
            _last_sec_request_at = time.monotonic()
            last_error = error
        if attempt < config.retry_count:
            time.sleep(config.retry_backoff_seconds * (attempt + 1))
    if path.exists():
        return path.read_bytes(), "stale_cache_fallback"
    raise RuntimeError(f"SEC market-cap source failed: {url}: {last_error}")


def _quarters(start_year: int, as_of: pd.Timestamp) -> Iterable[tuple[int, int]]:
    last_quarter = (as_of.month - 1) // 3 + 1
    for year in range(start_year, as_of.year + 1):
        maximum = last_quarter if year == as_of.year else 4
        for quarter in range(1, maximum + 1):
            yield year, quarter


def _accession_from_filename(value: str) -> str | None:
    match = re.search(r"(\d{10}-\d{2}-\d{6})", value)
    return match.group(1) if match else None


def _parse_master_index(payload: bytes) -> list[dict[str, object]]:
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        lines = archive.read("master.idx").decode("latin1").splitlines()
    rows: list[dict[str, object]] = []
    for line in lines:
        if line.count("|") != 4:
            continue
        cik, name, form, filed, filename = line.split("|", maxsplit=4)
        accession = _accession_from_filename(filename)
        if accession is None:
            continue
        try:
            filed_at = pd.Timestamp(filed).normalize()
        except (TypeError, ValueError):
            continue
        rows.append(
            {
                "accession": accession,
                "cik": int(cik),
                "entityName": name,
                "form": form,
                "filed": filed_at,
            }
        )
    return rows


def _ticker_cik_map(payload: bytes) -> pd.DataFrame:
    parsed = json.loads(payload)
    frame = pd.DataFrame(parsed.get("data", []), columns=parsed.get("fields", []))
    if not {"cik", "ticker", "name"}.issubset(frame.columns):
        raise ValueError("SEC company ticker response is missing required fields")
    frame["symbol"] = frame["ticker"].astype(str).map(normalize_symbol)
    frame["cik"] = pd.to_numeric(frame["cik"], errors="coerce").astype("Int64")
    frame = frame.dropna(subset=["cik"]).drop_duplicates("symbol", keep="first")
    return frame[["symbol", "cik", "name"]].reset_index(drop=True)


def _frame_contexts(spec: FrameSpec, start_year: int, as_of: pd.Timestamp) -> Iterable[str]:
    for year, quarter in _quarters(start_year, as_of):
        suffix = "I" if spec.context == "instant" else ""
        yield f"CY{year}Q{quarter}{suffix}"
    if spec.context == "duration":
        for year in range(start_year, as_of.year + 1):
            yield f"CY{year}"


def _frame_rows(payload: bytes, spec: FrameSpec) -> list[dict[str, object]]:
    parsed = json.loads(payload)
    if (
        parsed.get("taxonomy") != spec.taxonomy
        or parsed.get("tag") != spec.tag
        or parsed.get("uom") != spec.uom
    ):
        raise ValueError(f"SEC frame identity mismatch for {spec.taxonomy}/{spec.tag}")
    rows: list[dict[str, object]] = []
    for raw in parsed.get("data", []):
        try:
            value = float(raw["val"])
            end = pd.Timestamp(raw["end"]).normalize()
            cik = int(raw["cik"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if not np.isfinite(value) or value <= 0.0:
            continue
        rows.append(
            {
                "accession": str(raw.get("accn") or ""),
                "cik": cik,
                "entityName": str(raw.get("entityName") or ""),
                "location": str(raw.get("loc") or ""),
                "factEnd": end,
                "value": value,
                "valueKind": spec.value_kind,
                "taxonomy": spec.taxonomy,
                "tag": spec.tag,
                "priority": spec.priority,
            }
        )
    return rows


def _normalized_entity_name(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _split_adjustment_after(
    stock_splits: pd.Series,
    fact_end: pd.Timestamp,
) -> float:
    values = pd.to_numeric(stock_splits, errors="coerce").replace([np.inf, -np.inf], np.nan)
    values = values.loc[values.index > fact_end].dropna()
    values = values.loc[values.gt(0.0) & values.ne(1.0)]
    return float(values.prod()) if not values.empty else 1.0


def _price_at_or_before(prices: pd.Series, date: pd.Timestamp) -> float | None:
    values = pd.to_numeric(prices.loc[prices.index <= date].tail(8), errors="coerce")
    values = values.replace([np.inf, -np.inf], np.nan).dropna()
    if values.empty or float(values.iloc[-1]) <= 0.0:
        return None
    return float(values.iloc[-1])


def _facts_for_symbols(
    facts: pd.DataFrame,
    universe: pd.DataFrame,
    ticker_map: pd.DataFrame,
) -> pd.DataFrame:
    symbols = universe[["symbol", "name"]].copy()
    symbols["symbol"] = symbols["symbol"].astype(str).map(normalize_symbol)
    mapped = ticker_map.set_index("symbol")["cik"]
    symbols["cik"] = symbols["symbol"].map(mapped).astype("Int64")
    fact_ciks = set(facts["cik"].astype(int))

    normalized_fact_names = facts[["cik", "entityName"]].drop_duplicates().copy()
    normalized_fact_names["normalizedName"] = normalized_fact_names["entityName"].map(
        _normalized_entity_name
    )
    by_name = normalized_fact_names.groupby("normalizedName")["cik"].agg(
        lambda values: sorted(set(int(value) for value in values))
    )
    unique_name_cik = {
        name: values[0] for name, values in by_name.items() if name and len(values) == 1
    }
    symbols["mappedBy"] = "ticker"
    needs_alias = ~symbols["cik"].isin(fact_ciks)
    alias = symbols.loc[needs_alias, "name"].map(_normalized_entity_name).map(unique_name_cik)
    symbols.loc[needs_alias & alias.notna(), "cik"] = alias.dropna().astype(int)
    symbols.loc[needs_alias & alias.notna(), "mappedBy"] = "unique_exact_entity_name"

    # One registrant can have multiple listed share classes (for example GOOG/GOOGL).
    # Duplicate the public fact to each current class and keep the mapping explicit.
    merged = facts.merge(symbols, on="cik", how="inner", validate="many_to_many")
    return merged


def build_market_cap_panel(
    *,
    dates: pd.DatetimeIndex,
    raw_closes: pd.DataFrame,
    stock_splits: pd.DataFrame,
    universe: pd.DataFrame,
    facts: pd.DataFrame,
    ticker_map: pd.DataFrame,
    config: RunConfig,
) -> MarketCapResult:
    if dates.empty:
        raise ValueError("market-cap panel requires at least one price date")
    required = {
        "accession",
        "cik",
        "entityName",
        "location",
        "factEnd",
        "filed",
        "value",
        "valueKind",
        "taxonomy",
        "tag",
        "priority",
    }
    if not required.issubset(facts.columns):
        raise ValueError("market-cap facts are missing required fields")
    usable = facts.copy()
    usable["factEnd"] = pd.to_datetime(usable["factEnd"], errors="coerce").dt.normalize()
    usable["filed"] = pd.to_datetime(usable["filed"], errors="coerce").dt.normalize()
    usable["value"] = pd.to_numeric(usable["value"], errors="coerce")
    usable = usable.loc[
        usable["factEnd"].notna()
        & usable["filed"].notna()
        & usable["value"].gt(0.0)
        & usable["factEnd"].le(usable["filed"])
        & usable["filed"].le(dates.max())
    ]
    usable["availableOn"] = usable["filed"] + pd.Timedelta(days=1)
    usable = usable.loc[
        (usable["availableOn"] - usable["factEnd"]).dt.days.le(config.market_cap_max_age_days)
    ]
    usable = _facts_for_symbols(usable, universe, ticker_map)
    if usable.empty:
        raise ValueError("no SEC point-in-time market-cap facts match the analyzed universe")

    # One filing can expose several standard tags. Prefer actual outstanding shares,
    # then diluted/basic period shares, and finally direct public-float market value.
    usable = usable.sort_values(
        ["symbol", "availableOn", "factEnd", "priority", "accession"],
        kind="stable",
    ).drop_duplicates(["symbol", "availableOn"], keep="last")

    columns = [str(column) for column in raw_closes.columns]
    panel = pd.DataFrame(np.nan, index=dates, columns=columns, dtype=float)
    source_rows: list[dict[str, object]] = []
    for symbol, group in usable.groupby("symbol", sort=False):
        if symbol not in panel.columns:
            continue
        close = pd.to_numeric(raw_closes[symbol], errors="coerce").reindex(dates)
        splits = (
            stock_splits[symbol].reindex(dates).fillna(0.0)
            if symbol in stock_splits
            else pd.Series(0.0, index=dates)
        )
        events: list[dict[str, object]] = []
        for row in group.to_dict(orient="records"):
            fact_end = pd.Timestamp(row["factEnd"])
            if row["valueKind"] == "direct_cap":
                reference_price = _price_at_or_before(close, fact_end)
                if reference_price is None:
                    continue
                implied_shares = float(row["value"]) / reference_price
            else:
                # Yahoo Close is split-normalized across its history. Converting the
                # disclosed share count by subsequent split ratios is a unit conversion,
                # not an economic signal, and keeps price and shares on the same basis.
                implied_shares = float(row["value"]) * _split_adjustment_after(splits, fact_end)
            if not np.isfinite(implied_shares) or implied_shares <= 0.0:
                continue
            events.append({**row, "impliedShares": implied_shares})
        if not events:
            continue
        event_frame = (
            pd.DataFrame(events)
            .sort_values(
                ["availableOn", "factEnd", "priority", "accession"],
                kind="stable",
            )
            .drop_duplicates("availableOn", keep="last")
        )
        event_index = pd.DatetimeIndex(event_frame["availableOn"])
        union = dates.union(event_index).sort_values()
        implied = (
            pd.Series(
                event_frame["impliedShares"].to_numpy(dtype=float),
                index=event_index,
            )
            .reindex(union)
            .ffill()
            .reindex(dates)
        )
        fact_end_series = (
            pd.Series(
                event_frame["factEnd"].to_numpy(),
                index=event_index,
            )
            .reindex(union)
            .ffill()
            .reindex(dates)
        )
        age_days = pd.Series(dates - pd.DatetimeIndex(fact_end_series), index=dates).dt.days
        values = implied.mul(close).where(age_days.between(0, config.market_cap_max_age_days))
        values = values.where(values.between(DIRECT_CAP_MINIMUM, DIRECT_CAP_MAXIMUM))
        panel[symbol] = values
        latest = event_frame.iloc[-1]
        source_rows.append(
            {
                "symbol": symbol,
                "cik": int(latest["cik"]),
                "mapping": latest["mappedBy"],
                "taxonomy": latest["taxonomy"],
                "tag": latest["tag"],
                "valueKind": latest["valueKind"],
                "latestFactEnd": pd.Timestamp(latest["factEnd"]).date().isoformat(),
                "latestFiled": pd.Timestamp(latest["filed"]).date().isoformat(),
                "latestAccession": latest["accession"],
                "location": latest["location"],
                "latestMarketCapAvailable": bool(pd.notna(panel.at[dates.max(), symbol])),
            }
        )
    panel = panel.reindex(index=dates, columns=columns)
    latest_covered = int(panel.loc[dates.max()].notna().sum())
    candidate_count = max(1, len([column for column in columns if column != config.benchmark]))
    coverage_ratio = latest_covered / candidate_count
    if coverage_ratio < config.market_cap_min_universe_coverage:
        raise ValueError(
            "point-in-time market-cap coverage is below the required threshold: "
            f"{latest_covered}/{candidate_count} ({coverage_ratio:.2%})"
        )
    source_frame = pd.DataFrame(source_rows).sort_values("symbol").reset_index(drop=True)
    health = pd.DataFrame(
        [
            {
                "source": "sec-xbrl-point-in-time-market-cap",
                "status": "available",
                "records": int(len(usable)),
                "candidate_symbols": candidate_count,
                "market_cap_covered_symbols": latest_covered,
                "market_cap_coverage_ratio": coverage_ratio,
                "point_in_time_market_cap": True,
                "version": SEC_MARKET_CAP_VERSION,
                "note": (
                    "Actual SEC filing dates gate every observation; no current market cap is "
                    "copied backward. Missing facts remain missing."
                ),
            }
        ]
    )
    return MarketCapResult(
        market_caps=panel,
        symbol_sources=source_frame,
        source_health=health,
        observation_count=int(len(usable)),
        covered_symbol_count=latest_covered,
        coverage_ratio=coverage_ratio,
    )


def load_sec_market_caps(
    *,
    dates: pd.DatetimeIndex,
    raw_closes: pd.DataFrame,
    stock_splits: pd.DataFrame,
    universe: pd.DataFrame,
    config: RunConfig,
) -> MarketCapResult:
    as_of = pd.Timestamp(dates.max()).normalize()
    context_start_year = pd.Timestamp(config.start_date).year - 1
    cache_root = config.cache_dir
    statuses: list[str] = []

    ticker_payload, status = _fetch_bytes(
        SEC_TICKERS_URL,
        _sec_cache_path(cache_root, "reference", "company_tickers_exchange.json"),
        config,
    )
    assert ticker_payload is not None
    statuses.append(status)
    ticker_map = _ticker_cik_map(ticker_payload)

    master_rows: list[dict[str, object]] = []
    for year, quarter in _quarters(context_start_year, as_of):
        payload, status = _fetch_bytes(
            SEC_MASTER_URL.format(year=year, quarter=quarter),
            _sec_cache_path(cache_root, "master", f"{year}q{quarter}.zip"),
            config,
            allow_not_found=True,
        )
        statuses.append(status)
        if payload is not None:
            master_rows.extend(_parse_master_index(payload))
    master = pd.DataFrame(master_rows).drop_duplicates("accession", keep="last")
    if master.empty:
        raise ValueError("SEC master indexes contain no filing-date evidence")
    filed_by_accession = master.set_index("accession")[["filed", "form"]]

    fact_rows: list[dict[str, object]] = []
    for spec in FRAME_SPECS:
        for context in _frame_contexts(spec, context_start_year, as_of):
            filename = f"{spec.taxonomy}_{spec.tag}_{spec.uom}_{context}.json"
            payload, status = _fetch_bytes(
                SEC_FRAME_URL.format(
                    taxonomy=spec.taxonomy,
                    tag=spec.tag,
                    uom=spec.uom,
                    ccp=context,
                ),
                _sec_cache_path(cache_root, "frames", filename),
                config,
                allow_not_found=True,
            )
            statuses.append(status)
            if payload is not None:
                fact_rows.extend(_frame_rows(payload, spec))
    facts = pd.DataFrame(fact_rows)
    if facts.empty:
        raise ValueError("SEC XBRL frames contain no market-cap facts")
    facts = facts.join(filed_by_accession, on="accession", how="inner")
    result = build_market_cap_panel(
        dates=dates,
        raw_closes=raw_closes,
        stock_splits=stock_splits,
        universe=universe,
        facts=facts,
        ticker_map=ticker_map,
        config=config,
    )
    result.source_health["fetchStatusCounts"] = json.dumps(
        pd.Series(statuses).value_counts().sort_index().to_dict(),
        sort_keys=True,
    )
    result.source_health["fetchStatusSha256"] = hashlib.sha256(
        "\n".join(sorted(statuses)).encode("utf-8")
    ).hexdigest()
    return result
