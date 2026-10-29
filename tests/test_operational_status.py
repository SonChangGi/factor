from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

from factor_lab.operational_status import financial_binding, validate_file, write_status

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 29, 8, tzinfo=timezone.utc)


def site_fixture(root, day="2026-10-27", identifier="a" * 24):
    (root / "data").mkdir(parents=True, exist_ok=True)
    result = {
        "data": {"asOf": day},
        "resultIdentity": {"resultId": identifier, "inputHash": "b" * 64, "codeHash": "c" * 64},
    }
    body = json.dumps(result).encode()
    (root / "data/integrated-result.json").write_bytes(body)
    manifest = {
        "calculationSourceCommit": "d" * 40,
        "resultIdentity": result["resultIdentity"],
        "files": {"data/integrated-result.json": hashlib.sha256(body).hexdigest()},
    }
    (root / "publication.json").write_text(json.dumps(manifest))
    return result


def failed_attempt(root, *, run=40802522743, **kwargs):
    return write_status(
        root,
        run_id=str(run),
        run_attempt=1,
        source_commit="e" * 40,
        outcome="failure",
        target="2026-10-28",
        started_at="2026-10-29T01:47:25Z",
        finished_at="2026-10-29T02:56:58Z",
        now=NOW,
        **kwargs,
    )


def test_failed_state_binds_current_financial_proof_without_modifying_any_financial_bytes(tmp_path):
    site_fixture(tmp_path)
    before = {
        str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()
    }
    failed_attempt(tmp_path)
    validate_file(tmp_path)
    for name, value in before.items():
        assert (tmp_path / name).read_bytes() == value
    status = json.loads((tmp_path / "data/refresh-status.json").read_text())
    assert (
        status["status"] == "failed"
        and status["attempt"]["sourceCommit"] != status["lastGood"]["calculationSourceCommit"]
    )
    assert status["attempt"]["finishedAtUtc"] == "2026-10-29T02:56:58Z"
    assert status["updatedAtUtc"] != status["attempt"]["finishedAtUtc"]


@pytest.mark.parametrize("outcome", ["failure", "cancelled", "skipped"])
def test_setup_or_admission_failure_without_artifact_is_recorded(tmp_path, outcome):
    site_fixture(tmp_path)
    write_status(
        tmp_path, run_id="12345", run_attempt=1, source_commit="e" * 40, outcome=outcome, now=NOW
    )
    validate_file(tmp_path)
    status = json.loads((tmp_path / "data/refresh-status.json").read_text())
    assert status["attempt"]["targetDataAsOf"] is None
    assert status["status"] == "failed"


def test_missing_provider_receipt_yields_delayed_and_runner_reason_has_priority(tmp_path):
    site_fixture(tmp_path / "site")
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    (receipts / "status.json").write_text(
        json.dumps(
            {
                "schemaVersion": "factor-provider-readiness/v1",
                "status": "waiting",
                "targetDataAsOf": "2026-10-28",
                "missingSymbols": ["QQQ"],
            }
        )
    )
    failed_attempt(tmp_path / "site", status_directory=receipts)
    status = json.loads((tmp_path / "site/data/refresh-status.json").read_text())
    assert status["status"] == "delayed" and status["attempt"]["missingSymbols"] == ["QQQ"]
    run = receipts / "run"
    run.mkdir()
    (run / "status.json").write_text(
        json.dumps(
            {
                "schemaVersion": "factor-automation/v1",
                "reasonCode": "held_quote_missing",
                "targetDataAsOf": "2026-10-28",
                "missingSymbols": ["HUBB"],
            }
        )
    )
    failed_attempt(tmp_path / "site", status_directory=receipts)
    assert (
        json.loads((tmp_path / "site/data/refresh-status.json").read_text())["attempt"][
            "reasonCode"
        ]
        == "held_quote_missing"
    )


def test_old_failed_attempt_cannot_overwrite_newer_run_and_cannot_mark_new_financial_result_stale(
    tmp_path,
):
    site_fixture(tmp_path)
    failed_attempt(tmp_path, run=50000)
    before = (tmp_path / "data/refresh-status.json").read_bytes()
    assert failed_attempt(tmp_path, run=49999)["changed"] is False
    assert (tmp_path / "data/refresh-status.json").read_bytes() == before
    site_fixture(tmp_path, day="2026-10-28", identifier="f" * 24)
    failed_attempt(tmp_path, run=50001)
    assert json.loads((tmp_path / "data/refresh-status.json").read_text())["status"] == "ok"


def test_operational_state_rejects_mismatched_financial_result_and_extra_payload(tmp_path):
    site_fixture(tmp_path)
    failed_attempt(tmp_path)
    path = tmp_path / "data/refresh-status.json"
    value = json.loads(path.read_text())
    value["lastGood"]["resultId"] = "x" * 24
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="different financial result"):
        validate_file(tmp_path)
    failed_attempt(tmp_path)
    value = json.loads(path.read_text())
    value["attempt"]["rawProviderPayload"] = {"secret": "not permitted"}
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="attempt fields"):
        validate_file(tmp_path)


def test_financial_changed_bytes_cannot_acquire_a_false_operational_binding(tmp_path):
    site_fixture(tmp_path)
    path = tmp_path / "data/integrated-result.json"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="bytes differ"):
        financial_binding(tmp_path)


