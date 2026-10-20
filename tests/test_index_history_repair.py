import json
import sys
from io import BytesIO
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

from factor_lab.config import RunConfig
from factor_lab import live_data


def inputs():
    dates = pd.to_datetime(['2026-09-21', '2026-09-22', '2026-09-23', '2026-09-24'])
    prices = pd.DataFrame({'^IXIC': [27122.089844, float('nan'), 26936.039062, 26939.373047],
                           'SPY': [773.50, 773.38, 767.81, 767.18]}, index=dates)
    config = RunConfig(end_date='2026-09-24', require_current_session=True,
                       retry_count=1, retry_backoff_seconds=0)
    return prices, config


def response():
    return {'status': {'rCode': 200}, 'data': {'symbol': 'COMP', 'tradesTable': {'rows': [
        {'date': '09/21/2026', 'close': '27,122.09', 'volume': '--'},
        {'date': '09/22/2026', 'close': '27,244.28', 'volume': '--'},
        {'date': '09/23/2026', 'close': '26,936.04', 'volume': '--'},
    ]}}}


def test_official_index_recovers_only_missing_cell_and_records_provenance(monkeypatch):
    prices, config = inputs()
    calls = []
    def fetch(request, **kwargs):
        calls.append(request.full_url)
        return BytesIO(json.dumps(response()).encode())
    monkeypatch.setattr(live_data, 'urlopen', fetch)
    repaired, raw, sources = live_data._repair_nasdaq_composite_gaps(prices, prices.copy(), config)
    assert repaired.loc['2026-09-22', '^IXIC'] == 27244.28
    assert raw.loc['2026-09-22', '^IXIC'] == 27244.28
    pd.testing.assert_frame_equal(repaired.loc[prices['^IXIC'].notna()],
                                  prices.loc[prices['^IXIC'].notna()])
    pd.testing.assert_series_equal(repaired['SPY'], prices['SPY'])
    assert pd.isna(prices.loc['2026-09-22', '^IXIC'])
    assert parse_qs(urlparse(calls[0]).query)['assetclass'] == ['index']
    assert len(calls) == 1
    receipt = json.loads(sources.iloc[0]['note'])
    assert receipt['repairedCloses'] == {'2026-09-22': 27244.28}
    assert receipt['overlapObservations'] == 2


@pytest.mark.parametrize('fault', ['wrong_symbol', 'wrong_date', 'anchor_mismatch',
                                  'duplicate_date', 'negative', 'empty'])
def test_unverified_index_response_never_modifies_input(monkeypatch, fault):
    prices, config = inputs()
    payload = response()
    rows = payload['data']['tradesTable']['rows']
    if fault == 'wrong_symbol': payload['data']['symbol'] = 'NDX'
    elif fault == 'wrong_date': rows[1]['date'] = '09/25/2026'
    elif fault == 'anchor_mismatch': rows[0]['close'] = '100'
    elif fault == 'duplicate_date': rows.append(rows[1].copy())
    elif fault == 'negative': rows[1]['close'] = '-1'
    else: payload['data']['tradesTable']['rows'] = []
    calls = []
    def fetch(*args, **kwargs):
        calls.append(1)
        return BytesIO(json.dumps(payload).encode())
    monkeypatch.setattr(live_data, 'urlopen', fetch)
    repaired, raw, sources = live_data._repair_nasdaq_composite_gaps(prices, prices.copy(), config)
    pd.testing.assert_frame_equal(repaired, prices)
    pd.testing.assert_frame_equal(raw, prices)
    assert sources.iloc[0]['status'] == 'failed'
    assert len(calls) == 2


def test_complete_history_does_not_fetch(monkeypatch):
    prices, config = inputs()
    prices.loc['2026-09-22', '^IXIC'] = 27244.28
    monkeypatch.setattr(live_data, 'urlopen', lambda *a, **kw: pytest.fail('duplicate fetch'))
    _, _, sources = live_data._repair_nasdaq_composite_gaps(prices, prices.copy(), config)
    assert sources.empty


def test_incomplete_response_is_retried(monkeypatch):
    prices, config = inputs()
    calls = []
    def fetch(*args, **kwargs):
        calls.append(1)
        payload = response()
        if len(calls) == 1: payload['data']['tradesTable']['rows'].pop(1)
        return BytesIO(json.dumps(payload).encode())
    monkeypatch.setattr(live_data, 'urlopen', fetch)
    repaired, _, sources = live_data._repair_nasdaq_composite_gaps(prices, prices.copy(), config)
    assert repaired.loc['2026-09-22', '^IXIC'] == 27244.28
    assert sources.iloc[0]['retries'] == 1


def test_acquisition_retains_repair_provenance(monkeypatch):
    prices, config = inputs()
    prices['AAA'] = 100.
    volumes = pd.DataFrame(1000000., index=prices.index, columns=prices.columns)
    splits = volumes * 0
    candidate = pd.DataFrame({'symbol': ['AAA'], 'name': ['Example'], 'is_etf': [False],
                              'asset_type': ['stock'], 'exchange': ['NASDAQ']})
    config.yahoo_chart_fallback_limit = config.nasdaq_fallback_limit = 0
    config.stooq_fallback_limit = config.finance_datareader_fallback_limit = 0
    monkeypatch.setitem(sys.modules, 'yfinance', SimpleNamespace())
    monkeypatch.setattr(live_data, '_candidate_universe', lambda config: (candidate, pd.DataFrame()))
    monkeypatch.setattr(live_data, '_requested_symbols', lambda *a: (list(prices.columns), False))
    monkeypatch.setattr(live_data, '_download_yfinance', lambda *a: (
        prices, prices.copy(), volumes, splits,
        pd.DataFrame([{'source': 'yfinance-adjusted-daily', 'records': 3}]),
    ))
    monkeypatch.setattr(live_data, 'urlopen', lambda *a, **kw: BytesIO(json.dumps(response()).encode()))
    result = live_data.download_live_data(config)
    records = result.data_sources.loc[result.data_sources.source.eq('nasdaq-composite-history-repair')]
    assert len(records) == 1
    assert json.loads(records.iloc[0]['note'])['repairedCloses'] == {'2026-09-22': 27244.28}
    assert 'nasdaq-composite-history-repair' in result.provider
    source = result.price_sources.set_index('symbol').loc['^IXIC', 'price_source']
    assert 'nasdaq-composite-history-repair' in source
    assert result.raw_prices.loc['2026-09-22', '^IXIC'] == 27244.28
