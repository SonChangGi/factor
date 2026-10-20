from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from factor_lab import integrated_automation as automation


def test_completed_session_freshness_uses_integrated_not_legacy_timestamp(tmp_path):
    (tmp_path / 'data').mkdir()
    path = tmp_path / 'data/integrated-result.json'
    now = datetime(2026, 10, 20, 0, tzinfo=timezone.utc)
    path.write_text(json.dumps(dict(schemaVersion='integrated-factor/v1', data={'asOf': '2026-10-19'})))
    assert automation.freshness(tmp_path, now=now)['skip'] is True
    assert automation.freshness(tmp_path, 'manual', now)['skip'] is False
    path.write_text(json.dumps(dict(schemaVersion='integrated-factor/v1', data={'asOf': '2026-10-16'})))
    assert automation.freshness(tmp_path, now=now)['skip'] is False


def test_us_holiday_does_not_require_nonexistent_market_session(tmp_path):
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data/integrated-result.json').write_text(json.dumps(
        dict(schemaVersion='integrated-factor/v1', data={'asOf': '2026-07-02'})))
    result = automation.freshness(tmp_path, now=datetime(2026, 7, 4, 1, tzinfo=timezone.utc))
    assert result['target_data_as_of'] == '2026-07-02'
    assert result['skip'] is True


def market():
    dates = pd.to_datetime(['2026-01-02', '2026-01-05', '2026-10-16', '2026-10-19'])
    zeros = pd.DataFrame(0., index=dates, columns=['A'])
    return SimpleNamespace(prices=zeros + 10, splits=zeros.copy(), dividends=zeros.copy(),
                           metadata={'snapshotId': 'immutable-parent'})


def policy():
    return dict(policyVersion='v1', reviewedThrough='2026-10-16', splitCorrections=[
        dict(symbol='A', date='2026-01-05', ratio=.1, sourceUrl='https://example.test/evidence')],
        quotes=[], valuationMarks=[], identityStarts=[], exchanges=[], quarantines=[])


def test_provider_already_fixed_split_is_not_applied_twice(monkeypatch):
    import factor_lab.integrated_repairs as repairs
    source, evidence = market(), policy()
    source.splits.loc['2026-01-05', 'A'] = .1
    captured = {}
    def amend(m, p):
        captured.update(p)
        return SimpleNamespace(metadata={})
    monkeypatch.setattr(repairs, 'amend_market', amend)
    result = automation.reconcile_policy(source, evidence)
    assert captured['splitCorrections'] == []
    assert captured['inputSnapshotId'] == 'immutable-parent'
    assert result.metadata['automationPolicy']['reconciliation'][0]['decision'] == 'provider_already_records_split'
    assert len(evidence['splitCorrections']) == 1


def test_conflicting_split_or_changed_patch_basis_fails_before_amending(monkeypatch):
    source, evidence = market(), policy()
    source.splits.loc['2026-01-05', 'A'] = .2
    with pytest.raises(ValueError, match='Conflicting provider split'):
        automation.reconcile_policy(source, evidence)
    source.splits.loc['2026-01-05', 'A'] = .1
    source.dividends.loc['2026-10-19', 'A'] = .5
    evidence['quotes'] = [{'symbol': 'A'}]
    with pytest.raises(ValueError, match='adjustment basis changed'):
        automation.reconcile_policy(source, evidence)


def test_fresh_spy_does_not_hide_widespread_stale_equities():
    day = pd.Timestamp('2026-10-19')
    symbols = ['SPY', 'QQQ', '^IXIC'] + [f'A{i}' for i in range(20)]
    prices = pd.DataFrame(10., index=[day], columns=symbols)
    source = SimpleNamespace(prices=prices, metadata={'dataAsOf': str(day.date())})
    baseline = {'data': {'symbols': [{'symbol': s, 'status': 'eligible'} for s in symbols[3:]]}}
    report = automation.validate_market_refresh(source, baseline, '2026-10-19')
    assert report['targetSessionObserved'] == 20
    assert type(report['targetSessionObserved']) is int
    # This object is embedded in publication.json after the full calculation.
    # A NumPy int64 compared equal to 20 but broke that final serialization.
    assert json.loads(json.dumps(report, allow_nan=False)) == report
    prices.loc[day, ['A0', 'A1']] = np.nan
    with pytest.raises(ValueError, match='95%'):
        automation.validate_market_refresh(source, baseline, '2026-10-19')


