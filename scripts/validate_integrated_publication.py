"""Validate the immutable integrated Pages release and its calculation provenance."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def validate(site=ROOT / 'site'):
    site = Path(site)
    manifest = json.loads((site / 'publication.json').read_text())
    assert manifest['schemaVersion'] == 'integrated-publication/v1'
    assert manifest['status'] == 'passed'
    expected = manifest['files']
    observed = {p.relative_to(site).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in site.rglob('*') if p.is_file() and p.name != 'publication.json'}
    assert observed == expected, 'Publication contains missing, changed or unreviewed files'
    result = json.loads((site / 'data/integrated-result.json').read_text())
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
    assert manifest['scheduledIntegratedRefresh'] == 'not_activated'
    print(f"PASS integrated publication: {identity['resultId']}, {len(expected)+1} files, source {source}")
    return manifest

if __name__ == '__main__':
    validate(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'site')
