import os
import subprocess
import textwrap
from pathlib import Path

import pytest


def test_pages_failure_cannot_be_hidden_by_existing_site_health():
    workflow = Path(".github/workflows/deploy-pages.yml").read_text()
    deployment_job = workflow.split("  deploy-pages:\n", 1)[1].split(
        "  public-site-health:\n", 1
    )[0]
    assert "continue-on-error:" not in deployment_job
    assert "Verify the complete public site byte-for-byte" in deployment_job


@pytest.mark.parametrize("override,expected", [
    ({}, 0),
    ({"UPDATE_RESULT": "failure"}, 1),
    ({"UPDATE_RESULT": "cancelled"}, 1),
    ({"SHOULD_DEPLOY": "false"}, 1),
    ({"DEPLOY_RESULT": "failure"}, 1),
    ({"DEPLOY_RESULT": "skipped"}, 1),
    ({"DEPLOY_RESULT": "cancelled"}, 1),
    ({"REFRESH_SKIPPED": "true", "DEPLOY_RESULT": "skipped"}, 0),
    ({"REFRESH_SKIPPED": "true", "UPDATE_RESULT": "failure"}, 1),
])
def test_workflow_never_treats_page_reachability_as_a_successful_refresh(override, expected):
    workflow = Path(".github/workflows/daily-dashboard.yml").read_text()
    final_job = workflow.split("  refresh-result:\n", 1)[1].split("  input-cache-diagnostics:\n", 1)[0]
    script = textwrap.dedent(final_job.split("        run: |\n", 1)[1])
    environment = {**os.environ, "UPDATE_RESULT": "success", "REFRESH_SKIPPED": "false",
                   "DEPLOY_RESULT": "success", "SHOULD_DEPLOY": "true", **override}
    result = subprocess.run(["bash", "-e", "-c", script], env=environment, capture_output=True)
    assert result.returncode == expected, result.stdout + result.stderr


def test_fresh_publication_skips_all_input_cache_resolution_and_restore():
    workflow = Path(".github/workflows/daily-dashboard.yml").read_text()
    update = workflow.split("  update-dashboard:\n", 1)[1].split("  deploy-pages:\n", 1)[0]
    for name in ("Resolve the explicitly requested immutable input cache",
                 "Resolve the previous verified primary input vintage"):
        step = update.split("      - name: " + name + "\n", 1)[1].split("      - name: ", 1)[0]
        assert "if: steps.freshness.outputs.skip != 'true'" in step
    # The actions cannot restore if their guarded resolver did not set enabled.
    for name, resolver in (("Restore the exact input cache without collection", "reuse"),
                           ("Restore previous primary input vintage for guarded history preservation", "archive")):
        step = update.split("      - name: " + name + "\n", 1)[1].split("      - name: ", 1)[0]
        assert f"if: steps.{resolver}.outputs.enabled == 'true'" in step


def test_financial_calculation_and_input_diagnostics_pin_the_runner_os():
    workflow = Path(".github/workflows/daily-dashboard.yml").read_text()
    for job in ("update-dashboard", "input-cache-diagnostics"):
        import re
        body = re.split(r"(?m)^  [a-z][a-z-]*:\s*$", workflow.split("  " + job + ":\n", 1)[1], maxsplit=1)[0]
        assert "    runs-on: ubuntu-24.04" in body
        assert "ubuntu-latest" not in body
