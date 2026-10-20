"""Dated source identities; the frozen investment-universe keys never change."""
from pathlib import Path
import hashlib
import json
import pandas as pd

RESOURCE = Path(__file__).parent / 'resources/integrated_listing_transitions.json'


def listing_context(symbols, asof):
    payload = RESOURCE.read_bytes()
    ledger = json.loads(payload)
    date = str(pd.Timestamp(asof).date())
    active = {}
    for row in ledger['transitions']:
        if row['symbol'] in symbols and row['effectiveDate'] <= date:
            if row.get('sameSecurity') is not True or not row.get('sources'):
                raise ValueError('Listing alias requires evidence of continuing security identity')
            if row['symbol'] not in active or row['effectiveDate'] > active[row['symbol']]['effectiveDate']:
                active[row['symbol']] = row
    providers = [active.get(s, {}).get('providerTicker', s) for s in symbols]
    if len(set(providers)) != len(providers):
        raise ValueError('Provider alias collides with a different canonical security')
    return dict(version=ledger['version'], sourceHash=hashlib.sha256(payload).hexdigest(),
                asOf=date, transitions=[active[s] for s in sorted(active)])


def provider_symbols(symbols, context):
    active = {r['symbol']: r['providerTicker'] for r in context['transitions']}
    return {s: active.get(s, s) for s in symbols}


def batch_cache_key(symbols, context):
    providers = provider_symbols(symbols, context)
    # Unaffected old batch downloads remain reusable. An alias cannot reuse an
    # old canonical-symbol response or an earlier alias-policy response.
    identity = symbols if all(s == p for s, p in providers.items()) else dict(
        symbols=symbols, providerSymbols=providers, listingSourceHash=context['sourceHash'])
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:16]


def normalize_provider_columns(data, symbols, context):
    providers = provider_symbols(symbols, context)
    if not isinstance(data.columns, pd.MultiIndex):
        if len(symbols) != 1:
            raise ValueError('Provider batch response has no symbol axis')
        data = data.copy()
        data.columns = pd.MultiIndex.from_product([data.columns, list(providers.values())])
    if data.columns.nlevels != 2:
        raise ValueError('Provider response has an unexpected column schema')
    reverse = {value: key for key, value in providers.items()}
    if any(symbol not in reverse for _, symbol in data.columns):
        raise ValueError('Provider response contains an unexpected security identity')
    out = data.copy()
    out.columns = pd.MultiIndex.from_tuples([(field, reverse[symbol]) for field, symbol in data.columns])
    if out.columns.duplicated().any():
        raise ValueError('Provider response contains duplicate canonical fields')
    out.index = pd.to_datetime(out.index).tz_localize(None).normalize()
    return out
