import math

import pandas as pd
import pytest

from factor_lab.metrics import (
    cagr,
    calmar_ratio,
    composite_factor_scorecard,
    downside_deviation,
    evaluation_metrics,
    mark_to_last_observed_returns,
    max_drawdown,
    metric_summary,
    sharpe_ratio,
    sortino_ratio,
    subperiod_stability,
)


def _score_row(factor: str, **changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "factor": factor,
        "observations": 756,
        "risk_metrics_complete": True,
        "valuation_coverage_ratio": 1.0,
        "daily_risk_observations": 756,
        "policy_input_coverage_ratio": 1.0,
        "execution_coverage_ratio": 1.0,
        "sortino": 1.0,
        "calmar": 1.0,
        "max_drawdown": -0.10,
        "cagr": 0.10,
        "sharpe": 1.0,
        "stability": 0.10,
        "annualized_turnover": 1.0,
        "comparison_eligible": True,
        "comparison_ineligible_status": None,
    }
    row.update(changes)
    return row


def test_max_drawdown_known_path() -> None:
    returns = pd.Series([0.10, -0.10, -0.20, 0.05])
    assert round(max_drawdown(returns), 4) == -0.28


def test_ratios_handle_flat_returns() -> None:
    flat = pd.Series([0.0] * 20)
    assert sharpe_ratio(flat) == 0.0
    assert sortino_ratio(flat) == 0.0
    assert calmar_ratio(flat) == 0.0


def test_sortino_positive_no_downside_is_infinite() -> None:
    positive = pd.Series([0.001] * 20)
    assert math.isinf(sortino_ratio(positive))


def test_downside_deviation_uses_all_observations_against_target() -> None:
    returns = pd.Series([-0.10, -0.05, 0.10, 0.10])
    expected = math.sqrt((0.10**2 + 0.05**2) / 4)
    assert math.isclose(downside_deviation(returns), expected)


def test_sortino_uses_target_downside_deviation_golden_value() -> None:
    returns = pd.Series([-0.02, 0.01, 0.03, 0.00])
    downside = math.sqrt(0.02**2 / 4)
    expected = returns.mean() / downside * math.sqrt(252)
    assert math.isclose(sortino_ratio(returns), expected)


def test_mark_to_last_observed_returns_preserves_internal_gap_and_terminal_unknown() -> None:
    prices = pd.DataFrame(
        {
            "INTERNAL": [100.0, float("nan"), 110.0, 121.0],
            "TERMINAL": [100.0, 105.0, float("nan"), float("nan")],
        }
    )

    returns = mark_to_last_observed_returns(prices)

    assert pd.isna(returns.loc[1, "INTERNAL"])
    assert math.isclose(returns.loc[2, "INTERNAL"], 0.10)
    assert math.isclose(returns.loc[3, "INTERNAL"], 0.10)
    assert math.isclose(returns.loc[1, "TERMINAL"], 0.05)
    assert returns.loc[2:, "TERMINAL"].isna().all()


def test_max_drawdown_counts_first_period_loss() -> None:
    assert round(max_drawdown(pd.Series([-0.10])), 8) == -0.10


def test_metric_summary_reports_turnover_and_cost_diagnostics() -> None:
    returns = pd.Series([0.01, -0.02, 0.03, 0.00])
    turnover = pd.Series([0.25, 0.75], index=[returns.index[1], returns.index[3]])
    costs = pd.Series([0.001, 0.002, 0.0, 0.003])

    summary = metric_summary(returns, turnover, costs)

    assert summary["avg_turnover"] == 0.5
    assert summary["total_turnover"] == 1.0
    assert summary["turnover_events"] == 2.0
    assert summary["annualized_turnover"] == 63.0
    assert math.isclose(summary["total_cost"], 0.006)
    assert math.isclose(summary["avg_daily_cost"], 0.0015)
    assert math.isclose(summary["annualized_cost_drag"], 0.378)


def test_metric_summary_applies_disclosed_annual_risk_free_rate_to_ratios() -> None:
    returns = pd.Series([0.001, 0.002, -0.001, 0.003] * 20, dtype=float)
    zero_rate = metric_summary(returns)
    positive_rate = metric_summary(returns, risk_free_rate=0.05)

    assert positive_rate["annual_risk_free_rate"] == 0.05
    assert positive_rate["sharpe"] < zero_rate["sharpe"]
    assert positive_rate["sortino"] < zero_rate["sortino"]


