import hashlib
import json
import numpy as np
import pandas as pd
import pytest
from factor_lab.integrated_listing import listing_context, provider_symbols, batch_cache_key, normalize_provider_columns
from factor_lab.integrated_data import collect_integrated_market, integrated_universe


def test_dated_listing_preserves_frozen_canonical_membership_and_historical_identity():
    before = listing_context(['CECO', 'IBOC', 'UUU'], '2026-10-18')
    after = listing_context(['CECO', 'IBOC', 'UUU'], '2026-10-19')
    assert before['transitions'] == []
    assert provider_symbols(['UUU'], before) == {'UUU':'UUU'}
    assert provider_symbols(['UUU'], after) == {'UUU':'DCM'}
    assert {r['symbol']:r['exchange'] for r in after['transitions']} == {'CECO':'TXSE','IBOC':'TXSE','UUU':'NYSE American'}
    rows = {r['symbol']:r for r in integrated_universe()['symbols']}
    assert 'UUU' in rows and 'DCM' not in rows and len(rows)==2960
    assert all(r['sameSecurity'] and r['sources'] for r in after['transitions'])
    with pytest.raises(ValueError, match='collides'):
        listing_context(['UUU','DCM'], '2026-10-19')


def test_alias_cache_and_source_columns_cannot_be_confused_with_old_symbol():
    context = listing_context(['UUU'], '2026-10-19')
    assert batch_cache_key(['UUU'], context) != hashlib.sha256(json.dumps(['UUU']).encode()).hexdigest()[:16]
    assert batch_cache_key(['CECO'], context) == hashlib.sha256(json.dumps(['CECO']).encode()).hexdigest()[:16]
    frame=pd.DataFrame({('Adj Close','DCM'):[4.3],('Volume','DCM'):[36696]},index=pd.to_datetime(['2026-10-19']))
    normalized=normalize_provider_columns(frame,['UUU'],context)
    assert normalized[('Adj Close','UUU')].iloc[0]==4.3
    assert ('Adj Close','DCM') in frame  # Original response is never rewritten.
    with pytest.raises(ValueError, match='unexpected security'):
        normalize_provider_columns(frame.rename(columns={'DCM':'UUU'},level=1),['UUU'],context)


def _download(symbols, **kwargs):
    dates=pd.to_datetime(['2026-10-15','2026-10-16','2026-10-19'])
    fields={'Adj Close':9.,'Close':10.,'Open':9.5,'High':11.,'Low':9.,'Volume':2e6,'Dividends':0.,'Stock Splits':0.}
    return pd.DataFrame({(field,symbol):[value]*3 for symbol in symbols for field,value in fields.items()},index=dates)


def test_collector_requests_new_provider_symbol_but_all_outputs_remain_canonical(tmp_path,monkeypatch):
    import yfinance as yf
    calls=[]
    def download(symbols,**kwargs):
        calls.append(symbols)
        return _download(symbols,**kwargs)
    monkeypatch.setattr(yf,'download',download)
    market=collect_integrated_market(tmp_path/'new',start='2010-01-01',end='2026-10-20',symbols=['UUU','CECO','IBOC'])
    assert 'DCM' in calls[0] and 'UUU' not in calls[0]
    assert 'UUU' in market.prices and 'DCM' not in market.prices
    assert market.metadata['listing']['version']==market.metadata['request']['listing']['version']
    assert market.metadata['receipts'][0]['providerSymbols']['UUU']=='DCM'
    assert market.metadata['receipts'][0]['listingSourceHash']==market.metadata['listing']['sourceHash']
    from factor_lab.integrated_service import data_inventory
    inventory={row['symbol']:row for row in data_inventory(market)}
    assert inventory['UUU']['providerTicker']=='DCM' and inventory['UUU']['name']=='DeFi Capital Markets Inc.'
    assert inventory['CECO']['exchange']=='TXSE' and inventory['IBOC']['exchange']=='TXSE'
    raw=pd.read_csv(next((tmp_path/'new/downloads').glob('*.csv.gz')),header=[0,1],index_col=0)
    assert ('Adj Close','DCM') in raw and ('Adj Close','UUU') not in raw
    historical=collect_integrated_market(tmp_path/'old',start='2010-01-01',end='2026-10-18',symbols=['UUU'])
    assert 'UUU' in calls[-1] and 'DCM' not in calls[-1]
    assert historical.metadata['listing']['transitions']==[]


