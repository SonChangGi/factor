from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from factor_lab.config import RunConfig
from factor_lab.control_run import (
    CONTROL_ARTIFACT_CONTRACT_VERSION,
    CONTROL_CONFIG_HASH_ALGORITHM,
    CONTROL_INPUT_KEYS,
    CONTROL_INPUT_SCHEMA,
    CONTROL_INPUT_SCHEMA_HASH,
    CONTROL_INPUT_SCHEMA_VERSION,
    PREVIOUS_CONTROL_INPUT_SCHEMA_HASH,
    PREVIOUS_CONTROL_INPUT_SCHEMA_VERSION,
    ControlBinding,
    ControlledRunError,
    control_config_hash,
    control_inputs_from_research_inputs,
    normalize_control_inputs,
    validate_control_binding,
    write_control_artifact,
)
from factor_lab.research_inputs import ResearchInputs
from factor_lab.workflow import AnalysisResult, result_payload


def _inputs(**changes: object) -> dict[str, object]:
    values = control_inputs_from_research_inputs(ResearchInputs())
    values.update(changes)
    return values


def _binding(inputs: dict[str, object], run_id: str = "momentum-run-0001") -> ControlBinding:
    return validate_control_binding(
        run_id=run_id,
        input_schema_version=CONTROL_INPUT_SCHEMA_VERSION,
        input_schema_hash=CONTROL_INPUT_SCHEMA_HASH,
        config_hash_algorithm=CONTROL_CONFIG_HASH_ALGORITHM,
        config_hash=control_config_hash(inputs),
        normalized_inputs=inputs,
        allow_fallback=False,
    )


def test_complete_26_input_object_round_trips_to_run_config(tmp_path: Path) -> None:
    raw = _inputs(
        rebalanceFrequency="QE",
        evaluationWindowDays=1_000,
        topN=25,
        maxWeight=0.09,
        transactionCostBps=6.0,
        slippageBps=7.0,
        minHistoryDays=300,
        minPrice=7.0,
        minAvgDollarVolume=6_000_000.0,
        minAvgVolume=100_000.0,
        liquidityLookbackDays=84,
        minLiquidityObservations=60,
        maxPriceMissingRatio=0.04,
        maxVolumeMissingRatio=0.08,
        maxExtremeDailyReturn=0.70,
        selectionMinSharpe=0.20,
        selectionMaxDrawdown=0.50,
        selectionMaxAnnualizedCostDrag=0.015,
        selectionMinEffectiveNames=12.0,
        selectionMaxTargetHhi=0.13,
        selectionMaxTargetWeight=0.12,
        selectionMaxAbsSecurityDayContribution=0.09,
        selectionMaxSecurityAbsoluteContributionShare=0.30,
        selectionMaxLeaveOneSecurityCagrDelta=0.20,
        selectionExtremeEventAction="penalize",
        selectionExtremeEventPenaltyPoints=15.0,
    )
    inputs, normalized = normalize_control_inputs(raw)
    config = inputs.apply(
        RunConfig(
            demo=True,
            output_dir=tmp_path / "output",
            site_dir=tmp_path / "site",
            cache_dir=tmp_path / "cache",
        )
    )

    assert tuple(normalized) == CONTROL_INPUT_KEYS
    assert len(normalized) == 26
    expected = {
        "rebalance_frequency": "QE",
        "evaluation_window_days": 1_000,
        "min_evaluation_observations": 748,
        "min_daily_risk_observations": 748,
        "top_n": 25,
        "max_weight": 0.09,
        "transaction_cost_bps": 6.0,
        "slippage_bps": 7.0,
        "min_history_days": 300,
        "min_price": 7.0,
        "min_avg_dollar_volume": 6_000_000.0,
        "min_avg_volume": 100_000.0,
        "liquidity_lookback_days": 84,
        "min_liquidity_observations": 60,
        "max_price_missing_ratio": 0.04,
        "max_volume_missing_ratio": 0.08,
        "max_extreme_daily_return": 0.70,
        "selection_min_sharpe": 0.20,
        "selection_max_drawdown": 0.50,
        "selection_max_annualized_cost_drag": 0.015,
        "selection_min_effective_names": 12.0,
        "selection_max_target_hhi": 0.13,
        "selection_max_target_weight": 0.12,
        "selection_max_abs_security_day_contribution": 0.09,
        "selection_max_security_absolute_contribution_share": 0.30,
        "selection_max_leave_one_security_cagr_delta": 0.20,
        "selection_extreme_event_action": "penalize",
        "selection_extreme_event_penalty_points": 15.0,
    }
    for field, expected_value in expected.items():
        observed = getattr(config, field)
        if isinstance(expected_value, float):
            assert observed == pytest.approx(expected_value), field
        else:
            assert observed == expected_value, field
    # Cross-repository handshake with the common control API Momentum adapter.
    assert (
        CONTROL_INPUT_SCHEMA_HASH
        == "7a135e791a3269486b540c9ab02ca712077558598cc08982ba57113cff816327"
    )
    assert tuple(field["key"] for field in CONTROL_INPUT_SCHEMA["fields"]) == CONTROL_INPUT_KEYS
    evaluation_window = next(
        field
        for field in CONTROL_INPUT_SCHEMA["fields"]
        if field["key"] == "evaluationWindowDays"
    )
    assert evaluation_window["minimum"] == 21
    assert CONTROL_INPUT_SCHEMA["derivedFields"] == {
        "minimumEvaluationObservations": (
            "min(evaluationWindowDays, max(252, evaluationWindowDays - 252))"
        )
    }


