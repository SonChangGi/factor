import json
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from factor_lab import workflow as workflow_module
from factor_lab.advanced_factors import ADVANCED_FACTOR_NAMES, AdvancedFactorResult
from factor_lab.config import (
    FIXED_WEIGHTING_POLICY,
    POLICY_REGISTRY,
    RunConfig,
    WEIGHTING_POLICIES,
)
from factor_lab.portfolio import construct_target_allocation
from factor_lab.workflow import (
    NoEligibleFactorError,
    AnalysisResult,
    _apply_factor_guardrails,
    _policy_grid_reasons,
    run_analysis,
)


def test_factor_catalog_is_evaluated_once_under_one_fixed_method(
    demo_result: AnalysisResult,
) -> None:
    definitions = demo_result.factor_definitions.set_index("factor")
    ranking = demo_result.factor_ranking
    aliases = definitions["compatibility_alias_of"].dropna()

    assert len(demo_result.factor_scores) == 64
    assert len(definitions) == 64
    assert int(definitions["selection_eligible"].fillna(True).astype(bool).sum()) == 61
    assert len(aliases) == 3
    assert set(aliases.index) == {
        "acceleration",
        "relative_strength_6m",
        "short_acceleration",
    }
    assert len(ranking) == 64
    assert ranking["policy_id"].eq(FIXED_WEIGHTING_POLICY).all()
    assert not ranking.duplicated("factor").any()
    alias_rows = ranking[ranking["factor"].isin(aliases.index)]
    assert alias_rows["comparison_status"].eq("duplicate_alias").all()
    assert alias_rows["comparison_eligible"].eq(False).all()
    assert alias_rows["composite_score"].isna().all()

    accounting = demo_result.grid_accounting
    assert accounting["independentFactorCount"] == 61
    assert accounting["expectedIndependentFactorCount"] == 61
    assert accounting["evaluatedIndependentFactorCount"] == 61
    assert (
        accounting["availableIndependentFactorCount"] + accounting["excludedIndependentFactorCount"]
        == accounting["expectedIndependentFactorCount"]
    )
    assert accounting["missingIndependentFactorCount"] == 0
    assert accounting["diagnosticAliasFactorCount"] == 3


def test_factor_selection_scores_each_available_factor_once(
    demo_result: AnalysisResult,
) -> None:
    ranking = demo_result.factor_ranking
    available = ranking.loc[ranking["comparison_status"].eq("available")]
    selected = ranking.loc[ranking["selected"]]

    assert len(selected) == 1
    assert selected.iloc[0]["factor"] == demo_result.selected_factor
    assert selected.iloc[0]["policy_id"] == FIXED_WEIGHTING_POLICY
    assert int(selected.iloc[0]["rank"]) == 1
    assert available["composite_score"].between(0.0, 100.0).all()
    assert demo_result.factor_selection_decision["method"] == "fixed_policy_factor_selection"
    assert demo_result.factor_selection_decision["weightingPolicyOptimized"] is False
    assert demo_result.policy_selection_decision["fixed"] is True
    assert demo_result.policy_selection_decision["optimized"] is False

    row = selected.iloc[0]
    expected = sum(
        row[f"{metric}_score"] * weight
        for metric, weight in demo_result.config.score_weights.items()
    )
    assert np.isfinite(expected)
    assert row["base_composite_score"] == pytest.approx(expected)
    assert row["selection_score"] == pytest.approx(
        row["base_composite_score"] - row["extreme_event_penalty_points"]
    )


def test_fixed_policy_cannot_be_changed_by_factor_selection(
    demo_result: AnalysisResult,
) -> None:
    ranking = demo_result.factor_ranking.copy()
    target_index = ranking.index[ranking["comparison_status"].eq("available")][0]
    ranking.loc[:, "composite_score"] = 1.0
    ranking.loc[target_index, "composite_score"] = 100.0

    _, selected_factor, selected_policy, _, decision = _apply_factor_guardrails(
        ranking,
        demo_result.config,
    )

    assert selected_factor == ranking.loc[target_index, "factor"]
    assert selected_policy == FIXED_WEIGHTING_POLICY
    assert decision["weightingPolicy"] == FIXED_WEIGHTING_POLICY
    assert decision["weightingPolicyOptimized"] is False


