"""Mutation tests use an already saved release; they do not run new backtests.

The historical payload is embedded with its verified presentation histories and
marked with the daily test setting solely to exercise the runtime contract. This
fixture does not assert that a new daily run or source-proof check occurred.
"""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import pytest
from factor_lab.integrated_factors import factor_registry as current_factor_registry
from factor_lab.integrated_validation import (
    validate_automated_result, check_candidates, check_curve, check_weights,
)


@pytest.fixture(scope='module')
def historical_fixture():
    root = Path(__file__).resolve().parents[1]
    source = '3df7d85c98dd1c42b822ee5a4ff89a274a614e30'
    def saved(path):
        return json.loads(subprocess.check_output(['git', 'show', source + ':' + path], cwd=root))
    result = saved('site/data/integrated-result.json')
    histories = saved('site/data/fixed-factor-history.json')
    for factor in result['factors']:
        item = histories['factors'][factor['id']]
        if item['latest'] is not None:
            factor.update({k: item[k] for k in ('history', 'latest', 'historyBasis', 'holdingsAsOf')})
    result['settings']['run_stress'] = True  # test-only; no calculation was run
    for stress in result['research']['stress']:
        stress['sourceResultId'] = result['resultIdentity']['resultId']
    return result


@pytest.fixture(autouse=True)
def historical_definition_contract(historical_fixture, monkeypatch):
    # Mutation checks exercise the frozen release's own catalog. Production
    # daily validation still requires the current definition version.
    monkeypatch.setattr('factor_lab.integrated_factors.factor_registry',
                        lambda: deepcopy(historical_fixture['registry']))


def test_current_daily_rejects_a_historical_definition_catalog(historical_fixture, monkeypatch):
    monkeypatch.setattr('factor_lab.integrated_factors.factor_registry', current_factor_registry)
    with pytest.raises(ValueError, match='Definition version/catalog changed'):
        validate_automated_result(historical_fixture)


@pytest.fixture
def result(historical_fixture):
    return deepcopy(historical_fixture)


def current(result):
    # A parsed payload has equal but separately allocated current/history rows.
    # Bind them for a mutation so the test reaches the intended invariant.
    result['selection']['current'] = result['selection']['history'][-1]
    return result['selection']['current']


def test_saved_historical_books_exercise_new_runtime_invariants(historical_fixture):
    report = validate_automated_result(historical_fixture, target_as_of='2026-10-16')
    assert report['status'] == 'passed' and report['fixedFactors'] == 26
    assert report['currentCandidates'] == 26 and report['stressScenarios'] == 7


@pytest.mark.parametrize('field', ['cagr', 'mdd', 'calmar'])
def test_false_performance_metrics_are_rejected(result, field):
    result['selection']['metrics'][field] += .1
    with pytest.raises(ValueError):
        validate_automated_result(result)


def test_current_missing_score_is_not_silently_accepted(result):
    current(result)['candidates'][0]['score'] = None
    with pytest.raises(ValueError, match='score'):
        validate_automated_result(result)


def test_missing_current_candidate_is_rejected(result):
    current(result)['candidates'].pop()
    with pytest.raises(ValueError, match='catalog'):
        validate_automated_result(result)


def test_corrupt_weights_or_unspendable_claim_is_rejected(result):
    result['selection']['holdings'][0]['weight'] += .01
    with pytest.raises(ValueError, match='conserve NAV'):
        validate_automated_result(result)
    row = dict(holdings=[{'symbol': 'A', 'weight': .8}], cashWeight=.2,
               receivableWeight=.2, liquidCashWeight=.2)
    with pytest.raises(ValueError, match='Claims'):
        check_weights(row)


def test_stress_must_share_calculation_version(result):
    result['research']['stress'][0]['codeHash'] = 'different'
    with pytest.raises(ValueError, match='Stress version'):
        validate_automated_result(result)


def test_all_risk_rejected_can_be_cash_but_data_error_cannot(historical_fixture):
    candidate = deepcopy(historical_fixture['selection']['current']['candidates'][0])
    candidate.update(id='A', status='risk_rejected', reason='sharpe', score=100.,
                     components=dict(cagr=25., sortino=25., calmar=20., mdd=20., stability=10.))
    candidate['metrics']['sharpe'] = -1.
    row = dict(status='cash', factorId=None, candidates=[candidate])
    check_candidates(row, {'A'}, complete=True)
    row['candidates'][0]['status'] = 'data_error'
    with pytest.raises(ValueError, match='Cash caused'):
        check_candidates(row, {'A'})
    row['status'] = 'deferred'
    check_candidates(row, {'A'})  # retained historical failure, not cash return


def test_current_data_error_deferral_is_not_a_publishable_success(result):
    row = current(result)
    row.update(status='deferred', factorId=None, score=None)
    for candidate in row['candidates']:
        candidate.update(status='data_error', score=None)
    with pytest.raises(ValueError):
        validate_automated_result(result)


def test_existing_partial_gaps_remain_null_and_cost_is_not_rebased(historical_fixture):
    factor = next(f for f in historical_fixture['factors']
                  if any(point['value'] is None for point in f['nav']))
    assert any(r['value'] is None for r in factor['drawdown'])
    check_curve(factor, historical_fixture['data']['asOf'])
    assert historical_fixture['factors'][0]['nav'][0]['value'] == .999
    book = deepcopy(factor)
    position = next(i for i, row in enumerate(book['nav']) if row['value'] is None)
    book['drawdown'][position]['value'] = 0.
    with pytest.raises(ValueError, match='Missing NAV'):
        check_curve(book, historical_fixture['data']['asOf'])


