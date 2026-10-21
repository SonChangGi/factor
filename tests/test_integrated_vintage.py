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


@pytest.mark.parametrize('field', ['raw_close','volumes','dividends','splits'])
def test_real_source_revision_is_not_silently_frozen(field):
    old=recorded('baseline',['ATEN','NBR'],'2018-01-02')
    new=deepcopy(old)
    getattr(new,field).iloc[100,0] += 1
    with pytest.raises(ValueError,match='Historical source revision requires review'):
        extend_price_vintage(new,old)


def test_missing_observation_or_calendar_cannot_be_filled_from_old_snapshot():
    old=recorded('baseline',['ATEN','NBR'],'2018-01-02')
    new=deepcopy(old)
    new.prices.iloc[100,0]=np.nan
    with pytest.raises(ValueError,match='null state'):
        extend_price_vintage(new,old)
    new=replace(old,prices=old.prices.iloc[1:])
    with pytest.raises(ValueError,match='calendar'):
        extend_price_vintage(new,old)


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


def test_daily_path_calculates_from_bound_vintage_and_keeps_downloads(tmp_path,monkeypatch):
    from factor_lab import integrated_automation as automation
    from factor_lab import integrated_data as data, integrated_service as service
    from factor_lab import integrated_validation as validation
    dates=pd.bdate_range('2026-10-15',periods=3)
    old=market(pd.DataFrame({'A':[90.,99.]},index=dates[:2]),
               raw=pd.DataFrame({'A':[100.,110.]},index=dates[:2]))
    save_integrated_market(old,tmp_path/'archive/raw')
    baseline=tmp_path/'site'
    (baseline/'data').mkdir(parents=True)
    payload=dict(settings={},registry=[],selection={'nav':[],'history':[]},factors=[],
        data={'asOf':old.metadata['dataAsOf'],'symbols':[],
              'inputCache':{'rawSnapshotId':old.metadata['snapshotId']}})
    (baseline/'data/integrated-result.json').write_text(json.dumps(payload))
    def collect(path,*args,**kwargs):
        fresh=market(pd.DataFrame({'A':[45.,49.5,54.]},index=dates),
                     raw=pd.DataFrame({'A':[100.,110.,120.]},index=dates))
        return save_integrated_market(fresh,path)
    def calculate(m,*args):
        assert m.prices.A.to_list()==[90.,99.,108.]
        return {**payload,'data':{**m.metadata,'asOf':str(dates[-1].date())},
                'resultIdentity':{'resultId':'new'}}
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
