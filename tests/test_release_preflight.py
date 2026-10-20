"""Regressions for real deployment failures, without market downloads or new backtests."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from scripts import prepare_presentation_release as prepare
from scripts import release_preflight as gate

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def baseline():
    result = json.loads((ROOT / 'site/data/integrated-result.json').read_text())
    return {key: result[key] for key in ('registry', 'data', 'settings', 'resultIdentity')}


@pytest.fixture
def site(tmp_path):
    target = tmp_path / 'site'
    shutil.copytree(ROOT / 'site', target)
    return target


def test_forgotten_html_hash_is_reported_before_dependencies_or_deployment(site):
    path = site / 'index.html'
    path.write_text(path.read_text() + '\n<!-- reviewed UI edit -->\n')
    original = (site / 'publication.json').read_bytes()
    process = subprocess.run([sys.executable, str(ROOT / 'scripts/release_preflight.py'),
                              '--site', str(site), '--mode', 'files'],
                             capture_output=True, text=True)
    assert process.returncode == 1
    assert 'index.html' in process.stderr and 'prepare_presentation_release.py' in process.stderr
    assert (site / 'publication.json').read_bytes() == original


def test_presentation_preparation_preserves_financial_bytes_and_all_provenance(site):
    before = json.loads((site / 'publication.json').read_text())
    data = (site / 'data/integrated-result.json').read_bytes()
    path = site / 'index.html'
    path.write_text(path.read_text() + '\n<!-- reviewed UI edit -->\n')
    assert prepare.prepare(site) == ['index.html']
    after = gate.check_files(site)
    assert after['files']['index.html'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert {k: v for k, v in before.items() if k != 'files'} == {
        k: v for k, v in after.items() if k != 'files'}
    assert (site / 'data/integrated-result.json').read_bytes() == data
    saved = (site / 'publication.json').read_bytes()
    assert prepare.prepare(site) == []
    assert (site / 'publication.json').read_bytes() == saved


@pytest.mark.parametrize('mutation', ['data', 'new_file', 'deleted_file', 'symlink'])
def test_presentation_tool_cannot_approve_non_ui_or_unknown_changes(site, mutation):
    original = (site / 'publication.json').read_bytes()
    if mutation == 'data':
        path = site / 'data/integrated-result.json'
        path.write_bytes(path.read_bytes() + b'\n')
    elif mutation == 'new_file':
        (site / 'assets/unreviewed.js').write_text('new source')
    elif mutation == 'deleted_file':
        (site / 'assets/integrated.js').unlink()
    else:
        (site / 'linked').symlink_to(site / 'index.html')
    with pytest.raises(ValueError):
        prepare.prepare(site)
    assert (site / 'publication.json').read_bytes() == original


def test_even_matching_hashes_do_not_approve_corrupt_performance(site):
    data = site / 'data/integrated-result.json'
    result = json.loads(data.read_text())
    result['selection']['metrics']['cagr'] += .1
    data.write_text(json.dumps(result))
    manifest = site / 'publication.json'
    proof = json.loads(manifest.read_text())
    proof['files']['data/integrated-result.json'] = hashlib.sha256(data.read_bytes()).hexdigest()
    manifest.write_text(json.dumps(proof))
    before = manifest.read_bytes()
    path = site / 'index.html'
    path.write_text(path.read_text() + '\n<!-- UI edit cannot approve false CAGR -->\n')
    with pytest.raises((ValueError, AssertionError)):
        prepare.prepare(site)
    assert manifest.read_bytes() == before


def test_concurrent_edit_cannot_be_overwritten_by_manifest_preparation(site, monkeypatch):
    from scripts import validate_integrated_publication as validator
    original = (site / 'publication.json').read_bytes()
    path = site / 'index.html'
    path.write_text(path.read_text() + '\n<!-- first edit -->\n')
    validate = validator.validate

    def race(candidate):
        validate(candidate)
        path.write_text(path.read_text() + '\n<!-- concurrent user edit -->\n')

    monkeypatch.setattr(validator, 'validate', race)
    with pytest.raises(RuntimeError, match='changed during preparation'):
        prepare.prepare(site)
    assert (site / 'publication.json').read_bytes() == original
    assert 'concurrent user edit' in path.read_text()


@pytest.mark.parametrize('mutation, message', [
    ('definition', 'reviewed definition'), ('universe', 'reviewed universe'),
    ('cost', 'reviewed financial settings'), ('lock', 'dependency lock differs'),
])
def test_daily_preflight_rejects_migrations_before_collection(baseline, mutation, message):
    result = deepcopy(baseline)
    if mutation == 'definition':
        result['registry'][0]['version'] = 'unreviewed'
    elif mutation == 'universe':
        result['data']['requestedSymbols'].pop()
    elif mutation == 'cost':
        result['settings']['transaction_cost_bps'] += 1
    else:
        result['resultIdentity']['runtime']['dependencyLockHash'] = '0' * 64
    with pytest.raises(ValueError, match=message):
        gate.daily_compatibility(result)


def test_current_baseline_is_compatible_without_changing_it(baseline):
    before = json.dumps(baseline, sort_keys=True)
    gate.daily_compatibility(baseline)
    assert json.dumps(baseline, sort_keys=True) == before


def test_nested_manifest_cannot_escape_inventory(site):
    (site / 'data/publication.json').write_text('{}')
    with pytest.raises(ValueError, match='data/publication.json'):
        gate.check_files(site)


def test_ci_and_pages_share_the_full_release_gate_and_locked_environment():
    pages = (ROOT / '.github/workflows/deploy-pages.yml').read_text()
    pr = (ROOT / '.github/workflows/release-preflight.yml').read_text()
    daily = (ROOT / '.github/workflows/daily-dashboard.yml').read_text()
    release = (ROOT / 'scripts/check_release.sh').read_text()
    for workflow in (pr, pages):
        assert 'bash scripts/check_release.sh' in workflow
        assert 'uv sync --locked --extra dev --extra live' in workflow
        assert 'runs-on: ubuntu-24.04' in workflow
        assert "pip install -e" not in workflow and 'pip install --upgrade pip' not in workflow
    assert 'pull_request:' in pr and 'contents: read' in pr
    assert 'pages: write' not in pr and 'id-token: write' not in pr
    assert 'python -m pytest -q tests/test_integrated*.py' in release
    assert 'test_integrated*dom.cjs' in release
    assert 'tests/test_release_preflight.py' in release
    assert '--mode release' in release
    assert daily.index('--mode daily') < daily.index('Resolve the explicitly requested immutable input cache')
    assert daily.index('--mode daily') < daily.index('Collect, reconcile, calculate and validate the candidate')
    assert 'test_fresh_spy_does_not_hide_widespread_stale_equities' in daily
    assert 'uv sync --frozen --extra live --extra dev' in daily