def prepare_promotion(tmp_path, monkeypatch):
    monkeypatch.setattr(automation, 'current_source', lambda: 'source')
    baseline, candidate, workspace = (tmp_path / s for s in ['site', 'candidate', 'run'])
    for directory in (baseline, candidate, workspace):
        directory.mkdir()
    (baseline / 'good.json').write_text('old-good')
    (candidate / 'new.json').write_text('validated-new')
    status = dict(state='validated', sourceCommit='source', baselineHash=automation.tree_hash(baseline),
                  candidateHash=automation.tree_hash(candidate))
    (workspace / 'status.json').write_text(json.dumps(status))
    return baseline, candidate, workspace


def test_promotion_compare_and_swap_preserves_concurrent_last_good(tmp_path, monkeypatch):
    baseline, candidate, workspace = prepare_promotion(tmp_path, monkeypatch)
    (baseline / 'good.json').write_text('concurrent-result')
    with pytest.raises(ValueError, match='changed'):
        automation.promote(workspace, baseline, candidate)
    assert (baseline / 'good.json').read_text() == 'concurrent-result'
    assert candidate.exists()


def test_validated_candidate_promotes_and_retains_exact_recovery(tmp_path, monkeypatch):
    baseline, candidate, workspace = prepare_promotion(tmp_path, monkeypatch)
    result = automation.promote(workspace, baseline, candidate)
    assert result['state'] == 'promoted'
    assert (baseline / 'new.json').read_text() == 'validated-new'
    assert (workspace / 'last-good-site/good.json').read_text() == 'old-good'


def test_failed_candidate_promotion_rolls_back_baseline(tmp_path, monkeypatch):
    baseline, candidate, workspace = prepare_promotion(tmp_path, monkeypatch)
    replace = automation.os.replace
    def fail_candidate(source, destination):
        if Path(source) == candidate:
            raise OSError('simulated filesystem failure')
        return replace(source, destination)
    monkeypatch.setattr(automation.os, 'replace', fail_candidate)
    with pytest.raises(OSError, match='filesystem'):
        automation.promote(workspace, baseline, candidate)
    assert (baseline / 'good.json').read_text() == 'old-good'


def test_collection_failure_records_failed_attempt_and_preserves_last_good(tmp_path, monkeypatch):
    import sys
    from types import ModuleType
    import factor_lab.integrated_data as data
    monkeypatch.setattr(automation, 'current_source', lambda: 'source')
    validation = ModuleType('factor_lab.integrated_validation')
    validation.validate_automated_result = lambda *a, **k: {}
    validation.write_automated_manifest = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, validation.__name__, validation)
    def fail(*a, **k):
        raise ValueError('provider incomplete')
    monkeypatch.setattr(data, 'collect_integrated_market', fail)
    baseline, workspace, candidate = (tmp_path / s for s in ['site', 'run', 'candidate'])
    baseline.mkdir()
    (baseline / 'last-good.json').write_text('published')
    (baseline / 'data').mkdir()
    (baseline / 'data/integrated-result.json').write_text(json.dumps(
        dict(schemaVersion='integrated-factor/v1', data=dict(asOf='2026-10-16',symbols=[]))))
    before = automation.tree_hash(baseline)
    with pytest.raises(ValueError, match='provider incomplete'):
        automation.run(workspace, baseline, candidate, 'source',
                       now=datetime(2026, 10, 20, 0, tzinfo=timezone.utc))
    status = json.loads((workspace / 'status.json').read_text())
    assert status['state'] == 'failed' and status['lastGoodPreserved'] is True
    assert automation.tree_hash(baseline) == before and not candidate.exists()


def test_weekday_workflow_cannot_reach_legacy_calculation_or_skip_validation():
    root = Path(__file__).resolve().parents[1]
    daily = (root / '.github/workflows/daily-dashboard.yml').read_text()
    watchdog = (root / '.github/workflows/daily-dashboard-watchdog.yml').read_text()
    assert 'scheduled-dashboard' not in daily
    assert '--site site' in daily and '--site site' in watchdog
    assert 'integrated_automation run' in daily and 'integrated_automation promote' in daily
    assert 'validate_integrated_publication.py site' in daily
    assert 'git push origin "HEAD:${DEFAULT_BRANCH}"' in daily
    assert 'git push --force' not in daily and 'continue-on-error' not in daily
    assert 'expected_source_sha="${SOURCE_SHA}"' in daily
    assert 'gh run watch' in daily and '--exit-status' in daily
    assert 'cron: "17 22 * * 1-5"' in daily


