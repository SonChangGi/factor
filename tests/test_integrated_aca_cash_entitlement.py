"""Reviewed ACA policy through normalized units, holdings and cash claims."""

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
    events = [r for r in policy["exchanges"] if r["symbol"] == "ACA"]
    assert len(events) == 1
    return dict(policyVersion=policy["policyVersion"], reviewedThrough=policy["reviewedThrough"],
                exchanges=events)


def _market(unit_basis=2., *, stale_after_merger=False):
    dates = pd.bdate_range(end="2026-10-27", periods=260)
    raw = pd.DataFrame({"ACA": 149.14999389648438, "OTHER": 100.}, index=dates)
    prices = raw.copy()
    prices["ACA"] *= unit_basis
    if not stale_after_merger:
        prices.loc["2026-10-23":, "ACA"] = np.nan
        raw.loc["2026-10-23":, "ACA"] = np.nan
    volume = raw * 0 + 1e6
    zero = pd.DataFrame(0., index=dates, columns=raw.columns)
    return IntegratedMarket(
        prices, raw, raw.copy(), raw.copy(), raw.copy(), volume,
        zero, zero.copy(), compute_eligibility(prices, raw, volume),
        {"snapshotId": "aca-unit-fixture", "requestedSymbols": ["ACA", "OTHER"]},
    )


def _target(day, weights):
    return TargetAllocation(FIXED_WEIGHTING_POLICY, pd.Timestamp(day),
                            rows=pd.DataFrame([dict(symbol=s, weight=w)
                                               for s, w in weights.items()]),
                            cash_weight=1 - sum(weights.values()), status="available")


def _run(market, targets):
    return run_factor_backtest(
        "ACA-independent-ledger", FIXED_WEIGHTING_POLICY, market.prices, market.prices,
        RunConfig(transaction_cost_bps=5, slippage_bps=5), signal_targets=targets,
        **backtest_inputs(market, market.prices.index),
    )


@pytest.mark.parametrize("unit_basis", [.5, 1., 2.])
def test_reviewed_aca_entitlement_matches_physical_shares_and_stays_unsettled(unit_basis):
    original = _market(unit_basis)
    fixed = reconcile_policy(original, _policy())
    event = fixed.metadata["corporateActions"][0]
    assert event["date"] == "2026-10-23"
    assert event["cashPerShare"] == 150.
    assert event["cashPerUnit"] == pytest.approx(unit_basis * 150.)
    assert event["sourceUnitAnchorDate"] == "2026-10-22"
    assert event["settlementDate"] is None
    assert event["sourceUrl"].startswith("https://infomemo.theocc.com/")
    assert fixed.metadata["cashEntitlementPolicy"].endswith("cannot fund a rebalance.")
    pd.testing.assert_frame_equal(fixed.prices, original.prices)
    pd.testing.assert_frame_equal(fixed.raw_close, original.raw_close)

    targets = {pd.Timestamp("2026-10-20"): _target("2026-10-20", {"ACA": .4, "OTHER": .4}),
               pd.Timestamp("2026-10-23"): _target("2026-10-23", {"OTHER": 1.})}
    result = _run(fixed, targets)
    # One-dollar inception: buy .8 weight at .001 cost and retain .2 liquid.
    # Physical ACA shares, rather than normalized TR units, receive USD150 each.
    after_entry = 1. - .8 * .001
    physical_shares = .4 * after_entry / 149.14999389648438
    claim = physical_shares * 150.
    liquid = .2 * after_entry
    other = .4 * after_entry
    expected_nav = claim + liquid + other
    assert result.equity.loc["2026-10-23":].tolist() == pytest.approx([expected_nav] * 3)
    assert result.ending_weights["ACA"] == 0
    assert result.ending_weights["OTHER"] == pytest.approx(other / expected_nav)
    assert result.ending_receivable_weight == pytest.approx(claim / expected_nav)
    assert result.ending_cash_weight - result.ending_receivable_weight == pytest.approx(
        liquid / expected_nav)
    assert result.costs.loc["2026-10-23":].sum() == 0
    assert result.turnover.loc["2026-10-23":].sum() == 0
    assert result.execution_statuses.loc["2026-10-26"] == "blocked_unsettled_corporate_cash"
    assert result.returns.loc["2026-10-23"] == pytest.approx(.4 * (150. / 149.14999389648438 - 1.))
    assert result.contribution_diagnostics.attribution_max_residual < 1e-12
    forward = forward_security_returns(fixed.prices, pd.Timestamp("2026-10-22"),
                                       pd.Timestamp("2026-10-27"), fixed.valuation_prices,
                                       fixed.metadata["corporateActions"])
    assert forward["ACA"] == pytest.approx(150. / 149.14999389648438 - 1.)


