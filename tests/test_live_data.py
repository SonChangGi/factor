import hashlib
import json
import os
import sys
import inspect
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from factor_lab.config import RunConfig
from factor_lab.live_data import (
    _apply_finance_datareader_fallback,
    _apply_nasdaq_latest_repair,
    _apply_stooq_fallback,
    _apply_yahoo_chart_fallback,
    _comparator_symbols,
    _download_nasdaq_symbol,
    _download_finance_datareader_symbol,
    _download_stooq_symbol,
    _download_yahoo_chart_symbol,
    _eligible_filter,
    _finance_datareader_cache_path,
    _nasdaq_cache_path,
    _requested_symbols,
    _stooq_cache_path,
    _stooq_symbol,
    _yahoo_chart_cache_path,
    build_data_quality_frame,
    download_live_data,
)


def _candidate_frame(symbols):
    return pd.DataFrame(
        {
            "symbol": symbols,
            "name": symbols,
            "asset_type": ["stock"] * len(symbols),
            "exchange": ["fixture"] * len(symbols),
            "source": ["test-fixture"] * len(symbols),
            "is_etf": [False] * len(symbols),
        }
    )


def test_default_comparators_are_ordered_deduplicated_and_never_candidates() -> None:
    config = RunConfig(
        live=True,
        chart_benchmark=" ^ixic ",
        additional_comparison_benchmarks=(" qqq ", "SPY", "^IXIC", "QQQ"),
    )
    candidate = _candidate_frame(["QQQ", "AAPL", "GOOD"])
    dates = pd.bdate_range("2024-01-01", periods=260)
    prices = pd.DataFrame(
        {
            "SPY": np.linspace(400, 430, len(dates)),
            "^IXIC": np.linspace(15_000, 17_000, len(dates)),
            "QQQ": np.linspace(300, 345, len(dates)),
            "AAPL": np.linspace(175, 220, len(dates)),
            "GOOD": np.linspace(20, 30, len(dates)),
        },
        index=dates,
    )
    volumes = pd.DataFrame(1_000_000.0, index=dates, columns=prices.columns)

    filtered, _, eligible, _ = _eligible_filter(prices, volumes, candidate, config)

    assert _comparator_symbols(config) == ["SPY", "^IXIC", "QQQ"]
    capped, subset = _requested_symbols(
        RunConfig(live=True, max_price_symbols=2),
        _candidate_frame(["AAPL", "GOOD"]),
    )
    assert capped == ["SPY", "^IXIC", "QQQ"]
    assert subset is True
    assert list(filtered.columns) == ["SPY", "^IXIC", "QQQ", "AAPL", "GOOD"]
    assert list(eligible["symbol"]) == ["AAPL", "GOOD"]


def test_eligible_filter_excludes_uninvestable_symbols():
    dates = pd.bdate_range("2024-01-01", periods=260)
    prices = pd.DataFrame(
        {
            "GOOD": np.linspace(20, 30, len(dates)),
            "LOWP": np.linspace(1, 2, len(dates)),
            "SHORT": [np.nan] * 200 + list(np.linspace(10, 12, 60)),
            "ILLIQ": np.linspace(10, 11, len(dates)),
        },
        index=dates,
    )
    volumes = pd.DataFrame(
        {
            "GOOD": 1_000_000,
            "LOWP": 1_000_000,
            "SHORT": 1_000_000,
            "ILLIQ": 10,
        },
        index=dates,
    )
    candidate = _candidate_frame(["GOOD", "LOWP", "SHORT", "ILLIQ", "MISS"])
    config = RunConfig(
        min_history_days=252, min_price=5, min_avg_dollar_volume=1_000_000, chart_benchmark="QQQ"
    )
    filtered, _, eligible, exclusions = _eligible_filter(prices, volumes, candidate, config)
    assert list(filtered.columns) == ["GOOD", "LOWP", "SHORT", "ILLIQ"]
    assert list(eligible["symbol"]) == ["GOOD"]
    reasons = exclusions.set_index("symbol")["reason"].to_dict()
    assert reasons["LOWP"] == "missing_or_below_min_price"
    assert reasons["SHORT"] == "insufficient_history,recent_price_coverage"
    assert reasons["ILLIQ"] == "liquidity_requirement"
    assert reasons["MISS"] == "missing from price providers"


def test_eligible_filter_excludes_recent_data_quality_anomalies():
    dates = pd.bdate_range("2024-01-01", periods=260)
    base = np.linspace(20, 30, len(dates))
    prices = pd.DataFrame(
        {
            "GOOD": base,
            "MISSING": base.copy(),
            "NEGATIVE": base.copy(),
            "EXTREME": base.copy(),
            "OLDEXT": base.copy(),
            "VOLMISS": base.copy(),
            "ALLNAN": np.nan,
        },
        index=dates,
    )
    prices.loc[dates[-60:-30], "MISSING"] = np.nan
    prices.loc[dates[-5], "NEGATIVE"] = -1.0
    prices.loc[dates[-3], "EXTREME"] = prices.loc[dates[-4], "EXTREME"] * 2.5
    prices.loc[dates[5], "OLDEXT"] = prices.loc[dates[4], "OLDEXT"] * 2.5
    volumes = pd.DataFrame(
        {
            "GOOD": 1_000_000,
            "MISSING": 1_000_000,
            "NEGATIVE": 1_000_000,
            "EXTREME": 1_000_000,
            "OLDEXT": 1_000_000,
            "VOLMISS": 1_000_000,
            "ALLNAN": 1_000_000,
        },
        index=dates,
    )
    volumes.loc[dates[-40:], "VOLMISS"] = np.nan
    candidate = _candidate_frame(
        ["GOOD", "MISSING", "NEGATIVE", "EXTREME", "OLDEXT", "VOLMISS", "ALLNAN"]
    )
    config = RunConfig(
        min_history_days=200,
        min_price=5,
        min_avg_dollar_volume=1_000_000,
        data_quality_lookback_days=252,
        max_price_missing_ratio=0.05,
        max_volume_missing_ratio=0.10,
        max_extreme_daily_return=0.80,
    )

    filtered, _, eligible, exclusions = _eligible_filter(prices, volumes, candidate, config)

    assert list(filtered.columns) == [
        "GOOD",
        "MISSING",
        "NEGATIVE",
        "EXTREME",
        "OLDEXT",
        "VOLMISS",
    ]
    assert list(eligible["symbol"]) == ["GOOD", "NEGATIVE", "OLDEXT"]
    reasons = exclusions.set_index("symbol")["reason"].to_dict()
    assert reasons["MISSING"] == "recent_price_coverage,liquidity_requirement"
    assert "NEGATIVE" not in reasons
    assert reasons["EXTREME"] == "recent_extreme_return"
    assert "OLDEXT" not in reasons
    assert reasons["VOLMISS"] == "recent_volume_coverage,liquidity_requirement"
    assert reasons["ALLNAN"] == "missing from price providers"


