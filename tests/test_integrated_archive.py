import json
import numpy as np
import pandas as pd
import pytest
from factor_lab.integrated_data import IntegratedMarket, save_integrated_market, collect_integrated_market
from factor_lab.integrated_archive import load_archived_columns, preserve_archived_columns


def archived_market(tmp_path):
    dates=pd.to_datetime(['2025-01-01','2025-01-02','2025-01-03'])
    price=pd.DataFrame({'A':[9.,9.9,10.8]},index=dates)
    close=price/.9; volume=price*0+2e6; zeros=price*0
    market=IntegratedMarket(price,close,close*.95,close*1.1,close*.9,volume,
        zeros,zeros,price.notna(),metadata=dict(dataAsOf='2025-01-03',universeVersion='frozen-union',
            requestedSymbols=['A'],receipts=[dict(symbols=['A'],retrievedAt='2025-01-04T00:00:00Z')]),
        provider_close=close.copy(),provider_open=close*.95,provider_high=close*1.1,
        provider_low=close*.9,provider_volumes=volume.copy(),valuation_prices=price.copy())
    save_integrated_market(market,tmp_path/'raw')
    return market


def test_preserves_complete_vintage_and_rejects_all_unverified_new_rows(tmp_path):
    old=archived_market(tmp_path/'old')
    archive=load_archived_columns(tmp_path/'old/raw',{'A'})
    dates=pd.to_datetime(['2025-01-01','2025-01-02','2025-01-03','2025-01-06'])
    fake=pd.DataFrame({'A':[500.,500.,500.,900.]},index=dates)
    current=IntegratedMarket(fake.copy(),fake.copy(),fake.copy(),fake.copy(),fake.copy(),fake.copy(),
        fake.copy(),fake.copy(),fake.notna(),metadata=dict(dataAsOf='2025-01-06',universeVersion='frozen-union'),
        provider_close=fake.copy(),provider_open=fake.copy(),provider_high=fake.copy(),
        provider_low=fake.copy(),provider_volumes=fake.copy(),valuation_prices=fake.copy())
    reference={'A':dict(observations=3,firstObservation='2025-01-01',asOf='2025-01-03')}
    preserve_archived_columns(current,archive,{'A'},reference)
    for name in ['prices','raw_close','raw_open','raw_high','raw_low','volumes','provider_close',
                 'provider_open','provider_high','provider_low','provider_volumes','dividends','splits']:
        pd.testing.assert_series_equal(getattr(current,name).A.iloc[:3],getattr(old,name).A,check_freq=False)
        assert pd.isna(getattr(current,name).A.iloc[-1])
    ledger=current.metadata['archivedHistory'][0]
    assert ledger['observedThrough']=='2025-01-03' and ledger['sourceAsOf']=='2025-01-03'
    assert ledger['sourceSnapshotId']==old.metadata['snapshotId']
    assert ledger['collectedAt']=='2025-01-04T00:00:00Z'


def test_corrupt_archive_or_different_identity_fails_closed(tmp_path):
    archived_market(tmp_path/'old')
    path=tmp_path/'old/raw/prices.csv.gz';path.write_bytes(path.read_bytes()+b'tamper')
    with pytest.raises(ValueError,match='matrix hash mismatch'):
        load_archived_columns(tmp_path/'old/raw',{'A'})


def test_collector_archives_whole_column_after_bounded_retry_without_new_quote(tmp_path,monkeypatch):
    import yfinance as yf
    from factor_lab.integrated_data import integrated_universe
    old=archived_market(tmp_path/'old')
    # Use the real packaged universe identity in this collector integration.
    old.metadata['universeVersion']=integrated_universe()['version']
    save_integrated_market(old,tmp_path/'matching/raw')
    monkeypatch.setattr('factor_lab.integrated_data.time.sleep',lambda *a:None)
    def download(symbols,**kwargs):
        dates=pd.bdate_range('2025-01-01',periods=4)
        fields={'Adj Close':900.,'Close':1000.,'Open':950.,'High':1100.,'Low':900.,'Volume':2e6,'Dividends':0.,'Stock Splits':0.}
        frame=pd.DataFrame({(field,symbol):[value]*4 for symbol in symbols for field,value in fields.items()},index=dates)
        frame.loc[dates[:-1],pd.IndexSlice[:,'A']]=np.nan
        return frame
    monkeypatch.setattr(yf,'download',download)
    reference={'A':dict(observations=3,firstObservation='2025-01-01',asOf='2025-01-03')}
    new=collect_integrated_market(tmp_path/'new',start='2025-01-01',end='2025-02-01',symbols=['A'],
        reference_coverage=reference,archived_input_root=tmp_path/'matching')
    assert new.prices.A.iloc[:3].to_list()==old.prices.A.to_list()
    assert pd.isna(new.prices.A.iloc[-1]) and not new.eligibility.A.iloc[-1]
    assert new.metadata['inputCoverage']['A']['observations']==3
    assert new.metadata['archivedHistory'][0]['state']=='archived_history_only'
    assert new.metadata['receipts'][-1]['retrievedAt']=='2025-01-04T00:00:00Z'
