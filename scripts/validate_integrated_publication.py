"""Validate the immutable integrated Pages release and its calculation provenance."""
import bisect
from datetime import date
import math
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def validate_daily_publication(site, manifest, result):
    from factor_lab.integrated_validation import validate_automated_result, validate_runtime_lock
    validation = validate_automated_result(result, manifest['dataAsOf'])
    assert manifest['status'] == 'passed' and manifest['publicationType'] in {'automated_daily', 'reviewed_definition_migration'}
    if manifest['publicationType'] == 'reviewed_definition_migration':
        contract = manifest['validation']['definitionReview']
        assert contract['path'] == 'data/definition-review.json'
        review_bytes = (site / contract['path']).read_bytes()
        assert hashlib.sha256(review_bytes).hexdigest() == contract['sha256']
        review = json.loads(review_bytes)
        assert review['schemaVersion'] == 'factor-definition-review/v1' and review['status'] == 'passed'
        assert review['resultIdentity'] == result['resultIdentity']
        assert review['sourceCommit'] == manifest['calculationSourceCommit']
        assert review['candidateResultId'] == contract['candidateResultId'] == result['resultIdentity']['resultId']
        assert review['candidateInputHash'] == result['resultIdentity']['inputHash']
        assert review['baselineResultId'] == contract['baselineResultId']
        assert review['reviewedDefinitionIds'] == contract['reviewedDefinitionIds'] == ['CONSISTENCY12_1']
        assert review['definitionBefore']['id'] == 'CONSISTENCY12_1' and review['definitionBefore']['version'] == '1.0.0'
        assert review['definitionAfter'] == next(r for r in result['registry'] if r['id'] == 'CONSISTENCY12_1')
        assert review['unchangedDefinitions'] == dict(status='passed', maximumPermittedRelativeNavRevision=.001, nullMasksPreserved=True)
    assert manifest['scheduledIntegratedRefresh'] == 'active'
    assert manifest['resultIdentity'] == result['resultIdentity']
    assert all(manifest['validation'].get(k) == v for k, v in validation.items())
    assert manifest['requestedCount'] == result['data']['requestedCount']
    package = manifest['calculationPackage']
    assert package in {'factor_lab', 'momentum_factor_lab'}
    source = manifest['calculationSourceCommit']
    assert len(source) == 40 and all(c in '0123456789abcdef' for c in source)
    lock = subprocess.check_output(['git', 'show', f'{source}:uv.lock'], cwd=ROOT)
    validate_runtime_lock(result['resultIdentity'], lock)
    for name, digest in result['resultIdentity']['codeHashFiles'].items():
        assert not name.startswith('/') and '..' not in Path(name).parts
        body = subprocess.check_output(['git', 'show', f'{source}:{package}/{name}'], cwd=ROOT)
        assert hashlib.sha256(body).hexdigest() == digest, name
    assert not (site / 'data/fixed-factor-history.json').exists(), 'Stale history sidecar in a new embedded-history release'
    html = (site / 'index.html').read_text()
    for asset in ('integrated.js', 'integrated_charts.js', 'integrated.css'):
        path = 'assets/' + asset
        assert path in manifest['files'] and path in html
    print(f"PASS daily Factor publication: {result['resultIdentity']['resultId']}, {manifest['dataAsOf']}")
    return manifest

