"""Integrated publication is explicit; legacy jobs cannot replace its artifact."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('publication_validator', ROOT / 'scripts/validate_integrated_publication.py')
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


def test_reviewed_publication_has_exact_assets_and_calculation_source():
    validator.validate()


def test_publication_rejects_changed_bytes_and_unreviewed_assets(tmp_path):
    target = tmp_path / 'site'
    shutil.copytree(ROOT / 'site', target)
    asset = target / 'assets/integrated.js'
    original = asset.read_bytes()
    asset.write_bytes(original + b'\n// unreviewed\n')
    with pytest.raises(AssertionError, match='unreviewed files'):
        validator.validate(target)
    asset.write_bytes(original)
    (target / 'extra.json').write_text('{}')
    with pytest.raises(AssertionError, match='unreviewed files'):
        validator.validate(target)


def test_deployment_and_recovery_read_the_same_integrated_publication():
    deploy = (ROOT / '.github/workflows/deploy-pages.yml').read_text()
    recovery = (ROOT / '.github/workflows/daily-dashboard-watchdog.yml').read_text()
    daily = (ROOT / '.github/workflows/daily-dashboard.yml').read_text()
    assert 'path: public' in deploy and 'find public -type f' in deploy
    assert 'PUBLICATION_ROOT: public' in recovery
    assert 'find "${PUBLICATION_ROOT:-docs}" -type f' in recovery
    for text in (deploy, recovery, daily):
        assert 'required_paths=(index.html publication.json data/integrated-result.json)' in text
    # This publication migration must not modify any existing schedule slots.
    for name in ('daily-dashboard.yml', 'daily-dashboard-watchdog.yml'):
        before = subprocess.check_output(['git', 'show', f'd0a07060a7ca330c50a8cc9edf76d9929f981c3b:.github/workflows/{name}'], cwd=ROOT, text=True)
        after = (ROOT / '.github/workflows' / name).read_text()
        assert [s.strip() for s in before.splitlines() if 'cron:' in s] == [s.strip() for s in after.splitlines() if 'cron:' in s]


def test_legacy_control_artifacts_remain_exact_and_cannot_replace_integrated_result(tmp_path):
    spec = importlib.util.spec_from_file_location('builder', ROOT / 'scripts/build_integrated_publication.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    site, legacy = tmp_path / 'site', tmp_path / 'legacy'
    (site / 'data').mkdir(parents=True)
    legacy.mkdir()
    (site / 'index.html').write_text('integrated UI')
    (site / 'data/integrated-result.json').write_text('{"schema":"integrated"}')
    (legacy / 'dashboard.json').write_text('{"schema":"legacy"}')
    control = legacy / 'control-runs/v1/run/result.json'
    control.parent.mkdir(parents=True)
    control.write_bytes(b'{"boundRun":"unchanged"}\n')
    output = tmp_path / 'published'
    manifest = module.build(output, site, legacy, source_sha='a' * 40)
    assert (output / 'data/control-runs/v1/run/result.json').read_bytes() == control.read_bytes()
    assert (output / 'data/dashboard.json').read_bytes() == (legacy / 'dashboard.json').read_bytes()
    assert (output / 'data/integrated-result.json').read_bytes() == (site / 'data/integrated-result.json').read_bytes()
    assert len(manifest['files']) == 2
    (legacy / 'integrated-result.json').write_text('{}')
    with pytest.raises(ValueError, match='collides'):
        module.build(tmp_path / 'collision', site, legacy, source_sha='a' * 40)


@pytest.fixture
def fixed_history():
    import json
    parent_bytes = (ROOT / 'site/data/integrated-result.json').read_bytes()
    return (json.loads((ROOT / 'site/data/fixed-factor-history.json').read_text()),
            json.loads(parent_bytes), parent_bytes)


def test_fixed_history_rejects_different_parent_bytes(fixed_history):
    history, parent, body = fixed_history
    with pytest.raises(AssertionError, match='parent binding mismatch: parentSha256'):
        validator.validate_fixed_factor_history(history, parent, body + b'\n')


@pytest.mark.parametrize(('mutation', 'message'), [
    ('order', 'unique and sorted'),
    ('missing_month', 'monthly coverage'),
    ('signal_execution', 'Execution must follow signal'),
    ('opening_weights_date', 'Executed holdings use the wrong close'),
    ('claims', 'Claims counted incorrectly'),
    ('weight_sum', 'do not conserve NAV'),
    ('latest', 'Latest holdings differ'),
    ('replay', 'replay validation mismatch'),
    ('factor_status', 'factor status mismatch'),
])
def test_fixed_history_rejects_financial_and_timing_corruption(fixed_history, mutation, message):
    history, parent, body = fixed_history
    factor = history['factors']['MOM12_1']
    row = factor['history'][0]
    if mutation == 'order':
        factor['history'][:2] = reversed(factor['history'][:2])
    elif mutation == 'missing_month':
        factor['history'].pop(0)
    elif mutation == 'signal_execution':
        row['executionDate'] = row['signalDate']
    elif mutation == 'opening_weights_date':
        row['holdingsAsOf'] = row['signalDate']
        row['valuationStatus'] = 'last_complete'
    elif mutation == 'claims':
        row['receivableWeight'] = .01
    elif mutation == 'weight_sum':
        row['holdings'][0]['weight'] += .01
    elif mutation == 'latest':
        factor['latest']['holdings'][0]['weight'] += .001
        factor['latest']['holdings'][1]['weight'] -= .001
    elif mutation == 'replay':
        history['validation']['fixedFactorsReplayed'] -= 1
    elif mutation == 'factor_status':
        factor['status'] = 'partial_data'
    with pytest.raises(AssertionError, match=message):
        validator.validate_fixed_factor_history(history, parent, body)


def test_history_source_hash_is_verified(fixed_history):
    import json
    history, parent, body = fixed_history
    manifest = json.loads((ROOT / 'site/publication.json').read_text())
    manifest['fixedFactorHistory']['sourceFiles']['momentum_factor_lab/integrated_history.py'] = '0' * 64
    with pytest.raises(AssertionError, match='History source mismatch'):
        validator.validate_history_publication(ROOT / 'site', manifest, parent)
