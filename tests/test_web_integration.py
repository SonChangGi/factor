from __future__ import annotations

import subprocess
import json
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def web_payload_path(demo_result, tmp_path_factory: pytest.TempPathFactory) -> Path:
    from factor_lab.workflow import result_payload

    path = tmp_path_factory.mktemp("web-contract") / "schema-v5.json"
    path.write_text(json.dumps(result_payload(demo_result)), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "script",
    [
        "scripts/test_web_contract.mjs",
        "scripts/test_web_dom_integration.mjs",
        "scripts/test_performance_table_dom.mjs",
        "scripts/test_chart_palette_dom.mjs",
        "scripts/test_original_design_contract.mjs",
        "scripts/test_common_design_v1_dom.mjs",
        "scripts/test_static_web_loader_contract.mjs",
        "scripts/test_web_local_api_dom_integration.mjs",
        "scripts/test_web_control_api_contract.mjs",
        "scripts/test_web_automation_status.mjs",
    ],
)
def test_node_web_contract_and_dom_integration(script: str, web_payload_path: Path) -> None:
    environment = {**os.environ, "MFL_TEST_PAYLOAD": str(web_payload_path)}
    completed = subprocess.run(
        ["node", script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        env=environment,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "PASS" in completed.stdout
