from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import RunConfig
from .universe import normalize_symbol


SEC_MARKET_CAP_VERSION = "sec-pit-market-cap-v1"
DIRECT_CAP_MINIMUM = 1_000_000.0
DIRECT_CAP_MAXIMUM = 20_000_000_000_000.0




@dataclass(slots=True)
class MarketCapResult:
    market_caps: pd.DataFrame
    symbol_sources: pd.DataFrame
    source_health: pd.DataFrame
    observation_count: int
    covered_symbol_count: int
    coverage_ratio: float


_last_sec_request_at = 0.0




















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