def test_aca_merger_policy_does_not_change_prior_signals_or_nav():
    original = _market()
    cutoff = pd.Timestamp("2026-10-22")
    prefix = replace(original, **{f.name: getattr(original, f.name).loc[:cutoff].copy()
                                 for f in fields(original)
                                 if isinstance(getattr(original, f.name), pd.DataFrame)})
    old = reconcile_policy(prefix, _policy())
    fixed = reconcile_policy(original, _policy())
    assert old.metadata["corporateActions"] == []
    pd.testing.assert_frame_equal(old.prices, prefix.prices)
    pd.testing.assert_frame_equal(fixed.eligibility.loc[:cutoff], old.eligibility)
    targets = {pd.Timestamp("2026-10-20"): _target("2026-10-20", {"ACA": .4, "OTHER": .4})}
    before = _run(old, targets)
    after = _run(fixed, targets)
    pd.testing.assert_series_equal(after.returns.loc[:cutoff], before.returns)
    pd.testing.assert_frame_equal(after.pre_trade_weights.loc[:cutoff], before.pre_trade_weights)
    future = _market()
    future.prices.loc["2026-10-27", "OTHER"] = 10000.
    changed = _run(reconcile_policy(future, _policy()), targets)
    pd.testing.assert_series_equal(changed.returns.loc[:"2026-10-23"],
                                   after.returns.loc[:"2026-10-23"])


def test_aca_cannot_enter_next_target_even_if_provider_repeats_old_quote():
    original = _market(stale_after_merger=True)
    fixed = reconcile_policy(original, _policy())
    day = pd.Timestamp("2026-10-26")
    assert original.eligibility.at[day, "ACA"]
    assert not fixed.eligibility.loc["2026-10-23":, "ACA"].any()
    allocation = construct_target_allocation(
        FIXED_WEIGHTING_POLICY, day, pd.Series({"ACA": 10., "OTHER": 1.}),
        fixed.prices.loc[day], fixed.eligibility.loc[day], RunConfig(top_n=1, max_weight=1.),
        trailing_dollar_volume=fixed.dollar_volumes.loc[:day].tail(63).mean(),
    )
    assert allocation.status == "available"
    assert allocation.rows["symbol"].tolist() == ["OTHER"]


def test_failed_cache_quote_gap_requires_entitlement_not_a_filled_price():
    from pathlib import Path
    from factor_lab.integrated_validation import check_curve

    fixture = json.loads((Path(__file__).parent / "fixtures/aca_20261023.json").read_text())
    panels = {name: pd.DataFrame(rows).set_index("Date")
              for name, rows in fixture["frames"].items()}
    for panel in panels.values():
        panel.index = pd.to_datetime(panel.index)
    prices, raw, volume = (panels[n] for n in ("prices", "raw_close", "volumes"))
    zero = prices * 0
    original = IntegratedMarket(prices, raw, raw.copy(), raw.copy(), raw.copy(), volume,
        zero, zero.copy(), prices.notna(),
        {"snapshotId": fixture["sourceSnapshotId"], "requestedSymbols": ["ACA", "SPY"]})
    targets = {pd.Timestamp("2026-10-21"): _target("2026-10-21", {"ACA": .4, "SPY": .4})}
    broken = _run(original, targets)
    assert np.isnan(broken.equity.iloc[-1])
    book = {"nav": [{"date": str(d.date()), "value": None if pd.isna(v) else v}
                    for d, v in broken.equity.items()],
            "drawdown": [{"date": str(d.date()), "value": None} for d in broken.equity.index],
            "metrics": {"endingNavAvailable": False}}
    with pytest.raises(ValueError, match="Terminal NAV unavailable"):
        check_curve(book, "2026-10-23")

    fixed = reconcile_policy(original, _policy())
    repaired = _run(fixed, targets)
    after_entry = 1 - .8 * .001
    claim = .4 * after_entry / raw.at[pd.Timestamp("2026-10-22"), "ACA"] * 150
    spy = .4 * after_entry * prices.SPY.iloc[-1] / prices.SPY.iloc[-2]
    liquid = .2 * after_entry
    assert repaired.equity.iloc[-1] == pytest.approx(claim + spy + liquid)
    assert repaired.ending_receivable_weight == pytest.approx(claim / repaired.equity.iloc[-1])
    assert repaired.ending_cash_weight - repaired.ending_receivable_weight == pytest.approx(
        liquid / repaired.equity.iloc[-1])
    assert repaired.ending_weights["ACA"] == 0
    assert repaired.costs.iloc[-1] == repaired.turnover.iloc[-1] == 0
    pd.testing.assert_series_equal(repaired.equity.iloc[:-1], broken.equity.iloc[:-1])
    pd.testing.assert_frame_equal(fixed.prices, original.prices)
    pd.testing.assert_frame_equal(fixed.raw_close, original.raw_close)
    assert pd.isna(fixed.valuation_prices.ACA.iloc[-1])
