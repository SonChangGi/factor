import sys
from types import SimpleNamespace

import pandas as pd
import pytest
from factor_lab.config import RunConfig
from factor_lab.live_data import _repair_yfinance_latest_session


def history():
    dates = pd.to_datetime(['2026-09-18', '2026-09-21'])
    return tuple(pd.DataFrame({'AAA': values, 'BBB': other}, index=dates) for values, other in (
        ([90., float('nan')], [50., 51.]),
        ([100., float('nan')], [50., 51.]),
        ([1000., 1100.], [2000., 2200.]),
        ([0., 0.], [0., 0.]),
    ))


def quote(date='2026-09-21', *, close=110., adjusted=99., volume=1100.):
    return pd.DataFrame({'Adj Close': [adjusted], 'Close': [close],
                         'Volume': [volume], 'Stock Splits': [0.]},
                        index=pd.to_datetime([date]))


def config():
    return RunConfig(end_date='2026-09-21', require_current_session=True,
                     retry_count=1, retry_backoff_seconds=0)


def test_narrow_request_recovers_actual_quote_without_changing_history(monkeypatch):
    calls = []
    def download(**kwargs):
        calls.append(kwargs)
        return quote()
    monkeypatch.setitem(sys.modules, 'yfinance', SimpleNamespace(download=download))
    before = history()
    after, diagnostics = _repair_yfinance_latest_session(['AAA', 'BBB'], config(), before)
    for original, result in zip(before, after):
        pd.testing.assert_series_equal(original.iloc[0], result.iloc[0])
        pd.testing.assert_series_equal(original['BBB'], result['BBB'])
    assert [frame.loc['2026-09-21', 'AAA'] for frame in after] == [99., 110., 1100., 0.]
    assert calls[0]['start'] == '2026-09-21'
    assert calls[0]['end'] == '2026-09-22'
    assert calls[0]['tickers'] == ['AAA']
    assert diagnostics['latestSessionRepairedCount'] == 1


def test_incomplete_http_success_is_retried(monkeypatch):
    calls = []
    def download(**kwargs):
        calls.append(kwargs)
        return quote(adjusted=float('nan')) if len(calls) == 1 else quote()
    monkeypatch.setitem(sys.modules, 'yfinance', SimpleNamespace(download=download))
    after, diagnostic = _repair_yfinance_latest_session(['AAA', 'BBB'], config(), history())
    assert after[0].loc['2026-09-21', 'AAA'] == 99.
    assert diagnostic['latestSessionAttempts'] == 2


@pytest.mark.parametrize('bad_quote', [quote('2026-09-22'), quote(adjusted=float('nan')),
    quote(volume=0), quote().drop(columns=['Adj Close'])])
def test_future_incomplete_or_unadjusted_quotes_cannot_fill_target(monkeypatch, bad_quote):
    monkeypatch.setitem(sys.modules, 'yfinance', SimpleNamespace(download=lambda **kwargs: bad_quote))
    before = history()
    after, diagnostic = _repair_yfinance_latest_session(['AAA', 'BBB'], config(), before)
    for original, result in zip(before, after):
        pd.testing.assert_frame_equal(original, result)
    assert diagnostic['latestSessionMissingSymbols'] == ['AAA']
    assert diagnostic['latestSessionAttempts'] == 2


def test_complete_session_never_requests_duplicate_data(monkeypatch):
    def forbidden(**kwargs):
        pytest.fail('complete quotes must not trigger a network call')
    monkeypatch.setitem(sys.modules, 'yfinance', SimpleNamespace(download=forbidden))
    original = tuple(frame[['BBB']] for frame in history())
    _, diagnostic = _repair_yfinance_latest_session(['BBB'], config(), original)
    assert diagnostic['latestSessionAttempts'] == 0