def test_metric_summary_reports_policy_input_reasons_and_execution_coverage() -> None:
    dates = pd.bdate_range("2025-01-02", periods=4)
    returns = pd.Series([0.0, 0.01, -0.01, 0.02], index=dates)
    policy_statuses = pd.Series(
        ["available", "unavailable", "not_scheduled", "available"],
        index=dates,
    )
    policy_reasons = pd.Series(
        [(), ("no_finite_trailing_volatility",), (), ()],
        index=dates,
    )
    execution_statuses = pd.Series(
        ["executed", "executed_partial_unpriceable_targets", "blocked_missing_held_quote", "none"],
        index=dates,
    )
    unpriceable = pd.Series([0, 2, 0, 0], index=dates)

    summary = metric_summary(
        returns,
        execution_statuses=execution_statuses,
        unpriceable_target_counts=unpriceable,
        policy_input_statuses=policy_statuses,
        policy_input_reasons=policy_reasons,
    )

    assert summary["scheduled_policy_signal_count"] == 3.0
    assert summary["available_policy_signal_count"] == 2.0
    assert summary["unavailable_policy_signal_count"] == 1.0
    assert summary["policy_input_coverage_ratio"] == pytest.approx(2.0 / 3.0)
    assert summary["policy_input_reason_counts"] == {"no_finite_trailing_volatility": 1}
    assert summary["execution_count"] == 2.0
    assert summary["full_execution_count"] == 1.0
    assert summary["partial_execution_count"] == 1.0
    assert summary["blocked_execution_count"] == 1.0
    assert summary["attempted_execution_count"] == 3.0
    assert summary["execution_coverage_ratio"] == pytest.approx(1.0 / 3.0)
    assert summary["unpriceable_target_observations"] == 1.0
    assert summary["total_unpriceable_target_count"] == 2.0


def test_metric_summary_exposes_worst_case_target_concentration_separately_from_medians() -> None:
    dates = pd.bdate_range("2025-01-02", periods=3)
    summary = metric_summary(
        pd.Series([0.0, 0.0, 0.0], index=dates),
        target_hhi=pd.Series([0.10, 0.10, 0.90], index=dates),
        target_effective_names=pd.Series([10.0, 10.0, 1.0 / 0.90], index=dates),
        target_max_weights=pd.Series([0.10, 0.10, 0.90], index=dates),
    )

    assert summary["median_target_hhi"] == pytest.approx(0.10)
    assert summary["max_target_hhi"] == pytest.approx(0.90)
    assert summary["median_target_effective_names"] == pytest.approx(10.0)
    assert summary["min_target_effective_names"] == pytest.approx(1.0 / 0.90)
    assert summary["max_target_weight"] == pytest.approx(0.90)


def test_internal_gap_preserves_endpoint_cagr_and_reports_daily_metric_coverage() -> None:
    returns = pd.Series([0.10, float("nan"), 0.10])
    turnover = pd.Series([1.0], index=[returns.index[0]])
    costs = pd.Series([0.01, 0.0, 0.0])

    summary = metric_summary(returns, turnover, costs)
    expected_cagr = (1.10 * 1.10) ** (252 / 3) - 1.0

    assert math.isclose(cagr(returns), expected_cagr)
    assert math.isclose(summary["cagr"], expected_cagr)
    assert summary["annual_return"] == pytest.approx(25.2)
    assert summary["daily_risk_observations"] == 1.0
    assert summary["multi_session_return_observations"] == 1.0
    assert summary["observations"] == 2.0
    assert summary["calendar_observations"] == 3.0
    assert summary["missing_observations"] == 1.0
    assert summary["return_coverage_ratio"] == 2.0 / 3.0
    assert summary["risk_metrics_complete"] is False
    assert summary["risk_metrics_exact"] is False
    assert summary["annualized_turnover"] == 84.0
    assert summary["annualized_cost_drag"] == pytest.approx(0.84)