@pytest.mark.parametrize(
    ("evaluation_window_days", "minimum_observations"),
    [(21, 21), (126, 126), (252, 252)],
)
def test_short_control_windows_apply_and_bind_exactly(
    evaluation_window_days: int,
    minimum_observations: int,
) -> None:
    inputs, normalized = normalize_control_inputs(
        _inputs(evaluationWindowDays=evaluation_window_days)
    )
    config = inputs.apply(RunConfig(demo=True))
    binding = _binding(normalized)

    assert config.evaluation_window_days == evaluation_window_days
    assert config.min_evaluation_observations == minimum_observations
    assert config.min_daily_risk_observations == minimum_observations
    assert binding.input_schema_version == "momentum/v3"
    assert binding.input_schema_hash == CONTROL_INPUT_SCHEMA_HASH


def test_previous_v2_binding_remains_accepted_for_in_flight_runs() -> None:
    normalized = _inputs(evaluationWindowDays=252)
    binding = validate_control_binding(
        run_id="momentum-v2-run-0001",
        input_schema_version=PREVIOUS_CONTROL_INPUT_SCHEMA_VERSION,
        input_schema_hash=PREVIOUS_CONTROL_INPUT_SCHEMA_HASH,
        config_hash_algorithm=CONTROL_CONFIG_HASH_ALGORITHM,
        config_hash=control_config_hash(normalized),
        normalized_inputs=normalized,
        allow_fallback=False,
    )

    assert binding.input_schema_version == "momentum/v2"
    assert binding.input_schema_hash == PREVIOUS_CONTROL_INPUT_SCHEMA_HASH


def test_previous_v2_binding_preserves_its_252_day_minimum() -> None:
    normalized = _inputs(evaluationWindowDays=21)
    with pytest.raises(ControlledRunError, match="v2 evaluationWindowDays"):
        validate_control_binding(
            run_id="momentum-v2-run-0002",
            input_schema_version=PREVIOUS_CONTROL_INPUT_SCHEMA_VERSION,
            input_schema_hash=PREVIOUS_CONTROL_INPUT_SCHEMA_HASH,
            config_hash_algorithm=CONTROL_CONFIG_HASH_ALGORITHM,
            config_hash=control_config_hash(normalized),
            normalized_inputs=normalized,
            allow_fallback=False,
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.pop("topN"),
        lambda value: value.update({"nearestPreset": True}),
        lambda value: value.update({"evaluationYears": 3}),
        lambda value: value.update({"version": "research-inputs-v2"}),
    ],
)
def test_partial_derived_and_unknown_control_inputs_fail_closed(mutate) -> None:
    value = _inputs()
    mutate(value)
    with pytest.raises(ControlledRunError, match="exactly all 26 fields"):
        normalize_control_inputs(value)


def test_a_b_inputs_produce_distinct_authoritative_hashes() -> None:
    baseline = _inputs()
    changed = _inputs(topN=25)

    assert control_config_hash(baseline) != control_config_hash(changed)
    assert control_config_hash(baseline) == control_config_hash(deepcopy(baseline))


