from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATHS = (
    "factor_lab/engine.py",
    ".github/factor-dashboard-config.json",
    "pyproject.toml",
    "uv.lock",
)


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _commit_script() -> str:
    workflow = (ROOT / ".github/workflows/daily-dashboard.yml").read_text(encoding="utf-8")
    block = workflow.split("      - name: Promote and commit only the validated Factor publication\n", 1)[1].split(
        "      - name: Record refresh result\n", 1)[0]
    script = textwrap.dedent(block.split("        run: |\n", 1)[1])
    return script.replace("${{ steps.freshness.outputs.target_data_as_of }}", "2026-10-19")


def _run_with_concurrent_change(
    tmp_path: Path, changed_path: str, race_at: str,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    remote = tmp_path / "remote.git"
    writer = tmp_path / "writer"
    runner = tmp_path / "runner"
    _git(tmp_path, "init", "--bare", "--initial-branch=main", str(remote))
    _git(tmp_path, "clone", str(remote), str(writer))
    _git(writer, "config", "user.name", "Fixture")
    _git(writer, "config", "user.email", "fixture@example.invalid")
    for relative in (*SOURCE_PATHS, "site/index.html", "README.md"):
        path = writer / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("baseline\n", encoding="utf-8")
    _git(writer, "add", ".")
    _git(writer, "commit", "-m", "baseline")
    _git(writer, "push", "origin", "main")
    _git(tmp_path, "clone", str(remote), str(runner))
    _git(runner, "config", "user.name", "Fixture")
    _git(runner, "config", "user.email", "fixture@example.invalid")
    (runner / "candidate.html").write_text("computed-candidate\n", encoding="utf-8")
    source_sha = _git(runner, "rev-parse", "HEAD")

    (writer / changed_path).write_text("concurrent change\n", encoding="utf-8")
    _git(writer, "add", changed_path)
    _git(writer, "commit", "-m", "concurrent source or documentation update")
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    # Publish the concurrent checkout at the first source fetch or final push.
    # Everything else executes the real workflow script and real git commands.
    hook = """
git() {
  if [[ "$1" == "$RACE_AT" && ! -e "$RACE_MARKER" ]]; then
    command git -C "$RACE_WRITER" push origin main || return
    touch "$RACE_MARKER"
  fi
  command git "$@"
}
python() {
  if [[ "$*" == *"integrated_automation promote"* ]]; then
    cp candidate.html site/index.html
  fi
  return 0
}
"""
    result = subprocess.run(
        ["bash", "-e", "-c", hook + _commit_script()],
        cwd=runner,
        env={
            **os.environ,
            "GITHUB_REF_NAME": "main",
            "RUNNER_TEMP": str(runner_temp),
            "SOURCE_SHA": source_sha,
            "DEFAULT_BRANCH": "main",
            "GITHUB_RUN_ID": "fixture",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_OUTPUT": str(tmp_path / "outputs"),
            "RACE_AT": race_at,
            "RACE_WRITER": str(writer),
            "RACE_MARKER": str(tmp_path / "race-fired"),
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert (tmp_path / "race-fired").exists(), result.stdout + result.stderr
    return result, remote


@pytest.mark.parametrize("changed_path", SOURCE_PATHS)
@pytest.mark.parametrize("race_at", ["fetch", "push"])
def test_computed_candidate_is_rejected_when_production_advances(
    tmp_path: Path, changed_path: str, race_at: str,
) -> None:
    result, remote = _run_with_concurrent_change(tmp_path, changed_path, race_at)

    assert result.returncode != 0, result.stdout + result.stderr
    if race_at == "fetch":
        assert "Source advanced during calculation" in result.stderr
    else:
        assert "rejected" in result.stderr
    assert _git(remote, "show", "main:site/index.html") == "baseline"
    assert _git(remote, "show", f"main:{changed_path}") == "concurrent change"


def test_unrelated_documentation_change_also_preserves_strict_source_binding(tmp_path: Path) -> None:
    result, remote = _run_with_concurrent_change(tmp_path, "README.md", "fetch")

    assert result.returncode != 0, result.stdout + result.stderr
    assert _git(remote, "show", "main:site/index.html") == "baseline"
    assert _git(remote, "show", "main:README.md") == "concurrent change"