def validate_fixed_factor_history(sidecar, parent, parent_bytes):
    """Validate the additive presentation artifact without recomputing a portfolio."""
    identity = parent['resultIdentity']
    assert sidecar['schemaVersion'] == 'fixed-factor-history/v1'
    bindings = dict(parentSha256=hashlib.sha256(parent_bytes).hexdigest(),
                    parentResultId=identity['resultId'], inputHash=identity['inputHash'],
                    codeHash=identity['codeHash'], dataAsOf=parent['data']['asOf'])
    for key, value in bindings.items():
        assert sidecar[key] == value, f'History parent binding mismatch: {key}'
    definitions = {row['id']: row for row in parent['registry']}
    parents = {row['id']: row for row in parent['factors']}
    assert set(sidecar['factors']) == set(parents) == set(definitions), 'History factor catalog mismatch'
    eligible = {key for key, row in definitions.items() if row['selectionEligible']}
    assert sidecar['validation'] == dict(
        status='passed', fixedFactorsReplayed=len(eligible),
        financialComparison='exact_parent_nav_drawdown_metrics_ending_holdings_cash'), 'History replay validation mismatch'
    asof = sidecar['dataAsOf']
    sessions = sorted({row['date'] for factor in parents.values() for row in factor['nav']})
    delay = parent['settings']['execution_delay_sessions']

    def valid_date(value):
        assert isinstance(value, str) and date.fromisoformat(value).isoformat() == value, 'Invalid history date'
        return value

    def finite(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

    def weights(rows):
        assert len({r['symbol'] for r in rows}) == len(rows), 'Duplicate holding symbol'
        assert all(isinstance(r['symbol'], str) and r['symbol'] and finite(r['weight']) and
                   0 < r['weight'] <= 1 + 1e-9 for r in rows), 'Invalid holding weights'
        return {r['symbol']: r['weight'] for r in rows}

    def snapshot(row, observed):
        held = weights(row['holdings'])
        state = row['valuationStatus']
        assert state in {'available', 'last_complete', 'unavailable'}, 'Invalid valuation status'
        if state == 'unavailable':
            assert not held and row['holdingsAsOf'] is None
            assert all(row[k] is None for k in ('cashWeight', 'receivableWeight', 'liquidCashWeight'))
            return
        valued = valid_date(row['holdingsAsOf'])
        assert valued <= observed, 'Holdings valued after observation'
        assert (valued == observed) == (state == 'available'), 'Valuation status/date mismatch'
        cash, claim, liquid = (row[k] for k in ('cashWeight', 'receivableWeight', 'liquidCashWeight'))
        assert all(finite(v) and -1e-9 <= v <= 1 + 1e-9 for v in (cash, claim, liquid)), 'Invalid cash or claims'
        assert abs(cash - claim - liquid) < 1e-9, 'Claims counted incorrectly'
        assert abs(sum(held.values()) + cash - 1) < 1e-9, 'Holdings and cash do not conserve NAV'

    for key, factor in sidecar['factors'].items():
        original = parents[key]
        assert factor['status'] == original['status'], f'History factor status mismatch: {key}'
        if key not in eligible:
            assert factor['status'] == 'research_only' and factor['history'] == [] and factor['latest'] is None
            continue
        assert factor['historyBasis'] == 'execution_close_actual_weights'
        assert factor['holdingsAsOf'] == asof
        history = factor['history']
        signals = [valid_date(r['signalDate']) for r in history]
        assert signals == sorted(set(signals)), 'History signals must be unique and sorted'
        assert signals == [r['signalDate'] for r in parent['selection']['history']], 'History monthly coverage differs from parent'
        for row in history:
            signal = row['signalDate']
            assert row['date'] == signal and signal <= asof
            execution = row['executionDate']
            assert execution is not None and valid_date(execution) > signal, 'Execution must follow signal'
            position = bisect.bisect_right(sessions, signal) + delay - 1
            if position < len(sessions):
                assert execution == sessions[position], 'Execution does not match session delay'
            pending = row['status'] == 'pending'
            assert row['status'] in {'pending', 'executed', 'valuation_unavailable', 'blocked',
                                     'deferred', 'awaiting_first_signal', 'not_executed'}
            assert pending == (execution > asof), 'Pending execution timing mismatch'
            assert row['targetStatus'] in {'available', 'unavailable'}
            target = weights(row['targetHoldings'])
            assert finite(row['targetCashWeight']) and -1e-9 <= row['targetCashWeight'] <= 1 + 1e-9
            assert abs(sum(target.values()) + row['targetCashWeight'] - 1) < 1e-9, 'Target weights do not conserve NAV'
            snapshot(row, asof if pending else execution)
            if pending:
                assert row['executionStatus'] == 'pending' and row['turnover'] is None and row['cost'] is None
            else:
                assert all(finite(row[k]) and row[k] >= 0 for k in ('turnover', 'cost'))
                if row['status'] == 'executed':
                    assert row['executionStatus'].startswith('executed') and row['targetStatus'] == 'available'
                    assert row['holdingsAsOf'] == execution, 'Executed holdings use the wrong close'
                elif row['status'] == 'blocked':
                    assert row['executionStatus'].startswith('blocked_')
                elif row['status'] == 'valuation_unavailable':
                    assert row['valuationStatus'] != 'available'
        latest = factor['latest']
        snapshot(latest, asof)
        assert weights(latest['holdings']) == weights(original['holdings']), 'Latest holdings differ from parent'
        for field in ('cashWeight', 'receivableWeight', 'liquidCashWeight'):
            assert latest[field] == original[field], f'Latest {field} differs from parent'
    return bindings


def validate_history_publication(site, manifest, result):
    contract = manifest['fixedFactorHistory']
    relative = contract['path']
    assert relative == 'data/fixed-factor-history.json', 'Unexpected history path'
    sidecar = json.loads((site / relative).read_text())
    bindings = validate_fixed_factor_history(sidecar, result, (site / 'data/integrated-result.json').read_bytes())
    for key, value in bindings.items():
        assert contract[key] == value, f'History manifest binding mismatch: {key}'
    assert contract['validation'] == sidecar['validation']
    sources = {'momentum_factor_lab/integrated_history.py', 'scripts/export_fixed_factor_history.py'}
    assert set(contract['sourceFiles']) == sources, 'History source catalog mismatch'
    for name, digest in contract['sourceFiles'].items():
        if contract.get('extractionSourceCommit'):
            body = subprocess.check_output(['git', 'show', f"{contract['extractionSourceCommit']}:{name}"], cwd=ROOT)
        else:
            body = (ROOT / name).read_bytes()
        assert hashlib.sha256(body).hexdigest() == digest, f'History source mismatch: {name}'
    html = (site / 'index.html').read_text()
    asset = 'assets/integrated_charts.js'
    assert asset in manifest['files'] and asset in html, 'Missing shared chart asset'
    assert html.index(asset) < html.index('assets/integrated.js'), 'Chart dependency must load first'
    assert relative in (site / 'assets/integrated.js').read_text(), 'History asset is not consumed'


def validate(site=ROOT / 'site'):
    site = Path(site)
    manifest = json.loads((site / 'publication.json').read_text())
    assert manifest['schemaVersion'] in {'integrated-publication/v1', 'integrated-publication/v2'}
    assert manifest['status'] == 'passed'
    expected = manifest['files']
    observed = {p.relative_to(site).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in site.rglob('*') if p.is_file() and p.name != 'publication.json'}
    assert observed == expected, 'Publication contains missing, changed or unreviewed files'
    result = json.loads((site / 'data/integrated-result.json').read_text())
    if manifest['schemaVersion'] == 'integrated-publication/v2':
        return validate_daily_publication(site, manifest, result)
    identity = result['resultIdentity']
    assert identity == manifest['resultIdentity'], 'Result identity differs from reviewed release'
    source = manifest['calculationSourceCommit']
    assert len(source) == 40 and all(c in '0123456789abcdef' for c in source)
    for name, digest in identity['codeHashFiles'].items():
        body = subprocess.check_output(['git', 'show', f'{source}:momentum_factor_lab/{name}'], cwd=ROOT)
        assert hashlib.sha256(body).hexdigest() == digest, f'Calculation source mismatch: {name}'
    fingerprint = hashlib.sha256(json.dumps(identity['codeHashFiles'], sort_keys=True).encode()).hexdigest()
    assert fingerprint == identity['codeHash']
    assert result['data']['asOf'] == manifest['dataAsOf']
    assert result['data']['requestedCount'] == manifest['requestedCount'] == 2960
    assert len(set(result['data']['requestedSymbols'])) == 2960
    assert len(result['registry']) == len(result['factors']) == 32
    candidates = result['selection']['current']['candidates']
    assert len(candidates) == 26 and all(c.get('score') is not None for c in candidates)
    assert {c['status'] for c in candidates} <= {'eligible', 'risk_rejected'}
    assert len([c for c in candidates if c['status'] == 'eligible']) == 24
    assert result['selection']['current']['factorId'] == 'LOGADV63'
    assert len(result['selection']['holdings']) == 20
    for key, value in manifest['independentMainMetrics'].items():
        assert abs(result['selection']['metrics'][key] - value) < 1e-12, key
    assert all(f['metrics']['endingNavAvailable'] for f in result['factors'] if f['status'] == 'available')
    stress = result['research']['stress']
    assert len(stress) == 7
    assert all(s['inputHash'] == identity['inputHash'] and s['codeHash'] == identity['codeHash'] for s in stress)
    assert manifest['validation']['manualBooks'] == 190
    assert manifest['validation']['mergedSourceShadow']['status'] == 'passed'
    assert manifest['validation']['mergedSourceShadow']['originalCodeHash'] == identity['codeHash']
    html = (site / 'index.html').read_text()
    for asset in ['assets/integrated.js', 'assets/integrated.css', 'assets/styles.css', 'assets/shared-nav.css']:
        assert asset in html and asset in expected
    assert 'data/integrated-result.json' in (site / 'assets/integrated.js').read_text()
    assert 'data/dashboard.json' not in (site / 'assets/integrated.js').read_text()
    validate_history_publication(site, manifest, result)
    assert manifest['scheduledIntegratedRefresh'] == 'not_activated'
    print(f"PASS integrated publication: {identity['resultId']}, {len(expected)+1} files, source {source}")
    return manifest

if __name__ == '__main__':
    validate(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'site')
