"""Append verified sessions without re-estimating accepted adjusted-price history.

The downloaded snapshot remains immutable.  A separate, hash-bound calculation
vintage keeps accepted observations and joins new quotes using the return between
two observations from the SAME provider response. Real source revisions keep
the complete new column and must pass the unchanged historical-result gate; a
historical NAV is never copied or exempted from validation.
When a new split event arrives without its adjusted quote basis or any new
price, the complete verified column remains archived with no appended quote.
"""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from .integrated_data import load_integrated_market, compute_eligibility


def normalize_pending_split_basis(current, previous):
    """Complete a deferred split when quotes resume before history is rebased.

    Only a hash-bound previously deferred action can authorize this unit
    conversion. The entire observed pre-action OHLC/TR/volume history must
    corroborate the split inversion exactly; real revisions remain untouched.
    New quotes are retained, never inferred. The normal NAV gate still applies.
    """
    vintage = previous.metadata.get('priceVintage', {})
    candidates = vintage.get('deferredSplitAdjustments', []) + vintage.get('normalizedSplitBases', [])
    frames, records = {}, []
    for receipt in candidates:
        symbol = receipt['symbol']
        actions = receipt.get('reportedActions', [])
        if len(actions) != 1 or symbol not in current.prices:
            continue
        day = pd.Timestamp(actions[0]['date'])
        ratio = float(actions[0]['ratio'])
        if (not np.isfinite(ratio) or ratio <= 0 or ratio == 1
                or day not in current.splits.index
                or current.splits.at[day, symbol] != ratio
                or not current.prices.loc[current.prices.index >= day, symbol].notna().any()):
            continue
        later_actions = current.splits.loc[current.prices.index >= day, symbol].dropna()
        later_actions = later_actions[later_actions.gt(0) & later_actions.ne(1)]
        if len(later_actions) != 1 or later_actions.index[0] != day:
            continue
        overlap = previous.prices.index[previous.prices.index < day]
        observed = previous.prices.loc[overlap, symbol].notna()
        if (not observed.any() or not observed.equals(current.prices.loc[overlap, symbol].notna())
                or current.dividends.loc[current.prices.index >= day, symbol].fillna(0).ne(0).any()):
            continue
        dates = overlap[observed]
        def matches(name, scale=1.):
            old, new = getattr(previous, name), getattr(current, name)
            if old is None or new is None:
                return False
            a, b = old.loc[dates, symbol].to_numpy(float), new.loc[dates, symbol].to_numpy(float)
            return bool(np.isfinite(a).all() and np.isfinite(b).all()
                        and np.allclose(b * scale, a, rtol=1e-12, atol=0))
        scale = 1 / ratio
        prior_normalized = receipt in vintage.get('normalizedSplitBases', [])
        provider_scale = scale if prior_normalized else 1.
        if not (matches('prices') and matches('splits') and matches('dividends')
                and all(matches('raw_' + f, scale) and matches('provider_' + f, provider_scale)
                        for f in ('close', 'open', 'high', 'low'))
                and matches('volumes', ratio) and matches('provider_volumes', 1 / provider_scale)):
            continue
        # Conversion is restricted to sessions before the confirmed action.
        # Provider prices and volumes use paired inverse units; dollar volume
        # is invariant, as-traded history matches the accepted snapshot.
        for name, multiplier in [
            ('prices', scale), ('valuation_prices', scale),
            *[(prefix + f, scale) for prefix in ('raw_', 'provider_')
              for f in ('close', 'open', 'high', 'low')],
            ('volumes', ratio), ('provider_volumes', ratio),
        ]:
            original = getattr(current, name)
            if original is None:
                continue
            frame = frames.setdefault(name, original.copy(deep=False))
            values = original[symbol].astype(float).copy()
            values.loc[values.index < day] *= multiplier
            frame[symbol] = values
        records.append(dict(symbol=symbol, reportedActions=actions,
            acceptedSnapshotId=previous.metadata['snapshotId'],
            reason='resumed_quote_before_provider_history_rebase',
            providerHistoryScale=scale, comparedObservations=int(observed.sum()),
            policy='pre_action_units_only_new_quotes_unchanged'))
    if not records:
        return current, records
    result = replace(current, **frames)
    result.eligibility = compute_eligibility(result.prices, result.raw_close,
        result.volumes, result.metadata.get('requestedSymbols'))
    return result, records


