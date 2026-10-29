"""Strict, result-bound operational state, separate from financial publication."""

from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re

CONTRACT = "factor-refresh-status/v1"
RELATIVE_PATH = "data/refresh-status.json"


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _iso(value):
    _require(
        isinstance(value, str) and date.fromisoformat(value).isoformat() == value,
        "Invalid operational date",
    )
    return value


def _utc(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _require(
        parsed.tzinfo is not None and parsed.utcoffset() is not None,
        "Operational timestamp needs timezone",
    )
    return parsed


def financial_binding(site):
    root = Path(site)
    body = (root / "data/integrated-result.json").read_bytes()
    payload = json.loads(body)
    manifest = json.loads((root / "publication.json").read_text())
    _require(
        manifest["files"]["data/integrated-result.json"] == hashlib.sha256(body).hexdigest(),
        "Financial result bytes differ from publication proof",
    )
    identity = payload["resultIdentity"]
    _require(
        manifest["resultIdentity"] == identity, "Operational binding needs matching financial proof"
    )
    return dict(
        dataAsOf=payload["data"]["asOf"],
        resultId=identity["resultId"],
        inputHash=identity["inputHash"],
        codeHash=identity["codeHash"],
        calculationSourceCommit=manifest["calculationSourceCommit"],
    )


def validate_status(payload, binding):
    _require(
        isinstance(payload, dict)
        and set(payload) == {"schemaVersion", "status", "updatedAtUtc", "attempt", "lastGood"},
        "Operational field contract",
    )
    _require(
        payload["schemaVersion"] == CONTRACT and payload["status"] in {"ok", "failed", "delayed"},
        "Operational status contract",
    )
    _require(
        payload["lastGood"] == binding, "Operational status refers to a different financial result"
    )
    _iso(binding["dataAsOf"])
    for key in ("inputHash", "codeHash"):
        _require(
            re.fullmatch("[0-9a-f]{64}", binding[key]) is not None, "Operational financial hash"
        )
    _require(
        re.fullmatch("[0-9a-f]{40}", binding["calculationSourceCommit"]) is not None,
        "Operational financial source",
    )
    attempt = payload["attempt"]
    _require(
        set(attempt)
        == {
            "runId",
            "runAttempt",
            "startedAtUtc",
            "finishedAtUtc",
            "sourceCommit",
            "targetDataAsOf",
            "status",
            "reasonCode",
            "missingSymbols",
            "runUrl",
        },
        "Operational attempt fields",
    )
    _require(isinstance(attempt["runId"], str) and attempt["runId"].isdigit(), "Operational run ID")
    _require(
        type(attempt["runAttempt"]) is int and attempt["runAttempt"] >= 1, "Operational run attempt"
    )
    _require(
        re.fullmatch("[0-9a-f]{40}", attempt["sourceCommit"]) is not None,
        "Operational attempt source",
    )
    _require(
        attempt["runUrl"]
        == "https://github.com/SonChangGi/factor/actions/runs/" + attempt["runId"],
        "Operational run URL",
    )
    _require(
        attempt["status"] in {"succeeded", "failed", "cancelled", "skipped"},
        "Operational attempt state",
    )
    _require(
        attempt["reasonCode"]
        in {
            "ok",
            "already_current",
            "provider_not_ready",
            "held_quote_missing",
            "benchmark_quote_missing",
            "refresh_failed",
            "publication_failed",
            "cancelled",
        },
        "Operational reason code",
    )
    symbols = attempt["missingSymbols"]
    _require(
        isinstance(symbols, list)
        and len(symbols) <= 3000
        and symbols == sorted(set(symbols))
        and all(
            isinstance(s, str) and re.fullmatch(r"[A-Za-z0-9^][A-Za-z0-9.^=-]{0,31}", s)
            for s in symbols
        ),
        "Operational missing-symbol contract",
    )
    if attempt["targetDataAsOf"] is not None:
        _iso(attempt["targetDataAsOf"])
    start, finish = _utc(attempt["startedAtUtc"]), _utc(attempt["finishedAtUtc"])
    _require(start <= finish <= _utc(payload["updatedAtUtc"]), "Operational attempt timestamps")
    _require(
        len(json.dumps(payload, allow_nan=False).encode()) <= 64 * 1024,
        "Operational state exceeds 64 KiB",
    )
    return payload


def write_status(
    site,
    *,
    run_id,
    run_attempt,
    source_commit,
    outcome,
    deployment_outcome="skipped",
    target=None,
    started_at=None,
    finished_at=None,
    status_directory=None,
    now=None,
):
    root = Path(site)
    binding = financial_binding(root)
    instant = (now or datetime.now(timezone.utc)).isoformat()
    runner, readiness = {}, {}
    if status_directory and Path(status_directory).exists():
        for path in sorted(Path(status_directory).rglob("status.json")):
            item = json.loads(path.read_text())
            if item.get("schemaVersion") == "factor-automation/v1":
                runner = item
            elif item.get("schemaVersion") == "factor-provider-readiness/v1":
                readiness = item
    target = target or runner.get("targetDataAsOf") or readiness.get("targetDataAsOf")
    reason = runner.get(
        "reasonCode",
        "provider_not_ready" if readiness.get("status") == "waiting" else "refresh_failed",
    )
    symbols = runner.get("missingSymbols", readiness.get("missingSymbols", []))
    state = "failed"
    if outcome == "success":
        state, reason = (
            ("succeeded", "ok")
            if deployment_outcome == "success"
            else ("skipped", "already_current")
        )
    elif outcome == "cancelled":
        state, reason = "cancelled", "cancelled"
    if outcome == "success" and deployment_outcome in {"failure", "cancelled"}:
        state, reason = "failed", "publication_failed"
    attempt = dict(
        runId=str(run_id),
        runAttempt=int(run_attempt),
        startedAtUtc=started_at or runner.get("attemptedAtUtc") or instant,
        finishedAtUtc=finished_at or runner.get("finishedAtUtc") or instant,
        sourceCommit=source_commit,
        targetDataAsOf=target,
        status=state,
        reasonCode=reason,
        missingSymbols=sorted(set(symbols)),
        runUrl="https://github.com/SonChangGi/factor/actions/runs/" + str(run_id),
    )
    status = (
        "ok"
        if state in {"succeeded", "skipped"}
        else "delayed"
        if reason == "provider_not_ready"
        else "failed"
    )
    # The old attempt may finish after a newer financial result was accepted.
    if target is not None and target <= binding["dataAsOf"]:
        status = "ok"
    payload = dict(
        schemaVersion=CONTRACT,
        status=status,
        updatedAtUtc=instant,
        attempt=attempt,
        lastGood=binding,
    )
    validate_status(payload, binding)
    destination = root / RELATIVE_PATH
    _require(not destination.is_symlink(), "Operational state cannot be a symbolic link")
    if destination.exists():
        previous = json.loads(destination.read_text())
        # Compare attempt ordering even if its last-good financial binding is old.
        old = previous.get("attempt", {})
        if (int(old.get("runId", "0")), int(old.get("runAttempt", 0))) > (
            int(run_id),
            int(run_attempt),
        ):
            return dict(changed=False, reason="newer_attempt_preserved")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n"
    )
    return dict(changed=True, status=status, lastGood=binding)


def validate_file(site):
    root = Path(site)
    path = root / RELATIVE_PATH
    if path.exists():
        _require(not path.is_symlink(), "Operational state cannot be a symbolic link")
        validate_status(json.loads(path.read_text()), financial_binding(root))