def test_build_data_quality_frame_records_practical_symbol_diagnostics():
    dates = pd.bdate_range("2024-01-01", periods=260)
    prices = pd.DataFrame(
        {
            "GOOD": np.linspace(20, 30, len(dates)),
            "SPY": np.linspace(400, 430, len(dates)),
            "MISSVOL": np.linspace(25, 35, len(dates)),
        },
        index=dates,
    )
    volumes = pd.DataFrame({"GOOD": 1_000_000, "MISSVOL": np.nan}, index=dates)
    candidate = _candidate_frame(["GOOD", "MISSVOL"])
    config = RunConfig(
        min_history_days=200, min_avg_dollar_volume=1_000_000, data_quality_lookback_days=126
    )

    quality = build_data_quality_frame(
        prices,
        volumes,
        ["GOOD", "MISSVOL", "MISSING", "SPY"],
        candidate,
        config,
        provider="fixture-provider",
        price_sources=pd.DataFrame(
            [
                {"symbol": "GOOD", "price_source": "adjusted-close-fixture"},
                {"symbol": "SPY", "price_source": "benchmark-fixture"},
            ]
        ),
        exclusions=pd.DataFrame([{"symbol": "MISSVOL", "reason": "missing volume data"}]),
        as_of=dates[-1],
    )

    rows = quality.set_index("symbol")
    assert rows.loc["GOOD", "data_quality_status"] == "pass"
    assert rows.loc["GOOD", "price_source"] == "adjusted-close-fixture"
    assert rows.loc["MISSVOL", "data_quality_status"] == "missing_volume"
    assert rows.loc["MISSING", "data_quality_status"] == "missing_price"
    assert rows.loc["SPY", "data_quality_status"] == "benchmark_comparator_only"
    assert rows.loc["GOOD", "missing_ratio"] == 0.0
    assert not bool(rows.loc["MISSVOL", "data_quality_pass"])


@pytest.mark.parametrize(
    ("provider", "price_source"),
    [
        ("yfinance-free-public-data+stooq-fallback", "stooq-daily-close-fallback"),
        (
            "yfinance-free-public-data+finance-datareader-fallback",
            "finance-datareader-close-fallback",
        ),
    ],
)
def test_close_fallback_is_not_tradable_data_quality(provider, price_source):
    dates = pd.bdate_range("2024-01-01", periods=260)
    prices = pd.DataFrame({"STQ": np.linspace(20, 30, len(dates))}, index=dates)
    volumes = pd.DataFrame({"STQ": 1_000_000}, index=dates)
    candidate = _candidate_frame(["STQ"])

    quality = build_data_quality_frame(
        prices,
        volumes,
        ["STQ"],
        candidate,
        RunConfig(min_history_days=200, min_avg_dollar_volume=1_000_000),
        provider=provider,
        price_sources=pd.DataFrame([{"symbol": "STQ", "price_source": price_source}]),
        as_of=dates[-1],
    )

    row = quality.iloc[0]
    assert row["data_quality_status"] == "provider_adjustment_incompatible"
    assert not bool(row["data_quality_pass"])


def test_eligible_filter_retains_benchmark_price_without_candidate_liquidity():
    dates = pd.bdate_range("2024-01-01", periods=260)
    prices = pd.DataFrame(
        {
            "SPY": np.linspace(400, 430, len(dates)),
            "QQQ": np.linspace(300, 345, len(dates)),
            "GOOD": np.linspace(20, 30, len(dates)),
        },
        index=dates,
    )
    volumes = pd.DataFrame({"GOOD": 1_000_000}, index=dates)
    candidate = _candidate_frame(["GOOD"])
    config = RunConfig(
        min_history_days=252,
        min_price=5,
        min_avg_dollar_volume=1_000_000,
        chart_benchmark="QQQ",
    )

    filtered, _, eligible, exclusions = _eligible_filter(prices, volumes, candidate, config)

    assert list(filtered.columns) == ["SPY", "QQQ", "GOOD"]
    assert list(eligible["symbol"]) == ["GOOD"]
    assert "SPY" not in set(exclusions["symbol"])


def test_eligible_filter_excludes_stock_chart_benchmark_from_holdings():
    dates = pd.bdate_range("2024-01-01", periods=260)
    prices = pd.DataFrame(
        {
            "SPY": np.linspace(400, 430, len(dates)),
            "AAPL": np.linspace(175, 220, len(dates)),
            "GOOD": np.linspace(20, 30, len(dates)),
        },
        index=dates,
    )
    volumes = pd.DataFrame(
        {
            "AAPL": 50_000_000,
            "GOOD": 1_000_000,
        },
        index=dates,
    )
    candidate = _candidate_frame(["AAPL", "GOOD"])
    config = RunConfig(
        min_history_days=252,
        min_price=5,
        min_avg_dollar_volume=1_000_000,
        chart_benchmark="AAPL",
    )

    filtered, _, eligible, exclusions = _eligible_filter(prices, volumes, candidate, config)

    assert list(filtered.columns) == ["SPY", "AAPL", "GOOD"]
    assert list(eligible["symbol"]) == ["GOOD"]
    assert "AAPL" not in set(exclusions["symbol"])