def test_absolute_concentration_guardrails_use_history_and_current_target(
    demo_result: AnalysisResult,
) -> None:
    ranking = demo_result.factor_ranking.copy()
    source = ranking.loc[ranking["selected"]].iloc[0]
    mask = ranking["factor"].eq(source["factor"])
    boundary_values = {
        "min_target_effective_names": demo_result.config.selection_min_effective_names,
        "current_target_effective_names": demo_result.config.selection_min_effective_names,
        "max_target_hhi": demo_result.config.selection_max_target_hhi,
        "current_target_hhi": demo_result.config.selection_max_target_hhi,
        "max_target_weight": demo_result.config.selection_max_target_weight,
        "current_target_max_weight": demo_result.config.selection_max_target_weight,
    }
    for field, value in boundary_values.items():
        ranking.loc[mask, field] = value

    boundary, *_ = _apply_factor_guardrails(ranking, demo_result.config)
    boundary_row = boundary.loc[boundary["factor"].eq(source["factor"])].iloc[0]
    for field in (
        "guardrail_historical_effective_names",
        "guardrail_current_effective_names",
        "guardrail_historical_target_hhi",
        "guardrail_current_target_hhi",
        "guardrail_historical_target_weight",
        "guardrail_current_target_weight",
    ):
        assert bool(boundary_row[field])

    failures = {
        "min_target_effective_names": (
            demo_result.config.selection_min_effective_names - 0.01,
            "guardrail_historical_effective_names",
        ),
        "current_target_effective_names": (
            demo_result.config.selection_min_effective_names - 0.01,
            "guardrail_current_effective_names",
        ),
        "max_target_hhi": (
            demo_result.config.selection_max_target_hhi + 0.01,
            "guardrail_historical_target_hhi",
        ),
        "current_target_hhi": (
            demo_result.config.selection_max_target_hhi + 0.01,
            "guardrail_current_target_hhi",
        ),
        "max_target_weight": (
            demo_result.config.selection_max_target_weight + 0.01,
            "guardrail_historical_target_weight",
        ),
        "current_target_max_weight": (
            demo_result.config.selection_max_target_weight + 0.01,
            "guardrail_current_target_weight",
        ),
    }
    for metric, (value, guardrail) in failures.items():
        changed = ranking.copy()
        changed.loc[mask, metric] = value
        guarded, *_ = _apply_factor_guardrails(changed, demo_result.config)
        row = guarded.loc[guarded["factor"].eq(source["factor"])].iloc[0]
        assert not bool(row[guardrail])
        assert not bool(row["selection_eligible"])
        assert row["selection_status"] == "absolute_guardrail_excluded"


@pytest.mark.parametrize(
    ("action", "expected_status", "expected_eligible", "expected_penalty"),
    [
        ("warn", "extreme_event_warning", True, 0.0),
        ("penalize", "extreme_event_penalized", True, 20.0),
        ("exclude", "extreme_event_excluded", False, 0.0),
    ],
)
def test_extreme_event_actions_apply_one_absolute_threshold(
    demo_result: AnalysisResult,
    action: str,
    expected_status: str,
    expected_eligible: bool,
    expected_penalty: float,
) -> None:
    ranking = demo_result.factor_ranking.copy()
    source = ranking.loc[ranking["selected"]].iloc[0]
    observed = float(source["max_abs_security_day_contribution"])
    assert observed > 0.0
    threshold = observed / 2.0
    ranking["max_abs_security_day_contribution"] = threshold
    ranking.loc[
        ranking["factor"].eq(source["factor"]),
        "max_abs_security_day_contribution",
    ] = observed
    config = replace(
        demo_result.config,
        selection_max_abs_security_day_contribution=threshold,
        selection_extreme_event_action=action,
        selection_extreme_event_penalty_points=20.0,
    )

    guarded, *_ = _apply_factor_guardrails(ranking, config)
    row = guarded.loc[guarded["factor"].eq(source["factor"])].iloc[0]

    assert row["selection_status"] == expected_status
    assert bool(row["selection_eligible"]) is expected_eligible
    assert row["extreme_event_penalty_points"] == pytest.approx(expected_penalty)
    assert row["contribution_guardrail_breaches"] == ["security_day_contribution"]


