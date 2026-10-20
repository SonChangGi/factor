import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from momentum_factor_lab.backtest import run_factor_backtest
from momentum_factor_lab.config import FIXED_WEIGHTING_POLICY, RunConfig
from momentum_factor_lab.integrated_history import fixed_factor_history
from momentum_factor_lab.portfolio import TargetAllocation


def allocation(date, rows=(), status='available'):
    return TargetAllocation(FIXED_WEIGHTING_POLICY, date,
                            rows=pd.DataFrame(rows, columns=['symbol', 'weight']),
                            cash_weight=1 - sum(row[1] for row in rows), status=status)


def replay(prices, targets, delay=1, **kwargs):
    return run_factor_backtest('fixed', FIXED_WEIGHTING_POLICY, prices, prices,
                               RunConfig(transaction_cost_bps=0, slippage_bps=0),
                               signal_targets=targets, execution_delay_sessions=delay,
                               **kwargs)


def test_history_uses_execution_close_not_opening_or_signal_weights():
    dates = pd.bdate_range('2020-01-01', periods=5)
    prices = pd.DataFrame({'A': [100, 100, 100, 200, 300], 'B': [100] * 5}, index=dates)
    targets = {dates[0]: allocation(dates[0], [('A', .7), ('B', .3)])}
    result = replay(prices, targets, delay=2)
    exported = fixed_factor_history(result, targets, dates, 2)
    row = exported['history'][0]
    assert row['executionDate'] == '2020-01-03'
    assert row['holdingsAsOf'] == '2020-01-03'
    assert row['holdings'] == [{'symbol': 'A', 'weight': .7}, {'symbol': 'B', 'weight': .3}]
    assert result.weights.loc[dates[2]].sum() == 0  # execution close was cash at open
    assert exported['latest']['holdings'][0]['weight'] == pytest.approx(.875)


def test_missing_new_quote_shows_actual_partial_trade_and_original_target():
    dates = pd.bdate_range('2020-01-01', periods=3)
    prices = pd.DataFrame({'A': [100, 100, 100], 'B': [100, np.nan, 100]}, index=dates)
    targets = {dates[0]: allocation(dates[0], [('A', .6), ('B', .4)])}
    row = fixed_factor_history(replay(prices, targets), targets, dates)['history'][0]
    assert row['executionStatus'] == 'executed_partial_unpriceable_targets'
    assert row['holdings'] == [{'symbol': 'A', 'weight': .6}]
    assert len(row['targetHoldings']) == 2
    assert row['cashWeight'] == pytest.approx(.4)


def test_blocked_missing_held_quote_never_reports_target_as_executed():
    dates = pd.bdate_range('2020-01-01', periods=5)
    prices = pd.DataFrame({'A': [100, 100, np.nan, 110, 120], 'B': [100] * 5}, index=dates)
    targets = {dates[0]: allocation(dates[0], [('A', 1)]),
               dates[1]: allocation(dates[1], [('B', 1)])}
    row = fixed_factor_history(replay(prices, targets), targets, dates)['history'][1]
    assert row['executionStatus'] == 'blocked_missing_held_quote'
    assert row['status'] == 'valuation_unavailable'
    assert row['holdings'] == [{'symbol': 'A', 'weight': 1.}]
    assert row['targetHoldings'] == [{'symbol': 'B', 'weight': 1.}]
    assert row['holdingsAsOf'] == str(dates[1].date())
    assert row['valuationStatus'] == 'last_complete'


def test_unsettled_corporate_receivable_is_not_liquid_cash():
    dates = pd.bdate_range('2020-01-01', periods=4)
    prices = pd.DataFrame({'A': [100, 100, np.nan, np.nan], 'B': [100] * 4}, index=dates)
    targets = {dates[0]: allocation(dates[0], [('A', 1)]),
               dates[1]: allocation(dates[1], [('B', 1)])}
    actions = [dict(date=str(dates[2].date()), symbol='A', targetSymbol=None,
                    unitRatio=0, cashPerUnit=105, settlementDate=None)]
    row = fixed_factor_history(replay(prices, targets, corporate_actions=actions),
                               targets, dates)['history'][1]
    assert row['executionStatus'] == 'blocked_unsettled_corporate_cash'
    assert row['holdings'] == []
    assert row['cashWeight'] == row['receivableWeight'] == 1.
    assert row['liquidCashWeight'] == 0.


def test_next_session_stock_exchange_does_not_leak_into_execution_close():
    dates = pd.bdate_range('2020-01-01', periods=4)
    prices = pd.DataFrame({'A': [100] * 4, 'B': [50] * 4}, index=dates)
    targets = {dates[0]: allocation(dates[0], [('A', 1)])}
    actions = [dict(date=str(dates[2].date()), symbol='A', targetSymbol='B', unitRatio=2)]
    result = replay(prices, targets, corporate_actions=actions)
    exported = fixed_factor_history(result, targets, dates)
    assert exported['history'][0]['holdingsAsOf'] == str(dates[1].date())
    assert exported['history'][0]['holdings'] == [{'symbol': 'A', 'weight': 1.}]
    assert exported['latest']['holdings'] == [{'symbol': 'B', 'weight': 1.}]


def test_pending_and_first_signal_wait_are_distinct_and_do_not_fake_holdings():
    dates = pd.bdate_range('2020-01-01', periods=4)
    prices = pd.DataFrame({'A': [100] * 4}, index=dates)
    targets = {dates[0]: allocation(dates[0], status='unavailable'),
               dates[-1]: allocation(dates[-1], [('A', 1)])}
    result = replay(prices, targets)
    rows = fixed_factor_history(result, targets, dates,
                                next_execution=lambda date, delay: pd.Timestamp('2020-01-07'))['history']
    assert rows[0]['status'] == 'awaiting_first_signal'
    assert rows[1]['status'] == rows[1]['executionStatus'] == 'pending'
    assert rows[1]['executionDate'] == '2020-01-07'
    assert rows[1]['holdings'] == []
    assert rows[1]['targetHoldings'] == [{'symbol': 'A', 'weight': 1.}]
    assert rows[1]['cashWeight'] == 1.


def test_missing_weight_history_is_rejected():
    dates = pd.bdate_range('2020-01-01', periods=3)
    prices = pd.DataFrame({'A': [100] * 3}, index=dates)
    target = {dates[0]: allocation(dates[0], [('A', 1)])}
    result = replay(prices, target, retain_weight_history=False)
    with pytest.raises(ValueError, match='Full retained'):
        fixed_factor_history(result, target, dates)


def test_export_is_immutable_and_parent_regression_rejects_changes(tmp_path):
    script = Path(__file__).resolve().parents[1] / 'scripts' / 'export_fixed_factor_history.py'
    spec = importlib.util.spec_from_file_location('history_export_test', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    destination = tmp_path / 'history.json'
    module.write_immutable(destination, {'value': 1})
    with pytest.raises(FileExistsError):
        module.write_immutable(destination, {'value': 2})
    assert destination.read_text() == '{"value":1}'
    with pytest.raises(ValueError, match='Parent result regression mismatch'):
        module.require_equal([{'value': .1}], [{'value': .2}], 'nav')