def test_data_quality_frame_records_symbol_level_statuses():
    dates = pd.bdate_range("2024-01-01", periods=260)
    prices = pd.DataFrame(
        {
            "SPY": np.linspace(400, 430, len(dates)),
            "QQQ": np.linspace(300, 345, len(dates)),
            "GOOD": np.linspace(20, 30, len(dates)),
            "STALE": list(np.linspace(20, 25, 254)) + [np.nan] * 6,
            "SHORT": [np.nan] * 220 + list(np.linspace(10, 12, 40)),
            "ILLIQ": np.linspace(20, 21, len(dates)),
            "NOVOL": np.linspace(20, 22, len(dates)),
        },
        index=dates,
    )
    volumes = pd.DataFrame(
        {
            "SPY": 1_000_000,
            "GOOD": 1_000_000,
            "STALE": 1_000_000,
            "SHORT": 1_000_000,
            "ILLIQ": 10,
        },
        index=dates,
    )
    candidate = _candidate_frame(["GOOD", "STALE", "SHORT", "ILLIQ", "NOVOL", "MISS"])
    config = RunConfig(
        min_history_days=252,
        min_price=5,
        min_avg_dollar_volume=1_000_000,
        stale_after_days=5,
        chart_benchmark="QQQ",
    )
    _, _, _, exclusions = _eligible_filter(prices, volumes, candidate, config)
    price_sources = pd.DataFrame(
        {"symbol": list(prices.columns), "price_source": ["fixture-adjusted"] * len(prices.columns)}
    )

    quality = build_data_quality_frame(
        prices,
        volumes,
        ["SPY", "QQQ", "GOOD", "STALE", "SHORT", "ILLIQ", "NOVOL", "MISS"],
        candidate,
        config,
        provider="fixture-provider",
        price_sources=price_sources,
        exclusions=exclusions,
        as_of=prices.index.max(),
    )
    statuses = quality.set_index("symbol")["data_quality_status"].to_dict()
    roles = quality.set_index("symbol")["role"].to_dict()

    assert roles["SPY"] == "benchmark"
    assert roles["QQQ"] == "chart_benchmark"
    assert statuses["SPY"] == "benchmark_comparator_only"
    assert statuses["QQQ"] == "benchmark_comparator_only"
    assert statuses["GOOD"] == "pass"
    assert statuses["STALE"] == "below_minimum_price"
    assert statuses["SHORT"] == "insufficient_history"
    assert statuses["ILLIQ"] == "below_liquidity_floor"
    assert statuses["NOVOL"] == "excessive_missing_volume"
    assert statuses["MISS"] == "missing_price"


def test_stooq_fallback_records_symbol_provider_and_cache(monkeypatch, tmp_path):
    dates = pd.bdate_range("2024-01-01", periods=5)
    config = RunConfig(cache_dir=tmp_path, stooq_fallback_limit=1)

    def fake_download(symbol, cfg):
        price = pd.Series(np.linspace(10, 12, len(dates)), index=dates, name=symbol)
        volume = pd.Series(1000, index=dates, name=symbol)
        return price, volume, None, "cache_hit", str(tmp_path / "cached.csv"), 0

    monkeypatch.setattr("factor_lab.live_data._download_stooq_symbol", fake_download)
    prices, volumes, sources = _apply_stooq_fallback(
        pd.DataFrame(index=dates), pd.DataFrame(index=dates), ["MISS"], config
    )
    assert "MISS" in prices.columns
    assert "MISS" in volumes.columns
    row = sources.iloc[0]
    assert row["symbol"] == "MISS"
    assert row["source"] == "stooq-daily-close-fallback"
    assert row["status"] == "cache_hit"
    assert row["cache_path"].endswith("cached.csv")


def test_stooq_symbol_normalizes_share_class_delimiters():
    assert _stooq_symbol("BRK/B") == "brk.b.us"
    assert _stooq_symbol("BF-B") == "bf.b.us"


def test_stooq_fallback_defaults_to_all_missing_symbols(monkeypatch, tmp_path):
    dates = pd.bdate_range("2024-01-01", periods=5)
    config = RunConfig(cache_dir=tmp_path, stooq_fallback_limit=None)

    def fake_download(symbol, cfg):
        price = pd.Series(np.linspace(10, 12, len(dates)), index=dates, name=symbol)
        volume = pd.Series(1000, index=dates, name=symbol)
        return price, volume, None, "fetched", str(tmp_path / f"{symbol}.csv"), 0

    monkeypatch.setattr("factor_lab.live_data._download_stooq_symbol", fake_download)
    prices, volumes, sources = _apply_stooq_fallback(
        pd.DataFrame(index=dates),
        pd.DataFrame(index=dates),
        ["MISS1", "MISS2"],
        config,
    )

    assert set(prices.columns) == {"MISS1", "MISS2"}
    assert set(volumes.columns) == {"MISS1", "MISS2"}
    assert set(sources["symbol"]) == {"MISS1", "MISS2"}


def test_stooq_fallback_replaces_unusable_existing_column(monkeypatch, tmp_path):
    dates = pd.bdate_range("2024-01-01", periods=10)
    prices = pd.DataFrame({"BAD": [np.nan] * 8 + [10.0, 11.0]}, index=dates)
    volumes = pd.DataFrame({"BAD": [np.nan] * len(dates)}, index=dates)
    config = RunConfig(
        cache_dir=tmp_path,
        min_history_days=5,
        min_liquidity_observations=3,
        stooq_fallback_limit=None,
    )

    def fake_download(symbol, cfg):
        price = pd.Series(np.linspace(20, 29, len(dates)), index=dates, name=symbol)
        volume = pd.Series(5_000, index=dates, name=symbol)
        return price, volume, None, "fetched", str(tmp_path / f"{symbol}.csv"), 0

    monkeypatch.setattr("factor_lab.live_data._download_stooq_symbol", fake_download)

    fixed_prices, fixed_volumes, sources = _apply_stooq_fallback(prices, volumes, ["BAD"], config)

    assert fixed_prices["BAD"].iloc[0] == 20.0
    assert fixed_prices["BAD"].notna().sum() == len(dates)
    assert fixed_volumes["BAD"].notna().sum() == len(dates)
    assert sources.iloc[0]["symbol"] == "BAD"


def test_yahoo_chart_fallback_repairs_stale_yfinance_column(monkeypatch, tmp_path):
    dates = pd.bdate_range("2024-01-01", periods=10)
    prices = pd.DataFrame(
        {"STALE": list(np.linspace(20, 26, 7)) + [np.nan, np.nan, np.nan]}, index=dates
    )
    volumes = pd.DataFrame({"STALE": [1_000_000] * 7 + [np.nan, np.nan, np.nan]}, index=dates)
    config = RunConfig(
        cache_dir=tmp_path,
        min_history_days=5,
        min_liquidity_observations=3,
        yahoo_chart_fallback_limit=None,
    )

    def fake_download(symbol, cfg):
        price = pd.Series(np.linspace(30, 39, len(dates)), index=dates, name=symbol)
        volume = pd.Series(2_000_000, index=dates, name=symbol)
        return price, volume, None, "fetched", str(tmp_path / f"{symbol}.csv"), 0

    monkeypatch.setattr("factor_lab.live_data._download_yahoo_chart_symbol", fake_download)

    fixed_prices, fixed_volumes, sources = _apply_yahoo_chart_fallback(
        prices, volumes, ["STALE"], config
    )

    assert fixed_prices["STALE"].iloc[-1] == 39.0
    assert fixed_prices["STALE"].notna().sum() == len(dates)
    assert fixed_volumes["STALE"].notna().sum() == len(dates)
    row = sources.iloc[0]
    assert row["symbol"] == "STALE"
    assert row["source"] == "yahoo-chart-adjusted-daily-fallback"
    assert row["status"] == "fetched"
    assert "adjusted close" in row["note"]