def test_initial_transaction_cost_included_in_nav_drawdown_and_cagr():
    nav = [.999, 1.01, .98]
    peak = 1.
    dd = []
    for value in nav:
        peak = max(peak, value)
        dd.append(value / peak - 1)
    expected = .98 ** (252 / 3) - 1
    book = dict(nav=[{'date': d, 'value': v} for d, v in zip(['2026-10-14','2026-10-15','2026-10-16'],nav)],
                drawdown=[{'date': d, 'value': v} for d, v in zip(['2026-10-14','2026-10-15','2026-10-16'],dd)],
                metrics=dict(endingNavAvailable=True, calendarObservations=3, mdd=min(dd),
                             cagr=expected, calmar=expected/abs(min(dd)), riskMetricsComplete=True),
                holdings=[], cashWeight=1., receivableWeight=0., liquidCashWeight=1.)
    check_curve(book, '2026-10-16')
    book['metrics']['cagr'] = (.98 / .999) ** (252 / 3) - 1
    with pytest.raises(ValueError, match='cost-inclusive'):
        check_curve(book, '2026-10-16')


def test_fixed_history_cannot_drop_a_month(result):
    result['factors'][0]['history'].pop(10)
    with pytest.raises(ValueError, match='monthly coverage'):
        validate_automated_result(result)


def test_execution_must_match_trading_session_delay_not_just_follow_signal(result):
    result['factors'][0]['history'][0]['executionDate'] = '2016-02-08'
    with pytest.raises(ValueError, match='session delay'):
        validate_automated_result(result)


def test_fixed_latest_cannot_reclassify_legal_claim_as_spendable_cash(result):
    factor = next(f for f in result['factors'] if f.get('receivableWeight', 0) > .01)
    factor['latest']['receivableWeight'] = 0.
    factor['latest']['liquidCashWeight'] = factor['latest']['cashWeight']
    with pytest.raises(ValueError, match='cash/claim mismatch'):
        validate_automated_result(result)


def test_omitted_nav_session_cannot_be_hidden_by_reannualizing(result):
    book = result['factors'][0]
    book['nav'].pop(5)
    book['drawdown'].pop(5)
    book['metrics']['calendarObservations'] = len(book['nav'])
    book['metrics']['cagr'] = book['nav'][-1]['value'] ** (252 / len(book['nav'])) - 1
    book['metrics']['calmar'] = book['metrics']['cagr'] / abs(book['metrics']['mdd'])
    with pytest.raises(ValueError, match='NYSE session'):
        validate_automated_result(result)


def test_balanced_component_tamper_cannot_preserve_total_score(result):
    candidate = current(result)['candidates'][0]
    candidate['components']['cagr'] += 1
    candidate['components']['sortino'] -= 1
    with pytest.raises(ValueError, match='percentile/weight mismatch'):
        validate_automated_result(result)


def test_risk_failure_cannot_be_labelled_eligible(result):
    candidate = current(result)['candidates'][0]
    candidate['metrics']['sharpe'] = -1.
    with pytest.raises(ValueError, match='Guardrail status'):
        validate_automated_result(result)


def test_incomplete_candidate_window_cannot_be_labelled_comparable(result):
    current(result)['candidates'][0]['metrics']['observedReturnCount'] = 755
    with pytest.raises(ValueError, match='756 complete'):
        validate_automated_result(result)


def test_future_holding_snapshot_and_false_pending_are_rejected(result):
    current(result)['holdingsAsOf'] = '2026-10-30'
    with pytest.raises(ValueError, match='Future selection'):
        validate_automated_result(result)


def test_false_pending_selection_is_rejected(result):
    result['selection']['pending'] = current(result)
    with pytest.raises(ValueError, match='Pending selection binding'):
        validate_automated_result(result)


def test_independent_percentiles_handle_ties_clipping_and_infinity():
    from factor_lab.integrated_validation import percentile_scores
    # Linear 5/95 quantiles of [0,1,1,3] are .15/2.7. Equal ones retain
    # average rank (2+3)/2 /4 =62.5%, including after clipping extremes.
    assert percentile_scores([0, 1, 1, 3]) == [25., 62.5, 62.5, 100.]
    assert percentile_scores([float('-inf'), 1, float('inf')]) == [
        pytest.approx(200/3), pytest.approx(200/3), pytest.approx(200/3)]
    assert percentile_scores([float('-inf'), float('inf')]) == [0., 100.]


def test_filling_historical_gap_without_changing_counts_is_rejected(historical_fixture):
    factor = deepcopy(next(f for f in historical_fixture['factors']
                           if any(point['value'] is None for point in f['nav'])))
    position = next(i for i, row in enumerate(factor['nav']) if row['value'] is None)
    previous = factor['nav'][position-1]['value']
    factor['nav'][position]['value'] = previous
    factor['drawdown'][position]['value'] = factor['drawdown'][position-1]['value']
    with pytest.raises(ValueError, match='Observed return count'):
        check_curve(factor, historical_fixture['data']['asOf'])


def test_wrong_stress_parent_is_rejected_even_when_code_hash_matches(result):
    result['research']['stress'][0]['sourceResultId'] = 'another-parent'
    with pytest.raises(ValueError, match='Stress parent binding'):
        validate_automated_result(result)