def test_new_financial_candidate_removes_old_operational_binding_and_next_status_rebinds(tmp_path):
    from factor_lab.integrated_service import build_site

    root = tmp_path / "candidate"
    site_fixture(root)
    failed_attempt(root)
    old_result = (root / "data/integrated-result.json").read_bytes()
    fresh = site_fixture(tmp_path / "new", day="2026-10-28", identifier="f" * 24)
    build_site(root, fresh)
    assert not (root / "data/refresh-status.json").exists()
    assert (root / "data/integrated-result.json").read_bytes() != old_result
    # The new financial manifest is written before a separately bound status.
    new_body = (root / "data/integrated-result.json").read_bytes()
    (root / "publication.json").write_text(
        json.dumps(
            {
                "calculationSourceCommit": "d" * 40,
                "resultIdentity": fresh["resultIdentity"],
                "files": {"data/integrated-result.json": hashlib.sha256(new_body).hexdigest()},
            }
        )
    )
    failed_attempt(root)
    validate_file(root)
    assert (
        json.loads((root / "data/refresh-status.json").read_text())["lastGood"]["resultId"]
        == "f" * 24
    )


def _git(directory, *args):
    return subprocess.check_output(["git", *args], cwd=directory, text=True).strip()


def test_operational_cas_publisher_commits_only_status_on_latest_remote_financial_result(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "publish_refresh", ROOT / "scripts/publish_refresh_status.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    remote, writer, runner = (tmp_path / p for p in ("remote.git", "writer", "runner"))
    _git(tmp_path, "init", "--bare", "--initial-branch=main", str(remote))
    _git(tmp_path, "clone", str(remote), str(writer))
    _git(writer, "config", "user.name", "Fixture")
    _git(writer, "config", "user.email", "fixture@example.invalid")
    site_fixture(writer / "site")
    _git(writer, "add", ".")
    _git(writer, "commit", "-m", "initial")
    _git(writer, "push", "origin", "main")
    _git(tmp_path, "clone", str(remote), str(runner))
    # Production advances after the calculation checkout, before state publication.
    site_fixture(writer / "site", day="2026-10-28", identifier="f" * 24)
    _git(writer, "add", ".")
    _git(writer, "commit", "-m", "new financial")
    _git(writer, "push", "origin", "main")
    before = _git(remote, "rev-parse", "main")
    result = module.publish(
        runner,
        "main",
        run_id="40802522743",
        run_attempt=1,
        source_commit="e" * 40,
        outcome="failure",
        target="2026-10-28",
        started_at="2026-10-29T01:47:25Z",
        now=NOW,
    )
    assert result["should_deploy"] == "true"
    assert _git(remote, "diff", "--name-only", before, "main") == "site/data/refresh-status.json"
    value = json.loads(_git(remote, "show", "main:site/data/refresh-status.json"))
    assert value["lastGood"]["resultId"] == "f" * 24 and value["status"] == "ok"
    assert (
        json.loads(_git(remote, "show", "main:site/data/integrated-result.json"))["data"]["asOf"]
        == "2026-10-28"
    )


def test_only_named_operational_file_is_outside_financial_inventory(tmp_path):
    from scripts.release_preflight import check_files

    site_fixture(tmp_path)
    failed_attempt(tmp_path)
    check_files(tmp_path)
    (tmp_path / "data/unreviewed-status.json").write_text("{}")
    with pytest.raises(ValueError, match="unreviewed files"):
        check_files(tmp_path)


def test_status_push_race_retries_against_new_financial_tip_without_overwriting_it(
    tmp_path, monkeypatch
):
    spec = importlib.util.spec_from_file_location(
        "publish_refresh_race", ROOT / "scripts/publish_refresh_status.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    remote, writer, runner = (tmp_path / p for p in ("remote.git", "writer", "runner"))
    _git(tmp_path, "init", "--bare", "--initial-branch=main", str(remote))
    _git(tmp_path, "clone", str(remote), str(writer))
    _git(writer, "config", "user.name", "Fixture")
    _git(writer, "config", "user.email", "fixture@example.invalid")
    site_fixture(writer / "site")
    _git(writer, "add", ".")
    _git(writer, "commit", "-m", "initial")
    _git(writer, "push", "origin", "main")
    _git(tmp_path, "clone", str(remote), str(runner))
    original_run = subprocess.run
    fired = []

    def race(args, *rest, **kwargs):
        if args[:3] == ["git", "push", "origin"] and not fired:
            fired.append(True)
            site_fixture(writer / "site", day="2026-10-28", identifier="f" * 24)
            _git(writer, "add", ".")
            _git(writer, "commit", "-m", "concurrent financial publication")
            _git(writer, "push", "origin", "main")
        return original_run(args, *rest, **kwargs)

    monkeypatch.setattr(subprocess, "run", race)
    result = module.publish(
        runner,
        "main",
        run_id="40802522743",
        run_attempt=1,
        source_commit="e" * 40,
        outcome="failure",
        target="2026-10-28",
        started_at="2026-10-29T01:47:25Z",
        now=NOW,
    )
    assert fired and result["should_deploy"] == "true"
    value = json.loads(_git(remote, "show", "main:site/data/refresh-status.json"))
    assert value["lastGood"]["resultId"] == "f" * 24 and value["status"] == "ok"
    assert _git(remote, "diff", "--name-only", "main~1", "main") == "site/data/refresh-status.json"
