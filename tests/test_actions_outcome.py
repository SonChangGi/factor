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
    final_job = workflow.split("  refresh-result:\n", 1)[1]
    script = textwrap.dedent(final_job.split("        run: |\n", 1)[1])
    environment = {**os.environ, "UPDATE_RESULT": "success", "REFRESH_SKIPPED": "false",
                   "DEPLOY_RESULT": "success", "SHOULD_DEPLOY": "true", **override}
    result = subprocess.run(["bash", "-e", "-c", script], env=environment, capture_output=True)
    assert result.returncode == expected, result.stdout + result.stderr