def test_yahoo_chart_cache_rejects_invalid_adjusted_close_payload(tmp_path):
    config = RunConfig(cache_dir=tmp_path)
    cache = _yahoo_chart_cache_path(config, "BAD")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text("Date,Close,Volume\nnot-a-date,abc,1000\n", encoding="utf-8")

    price, _, error, status, _, _ = _download_yahoo_chart_symbol("BAD", config)

    assert price is None
    assert status == "cache_hit_invalid"
    assert "no numeric close prices" in str(error)


def test_nasdaq_latest_repair_fills_only_missing_tail_dates(monkeypatch, tmp_path):
    dates = pd.bdate_range("2024-01-01", periods=10)
    prices = pd.DataFrame(
        {
            "FRESH": np.linspace(100, 109, len(dates)),
            "TAIL": [20.0, 21.0, np.nan, 23.0, 24.0, 25.0, 26.0, np.nan, np.nan, np.nan],
        },
        index=dates,
    )
    volumes = pd.DataFrame(
        {
            "FRESH": 2_000_000,
            "TAIL": [
                1_000_000,
                1_000_000,
                np.nan,
                1_000_000,
                1_000_000,
                1_000_000,
                1_000_000,
                np.nan,
                np.nan,
                np.nan,
            ],
        },
        index=dates,
    )
    config = RunConfig(
        cache_dir=tmp_path,
        min_history_days=5,
        min_liquidity_observations=3,
        stale_after_days=0,
        nasdaq_fallback_limit=None,
    )

    def fake_download(symbol, cfg):
        assert symbol == "TAIL"
        price = pd.Series(np.linspace(30, 39, len(dates)), index=dates, name=symbol)
        volume = pd.Series(3_000_000, index=dates, name=symbol)
        return price, volume, None, "fetched", str(tmp_path / f"{symbol}.csv"), 0

    monkeypatch.setattr("factor_lab.live_data._download_nasdaq_symbol", fake_download)

    fixed_prices, fixed_volumes, sources = _apply_nasdaq_latest_repair(
        prices, volumes, ["TAIL"], config
    )

    assert fixed_prices["TAIL"].iloc[0] == 20.0
    assert np.isnan(fixed_prices["TAIL"].iloc[2])
    assert fixed_prices["TAIL"].iloc[-1] == 39.0
    assert fixed_prices["TAIL"].notna().sum() == len(dates) - 1
    assert fixed_volumes["TAIL"].iloc[0] == 1_000_000
    assert np.isnan(fixed_volumes["TAIL"].iloc[2])
    assert fixed_volumes["TAIL"].iloc[-1] == 3_000_000
    row = sources.iloc[0]
    assert row["symbol"] == "TAIL"
    assert row["source"] == "nasdaq-latest-close-repair"
    assert row["status"] == "fetched"
    assert row["records"] == 3
    assert "historical adjusted prices were preserved" in row["provider_adjustment_note"]


def test_nasdaq_latest_repair_requires_existing_adjusted_history(monkeypatch, tmp_path):
    dates = pd.bdate_range("2024-01-01", periods=10)
    prices = pd.DataFrame({"FRESH": np.linspace(100, 109, len(dates))}, index=dates)
    volumes = pd.DataFrame({"FRESH": 2_000_000}, index=dates)
    config = RunConfig(
        cache_dir=tmp_path, min_history_days=5, stale_after_days=0, nasdaq_fallback_limit=None
    )

    def unexpected_download(symbol, cfg):  # pragma: no cover - assertion path
        raise AssertionError(f"Nasdaq full-history replacement should not run for {symbol}")

    monkeypatch.setattr(
        "factor_lab.live_data._download_nasdaq_symbol", unexpected_download
    )

    fixed_prices, fixed_volumes, sources = _apply_nasdaq_latest_repair(
        prices, volumes, ["MISSING"], config
    )

    pd.testing.assert_frame_equal(fixed_prices, prices)
    pd.testing.assert_frame_equal(fixed_volumes, volumes.reindex(index=prices.index))
    assert sources.empty


def test_nasdaq_cache_rejects_invalid_close_payload(tmp_path):
    config = RunConfig(cache_dir=tmp_path)
    cache = _nasdaq_cache_path(config, "BAD")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text("Date,Close,Volume\n2024-01-02,not-a-number,1000\n", encoding="utf-8")

    price, _, error, status, _, _ = _download_nasdaq_symbol("BAD", config)

    assert price is None
    assert status == "cache_hit_invalid"
    assert "no numeric close prices" in str(error)


def test_finance_datareader_fallback_records_symbol_provider(monkeypatch, tmp_path):
    dates = pd.bdate_range("2024-01-01", periods=5)
    config = RunConfig(cache_dir=tmp_path, finance_datareader_fallback_limit=None)

    def fake_download(symbol, cfg):
        price = pd.Series(np.linspace(20, 22, len(dates)), index=dates, name=symbol)
        volume = pd.Series(2000, index=dates, name=symbol)
        return price, volume, None, "fetched", str(tmp_path / f"{symbol}.csv"), 0

    monkeypatch.setattr(
        "factor_lab.live_data._download_finance_datareader_symbol", fake_download
    )
    prices, volumes, sources = _apply_finance_datareader_fallback(
        pd.DataFrame(index=dates),
        pd.DataFrame(index=dates),
        ["FDR1", "FDR2"],
        config,
    )

    assert set(prices.columns) == {"FDR1", "FDR2"}
    assert set(volumes.columns) == {"FDR1", "FDR2"}
    assert set(sources["source"]) == {"finance-datareader-close-fallback"}
    assert set(sources["symbol"]) == {"FDR1", "FDR2"}


def test_corrupt_provider_caches_return_invalid_status_without_crashing(tmp_path):
    config = RunConfig(cache_dir=tmp_path)
    stooq_cache = _stooq_cache_path(config, "BAD")
    fdr_cache = _finance_datareader_cache_path(config, "BAD")
    stooq_cache.parent.mkdir(parents=True, exist_ok=True)
    fdr_cache.parent.mkdir(parents=True, exist_ok=True)
    stooq_cache.write_text("Date,Close\nnot-a-date,abc\n", encoding="utf-8")
    fdr_cache.write_text("Date,Close\nnot-a-date,abc\n", encoding="utf-8")

    stooq_price, _, stooq_error, stooq_status, _, _ = _download_stooq_symbol("BAD", config)
    fdr_price, _, fdr_error, fdr_status, _, _ = _download_finance_datareader_symbol("BAD", config)

    assert stooq_price is None
    assert stooq_status == "cache_hit_invalid"
    assert "invalid stooq cache" in str(stooq_error)
    assert fdr_price is None
    assert fdr_status == "cache_hit_invalid"
    assert "invalid FinanceDataReader cache" in str(fdr_error)