def test_sparse_internal_gap_does_not_invalidate_other_exact_daily_returns() -> None:
    returns = pd.Series([0.01, float("nan"), 0.02, -0.01, 0.01])
    intervals = pd.Series([1, 0, 2, 1, 1])

    summary = metric_summary(returns, return_interval_sessions=intervals)

    assert summary["ending_nav_available"] is True
    assert summary["risk_metrics_complete"] is True
    assert summary["risk_metrics_exact"] is False
    assert summary["daily_risk_observations"] == 3.0
    assert summary["multi_session_return_observations"] == 1.0
    assert summary["quote_gap_observations"] == 1.0
    assert math.isfinite(summary["sharpe"])
    assert math.isfinite(summary["sortino"])


def test_trailing_unknown_return_makes_ending_nav_cagr_and_calmar_unknown() -> None:
    returns = pd.Series([0.10, float("nan")])
    summary = metric_summary(returns)

    assert math.isnan(cagr(returns))
    assert math.isnan(summary["cagr"])
    assert math.isnan(calmar_ratio(returns))
    assert math.isnan(summary["calmar"])
    assert summary["calendar_observations"] == 2.0
    assert summary["missing_observations"] == 1.0
    assert summary["risk_metrics_complete"] is False


def test_terminal_unknown_flat_path_does_not_report_zero_calmar() -> None:
    returns = pd.Series([0.0, float("nan")])
    assert math.isnan(cagr(returns))
    assert math.isnan(calmar_ratio(returns))


def test_leading_unknown_observations_are_outside_the_active_metric_window() -> None:
    returns = pd.Series([float("nan"), 0.10, 0.10])
    summary = metric_summary(returns)
    expected_cagr = (1.10 * 1.10) ** (252 / 2) - 1.0

    assert math.isclose(summary["cagr"], expected_cagr)
    assert summary["calendar_observations"] == 2.0
    assert summary["missing_observations"] == 0.0
    assert summary["risk_metrics_complete"] is True


def test_subperiod_stability_rewards_persistent_positive_paths() -> None:
    stable = pd.Series([0.001] * 756)
    unstable = pd.Series([0.004] * 252 + [-0.002] * 252 + [0.001] * 252)
    stable_score, stable_periods = subperiod_stability(stable, periods=3)
    unstable_score, unstable_periods = subperiod_stability(unstable, periods=3)
    assert len(stable_periods) == len(unstable_periods) == 3
    assert stable_score > unstable_score


def test_evaluation_metrics_honors_explicit_common_evaluation_index() -> None:
    dates = pd.bdate_range("2025-01-02", periods=12)
    returns = pd.Series([-0.10] * 7 + [0.01] * 5, index=dates)
    turnover = pd.Series(0.0, index=dates)
    costs = pd.Series(0.0, index=dates)
    common_index = dates[-5:]

    metrics = evaluation_metrics(
        returns,
        turnover,
        costs,
        window_days=10,
        stability_periods=2,
        evaluation_index=common_index,
    )

    assert metrics["observations"] == 5
    assert metrics["calendar_observations"] == 5
    assert metrics["cagr"] > 0.0


def test_composite_score_uses_all_declared_components_without_imputation() -> None:
    frame = pd.DataFrame(
        [
            _score_row(
                "balanced",
                sortino=2.0,
                calmar=1.5,
                max_drawdown=-0.10,
                cagr=0.15,
                sharpe=1.1,
                stability=0.10,
            ),
            _score_row(
                "sharpe_only",
                sortino=0.5,
                calmar=0.2,
                max_drawdown=-0.40,
                cagr=0.03,
                sharpe=2.0,
                stability=-0.10,
            ),
            _score_row(
                "missing",
                sortino=float("nan"),
                calmar=2.0,
                max_drawdown=-0.05,
                cagr=0.20,
                sharpe=1.5,
                stability=0.15,
            ),
        ]
    )
    weights = {
        "sortino": 0.25,
        "calmar": 0.20,
        "max_drawdown": 0.20,
        "cagr": 0.15,
        "sharpe": 0.10,
        "stability": 0.10,
    }

    result = composite_factor_scorecard(
        frame,
        weights=weights,
        winsor_lower=0.05,
        winsor_upper=0.95,
        min_observations=504,
        min_valuation_coverage=0.98,
        min_daily_risk_observations=504,
    ).set_index("factor")

    assert result.loc["balanced", "composite_score"] > result.loc["sharpe_only", "composite_score"]
    assert pd.isna(result.loc["missing", "composite_score"])
    assert result.loc["missing", "comparison_status"] == "insufficient_history"


