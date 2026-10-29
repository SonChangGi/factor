from datetime import datetime, timezone
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from factor_lab import integrated_automation as automation
from factor_lab.integrated_data import collect_integrated_market


def _provider(symbols, *, missing=()):
    dates = pd.to_datetime(["2026-10-27", "2026-10-28"])
    values = {
        "Adj Close": 10.0,
        "Close": 10.0,
        "Open": 9.0,
        "High": 11.0,
        "Low": 8.0,
        "Volume": 50000.0,
        "Dividends": 0.0,
        "Stock Splits": 0.0,
    }
    frame = pd.DataFrame({(f, s): [v, v] for s in symbols for f, v in values.items()}, index=dates)
    for symbol in missing:
        frame.loc[dates[-1], ("Adj Close", symbol)] = np.nan
    return frame


def test_only_new_day_missing_gets_fresh_bounded_retry_and_full_history_is_preserved(
    tmp_path, monkeypatch
):
    import yfinance as yf

    calls = []

    def download(symbols, **kwargs):
        calls.append(symbols)
        return _provider(symbols, missing=["HUBB"] if len(symbols) > 1 else [])

    monkeypatch.setattr(yf, "download", download)
    monkeypatch.setattr("factor_lab.integrated_data.time.sleep", lambda _: None)
    result = collect_integrated_market(
        tmp_path,
        start="2010-01-01",
        end="2026-10-29",
        symbols=["HUBB"],
        target_session="2026-10-28",
        required_target_symbols=["HUBB"],
    )
    assert calls[1:] == [["HUBB"]]
    assert result.prices.HUBB.to_list() == [10.0, 10.0]
    receipt = result.metadata["receipts"][-1]
    assert receipt["retryReason"] == "missing_target_session"
    assert len(list((tmp_path / "downloads").glob("*.csv.gz"))) == 2


def test_persistent_new_day_gap_is_not_filled_or_retried_forever(tmp_path, monkeypatch):
    import yfinance as yf

    calls = []

    def download(symbols, **kwargs):
        calls.append(symbols)
        return _provider(symbols, missing=["HUBB"])

    monkeypatch.setattr(yf, "download", download)
    monkeypatch.setattr("factor_lab.integrated_data.time.sleep", lambda _: None)
    result = collect_integrated_market(
        tmp_path,
        start="2010-01-01",
        end="2026-10-29",
        symbols=["HUBB"],
        target_session="2026-10-28",
        required_target_symbols=["HUBB"],
    )
    assert calls[1:] == [["HUBB"], ["HUBB"]]
    assert result.prices.HUBB.iloc[0] == 10.0 and pd.isna(result.prices.HUBB.iloc[-1])
    assert "HUBB" in result.metadata["targetSessionMissingSymbols"]
    baseline = {
        "data": {"asOf": "2026-10-27"},
        "factors": [{"holdings": [{"symbol": "HUBB", "weight": 0.066}]}],
    }
    with pytest.raises(automation.RefreshInputError, match="Required holding") as error:
        automation.validate_required_valuations(result, baseline, "2026-10-28")
    assert error.value.code == "held_quote_missing" and error.value.symbols == ["HUBB"]


def test_required_valuation_follows_cash_claim_stock_exchange_and_approved_valuation_mark():
    baseline = {
        "data": {"asOf": "2026-10-27"},
        "selection": {"holdings": [{"symbol": "CASH", "weight": 0.2}]},
        "factors": [
            {"holdings": [{"symbol": "OLD", "weight": 0.4}, {"symbol": "HALT", "weight": 0.4}]}
        ],
    }
    dates = pd.to_datetime(["2026-10-28"])
    prices = pd.DataFrame({"NEW": [12.0], "HALT": [np.nan]}, index=dates)
    marks = pd.DataFrame({"NEW": [12.0], "HALT": [11.0]}, index=dates)
    market = SimpleNamespace(
        prices=prices,
        valuation_prices=marks,
        metadata={
            "corporateActions": [
                {"symbol": "CASH", "targetSymbol": None, "cashPerUnit": 95.0, "date": "2026-10-28"},
                {"symbol": "OLD", "targetSymbol": "NEW", "unitRatio": 2.0, "date": "2026-10-28"},
            ]
        },
    )
    assert (
        automation.validate_required_valuations(market, baseline, "2026-10-28")["valuedHeldSymbols"]
        == 2
    )
    marks.at[dates[0], "NEW"] = np.nan
    with pytest.raises(automation.RefreshInputError) as error:
        automation.validate_required_valuations(market, baseline, "2026-10-28")
    assert error.value.symbols == ["NEW"]


def _probe_site(tmp_path, monkeypatch):
    site = tmp_path / "site"
    (site / "data").mkdir(parents=True)
    (site / "data/integrated-result.json").write_text(
        json.dumps(
            {
                "schemaVersion": "integrated-factor/v1",
                "data": {"asOf": "2026-10-27"},
                "selection": {"holdings": [{"symbol": "HUBB", "weight": 1.0}]},
            }
        )
    )
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({"quotes": [], "valuationMarks": [], "exchanges": []}))
    monkeypatch.setattr(automation, "POLICY", policy)
    return site, policy


