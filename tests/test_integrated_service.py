import json
import pytest
from factor_lab.integrated_service import atomic_json, normalize_settings, validate_result


def test_atomic_result_preserves_good_file_on_nonfinite_failure(tmp_path):
    path = tmp_path / "result.json"
    atomic_json(path, {"nav": 1})
    with pytest.raises(ValueError):
        atomic_json(path, {"nav": float("nan")})
    assert json.loads(path.read_text()) == {"nav": 1}


@pytest.mark.parametrize(
    "settings",
    [
        {"top_n": 0},
        {"top_n": 20.5},
        {"max_weight": float("nan")},
        {"slippage_bps": -1},
        {"execution_delay_sessions": 0},
        {"arbitrary": 1},
    ],
)
def test_reject_invalid_execution_inputs(settings):
    with pytest.raises(ValueError):
        normalize_settings(settings)


def test_incomplete_result_not_publishable():
    with pytest.raises(ValueError):
        validate_result({"selection": {}, "factors": []})


def test_static_build_copies_hover_chart_dependency_and_versions_exact_assets(tmp_path):
    import hashlib
    import re
    from pathlib import Path
    import factor_lab.integrated_service as service

    result = {'schemaVersion': 'integrated-factor/v1', 'factors': [
        {'id': 'MOM12_1', 'history': [{'signalDate': '2020-01-31', 'holdings': []}]}]}
    service.build_site(tmp_path, result)
    source_web = Path(service.__file__).parent / 'web'
    html = (tmp_path / 'index.html').read_text()
    for name in ('integrated.js', 'integrated_charts.js', 'integrated.css'):
        path = tmp_path / 'assets' / name
        assert path.read_bytes() == (source_web / name).read_bytes()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        assert f'assets/{name}?v={digest}"' in html
    # Deferred dependency order matters: the UI needs the hover renderer when
    # it first renders. Both paths must resolve under a project URL prefix.
    assert html.index('assets/integrated_charts.js') < html.index('assets/integrated.js')
    assert not re.search(r'(?:src|href)="/assets/', html)
    assert json.loads((tmp_path / 'data' / 'integrated-result.json').read_text()) == result


def test_fixed_history_accounting_changes_invalidate_calculation_fingerprint(tmp_path, monkeypatch):
    from pathlib import Path
    import factor_lab.integrated_service as service

    source = Path(service.__file__).parent
    history = tmp_path / 'integrated_history.py'
    history.write_bytes((source / 'integrated_history.py').read_bytes())
    monkeypatch.setattr(service, '__file__', str(tmp_path / 'integrated_service.py'))
    before, records = service.code_fingerprint()
    assert 'integrated_history.py' in records
    history.write_text(history.read_text() + '\n# accounting revision\n')
    after, changed = service.code_fingerprint()
    assert after != before
    assert changed['integrated_history.py'] != records['integrated_history.py']


def test_stress_bindings_use_final_parent_identity_and_same_policy(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import factor_lab.integrated_service as service
    import factor_lab.integrated_engine as engine
    result = dict(schemaVersion='integrated-factor/v1', registry=[{'id': 'A'}],
                  selection={'status': 'fixture'}, factors=[{'id': 'A'}], data={},
                  research={'stress': [dict(id='delay2', sourceResultId='provisional'),
                                       dict(id='fixed_choice_delay2', sourceResultId='provisional')]},
                  resultIdentity=dict(resultId='provisional', inputHash='input', engineVersion='v4'))
    monkeypatch.setattr(engine, 'run_integrated_analysis', lambda *a, **k: result)
    monkeypatch.setattr(service, 'data_inventory', lambda m: [])
    monkeypatch.setattr(service, 'code_fingerprint', lambda: ('code', {'engine.py': 'digest'}))
    market = SimpleNamespace(metadata={'automationPolicy': {'sha256': 'policy'}})
    actual = service.execute_run(market, {}, tmp_path)
    for stress in actual['research']['stress']:
        assert stress['inputHash'] == 'input' and stress['codeHash'] == 'code'
        assert stress['sourceResultId'] == actual['resultIdentity']['resultId'] != 'provisional'
        assert stress['sourceEngineVersion'] == 'v4' and stress['sourcePolicyHash'] == 'policy'