@pytest.mark.parametrize(
    ("public_field", "changed_value", "run_config_field"),
    [
        ("rebalanceFrequency", "W", "rebalance_frequency"),
        ("evaluationWindowDays", 1_000, "evaluation_window_days"),
        ("topN", 25, "top_n"),
        ("maxWeight", 0.09, "max_weight"),
        ("transactionCostBps", 6.0, "transaction_cost_bps"),
        ("slippageBps", 7.0, "slippage_bps"),
        ("minHistoryDays", 300, "min_history_days"),
        ("minPrice", 7.0, "min_price"),
        ("minAvgDollarVolume", 6_000_000.0, "min_avg_dollar_volume"),
        ("minAvgVolume", 100_000.0, "min_avg_volume"),
        ("liquidityLookbackDays", 84, "liquidity_lookback_days"),
        ("minLiquidityObservations", 50, "min_liquidity_observations"),
        ("maxPriceMissingRatio", 0.04, "max_price_missing_ratio"),
        ("maxVolumeMissingRatio", 0.08, "max_volume_missing_ratio"),
        ("maxExtremeDailyReturn", 0.70, "max_extreme_daily_return"),
        ("selectionMinSharpe", 0.20, "selection_min_sharpe"),
        ("selectionMaxDrawdown", 0.50, "selection_max_drawdown"),
        (
            "selectionMaxAnnualizedCostDrag",
            0.015,
            "selection_max_annualized_cost_drag",
        ),
        ("selectionMinEffectiveNames", 12.0, "selection_min_effective_names"),
        ("selectionMaxTargetHhi", 0.13, "selection_max_target_hhi"),
        ("selectionMaxTargetWeight", 0.12, "selection_max_target_weight"),
        (
            "selectionMaxAbsSecurityDayContribution",
            0.09,
            "selection_max_abs_security_day_contribution",
        ),
        (
            "selectionMaxSecurityAbsoluteContributionShare",
            0.30,
            "selection_max_security_absolute_contribution_share",
        ),
        (
            "selectionMaxLeaveOneSecurityCagrDelta",
            0.20,
            "selection_max_leave_one_security_cagr_delta",
        ),
        (
            "selectionExtremeEventAction",
            "penalize",
            "selection_extreme_event_action",
        ),
        (
            "selectionExtremeEventPenaltyPoints",
            15.0,
            "selection_extreme_event_penalty_points",
        ),
    ],
)
def test_each_control_input_changes_its_existing_python_run_config_field(
    public_field: str,
    changed_value: object,
    run_config_field: str,
    tmp_path: Path,
) -> None:
    baseline_raw = _inputs()
    changed_raw = _inputs(**{public_field: changed_value})
    baseline_inputs, baseline_normalized = normalize_control_inputs(baseline_raw)
    changed_inputs, changed_normalized = normalize_control_inputs(changed_raw)
    base = RunConfig(
        demo=True,
        output_dir=tmp_path / "output",
        site_dir=tmp_path / "site",
        cache_dir=tmp_path / "cache",
    )

    baseline_config = baseline_inputs.apply(base)
    changed_config = changed_inputs.apply(base)

    assert tuple(baseline_normalized) == tuple(changed_normalized) == CONTROL_INPUT_KEYS
    assert control_config_hash(baseline_normalized) != control_config_hash(
        changed_normalized
    )
    assert getattr(baseline_config, run_config_field) != getattr(
        changed_config,
        run_config_field,
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("run_id", "../unsafe", "run id"),
        ("input_schema_version", "momentum/v1", "schema mismatch"),
        ("input_schema_hash", "a" * 64, "schema hash"),
        ("config_hash_algorithm", "json-stringify-v1", "algorithm"),
        ("config_hash", "a" * 64, "reproduce config hash"),
        ("allow_fallback", True, "allowFallback=false"),
    ],
)
def test_control_binding_rejects_every_mismatch(
    field: str,
    value: object,
    message: str,
) -> None:
    inputs = _inputs()
    kwargs: dict[str, object] = {
        "run_id": "momentum-run-0001",
        "input_schema_version": CONTROL_INPUT_SCHEMA_VERSION,
        "input_schema_hash": CONTROL_INPUT_SCHEMA_HASH,
        "config_hash_algorithm": CONTROL_CONFIG_HASH_ALGORITHM,
        "config_hash": control_config_hash(inputs),
        "normalized_inputs": inputs,
        "allow_fallback": False,
    }
    kwargs[field] = value
    with pytest.raises(ControlledRunError, match=message):
        validate_control_binding(**kwargs)


