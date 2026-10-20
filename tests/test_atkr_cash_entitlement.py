"""Reviewed ATKR policy through normalized units, holdings and cash claims."""

from dataclasses import fields, replace
import json

import numpy as np
import pandas as pd
import pytest

from factor_lab.backtest import run_factor_backtest
from factor_lab.config import FIXED_WEIGHTING_POLICY, RunConfig
from factor_lab.integrated_automation import POLICY, reconcile_policy
from factor_lab.integrated_data import IntegratedMarket, compute_eligibility
from factor_lab.integrated_repairs import backtest_inputs
from factor_lab.integrated_research import forward_security_returns
from factor_lab.portfolio import TargetAllocation, construct_target_allocation


def _policy():
    policy = json.loads(POLICY.read_text())
    events = [r for r in policy["exchanges"] if r["symbol"] == "ATKR"]
    assert len(events) == 1
    return dict(policyVersion=policy["policyVersion"], reviewedThrough=policy["reviewedThrough"],
                exchanges=events)


def _market(unit_basis=2., *, stale_after_merger=False):
    dates = pd.bdate_range(end="2026-10-21", periods=260)
    raw = pd.DataFrame({"ATKR": 94.96, "OTHER": 100.}, index=dates)
    prices = raw.copy()
    prices["ATKR"] *= unit_basis
    if not stale_after_merger:
        prices.loc["2026-10-19":, "ATKR"] = np.nan
        raw.loc["2026-10-19":, "ATKR"] = np.nan
    volume = raw * 0 + 1e6
    zero = pd.DataFrame(0., index=dates, columns=raw.columns)
    return IntegratedMarket(
        prices, raw, raw.copy(), raw.copy(), raw.copy(), volume,
        zero, zero.copy(), compute_eligibility(prices, raw, volume),
        {"snapshotId": "atkr-unit-fixture", "requestedSymbols": ["ATKR", "OTHER"]},
    )


def _target(day, weights):
    return TargetAllocation(FIXED_WEIGHTING_POLICY, pd.Timestamp(day),
                            rows=pd.DataFrame([dict(symbol=s, weight=w)
                                               for s, w in weights.items()]),
                            cash_weight=1 - sum(weights.values()), status="available")


def _run(market, targets):
    return run_factor_backtest(
        "ATKR-independent-ledger", FIXED_WEIGHTING_POLICY, market.prices, market.prices,
        RunConfig(transaction_cost_bps=5, slippage_bps=5), signal_targets=targets,
        **backtest_inputs(market, market.prices.index),
    )


@pytest.mark.parametrize("unit_basis", [.5, 1., 2.])
def test_reviewed_atkr_entitlement_matches_physical_shares_and_stays_unsettled(unit_basis):
    original = _market(unit_basis)
    fixed = reconcile_policy(original, _policy())
    event = fixed.metadata["corporateActions"][0]
    assert event["date"] == "2026-10-19"
    assert event["cashPerShare"] == 95.
    assert event["cashPerUnit"] == pytest.approx(unit_basis * 95.)
    assert event["sourceUnitAnchorDate"] == "2026-10-16"
    assert event["settlementDate"] is None
    assert event["sourceUrl"].startswith("https://www.sec.gov/Archives/")
    assert fixed.metadata["cashEntitlementPolicy"].endswith("cannot fund a rebalance.")
    pd.testing.assert_frame_equal(fixed.prices, original.prices)
    pd.testing.assert_frame_equal(fixed.raw_close, original.raw_close)

    targets = {pd.Timestamp("2026-10-14"): _target("2026-10-14", {"ATKR": .4, "OTHER": .4}),
               pd.Timestamp("2026-10-19"): _target("2026-10-19", {"OTHER": 1.})}
    result = _run(fixed, targets)
    # One-dollar inception: buy .8 weight at .001 cost and retain .2 liquid.
    # Physical ATKR shares, rather than normalized TR units, receive USD95 each.
    after_entry = 1. - .8 * .001
    physical_shares = .4 * after_entry / 94.96
    claim = physical_shares * 95.
    liquid = .2 * after_entry
    other = .4 * after_entry
    expected_nav = claim + liquid + other
    assert result.equity.loc["2026-10-19":].tolist() == pytest.approx([expected_nav] * 3)
    assert result.ending_weights["ATKR"] == 0
    assert result.ending_weights["OTHER"] == pytest.approx(other / expected_nav)
    assert result.ending_receivable_weight == pytest.approx(claim / expected_nav)
    assert result.ending_cash_weight - result.ending_receivable_weight == pytest.approx(
        liquid / expected_nav)
    assert result.costs.loc["2026-10-19":].sum() == 0
    assert result.turnover.loc["2026-10-19":].sum() == 0
    assert result.execution_statuses.loc["2026-10-20"] == "blocked_unsettled_corporate_cash"
    assert result.returns.loc["2026-10-19"] == pytest.approx(.4 * (95. / 94.96 - 1.))
    assert result.contribution_diagnostics.attribution_max_residual < 1e-12
    forward = forward_security_returns(fixed.prices, pd.Timestamp("2026-10-16"),
                                       pd.Timestamp("2026-10-21"), fixed.valuation_prices,
                                       fixed.metadata["corporateActions"])
    assert forward["ATKR"] == pytest.approx(95. / 94.96 - 1.)


def test_atkr_merger_policy_does_not_change_prior_signals_or_nav():
    original = _market()
    cutoff = pd.Timestamp("2026-10-16")
    prefix = replace(original, **{f.name: getattr(original, f.name).loc[:cutoff].copy()
                                 for f in fields(original)
                                 if isinstance(getattr(original, f.name), pd.DataFrame)})
    old = reconcile_policy(prefix, _policy())
    fixed = reconcile_policy(original, _policy())
    assert old.metadata["corporateActions"] == []
    pd.testing.assert_frame_equal(old.prices, prefix.prices)
    pd.testing.assert_frame_equal(fixed.eligibility.loc[:cutoff], old.eligibility)
    targets = {pd.Timestamp("2026-10-14"): _target("2026-10-14", {"ATKR": .4, "OTHER": .4})}
    before = _run(old, targets)
    after = _run(fixed, targets)
    pd.testing.assert_series_equal(after.returns.loc[:cutoff], before.returns)
    pd.testing.assert_frame_equal(after.pre_trade_weights.loc[:cutoff], before.pre_trade_weights)
    future = _market()
    future.prices.loc["2026-10-21", "OTHER"] = 10000.
    changed = _run(reconcile_policy(future, _policy()), targets)
    pd.testing.assert_series_equal(changed.returns.loc[:"2026-10-19"],
                                   after.returns.loc[:"2026-10-19"])


def test_atkr_cannot_enter_next_target_even_if_provider_repeats_old_quote():
    original = _market(stale_after_merger=True)
    fixed = reconcile_policy(original, _policy())
    day = pd.Timestamp("2026-10-20")
    assert original.eligibility.at[day, "ATKR"]
    assert not fixed.eligibility.loc["2026-10-19":, "ATKR"].any()
    allocation = construct_target_allocation(
        FIXED_WEIGHTING_POLICY, day, pd.Series({"ATKR": 10., "OTHER": 1.}),
        fixed.prices.loc[day], fixed.eligibility.loc[day], RunConfig(top_n=1, max_weight=1.),
        trailing_dollar_volume=fixed.dollar_volumes.loc[:day].tail(63).mean(),
    )
    assert allocation.status == "available"
    assert allocation.rows["symbol"].tolist() == ["OTHER"]
