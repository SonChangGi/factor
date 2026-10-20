from __future__ import annotations

import pandas as pd
import pytest

from factor_lab.config import RunConfig
from factor_lab.market_cap import build_market_cap_panel


def _fact(
    *,
    accession: str = "0000000001-24-000001",
    cik: int = 1,
    entity_name: str = "Alpha Inc",
    fact_end: str = "2024-01-02",
    filed: str = "2024-01-05",
    value: float = 100_000_000.0,
    value_kind: str = "shares",
    priority: int = 60,
) -> dict[str, object]:
    return {
        "accession": accession,
        "cik": cik,
        "entityName": entity_name,
        "location": "US-DE",
        "factEnd": fact_end,
        "filed": filed,
        "value": value,
        "valueKind": value_kind,
        "taxonomy": "dei",
        "tag": (
            "EntityPublicFloat"
            if value_kind == "direct_cap"
            else "EntityCommonStockSharesOutstanding"
        ),
        "priority": priority,
    }


def _panel(
    facts: list[dict[str, object]],
    *,
    dates: pd.DatetimeIndex | None = None,
    closes: pd.DataFrame | None = None,
    splits: pd.DataFrame | None = None,
    universe: pd.DataFrame | None = None,
    ticker_map: pd.DataFrame | None = None,
    **config_overrides: object,
):
    dates = dates if dates is not None else pd.bdate_range("2024-01-02", "2024-01-12")
    closes = closes if closes is not None else pd.DataFrame({"AAA": 10.0}, index=dates)
    splits = splits if splits is not None else pd.DataFrame({"AAA": 0.0}, index=dates)
    universe = (
        universe if universe is not None else pd.DataFrame([{"symbol": "AAA", "name": "Alpha Inc"}])
    )
    ticker_map = (
        ticker_map
        if ticker_map is not None
        else pd.DataFrame([{"symbol": "AAA", "cik": 1, "name": "Alpha Inc"}])
    )
    config_values = {
        "benchmark": "SPY",
        "market_cap_min_universe_coverage": 0.0,
        **config_overrides,
    }
    config = RunConfig(**config_values)
    return build_market_cap_panel(
        dates=dates,
        raw_closes=closes,
        stock_splits=splits,
        universe=universe,
        facts=pd.DataFrame(facts),
        ticker_map=ticker_map,
        config=config,
    )


def test_filing_date_prevents_lookahead() -> None:
    result = _panel([_fact(filed="2024-01-05")])

    assert result.market_caps.loc[:"2024-01-05", "AAA"].isna().all()
    assert result.market_caps.loc["2024-01-08", "AAA"] == pytest.approx(1_000_000_000.0)


def test_share_fact_is_converted_to_split_normalized_close_units() -> None:
    dates = pd.bdate_range("2024-01-02", "2024-01-12")
    splits = pd.DataFrame({"AAA": 0.0}, index=dates)
    splits.loc["2024-01-09", "AAA"] = 2.0

    result = _panel([_fact()], dates=dates, splits=splits)

    assert result.market_caps.loc["2024-01-08", "AAA"] == pytest.approx(2_000_000_000.0)
    assert result.market_caps.loc["2024-01-10", "AAA"] == pytest.approx(2_000_000_000.0)


def test_direct_cap_fact_becomes_implied_shares_without_copying_value_forward() -> None:
    dates = pd.bdate_range("2024-01-02", "2024-01-12")
    closes = pd.DataFrame({"AAA": 10.0}, index=dates)
    closes.loc["2024-01-08":, "AAA"] = 12.0

    result = _panel(
        [_fact(value=1_000_000_000.0, value_kind="direct_cap")],
        dates=dates,
        closes=closes,
    )

    assert result.market_caps.loc["2024-01-08", "AAA"] == pytest.approx(1_200_000_000.0)


def test_stale_fact_is_masked_after_maximum_age() -> None:
    result = _panel(
        [_fact(fact_end="2024-01-02", filed="2024-01-02")],
        market_cap_max_age_days=3,
    )

    assert result.market_caps.loc["2024-01-05", "AAA"] == pytest.approx(1_000_000_000.0)
    assert pd.isna(result.market_caps.loc["2024-01-08", "AAA"])


def test_unique_exact_entity_name_can_recover_changed_ticker_mapping() -> None:
    ticker_map = pd.DataFrame([{"symbol": "OLD", "cik": 1, "name": "Alpha Inc"}])

    result = _panel([_fact()], ticker_map=ticker_map)

    assert result.covered_symbol_count == 1
    assert result.symbol_sources.loc[0, "mapping"] == "unique_exact_entity_name"


def test_latest_coverage_requirement_fails_closed() -> None:
    dates = pd.bdate_range("2024-01-02", "2024-01-12")
    closes = pd.DataFrame({"AAA": 10.0, "BBB": 20.0}, index=dates)
    splits = pd.DataFrame(0.0, index=dates, columns=closes.columns)
    universe = pd.DataFrame(
        [
            {"symbol": "AAA", "name": "Alpha Inc"},
            {"symbol": "BBB", "name": "Beta Inc"},
        ]
    )
    ticker_map = pd.DataFrame(
        [
            {"symbol": "AAA", "cik": 1, "name": "Alpha Inc"},
            {"symbol": "BBB", "cik": 2, "name": "Beta Inc"},
        ]
    )

    with pytest.raises(ValueError, match="coverage is below"):
        _panel(
            [_fact()],
            dates=dates,
            closes=closes,
            splits=splits,
            universe=universe,
            ticker_map=ticker_map,
            market_cap_min_universe_coverage=0.75,
        )


def test_higher_priority_fact_wins_when_multiple_tags_arrive_together() -> None:
    result = _panel(
        [
            _fact(accession="0000000001-24-000001", value=80_000_000.0, priority=40),
            _fact(accession="0000000001-24-000002", value=100_000_000.0, priority=60),
        ]
    )

    assert result.market_caps.loc["2024-01-08", "AAA"] == pytest.approx(1_000_000_000.0)
    assert result.symbol_sources.loc[0, "latestAccession"] == "0000000001-24-000002"