def test_missing_factor_execution_is_an_implementation_error(
    demo_result: AnalysisResult,
) -> None:
    all_backtests = {FIXED_WEIGHTING_POLICY: dict(demo_result.backtests)}
    missing_factor = next(iter(demo_result.backtests))
    del all_backtests[FIXED_WEIGHTING_POLICY][missing_factor]
    evaluation_index = pd.DatetimeIndex(
        demo_result.backtests[missing_factor].returns.index[
            -demo_result.config.evaluation_window_days :
        ]
    )
    with pytest.raises(ValueError, match="implementation_error_missing_factor_policy_pairs"):
        _policy_grid_reasons(
            all_backtests,
            evaluation_index,
            expected_factors=demo_result.backtests,
        )


def test_unknown_fixed_method_input_reason_is_an_implementation_error() -> None:
    dates = pd.bdate_range("2026-01-02", periods=3)
    statuses = pd.Series(["not_scheduled", "unavailable", "not_scheduled"], index=dates)
    reasons = pd.Series([(), ("weight_invariant_failed",), ()], index=dates)
    all_backtests = {
        FIXED_WEIGHTING_POLICY: {
            "factor_x": SimpleNamespace(
                policy_input_statuses=statuses,
                policy_input_reasons=reasons,
            )
        }
    }

    with pytest.raises(ValueError, match="implementation_error_policy_input_reason"):
        _policy_grid_reasons(all_backtests, dates, expected_factors=["factor_x"])


def test_fixed_policy_diagnostic_is_not_an_optimization_table(
    demo_result: AnalysisResult,
) -> None:
    diagnostics = demo_result.policy_comparison
    assert len(diagnostics) == 1
    assert diagnostics.iloc[0]["policy_id"] == FIXED_WEIGHTING_POLICY
    assert diagnostics.iloc[0]["diagnostic_only"]
    assert "selected" not in diagnostics
    assert "rank" not in diagnostics


def test_weighting_policy_registry_exposes_exact_fixed_formula() -> None:
    assert WEIGHTING_POLICIES == (FIXED_WEIGHTING_POLICY,)
    assert set(POLICY_REGISTRY) == {FIXED_WEIGHTING_POLICY}
    method = POLICY_REGISTRY[FIXED_WEIGHTING_POLICY]
    assert method["selectionRole"] == "fixed_methodology_not_optimized"
    assert method["formula"] == ("floor+0.70*factor_score_pct+0.30*lagged_raw_dollar_volume_pct")
    assert "point_in_time_market_cap" not in method["requiredSignalDateInputs"]


def test_fixed_method_missing_required_liquidity_fails_closed_to_cash() -> None:
    symbols = pd.Index(["AAA", "BBB", "CCC"])
    allocation = construct_target_allocation(
        FIXED_WEIGHTING_POLICY,
        pd.Timestamp("2026-07-10"),
        pd.Series([3.0, 2.0, 1.0], index=symbols),
        pd.Series([30.0, 20.0, 10.0], index=symbols),
        pd.Series(True, index=symbols),
        RunConfig(demo=True, top_n=3, max_weight=0.50),
        trailing_dollar_volume=None,
        trailing_market_cap=None,
    )

    assert allocation.status == "unavailable"
    assert allocation.reasons == ["no_finite_trailing_dollar_volume"]
    assert allocation.rows.empty
    assert allocation.cash_weight == pytest.approx(1.0)


def test_factor_selection_fails_closed_when_every_factor_breaks_guardrails(
    demo_result: AnalysisResult,
) -> None:
    ranking = demo_result.factor_ranking.copy()
    ranking["execution_coverage_ratio"] = 0.0
    ranking["blocked_execution_count"] = 1
    ranking["total_unpriceable_target_count"] = 1
    with pytest.raises(NoEligibleFactorError, match="no factor passes") as exc_info:
        _apply_factor_guardrails(ranking, demo_result.config)
    error = exc_info.value
    comparable_count = int(ranking["comparison_status"].eq("available").sum())
    assert error.evaluated_factor_count == len(ranking)
    assert error.comparable_factor_count == comparable_count
    assert error.guardrail_breach_counts["execution"] == comparable_count
    assert error.selection_status_counts["absolute_guardrail_excluded"] == comparable_count
    assert len(error.factor_details) == len(ranking)