def test_future_or_malformed_input_date_cannot_suppress_refresh(tmp_path):
    (tmp_path / 'data').mkdir()
    path = tmp_path / 'data/integrated-result.json'
    now = datetime(2026, 10, 20, 0, tzinfo=timezone.utc)
    path.write_text(json.dumps(dict(schemaVersion='integrated-factor/v1', data={'asOf': 'zz-invalid'})))
    assert automation.freshness(tmp_path, now=now)['skip'] is False
    path.write_text(json.dumps(dict(schemaVersion='integrated-factor/v1', data={'asOf': '2026-10-21'})))
    with pytest.raises(ValueError, match='after the completed'):
        automation.freshness(tmp_path, now=now)


def revision_fixture():
    book = {'nav': [{'date': '2026-10-14', 'value': 1.},
                    {'date': '2026-10-15', 'value': None},
                    {'date': '2026-10-16', 'value': 1.1}]}
    return dict(settings={'start_date': '2016-01-01'}, registry=[{'id': 'A'}],
                selection={'nav': [dict(p) for p in book['nav']], 'history': [{'signalDate':'2026-09-30', 'status':'selected','factorId':'A'}]},
                factors=[{'id':'A', **book}])


def test_historical_revision_compares_only_existing_dates_and_preserves_gaps():
    from copy import deepcopy
    baseline = revision_fixture()
    candidate = deepcopy(baseline)
    candidate['factors'][0]['nav'].append({'date':'2026-10-19', 'value':1.3})
    report = automation.history_revision(baseline, candidate)
    assert report['status'] == 'passed' and report['comparedObservations'] == 6
    candidate['factors'][0]['nav'][1]['value'] = 1.
    report = automation.history_revision(baseline, candidate)
    assert report['status'] == 'review_required'
    assert any(r['reason'] == 'observation_or_null_changed' for r in report['issues'])


def test_nav_revision_or_same_nav_different_past_choice_requires_review():
    from copy import deepcopy
    baseline = revision_fixture()
    candidate = deepcopy(baseline)
    candidate['factors'][0]['nav'][0]['value'] = 1.002
    report = automation.history_revision(baseline, candidate)
    assert report['status'] == 'review_required'
    assert report['maximumDifference']['curveId'] == 'A'
    assert report['maximumRelativeNavRevision'] == pytest.approx(.002)
    candidate = deepcopy(baseline)
    candidate['selection']['history'][0]['factorId'] = 'B'
    assert automation.history_revision(baseline, candidate)['issues'][0]['reason'] == 'historical_choice_changed'
    candidate['settings']['transaction_cost_bps'] = 10
    with pytest.raises(ValueError, match='Financial settings changed'):
        automation.history_revision(baseline, candidate)


def test_revisions_within_fixed_ten_basis_point_policy_are_recorded():
    from copy import deepcopy
    baseline = revision_fixture()
    candidate = deepcopy(baseline)
    candidate['factors'][0]['nav'][0]['value'] = 1.0005
    report = automation.history_revision(baseline, candidate)
    assert report['status'] == 'passed'
    assert report['maximumRelativeNavRevision'] == pytest.approx(.0005)


def test_input_cache_must_be_confirmed_before_promotion(tmp_path, monkeypatch):
    baseline, candidate, workspace = prepare_promotion(tmp_path, monkeypatch)
    status_path = workspace / 'status.json'
    status = json.loads(status_path.read_text())
    status['inputCacheKey'] = 'factor-input-v1-test-1'
    status_path.write_text(json.dumps(status))
    with pytest.raises(ValueError, match='not confirmed'):
        automation.promote(workspace, baseline, candidate)
    assert (baseline / 'good.json').read_text() == 'old-good'
    with pytest.raises(ValueError, match='does not match'):
        automation.confirm_input_cache(workspace, 'wrong-key', '123')
    automation.confirm_input_cache(workspace, status['inputCacheKey'], '123')
    assert automation.promote(workspace, baseline, candidate)['state'] == 'promoted'