def defer_unadjusted_split_history(current, previous, cutoff):
    """Retain verified history while a new split has no adjusted quote basis.

    Some responses add a split event before changing their historical OHLC.
    Inverting that event would then corrupt as-traded prices and liquidity.
    This narrow case has no new price, unchanged provider OHLC/TR history,
    and exactly the inverse price/volume distortion from the new split.
    Any genuine revision or new quote must still face the normal history gate.
    """
    from .integrated_data import FIELDS, PROVIDER_FIELDS, OPTIONAL_FIELDS

    overlap = previous.prices.index
    future = current.prices.index > cutoff
    deferred = []
    pending = {r['symbol']: r for r in previous.metadata.get('priceVintage', {}).get(
        'deferredSplitAdjustments', [])}
    for symbol in current.prices:
        actions = current.splits.loc[future, symbol].dropna()
        actions = actions[actions.gt(0) & actions.ne(1)]
        # A pending event can move inside the next day's overlap. Carry only
        # the exact previously recorded action, never a new historical edit.
        for action in pending.get(symbol, {}).get('reportedActions', []):
            day = pd.Timestamp(action['date'])
            if day not in current.splits.index:
                continue
            observed = current.splits.at[day, symbol]
            if np.isfinite(observed) and observed == action['ratio']:
                actions.loc[day] = observed
        actions = actions.sort_index()
        if (actions.empty or current.prices.loc[future, symbol].notna().any()
                or current.dividends.loc[future, symbol].fillna(0).ne(0).any()
                or not previous.prices[symbol].notna().equals(
                    current.prices.loc[overlap, symbol].notna())):
            continue
        ratio = float(actions.prod())
        if not np.isfinite(ratio) or ratio <= 0 or np.isclose(ratio, 1):
            continue
        observed = previous.prices[symbol].notna()
        if not observed.any():
            continue
        def matches(name, scale=1.):
            old, new = getattr(previous, name), getattr(current, name)
            if old is None or new is None:
                return False
            a = old.loc[observed, symbol].to_numpy(dtype=float)
            b = new.loc[overlap[observed], symbol].to_numpy(dtype=float)
            return bool(np.isfinite(a).all() and np.isfinite(b).all()
                        and np.allclose(b, a * scale, rtol=1e-12, atol=0))
        if not (matches('prices') and matches('dividends') and matches('splits')
                and all(matches('provider_' + f)
                and matches('raw_' + f, ratio) for f in ('close', 'open', 'high', 'low'))
                and matches('provider_volumes') and matches('volumes', 1 / ratio)):
            continue
        deferred.append(dict(symbol=symbol, reason='split_event_before_provider_price_adjustment',
            acceptedSnapshotId=previous.metadata['snapshotId'],
            observedThrough=str(overlap[observed][-1].date()),
            reportedActions=[dict(date=str(day.date()), ratio=float(value))
                             for day, value in actions.items()],
            currentQuoteStatus='unavailable',
            policy='entire_verified_column_preserved_no_new_quotes_or_forward_fill'))
    if not deferred:
        return current, deferred
    # Replace whole columns in shallow frame copies: shared source arrays remain
    # untouched and a full-universe matrix is not duplicated for one security.
    frames = {}
    for name in FIELDS + PROVIDER_FIELDS + OPTIONAL_FIELDS:
        old, new = getattr(previous, name), getattr(current, name)
        if new is None:
            continue
        if old is None:
            raise ValueError('Verified split-history field is missing: ' + name)
        frame = new.copy(deep=False)
        for record in deferred:
            symbol = record['symbol']
            values = old[symbol].reindex(frame.index)
            if pd.api.types.is_bool_dtype(old[symbol]):
                values = values.fillna(False).astype(bool)
            frame[symbol] = values
        frames[name] = frame
    return replace(current, **frames), deferred


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

    current, normalized_splits = normalize_pending_split_basis(current, previous)
    current, deferred_splits = defer_unadjusted_split_history(current, previous, cutoff)

    # Freeze only economically equivalent price inputs. Genuine source changes
    # retain their complete new column, so the existing NAV/null/choice gate
    # judges their effect. Never splice a changed source onto accepted prices.
    # Volume remains current and is validated by eligibility/liquidity/history;
    # a volume correction alone does not change the adjusted-price units.
    revised = {}
    def record(symbol, field, date, old, new):
        revised.setdefault(symbol, []).append(dict(
            field=field, firstChangedDate=str(date.date()),
            previous=float(old) if np.isfinite(old) else None,
            candidate=float(new) if np.isfinite(new) else None))
    for name in ('raw_close', 'dividends', 'splits'):
        old = getattr(previous, name).to_numpy(dtype=float)
        new = getattr(current, name).loc[overlap].to_numpy(dtype=float)
        equal = np.isclose(old, new, rtol=8*np.finfo(float).eps, atol=0, equal_nan=True)
        # A deferred action was explicitly recorded even though its no-quote
        # rows were archived. Admit only that same action and neutral missing
        # action rows after a fully corroborated split-basis normalization.
        if name in ('dividends', 'splits'):
            for receipt in normalized_splits:
                col = current.prices.columns.get_loc(receipt['symbol'])
                unquoted = previous.prices[receipt['symbol']].isna().to_numpy()
                permitted = np.isnan(old[:, col]) & (new[:, col] == 0)
                if name == 'splits':
                    for action in receipt['reportedActions']:
                        permitted |= ((overlap == pd.Timestamp(action['date']))
                                      & np.isnan(old[:, col]) & (new[:, col] == action['ratio']))
                equal[:, col] |= unquoted & permitted
        for col in np.flatnonzero(~equal.all(axis=0)):
            row = np.flatnonzero(~equal[:, col])[0]
            record(current.prices.columns[col], name, overlap[row], old[row,col], new[row,col])
    missing = previous.prices.notna() != current.prices.loc[overlap].notna()
    for symbol in missing.columns[missing.any()]:
        date = missing.index[missing[symbol]][0]
        record(symbol, 'price_observation_state', date,
               previous.prices.at[date,symbol],current.prices.at[date,symbol])

    prices = current.prices.copy()
    marks = current.valuation_prices.copy() if current.valuation_prices is not None else None
    bridges = []
    revisions = []
    for symbol in prices:
        if symbol in revised:
            continue
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
        deferredSplitAdjustments=deferred_splits,
        normalizedSplitBases=normalized_splits,
        sourceChecks=['raw_close', 'dividends', 'splits', 'calendar', 'null_state'],
        unfrozenSourceRevisions=[dict(symbol=symbol, changes=changes,
            policy='complete_current_column_subject_to_unchanged_history_gate')
            for symbol,changes in sorted(revised.items())])
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
