"""Independent dollar ledgers for verified marks and compulsory exchanges."""

import numpy as np
import pandas as pd
import pytest

from momentum_factor_lab.backtest import run_factor_backtest
from momentum_factor_lab.config import FIXED_WEIGHTING_POLICY, RunConfig
from momentum_factor_lab.portfolio import TargetAllocation


def _target(date, weights):
    return TargetAllocation(
        FIXED_WEIGHTING_POLICY,
        date,
        rows=pd.DataFrame([dict(symbol=s, weight=w) for s, w in weights.items()]),
        cash_weight=1 - sum(weights.values()),
        status="available",
    )


def _run(prices, targets, **kwargs):
    return run_factor_backtest(
        "independent-ledger", FIXED_WEIGHTING_POLICY, prices, prices,
        RunConfig(transaction_cost_bps=0, slippage_bps=0),
        signal_targets=targets, retain_contribution_history=True, **kwargs,
    )


def test_verified_halt_mark_values_holdings_but_cannot_execute_sale():
    dates = pd.bdate_range("2025-01-06", periods=5)
    observed = pd.DataFrame({"A": [100, 100, np.nan, 110, 121]}, index=dates)
    marks = observed.copy()
    marks.loc[dates[2], "A"] = 100
    result = _run(
        observed,
        {dates[0]: _target(dates[0], {"A": 1}), dates[1]: _target(dates[1], {})},
        valuation_prices=marks,
    )
    assert result.returns.loc[dates[2]:].tolist() == pytest.approx([0, .1, .1])
    assert result.valuation_available.all()
    assert result.execution_statuses.loc[dates[2]] == "blocked_missing_held_quote"
    assert result.turnover.loc[dates[2]] == 0
    assert result.equity.iloc[-1] == pytest.approx(1.21)
    assert result.return_interval_sessions.loc[dates[2]] == 1
    pd.testing.assert_series_equal(result.security_contributions.A, result.returns.fillna(0), check_names=False)


def test_verified_halt_mark_is_not_an_entry_price():
    dates = pd.bdate_range("2025-01-06", periods=4)
    observed = pd.DataFrame({"A": [100, np.nan, 110, 121]}, index=dates)
    marks = observed.fillna(100)
    result = _run(observed, {dates[0]: _target(dates[0], {"A": 1})}, valuation_prices=marks)
    assert result.returns.isna().all()
    assert result.execution_statuses.loc[dates[1]] == "blocked_all_targets_unpriceable"
    assert result.ending_cash_weight == 1


def test_normalized_merger_units_match_raw_share_ledger_and_receive_target():
    dates = pd.bdate_range("2025-01-06", periods=5)
    # A total-return unit is 2 raw A shares (TR/raw=200/100).
    # Each A share receives .25 B share; one raw B share is 2 TR B units
    # (raw/TR=400/200), so one A TR unit becomes 1 B TR unit.
    prices = pd.DataFrame({"A": [200, 200, np.nan, np.nan, np.nan],
                           "B": [200, 200, 210, 220, 230]}, index=dates)
    event = dict(date=str(dates[2].date()), symbol="A", targetSymbol="B", unitRatio=1.)
    result = _run(prices, {dates[0]: _target(dates[0], {"A": 1})}, corporate_actions=[event])
    assert result.returns.loc[dates[2]:].tolist() == pytest.approx([.05, 220 / 210 - 1, 230 / 220 - 1])
    assert result.equity.iloc[-1] == pytest.approx(1.15)
    assert result.ending_weights.to_dict() == {"A": 0, "B": 1}
    assert result.pre_trade_weights.loc[dates[2]].to_dict() == {"A": 0, "B": 1}
    assert result.turnover.loc[dates[2]] == result.costs.loc[dates[2]] == 0
    assert result.security_contributions.loc[dates[2]].to_dict() == pytest.approx({"A": .05, "B": 0})
    assert result.security_contributions.loc[dates[3], "A"] == 0
    assert result.contribution_diagnostics.attribution_max_residual < 1e-12


def test_merger_preserves_existing_target_and_attributes_cash_to_source():
    dates = pd.bdate_range("2025-01-06", periods=4)
    prices = pd.DataFrame({"A": [100, 100, np.nan, np.nan], "B": [50, 50, 55, 60]}, index=dates)
    # Entry: .005 A units + .01 B units. Exchange yields .01 B + .10 cash.
    # Event NAV: .02*55+.10 = 1.20. A earns .15 and B earns .05.
    event = dict(date=str(dates[2].date()), symbol="A", targetSymbol="B", unitRatio=2., cashPerUnit=20.)
    result = _run(prices, {dates[0]: _target(dates[0], {"A": .5, "B": .5})}, corporate_actions=[event])
    assert result.equity.loc[dates[2]] == pytest.approx(1.20)
    assert result.equity.iloc[-1] == pytest.approx(1.30)
    assert result.security_contributions.loc[dates[2]].to_dict() == pytest.approx({"A": .15, "B": .05})
    assert result.ending_cash_weight == pytest.approx(.10 / 1.30)
    assert result.contribution_diagnostics.attribution_max_residual < 1e-12


