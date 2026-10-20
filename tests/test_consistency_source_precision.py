from copy import deepcopy

import numpy as np
import pandas as pd

from factor_lab.integrated_data import IntegratedMarket
from factor_lab.integrated_factors import consistency_return_signs, factor_registry


def market(closes, cash=None, provider=True):
    c = pd.DataFrame({'A': closes}, index=pd.bdate_range('2015-01-01', periods=len(closes)))
    d = c * 0
    if cash is not None:
        d['A'] = cash
    return IntegratedMarket(c.copy(), c.copy(), c.copy(), c.copy(), c.copy(),
                            c * 0 + 1000, d, c * 0, c.notna(), {},
                            provider_close=c.copy() if provider else None)


def test_actual_ex_dividend_flat_days_and_real_small_gains():
    for before, after, cash in [(60.16999816894531, 59.720001220703125, .45),
                               (159.0500030517578, 158.99000549316406, .06)]:
        m = market([before, after], [0, cash])
        assert after - before + cash > 0  # naive close+cash is still wrong
        assert consistency_return_signs(m).A.iloc[-1] == 0
    # 0.0001% is far below a generic financial tolerance, but distinguishable
    # at the source precision and must remain a positive return.
    m = market([100., float(np.float32(100.0001))])
    assert consistency_return_signs(m).A.iloc[-1] == 1
    m = market([100., 99.], [0, 2.])
    assert consistency_return_signs(m).A.iloc[-1] == 1
    m.dividends.iloc[-1, 0] = .5
    assert consistency_return_signs(m).A.iloc[-1] == -1


def test_missing_closes_cash_and_unstated_source_do_not_become_flat():
    m = market([100., np.nan, 101., 102., 103.], [0, 0, 0, np.nan, 0])
    result = consistency_return_signs(m).A
    assert result.iloc[:4].isna().all()
    assert result.iloc[4] == 1
    m = market([100., 100.00000001], provider=False)
    assert consistency_return_signs(m).isna().all().all()
    m.metadata['consistencySignSource'] = {
        'basis': 'split_adjusted_raw_close', 'precision': {'kind': 'exact'}}
    assert consistency_return_signs(m).A.iloc[-1] == 1


def test_repaired_split_propagates_original_encoding_bounds():
    original = market([60.16999816894531, 59.720001220703125, 59.73], [0, .45, 0])
    expected = consistency_return_signs(original)
    repaired = deepcopy(original)
    date = repaired.prices.index[-1] + pd.Timedelta(days=1)
    repaired.metadata['amendments'] = [
        {'kind': 'verified_missing_split_normalization', 'symbol': 'A',
         'date': str(date.date()), 'ratio': .04}]
    repaired.provider_close /= .04
    repaired.dividends /= .04
    pd.testing.assert_frame_equal(consistency_return_signs(repaired), expected)
    # Genuine split on the date has already been normalized in provider close;
    # the raw jump must not enter the sign or cause double split application.
    split = market([25., 25., 25.01])
    split.raw_close.iloc[0, 0] = 100.
    split.splits.iloc[1, 0] = 4.
    assert consistency_return_signs(split).A.tolist()[1:] == [0., 1.]


def test_external_quote_has_its_own_precision_and_future_does_not_change_past():
    m = market([100., 100.001, 101.])
    m.metadata['amendments'] = [{'kind': 'observed_quote', 'symbol': 'A',
                                'date': str(m.prices.index[1].date())}]
    assert consistency_return_signs(m).A.iloc[1:].isna().all()
    m.metadata['amendments'][0]['closePrecision'] = {'kind': 'decimal', 'places': 2}
    assert consistency_return_signs(m).A.iloc[1] == 0
    assert consistency_return_signs(m).A.iloc[2] == 1
    before = consistency_return_signs(m)
    m.provider_close.iloc[-1, 0] *= 2
    m.dividends.iloc[-1, 0] = 3.
    pd.testing.assert_frame_equal(consistency_return_signs(m).iloc[:-1], before.iloc[:-1])
    definition = next(r for r in factor_registry() if r['id'] == 'CONSISTENCY12_1')
    assert definition['version'] == '1.1.0'
    assert definition['signInputContract'] == 'provider-close-cash-source-interval-v1'


def test_only_consistency_uses_new_cash_sign_input_and_keeps_formation_denominator():
    from factor_lab.integrated_factors import compute_integrated_factors

    m = market([100.] * 850)
    for name in ('prices', 'raw_close', 'raw_open', 'raw_high', 'raw_low',
                 'volumes', 'dividends', 'splits', 'eligibility', 'provider_close'):
        frame = getattr(m, name)
        frame['SPY'] = frame['A']
    m.eligibility['SPY'] = False
    original_prices = m.prices.copy()
    baseline = compute_integrated_factors(m)
    changed_day = m.prices.index[400]
    m.dividends.loc[changed_day, 'A'] = .01
    changed = compute_integrated_factors(m)
    for key in baseline:
        if key != 'CONSISTENCY12_1':
            pd.testing.assert_frame_equal(changed[key], baseline[key])
    pd.testing.assert_frame_equal(m.prices, original_prices)
    ends = m.prices.groupby(m.prices.index.to_period('M')).tail(1).index
    k = next(i for i in range(12, len(ends)) if ends[i - 12] < changed_day <= ends[i - 1])
    observations = ((m.prices.index > ends[k - 12]) & (m.prices.index <= ends[k - 1])).sum()
    assert changed['CONSISTENCY12_1'].at[ends[k], 'A'] == 1 / observations
    assert baseline['CONSISTENCY12_1'].at[ends[k], 'A'] == 0
