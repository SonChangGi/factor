from pathlib import Path



def test_pages_failure_cannot_be_hidden_by_existing_site_health():
    workflow = Path(".github/workflows/deploy-pages.yml").read_text()
    deployment_job = workflow.split("  deploy-pages:\n", 1)[1].split(
        "  public-site-health:\n", 1
    )[0]
    assert "continue-on-error:" not in deployment_job
    assert "Verify the complete public site byte-for-byte" in deployment_job
