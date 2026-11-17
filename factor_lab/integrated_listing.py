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
