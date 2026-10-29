"""CAS-publish only operational state onto the latest remote financial result."""

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from factor_lab.operational_status import RELATIVE_PATH, write_status  # noqa: E402


def publish(repository, branch, *, status_directory=None, **attempt):
    repository = Path(repository).resolve()

    def git(*args, cwd=repository):
        return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()

    for retry in range(3):
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