def test_exchange_ancestry_survives_a_missing_event_day_quote():
    dates = pd.bdate_range("2025-01-06", periods=5)
    prices = pd.DataFrame({"A": [100, 100, np.nan, np.nan, np.nan],
                           "B": [50, 50, np.nan, 60, 66]}, index=dates)
    event = dict(date=str(dates[2].date()), symbol="A", targetSymbol="B", unitRatio=2.)
    result = _run(prices, {dates[0]: _target(dates[0], {"A": 1})}, corporate_actions=[event])
    assert np.isnan(result.returns.loc[dates[2]])
    assert result.returns.loc[dates[3]] == pytest.approx(.2)
    assert result.return_interval_sessions.loc[dates[3]] == 2
    assert result.security_contributions.loc[dates[3]].to_dict() == pytest.approx({"A": .2, "B": 0})
    assert result.equity.iloc[-1] == pytest.approx(1.32)
    assert result.contribution_diagnostics.attribution_max_residual < 1e-12


def test_future_price_or_event_does_not_change_prior_state():
    dates = pd.bdate_range("2025-01-06", periods=5)
    prices = pd.DataFrame({"A": [100, 100, 101, np.nan, np.nan], "B": [50, 50, 50, 55, 60]}, index=dates)
    targets = {dates[0]: _target(dates[0], {"A": 1})}
    event = dict(date=str(dates[3].date()), symbol="A", targetSymbol="B", unitRatio=2.)
    original = _run(prices, targets, corporate_actions=[event])
    modified = prices.copy()
    modified.loc[dates[3]:, "B"] *= 10
    changed = _run(modified, targets, corporate_actions=[event])
    ordinary = _run(prices, targets)
    for other in (changed, ordinary):
        pd.testing.assert_series_equal(original.returns.loc[:dates[2]], other.returns.loc[:dates[2]])
        pd.testing.assert_frame_equal(original.weights.loc[:dates[2]], other.weights.loc[:dates[2]])


def test_optional_empty_actions_and_observed_marks_preserve_default_exactly():
    dates = pd.bdate_range("2025-01-06", periods=5)
    prices = pd.DataFrame({"A": [100, 100, 101, 99, 105]}, index=dates)
    targets = {dates[0]: _target(dates[0], {"A": 1})}
    original = _run(prices, targets)
    explicit = _run(prices, targets, valuation_prices=prices.copy(), corporate_actions=[])
    for name in ("returns", "equity", "turnover", "costs", "cash_weights", "ending_weights"):
        pd.testing.assert_series_equal(getattr(original, name), getattr(explicit, name))
    pd.testing.assert_frame_equal(original.security_contributions, explicit.security_contributions)


def test_conflicting_mark_or_duplicate_exchange_fails():
    dates = pd.bdate_range("2025-01-06", periods=3)
    prices = pd.DataFrame({"A": [100, 100, 100], "B": [50, 50, 50]}, index=dates)
    targets = {dates[0]: _target(dates[0], {"A": 1})}
    with pytest.raises(ValueError, match="preserve"):
        _run(prices, targets, valuation_prices=prices * 2)
    event = dict(date=str(dates[2].date()), symbol="A", targetSymbol="B", unitRatio=2.)
    with pytest.raises(ValueError, match="duplicate"):
        _run(prices, targets, corporate_actions=[event, event])


def test_cash_merger_converts_absent_quote_to_known_unsettled_entitlement():
    dates = pd.bdate_range("2026-10-12", periods=6)
    prices = pd.DataFrame({"A": [100, 100, np.nan, np.nan, np.nan, np.nan]}, index=dates)
    event = dict(date=str(dates[2].date()), symbol="A", targetSymbol=None,
                 unitRatio=0., cashPerUnit=105., settlementDate=None)
    result = _run(prices, {dates[0]: _target(dates[0], {"A": 1})}, corporate_actions=[event])
    assert result.returns.loc[dates[2]:].tolist() == pytest.approx([.05, 0, 0, 0])
    assert result.valuation_available.all()
    assert result.equity.iloc[-1] == pytest.approx(1.05)
    assert result.ending_weights.A == 0
    assert result.ending_cash_weight == result.ending_receivable_weight == 1
    assert result.receivable_weights.loc[dates[3]:].tolist() == [1, 1, 1]
    assert result.security_contributions.loc[dates[2], "A"] == pytest.approx(.05)
    assert result.costs.loc[dates[2]:].sum() == result.turnover.loc[dates[2]:].sum() == 0
    assert result.contribution_diagnostics.attribution_max_residual < 1e-12


