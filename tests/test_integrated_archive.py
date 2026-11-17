import pandas as pd
import pytest
from factor_lab.integrated_data import IntegratedMarket, save_integrated_market
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