def test_less_negative_mdd_gets_the_higher_component_score() -> None:
    frame = pd.DataFrame(
        [
            _score_row("small_drawdown", max_drawdown=-0.05),
            _score_row("large_drawdown", max_drawdown=-0.40),
        ]
    )

    result = composite_factor_scorecard(
        frame,
        weights={"max_drawdown": 1.0},
        winsor_lower=0.0,
        winsor_upper=1.0,
        min_observations=504,
        min_valuation_coverage=0.98,
        min_daily_risk_observations=504,
    ).set_index("factor")

    assert (
        result.loc["small_drawdown", "max_drawdown_score"]
        > result.loc["large_drawdown", "max_drawdown_score"]
    )


def test_composite_percentiles_ignore_ineligible_factor_values() -> None:
    frame = pd.DataFrame(
        [
            _score_row("low", sortino=1.0, observations=600, daily_risk_observations=600),
            _score_row("high", sortino=2.0, observations=600, daily_risk_observations=600),
            _score_row(
                "short_extreme",
                sortino=1_000_000.0,
                observations=10,
                daily_risk_observations=10,
            ),
            _score_row(
                "duplicate_extreme",
                sortino=2_000_000.0,
                observations=600,
                daily_risk_observations=600,
                comparison_eligible=False,
                comparison_ineligible_status="duplicate_alias",
            ),
        ]
    )

    result = composite_factor_scorecard(
        frame,
        weights={"sortino": 1.0},
        winsor_lower=0.05,
        winsor_upper=0.95,
        min_observations=504,
        min_valuation_coverage=0.98,
        min_daily_risk_observations=504,
    ).set_index("factor")

    assert result.loc["high", "sortino_score"] == pytest.approx(100.0)
    assert result.loc["low", "sortino_score"] == pytest.approx(50.0)
    assert pd.isna(result.loc["short_extreme", "sortino_score"])
    assert pd.isna(result.loc["duplicate_extreme", "sortino_score"])
    assert result.loc["duplicate_extreme", "comparison_status"] == "duplicate_alias"


@pytest.mark.parametrize(
    ("value", "expected_score"),
    [(float("inf"), 100.0), (float("-inf"), 0.0)],
)
def test_composite_percentiles_score_same_sign_infinity_only_columns(
    value: float,
    expected_score: float,
) -> None:
    frame = pd.DataFrame(
        [
            _score_row("first", sortino=value),
            _score_row("second", sortino=value),
        ]
    )

    result = composite_factor_scorecard(
        frame,
        weights={"sortino": 1.0},
        winsor_lower=0.05,
        winsor_upper=0.95,
        min_observations=504,
        min_valuation_coverage=0.98,
        min_daily_risk_observations=504,
    )

    assert result["sortino_score"].tolist() == [expected_score, expected_score]
    assert result["composite_score"].tolist() == [expected_score, expected_score]
    assert result["comparison_status"].tolist() == ["available", "available"]


@pytest.mark.parametrize(
    ("changes", "expected_status"),
    [
        (
            {"valuation_coverage_ratio": 0.97},
            "insufficient_valuation_or_daily_risk_coverage",
        ),
        (
            {"daily_risk_observations": 503},
            "insufficient_valuation_or_daily_risk_coverage",
        ),
        (
            {"policy_input_coverage_ratio": 0.99},
            "insufficient_policy_input_coverage",
        ),
        (
            {"execution_coverage_ratio": 0.99},
            "incomplete_execution_coverage",
        ),
    ],
)
def test_scorecard_fail_closes_coverage_gates(
    changes: dict[str, object],
    expected_status: str,
) -> None:
    frame = pd.DataFrame([_score_row("blocked", **changes)])

    result = composite_factor_scorecard(
        frame,
        weights={"sortino": 1.0},
        winsor_lower=0.0,
        winsor_upper=1.0,
        min_observations=504,
        min_valuation_coverage=0.98,
        min_daily_risk_observations=504,
    )

    assert result.loc[0, "comparison_status"] == expected_status
    assert pd.isna(result.loc[0, "composite_score"])