def test_exact_artifact_bytes_and_result_manifest_are_bound(
    demo_result: AnalysisResult,
    tmp_path: Path,
) -> None:
    payload = result_payload(demo_result)
    inputs = control_inputs_from_research_inputs(
        ResearchInputs.from_config(demo_result.config)
    )
    binding = _binding(inputs)

    receipt = write_control_artifact(
        payload=payload,
        normalized_inputs=inputs,
        binding=binding,
        code_version="git:12345678",
        site_dir=tmp_path / "site",
        manifest_path=tmp_path / "output" / "result-manifest.json",
    )

    artifact_path = Path(receipt["artifactPath"])
    manifest = receipt["manifest"]
    artifact = manifest["artifact"]
    artifact_bytes = artifact_path.read_bytes()
    assert artifact["sha256"] == hashlib.sha256(artifact_bytes).hexdigest()
    assert artifact["byteSize"] == len(artifact_bytes)
    assert artifact["contractVersion"] == CONTROL_ARTIFACT_CONTRACT_VERSION
    assert f"/{binding.run_id}/{payload['resultKey']}.json" in artifact["url"]
    assert manifest["binding"] == binding.to_dict()
    assert manifest["requestedInputs"] == inputs
    assert manifest["normalizedInputs"] == inputs
    assert manifest["effectiveInputs"] == inputs
    assert manifest["effectiveConfigHash"] == binding.config_hash
    assert manifest["ignoredInputs"] == []
    assert manifest["fallbacks"] == []
    assert manifest["fallbackUsed"] is False
    assert manifest["fallbackReason"] is None
    assert manifest["codeVersion"] == "git:12345678"
    assert set(manifest["payload"]) == {
        "schemaVersion",
        "resultKey",
        "resultIdentity",
        "researchInputs",
        "bestFactor",
        "weightingPolicy",
        "dataIdentity",
        "selectedSecurityCount",
        "holdings",
    }
    assert len(
        json.dumps(
            manifest["payload"],
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ) <= 64 * 1024
    assert Path(receipt["sidecarPath"]).is_file()
    assert Path(receipt["manifestPath"]).is_file()


def test_artifact_rejects_result_for_a_different_input(
    demo_result: AnalysisResult,
    tmp_path: Path,
) -> None:
    payload = result_payload(demo_result)
    requested = _inputs(topN=25)
    with pytest.raises(ControlledRunError, match="researchInputs"):
        write_control_artifact(
            payload=payload,
            normalized_inputs=requested,
            binding=_binding(requested),
            code_version="git:12345678",
            site_dir=tmp_path / "site",
            manifest_path=tmp_path / "result-manifest.json",
        )


def test_workflow_is_thin_external_worker_with_callback() -> None:
    workflow = Path(".github/workflows/controlled-analysis.yml").read_text(encoding="utf-8")
    assert "python -m factor_lab.control_run" in workflow
    assert "research_inputs_json:" in workflow
    assert "control_input_schema_version:" in workflow
    assert "control_input_schema_hash:" in workflow
    assert "control_config_hash_algorithm:" in workflow
    assert "control_config_hash:" in workflow
    assert "--allow-fallback" in workflow
    assert "data/control-runs/v1" not in workflow
    assert "result-manifest" in workflow
    assert "QUANT_CONTROL_WORKER_CALLBACK_TOKEN" in workflow
    assert "timeout-minutes: 210" in workflow
    assert '--code-version "github:${GITHUB_REPOSITORY}@${ANALYSIS_SHA}"' in workflow
    assert "always() && failure()" in workflow
    assert '/v1/internal/runs/${CONTROL_RUN_ID}/failure' in workflow
    assert '"projectId": "momentum"' in workflow
    assert '"providerRunId": f"github-actions:{run_id}"' in workflow
    assert '"errorCode": "worker_workflow_failed"' in workflow
    assert '"occurredAt": datetime.now(timezone.utc)' in workflow
    assert workflow.count("from urllib.parse import urlsplit, urlunsplit") == 2
    assert workflow.count("--proto '=https'") == 2
    assert workflow.count("or parsed.username") == 1
    assert workflow.count("or parsed_callback_base.username") == 1
    assert workflow.count("or parsed.query") == 1
    assert workflow.count("or parsed_callback_base.query") == 1
    assert "Reject secrets in immutable controlled result" in workflow
    assert "factor_lab.publication_security" in workflow
    assert '"${ARTIFACT_PATH}"' in workflow
    assert '"${SIDECAR_PATH}"' in workflow
    assert workflow.index("factor_lab.publication_security") < workflow.index(
        'git add -- "${ARTIFACT_PATH}" "${SIDECAR_PATH}"'
    )
    assert "run_analysis" not in workflow
