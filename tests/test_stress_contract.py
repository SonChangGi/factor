from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from factor_lab.workflow import AnalysisResult, result_payload


@pytest.fixture(scope="module")
def stress_module() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / "stress_large_scale.py"
    spec = importlib.util.spec_from_file_location("stress_large_scale_contract_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stress_recomputation_rejects_a_mutated_nonselected_current_metric(
    demo_result: AnalysisResult,
    stress_module: ModuleType,
) -> None:
    payload = result_payload(demo_result)
    row = next(item for item in payload["factorRanking"] if not item["selected"])
    row["current_target_effective_names"] += 100.0

    failures, _, checked = stress_module._recompute_all_current_portfolios(
        demo_result,
        payload,
    )

    assert checked == 64
    assert (
        "recomputed_current:"
        f"{row['policy_id']}:{row['factor']}:"
        "serialized_current_row_current_target_effective_names"
    ) in failures


def test_stress_payload_contract_rejects_a_same_length_mutated_guardrail_profile(
    demo_result: AnalysisResult,
    stress_module: ModuleType,
) -> None:
    payload = result_payload(demo_result)
    payload["factorSelectionDecision"]["guardrailProfile"]["rules"][0]["threshold"] += 1.0

    failures = stress_module._validate_payload_contract(
        payload,
        args=SimpleNamespace(symbols=demo_result.config.demo_symbol_count),
        config=demo_result.config,
    )

    assert "decision:absolute_guardrail_profile_exact" in failures
