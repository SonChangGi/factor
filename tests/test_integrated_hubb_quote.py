"""Observed Nasdaq daily bar repairs the real missing HUBB 2026-10-28 close."""
from dataclasses import replace
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_lab.backtest import run_factor_backtest
from factor_lab.config import FIXED_WEIGHTING_POLICY, RunConfig
from factor_lab.integrated_automation import POLICY, reconcile_policy
from factor_lab.integrated_data import IntegratedMarket, compute_eligibility
from factor_lab.integrated_repairs import backtest_inputs
from factor_lab.portfolio import TargetAllocation

FIXTURE = Path(__file__).parent / "fixtures/hubb_20261028.json"


def evidence():
    return json.loads(FIXTURE.read_text())


def policy():
    full = json.loads(POLICY.read_text())
    rows = [r for r in full["quotes"] if r["symbol"] == "HUBB"]
    assert len(rows) == 1
    return dict(policyVersion=full["policyVersion"], reviewedThrough=full["reviewedThrough"],
                quotes=rows)


def market():
    ix = pd.bdate_range(end="2026-10-28", periods=260)
    close = pd.DataFrame({"HUBB": 434.28}, index=ix)
    volume = close * 0 + 1e6
    zero = close * 0
    raw = evidence()["yahooResponse"]["chart"]["result"][0]["indicators"]["quote"][0]
    frames = {}
    for name in ("close", "open", "high", "low"):
        frame = close.copy()
        frame.iloc[-1, 0] = raw[name][-1] if raw[name][-1] is not None else np.nan
        frames[name] = frame
    volume.iloc[-1, 0] = raw["volume"][-1]
    return IntegratedMarket(
        frames["close"].copy(), frames["close"], frames["open"], frames["high"], frames["low"],
        volume, zero, zero.copy(), compute_eligibility(frames["close"], frames["close"], volume),
        {"snapshotId": "observed-hubb-missing-close", "requestedSymbols": ["HUBB"]},
        provider_close=frames["close"].copy(), provider_open=frames["open"].copy(),
        provider_high=frames["high"].copy(), provider_low=frames["low"].copy(),
        provider_volumes=volume.copy(),
    )


def test_policy_bar_is_one_dated_source_and_independently_corroborated():
    item = evidence()
    source = item["nasdaqResponse"]
    bar = source["data"]["tradesTable"]["rows"][0]
    row = policy()["quotes"][0]
    assert source["data"]["symbol"] == "HUBB" and source["status"]["rCode"] == 200
    assert bar["date"] == "10/28/2026" and row["date"] == "2026-10-28"
    assert row == item["policyQuote"]
    assert row["close"] == row["adjustedClose"] == item["stockAnalysisObservation"]["close"] == 437.33
    assert row["open"] == 444.68 and row["high"] == 444.805 and row["low"] == 426.91
    assert row["volume"] == 1163860 and row["sourceUrl"].startswith("https://api.nasdaq.com/")
    assert row["closePrecision"] == {"kind": "decimal", "places": 2}
    raw = item["yahooResponse"]["chart"]["result"][0]
    assert raw["indicators"]["quote"][0]["close"][-1] is None
    assert raw["indicators"]["quote"][0]["high"][-1] < raw["indicators"]["quote"][0]["open"][-1]
    assert raw["meta"]["regularMarketPrice"] == row["close"]


def test_whole_bar_replaces_only_missing_close_and_preserves_immutable_parent():
    original = market()
    fixed = reconcile_policy(original, policy())
    d = pd.Timestamp("2026-10-28")
    assert np.isnan(original.prices.at[d, "HUBB"])
    assert original.raw_high.at[d, "HUBB"] < original.raw_open.at[d, "HUBB"]
    for field, expected in (("prices", 437.33), ("raw_close", 437.33), ("raw_open", 444.68),
                            ("raw_high", 444.805), ("raw_low", 426.91), ("volumes", 1163860),
                            ("provider_high", 444.805), ("provider_volumes", 1163860)):
        assert getattr(fixed, field).at[d, "HUBB"] == expected
    pd.testing.assert_frame_equal(original.prices.iloc[:-1], fixed.prices.iloc[:-1])
    assert fixed.shape_valid.at[d, "HUBB"] and fixed.eligibility.at[d, "HUBB"]
    assert fixed.dollar_volumes.at[d, "HUBB"] == pytest.approx(437.33 * 1163860)
    assert fixed.metadata["amendments"][0]["kind"] == "observed_quote"
    assert fixed.metadata["amendments"][0]["evidenceSha256"] == evidence()["nasdaqResponseSha256"]


def test_observed_close_restores_holding_nav_without_flat_price_or_synthetic_cash():
    fixed = reconcile_policy(market(), policy())
    signal = pd.Timestamp("2026-10-26")
    target = TargetAllocation(FIXED_WEIGHTING_POLICY, signal,
                              rows=pd.DataFrame([dict(symbol="HUBB", weight=1.)]),
                              cash_weight=0., status="available")
    result = run_factor_backtest("HUBB-verified-close", FIXED_WEIGHTING_POLICY,
        fixed.prices, fixed.prices, RunConfig(transaction_cost_bps=5, slippage_bps=5),
        signal_targets={signal: target}, **backtest_inputs(fixed, fixed.prices.index))
    assert result.equity.loc["2026-10-28"] / result.equity.loc["2026-10-27"] - 1 == pytest.approx(437.33 / 434.28 - 1)
    assert result.equity.loc["2026-10-28"] > result.equity.loc["2026-10-27"]


def test_existing_conflicting_quote_and_changed_adjustment_basis_still_fail():
    original = market()
    observed = replace(original, prices=original.prices.copy())
    observed.prices.iloc[-1, 0] = 500.
    with pytest.raises(ValueError, match="Conflicting observed close"):
        reconcile_policy(observed, policy())
    original.dividends.iloc[-1, 0] = 1.
    with pytest.raises(ValueError, match="adjustment basis changed"):
        reconcile_policy(original, policy())