def test_provider_caches_reject_nonnumeric_close_values(tmp_path):
    config = RunConfig(cache_dir=tmp_path)
    stooq_cache = _stooq_cache_path(config, "BADNUM")
    fdr_cache = _finance_datareader_cache_path(config, "BADNUM")
    stooq_cache.parent.mkdir(parents=True, exist_ok=True)
    fdr_cache.parent.mkdir(parents=True, exist_ok=True)
    payload = "Date,Close,Volume\n2024-01-02,abc,1000\n2024-01-03,,2000\n"
    stooq_cache.write_text(payload, encoding="utf-8")
    fdr_cache.write_text(payload, encoding="utf-8")

    stooq_price, _, stooq_error, stooq_status, _, _ = _download_stooq_symbol("BADNUM", config)
    fdr_price, _, fdr_error, fdr_status, _, _ = _download_finance_datareader_symbol(
        "BADNUM", config
    )

    assert stooq_price is None
    assert stooq_status == "cache_hit_invalid"
    assert "no numeric close prices" in str(stooq_error)
    assert fdr_price is None
    assert fdr_status == "cache_hit_invalid"
    assert "no numeric close prices" in str(fdr_error)


def test_live_download_preserves_yfinance_yahoo_chart_stooq_finance_datareader_order(
    monkeypatch, tmp_path
):
    dates = pd.bdate_range("2024-01-01", periods=8)
    config = RunConfig(
        cache_dir=tmp_path,
        start_date="2024-01-01",
        end_date="2024-01-12",
        min_history_days=2,
        min_price=1,
        min_avg_dollar_volume=0,
        min_liquidity_observations=2,
        stale_after_days=10_000,
        universe=["YF", "YCH", "STQ", "FDRX"],
        stooq_fallback_limit=None,
        finance_datareader_fallback_limit=None,
    )
    candidate = _candidate_frame(["YF", "YCH", "STQ", "FDRX"])
    monkeypatch.setattr(
        "factor_lab.live_data._candidate_universe",
        lambda _: (
            candidate,
            pd.DataFrame([{"source": "fixture-universe", "status": "loaded", "records": 4}]),
        ),
    )
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace())

    def fake_yfinance(symbols, cfg):
        prices = pd.DataFrame(
            {
                "SPY": np.linspace(400, 408, len(dates)),
                "YF": np.linspace(10, 18, len(dates)),
            },
            index=dates,
        )
        volumes = pd.DataFrame({"SPY": 1_000_000, "YF": 1_000_000}, index=dates)
        return (
            prices,
            prices.copy(),
            volumes,
            pd.DataFrame(0.0, index=dates, columns=prices.columns),
            pd.DataFrame(
                [
                    {
                        "source": "yfinance-adjusted-daily",
                        "status": "fetched",
                        "records": 2,
                        "requested_symbols": ",".join(symbols),
                        "returned_symbols": "SPY,YF",
                        "missing_symbols": "YCH,STQ,FDRX",
                    }
                ]
            ),
        )

    def fake_yahoo_chart(symbol, cfg):
        if symbol != "YCH":
            return None, None, "not found", "failed", "cache", 0
        return (
            pd.Series(np.linspace(15, 23, len(dates)), index=dates, name=symbol),
            pd.Series(1_500_000, index=dates, name=symbol),
            None,
            "fetched",
            "cache",
            0,
        )

    def fake_stooq(symbol, cfg):
        if symbol != "STQ":
            return None, None, "not found", "failed", "cache", 0
        return (
            pd.Series(np.linspace(20, 28, len(dates)), index=dates, name=symbol),
            pd.Series(2_000_000, index=dates, name=symbol),
            None,
            "fetched",
            "cache",
            0,
        )

    def fake_fdr(symbol, cfg):
        if symbol != "FDRX":
            return None, None, "not found", "failed", "cache", 0
        return (
            pd.Series(np.linspace(30, 38, len(dates)), index=dates, name=symbol),
            pd.Series(3_000_000, index=dates, name=symbol),
            None,
            "fetched",
            "cache",
            0,
        )

    monkeypatch.setattr("factor_lab.live_data._download_yfinance", fake_yfinance)
    monkeypatch.setattr(
        "factor_lab.live_data._download_yahoo_chart_symbol", fake_yahoo_chart
    )
    monkeypatch.setattr("factor_lab.live_data._download_stooq_symbol", fake_stooq)
    monkeypatch.setattr(
        "factor_lab.live_data._download_finance_datareader_symbol", fake_fdr
    )

    result = download_live_data(config)

    sources = result.data_sources["source"].tolist()
    assert sources.index("yfinance-adjusted-daily") < sources.index(
        "yahoo-chart-adjusted-daily-fallback"
    )
    assert sources.index("yahoo-chart-adjusted-daily-fallback") < sources.index(
        "stooq-daily-close-fallback"
    )
    assert sources.index("yfinance-adjusted-daily") < sources.index("stooq-daily-close-fallback")
    assert sources.index("stooq-daily-close-fallback") < sources.index(
        "finance-datareader-close-fallback"
    )
    assert {"YF", "YCH", "STQ", "FDRX"}.issubset(set(result.prices.columns))
    summary = result.data_sources[
        result.data_sources["source"].eq("acquisition-run-diagnostics")
    ].iloc[-1]
    assert int(summary["requested_price_symbols"]) == 4
    assert int(summary["returned_price_symbols"]) == 4
    assert int(summary["eligible_price_symbols"]) == 4
    assert pd.isna(summary["liquidity_eligible_symbols"])


