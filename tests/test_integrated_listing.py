import pandas as pd
import pytest
from factor_lab.integrated_listing import listing_context, provider_symbols
from factor_lab.integrated_data import integrated_universe


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




def _download(symbols, **kwargs):
    dates=pd.to_datetime(['2026-10-15','2026-10-16','2026-10-19'])
    fields={'Adj Close':9.,'Close':10.,'Open':9.5,'High':11.,'Low':9.,'Volume':2e6,'Dividends':0.,'Stock Splits':0.}
    return pd.DataFrame({(field,symbol):[value]*3 for symbol in symbols for field,value in fields.items()},index=dates)
