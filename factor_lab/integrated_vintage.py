"""Append verified sessions without re-estimating accepted adjusted-price history.

The downloaded snapshot remains immutable.  A separate, hash-bound calculation
vintage keeps accepted observations and joins new quotes using the return between
two observations from the SAME provider response.  Real source revisions fail
closed; a historical NAV is never copied or exempted from validation.
"""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from .integrated_data import load_integrated_market, compute_eligibility


def extend_price_vintage(current, previous):
    cutoff = pd.Timestamp(previous.metadata['dataAsOf'])
    if cutoff > pd.Timestamp(current.metadata['dataAsOf']):
        raise ValueError('Accepted price vintage is from a future session')
    if (previous.metadata['universeVersion'] != current.metadata['universeVersion']
            or not previous.prices.columns.equals(current.prices.columns)):
        raise ValueError('Accepted price vintage universe differs')
    overlap = current.prices.index[current.prices.index <= cutoff]
    if not previous.prices.index.equals(overlap):
        raise ValueError('Accepted price vintage calendar changed')

    # These are economic source observations, not the provider's recomputed
    # dividend-adjusted history.  Only CSV/binary64 round-trip noise is allowed.
    # No NAV tolerance, price rounding or approximate rank tie is used here.
    for name in ('raw_close', 'volumes', 'dividends', 'splits'):
        old = getattr(previous, name).to_numpy(dtype=float)
        new = getattr(current, name).loc[overlap].to_numpy(dtype=float)
        equal = np.isclose(old, new, rtol=8*np.finfo(float).eps, atol=0, equal_nan=True)
        if not equal.all():
            row, col = np.argwhere(~equal)[0]
            raise ValueError(f'Historical source revision requires review: {name} '
                             f'{overlap[row].date()} {current.prices.columns[col]}')
    if not previous.prices.notna().equals(current.prices.loc[overlap].notna()):
        raise ValueError('Historical adjusted-price observation/null state changed')

    prices = current.prices.copy()
    marks = current.valuation_prices.copy() if current.valuation_prices is not None else None
    bridges = []
    revisions = []
    for symbol in prices:
        old = previous.prices[symbol].dropna()
        future = prices.index > cutoff
        if not old.empty and prices.loc[future, symbol].notna().any():
            boundary = old.index[-1]
            fresh = float(current.prices.at[boundary, symbol])
            accepted = float(old.iloc[-1])
            if not np.isfinite([fresh, accepted]).all() or min(fresh, accepted) <= 0:
                raise ValueError('Invalid price-vintage boundary: ' + symbol)
            scale = accepted / fresh
            prices.loc[future, symbol] *= scale
            if marks is not None:
                marks.loc[future, symbol] *= scale
            bridges.append(dict(symbol=symbol, date=str(boundary.date()),
                                accepted=accepted, downloaded=fresh, scale=scale))
        old_values = previous.prices[symbol]
        new_values = current.prices.loc[overlap, symbol]
        valid = old_values.notna()
        differences = (new_values[valid] / old_values[valid] - 1).abs()
        if differences.gt(0).any():
            revisions.append(dict(symbol=symbol, observations=int(differences.gt(0).sum()),
                                  maximumRelativeDifference=float(differences.max())))
        prices.loc[overlap, symbol] = previous.prices[symbol]
        if marks is not None:
            source = previous.valuation_prices
            if source is None:
                raise ValueError('Accepted valuation-price basis is missing')
            marks.loc[overlap, symbol] = source[symbol]
    metadata = deepcopy(current.metadata)
    metadata.pop('files', None)
    metadata.pop('snapshotId', None)
    metadata['priceVintage'] = dict(
        version='accepted-history-same-response-return-v1',
        acceptedSnapshotId=previous.metadata['snapshotId'],
        downloadedSnapshotId=current.metadata['snapshotId'],
        acceptedThrough=str(cutoff.date()), bridges=bridges,
        preservedAdjustedHistoryChanges=revisions,
        sourceChecks=['raw_close', 'volumes', 'dividends', 'splits', 'calendar', 'null_state'])
    metadata['priceBasis'] = ('Yahoo Adj Close returns; accepted historical input vintage '
                              'with same-response returns appended at a verified boundary')
    result = replace(current, prices=prices, valuation_prices=marks, metadata=metadata)
    result.eligibility = compute_eligibility(prices, current.raw_close, current.volumes,
                                             metadata['requestedSymbols'])
    return result


def load_accepted_vintage(archive_root, baseline):
    """Bind the restored cache to the baseline, including subsequent extensions."""
    cache = baseline['data'].get('inputCache', {})
    expected = cache.get('priceVintageSnapshotId') or cache.get('rawSnapshotId')
    if not expected:
        raise ValueError('Baseline has no verified primary input vintage')
    root = Path(archive_root) / 'raw'
    if cache.get('priceVintageSnapshotId'):
        root /= 'price-vintage'
    previous = load_integrated_market(root)
    if previous.metadata['snapshotId'] != expected:
        raise ValueError('Restored price vintage does not belong to the baseline')
    if previous.metadata['dataAsOf'] != baseline['data']['asOf']:
        raise ValueError('Restored price vintage as-of differs from the baseline')
    if previous.metadata.get('amendments') or previous.metadata.get('corporateActions'):
        raise ValueError('Price vintage requires unamended primary input')
    return previous
