import copy
import json

import pytest

from factor_lab.integrated_factors import factor_registry
from factor_lab.integrated_review import reviewed_revision
from factor_lab import integrated_review


def revisions():
    registry = factor_registry()
    baseline_registry = copy.deepcopy(registry)
    original = next(row for row in baseline_registry if row['id'] == 'CONSISTENCY12_1')
    original['version'] = '1.0.0'
    original.pop('signInputContract')
    original.pop('signInputNotes')
    nav = [dict(date='2020-01-02', value=1.), dict(date='2020-01-03', value=1.1)]
    baseline = dict(settings={}, registry=baseline_registry,
                    resultIdentity=dict(resultId='baseline', inputHash='old-input'),
                    selection=dict(nav=copy.deepcopy(nav), history=[dict(signalDate='2019-12-31', status='selected', factorId='MOM12_1')]),
                    factors=[dict(id=key, nav=copy.deepcopy(nav)) for key in ('MOM12_1', 'CONSISTENCY12_1')])
    candidate = copy.deepcopy(baseline)
    candidate['registry'] = registry
    candidate['resultIdentity'] = dict(resultId='candidate', inputHash='new-input')
    candidate['selection']['nav'][1]['value'] = 1.12
    candidate['selection']['history'][0]['factorId'] = 'CONSISTENCY12_1'
    candidate['factors'][1]['nav'][1]['value'] = 1.11
    return baseline, candidate


def test_review_is_explicit_about_revised_definition_and_dependent_strategy():
    baseline, candidate = revisions()
    report = reviewed_revision(baseline, candidate)
    assert report['status'] == 'passed'
    assert report['reviewedDefinitionIds'] == ['CONSISTENCY12_1']
    assert report['definitionBefore']['version'] == '1.0.0'
    assert report['definitionAfter']['version'] == '1.1.0'
    assert report['comparison']['revisedObservationCounts'] == {'MONTHLY_SELECTION': 2, 'CONSISTENCY12_1': 1}
    assert report['baselineInputHash'] == 'old-input'
    assert report['candidateInputHash'] == 'new-input'


@pytest.mark.parametrize('edit', [
    lambda p: p['factors'][0]['nav'][1].update(value=1.2),
    lambda p: p['factors'][0]['nav'][1].update(value=None),
    lambda p: p['factors'][0]['nav'].pop(),
])
def test_review_cannot_admit_unrelated_revisions_or_hide_missing_prices(edit):
    baseline, candidate = revisions()
    edit(candidate)
    with pytest.raises(ValueError, match='Unchanged factor history changed'):
        reviewed_revision(baseline, candidate)


@pytest.mark.parametrize('edit', [
    lambda p: p['registry'][0].update(version='2.0.0'),
    lambda p: next(r for r in p['registry'] if r['id'] == 'CONSISTENCY12_1').update(formula='a different hypothesis'),
    lambda p: p['settings'].update(top_n=30),
])
def test_review_cannot_expand_definition_or_portfolio_scope(edit):
    baseline, candidate = revisions()
    edit(candidate)
    with pytest.raises(ValueError):
        reviewed_revision(baseline, candidate)


def test_review_cannot_publish_when_primary_input_cache_is_unavailable(tmp_path, monkeypatch):
    baseline = tmp_path / 'baseline'
    (baseline / 'data').mkdir(parents=True)
    original = json.dumps(dict(resultIdentity=dict(resultId='old')))
    (baseline / 'data/integrated-result.json').write_text(original)
    candidate_result = tmp_path / 'result.json'
    candidate_result.write_text(json.dumps(dict(
        resultIdentity=dict(inputHash='input', codeHash='code'),
        data=dict(inputCache=dict(key='factor-input-v1-123-1')))))
    monkeypatch.setattr(integrated_review, 'current_source', lambda: 'source')
    monkeypatch.setattr(integrated_review, 'code_fingerprint', lambda: ('code', {}))
    monkeypatch.setattr(integrated_review.subprocess, 'check_output',
                        lambda *args, **kwargs: '{"actions_caches":[]}')
    candidate = tmp_path / 'candidate'
    with pytest.raises(ValueError, match='input cache is unavailable'):
        integrated_review.prepare(candidate_result, baseline, candidate, 'source', 'old', 'input', '456')
    assert not candidate.exists()
    assert (baseline / 'data/integrated-result.json').read_text() == original