def test_live_download_attempts_free_fallback_when_yfinance_unavailable(monkeypatch, tmp_path):
    dates = pd.bdate_range("2024-01-01", periods=8)
    config = RunConfig(
        cache_dir=tmp_path,
        start_date="2024-01-01",
        end_date="2024-01-12",
        min_history_days=2,
        min_price=1,
        min_avg_dollar_volume=0,
        min_liquidity_observations=2,
        stale_after_days=10_000,
        universe=["AAA"],
        yahoo_chart_fallback_limit=0,
        stooq_fallback_limit=None,
        finance_datareader_fallback_limit=0,
    )
    candidate = _candidate_frame(["AAA"])
    monkeypatch.setattr(
        "factor_lab.live_data._candidate_universe",
        lambda _: (
            candidate,
            pd.DataFrame([{"source": "fixture-universe", "status": "loaded", "records": 1}]),
        ),
    )
    monkeypatch.setitem(sys.modules, "yfinance", None)

    def fake_stooq(symbol, cfg):
        return (
            pd.Series(np.linspace(20, 28, len(dates)), index=dates, name=symbol),
            pd.Series(2_000_000, index=dates, name=symbol),
            None,
            "fetched",
            str(tmp_path / f"{symbol}.csv"),
            0,
        )

    monkeypatch.setattr("factor_lab.live_data._download_stooq_symbol", fake_stooq)

    result = download_live_data(config)

    assert result.live_error is None
    assert result.provider == "stooq-fallback"
    assert {"SPY", "AAA"}.issubset(set(result.prices.columns))
    yf_row = result.data_sources[result.data_sources["source"].eq("yfinance-adjusted-daily")].iloc[
        0
    ]
    assert yf_row["status"] == "unavailable"
    assert "stooq-daily-close-fallback" in set(result.data_sources["source"])
    summary = result.data_sources[
        result.data_sources["source"].eq("acquisition-run-diagnostics")
    ].iloc[-1]
    assert int(summary["returned_price_symbols"]) == 1
    assert int(summary["eligible_price_symbols"]) == 1


def test_yfinance_chunk_uses_csv_json_price_cache_without_network(tmp_path):
    from factor_lab.live_data import (
        _download_yfinance_chunk,
        _price_cache_path,
        _write_price_cache,
    )

    config = RunConfig(cache_dir=tmp_path, start_date="2024-01-01", end_date="2024-01-10")
    symbols = ["AAA", "BBB"]
    dates = pd.bdate_range("2024-01-01", periods=3)
    cached_prices = pd.DataFrame({"AAA": [1, 2, 3], "BBB": [4, 5, 6]}, index=dates)
    cached_volumes = pd.DataFrame({"AAA": [10, 10, 10], "BBB": [20, 20, 20]}, index=dates)
    cache_path = _price_cache_path(config, "yfinance", symbols)
    _write_price_cache(
        cache_path,
        cached_prices,
        cached_prices,
        cached_volumes,
        pd.DataFrame(0.0, index=dates, columns=cached_prices.columns),
        provider="yfinance",
        symbols=symbols,
    )
    prices, raw_closes, volumes, stock_splits, status = _download_yfinance_chunk(symbols, config)
    pd.testing.assert_frame_equal(prices, cached_prices, check_freq=False)
    pd.testing.assert_frame_equal(raw_closes, cached_prices, check_freq=False)
    pd.testing.assert_frame_equal(volumes, cached_volumes, check_freq=False)
    assert stock_splits.eq(0.0).all().all()
    assert status["status"] == "cache_hit"
    assert status["cache_path"] == str(cache_path)
    assert status["cache_format"] == "csv+json"
    assert cache_path.suffix == ".json"
    assert not list(tmp_path.rglob("*.pkl"))


def test_yfinance_cache_v3_records_hashes_timestamps_asof_and_symbols(tmp_path):
    from factor_lab.live_data import (
        PRICE_CACHE_VERSION,
        _price_cache_component_paths,
        _price_cache_path,
        _read_price_cache,
        _write_price_cache,
    )

    config = RunConfig(cache_dir=tmp_path, start_date="2024-01-01", end_date="2024-01-10")
    symbols = ["AAA", "BBB"]
    dates = pd.bdate_range("2024-01-01", periods=3)
    prices = pd.DataFrame({"AAA": [1.0, 2.0, 3.0], "BBB": [4.0, 5.0, 6.0]}, index=dates)
    volumes = pd.DataFrame({"AAA": [10.0] * 3, "BBB": [20.0] * 3}, index=dates)
    metadata_path = _price_cache_path(config, "yfinance", symbols)

    _write_price_cache(
        metadata_path,
        prices,
        prices,
        volumes,
        pd.DataFrame(0.0, index=dates, columns=prices.columns),
        provider="yfinance",
        symbols=symbols,
    )
    paths = _price_cache_component_paths(metadata_path)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    assert metadata["version"] == PRICE_CACHE_VERSION == 4
    assert metadata["provider"] == "yfinance"
    assert metadata["symbols"] == metadata["returnedSymbols"] == symbols
    assert metadata["observedAsOf"] == dates[-1].date().isoformat()
    assert datetime.fromisoformat(metadata["createdAtUtc"]).tzinfo is not None
    assert datetime.fromisoformat(metadata["checkedAtUtc"]).tzinfo is not None
    for name in ("prices", "raw_closes", "volumes", "stock_splits"):
        encoded = paths[name].read_bytes()
        reference = metadata["components"][name]
        assert reference["file"] == paths[name].name
        assert reference["bytes"] == len(encoded)
        assert reference["sha256"] == hashlib.sha256(encoded).hexdigest()

    original_created = metadata["createdAtUtc"]
    metadata["checkedAtUtc"] = "2000-01-01T00:00:00+00:00"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    cached = _read_price_cache(
        metadata_path,
        config=config,
        provider="yfinance",
        symbols=symbols,
    )
    checked = json.loads(metadata_path.read_text(encoding="utf-8"))

    assert cached is not None
    assert checked["createdAtUtc"] == original_created
    assert checked["checkedAtUtc"] != "2000-01-01T00:00:00+00:00"


def test_yfinance_cache_same_asof_content_mutation_changes_component_identity(tmp_path):
    from factor_lab.live_data import (
        _price_cache_path,
        _read_price_cache,
        _write_price_cache,
    )

    config = RunConfig(cache_dir=tmp_path, start_date="2024-01-01", end_date="2024-01-10")
    symbols = ["AAA"]
    dates = pd.bdate_range("2024-01-01", periods=3)
    first = pd.DataFrame({"AAA": [1.0, 2.0, 3.0]}, index=dates)
    revised = pd.DataFrame({"AAA": [1.0, 2.25, 3.0]}, index=dates)
    volumes = pd.DataFrame({"AAA": [100.0, 110.0, 120.0]}, index=dates)
    metadata_path = _price_cache_path(config, "yfinance", symbols)

    _write_price_cache(
        metadata_path,
        first,
        first,
        volumes,
        pd.DataFrame(0.0, index=dates, columns=first.columns),
        provider="yfinance",
        symbols=symbols,
    )
    before = json.loads(metadata_path.read_text(encoding="utf-8"))
    _write_price_cache(
        metadata_path,
        revised,
        revised,
        volumes,
        pd.DataFrame(0.0, index=dates, columns=revised.columns),
        provider="yfinance",
        symbols=symbols,
    )
    after = json.loads(metadata_path.read_text(encoding="utf-8"))
    cached = _read_price_cache(
        metadata_path,
        config=config,
        provider="yfinance",
        symbols=symbols,
    )

    assert before["observedAsOf"] == after["observedAsOf"] == dates[-1].date().isoformat()
    assert before["components"]["prices"]["sha256"] != after["components"]["prices"]["sha256"]
    assert cached is not None
    assert cached[0].loc[dates[1], "AAA"] == pytest.approx(2.25)