def test_probe_wait_is_bounded_and_only_missing_symbols_are_requeried(tmp_path, monkeypatch):
    site, policy = _probe_site(tmp_path, monkeypatch)
    calls, waits = [], []

    def download(symbols, **kwargs):
        calls.append(symbols)
        assert kwargs["threads"] is False
        return _provider(symbols, missing=["HUBB"] if len(calls) < 3 else [])

    report = automation.provider_ready(
        site,
        tmp_path / "probe",
        now=datetime(2026, 10, 29, 6, tzinfo=timezone.utc),
        sleep=waits.append,
        download=download,
    )
    assert waits == [30, 30] and calls[1:] == [["HUBB"], ["HUBB"]]
    assert report["status"] == "ready" and report["attempts"] == 3


def test_verified_exact_session_policy_quote_admits_probe_but_does_not_invent_inputs(
    tmp_path, monkeypatch
):
    site, policy = _probe_site(tmp_path, monkeypatch)
    policy.write_text(
        json.dumps(
            {
                "quotes": [{"symbol": "HUBB", "date": "2026-10-28", "adjustedClose": 437.33}],
                "valuationMarks": [],
                "exchanges": [],
            }
        )
    )
    calls = []

    def download(symbols, **kwargs):
        calls.append(symbols)
        return _provider(symbols)

    result = automation.provider_ready(
        site,
        tmp_path / "probe",
        now=datetime(2026, 10, 29, 6, tzinfo=timezone.utc),
        download=download,
    )
    assert all("HUBB" not in s for s in calls) and result["status"] == "ready"
    # Evidence from an earlier date cannot waive the current observation.
    policy.write_text(policy.read_text().replace("2026-10-28", "2026-10-27"))
    with pytest.raises(automation.RefreshInputError):
        automation.provider_ready(
            site,
            tmp_path / "second",
            now=datetime(2026, 10, 29, 6, tzinfo=timezone.utc),
            download=lambda symbols, **_: _provider(symbols, missing=["HUBB"]),
            sleep=lambda _: None,
        )


def test_unheld_latest_day_gaps_do_not_expand_target_retries_to_the_whole_universe(
    tmp_path, monkeypatch
):
    import yfinance as yf

    calls = []

    def download(symbols, **kwargs):
        calls.append(symbols)
        return _provider(symbols, missing=[s for s in symbols if s == "UNHELD"])

    monkeypatch.setattr(yf, "download", download)
    result = collect_integrated_market(
        tmp_path,
        start="2010-01-01",
        end="2026-10-29",
        symbols=["HUBB", "UNHELD"],
        target_session="2026-10-28",
        required_target_symbols=["HUBB"],
    )
    assert len(calls) == 1 and pd.isna(result.prices.UNHELD.iloc[-1])
    assert result.metadata["requiredTargetSymbols"] == ["HUBB"]


def test_only_current_verified_full_bar_clears_failed_inventory_and_keeps_source_failure():
    from factor_lab.integrated_data import IntegratedMarket, compute_eligibility
    from factor_lab.integrated_repairs import amend_market
    from factor_lab.integrated_service import data_inventory

    dates = pd.bdate_range(end="2026-10-28", periods=260)
    price = pd.DataFrame({"HUBB": [10.0] * 260}, index=dates)
    price.iloc[-1, 0] = np.nan
    volume = price * 0 + 2e6
    volume.iloc[-1, 0] = 2e6
    source_failure = {
        "code": "target_session_quote_unavailable",
        "date": "2026-10-28",
        "attempts": 2,
    }
    raw = IntegratedMarket(
        price,
        price.copy(),
        price.copy(),
        price.copy(),
        price.copy(),
        volume,
        price * 0,
        price * 0,
        compute_eligibility(price, price, volume),
        metadata={
            "snapshotId": "raw",
            "requestedSymbols": ["HUBB"],
            "failedSymbols": {"HUBB": "provider quote absent"},
            "sourceTargetFailures": {"HUBB": source_failure},
        },
    )
    assert data_inventory(raw)[0]["status"] == "failed"
    quote = {
        "symbol": "HUBB",
        "date": "2026-10-28",
        "open": 10.0,
        "high": 10.0,
        "low": 10.0,
        "close": 10.0,
        "adjustedClose": 10.0,
        "volume": 2e6,
        "sourceUrl": "https://example.test/verified-bar",
        "retrievedAt": "2026-10-29",
    }
    fixed = amend_market(raw, {"inputSnapshotId": "raw", "quotes": [quote]})
    row = data_inventory(fixed)[0]
    assert row["status"] == "eligible" and row["sourceFailure"] == source_failure
    assert row["reason"] == ""
    fixed.metadata["amendments"][0]["date"] = "2026-10-27"
    assert data_inventory(fixed)[0]["status"] == "failed"