def test_no_comparable_factor_preserves_data_exclusion_diagnostics(
    demo_result: AnalysisResult,
) -> None:
    selected = demo_result.factor_ranking.loc[demo_result.factor_ranking["selected"]]
    ranking = pd.concat([selected] * 3, ignore_index=True)
    ranking["factor"] = ["execution_shortage", "history_shortage", "diagnostic_alias"]
    ranking["comparison_status"] = [
        "incomplete_execution_coverage",
        "insufficient_history",
        "duplicate_alias",
    ]
    ranking.at[0, "execution_coverage_ratio"] = 0.5
    ranking.at[0, "blocked_execution_count"] = 2
    ranking.at[0, "total_unpriceable_target_count"] = 4
    ranking.at[1, "ending_nav_available"] = True
    ranking.at[1, "observations"] = 0
    ranking.at[1, "daily_risk_observations"] = np.nan
    ranking.at[2, "comparison_reason"] = "duplicate_alias_of:history_shortage"
    ranking = workflow_module._with_exclusion_accounting(ranking, demo_result.config)

    with pytest.raises(NoEligibleFactorError) as exc_info:
        _apply_factor_guardrails(ranking, demo_result.config)

    error = exc_info.value
    assert error.evaluated_factor_count == 3
    assert error.comparable_factor_count == 0
    assert error.comparison_status_counts == {
        "duplicate_alias": 1,
        "incomplete_execution_coverage": 1,
        "insufficient_history": 1,
    }
    assert error.exclusion_reason_counts == {
        "duplicate_alias": 1,
        "incomplete_execution_coverage": 1,
        "insufficient_observations": 1,
    }
    assert error.selection_status_counts == {"data_excluded": 3}
    # Missing inputs are not counted as failed absolute selection thresholds.
    assert error.guardrail_breach_counts == {}
    rows = {row["factor"]: row for row in error.factor_details}
    execution_reason = rows["execution_shortage"]["exclusion_reasons"][0]
    assert execution_reason == {
        "code": "incomplete_execution_coverage",
        "coverage": 0.5,
        "blockedExecutions": 2.0,
        "unpriceableTargets": 4.0,
    }
    history_reason = rows["history_shortage"]["exclusion_reasons"][0]
    assert history_reason["required"] == demo_result.config.min_evaluation_observations
    assert history_reason["observed"] == 0
    assert rows["history_shortage"]["daily_risk_observations"] is None
    assert json.loads(json.dumps(error.factor_details, allow_nan=False)) == error.factor_details


def test_unavailable_advanced_factors_remain_in_single_fixed_method_catalog(
    demo_result: AnalysisResult,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = workflow_module.compute_advanced_factor_scores

    def force_both_advanced_factors_unavailable(*args, **kwargs) -> AdvancedFactorResult:
        computed = original(*args, **kwargs)
        scores = {factor: panel.copy() for factor, panel in computed.scores.items()}
        status = computed.status.copy()
        for factor in ADVANCED_FACTOR_NAMES:
            scores[factor].iloc[-1, :] = np.nan
            mask = status["factor"].eq(factor)
            status.loc[mask, "available"] = False
            status.loc[mask, "latestFiniteCount"] = 0
            status.loc[mask, "reasonCode"] = "forced_distinct_advanced_input_shortage"
            status.loc[mask, "detail"] = f"forced unavailable fixture for {factor}"
        return AdvancedFactorResult(scores=scores, status=status)

    monkeypatch.setattr(
        workflow_module,
        "compute_advanced_factor_scores",
        force_both_advanced_factors_unavailable,
    )
    result = run_analysis(demo_result.config, market_data=demo_result.market_data)
    rows = result.factor_ranking[result.factor_ranking["factor"].isin(ADVANCED_FACTOR_NAMES)]

    assert len(result.factor_scores) == 64
    assert len(result.factor_ranking) == 64
    assert result.grid_accounting["expectedIndependentFactorCount"] == 61
    assert result.grid_accounting["missingIndependentFactorCount"] == 0
    assert len(rows) == len(ADVANCED_FACTOR_NAMES)
    assert rows["comparison_status"].eq("factor_input_unavailable").all()
    assert rows["comparison_eligible"].eq(False).all()
    assert (
        rows["exclusion_reason_codes"]
        .map(lambda codes: list(codes) == ["factor_input_unavailable"])
        .all()
    )
    assert set(rows["factor"]) == set(ADVANCED_FACTOR_NAMES)
    assert result.grid_accounting["exclusionReasonCounts"]["factor_input_unavailable"] == 2
