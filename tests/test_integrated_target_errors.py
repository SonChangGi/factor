from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from factor_lab.config import FIXED_WEIGHTING_POLICY
from factor_lab.integrated_data import IntegratedMarket
from factor_lab.integrated_engine import IntegratedConfig, _monthly_candidate, run_integrated_analysis
from factor_lab.portfolio import TargetAllocation


@pytest.mark.parametrize('reason', [
    'weight_invariant_failed', 'duplicate_scores_symbol', 'duplicate_prices_symbol',
    'duplicate_eligibility_symbol', 'no_finite_trailing_dollar_volume',
    'top_n_boundary_tie_has_no_finite_liquidity_tie_break', 'unknown_calculation_failure',
])
def test_target_failure_preserves_reason_and_is_not_normal_shortage(reason):
    index = pd.bdate_range('2020-01-01', periods=756)
    target = TargetAllocation(FIXED_WEIGHTING_POLICY, index[-1], status='unavailable',
                              reasons=[reason], component_status={'liquidity': 'unavailable'})
    candidate = _monthly_candidate(SimpleNamespace(returns=pd.Series(.001, index=index)),
                                   index[-1], target, pd.DataFrame(index=index), 756)
    assert candidate['status'] == 'data_error'
    assert candidate['reason'] == 'target_allocation_failed'
    assert candidate['allocationIssue']['reasons'] == [reason]
    assert candidate['allocationIssue']['componentStatus'] == {'liquidity': 'unavailable'}


def test_no_signal_history_and_available_target_warmup_remain_shortages():
    index = pd.bdate_range('2020-01-01', periods=21)
    result = SimpleNamespace(returns=pd.Series(.001, index=index))
    target = TargetAllocation(FIXED_WEIGHTING_POLICY, index[-1], status='unavailable',
                              reasons=['no_complete_signal_inputs'])
    candidate = _monthly_candidate(result, index[-1], target, pd.DataFrame(index=index), 756)
    assert candidate['status'] == 'insufficient_data'
    assert candidate['allocationIssue']['reasons'] == ['no_complete_signal_inputs']
    target.status = 'available'
    target.rows = pd.DataFrame([{'symbol': 'A', 'weight': .1}])
    assert _monthly_candidate(result, index[-1], target, pd.DataFrame(index=index), 756) == {
        'status': 'insufficient_data', 'reason': 'incomplete_nav_or_target', 'metrics': {}}


def test_target_error_plus_all_other_risk_rejected_holds_existing_portfolio(monkeypatch):
    import factor_lab.integrated_engine as engine

    dates = pd.bdate_range('2020-01-01', periods=150)
    p = pd.DataFrame({f'{side}{j}': 100 * (1 + drift) ** np.arange(len(dates))
                      for side, drift in [('UP', .001), ('DOWN', -.001)] for j in range(20)},
                     index=dates)
    v = p * 0 + 1e6
    market = IntegratedMarket(p, p, p, p, p, v, p * 0, p * 0, p.notna(), {})
    scores = pd.DataFrame(np.tile([1.] * 20 + [-1.] * 20, (len(p), 1)),
                          index=dates, columns=p.columns)
    last_signal = engine.completed_monthends(dates)[-1]
    original = engine._allocation

    def failed_target(date, panel, *args):
        if date == last_signal and panel.iloc[0, 0] > 0:
            return TargetAllocation(FIXED_WEIGHTING_POLICY, date, status='unavailable',
                                    reasons=['weight_invariant_failed'])
        return original(date, panel, *args)

    monkeypatch.setattr(engine, '_allocation', failed_target)
    out = run_integrated_analysis(market, IntegratedConfig(
        start_date='2020-01-01', evaluation_window_days=21, bootstrap_repetitions=0),
        {'MOM12_1': scores, 'STREV1': -scores})
    history = out['selection']['history']
    assert any(h['status'] == 'selected' for h in history[:-1])
    latest = history[-1]
    assert latest['status'] == 'deferred'
    states = {c['id']: c['status'] for c in latest['candidates']}
    assert states == {'MOM12_1': 'data_error', 'STREV1': 'risk_rejected'}
    assert latest['targetHoldings'] == []
    assert latest['turnover'] == latest['cost'] == 0
    assert out['selection']['cashWeight'] == 0
    assert all(h['symbol'].startswith('UP') for h in out['selection']['holdings'])