def test_alias_truncated_history_still_fails_before_analysis(tmp_path,monkeypatch):
    import yfinance as yf
    calls=[]
    def download(symbols,**kwargs):
        calls.append(list(symbols))
        frame=_download(symbols,**kwargs)
        if 'DCM' in symbols:
            frame.loc[frame.index[:-1],pd.IndexSlice[:,'DCM']]=np.nan
        return frame
    monkeypatch.setattr(yf,'download',download)
    monkeypatch.setattr('factor_lab.integrated_data.time.sleep',lambda *a:None)
    with pytest.raises(ValueError,match='Truncated historical input'):
        collect_integrated_market(tmp_path,start='2010-01-01',end='2026-10-20',symbols=['UUU'],
            reference_coverage={'UUU':dict(observations=2,firstObservation='2026-10-15',asOf='2026-10-16')})
    assert calls[1:]==[['DCM'],['DCM']]


def test_seed_keeps_old_request_evidence_and_upgrades_only_provider_contract(tmp_path):
    from factor_lab.integrated_automation import seed_download_cache
    old=tmp_path/'old/raw';old.mkdir(parents=True);(old/'downloads').mkdir()
    request=dict(start='2010-01-01',endExclusive='2026-10-20',symbols=['UUU'])
    (old/'request.json').write_text(json.dumps(request))
    manifest=dict(dataAsOf='2026-10-19',request=request,files={})
    manifest['snapshotId']=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
    (old/'manifest.json').write_text(json.dumps(manifest))
    destination=tmp_path/'new/raw'
    seed_download_cache(old.parent,destination,'2026-10-19')
    assert json.loads((destination/'reuse-source-request.json').read_text())==request
    current=json.loads((destination/'request.json').read_text())
    assert {key:current[key] for key in request}==request
    assert provider_symbols(['UUU'],current['listing'])=={'UUU':'DCM'}


def test_collector_cannot_reuse_old_uuu_batch_even_when_its_hash_is_valid(tmp_path,monkeypatch):
    import yfinance as yf
    from factor_lab.integrated_data import BENCHMARKS
    cache=tmp_path/'downloads';cache.mkdir()
    symbols=sorted({'UUU',*BENCHMARKS})
    key=hashlib.sha256(json.dumps(symbols).encode()).hexdigest()[:16]
    poison=_download(symbols)*100
    path=cache/(key+'.csv.gz');poison.to_csv(path,compression='gzip')
    path.with_suffix('.json').write_text(json.dumps(dict(symbols=symbols,retrievedAt='2026-10-20T00:00:00Z',
        sha256=hashlib.sha256(path.read_bytes()).hexdigest())))
    calls=[]
    def download(requested,**kwargs):
        calls.append(requested)
        return _download(requested,**kwargs)
    monkeypatch.setattr(yf,'download',download)
    market=collect_integrated_market(tmp_path,start='2010-01-01',end='2026-10-20',symbols=['UUU'])
    assert calls==[['QQQ','SPY','DCM','^IXIC']]
    assert market.prices.UUU.iloc[-1]==9.0
    assert market.metadata['receipts'][0]['providerSymbols']['UUU']=='DCM'


def test_immutable_snapshot_rejects_changed_listing_evidence(tmp_path,monkeypatch):
    import yfinance as yf
    import factor_lab.integrated_listing as listing
    monkeypatch.setattr(yf,'download',_download)
    collect_integrated_market(tmp_path/'market',start='2010-01-01',end='2026-10-20',symbols=['UUU'])
    resource=tmp_path/'listing.json'
    payload=json.loads(listing.RESOURCE.read_text());payload['version']='future-ledger-reviewed-v2'
    resource.write_text(json.dumps(payload));monkeypatch.setattr(listing,'RESOURCE',resource)
    with pytest.raises(ValueError,match='different dated listing contract'):
        collect_integrated_market(tmp_path/'market',start='2010-01-01',end='2026-10-20',symbols=['UUU'])