def test_yfinance_component_tampering_bypasses_cache_and_refetches(monkeypatch, tmp_path):
    from factor_lab.live_data import (
        _download_yfinance_chunk,
        _price_cache_component_paths,
        _price_cache_path,
        _read_price_cache,
        _write_price_cache,
    )

    config = RunConfig(cache_dir=tmp_path, start_date="2024-01-01", end_date="2024-01-10")
    symbols = ["AAA"]
    dates = pd.bdate_range("2024-01-01", periods=3)
    cached_prices = pd.DataFrame({"AAA": [1.0, 2.0, 3.0]}, index=dates)
    cached_volumes = pd.DataFrame({"AAA": [10.0, 10.0, 10.0]}, index=dates)
    metadata_path = _price_cache_path(config, "yfinance", symbols)
    _write_price_cache(
        metadata_path,
        cached_prices,
        cached_prices,
        cached_volumes,
        pd.DataFrame(0.0, index=dates, columns=cached_prices.columns),
        provider="yfinance",
        symbols=symbols,
    )
    component = _price_cache_component_paths(metadata_path)["prices"]
    encoded = component.read_bytes()
    tampered = encoded.replace(b",1.0\n", b",9.0\n", 1)
    assert tampered != encoded and len(tampered) == len(encoded)
    component.write_bytes(tampered)

    assert (
        _read_price_cache(
            metadata_path,
            config=config,
            provider="yfinance",
            symbols=symbols,
        )
        is None
    )
    fresh_raw = pd.DataFrame(
        {"Adj Close": [10.0, 11.0, 12.0], "Close": [10.0, 11.0, 12.0], "Volume": 500.0},
        index=dates,
    )
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=lambda **_: fresh_raw))

    prices, _, _, _, status = _download_yfinance_chunk(symbols, config)

    assert status["status"] == "fetched"
    assert prices["AAA"].tolist() == [10.0, 11.0, 12.0]
    rewritten = json.loads(metadata_path.read_text(encoding="utf-8"))
    rewritten_bytes = _price_cache_component_paths(metadata_path)["prices"].read_bytes()
    assert (
        rewritten["components"]["prices"]["sha256"] == hashlib.sha256(rewritten_bytes).hexdigest()
    )


@pytest.mark.parametrize(("refresh", "stale"), [(True, False), (False, True)])
def test_yfinance_refresh_flag_and_ttl_bypass_cache(monkeypatch, tmp_path, refresh, stale):
    from factor_lab.live_data import (
        _download_yfinance_chunk,
        _price_cache_path,
        _write_price_cache,
    )

    config = RunConfig(
        cache_dir=tmp_path,
        start_date="2024-01-01",
        end_date="2024-01-10",
        refresh_market_data=refresh,
        market_cache_max_age_hours=1.0,
    )
    symbols = ["AAA"]
    dates = pd.bdate_range("2024-01-01", periods=3)
    old = pd.DataFrame({"AAA": [1.0, 2.0, 3.0]}, index=dates)
    volumes = pd.DataFrame({"AAA": [10.0, 10.0, 10.0]}, index=dates)
    metadata_path = _price_cache_path(config, "yfinance", symbols)
    _write_price_cache(
        metadata_path,
        old,
        old,
        volumes,
        pd.DataFrame(0.0, index=dates, columns=old.columns),
        provider="yfinance",
        symbols=symbols,
    )
    if stale:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["createdAtUtc"] = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    fresh_raw = pd.DataFrame(
        {"Adj Close": [20.0, 21.0, 22.0], "Close": [20.0, 21.0, 22.0], "Volume": 500.0},
        index=dates,
    )
    calls = []

    def fake_download(**kwargs):
        calls.append(kwargs)
        return fresh_raw

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=fake_download))

    prices, _, _, _, status = _download_yfinance_chunk(symbols, config)

    assert len(calls) == 1
    assert status["status"] == "fetched"
    assert prices["AAA"].iloc[-1] == 22.0


@pytest.mark.parametrize(("refresh", "stale"), [(True, False), (False, True)])
def test_single_symbol_fallback_refresh_flag_and_ttl_bypass_cache(
    monkeypatch, tmp_path, refresh, stale
):
    from factor_lab.live_data import _download_stooq_symbol

    config = RunConfig(
        cache_dir=tmp_path,
        start_date="2024-01-01",
        end_date="2024-01-10",
        refresh_market_data=refresh,
        market_cache_max_age_hours=1.0,
    )
    cache_path = _stooq_cache_path(config, "AAA")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        "Date,Close,Volume\n2024-01-02,1.0,100\n2024-01-03,2.0,100\n",
        encoding="utf-8",
    )
    if stale:
        old = time.time() - 2 * 60 * 60
        os.utime(cache_path, (old, old))

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"Date,Close,Volume\n2024-01-02,10.0,500\n2024-01-03,12.0,500\n"

    calls = []

    def fake_urlopen(*args, **kwargs):
        calls.append((args, kwargs))
        return Response()

    monkeypatch.setattr("factor_lab.live_data.urlopen", fake_urlopen)

    price, _, error, status, _, _ = _download_stooq_symbol("AAA", config)

    assert len(calls) == 1
    assert error is None
    assert status == "fetched"
    assert price is not None and price.iloc[-1] == 12.0


def test_yfinance_chunk_does_not_use_pickle_cache(monkeypatch, tmp_path):
    import factor_lab.live_data as data
    from factor_lab.live_data import _download_yfinance_chunk

    monkeypatch.setattr(
        pd,
        "read_pickle",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("read_pickle used")),
    )
    monkeypatch.setattr(
        pd,
        "to_pickle",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("to_pickle used")),
    )

    dates = pd.bdate_range("2024-01-01", periods=2)
    raw = pd.DataFrame({"Close": [10.0, 11.0], "Volume": [100.0, 120.0]}, index=dates)

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=lambda **kwargs: raw))

    config = RunConfig(cache_dir=tmp_path, start_date="2024-01-01", end_date="2024-01-10")
    prices, raw_closes, volumes, stock_splits, status = _download_yfinance_chunk(["AAA"], config)

    assert status["status"] == "fetched"
    assert list(prices.columns) == ["AAA"]
    assert list(raw_closes.columns) == ["AAA"]
    assert list(volumes.columns) == ["AAA"]
    assert list(stock_splits.columns) == ["AAA"]
    assert not list(tmp_path.rglob("*.pkl"))
    assert not str(status.get("cache_path", "")).endswith(".pkl")
    source = inspect.getsource(data)
    assert "read_pickle" not in source
    assert "to_pickle" not in source
    assert ".pkl" not in source


