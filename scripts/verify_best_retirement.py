#!/usr/bin/env python3
"""Read-only Best cleanup preflight. This command never deletes or edits files."""

from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

REQUIRED_GATES = ("data", "parity", "engine", "api", "ui", "stress")
IDENTITY_KEYS = ("resultId", "inputHash", "codeHash")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check(manifest, validation, result):
    failures = []
    if manifest.get("schemaVersion") != "best-cleanup-manifest/v1":
        failures.append("Unexpected manifest schema")
    if validation.get("schemaVersion") != "integration-validation/v1":
        failures.append("Expected integration-validation/v1 report")
    for name in REQUIRED_GATES:
        gate = validation.get("checks", {}).get(name)
        if gate is not True and not (isinstance(gate, dict) and gate.get("status") == "passed"):
            failures.append(f"Validation gate not passed: {name}")
    for key in IDENTITY_KEYS:
        value = result.get("resultIdentity", {}).get(key)
        if not value or validation.get("resultIdentity", {}).get(key) != value:
            failures.append(f"Validation/result identity mismatch: {key}")
    if result.get("schemaVersion") != "integrated-factor/v1":
        failures.append("Unexpected integrated result schema")
    protected = validation.get("protectedHashes", {})
    if not protected:
        failures.append("Missing protectedHashes for workflows, user changes and integrated input")
    for path, expected in protected.items():
        p = Path(path)
        if not p.is_file() or p.is_symlink() or sha(p) != expected:
            failures.append(f"Protected file changed: {p}")
    inventory = []
    for row in manifest.get("files", []):
        p = Path(row["path"])
        if not p.is_absolute() or any(parent.is_symlink() for parent in [p, *p.parents]):
            failures.append(f"Noncanonical/symlink path: {p}")
            continue
        if ".git" in p.parts or "workflows" in p.parts or "LaunchAgents" in p.parts:
            failures.append(f"Protected path cannot be removed: {p}")
            continue
        if not p.is_file():
            failures.append(f"Missing or nonregular candidate: {p}")
            continue
        st = p.lstat()
        if (
            not stat.S_ISREG(st.st_mode)
            or st.st_size != row["size"]
            or st.st_ino != row["inode"]
            or st.st_mtime_ns != row["mtimeNs"]
            or sha(p) != row["sha256"]
        ):
            failures.append(f"Candidate identity changed: {p}")
            continue
        inventory.append({"path": str(p), "size": st.st_size, "sha256": row["sha256"]})
    for value in manifest.get("emptyDirectories", []):
        p = Path(value)
        if not p.is_dir() or p.is_symlink() or any(p.iterdir()):
            failures.append(f"Expected empty cache directory changed: {p}")
    if inventory:
        handles = subprocess.run(
            ["lsof", "-n", "-F", "pn", "--", *[row["path"] for row in inventory]],
            capture_output=True,
            text=True,
        )
        if handles.returncode == 0 and handles.stdout.strip():
            failures.append("Candidate files currently open: " + handles.stdout.strip())
        elif handles.returncode not in (0, 1):
            failures.append("Open-file preflight unavailable")
    processes = subprocess.run(
        ["ps", "-axo", "pid=,command="], capture_output=True, text=True, check=True
    ).stdout.splitlines()
    active = [
        line.strip()
        for line in processes
        if str(os.getpid()) != line.strip().split(" ", 1)[0]
        and (
            "-m best_factor" in line
            or "best-factor run " in line
            or "scripts/build_live_universe.py " in line
            or "scripts/refresh_dashboard_tickers.py " in line
        )
    ]
    if active:
        failures.append("Best worker or generator still active: " + "; ".join(active))
    return {
        "dryRun": True,
        "applySupported": False,
        "ready": not failures,
        "resultIdentity": result.get("resultIdentity"),
        "files": inventory,
        "logicalBytes": sum(row["size"] for row in inventory),
        "failures": failures,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "outputs/integration/cleanup-manifest.json",
    )
    parser.add_argument("--validation-report", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = check(
            json.loads(args.manifest.read_text()),
            json.loads(args.validation_report.read_text()),
            json.loads(args.result.read_text()),
        )
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(
            json.dumps(
                {"dryRun": True, "applySupported": False, "ready": False, "failures": [str(exc)]},
                ensure_ascii=False,
            )
        )
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    sys.exit(main())