def test_unsettled_claim_blocks_reinvestment_until_explicit_settlement():
    dates = pd.bdate_range("2026-10-12", periods=7)
    prices = pd.DataFrame({"A": [100, 100, np.nan, np.nan, np.nan, np.nan, np.nan],
                           "B": [50, 50, 50, 50, 50, 50, 55]}, index=dates)
    event = dict(date=str(dates[2].date()), symbol="A", targetSymbol=None,
                 unitRatio=0., cashPerUnit=105., settlementDate=str(dates[5].date()))
    targets = {dates[0]: _target(dates[0], {"A": 1}),
               dates[2]: _target(dates[2], {"B": 1}),
               dates[4]: _target(dates[4], {"B": 1})}
    result = _run(prices, targets, corporate_actions=[event])
    assert result.execution_statuses.loc[dates[3]] == "blocked_unsettled_corporate_cash"
    assert result.turnover.loc[dates[3]] == 0
    assert result.execution_statuses.loc[dates[5]] == "executed"
    assert result.returns.loc[dates[5]] == 0  # settlement and reinvestment have no P&L
    assert result.ending_receivable_weight == 0
    assert result.ending_cash_weight == 0
    assert result.ending_weights.B == 1
    assert result.equity.iloc[-1] == pytest.approx(1.155)
    assert result.contribution_diagnostics.attribution_max_residual < 1e-12


def test_claim_does_not_accrue_interest_while_existing_liquid_cash_does():
    dates = pd.bdate_range("2026-10-12", periods=5)
    prices = pd.DataFrame({"A": [100, 100, np.nan, np.nan, np.nan]}, index=dates)
    event = dict(date=str(dates[2].date()), symbol="A", targetSymbol=None,
                 unitRatio=0., cashPerUnit=105.)  # cash-only omission means unknown settlement
    result = run_factor_backtest(
        "cash-ledger", FIXED_WEIGHTING_POLICY, prices, prices,
        RunConfig(transaction_cost_bps=0, slippage_bps=0, annual_cash_return=1.),
        signal_targets={dates[0]: _target(dates[0], {"A": .5})},
        corporate_actions=[event], retain_contribution_history=True,
    )
    growth = 2 ** (1 / 252)
    expected = .525 + .5 * growth ** 3
    assert result.equity.iloc[-1] == pytest.approx(expected)
    assert result.ending_receivable_weight == pytest.approx(.525 / expected)
    assert result.ending_cash_weight == 1
    assert result.receivable_weights.loc[dates[3]] > result.ending_receivable_weight
    assert result.contribution_diagnostics.attribution_max_residual < 1e-12


def test_cash_merger_preserves_other_equity_and_claim_weights_reconcile():
    dates = pd.bdate_range("2026-10-12", periods=5)
    prices = pd.DataFrame({"A": [100, 100, np.nan, np.nan, np.nan],
                           "B": [50, 50, 55, 60, 65]}, index=dates)
    event = dict(date=str(dates[2].date()), symbol="A", targetSymbol=None,
                 unitRatio=0., cashPerUnit=105., settlementDate=None)
    result = _run(prices, {dates[0]: _target(dates[0], {"A": .4, "B": .4})},
                  corporate_actions=[event])
    # .004 A units => .42 claim, .008 B units => .52 B value, .20 cash.
    assert result.equity.iloc[-1] == pytest.approx(1.14)
    assert result.ending_receivable_weight == pytest.approx(.42 / 1.14)
    assert result.ending_cash_weight == pytest.approx(.62 / 1.14)
    assert result.ending_weights.B == pytest.approx(.52 / 1.14)
    assert result.ending_weights.sum() + result.ending_cash_weight == pytest.approx(1)
    assert result.security_contributions.loc[dates[2]].to_dict() == pytest.approx({"A": .02, "B": .04})
    assert result.contribution_diagnostics.attribution_max_residual < 1e-12


def test_stock_and_deferred_cash_exchange_separates_claim_from_successor():
    dates = pd.bdate_range("2026-10-12", periods=4)
    prices = pd.DataFrame({"A": [100, 100, np.nan, np.nan], "B": [50, 50, 55, 60]}, index=dates)
    event = dict(date=str(dates[2].date()), symbol="A", targetSymbol="B",
                 unitRatio=1., cashPerUnit=50., settlementDate=None)
    result = _run(prices, {dates[0]: _target(dates[0], {"A": 1})}, corporate_actions=[event])
    assert result.equity.iloc[-1] == pytest.approx(1.10)
    assert result.ending_receivable_weight == pytest.approx(.5 / 1.1)
    assert result.ending_cash_weight == result.ending_receivable_weight
    assert result.ending_weights.B == pytest.approx(.6 / 1.1)
    assert result.contribution_diagnostics.attribution_max_residual < 1e-12


@pytest.mark.parametrize("extra", [
    dict(targetSymbol=None, unitRatio=1., cashPerUnit=105.),
    dict(targetSymbol=None, unitRatio=0., cashPerUnit=0.),
    dict(targetSymbol="B", unitRatio=0., cashPerUnit=105.),
    dict(targetSymbol=None, unitRatio=0., cashPerUnit=105., settlementDate="2026-10-12"),
])
def test_invalid_cash_exchange_contracts_fail(extra):
    dates = pd.bdate_range("2026-10-12", periods=3)
    prices = pd.DataFrame({"A": [100, 100, 100], "B": [50, 50, 50]}, index=dates)
    event = dict(date=str(dates[2].date()), symbol="A", **extra)
    with pytest.raises(ValueError, match="cash|settlement"):
        _run(prices, {dates[0]: _target(dates[0], {"A": 1})}, corporate_actions=[event])
