"""CAS-publish only operational state onto the latest remote financial result."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from factor_lab.operational_status import RELATIVE_PATH, write_status  # noqa: E402


def wait_for_idle_pages(repository, branch, *, timeout=600):
    """Avoid advancing main while an existing exact-source Pages build uses it."""
    deadline = time.monotonic() + max(0, timeout)
    announced = False
    while True:
        body = subprocess.check_output(
            ["gh", "run", "list", "--repo", "SonChangGi/factor", "--workflow",
             "deploy-pages.yml", "--branch", branch, "--limit", "100", "--json", "status"],
            cwd=repository, text=True, timeout=30,
        )
        rows = json.loads(body)
        if not isinstance(rows, list) or any(not isinstance(row, dict) or "status" not in row for row in rows):
            raise ValueError("Cannot establish active Pages state; operational commit was not made")
        if all(row["status"] == "completed" for row in rows):
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Active Pages deployment did not finish; operational commit was not made")
        if not announced:
            print("Waiting for existing Pages publication before the operational-state commit.",
                  file=sys.stderr, flush=True)
            announced = True
        time.sleep(min(10, remaining))


def publish(repository, branch, *, status_directory=None, wait_for_pages=False, **attempt):
    repository = Path(repository).resolve()

    def git(*args, cwd=repository):
        return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()

    wait_deadline = time.monotonic() + 600
    for retry in range(3):
        if wait_for_pages:
            wait_for_idle_pages(repository, branch, timeout=max(0, wait_deadline - time.monotonic()))
        git("fetch", "origin", branch)
        source = git("rev-parse", "origin/" + branch)
        with tempfile.TemporaryDirectory(prefix="factor-status-") as temporary:
            checkout = Path(temporary) / "checkout"
            git("worktree", "add", "--detach", str(checkout), source)
            try:
                result = write_status(
                    checkout / "site", status_directory=status_directory, **attempt
                )
                if not result["changed"]:
                    return dict(should_deploy="false", source_sha=source)
                from factor_lab.publication_security import scan_publication_paths

                if scan_publication_paths([checkout / "site" / RELATIVE_PATH]):
                    raise ValueError("Operational state failed publication security")
                git("add", "--", "site/" + RELATIVE_PATH, cwd=checkout)
                if not git("diff", "--cached", "--name-only", cwd=checkout):
                    return dict(should_deploy="false", source_sha=source)
                changed = git("diff", "--cached", "--name-only", cwd=checkout).splitlines()
                if changed != ["site/" + RELATIVE_PATH]:
                    raise ValueError("Operational publication attempted to modify financial files")
                git("config", "user.name", "github-actions[bot]", cwd=checkout)
                git(
                    "config",
                    "user.email",
                    "41898282+github-actions[bot]@users.noreply.github.com",
                    cwd=checkout,
                )
                git(
                    "commit",
                    "-m",
                    "Record Factor refresh attempt " + str(attempt["run_id"]),
                    cwd=checkout,
                )
                commit = git("rev-parse", "HEAD", cwd=checkout)
                pushed = subprocess.run(
                    ["git", "push", "origin", "HEAD:" + branch],
                    cwd=checkout,
                    capture_output=True,
                    text=True,
                )
                if pushed.returncode == 0:
                    return dict(should_deploy="true", source_sha=commit)
                if retry == 2:
                    raise RuntimeError(
                        "Operational-state CAS publication failed; financial result was preserved"
                    )
            finally:
                git("worktree", "remove", "--force", str(checkout))
    raise RuntimeError("Operational publication did not finish")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--branch", default="main")
    parser.add_argument("--wait-for-pages", action="store_true")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", type=int, default=1)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument(
        "--outcome", choices=["success", "failure", "cancelled", "skipped"], required=True
    )
    parser.add_argument("--deployment-outcome", default="skipped")
    parser.add_argument("--target")
    parser.add_argument("--started-at")
    parser.add_argument("--finished-at")
    parser.add_argument("--status-directory", type=Path)
    args = vars(parser.parse_args())
    for field in ("target", "finished_at"):
        if args.get(field) == "":
            args[field] = None
    for key, value in publish(**args).items():
        print(f"{key}={value}")