def test_yfinance_chunk_passes_inclusive_config_end_date(monkeypatch, tmp_path):
    from factor_lab.live_data import _download_yfinance_chunk

    captured = {}
    dates = pd.bdate_range("2024-01-01", periods=3)
    columns = pd.MultiIndex.from_tuples(
        [
            ("Close", "AAA"),
            ("Close", "BBB"),
            ("Volume", "AAA"),
            ("Volume", "BBB"),
        ]
    )
    raw = pd.DataFrame(
        [
            [1.0, 4.0, 100.0, 400.0],
            [2.0, 5.0, 100.0, 400.0],
            [3.0, 6.0, 100.0, 400.0],
        ],
        index=dates,
        columns=columns,
    )

    def fake_download(**kwargs):
        captured.update(kwargs)
        return raw

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=fake_download))

    config = RunConfig(cache_dir=tmp_path, start_date="2024-01-01", end_date="2024-01-10")
    prices, raw_closes, volumes, stock_splits, status = _download_yfinance_chunk(
        ["AAA", "BBB"], config
    )

    assert captured["end"] == "2024-01-11"
    assert captured["start"] == "2024-01-01"
    assert status["status"] == "fetched"
    assert list(prices.columns) == ["AAA", "BBB"]
    assert list(raw_closes.columns) == ["AAA", "BBB"]
    assert list(volumes.columns) == ["AAA", "BBB"]
    assert list(stock_splits.columns) == ["AAA", "BBB"]


def test_yfinance_chunk_leaves_open_ended_download_without_end(monkeypatch, tmp_path):
    from factor_lab.live_data import _download_yfinance_chunk

    captured = {}
    dates = pd.bdate_range("2024-01-01", periods=2)
    raw = pd.DataFrame({"Close": [10.0, 11.0], "Volume": [100.0, 120.0]}, index=dates)

    def fake_download(**kwargs):
        captured.update(kwargs)
        return raw

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=fake_download))

    config = RunConfig(cache_dir=tmp_path, start_date="2024-01-01", end_date=None)
    prices, raw_closes, _, _, status = _download_yfinance_chunk(["AAA"], config)

    assert captured["end"] is None
    assert status["status"] == "fetched"
    assert list(prices.columns) == ["AAA"]
    assert list(raw_closes.columns) == ["AAA"]


def test_provider_summary_marks_cached_stooq_as_mixed():
    from factor_lab.live_data import _provider_label_from_sources

    stooq_sources = pd.DataFrame(
        [
            {
                "source": "stooq-daily-close-fallback",
                "symbol": "MISS",
                "status": "cache_hit",
                "records": 1,
            }
        ]
    )
    assert _provider_label_from_sources(stooq_sources) == "yfinance-free-public-data+stooq-fallback"
    fdr_sources = pd.DataFrame(
        [
            {
                "source": "finance-datareader-close-fallback",
                "symbol": "MISS2",
                "status": "fetched",
                "records": 1,
            }
        ]
    )
    assert (
        _provider_label_from_sources(stooq_sources, fdr_sources)
        == "yfinance-free-public-data+stooq-fallback+finance-datareader-fallback"
    )
    yahoo_chart_sources = pd.DataFrame(
        [
            {
                "source": "yahoo-chart-adjusted-daily-fallback",
                "symbol": "YCH",
                "status": "fetched",
                "records": 1,
            }
        ]
    )
    nasdaq_sources = pd.DataFrame(
        [
            {
                "source": "nasdaq-latest-close-repair",
                "symbol": "TAIL",
                "status": "fetched",
                "records": 2,
            }
        ]
    )
    assert (
        _provider_label_from_sources(
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame([{"source": "yfinance-adjusted-daily", "records": 1}]),
            yahoo_chart_sources,
            nasdaq_sources,
        )
        == "yfinance-free-public-data+yahoo-chart-fallback+nasdaq-latest-repair"
    )
    assert _provider_label_from_sources(pd.DataFrame()) == "yfinance-free-public-data"


def test_build_eligibility_mask_uses_rebalance_date_liquidity_and_history():
    from factor_lab.live_data import build_eligibility_mask

    dates = pd.bdate_range("2024-01-01", periods=80)
    prices = pd.DataFrame(
        {
            "GOOD": np.linspace(20, 30, len(dates)),
            "LATE": [np.nan] * 30 + list(np.linspace(20, 25, 50)),
            "LOWP": np.linspace(1, 2, len(dates)),
            "ILLIQ": np.linspace(20, 21, len(dates)),
        },
        index=dates,
    )
    volumes = pd.DataFrame(
        {
            "GOOD": 1_000_000,
            "LATE": 1_000_000,
            "LOWP": 1_000_000,
            "ILLIQ": 10,
        },
        index=dates,
    )
    config = RunConfig(
        min_history_days=40,
        min_price=5,
        min_avg_dollar_volume=1_000_000,
        min_liquidity_observations=20,
        max_price_missing_ratio=0.50,
    )

    mask = build_eligibility_mask(prices, volumes, config)

    assert mask.loc[dates[45], "GOOD"]
    assert not mask.loc[dates[45], "LATE"]
    assert mask.loc[dates[-1], "LATE"]
    assert not mask["LOWP"].any()
    assert not mask.loc[dates[-1], "ILLIQ"]


def test_aggressive_profile_lowers_endpoint_discovery_not_configured_gate():
    dates = pd.bdate_range("2024-01-01", periods=260)
    prices = pd.DataFrame({"MID": np.linspace(10, 12, len(dates))}, index=dates)
    volumes = pd.DataFrame({"MID": 150_000}, index=dates)  # about $1.8m ADV, below default $5m.
    candidate = _candidate_frame(["MID"])
    aggressive = RunConfig(
        universe_profile="aggressive_stock_only", min_avg_dollar_volume=5_000_000
    )
    large = RunConfig(universe_profile="large_liquid", min_avg_dollar_volume=5_000_000)

    aggressive_prices, _, aggressive_eligible, _ = _eligible_filter(
        prices, volumes, candidate, aggressive
    )
    large_prices, _, large_eligible, _ = _eligible_filter(prices, volumes, candidate, large)

    assert list(aggressive_prices.columns) == ["MID"]
    assert aggressive_eligible.empty
    assert list(large_prices.columns) == ["MID"]
    assert large_eligible.empty
    assert aggressive.min_avg_dollar_volume == 5_000_000
