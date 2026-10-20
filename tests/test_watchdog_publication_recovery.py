from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA = "a" * 40


def _recovery_script() -> str:
    workflow = (ROOT / ".github/workflows/daily-dashboard-watchdog.yml").read_text(
        encoding="utf-8"
    )
    block = workflow.split(
        "      - name: Recover publication when repository data is already fresh\n", 1
    )[1].split("  public-site-health:\n", 1)[0]
    assert "if: steps.freshness.outputs.skip == 'true'" in block
    return textwrap.dedent(block.split("        run: |\n", 1)[1])


def _run_recovery(
    tmp_path: Path,
    *,
    matching: bool = False,
    watch_exit: int = 0,
    repair_content: bool = True,
    origin_sha: str = SOURCE_SHA,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    docs = tmp_path / "docs"
    for relative, content in {
        "index.html": "<!doctype html><title>Momentum</title>",
        "data/dashboard.json": '{"data":{"asOf":"2026-09-17"}}',
        "data/grid/v1/manifest.json": '{"entries":[]}',
        "data/grid/v1/details/immutable.json": '{"detail":"current"}',
    }.items():
        target = docs / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    public = tmp_path / "public"
    shutil.copytree(docs, public)
    if not matching:
        # Detect stale detail even when the index and headline dates match.
        (public / "data/grid/v1/details/immutable.json").write_text(
            '{"detail":"old"}', encoding="utf-8"
        )
    calls = tmp_path / "calls.log"
    mocks = """
timeout() { shift; "$@"; }
sleep() { :; }
git() {
  case "$1 $2" in
    'rev-parse HEAD') printf '%s\\n' "$SOURCE_SHA" ;;
    'rev-parse origin/main') printf '%s\\n' "$ORIGIN_SHA" ;;
    'fetch origin') return 0 ;;
    *) echo "Unexpected git command: $*" >&2; return 99 ;;
  esac
}
curl() {
  local url='' output='' relative
  while (( $# )); do
    case "$1" in
      --output) output="$2"; shift 2 ;;
      https://*) url="$1"; shift ;;
      *) shift ;;
    esac
  done
  relative="${url#${PAGE_URL%/}/}"
  relative="${relative%%\\?*}"
  printf 'curl %s\\n' "$url" >> "$CALLS_LOG"
  cp "$PUBLIC_DIR/$relative" "$output"
}
gh() {
  printf 'gh %s\\n' "$*" >> "$CALLS_LOG"
  case "$1 $2" in
    'workflow run') return 0 ;;
    'run list') printf '123456\\n' ;;
    'run watch')
      (( WATCH_EXIT == 0 )) || return "$WATCH_EXIT"
      if [[ "$REPAIR_CONTENT" == true ]]; then cp -R docs/. "$PUBLIC_DIR/"; fi
      ;;
    *) echo "Unexpected gh command: $*" >&2; return 99 ;;
  esac
}
"""
    result = subprocess.run(
        ["bash", "-e", "-c", mocks + _recovery_script()],
        cwd=tmp_path,
        env={
            **os.environ,
            "SOURCE_SHA": SOURCE_SHA,
            "ORIGIN_SHA": origin_sha,
            "DEFAULT_BRANCH": "main",
            "GITHUB_REPOSITORY": "fixture/momentum-factor-lab",
            "GITHUB_RUN_ID": "456",
            "GITHUB_RUN_ATTEMPT": "1",
            "PAGE_URL": "https://example.invalid/momentum-factor-lab/",
            "PUBLIC_DIR": str(public),
            "CALLS_LOG": str(calls),
            "WATCH_EXIT": str(watch_exit),
            "REPAIR_CONTENT": "true" if repair_content else "false",
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    recorded = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
    return result, recorded


def test_matching_publication_checks_all_files_without_dispatch(tmp_path: Path) -> None:
    result, calls = _run_recovery(tmp_path, matching=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert len([call for call in calls if call.startswith("curl ")]) == 4
    assert not any(call.startswith("gh ") for call in calls)


def test_stale_public_detail_dispatches_only_pages_and_verifies_recovery(tmp_path: Path) -> None:
    result, calls = _run_recovery(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    dispatches = [call for call in calls if call.startswith("gh workflow run ")]
    assert len(dispatches) == 1
    assert "deploy-pages.yml" in dispatches[0]
    assert f"expected_source_sha={SOURCE_SHA}" in dispatches[0]
    assert "request_origin=daily-dashboard-watchdog" in dispatches[0]
    assert not any("daily-dashboard.yml" in call for call in calls)
    assert any("gh run watch 123456" in call and "--exit-status" in call for call in calls)
    assert "Recovered and verified" in result.stdout
    detail_reads = [call for call in calls if "details/immutable.json?" in call]
    assert len(detail_reads) == 2
    assert detail_reads[0] != detail_reads[1], "Recovery must bypass the initial stale CDN response"


@pytest.mark.parametrize("watch_exit,repair_content", [(1, True), (0, False)])
def test_failed_pages_or_failed_readback_cannot_report_recovery(
    tmp_path: Path,
    watch_exit: int,
    repair_content: bool,
) -> None:
    result, calls = _run_recovery(
        tmp_path, watch_exit=watch_exit, repair_content=repair_content
    )

    assert result.returncode != 0, result.stdout + result.stderr
    assert any("gh run watch 123456" in call for call in calls)
    assert "Recovered and verified" not in result.stdout


def test_advanced_production_head_cannot_deploy_the_old_checkout(tmp_path: Path) -> None:
    result, calls = _run_recovery(tmp_path, origin_sha="b" * 40)

    assert result.returncode != 0, result.stdout + result.stderr
    assert "Production advanced" in result.stderr
    assert not any(call.startswith("gh ") for call in calls)


def test_stale_repository_still_requests_the_collector() -> None:
    workflow = (ROOT / ".github/workflows/daily-dashboard-watchdog.yml").read_text(
        encoding="utf-8"
    )
    block = workflow.split("      - name: Dispatch daily dashboard workflow\n", 1)[1].split(
        "      - name: Recover publication", 1
    )[0]
    assert "if: steps.freshness.outputs.skip != 'true'" in block
    assert "gh workflow run daily-dashboard.yml" in block
    assert "watchdog_origin=true" in block


@pytest.mark.parametrize('active,expected_dispatch', [('1', False), ('0', True)])
def test_watchdog_does_not_duplicate_an_active_collection(tmp_path, active, expected_dispatch):
    workflow = (ROOT / '.github/workflows/daily-dashboard-watchdog.yml').read_text()
    block = workflow.split('      - name: Dispatch daily dashboard workflow\n', 1)[1].split(
        '      - name: Recover publication', 1)[0]
    script = textwrap.dedent(block.split('        run: |\n', 1)[1])
    for key in ('reason', 'latest_data_as_of', 'target_data_as_of'):
        script = script.replace('${{ steps.freshness.outputs.' + key + ' }}', 'stale')
    mock = '''gh() {
      if [[ "$1 $2" == 'run list' ]]; then printf '%s\\n' "$ACTIVE";
      elif [[ "$1 $2" == 'workflow run' ]]; then echo DISPATCH;
      else return 99; fi
    }
    '''
    result = subprocess.run(['bash', '-c', mock + script], capture_output=True, text=True,
        env={**os.environ, 'ACTIVE': active, 'GITHUB_REPOSITORY': 'SonChangGi/factor',
             'DEFAULT_BRANCH': 'main'})
    assert result.returncode == 0, result.stderr
    assert ('DISPATCH' in result.stdout) is expected_dispatch
