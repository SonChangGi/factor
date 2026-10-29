"""One-core, fail-closed weekday refresh of the integrated Factor publication.

A run creates immutable inputs/results and a separate candidate. Only the
explicit promote command may replace a baseline, after a compare-and-swap check.
"""
from __future__ import annotations
import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import uuid

for _name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
              'VECLIB_MAXIMUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[_name] = '1'

POLICY = Path(__file__).parent / 'resources' / 'integrated_market_policy.json'


def tree_hash(root):
    root = Path(root)
    records = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('Publication cannot contain symbolic links')
        if path.is_file():
            records[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()


def freshness(site, event_name='schedule', now=None):
    from .dashboard_freshness import expected_recent_us_close_date
    now = now or datetime.now(timezone.utc)
    target = expected_recent_us_close_date(now)
    try:
        payload = json.loads((Path(site) / 'data/integrated-result.json').read_text())
        latest = payload['data']['asOf']
        if not isinstance(latest, str) or date.fromisoformat(latest).isoformat() != latest:
            raise ValueError('Invalid observation date')
        if payload['schemaVersion'] != 'integrated-factor/v1':
            raise ValueError('Not an integrated result')
    except (OSError, KeyError, ValueError):
        latest = None
    # The input date, rather than a legacy execution timestamp, is authoritative.
    # A failed attempt does not mark the old payload as fresh.
    if latest is not None and latest > target.isoformat():
        raise ValueError('Published input date is after the completed market session')
    skip = event_name == 'schedule' and latest == target.isoformat()
    return dict(skip=skip, target_data_as_of=target.isoformat(), latest_data_as_of=latest,
                reason='target_close_already_published' if skip else 'integrated_refresh_required')


def reconcile_policy(market, policy):
    """Bind reviewed evidence to new input; conflicting adjustments fail closed."""
    import copy
    import numpy as np
    import pandas as pd
    from .integrated_repairs import amend_market
    amended = copy.deepcopy(policy)
    amended['inputSnapshotId'] = market.metadata['snapshotId']
    ledger = []
    observed = market.prices.index
    reviewed = pd.Timestamp(policy['reviewedThrough'])
    # Fixed historical OHLC/TR patches cannot be reused after a new split or
    # dividend changes their provider units. Require a reviewed updated policy.
    patched = {r['symbol'] for name in ('quotes', 'valuationMarks') for r in policy.get(name, [])}
    for symbol in patched:
        later = observed > reviewed
        if (market.splits.loc[later, symbol].fillna(0).ne(0).any() or
                market.dividends.loc[later, symbol].fillna(0).ne(0).any()):
            raise ValueError(f'Reviewed patch adjustment basis changed: {symbol}')
    retained = []
    for row in policy.get('splitCorrections', []):
        date, symbol, ratio = pd.Timestamp(row['date']), row['symbol'], row['ratio']
        if date not in observed:
            if date > observed[-1]:
                continue
            raise ValueError('Reviewed split session absent from primary calendar')
        recorded = market.splits.at[date, symbol]
        if pd.notna(recorded) and recorded != 0:
            if not np.isclose(recorded, ratio, rtol=1e-7, atol=1e-12):
                raise ValueError(f'Conflicting provider split: {symbol}')
            ledger.append(dict(symbol=symbol, date=row['date'], decision='provider_already_records_split'))
        else:
            retained.append(row)
    amended['splitCorrections'] = retained
    # amend_market checks every existing quote against its evidence before
    # admitting missing observations. A provider-resolved mark stays tradable.
    amended['valuationMarks'] = []
    for row in policy.get('valuationMarks', []):
        date, symbol = pd.Timestamp(row['date']), row['symbol']
        if date not in observed:
            if date > observed[-1]:
                continue
            raise ValueError('Reviewed valuation session absent from primary calendar')
        value = market.prices.at[date, symbol]
        if pd.notna(value):
            if not np.isclose(value, row['adjustedClose'], atol=.011):
                raise ValueError(f'Conflicting recovered valuation: {symbol}')
            ledger.append(dict(symbol=symbol, date=row['date'], decision='provider_recovered_tradable_quote'))
        else:
            amended['valuationMarks'].append(row)
    for name in ('quotes', 'identityStarts', 'exchanges'):
        amended[name] = [r for r in amended.get(name, []) if pd.Timestamp(r['date']) <= observed[-1]]
    result = amend_market(market, amended)
    result.metadata['automationPolicy'] = {
        'version': policy['policyVersion'], 'reviewedThrough': policy['reviewedThrough'],
        'sha256': hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest(),
        'reconciliation': ledger, 'rawSnapshotId': market.metadata['snapshotId']}
    return result


class RefreshInputError(ValueError):
    def __init__(self, code, message, symbols=()):
        super().__init__(message)
        self.code, self.symbols = code, sorted(set(symbols))


def required_valuation_symbols(baseline_payload, target, actions=()):
    """Continue every held security through only newly effective legal actions."""
    previous = baseline_payload.get('data', {}).get('asOf', '')
    held = {r['symbol'] for book in [baseline_payload.get('selection', {}), *baseline_payload.get('factors', [])]
            for r in book.get('holdings', []) if r.get('weight', 0) > 0}
    for action in sorted(actions, key=lambda r: r['date']):
        if previous < action['date'] <= target and action['symbol'] in held:
            destination = action.get('targetSymbol')
            if destination is None:
                amount = action.get('cashPerUnit', action.get('cashPerShare', 0))
                if not isinstance(amount, (int, float)) or amount <= 0:
                    raise ValueError('A held cash conversion has no positive legal consideration')
            held.remove(action['symbol'])
            if destination is not None:
                held.add(destination)
    return held


def validate_required_valuations(market, baseline_payload, target):
    """Fail before a full backtest if any continued holding cannot be valued."""
    import pandas as pd
    required = required_valuation_symbols(baseline_payload, target, market.metadata.get('corporateActions', []))
    prices = market.valuation_prices if getattr(market, 'valuation_prices', None) is not None else market.prices
    day = pd.Timestamp(target)
    missing = [s for s in required if s not in prices or day not in prices.index or
               pd.isna(prices.at[day, s]) or prices.at[day, s] <= 0]
    if missing:
        raise RefreshInputError('held_quote_missing', 'Required holding valuation unavailable: ' + ', '.join(sorted(missing)), missing)
    return dict(targetDataAsOf=target, requiredHeldSymbols=len(required), valuedHeldSymbols=len(required))


def provider_ready(baseline, output, *, now=None, attempts=3, delay_seconds=30, sleep=None, download=None, benchmarks_only=False):
    """Small, bounded admission probe; its quotes never enter financial inputs."""
    import time
    import pandas as pd
    import yfinance as yf
    from .integrated_listing import listing_context, provider_symbols, normalize_provider_columns
    from .integrated_service import atomic_json
    if not 1 <= attempts <= 3 or not 0 <= delay_seconds <= 30:
        raise ValueError('Provider admission is limited to three probes and 60 seconds waiting')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    baseline_payload = json.loads((Path(baseline) / 'data/integrated-result.json').read_text())
    target = freshness(baseline, 'manual', now)['target_data_as_of']
    policy = json.loads(POLICY.read_text())
    required = set() if benchmarks_only else required_valuation_symbols(baseline_payload, target, policy.get('exchanges', []))
    evidence = {r['symbol'] for kind in ('quotes', 'valuationMarks') for r in policy.get(kind, [])
                if r['date'] == target and r.get('adjustedClose', 0) > 0}
    remaining = set(('SPY', 'QQQ', '^IXIC')) | (required - evidence)
    context = listing_context(sorted(remaining), target)
    download = download or yf.download
    sleep = sleep or time.sleep
    receipts = []
    for attempt in range(1, attempts + 1):
        for offset in range(0, len(remaining), 25):
            # Freeze this attempt's ordering, even when later batches succeed.
            symbols = sorted(remaining)[offset:offset + 25]
            if not symbols:
                continue
            source_symbols = list(provider_symbols(symbols, context).values())
            try:
                raw = download(source_symbols, start=(pd.Timestamp(target) - pd.Timedelta(days=7)).date().isoformat(),
                    end=(pd.Timestamp(target) + pd.Timedelta(days=1)).date().isoformat(),
                    auto_adjust=False, actions=False, repair=False, keepna=True, progress=False,
                    threads=False, timeout=15, group_by='column')
                path = output / f'probe-{attempt}-{offset}.csv.gz'
                raw.to_csv(path, compression={'method': 'gzip', 'mtime': 0})
                data = normalize_provider_columns(raw, symbols, context)
                found = [symbol for symbol in symbols if ('Adj Close', symbol) in data and
                         pd.Timestamp(target) in data.index and pd.notna(data.at[pd.Timestamp(target), ('Adj Close', symbol)]) and
                         data.at[pd.Timestamp(target), ('Adj Close', symbol)] > 0 and
                         ('Volume', symbol) in data and pd.notna(data.at[pd.Timestamp(target), ('Volume', symbol)]) and
                         data.at[pd.Timestamp(target), ('Volume', symbol)] > 0]
                receipts.append(dict(attempt=attempt, symbols=symbols, observed=found,
                    path=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    retrievedAtUtc=datetime.now(timezone.utc).isoformat()))
            except Exception as exc:
                receipts.append(dict(attempt=attempt, symbols=symbols, errorType=type(exc).__name__))
        found = {s for receipt in receipts if receipt['attempt'] == attempt for s in receipt.get('observed', [])}
        remaining -= found
        status = dict(schemaVersion='factor-provider-readiness/v1', status='ready' if not remaining else 'waiting',
            targetDataAsOf=target, missingSymbols=sorted(remaining), attempts=attempt,
            policyHash=hashlib.sha256(POLICY.read_bytes()).hexdigest(), listing=context, receipts=receipts)
        atomic_json(output / 'status.json', status)
        if not remaining:
            return status
        if attempt < attempts:
            sleep(delay_seconds)
    raise RefreshInputError('provider_not_ready', 'Provider target-session quotes unavailable: ' + ', '.join(sorted(remaining)), remaining)


def validate_market_refresh(market, baseline_payload, target):
    """A fresh benchmark alone cannot admit a broadly stale equity refresh."""
    import pandas as pd
    day = pd.Timestamp(target)
    if market.metadata['dataAsOf'] != target or market.prices.index[-1] != day:
        raise ValueError('Input calendar does not reach the target completed session')
    for symbol in ('SPY', 'QQQ', '^IXIC'):
        if symbol not in market.prices or pd.isna(market.prices.at[day, symbol]):
            raise RefreshInputError('benchmark_quote_missing', f'Missing target-session benchmark: {symbol}', [symbol])
    previous = {r['symbol'] for r in baseline_payload.get('data', {}).get('symbols', [])
                if r.get('status') == 'eligible'}
    inactive = {r['symbol'] for r in market.metadata.get('corporateActions', [])
                if pd.Timestamp(r['date']) <= day}
    inactive |= {r['symbol'] for r in market.metadata.get('amendments', [])
                 if r['kind'] == 'unverified_input_quarantine'}
    comparison = previous - inactive
    if comparison:
        fresh = sum(symbol in market.prices and pd.notna(market.prices.at[day, symbol])
                    and market.prices.at[day, symbol] > 0 for symbol in comparison)
        if fresh / len(comparison) < .95:
            raise ValueError('Fewer than 95% of previously eligible equities have target-session quotes')
    return dict(targetDataAsOf=target, previousEligibleCompared=len(comparison),
                targetSessionObserved=(int(fresh) if comparison else 0), minimumCoverage=.95)


def history_revision(baseline, candidate, tolerance=.001):
    """Compare existing observations, retaining null gaps and prior choices."""
    keys = ('start_date','end_date','evaluation_window_days','top_n','max_weight',
            'transaction_cost_bps','slippage_bps','execution_delay_sessions','weighting',
            'common_universe','comparison_factors')
    if any(baseline['settings'].get(k) != candidate['settings'].get(k) for k in keys):
        raise ValueError('Financial settings changed; daily historical comparison requires review')
    if baseline['registry'] != candidate['registry']:
        raise ValueError('Definition catalog changed; historical comparison requires review')
    report = dict(status='passed', maximumRelativeNavRevision=0., threshold=tolerance,
                  comparedObservations=0, maximumDifference=None, issues=[])
    old_books = {'MONTHLY_SELECTION': baseline['selection'], **{f['id']: f for f in baseline['factors']}}
    new_books = {'MONTHLY_SELECTION': candidate['selection'], **{f['id']: f for f in candidate['factors']}}
    for key, book in old_books.items():
        new = {p['date']: p['value'] for p in new_books.get(key, {}).get('nav', [])}
        for point in book.get('nav', []):
            day, old = point['date'], point['value']
            report['comparedObservations'] += 1
            if day not in new or (old is None) != (new[day] is None):
                report['issues'].append(dict(curveId=key, date=day, reason='observation_or_null_changed'))
                continue
            if old is None:
                continue
            difference = abs(new[day] / old - 1)
            if difference > report['maximumRelativeNavRevision']:
                report.update(maximumRelativeNavRevision=difference,
                              maximumDifference=dict(curveId=key,date=day,previous=old,candidate=new[day]))
            if difference > tolerance:
                report['issues'].append(dict(curveId=key,date=day,reason='nav_revision_exceeds_threshold',relativeDifference=difference))
    old_choices = {h['signalDate']: (h['status'], h.get('factorId')) for h in baseline['selection']['history']}
    new_choices = {h['signalDate']: (h['status'], h.get('factorId')) for h in candidate['selection']['history']}
    for day, choice in old_choices.items():
        if new_choices.get(day) != choice:
            report['issues'].append(dict(curveId='MONTHLY_SELECTION',date=day,reason='historical_choice_changed'))
    if report['issues']:
        report['status'] = 'review_required'
    return report


def confirm_input_cache(workspace, key, cache_id):
    from .integrated_service import atomic_json
    path = Path(workspace) / 'status.json'
    status = json.loads(path.read_text())
    if status.get('state') != 'validated' or status.get('inputCacheKey') != key or not str(cache_id).isdigit():
        raise ValueError('Input cache receipt does not match the validated run')
    status['inputCacheVerified'] = dict(key=key, cacheId=str(cache_id),
                                      verifiedAtUtc=datetime.now(timezone.utc).isoformat())
    atomic_json(path, status)
    return status['inputCacheVerified']


def current_source():
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()


def coverage_contract_from_result(payload):
    """First migration uses the same positive-volume price basis as collection."""
    if payload['data'].get('inputCoverage'):
        return payload['data']['inputCoverage']
    patches = {}
    for row in payload['data'].get('amendments', []):
        if row['kind'] == 'observed_quote':
            patches[row['symbol']] = patches.get(row['symbol'], 0) + 1
    return {row['symbol']: dict(observations=max(0, row['observations']-patches.get(row['symbol'], 0)),
                               firstObservation=row['firstObservation'], asOf=payload['data']['asOf'],
                               basis='positive_adjusted_close_and_positive_provider_volume')
            for row in payload['data']['symbols']}


def seed_download_cache(reuse_root, destination, target):
    """Copy only verified provider responses; never splice old price matrices."""
    source, destination = Path(reuse_root) / 'raw', Path(destination)
    manifest_path = source / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    identity = manifest.pop('snapshotId')
    if hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest() != identity:
        raise ValueError('Reused input manifest is corrupt')
    manifest['snapshotId'] = identity
    expected_end = (datetime.fromisoformat(target).date()+timedelta(days=1)).isoformat()
    request = json.loads((source / 'request.json').read_text())
    if request['endExclusive'] != expected_end or manifest['dataAsOf'] != target:
        raise ValueError('Reused input cache belongs to a different completed session')
    destination.mkdir(parents=True, exist_ok=False)
    # Preserve the old request separately. Batch alias keys prevent reusing its
    # obsolete provider-symbol response; unchanged symbols keep their caches.
    shutil.copyfile(source / 'request.json', destination / 'reuse-source-request.json')
    from .integrated_listing import listing_context
    from .integrated_data import BENCHMARKS
    request['listing'] = listing_context(sorted(set(request['symbols']) | set(BENCHMARKS)), target)
    (destination / 'request.json').write_text(json.dumps(request, indent=2) + '\n')
    downloads = source / 'downloads'
    for path in downloads.rglob('*'):
        if path.is_symlink():
            raise ValueError('Reused input cache contains symbolic links')
    shutil.copytree(downloads, destination / 'downloads')
    return dict(sourcePath=str(source), sourceSnapshotId=identity,
                sourceManifestSha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                sourceCacheKey=os.environ.get('FACTOR_REUSED_INPUT_CACHE_KEY'))


def export_input_diagnostics(reuse_root, output, *, symbols=None, start='2015-01-01', end='2016-12-15'):
    """Read a restored cache; never collect, calculate a factor or publish."""
    import pandas as pd
    root, output = Path(reuse_root), Path(output)
    if output.exists():
        raise FileExistsError('Choose a new diagnostics output directory')
    symbols = symbols or ['CECO','IBOC','UUU','TYL','BOH','GPN','AAP','FISV','PSA','DEA']
    if not 1 <= len(symbols) <= 30 or len(set(symbols)) != len(symbols) or any(
        re.fullmatch(r'[A-Z0-9.^-]{1,16}', value) is None for value in symbols
    ):
        raise ValueError('Diagnostics require 1..30 distinct canonical symbols')
    if (str(pd.Timestamp(start).date()) != start or str(pd.Timestamp(end).date()) != end
            or not pd.Timestamp(start) <= pd.Timestamp(end)):
        raise ValueError('Diagnostics require an ordered ISO date interval')
    output.mkdir(parents=True)
    receipt = dict(schemaVersion='factor-input-diagnostics/v1', sourcePath=str(root),
                   sourceCacheKey=os.environ.get('FACTOR_REUSED_INPUT_CACHE_KEY'),
                   cacheId=os.environ.get('FACTOR_REUSED_INPUT_CACHE_ID'),
                   sourceCommit=current_source(), inputSourceCommit=os.environ.get('FACTOR_REUSED_INPUT_SOURCE_SHA'), symbols=symbols,
                   start=start, end=end, files={})
    for stage in ('raw', 'market'):
        folder = root / stage
        manifest_file = folder / 'manifest.json'
        if stage == 'market' and not manifest_file.exists():
            receipt[stage] = dict(state='not_created')
            continue
        manifest = json.loads(manifest_file.read_text())
        receipt[stage] = dict(snapshotId=manifest['snapshotId'],
            manifestSha256=hashlib.sha256(manifest_file.read_bytes()).hexdigest())
        target = output / stage
        target.mkdir()
        shutil.copyfile(manifest_file, target / 'manifest.json')
        for relative, digest in manifest['files'].items():
            if relative not in {f'{f}.csv.gz' for f in ('prices','raw_close','provider_close','raw_open','raw_high','raw_low','volumes','provider_volumes','splits','dividends','eligibility')}:
                continue
            path = folder / relative
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError('Restored input matrix hash mismatch: ' + relative)
            date_column = pd.read_csv(path, nrows=0).columns[0]
            frame = pd.read_csv(path, index_col=0, parse_dates=True,
                                usecols=lambda col: col in symbols or col == date_column)
            frame = frame.loc[receipt['start']:receipt['end']]
            export = target / relative.replace('.gz', '')
            frame.to_csv(export)
            receipt['files'][export.relative_to(output).as_posix()] = hashlib.sha256(export.read_bytes()).hexdigest()
    from .integrated_service import atomic_json
    atomic_json(output / 'receipt.json', receipt)
    return receipt


def run(workspace, baseline, candidate, source_commit, *, now=None, reuse_input_root=None, archived_input_root=None):
    from .integrated_data import collect_integrated_market, save_integrated_market
    from .integrated_service import atomic_json, execute_run, build_site, code_fingerprint
    from .integrated_validation import validate_automated_result, write_automated_manifest
    workspace, baseline, candidate = map(Path, (workspace, baseline, candidate))
    if workspace.exists() or candidate.exists():
        raise FileExistsError('Choose a new immutable run workspace and candidate')
    if current_source() != source_commit:
        raise ValueError('Calculation checkout differs from requested source')
    workspace.mkdir(parents=True)
    before, fingerprint = tree_hash(baseline), code_fingerprint()[0]
    decision = freshness(baseline, 'manual', now)
    target = decision['target_data_as_of']
    status = dict(schemaVersion='factor-automation/v1', state='running',
                  attemptedAtUtc=datetime.now(timezone.utc).isoformat(), targetDataAsOf=target,
                  sourceCommit=source_commit, baselineHash=before,
                  inputCacheKey=os.environ.get('FACTOR_INPUT_CACHE_KEY'))
    atomic_json(workspace / 'status.json', status)
    staging = candidate.with_name(candidate.name + '.tmp-' + uuid.uuid4().hex)
    try:
        end = (datetime.fromisoformat(target).date() + timedelta(days=1)).isoformat()
        if reuse_input_root:
            status['reusedInputCache'] = seed_download_cache(reuse_input_root, workspace / 'raw', target)
            atomic_json(workspace / 'status.json', status)
        baseline_payload = json.loads((baseline / 'data/integrated-result.json').read_text())
        reference = coverage_contract_from_result(baseline_payload)
        policy = json.loads(POLICY.read_text())
        required_targets = required_valuation_symbols(baseline_payload, target, policy.get('exchanges', [])) | {'SPY', 'QQQ', '^IXIC'}
        raw = collect_integrated_market(workspace / 'raw', '2010-01-01', end, reference_coverage=reference, archived_input_root=archived_input_root, target_session=target, required_target_symbols=required_targets)
        if raw.metadata['dataAsOf'] != target:
            raise ValueError('Provider has not supplied the completed target session')
        from .integrated_vintage import load_accepted_vintage, extend_price_vintage
        if archived_input_root is None:
            raise ValueError('Daily calculation requires the baseline input vintage')
        previous = load_accepted_vintage(archived_input_root, baseline_payload)
        vintage = extend_price_vintage(raw, previous)
        # Nested in raw so the existing cache path/version continues to restore
        # both legacy raw caches and new caches containing a calculation vintage.
        vintage = save_integrated_market(vintage, workspace / 'raw' / 'price-vintage')
        atomic_json(workspace / 'price-vintage.json', vintage.metadata['priceVintage'])
        market = reconcile_policy(vintage, policy)
        if status['inputCacheKey']:
            market.metadata['inputCache'] = dict(key=status['inputCacheKey'],
                storage='GitHub Actions cache', retention='bounded_10GB_eviction_7_days_unused',
                rawSnapshotId=raw.metadata['snapshotId'],
                priceVintageSnapshotId=vintage.metadata['snapshotId'])
        # Do not retain two extra full-universe snapshots during the backtest.
        del previous, raw, vintage
        market_check = validate_market_refresh(market, baseline_payload, target)
        market_check['holdingValuations'] = validate_required_valuations(market, baseline_payload, target)
        market = save_integrated_market(market, workspace / 'market', compression_level=1)
        result = execute_run(market, dict(run_stress=True, bootstrap_repetitions=2000), workspace / 'analysis')
        validation = validate_automated_result(result, target_as_of=target)
        validation['automationPolicy'] = market.metadata['automationPolicy']
        validation['marketRefresh'] = market_check
        revision = history_revision(json.loads((baseline / 'data/integrated-result.json').read_text()),
                                    result, policy['maxHistoricalNavRevision'])
        atomic_json(workspace / 'history-revision.json', revision)
        if revision['status'] != 'passed':
            raise ValueError('Historical NAV or choices changed; see history-revision.json')
        validation['historyRevision'] = revision
        if (tree_hash(baseline) != before or current_source() != source_commit or
                code_fingerprint()[0] != fingerprint):
            raise RuntimeError('Source or last-good publication changed during calculation')
        build_site(staging, result)
        # Historical audit reports and additive history sidecars belong to the
        # old run. Embedded current histories are authoritative; do not copy
        # old diagnostics into a new run's page.
        write_automated_manifest(staging, result, source_commit, validation)
        from .publication_security import scan_publication_paths
        findings = scan_publication_paths([staging])
        if findings:
            raise ValueError('Candidate publication failed secret scan')
        os.replace(staging, candidate)
        status.update(state='validated', finishedAtUtc=datetime.now(timezone.utc).isoformat(), resultId=result['resultIdentity']['resultId'],
                      dataAsOf=result['data']['asOf'], candidateHash=tree_hash(candidate),
                      candidate=str(candidate.resolve()), validation=validation)
        atomic_json(workspace / 'status.json', status)
        return status
    except Exception as exc:
        status.update(state='failed', finishedAtUtc=datetime.now(timezone.utc).isoformat(), errorType=type(exc).__name__, reason=str(exc),
                      reasonCode=getattr(exc, 'code', 'refresh_failed'), missingSymbols=getattr(exc, 'symbols', []),
                      lastGoodPreserved=tree_hash(baseline) == before)
        atomic_json(workspace / 'status.json', status)
        if staging.exists():
            shutil.rmtree(staging)
        raise


def promote(workspace, baseline, candidate):
    """Guarded local promotion. Git/Pages publication remains workflow-owned."""
    from .integrated_service import atomic_json
    workspace, baseline, candidate = map(Path, (workspace, baseline, candidate))
    status = json.loads((workspace / 'status.json').read_text())
    if status.get('state') != 'validated' or current_source() != status['sourceCommit']:
        raise ValueError('Only a same-source validated candidate can be promoted')
    if status.get('inputCacheKey') and status.get('inputCacheVerified', {}).get('key') != status['inputCacheKey']:
        raise ValueError('Validated raw inputs were not confirmed in bounded cache')
    if tree_hash(candidate) != status['candidateHash'] or tree_hash(baseline) != status['baselineHash']:
        raise ValueError('Candidate or baseline changed before promotion')
    backup = baseline.with_name(baseline.name + '.last-good-' + uuid.uuid4().hex)
    os.replace(baseline, backup)
    try:
        os.replace(candidate, baseline)
    except BaseException:
        os.replace(backup, baseline)
        raise
    # Preserve recovery data inside the immutable run, outside publication.
    shutil.move(str(backup), str(workspace / 'last-good-site'))
    status.update(state='promoted', promotedAtUtc=datetime.now(timezone.utc).isoformat())
    atomic_json(workspace / 'status.json', status)
    return status


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    fresh = sub.add_parser('freshness')
    fresh.add_argument('--site', type=Path, required=True)
    fresh.add_argument('--event-name', default='schedule')
    receipt = sub.add_parser('confirm-input-cache')
    receipt.add_argument('--workspace', type=Path, required=True)
    receipt.add_argument('--cache-key', required=True)
    receipt.add_argument('--cache-id', required=True)
    diagnostics = sub.add_parser('export-input-diagnostics')
    diagnostics.add_argument('--reuse-input-root', type=Path, required=True)
    diagnostics.add_argument('--output', type=Path, required=True)
    diagnostics.add_argument('--symbols', default='')
    diagnostics.add_argument('--start', default='2015-01-01')
    diagnostics.add_argument('--end', default='2016-12-15')
    ready = sub.add_parser('provider-ready')
    ready.add_argument('--baseline', type=Path, required=True)
    ready.add_argument('--output', type=Path, required=True)
    ready.add_argument('--benchmarks-only', action='store_true')
    for name in ('run', 'promote'):
        command = sub.add_parser(name)
        command.add_argument('--workspace', type=Path, required=True)
        command.add_argument('--baseline', type=Path, required=True)
        command.add_argument('--candidate', type=Path, required=True)
        if name == 'run':
            command.add_argument('--source-commit', required=True)
            command.add_argument('--reuse-input-root', type=Path)
            command.add_argument('--archived-input-root', type=Path)
    args = parser.parse_args(argv)
    if args.command == 'freshness':
        for key, value in freshness(args.site, args.event_name).items():
            print(f'{key}={str(value).lower() if isinstance(value, bool) else value or "none"}')
    elif args.command == 'confirm-input-cache':
        print(json.dumps(confirm_input_cache(args.workspace, args.cache_key, args.cache_id)))
    elif args.command == 'export-input-diagnostics':
        print(json.dumps(export_input_diagnostics(args.reuse_input_root, args.output,
            symbols=args.symbols.split(',') if args.symbols else None, start=args.start, end=args.end)))
    elif args.command == 'provider-ready':
        print(json.dumps(provider_ready(args.baseline, args.output, benchmarks_only=args.benchmarks_only)))
    elif args.command == 'run':
        print(json.dumps(run(args.workspace, args.baseline, args.candidate, args.source_commit, reuse_input_root=args.reuse_input_root, archived_input_root=args.archived_input_root)))
    else:
        print(json.dumps(promote(args.workspace, args.baseline, args.candidate)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
