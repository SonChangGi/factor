"""Actual 2026-10-21 failures plus fail-closed incremental input contracts."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_lab.integrated_data import IntegratedMarket, save_integrated_market
from factor_lab.integrated_vintage import extend_price_vintage, load_accepted_vintage

FIXTURE = Path(__file__).parent / 'fixtures' / 'price-vintage'


def market(prices, *, raw=None, volumes=None, dividends=None, splits=None, identity='test'):
    close = prices.copy() if raw is None else raw
    zeros = prices*0
    return IntegratedMarket(prices, close, close, close, close,
        prices*0+1000 if volumes is None else volumes,
        zeros if dividends is None else dividends, zeros if splits is None else splits,
        prices.notna(), metadata=dict(dataAsOf=str(prices.index[-1].date()),
            universeVersion='test', requestedSymbols=list(prices.columns), snapshotId=identity),
        valuation_prices=prices.copy())


def recorded(label, symbols, start=None):
    data = (FIXTURE/(label+'.csv.gz')).read_bytes()
    provenance = json.loads((FIXTURE/'provenance.json').read_text())[label]
    assert hashlib.sha256(data).hexdigest() == provenance['fixtureSha256']
    frame = pd.read_csv(FIXTURE/(label+'.csv.gz'), header=[0, 1], index_col=0, parse_dates=True)
    values = {key: frame[key].loc[start:, symbols] for key in ('prices','raw_close','volumes','dividends','splits')}
    return market(values.pop('prices'), raw=values.pop('raw_close'), **values,
                  identity=provenance['snapshot'])


def scores(m, factor, date, monkeypatch):
    import factor_lab.integrated_factors as f
    specs = f._SPECS
    monkeypatch.setattr(f, '_SPECS', [r for r in specs if r[0] == factor])
    return next(f.iter_integrated_factors(m))[1].loc[date]


@pytest.mark.parametrize('label,symbols,start,factor,date,pair', [
    ('latest', ['MIDD','ROKU','SPY'], '2017-01-03', 'REL_DOWNSIDEBETA252','2018-10-31', ['MIDD','ROKU']),
    ('earlier', ['ATEN','NBR'], '2018-01-02', 'SEASON5Y','2023-09-29', ['ATEN','NBR']),
])
def test_real_failures_reverse_ranks_and_accepted_vintage_restores_them(label,symbols,start,factor,date,pair,monkeypatch):
    old, new = recorded('baseline',symbols,start), recorded(label,symbols,start)
    before = scores(old,factor,date,monkeypatch)
    changed = scores(new,factor,date,monkeypatch)
    assert np.sign(before[pair[0]]-before[pair[1]]) != np.sign(changed[pair[0]]-changed[pair[1]])
    fixed = extend_price_vintage(new,old)
    pd.testing.assert_frame_equal(fixed.prices,old.prices)
    pd.testing.assert_series_equal(scores(fixed,factor,date,monkeypatch)[pair],before[pair])
    # The immutable new source is not changed to resemble the accepted input.
    assert not new.prices.equals(old.prices)


def test_append_uses_same_response_return_and_leaves_both_sources_unchanged():
    dates=pd.bdate_range('2026-10-15',periods=4)
    old=market(pd.DataFrame({'A':[90.,99.,108.]},index=dates[:3]),
               raw=pd.DataFrame({'A':[100.,110.,120.]},index=dates[:3]))
    new=market(pd.DataFrame({'A':[45.00001,49.50001,54.,56.7]},index=dates),
               raw=pd.DataFrame({'A':[100.,110.,120.,126.]},index=dates))
    original=deepcopy(new)
    fixed=extend_price_vintage(new,old)
    assert fixed.prices.A.to_list()==pytest.approx([90.,99.,108.,113.4])
    assert fixed.prices.A.iloc[-1]/fixed.prices.A.iloc[-2]==pytest.approx(56.7/54.)
    pd.testing.assert_frame_equal(new.prices,original.prices)
    assert fixed.metadata['priceVintage']['acceptedSnapshotId']=='test'
    pd.testing.assert_frame_equal(fixed.prices,fixed.valuation_prices)


@pytest.mark.parametrize('field', ['raw_close','dividends','splits'])
def test_real_source_revision_keeps_complete_current_column_for_history_gate(field):
    old=recorded('baseline',['ATEN','NBR'],'2018-01-02')
    new=recorded('earlier',['ATEN','NBR'],'2018-01-02')
    getattr(new,field).iloc[100,0] += 1
    fixed=extend_price_vintage(new,old)
    pd.testing.assert_series_equal(fixed.prices.ATEN,new.prices.ATEN)
    pd.testing.assert_series_equal(fixed.prices.NBR,old.prices.NBR)
    record=fixed.metadata['priceVintage']['unfrozenSourceRevisions'][0]
    assert record['symbol']=='ATEN'
    assert record['policy']=='complete_current_column_subject_to_unchanged_history_gate'


def test_late_recovered_quote_is_not_discarded_or_spliced_into_old_basis():
    old=recorded('baseline',['ATEN','NBR'],'2018-01-02')
    new=recorded('earlier',['ATEN','NBR'],'2018-01-02')
    old.prices.iloc[-1,0]=np.nan
    old.raw_close.iloc[-1,0]=np.nan
    fixed=extend_price_vintage(new,old)
    pd.testing.assert_series_equal(fixed.prices.ATEN,new.prices.ATEN)
    assert 'ATEN' in [r['symbol'] for r in fixed.metadata['priceVintage']['unfrozenSourceRevisions']]


def test_volume_correction_uses_current_liquidity_without_rewriting_price_history():
    old=recorded('baseline',['ATEN','NBR'],'2018-01-02')
    new=recorded('earlier',['ATEN','NBR'],'2018-01-02')
    new.volumes.iloc[100,0] += 1
    fixed=extend_price_vintage(new,old)
    pd.testing.assert_frame_equal(fixed.prices,old.prices)
    pd.testing.assert_frame_equal(fixed.volumes,new.volumes)


def test_calendar_change_still_fails_closed():
    old=recorded('baseline',['ATEN','NBR'],'2018-01-02')
    new=replace(old,prices=old.prices.iloc[1:])
    with pytest.raises(ValueError,match='calendar'):
        extend_price_vintage(new,old)


def pending_split_pair():
    dates = pd.bdate_range('2026-10-26', periods=4)
    old_prices = pd.DataFrame({'A': [100., 110., np.nan]}, index=dates[:3])
    old = market(old_prices, raw=old_prices / 10)
    new_prices = old_prices.reindex(dates)
    new = market(new_prices, raw=new_prices / 400)
    # Provider's split-adjusted history has NOT yet changed, but its new
    # event made inversion divide as-traded prices and multiply volume by40.
    new.volumes.loc[dates[:2], 'A'] = old.volumes.A.iloc[:2] * 40
    new.splits = new.splits.copy()
    new.splits.loc[dates[-1], 'A'] = .025
    from factor_lab.integrated_data import compute_eligibility
    old.eligibility = compute_eligibility(old.prices, old.raw_close, old.volumes, ['A'])
    for m in (old, new):
        for field in ('close', 'open', 'high', 'low'):
            setattr(m, 'raw_' + field, getattr(m, 'raw_' + field).copy())
            setattr(m, 'provider_' + field, m.prices.copy())
        m.provider_volumes = old.volumes.reindex(m.prices.index).copy()
    return old, new


def test_new_split_without_new_quote_preserves_verified_whole_column():
    from factor_lab.integrated_data import FIELDS, PROVIDER_FIELDS, OPTIONAL_FIELDS
    old, new = pending_split_pair()
    original = deepcopy(new)
    fixed = extend_price_vintage(new, old)
    for name in FIELDS + PROVIDER_FIELDS + OPTIONAL_FIELDS:
        a, b = getattr(old, name), getattr(fixed, name)
        if a is None:
            continue
        pd.testing.assert_series_equal(b.A.iloc[:len(a)], a.A, check_freq=False)
        if name == 'eligibility':
            assert not b.A.iloc[-1]
        else:
            assert pd.isna(b.A.iloc[-1])
        pd.testing.assert_frame_equal(getattr(new, name), getattr(original, name))
    report = fixed.metadata['priceVintage']['deferredSplitAdjustments'][0]
    assert report['symbol'] == 'A' and report['currentQuoteStatus'] == 'unavailable'
    assert report['reportedActions'] == [{'date': '2026-10-29', 'ratio': .025}]
    assert not fixed.metadata['priceVintage']['unfrozenSourceRevisions']
    from factor_lab.integrated_automation import validate_required_valuations, RefreshInputError
    # Preserving history must never admit a missing valuation for a held name.
    held = {'data': {'asOf': '2026-10-28'},
            'selection': {'holdings': [{'symbol': 'A', 'weight': 1.}]}, 'factors': []}
    with pytest.raises(RefreshInputError, match='Required holding valuation unavailable'):
        validate_required_valuations(fixed, held, '2026-10-29')


@pytest.mark.parametrize('change', ['new_quote', 'source_revision', 'volume_revision',
                                  'recovered_old_quote', 'dividend', 'old_action'])
def test_split_deferral_never_hides_new_quotes_or_real_revisions(change):
    old, new = pending_split_pair()
    if change == 'new_quote':
        new.prices.iloc[-1, 0] = 4400.
    elif change == 'source_revision':
        new.provider_close.iloc[0, 0] += 1
    elif change == 'volume_revision':
        new.volumes.iloc[0, 0] += 100
    elif change == 'recovered_old_quote':
        new.prices.iloc[-2, 0] = 120.
    elif change == 'dividend':
        new.dividends.iloc[-1, 0] = 2
    elif change == 'old_action':
        new.splits.iloc[0, 0] = .5
    fixed = extend_price_vintage(new, old)
    assert not fixed.metadata['priceVintage']['deferredSplitAdjustments']
    pd.testing.assert_frame_equal(fixed.raw_close, new.raw_close)


def test_split_with_consistently_adjusted_provider_basis_is_not_deferred():
    old, new = pending_split_pair()
    for field in ('close', 'open', 'high', 'low'):
        getattr(new, 'provider_' + field).iloc[:2] *= 40
        getattr(new, 'raw_' + field).iloc[:2] *= 40
    new.prices.iloc[:2] *= 40
    new.volumes.iloc[:2] /= 40
    pd.testing.assert_frame_equal(new.raw_close.iloc[:3], old.raw_close)
    fixed = extend_price_vintage(new, old)
    assert not fixed.metadata['priceVintage']['deferredSplitAdjustments']
    pd.testing.assert_series_equal(fixed.prices.A.iloc[:3], old.prices.A)


def test_pending_split_survives_next_daily_extension_without_a_new_quote(tmp_path):
    from factor_lab.integrated_data import FIELDS, PROVIDER_FIELDS, OPTIONAL_FIELDS
    old, new = pending_split_pair()
    first = extend_price_vintage(new, old)
    first = save_integrated_market(first, tmp_path / 'first')
    following = deepcopy(new)
    index = pd.bdate_range('2026-10-26', periods=5)
    for name in FIELDS + PROVIDER_FIELDS + OPTIONAL_FIELDS:
        frame = getattr(following, name)
        if frame is not None:
            setattr(following, name, frame.reindex(index))
    following.metadata['dataAsOf'] = '2026-10-30'
    second = extend_price_vintage(following, first)
    pd.testing.assert_frame_equal(second.raw_close.iloc[:3], old.raw_close)
    assert second.prices.A.iloc[-2:].isna().all()
    record = second.metadata['priceVintage']['deferredSplitAdjustments'][0]
    assert record['reportedActions'] == [{'date': '2026-10-29', 'ratio': .025}]
    assert record['acceptedSnapshotId'] == first.metadata['snapshotId']


def resumed_split_pair():
    from factor_lab.integrated_data import FIELDS, PROVIDER_FIELDS, OPTIONAL_FIELDS
    old, raw = pending_split_pair()
    accepted = extend_price_vintage(raw, old)
    accepted.metadata['snapshotId'] = 'accepted-deferred-test'
    index = pd.bdate_range('2026-10-26', periods=5)
    current = deepcopy(raw)
    for name in FIELDS + PROVIDER_FIELDS + OPTIONAL_FIELDS:
        frame = getattr(current, name)
        if frame is not None:
            setattr(current, name, frame.reindex(index))
    current.metadata['dataAsOf'] = str(index[-1].date())
    for name in ('prices', 'valuation_prices', 'raw_close', 'raw_open', 'raw_high',
                 'raw_low', 'provider_close', 'provider_open', 'provider_high', 'provider_low'):
        getattr(current, name).loc[index[-1], 'A'] = 4400.
    for name in ('volumes', 'provider_volumes'):
        getattr(current, name).loc[index[-1], 'A'] = 1000.
    for name in ('splits', 'dividends'):
        getattr(current, name).loc[index[-1], 'A'] = 0.
    return accepted, current


def test_pending_split_quote_resumption_rebases_units_without_inventing_returns():
    accepted, current = resumed_split_pair()
    current.provider_volumes = current.provider_volumes.fillna(0).astype('int64')
    original = deepcopy(current)
    fixed = extend_price_vintage(current, accepted)
    pd.testing.assert_series_equal(fixed.raw_close.A.iloc[:len(accepted.prices)],
                                   accepted.raw_close.A, check_freq=False)
    pd.testing.assert_series_equal(fixed.prices.A.iloc[:len(accepted.prices)],
                                   accepted.prices.A, check_freq=False)
    assert fixed.prices.A.iloc[-1] == 110.  # 4400 / (110 * 40), not a 40x return
    assert fixed.raw_close.A.iloc[-1] == 4400.
    assert fixed.provider_close.A.iloc[0] == 4000.
    assert fixed.volumes.A.iloc[0] == accepted.volumes.A.iloc[0]
    assert fixed.provider_volumes.A.iloc[0] == current.provider_volumes.A.iloc[0] / 40
    assert not fixed.metadata['priceVintage']['unfrozenSourceRevisions']
    assert fixed.metadata['priceVintage']['normalizedSplitBases'][0]['providerHistoryScale'] == 40.
    assert not fixed.metadata['priceVintage']['deferredSplitAdjustments']
    for name in ('prices', 'raw_close', 'provider_close', 'volumes', 'provider_volumes'):
        pd.testing.assert_frame_equal(getattr(current, name), getattr(original, name))


@pytest.mark.parametrize('change', ['unreviewed_action', 'changed_action', 'new_action', 'ohlc_revision',
                                  'volume_revision', 'dividend', 'recovered_pre_action_quote'])
def test_quote_resumption_never_hides_unproven_or_revised_split_history(change):
    accepted, current = resumed_split_pair()
    if change == 'unreviewed_action':
        accepted.metadata['priceVintage']['deferredSplitAdjustments'] = []
    elif change == 'changed_action':
        current.splits.loc['2026-10-29', 'A'] = .05
    elif change == 'new_action':
        current.splits.loc['2026-10-30', 'A'] = .5
    elif change == 'ohlc_revision':
        current.provider_open.iloc[0, 0] += 1
    elif change == 'volume_revision':
        current.provider_volumes.iloc[0, 0] += 1
    elif change == 'dividend':
        current.dividends.iloc[0, 0] = 1
    else:
        current.prices.loc['2026-10-28', 'A'] = 120.
    fixed = extend_price_vintage(current, accepted)
    assert not fixed.metadata['priceVintage']['normalizedSplitBases']
    assert fixed.raw_close.A.iloc[0] == current.raw_close.A.iloc[0]


def test_normalized_split_survives_serialization_and_provider_history_catchup(tmp_path):
    accepted, current = resumed_split_pair()
    fixed = save_integrated_market(extend_price_vintage(current, accepted), tmp_path / 'accepted')
    from factor_lab.integrated_data import load_integrated_market
    fixed = load_integrated_market(tmp_path / 'accepted')
    repeated = extend_price_vintage(current, fixed)
    pd.testing.assert_frame_equal(repeated.prices, fixed.prices, check_freq=False)
    assert repeated.metadata['priceVintage']['normalizedSplitBases']
    # Provider finally rebases history. No second correction is applied.
    caught_up = deepcopy(current)
    before = caught_up.prices.index < pd.Timestamp('2026-10-29')
    for name in ('prices', 'valuation_prices', 'raw_close', 'raw_open', 'raw_high',
                 'raw_low', 'provider_close', 'provider_open', 'provider_high', 'provider_low'):
        getattr(caught_up, name).loc[before, 'A'] *= 40
    for name in ('volumes', 'provider_volumes'):
        getattr(caught_up, name).loc[before, 'A'] /= 40
    result = extend_price_vintage(caught_up, fixed)
    assert not result.metadata['priceVintage']['normalizedSplitBases']
    pd.testing.assert_frame_equal(result.prices, fixed.prices, check_freq=False)
    pd.testing.assert_frame_equal(result.raw_close, fixed.raw_close, check_freq=False)


def test_cache_binding_and_repeated_extension_use_canonical_not_fresh_raw(tmp_path):
    dates=pd.bdate_range('2026-10-15',periods=3)
    old=market(pd.DataFrame({'A':[90.,99.]},index=dates[:2]),
               raw=pd.DataFrame({'A':[100.,110.]},index=dates[:2]))
    save_integrated_market(old,tmp_path/'first/raw')
    baseline={'data':{'asOf':old.metadata['dataAsOf'],
        'inputCache':{'rawSnapshotId':old.metadata['snapshotId']}}}
    loaded=load_accepted_vintage(tmp_path/'first',baseline)
    new=market(pd.DataFrame({'A':[45.,49.5,54.]},index=dates),
               raw=pd.DataFrame({'A':[100.,110.,120.]},index=dates))
    save_integrated_market(new,tmp_path/'second/raw')
    fixed=extend_price_vintage(new,loaded)
    save_integrated_market(fixed,tmp_path/'second/raw/price-vintage')
    baseline['data'].update(asOf=fixed.metadata['dataAsOf'],inputCache={
        'rawSnapshotId':new.metadata['snapshotId'], 'priceVintageSnapshotId':fixed.metadata['snapshotId']})
    reloaded=load_accepted_vintage(tmp_path/'second',baseline)
    pd.testing.assert_frame_equal(reloaded.prices,fixed.prices,check_freq=False)
    baseline['data']['inputCache']['priceVintageSnapshotId']='wrong'
    with pytest.raises(ValueError,match='does not belong'):
        load_accepted_vintage(tmp_path/'second',baseline)
    (tmp_path/'second/raw/price-vintage/prices.csv.gz').write_bytes(b'tamper')
    with pytest.raises(ValueError,match='hash mismatch'):
        load_accepted_vintage(tmp_path/'second',baseline)


@pytest.mark.parametrize('case,issues', [('latest',5),('earlier',4)])
def test_original_nav_failures_still_hit_unchanged_guard(case,issues):
    from factor_lab.integrated_automation import history_revision
    recorded=json.loads((FIXTURE/'nav-revisions.json').read_text())[case]
    report=history_revision(recorded['baseline'],recorded['candidate'])
    assert report['threshold']==.001
    assert report['status']=='review_required'
    assert len(report['issues'])==issues
    assert report['maximumRelativeNavRevision']==recorded['report']['maximumRelativeNavRevision']


def test_workflow_preserves_original_cache_paths_and_retains_vintage_audit():
    workflow=(Path(__file__).parents[1]/'.github/workflows/daily-dashboard.yml').read_text()
    # A new top-level cache path changes Actions' cache version, making the
    # last-good pre-fix cache impossible to restore under its existing key.
    assert 'outputs/factor-daily/*/raw/price-vintage/manifest.json' in workflow
    assert 'outputs/factor-daily/*/price-vintage.json' in workflow
    assert '${{ steps.archive.outputs.path }}/raw\n' in workflow


@pytest.mark.parametrize('revision', ['none','nav','choice','gap'])
def test_daily_path_calculates_from_bound_vintage_and_keeps_downloads(tmp_path,monkeypatch,revision):
    from factor_lab import integrated_automation as automation
    from factor_lab import integrated_data as data, integrated_service as service
    from factor_lab import integrated_validation as validation
    dates=pd.bdate_range('2026-10-15',periods=3)
    old=market(pd.DataFrame({'A':[90.,99.]},index=dates[:2]),
               raw=pd.DataFrame({'A':[100.,110.]},index=dates[:2]))
    save_integrated_market(old,tmp_path/'archive/raw')
    baseline=tmp_path/'site'
    (baseline/'data').mkdir(parents=True)
    payload=dict(settings={},registry=[],
        selection={'nav':[],'history':[{'signalDate':'2026-09-30','status':'selected','factorId':'A'}]},
        factors=[{'id':'A','nav':[{'date':'2026-10-15','value':1.}]}],
        data={'asOf':old.metadata['dataAsOf'],'symbols':[],
              'inputCache':{'rawSnapshotId':old.metadata['snapshotId']}})
    (baseline/'data/integrated-result.json').write_text(json.dumps(payload))
    def collect(path,*args,**kwargs):
        fresh=market(pd.DataFrame({'A':[45.,49.5,54.]},index=dates),
                     raw=pd.DataFrame({'A':[100.,110.,120.]},index=dates))
        if revision != 'none':
            fresh.raw_close=fresh.raw_close.copy()
            fresh.raw_close.iloc[0,0]=101.  # a genuine source change, not price noise
        return save_integrated_market(fresh,path)
    def calculate(m,*args):
        if revision == 'none':
            assert m.prices.A.to_list()==[90.,99.,108.]
        else:
            assert m.prices.A.to_list()==[45.,49.5,54.]  # complete fresh basis
            assert m.metadata['priceVintage']['unfrozenSourceRevisions'][0]['symbol']=='A'
        result={**deepcopy(payload),'data':{**m.metadata,'asOf':str(dates[-1].date())},
                'resultIdentity':{'resultId':'new'}}
        if revision == 'nav':
            result['factors'][0]['nav'][0]['value']=1.002
        elif revision == 'choice':
            result['selection']['history'][0]['factorId']='B'
        elif revision == 'gap':
            result['factors'][0]['nav'][0]['value']=None
        return result
    def policy(m,*args):
        m.metadata['automationPolicy']={}
        return m
    def build(path,result):
        path.mkdir()
        (path/'result.json').write_text(json.dumps(result))
    monkeypatch.setattr(automation,'current_source',lambda:'source')
    monkeypatch.setattr(automation,'freshness',lambda *a:{'target_data_as_of':str(dates[-1].date())})
    monkeypatch.setattr(automation,'reconcile_policy',policy)
    monkeypatch.setattr(automation,'validate_market_refresh',lambda *a:{})
    monkeypatch.setattr(data,'collect_integrated_market',collect)
    monkeypatch.setattr(service,'execute_run',calculate)
    monkeypatch.setattr(service,'build_site',build)
    monkeypatch.setattr(validation,'validate_automated_result',lambda *a,**kw:{})
    monkeypatch.setattr(validation,'write_automated_manifest',lambda *a:None)
    monkeypatch.setenv('FACTOR_INPUT_CACHE_KEY','factor-input-v1-test-1')
    before=automation.tree_hash(baseline)
    if revision != 'none':
        with pytest.raises(ValueError,match='Historical NAV or choices changed'):
            automation.run(tmp_path/'run',baseline,tmp_path/'candidate','source',
                           archived_input_root=tmp_path/'archive')
        report=json.loads((tmp_path/'run/history-revision.json').read_text())
        expected={'nav':'nav_revision_exceeds_threshold',
                  'choice':'historical_choice_changed','gap':'observation_or_null_changed'}
        assert report['threshold']==.001 and report['status']=='review_required'
        assert any(row['reason']==expected[revision] for row in report['issues'])
        status=json.loads((tmp_path/'run/status.json').read_text())
        assert status['state']=='failed' and status['lastGoodPreserved'] is True
        assert automation.tree_hash(baseline)==before
        assert not (tmp_path/'candidate').exists()
        return
    status=automation.run(tmp_path/'run',baseline,tmp_path/'candidate','source',
                          archived_input_root=tmp_path/'archive')
    assert status['state']=='validated'
    raw=data.load_integrated_market(tmp_path/'run/raw')
    assert raw.prices.A.to_list()==[45.,49.5,54.]
    result=json.loads((tmp_path/'candidate/result.json').read_text())
    canonical=load_accepted_vintage(tmp_path/'run',result)
    assert canonical.prices.A.to_list()==[90.,99.,108.]


def test_snapshot_roundtrip_preserves_bits_across_future_daily_runs(tmp_path):
    from factor_lab.integrated_data import load_integrated_market
    from factor_lab.integrated_archive import load_archived_columns
    prices=pd.DataFrame({'A':[np.nextafter(1.3,np.inf),np.nextafter(1.2,np.inf)]},
                        index=pd.bdate_range('2026-10-15',periods=2))
    original=market(prices)
    saved=save_integrated_market(original,tmp_path/'raw')
    loaded=load_integrated_market(tmp_path/'raw')
    np.testing.assert_array_equal(loaded.prices.to_numpy(),prices.to_numpy())
    archived=load_archived_columns(tmp_path/'raw',{'A'})
    np.testing.assert_array_equal(archived.prices.to_numpy(),prices.to_numpy())
    save_integrated_market(loaded,tmp_path/'again')
    reloaded=load_integrated_market(tmp_path/'again')
    np.testing.assert_array_equal(reloaded.prices.to_numpy(),saved.prices.to_numpy())


def test_actual_avvsy_late_quote_that_blocked_first_recovery_is_retained():
    records=json.loads((FIXTURE/'late-observation.json').read_text())
    def load(label):
        frames={k:pd.DataFrame(rows).set_index('Date') for k,rows in records[label]['fields'].items()}
        for frame in frames.values():
            frame.index=pd.to_datetime(frame.index)
        return market(frames['prices'],raw=frames['raw_close'],volumes=frames['volumes'],
                      identity=records[label]['rawSnapshotId'])
    old,new=load('baseline'),load('current')
    # Actions fields are zero on the missing-price rows as in the raw source.
    for m in (old,new):
        m.dividends=m.prices*0
        m.splits=m.prices*0
        m.dividends=m.dividends.fillna(0)
        m.splits=m.splits.fillna(0)
    fixed=extend_price_vintage(new,old)
    assert pd.isna(old.prices.at['2026-10-19','AVVSY'])
    assert fixed.prices.at['2026-10-19','AVVSY']==8.170000076293945
    assert fixed.volumes.at['2026-10-19','AVVSY']==466
    pd.testing.assert_frame_equal(fixed.prices,new.prices)
    assert fixed.metadata['priceVintage']['unfrozenSourceRevisions'][0]['symbol']=='AVVSY'
