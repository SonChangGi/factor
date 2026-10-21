"""Preserve verified primary input vintages when a provider loses its history.

This is not a join of old and new quote bases. The entire affected column is
retained through its last observed old session; every later quote stays absent.
"""
from pathlib import Path
import hashlib
import json
import os
import pandas as pd


def load_archived_columns(directory, symbols):
    from .integrated_data import IntegratedMarket, FIELDS, PROVIDER_FIELDS, OPTIONAL_FIELDS
    root = Path(directory)
    manifest_file = root / 'manifest.json'
    if manifest_file.is_symlink():
        raise ValueError('Archived input manifest cannot be a symbolic link')
    original = manifest_file.read_bytes()
    metadata = json.loads(original)
    unsigned = dict(metadata)
    identity = unsigned.pop('snapshotId')
    if hashlib.sha256(json.dumps(unsigned, sort_keys=True).encode()).hexdigest() != identity:
        raise ValueError('Archived input manifest hash mismatch')
    if metadata.get('amendments') or metadata.get('corporateActions'):
        raise ValueError('Archive recovery requires primary raw inputs, not amended results')
    names = list(FIELDS) + [name for name in PROVIDER_FIELDS + OPTIONAL_FIELDS
                           if name + '.csv.gz' in metadata['files']]
    frames = {}
    for name in names:
        path = root / (name + '.csv.gz')
        if path.is_symlink():
            raise ValueError('Archived input matrix cannot be a symbolic link')
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024*1024), b''):
                digest.update(chunk)
        if digest.hexdigest() != metadata['files'][path.name]:
            raise ValueError('Archived input matrix hash mismatch: ' + name)
        header = pd.read_csv(path, nrows=0).columns[0]
        frame = pd.read_csv(path, index_col=0, parse_dates=True, float_precision="round_trip",
                            usecols=lambda column: column == header or column in symbols)
        if set(frame.columns) != set(symbols):
            raise ValueError('Archived input is missing requested canonical symbols')
        frames[name] = frame.reindex(columns=sorted(symbols))
    index = frames['prices'].index
    if any(not frame.index.equals(index) for frame in frames.values()):
        raise ValueError('Archived input field calendars differ')
    metadata['archiveManifestSha256'] = hashlib.sha256(original).hexdigest()
    metadata['archivePath'] = str(root)
    return IntegratedMarket(**frames, metadata=metadata)


def preserve_archived_columns(market, archive, symbols, reference):
    from .integrated_data import FIELDS, PROVIDER_FIELDS, OPTIONAL_FIELDS, history_coverage_issue
    if market.metadata['universeVersion'] != archive.metadata['universeVersion']:
        raise ValueError('Archived input universe identity differs')
    source_end = pd.Timestamp(archive.metadata['dataAsOf'])
    if source_end > market.prices.index[-1]:
        raise ValueError('Archived input comes from a future session')
    records = []
    earlier_records = {row['symbol']: row for row in archive.metadata.get('archivedHistory', [])}
    for symbol in sorted(symbols):
        paired = pd.DataFrame({('Adj Close', symbol): archive.prices[symbol],
                               ('Volume', symbol): archive.volumes[symbol]})
        if history_coverage_issue(paired, symbol, reference):
            raise ValueError('Archived input cannot meet historical reference: ' + symbol)
        valid = archive.prices[symbol].notna() & archive.prices[symbol].gt(0) & archive.volumes[symbol].gt(0)
        if not valid.any():
            raise ValueError('Archived symbol has no verified primary observations')
        observed_through = archive.prices.index[valid][-1]
        if observed_through > source_end:
            raise ValueError('Archived observation is after its frozen as-of date')
        cutoff = market.prices.index <= observed_through
        for name in FIELDS + PROVIDER_FIELDS + OPTIONAL_FIELDS:
            target, source = getattr(market, name), getattr(archive, name)
            if target is None:
                continue
            # Never use the failed current response for any cell of this
            # symbol. All fields share the original complete source vintage.
            target.loc[:, symbol] = False if name in ('eligibility', 'shape_valid') else float('nan')
            if source is not None:
                target.loc[cutoff, symbol] = source[symbol].reindex(target.index[cutoff])
            elif name == 'valuation_prices':
                target.loc[cutoff, symbol] = archive.prices[symbol].reindex(target.index[cutoff])
            elif name.startswith('provider_'):
                raise ValueError('Archived provider basis is missing: ' + name)
        collected = earlier_records.get(symbol, {}).get('collectedAt')
        if not collected:
            for receipt in archive.metadata.get('receipts', []):
                if symbol in receipt.get('symbols', []):
                    collected = receipt.get('retrievedAt')
        record = dict(symbol=symbol, state='archived_history_only',
            sourceSnapshotId=archive.metadata['snapshotId'],
            sourceCacheKey=os.environ.get('FACTOR_ARCHIVED_INPUT_CACHE_KEY'),
            sourceManifestSha256=archive.metadata['archiveManifestSha256'],
            sourceFieldHashes=archive.metadata['files'], sourcePath=archive.metadata['archivePath'],
            sourceAsOf=archive.metadata['dataAsOf'], observedThrough=str(observed_through.date()),
            collectedAt=collected, currentQuoteStatus='unavailable',
            policy='entire_primary_column_preserved_later_quotes_absent_no_forward_fill',
            sourceLineage=archive.metadata.get('archiveSeed') or earlier_records.get(symbol, {}).get('sourceLineage'))
        records.append(record)
        market.metadata.setdefault('receipts', []).append(dict(symbols=[symbol],
            retrievedAt=collected, sha256=archive.metadata['archiveManifestSha256'],
            role='preserved_archived_primary_history'))
    market.metadata['archivedHistory'] = records
    return market
