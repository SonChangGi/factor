from copy import deepcopy

import numpy as np
import pandas as pd

from factor_lab.integrated_data import IntegratedMarket
from factor_lab.integrated_factors import (
    compute_integrated_factors, consistency_return_signs, factor_registry, source_holding_returns,
)


def market(closes, cash=None):
    c = pd.DataFrame({'A': closes, 'SPY': [100.] * len(closes)},
                     index=pd.bdate_range('2023-09-01', periods=len(closes)))
    d = c * 0
    if cash is not None:
        d['A'] = cash
    e = c.notna()
    e['SPY'] = False
    return IntegratedMarket(c.copy(), c.copy(), c.copy(), c.copy(), c.copy(),
                            c * 0 + 1000, d, c * 0, e, {}, provider_close=c.copy())


def test_actual_max_boundary_returns_remain_distinct_and_vintage_invariant():
    cases = [(9.770000457763672, 9.75, .15),
             (5.920000076293945, 6., 0.),
             (135.08999633789062, 136.6699981689453, 0.),
             (10.260000228881836, 10.380000114440918, 0.)]
    results = []
    for previous, current, cash in cases:
        m = market([previous, current], [0, cash])
        actual = source_holding_returns(m).A.iloc[-1]
        assert np.isclose(actual, (current + cash) / previous - 1, atol=1e-15)
        changed = deepcopy(m)
        changed.prices.iloc[0, 0] *= 1 + 4e-7
        pd.testing.assert_frame_equal(source_holding_returns(changed), source_holding_returns(m))
        results.append(actual)
    assert results[0] < results[1]  # F dividend holding return is NOT tied with PSEC.
    assert results[2] > results[3]  # Preserve close differences; do not epsilon-tie INGR/WU.


def test_actual_signed_boundary_dividend_days_are_neutral():
    # AON 2018-08-09, HTH 2021-02-11, ESLT 2021-12-17.
    for previous, current, cash in [
        (143.3800048828125, 142.97999572753906, .4),
        (31.739999771118164, 31.6200008392334, .12),
        (172.08999633789062, 171.6300048828125, .46),
    ]:
        m = market([previous, current], [0, cash])
        assert consistency_return_signs(m).A.iloc[-1] == 0.


def test_holding_return_missing_basis_zero_denominator_and_split_basis():
    m = market([100., 101., 0., 102., 103., np.nan, 104.], [0, 0, 0, 0, np.nan, 0, 0])
    result = source_holding_returns(m).A
    assert result.iloc[[0, 2, 3, 4, 5, 6]].isna().all()
    assert result.iloc[1] == .01
    m = market([25., 25., 25.25], [0, 0, .25])
    m.raw_close.iloc[0, 0] = 100.
    m.splits.iloc[1, 0] = 4.
    assert source_holding_returns(m).A.iloc[1:].tolist() == [0., .02]
    scaled = deepcopy(m)
    scaled.provider_close /= 10
    scaled.dividends /= 10
    scaled.metadata['amendments'] = [
        {'kind': 'verified_missing_split_normalization', 'symbol': symbol,
         'date': str((m.prices.index[-1] + pd.Timedelta(days=1)).date()), 'ratio': 10.}
        for symbol in m.prices]
    np.testing.assert_allclose(source_holding_returns(scaled), source_holding_returns(m),
                               atol=1e-15, equal_nan=True)
    m.provider_close = None
    assert source_holding_returns(m).isna().all().all()
    m.metadata['holdingReturnSource'] = {'basis': 'split_adjusted_raw_close'}
    m.raw_close.iloc[0, 0] = 25.
    assert source_holding_returns(m).A.iloc[1] == 0.


def test_source_centers_ignore_csv_tails_but_preserve_external_and_exact_quotes():
    m = market([135.08999633789062, 136.6699981689453])
    before = source_holding_returns(m)
    m.provider_close = np.nextafter(m.provider_close, np.inf)
    pd.testing.assert_frame_equal(source_holding_returns(m), before)
    m = market([100., 100.00000001])
    m.metadata['amendments'] = [
        {'kind': 'observed_quote', 'symbol': 'A', 'date': str(date.date()),
         'closePrecision': {'kind': 'exact'}} for date in m.prices.index]
    assert source_holding_returns(m).A.iloc[-1] > 0
    m.metadata['amendments'][0].pop('closePrecision')
    assert source_holding_returns(m).A.isna().all()
    m.provider_close = None
    m.metadata = {'holdingReturnSource': {'basis': 'split_adjusted_raw_close'}}
    assert source_holding_returns(m).A.iloc[-1] > 0


def test_signed_dollar_volume_neutral_cash_day_and_max_complete_month():
    # Flat holding-return day: binary32 closes leave a spurious positive
    # close+cash residual, and adjusted-close vintages can change its sign.
    before, after = 60.16999816894531, 59.720001220703125
    closes = [before] * 40 + [after] * 80
    cash = [0.] * 120
    cash[40] = .45
    m = market(closes, cash)
    m.prices.iloc[40:, 0] = before * (1 + 3e-7)
    one = compute_integrated_factors(m)
    m.prices.iloc[40:, 0] = before * (1 - 3e-7)
    two = compute_integrated_factors(m)
    pd.testing.assert_frame_equal(one['SIGNED_VP63'], two['SIGNED_VP63'])
    pd.testing.assert_frame_equal(one['MAX1M'], two['MAX1M'])
    assert one['SIGNED_VP63'].A.iloc[70] == 0.
    # Real positive direction contributes its entire paired dollar volume.
    m.provider_close.iloc[75:, 0] += .01
    m.raw_close.iloc[75:, 0] += .01
    result = compute_integrated_factors(m)['SIGNED_VP63'].A.iloc[90]
    expected = m.dollar_volumes.A.iloc[75] / m.dollar_volumes.A.iloc[28:91].sum()
    assert np.isclose(result, expected)
    # Missing cash is not a zero distribution; the whole MAX month is unavailable.
    date = m.prices.index[75]
    m.dividends.loc[date, 'A'] = np.nan
    month_end = m.prices.index[m.prices.index.to_period('M') == date.to_period('M')][-1]
    assert pd.isna(compute_integrated_factors(m)['MAX1M'].at[month_end, 'A'])
    definitions = {r['id']: r for r in factor_registry()}
    assert definitions['SIGNED_VP63']['version'] == '1.1.0'
    assert definitions['MAX1M']['returnInputContract'] == 'provider-close-cash-holding-return-v1'
