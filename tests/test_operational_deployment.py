"""Producer request origins and deployment coordination use the actual workflow contract."""
import importlib.util
import json
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('status_deployment', ROOT / 'scripts/publish_refresh_status.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_every_literal_producer_origin_is_accepted_by_pages():
    consumer = (ROOT / '.github/workflows/deploy-pages.yml').read_text()
    block = consumer.split('case "${REQUEST_ORIGIN}" in', 1)[1].split('*)', 1)[0]
    allowed = set(re.search(r'([a-z|\-]+)\)', block).group(1).split('|'))
    found = set()
    for path in (ROOT / '.github/workflows').glob('*.yml'):
        origins = set(re.findall(r'\brequest_origin=([a-z\-]+)', path.read_text()))
        found.update(origins)
        assert origins <= allowed, f'{path.name}: unsupported request origin {origins - allowed}'
    assert {'daily-refresh-status', 'watchdog-refresh-status'} <= found
    assert 'Unsupported deployment request origin.' in consumer
    assert 'remote_sha' in consumer and 'EXPECTED_SOURCE_SHA' in consumer


def test_status_publication_waits_for_existing_pages_before_advancing_main(tmp_path, monkeypatch):
    states = iter([[{'status': 'in_progress'}, {'status': 'queued'}], [{'status': 'completed'}]])
    calls, sleeps = [], []
    def runs(command, **kwargs):
        calls.append((command, kwargs))
        return json.dumps(next(states))
    monkeypatch.setattr(module.subprocess, 'check_output', runs)
    monkeypatch.setattr(module.time, 'sleep', sleeps.append)
    module.wait_for_idle_pages(tmp_path, 'main', timeout=20)
    assert len(calls) == 2 and len(sleeps) == 1
    assert calls[0][1]['timeout'] == 30
    assert calls[0][0][calls[0][0].index('--workflow') + 1] == 'deploy-pages.yml'


def test_status_publication_does_not_wait_or_change_data_when_pages_idle(tmp_path, monkeypatch):
    monkeypatch.setattr(module.subprocess, 'check_output', lambda *a, **k: '[]')
    monkeypatch.setattr(module.time, 'sleep', lambda _: pytest.fail('Already idle'))
    module.wait_for_idle_pages(tmp_path, 'main', timeout=0)
    assert list(tmp_path.iterdir()) == []


def test_status_timeout_and_unreadable_state_do_not_write_financial_files(tmp_path, monkeypatch):
    marker = tmp_path / 'last-good.json'
    marker.write_bytes(b'accepted financial result')
    monkeypatch.setattr(module.subprocess, 'check_output', lambda *a, **k: '[{"status":"in_progress"}]')
    with pytest.raises(TimeoutError, match='commit was not made'):
        module.wait_for_idle_pages(tmp_path, 'main', timeout=0)
    monkeypatch.setattr(module.subprocess, 'check_output', lambda *a, **k: '{}')
    with pytest.raises(ValueError, match='Cannot establish active Pages'):
        module.wait_for_idle_pages(tmp_path, 'main', timeout=0)
    assert marker.read_bytes() == b'accepted financial result'


def test_all_scheduled_status_publishers_coordinate_with_pages():
    for name in ('daily-dashboard.yml', 'daily-dashboard-watchdog.yml'):
        workflow = (ROOT / '.github/workflows' / name).read_text()
        calls = [line for line in workflow.splitlines() if 'python scripts/publish_refresh_status.py' in line]
        assert calls and all('--wait-for-pages' in line for line in calls)