def test_initial_coverage_contract_subtracts_only_verified_inserted_trade_quotes():
    payload={'data':dict(asOf='2026-10-16',symbols=[dict(symbol='A',observations=4,firstObservation='2020-01-02')],
        amendments=[dict(kind='observed_quote',symbol='A'),dict(kind='non_trading_valuation_mark',symbol='A')])}
    contract=automation.coverage_contract_from_result(payload)
    assert contract['A']['observations']==3 and contract['A']['asOf']=='2026-10-16'
    payload['data']['inputCoverage']={'A':dict(observations=2,firstObservation='2020-01-02',asOf='2026-10-16')}
    assert automation.coverage_contract_from_result(payload)==payload['data']['inputCoverage']


def test_recovery_copies_only_provider_downloads_without_splicing_input_matrices(tmp_path):
    import hashlib
    old=tmp_path/'restored/raw'; old.mkdir(parents=True)
    request=dict(start='2010-01-01',endExclusive='2026-10-20',symbols=['A'])
    (old/'request.json').write_text(json.dumps(request))
    (old/'downloads').mkdir();(old/'downloads/batch.json').write_text('verified-elsewhere')
    (old/'prices.csv.gz').write_text('old matrix never copied')
    manifest=dict(dataAsOf='2026-10-19',request=request,files={})
    manifest['snapshotId']=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
    (old/'manifest.json').write_text(json.dumps(manifest))
    destination=tmp_path/'new/raw'
    receipt=automation.seed_download_cache(old.parent,destination,'2026-10-19')
    assert (destination/'downloads/batch.json').exists()
    assert not (destination/'prices.csv.gz').exists() and not (destination/'manifest.json').exists()
    assert receipt['sourceSnapshotId']==manifest['snapshotId']
    with pytest.raises(ValueError,match='different completed session'):
        automation.seed_download_cache(old.parent,tmp_path/'another/raw','2026-10-20')


def test_read_only_diagnostics_exports_original_selected_columns_and_provenance(tmp_path,monkeypatch):
    import hashlib
    source=tmp_path/'restored'
    dates=pd.to_datetime(['2014-12-31','2015-02-25','2016-12-15','2017-01-03'])
    for stage in ['raw','market']:
        folder=source/stage;folder.mkdir(parents=True)
        frame=pd.DataFrame({'BOH':[1.,1.0000003854,1.1,1.2],'OTHER':[2.]*4},index=dates)
        frame.index.name='Date'
        path=folder/'prices.csv.gz';frame.to_csv(path)
        manifest={'snapshotId':'source-input', 'files':{'prices.csv.gz':hashlib.sha256(path.read_bytes()).hexdigest()}}
        (folder/'manifest.json').write_text(json.dumps(manifest))
    monkeypatch.setattr(automation,'current_source',lambda:'diagnostic-source')
    monkeypatch.setenv('FACTOR_REUSED_INPUT_CACHE_ID','123')
    output=tmp_path/'export'
    receipt=automation.export_input_diagnostics(source,output)
    exported=pd.read_csv(output/'raw/prices.csv',index_col=0)
    assert list(exported.columns)==['BOH'] and list(exported.index)==['2015-02-25','2016-12-15']
    assert receipt['cacheId']=='123' and receipt['raw']['snapshotId']=='source-input'
    assert exported.BOH.iloc[0]==1.0000003854


def test_diagnostics_job_cannot_calculate_or_publish():
    workflow=(Path(__file__).resolve().parents[1]/'.github/workflows/daily-dashboard.yml').read_text()
    diagnostics=workflow.split('  input-cache-diagnostics:\n',1)[1]
    assert 'export-input-diagnostics' in diagnostics
    assert 'integrated_automation run' not in diagnostics and 'git push' not in diagnostics
    assert 'actions/cache/restore@' in diagnostics and 'fail-on-cache-miss: true' in diagnostics
    assert 'inputs.diagnostics_only != true' in workflow


def test_diagnostics_reject_invalid_symbols_and_dates_before_writing(tmp_path):
    for options in (dict(symbols=['BOH', 'BOH']), dict(symbols=['BOH;id']),
                    dict(start='2016-01-01', end='2015-12-31'), dict(start='2015-1-1')):
        output = tmp_path / 'rejected'
        with pytest.raises(ValueError):
            automation.export_input_diagnostics(tmp_path / 'absent', output, **options)
        assert not output.exists()
