from __future__ import annotations

import hashlib
import json
import resource
import sys
from collections import Counter
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd

from .advanced_factors import advanced_factor_definitions_frame, compute_advanced_factor_scores
from .backtest import BacktestResult, run_factor_backtest
from .config import (
    ABSOLUTE_GUARDRAIL_VERSION,
    FACTOR_SELECTION_VERSION,
    FIXED_WEIGHTING_POLICY,
    POLICY_REGISTRY,
    POLICY_REGISTRY_VERSION,
    RunConfig,
    WEIGHTING_POLICIES,
)
from .data import SNAPSHOT_READ_CONTRACT, MarketData, load_market_data, write_market_data_snapshot
from .factors import factor_definition_sha256, factor_definitions_frame, iter_factor_scores
from .identity import (
    build_result_identity,
    canonical_json_bytes,
    policy_definition_sha256,
    selection_spec_sha256,
)
from .metrics import (
    composite_factor_scorecard,
    evaluation_metrics,
    mark_to_last_observed_returns,
    metric_summary,
)
from .portfolio import ModelPortfolio, construct_model_portfolio
from .research_inputs import ResearchInputs


RESEARCH_LIMITATIONS = (
    "동일한 후행 평가기간에서 여러 팩터를 비교한 설명적 순위이므로 선택 편향이 있습니다.",
    "현재 상장 종목 중심 입력은 역사적 구성종목·상장폐지·ticker reuse를 완전히 복원하지 못합니다.",
    "중간 quote gap은 종목별 sleeve NAV를 유지하지만 그 날짜의 일별 위험 수익률을 추정하지 않습니다.",
    "시가총액은 실제 SEC 제출일 이후에만 사용하며 공시가 없는 종목은 추정값으로 채우지 않습니다.",
    "표시 포트폴리오는 마지막 입력일 신호로 만든 다음 세션 종가용 연구 비중이며 이미 체결된 보유가 아닙니다.",
)

PERFORMANCE_CONTRACT_VERSION = "python-period-performance-v1"
PERFORMANCE_PERIODS = (
    ("1W", "최근 1주", 5),
    ("1M", "최근 1개월", 21),
    ("3M", "최근 3개월", 63),
    ("6M", "최근 6개월", 126),
    ("1Y", "최근 1년", 252),
    ("YTD", "연초 이후", None),
    ("FULL", "전체 공통 평가기간", None),
)
PERFORMANCE_METRIC_KEYS = (
    "cumulativeReturn",
    "sharpe",
    "annualizedVolatility",
    "maxDrawdown",
    "sortino",
    "calmar",
    "cvar5",
    "winRate",
)
SELECTED_HOLDING_HISTORY_CONTRACT_VERSION = 1
SELECTED_HOLDING_HISTORY_SESSION_COUNT = 21
SELECTED_HOLDING_HISTORY_WEIGHT_TIMING = "last_complete_close_after_execution_processing"
FACTOR_HOLDING_HISTORY_SIDECAR_CONTRACT = "momentum-factor-holding-history-sidecar"
FACTOR_HOLDING_HISTORY_SIDECAR_CONTRACT_VERSION = 2
FACTOR_HOLDING_HISTORY_SIDECAR_DIRECTORY = "factor-holding-history"
MAX_FACTOR_HOLDING_HISTORY_SIDECAR_BYTES = 5_000_000


class NoEligibleFactorError(ValueError):
    """The fixed absolute policy produced no publishable factor.

    This is a valid fail-closed analytical outcome, not permission to relax a
    guardrail or select a fallback factor. Details retain every evaluated row so
    unavailable metrics remain distinguishable from absolute guardrail failures.
    """

    def __init__(self, details: list[dict[str, Any]]) -> None:
        self.factor_details = _json_safe(details)
        self.evaluated_factor_count = len(self.factor_details)
        comparison_counts: Counter[str] = Counter()
        selection_counts: Counter[str] = Counter()
        exclusion_counts: Counter[str] = Counter()
        breach_counts: Counter[str] = Counter()
        for detail in self.factor_details:
            # Older callers supplied comparable rows containing only breaches.
            status = str(detail.get("comparison_status", "available"))
            comparison_counts[status] += 1
            selection_status = str(detail.get("selection_status", "absolute_guardrail_excluded"))
            selection_counts[selection_status] += 1
            if status == "available":
                breach_counts.update(_normalized_reason_codes(detail.get("guardrail_breaches")))
            else:
                exclusion_counts.update(
                    _normalized_reason_codes(detail.get("exclusion_reason_codes"))
                )
        self.comparable_factor_count = comparison_counts["available"]
        self.comparison_status_counts = dict(sorted(comparison_counts.items()))
        self.selection_status_counts = dict(sorted(selection_counts.items()))
        self.exclusion_reason_counts = dict(sorted(exclusion_counts.items()))
        self.guardrail_breach_counts = dict(sorted(breach_counts.items()))
        super().__init__(
            "no factor passes the absolute selection guardrails under the fixed policy: "
            + json.dumps(
                {
                    "evaluatedFactorCount": self.evaluated_factor_count,
                    "comparableFactorCount": self.comparable_factor_count,
                    "comparisonStatusCounts": self.comparison_status_counts,
                    "exclusionReasonCounts": self.exclusion_reason_counts,
                    "guardrailBreachCounts": self.guardrail_breach_counts,
                    "factorDetails": self.factor_details,
                },
                ensure_ascii=False,
                allow_nan=False,
            )
        )


FACTOR_DIAGNOSTICS_CONTRACT_VERSION = 1
FACTOR_DIAGNOSTICS_RANK_IC_HORIZON_SESSIONS = 21
FACTOR_DIAGNOSTICS_MAX_SIGNAL_SESSIONS = 756
FACTOR_DIAGNOSTICS_REDUNDANCY_THRESHOLD = 0.95
FACTOR_DIAGNOSTICS_TOP_PAIR_COUNT = 10
FACTOR_DIAGNOSTICS_RANK_IC_METHOD = (
    "cross_sectional_spearman_signal_t_vs_adjusted_close_return_t_to_t_plus_21"
)
FACTOR_DIAGNOSTICS_REDUNDANCY_METHOD = "latest_signal_date_cross_sectional_spearman"

CANONICAL_TOTAL_FACTOR_COUNT = 64
CANONICAL_INDEPENDENT_FACTOR_COUNT = 61
CANONICAL_ALIAS_FACTOR_COUNT = 3

_DATA_SHORTAGE_POLICY_REASONS = frozenset(
    {
        "no_complete_signal_inputs",
        "no_finite_trailing_dollar_volume",
        "no_point_in_time_market_cap",
        "no_complete_fixed_policy_inputs",
        "top_n_boundary_tie_has_no_finite_liquidity_tie_break",
    }
)

FACTOR_SELECTION_TIE_BREAK_POLICY = (
    "selection_score_desc",
    "base_composite_score_desc",
    "max_abs_leave_one_security_cagr_delta_asc",
    "max_abs_security_observation_contribution_asc",
    "sortino_desc",
    "calmar_desc",
    "max_drawdown_desc",
    "cagr_desc",
    "sharpe_desc",
    "stability_desc",
    "annualized_cost_drag_asc",
    "annualized_turnover_asc",
    "factor_name_asc",
    "policy_id_asc",
)


@dataclass(slots=True)
class AnalysisResult:
    generated_at_utc: datetime
    runtime_seconds: float
    max_rss_bytes: int
    config: RunConfig
    market_data: MarketData
    factor_scores: dict[str, pd.Series]
    backtests: dict[str, BacktestResult]
    policy_factor_metrics: pd.DataFrame
    policy_comparison: pd.DataFrame
    selected_policy: str
    selected_policy_reason: str
    policy_selection_decision: dict[str, Any]
    factor_ranking: pd.DataFrame
    selected_factor: str
    selected_reason: str
    factor_selection_decision: dict[str, Any]
    model_portfolio: ModelPortfolio
    factor_portfolios: dict[str, ModelPortfolio]
    factor_definitions: pd.DataFrame
    benchmark_metrics: dict[str, object]
    factor_diagnostics: dict[str, Any] = field(default_factory=dict)
    factor_holding_histories: dict[str, dict[str, Any]] = field(default_factory=dict)
    grid_accounting: dict[str, Any] = field(default_factory=dict)
    result_identity: dict[str, Any] = field(default_factory=dict)
    advanced_factor_status: pd.DataFrame = field(default_factory=pd.DataFrame)
    input_snapshot_paths: dict[str, str] = field(default_factory=dict)
    output_paths: dict[str, str] = field(default_factory=dict)


def _max_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _analysis_prices(market_data: MarketData) -> pd.DataFrame:
    columns = [column for column in market_data.prices.columns if column != market_data.benchmark]
    return market_data.prices.reindex(columns=columns).dropna(axis=1, how="all")


def _canonical_factor_definitions() -> pd.DataFrame:
    definitions = pd.concat(
        [factor_definitions_frame(), advanced_factor_definitions_frame()],
        ignore_index=True,
        sort=False,
    )
    if definitions["factor"].duplicated().any():
        duplicates = sorted(
            definitions.loc[definitions["factor"].duplicated(), "factor"].astype(str)
        )
        raise RuntimeError(f"canonical factor registry has duplicates: {duplicates}")
    aliases = definitions["compatibility_alias_of"].notna()
    independent = definitions["selection_eligible"].fillna(True).astype(bool) & ~aliases
    observed = {
        "total": len(definitions),
        "independent": int(independent.sum()),
        "aliases": int(aliases.sum()),
    }
    expected = {
        "total": CANONICAL_TOTAL_FACTOR_COUNT,
        "independent": CANONICAL_INDEPENDENT_FACTOR_COUNT,
        "aliases": CANONICAL_ALIAS_FACTOR_COUNT,
    }
    if observed != expected:
        raise RuntimeError(
            "canonical factor registry count mismatch: "
            + json.dumps({"observed": observed, "expected": expected}, sort_keys=True)
        )
    return definitions.reset_index(drop=True)


def _advanced_factor_input_issues(status: pd.DataFrame) -> dict[str, dict[str, object]]:
    expected = set(advanced_factor_definitions_frame()["factor"].astype(str))
    if status.empty or "factor" not in status or status["factor"].duplicated().any():
        raise ValueError("implementation_error_advanced_factor_status_registry")
    observed = set(status["factor"].astype(str))
    if observed != expected:
        raise ValueError(
            "implementation_error_advanced_factor_status_registry: "
            + json.dumps(
                {
                    "missing": sorted(expected.difference(observed)),
                    "unexpected": sorted(observed.difference(expected)),
                },
                sort_keys=True,
            )
        )
    issues: dict[str, dict[str, object]] = {}
    for row in status.to_dict(orient="records"):
        factor = str(row["factor"])
        available = row.get("available")
        if not isinstance(available, bool):
            raise ValueError(f"implementation_error_advanced_factor_status:{factor}")
        if available:
            continue
        reason_code = str(row.get("reasonCode") or "").strip()
        detail = str(row.get("detail") or "").strip()
        if not reason_code or not detail:
            raise ValueError(f"implementation_error_advanced_factor_reason:{factor}")
        issues[factor] = {
            "factor": factor,
            "reasonCode": reason_code,
            "detail": detail,
        }
    return issues


def _names_by_symbol(market_data: MarketData) -> pd.Series:
    if market_data.universe.empty or "symbol" not in market_data.universe:
        return pd.Series(dtype=object)
    names = market_data.universe.drop_duplicates("symbol").set_index("symbol")
    if "name" not in names:
        return pd.Series(names.index.astype(str), index=names.index, dtype=object)
    return names["name"].astype(str)


def _liquidity_context(
    dollar_volumes: pd.DataFrame,
    config: RunConfig,
) -> pd.DataFrame:
    liquidity = dollar_volumes.rolling(
        config.liquidity_lookback_days,
        min_periods=config.min_liquidity_observations,
    ).mean()
    return liquidity


def _recompute_selected_factor_panel(
    selected_factor: str,
    prices: pd.DataFrame,
    eligibility: pd.DataFrame,
    market: MarketData,
    dollar_volumes: pd.DataFrame,
) -> pd.DataFrame:
    for factor, panel in iter_factor_scores(prices, eligibility_mask=eligibility):
        if factor == selected_factor:
            return panel
    advanced = compute_advanced_factor_scores(
        prices,
        volumes=market.volumes.reindex(index=prices.index, columns=prices.columns),
        dollar_volumes=dollar_volumes,
        eligibility_mask=eligibility,
    )
    panel = advanced.scores.get(selected_factor)
    if panel is None:
        raise ValueError(f"implementation_error_selected_factor_panel_missing: {selected_factor}")
    return panel


def _assert_selected_history_replay_matches(
    original: BacktestResult,
    replayed: BacktestResult,
) -> None:
    series_fields = (
        "returns",
        "equity",
        "turnover",
        "costs",
        "signal_dates",
        "eligible_security_counts",
        "selected_security_counts",
        "selection_fractions",
        "gross_exposure",
        "strategy_active",
        "valuation_available",
        "stale_holding_counts",
        "stale_holding_weights",
        "execution_statuses",
        "unpriceable_target_counts",
        "return_interval_sessions",
        "target_cash_weights",
        "target_hhi",
        "target_effective_names",
        "target_top1_weights",
        "target_top5_weights",
        "target_max_weights",
        "policy_input_statuses",
        "policy_input_reasons",
    )
    mismatched = [
        field
        for field in series_fields
        if not getattr(original, field).equals(getattr(replayed, field))
    ]
    if not original.ending_weights.equals(replayed.ending_weights):
        mismatched.append("ending_weights")
    scalar_fields = (
        "ending_cash_weight",
        "last_execution_date",
        "last_signal_date",
        "first_nonempty_execution_date",
        "first_market_exposure_return_date",
    )
    mismatched.extend(
        field for field in scalar_fields if getattr(original, field) != getattr(replayed, field)
    )
    if original.contribution_diagnostics.to_dict() != replayed.contribution_diagnostics.to_dict():
        mismatched.append("contribution_diagnostics")
    if mismatched:
        raise ValueError(
            "implementation_error_selected_history_replay_mismatch: " + ", ".join(mismatched)
        )


def _normalized_reason_codes(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set)):
        return ()
    return tuple(dict.fromkeys(str(reason).strip() for reason in value if str(reason).strip()))


def _validated_policy_input_failures(
    backtest: BacktestResult,
    evaluation_index: pd.DatetimeIndex,
    *,
    factor: str,
    policy_id: str,
) -> list[dict[str, object]]:
    statuses = backtest.policy_input_statuses.astype(str)
    reasons = backtest.policy_input_reasons.reindex(statuses.index)
    failures: list[dict[str, object]] = []
    evaluation_dates = set(pd.DatetimeIndex(evaluation_index))
    for date, status in statuses.items():
        if status not in {"not_scheduled", "available", "unavailable"}:
            raise ValueError(
                "implementation_error_unknown_policy_input_status: "
                f"{factor}@{policy_id} {pd.Timestamp(date).date().isoformat()} status={status!r}"
            )
        if status != "unavailable":
            continue
        reason_codes = _normalized_reason_codes(reasons.get(date))
        unknown = sorted(set(reason_codes).difference(_DATA_SHORTAGE_POLICY_REASONS))
        if not reason_codes or unknown:
            raise ValueError(
                "implementation_error_policy_input_reason: "
                + json.dumps(
                    {
                        "factor": factor,
                        "policyId": policy_id,
                        "date": pd.Timestamp(date).date().isoformat(),
                        "reasons": list(reason_codes),
                        "unknownReasons": unknown,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        if pd.Timestamp(date) in evaluation_dates:
            failures.append(
                {
                    "policyId": policy_id,
                    "date": pd.Timestamp(date).date().isoformat(),
                    "reasons": list(reason_codes),
                }
            )
    return failures


def _validated_current_unavailable_reasons(
    reasons: object,
    *,
    factor: str,
    policy_id: str,
    date: pd.Timestamp,
) -> list[str]:
    reason_codes = _normalized_reason_codes(reasons)
    unknown = sorted(set(reason_codes).difference(_DATA_SHORTAGE_POLICY_REASONS))
    if not reason_codes or unknown:
        raise ValueError(
            "implementation_error_current_policy_input_reason: "
            + json.dumps(
                {
                    "factor": factor,
                    "policyId": policy_id,
                    "date": date.date().isoformat(),
                    "reasons": list(reason_codes),
                    "unknownReasons": unknown,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    return list(reason_codes)


def _raw_factor_metrics(
    policy_id: str,
    backtests: dict[str, BacktestResult],
    definitions: pd.DataFrame,
    config: RunConfig,
    evaluation_index: pd.DatetimeIndex,
    *,
    portfolios: dict[str, ModelPortfolio] | None = None,
    policy_grid_reasons: dict[str, dict[str, object] | None] | None = None,
    factor_input_issues: Mapping[str, Mapping[str, object]] | None = None,
) -> pd.DataFrame:
    category = definitions.set_index("factor")["category"].to_dict()
    selection_eligible = definitions.set_index("factor")["selection_eligible"].to_dict()
    alias_of = definitions.set_index("factor")["compatibility_alias_of"].to_dict()
    rows: list[dict[str, object]] = []
    for factor, backtest in backtests.items():
        raw_alias = alias_of.get(factor)
        alias = str(raw_alias).strip() if pd.notna(raw_alias) and str(raw_alias).strip() else None
        distinct = bool(selection_eligible.get(factor, True)) and alias is None
        portfolio = portfolios[factor] if portfolios is not None else None
        current_available = portfolio is None or portfolio.status == "available"
        current_holding_count = (
            portfolio.allocation.selected_security_count if portfolio is not None else float("nan")
        )
        current_cash_weight = portfolio.cash_weight if portfolio is not None else float("nan")
        current_concentration = portfolio.allocation.concentration if portfolio is not None else {}
        current_target_effective_names = current_concentration.get("effectiveNames", float("nan"))
        current_target_hhi = current_concentration.get("riskySleeveHhi", float("nan"))
        current_target_max_weight = current_concentration.get("maxWeight", float("nan"))
        current_input_reasons: list[str] = []
        if portfolio is not None and not current_available:
            current_input_reasons = _validated_current_unavailable_reasons(
                portfolio.reasons,
                factor=factor,
                policy_id=policy_id,
                date=portfolio.as_of,
            )
        policy_input_failures = _validated_policy_input_failures(
            backtest,
            evaluation_index,
            factor=factor,
            policy_id=policy_id,
        )
        grid_reason = policy_grid_reasons.get(factor) if policy_grid_reasons is not None else None
        factor_input_issue = (
            dict(factor_input_issues[factor])
            if factor_input_issues is not None and factor in factor_input_issues
            else None
        )
        comparison_eligible = (
            distinct and current_available and grid_reason is None and factor_input_issue is None
        )
        if alias:
            ineligible_status = "duplicate_alias"
            comparison_reason = f"duplicate_alias_of:{alias}"
        elif factor_input_issue is not None:
            ineligible_status = "factor_input_unavailable"
            comparison_reason = factor_input_issue
        elif grid_reason is not None:
            ineligible_status = "policy_rebalance_grid_mismatch"
            comparison_reason = grid_reason
        elif not current_available:
            ineligible_status = "current_portfolio_unavailable"
            comparison_reason = {
                "policyId": policy_id,
                "date": portfolio.as_of.date().isoformat() if portfolio is not None else None,
                "reasons": current_input_reasons,
            }
        else:
            ineligible_status = None
            comparison_reason = None
        summary = evaluation_metrics(
            backtest.returns,
            backtest.turnover,
            backtest.costs,
            window_days=config.evaluation_window_days,
            stability_periods=config.stability_periods,
            risk_free_rate=config.annual_cash_return,
            gross_exposure=backtest.gross_exposure,
            strategy_active=backtest.strategy_active,
            valuation_available=backtest.valuation_available,
            stale_holding_counts=backtest.stale_holding_counts,
            stale_holding_weights=backtest.stale_holding_weights,
            execution_statuses=backtest.execution_statuses,
            unpriceable_target_counts=backtest.unpriceable_target_counts,
            policy_input_statuses=backtest.policy_input_statuses,
            policy_input_reasons=backtest.policy_input_reasons,
            return_interval_sessions=backtest.return_interval_sessions,
            target_cash_weights=backtest.target_cash_weights,
            target_hhi=backtest.target_hhi,
            target_effective_names=backtest.target_effective_names,
            target_top1_weights=backtest.target_top1_weights,
            target_top5_weights=backtest.target_top5_weights,
            target_max_weights=backtest.target_max_weights,
            evaluation_index=evaluation_index,
        )
        diagnostics = backtest.contribution_diagnostics
        observed_event = diagnostics.max_observed_interval_security_contribution
        rows.append(
            {
                "policy_id": policy_id,
                "factor": factor,
                "category": category.get(factor, "other"),
                "comparison_eligible": comparison_eligible,
                "comparison_ineligible_status": ineligible_status,
                "comparison_reason": comparison_reason,
                "current_portfolio_available": current_available,
                "current_holding_count": current_holding_count,
                "current_cash_weight": current_cash_weight,
                "current_target_effective_names": current_target_effective_names,
                "current_target_hhi": current_target_hhi,
                "current_target_max_weight": current_target_max_weight,
                "current_portfolio_input_reasons": current_input_reasons,
                "policy_input_failures": policy_input_failures,
                "contribution_diagnostics_complete": diagnostics.complete,
                "contribution_diagnostics_reason": diagnostics.reason,
                "contribution_attribution_method": diagnostics.attribution_method,
                "contribution_attribution_version": diagnostics.attribution_version,
                "max_abs_security_day_contribution": (
                    diagnostics.max_abs_security_day_contribution
                ),
                "max_abs_security_observation_contribution": (
                    observed_event.absolute_contribution if observed_event is not None else 0.0
                ),
                "max_security_absolute_contribution_share": (
                    diagnostics.max_security_absolute_contribution_share
                ),
                "absolute_contribution_hhi": diagnostics.absolute_contribution_hhi,
                "max_abs_leave_one_security_cagr_delta": (
                    diagnostics.max_leave_one_security_cagr_delta
                ),
                "attribution_max_residual": diagnostics.attribution_max_residual,
                **summary,
            }
        )
    return pd.DataFrame(rows)


def _policy_grid_reasons(
    all_backtests: dict[str, dict[str, BacktestResult]],
    evaluation_index: pd.DatetimeIndex,
    expected_factors: Collection[str],
) -> dict[str, dict[str, object] | None]:
    """Verify the complete fixed-policy factor execution grid."""

    factors = {str(factor) for factor in expected_factors}
    missing_pairs = sorted(
        (factor, policy)
        for factor in factors
        for policy in WEIGHTING_POLICIES
        if factor not in all_backtests.get(policy, {})
    )
    if missing_pairs:
        rendered = ", ".join(f"{factor}@{policy}" for factor, policy in missing_pairs)
        raise ValueError("implementation_error_missing_factor_policy_pairs: " + rendered)
    reasons: dict[str, dict[str, object] | None] = {}
    for factor in factors:
        available_dates: dict[str, tuple[str, ...]] = {}
        scheduled_counts: dict[str, int] = {}
        policy_failures: list[dict[str, object]] = []
        for policy in WEIGHTING_POLICIES:
            backtest = all_backtests[policy][factor]
            policy_failures.extend(
                _validated_policy_input_failures(
                    backtest,
                    evaluation_index,
                    factor=factor,
                    policy_id=policy,
                )
            )
            statuses = (
                backtest.policy_input_statuses.reindex(evaluation_index)
                .fillna("not_scheduled")
                .astype(str)
            )
            available_dates[policy] = tuple(
                date.date().isoformat() for date in statuses.index[statuses.eq("available")]
            )
            scheduled_counts[policy] = int(statuses.ne("not_scheduled").sum())
        distinct_grids = set(available_dates.values())
        if all(not dates for dates in available_dates.values()):
            reasons[factor] = {
                "detail": "no_available_policy_rebalance_in_evaluation_window",
                "policyFailures": policy_failures,
                "availableDateCounts": {
                    policy: len(available_dates[policy]) for policy in WEIGHTING_POLICIES
                },
                "scheduledDateCounts": scheduled_counts,
            }
        elif len(distinct_grids) != 1:
            reasons[factor] = {
                "detail": "successful_rebalance_dates_differ",
                "policyFailures": policy_failures,
                "availableDateCounts": {
                    policy: len(available_dates[policy]) for policy in WEIGHTING_POLICIES
                },
                "scheduledDateCounts": scheduled_counts,
            }
        else:
            reasons[factor] = None
    return reasons


def _score_factor_metrics(raw: pd.DataFrame, config: RunConfig) -> pd.DataFrame:
    return composite_factor_scorecard(
        raw,
        weights=config.score_weights,
        winsor_lower=config.score_winsor_lower,
        winsor_upper=config.score_winsor_upper,
        min_observations=config.min_evaluation_observations,
        min_valuation_coverage=config.min_valuation_coverage,
        min_daily_risk_observations=config.min_daily_risk_observations,
    )


def _structured_exclusion_reasons(row: pd.Series, config: RunConfig) -> list[dict[str, object]]:
    status = str(row.get("comparison_status") or "")
    if status == "available":
        return []
    reason = row.get("comparison_reason")
    if status == "duplicate_alias":
        return [{"code": "duplicate_alias", "detail": str(reason)}]
    if status == "factor_input_unavailable":
        if not isinstance(reason, Mapping):
            raise ValueError("implementation_error_invalid_factor_input_exclusion")
        return [{"code": "factor_input_unavailable", **dict(reason)}]
    if status == "policy_rebalance_grid_mismatch":
        if not isinstance(reason, Mapping):
            raise ValueError("implementation_error_invalid_policy_grid_exclusion")
        return [{"code": "policy_rebalance_grid_mismatch", **dict(reason)}]
    if status == "current_portfolio_unavailable":
        if not isinstance(reason, Mapping):
            raise ValueError("implementation_error_invalid_current_target_exclusion")
        return [{"code": "current_portfolio_unavailable", **dict(reason)}]
    if status == "insufficient_history":
        if not bool(row.get("ending_nav_available", False)):
            return [
                {
                    "code": "terminal_nav_unavailable",
                    "metric": "ending_nav_available",
                    "observed": False,
                    "detail": "final valuation interval contains an unpriced held sleeve",
                }
            ]
        observations = float(row.get("observations", 0.0))
        if observations < config.min_evaluation_observations:
            return [
                {
                    "code": "insufficient_observations",
                    "metric": "observations",
                    "observed": observations,
                    "required": config.min_evaluation_observations,
                }
            ]
        if not bool(row.get("risk_metrics_complete", False)):
            return [{"code": "incomplete_risk_metrics", "metric": "risk_metrics_complete"}]
    if status == "insufficient_valuation_or_daily_risk_coverage":
        return [
            {
                "code": status,
                "valuationCoverage": float(row.get("valuation_coverage_ratio", 0.0)),
                "minimumValuationCoverage": config.min_valuation_coverage,
                "dailyRiskObservations": float(row.get("daily_risk_observations", 0.0)),
                "minimumDailyRiskObservations": config.min_daily_risk_observations,
            }
        ]
    if status == "insufficient_policy_input_coverage":
        return [
            {
                "code": status,
                "coverage": float(row.get("policy_input_coverage_ratio", 0.0)),
                "reasonCounts": dict(row.get("policy_input_reason_counts") or {}),
                "policyFailures": list(row.get("policy_input_failures") or []),
            }
        ]
    if status == "incomplete_execution_coverage":
        return [
            {
                "code": status,
                "coverage": float(row.get("execution_coverage_ratio", 0.0)),
                "blockedExecutions": float(row.get("blocked_execution_count", 0.0)),
                "unpriceableTargets": float(row.get("total_unpriceable_target_count", 0.0)),
            }
        ]
    raise ValueError(
        "implementation_error_unexplained_factor_policy_exclusion: "
        f"{row.get('factor')}@{row.get('policy_id')} status={status!r} reason={reason!r}"
    )


def _with_exclusion_accounting(scored: pd.DataFrame, config: RunConfig) -> pd.DataFrame:
    result = scored.copy()
    reasons = [_structured_exclusion_reasons(row, config) for _, row in result.iterrows()]
    result["exclusion_reasons"] = reasons
    result["exclusion_reason_codes"] = [
        [str(item["code"]) for item in row_reasons] for row_reasons in reasons
    ]
    return result


def _ratio_severity(observed: float, threshold: float) -> float:
    if observed <= threshold:
        return 0.0
    if threshold <= 0.0:
        return 1.0
    return min(1.0, max(0.0, observed / threshold - 1.0))


def _absolute_guardrail_profile(config: RunConfig) -> dict[str, Any]:
    return {
        "id": ABSOLUTE_GUARDRAIL_VERSION,
        "version": 1,
        "policyNeutral": True,
        "rules": [
            {
                "id": "minimum_sharpe",
                "metric": "sharpe",
                "operator": ">=",
                "threshold": config.selection_min_sharpe,
                "unit": "ratio",
            },
            {
                "id": "maximum_drawdown_magnitude",
                "metric": "max_drawdown",
                "operator": ">=",
                "threshold": -config.selection_max_drawdown,
                "unit": "fraction",
            },
            {
                "id": "maximum_annualized_cost_drag",
                "metric": "annualized_cost_drag",
                "operator": "<=",
                "threshold": config.selection_max_annualized_cost_drag,
                "unit": "fraction_per_year",
            },
            {
                "id": "minimum_historical_target_effective_names",
                "metric": "min_target_effective_names",
                "operator": ">=",
                "threshold": config.selection_min_effective_names,
                "unit": "names",
            },
            {
                "id": "minimum_current_target_effective_names",
                "metric": "current_target_effective_names",
                "operator": ">=",
                "threshold": config.selection_min_effective_names,
                "unit": "names",
            },
            {
                "id": "maximum_historical_target_hhi",
                "metric": "max_target_hhi",
                "operator": "<=",
                "threshold": config.selection_max_target_hhi,
                "unit": "fraction",
            },
            {
                "id": "maximum_current_target_hhi",
                "metric": "current_target_hhi",
                "operator": "<=",
                "threshold": config.selection_max_target_hhi,
                "unit": "fraction",
            },
            {
                "id": "maximum_historical_target_weight",
                "metric": "max_target_weight",
                "operator": "<=",
                "threshold": config.selection_max_target_weight,
                "unit": "fraction",
            },
            {
                "id": "maximum_current_target_weight",
                "metric": "current_target_max_weight",
                "operator": "<=",
                "threshold": config.selection_max_target_weight,
                "unit": "fraction",
            },
            {
                "id": "maximum_security_day_contribution",
                "metric": "max_abs_security_day_contribution",
                "operator": "<=",
                "threshold": config.selection_max_abs_security_day_contribution,
                "unit": "portfolio_return_fraction",
            },
            {
                "id": "maximum_security_absolute_contribution_share",
                "metric": "max_security_absolute_contribution_share",
                "operator": "<=",
                "threshold": config.selection_max_security_absolute_contribution_share,
                "unit": "fraction",
            },
            {
                "id": "maximum_leave_one_security_cagr_delta",
                "metric": "max_abs_leave_one_security_cagr_delta",
                "operator": "<=",
                "threshold": config.selection_max_leave_one_security_cagr_delta,
                "unit": "cagr_fraction",
            },
        ],
        "requiredContracts": {
            "completePolicyInputs": True,
            "completeExecutionCoverage": True,
            "currentTargetAvailable": True,
            "contributionDiagnosticsComplete": True,
        },
        "extremeEventAction": config.selection_extreme_event_action,
        "extremeEventPenaltyPoints": config.selection_extreme_event_penalty_points,
    }


def _apply_factor_guardrails(
    scored: pd.DataFrame,
    config: RunConfig,
) -> tuple[pd.DataFrame, str, str, str, dict[str, Any]]:
    result = scored.copy()
    result["base_composite_score"] = pd.to_numeric(result["composite_score"], errors="coerce")
    result["guardrail_sharpe"] = pd.to_numeric(result["sharpe"], errors="coerce").ge(
        config.selection_min_sharpe
    )
    result["guardrail_drawdown"] = pd.to_numeric(result["max_drawdown"], errors="coerce").ge(
        -config.selection_max_drawdown
    )
    result["guardrail_cost"] = pd.to_numeric(result["annualized_cost_drag"], errors="coerce").le(
        config.selection_max_annualized_cost_drag
    )
    result["guardrail_historical_effective_names"] = pd.to_numeric(
        result["min_target_effective_names"], errors="coerce"
    ).ge(config.selection_min_effective_names)
    result["guardrail_current_effective_names"] = pd.to_numeric(
        result["current_target_effective_names"], errors="coerce"
    ).ge(config.selection_min_effective_names)
    result["guardrail_historical_target_hhi"] = pd.to_numeric(
        result["max_target_hhi"], errors="coerce"
    ).le(config.selection_max_target_hhi)
    result["guardrail_current_target_hhi"] = pd.to_numeric(
        result["current_target_hhi"], errors="coerce"
    ).le(config.selection_max_target_hhi)
    result["guardrail_historical_target_weight"] = pd.to_numeric(
        result["max_target_weight"], errors="coerce"
    ).le(config.selection_max_target_weight)
    result["guardrail_current_target_weight"] = pd.to_numeric(
        result["current_target_max_weight"], errors="coerce"
    ).le(config.selection_max_target_weight)
    result["guardrail_policy_input"] = pd.to_numeric(
        result["policy_input_coverage_ratio"], errors="coerce"
    ).ge(1.0 - 1e-12)
    result["guardrail_execution"] = (
        pd.to_numeric(result["execution_coverage_ratio"], errors="coerce").ge(1.0 - 1e-12)
        & pd.to_numeric(result["blocked_execution_count"], errors="coerce").le(0.0)
        & pd.to_numeric(result["total_unpriceable_target_count"], errors="coerce").le(0.0)
    )
    result["guardrail_current_target"] = (
        result["current_portfolio_available"].fillna(False).astype(bool)
    )
    result["guardrail_contribution_complete"] = (
        result["contribution_diagnostics_complete"].fillna(False).astype(bool)
    )
    result["guardrail_security_day_contribution"] = pd.to_numeric(
        result["max_abs_security_day_contribution"], errors="coerce"
    ).le(config.selection_max_abs_security_day_contribution)
    result["guardrail_security_absolute_contribution_share"] = pd.to_numeric(
        result["max_security_absolute_contribution_share"], errors="coerce"
    ).le(config.selection_max_security_absolute_contribution_share)
    result["guardrail_leave_one_security"] = pd.to_numeric(
        result["max_abs_leave_one_security_cagr_delta"], errors="coerce"
    ).le(config.selection_max_leave_one_security_cagr_delta)

    standard_guardrails = [
        "guardrail_sharpe",
        "guardrail_drawdown",
        "guardrail_cost",
        "guardrail_historical_effective_names",
        "guardrail_current_effective_names",
        "guardrail_historical_target_hhi",
        "guardrail_current_target_hhi",
        "guardrail_historical_target_weight",
        "guardrail_current_target_weight",
        "guardrail_policy_input",
        "guardrail_execution",
        "guardrail_current_target",
        "guardrail_contribution_complete",
    ]
    contribution_guardrails = [
        "guardrail_security_day_contribution",
        "guardrail_security_absolute_contribution_share",
        "guardrail_leave_one_security",
    ]
    metric_available = result["comparison_status"].eq("available")
    result["standard_guardrail_pass"] = result[standard_guardrails].all(axis=1)
    result["contribution_guardrail_pass"] = result[contribution_guardrails].all(axis=1)
    result["absolute_guardrail_pass"] = (
        result["standard_guardrail_pass"] & result["contribution_guardrail_pass"]
    )

    guardrail_breaches: list[list[str]] = []
    contribution_breaches: list[list[str]] = []
    penalties: list[float] = []
    for _, row in result.iterrows():
        standard = [
            name.removeprefix("guardrail_") for name in standard_guardrails if not bool(row[name])
        ]
        contribution = [
            name.removeprefix("guardrail_")
            for name in contribution_guardrails
            if not bool(row[name])
        ]
        guardrail_breaches.append([*standard, *contribution])
        contribution_breaches.append(contribution)
        if config.selection_extreme_event_action == "penalize" and contribution:
            severity = max(
                _ratio_severity(
                    float(row["max_abs_security_day_contribution"]),
                    config.selection_max_abs_security_day_contribution,
                ),
                _ratio_severity(
                    float(row["max_security_absolute_contribution_share"]),
                    config.selection_max_security_absolute_contribution_share,
                ),
                _ratio_severity(
                    float(row["max_abs_leave_one_security_cagr_delta"]),
                    config.selection_max_leave_one_security_cagr_delta,
                ),
            )
            penalties.append(config.selection_extreme_event_penalty_points * severity)
        else:
            penalties.append(0.0)
    result["guardrail_breaches"] = guardrail_breaches
    result["contribution_guardrail_breaches"] = contribution_breaches
    result["extreme_event_penalty_points"] = penalties
    result["selection_score"] = (
        result["base_composite_score"] - result["extreme_event_penalty_points"]
    ).clip(lower=0.0)
    result["selection_eligible"] = metric_available & result["standard_guardrail_pass"]
    if config.selection_extreme_event_action == "exclude":
        result["selection_eligible"] &= result["contribution_guardrail_pass"]
    result.loc[~result["selection_eligible"], "selection_score"] = np.nan
    result["selection_status"] = "data_excluded"
    result.loc[metric_available & ~result["standard_guardrail_pass"], "selection_status"] = (
        "absolute_guardrail_excluded"
    )
    result.loc[
        metric_available
        & result["standard_guardrail_pass"]
        & ~result["contribution_guardrail_pass"],
        "selection_status",
    ] = (
        "extreme_event_excluded"
        if config.selection_extreme_event_action == "exclude"
        else (
            "extreme_event_penalized"
            if config.selection_extreme_event_action == "penalize"
            else "extreme_event_warning"
        )
    )
    result.loc[result["selection_eligible"], "selection_status"] = "eligible"
    if config.selection_extreme_event_action in {"warn", "penalize"}:
        warned = (
            metric_available
            & result["standard_guardrail_pass"]
            & ~result["contribution_guardrail_pass"]
        )
        result.loc[warned, "selection_status"] = (
            "extreme_event_penalized"
            if config.selection_extreme_event_action == "penalize"
            else "extreme_event_warning"
        )

    candidates = result[result["selection_eligible"]].copy()
    if candidates.empty:
        diagnostic_columns = [
            "factor",
            "policy_id",
            "comparison_status",
            "comparison_eligible",
            "comparison_reason",
            "exclusion_reason_codes",
            "exclusion_reasons",
            "selection_status",
            "guardrail_breaches",
            "observations",
            "ending_nav_available",
            "risk_metrics_complete",
            "valuation_coverage_ratio",
            "daily_risk_observations",
            "policy_input_coverage_ratio",
            "policy_input_reason_counts",
            "policy_input_failures",
            "execution_coverage_ratio",
            "blocked_execution_count",
            "total_unpriceable_target_count",
            "current_portfolio_available",
            "current_portfolio_input_reasons",
            "contribution_diagnostics_complete",
            "contribution_diagnostics_reason",
        ]
        detail = result.loc[
            :, [column for column in diagnostic_columns if column in result.columns]
        ].to_dict(orient="records")
        raise NoEligibleFactorError(detail)
    sort_columns = [
        "selection_score",
        "base_composite_score",
        "max_abs_leave_one_security_cagr_delta",
        "max_abs_security_day_contribution",
        "sortino",
        "calmar",
        "max_drawdown",
        "cagr",
        "sharpe",
        "stability",
        "annualized_cost_drag",
        "annualized_turnover",
        "factor",
        "policy_id",
    ]
    ascending = [
        False,
        False,
        True,
        True,
        False,
        False,
        False,
        False,
        False,
        False,
        True,
        True,
        True,
        True,
    ]
    ordered = candidates.sort_values(sort_columns, ascending=ascending, kind="stable")
    selected_index = ordered.index[0]
    result["selected"] = False
    result.loc[selected_index, "selected"] = True
    result["rank"] = np.nan
    result.loc[ordered.index, "rank"] = np.arange(1, len(ordered) + 1, dtype=int)
    result = result.sort_values(
        ["selected", "rank", "factor", "policy_id"],
        ascending=[False, True, True, True],
        na_position="last",
        kind="stable",
    ).reset_index(drop=True)
    selected_row = result.loc[result["selected"]].iloc[0]
    selected_factor = str(selected_row["factor"])
    selected_policy = str(selected_row["policy_id"])
    if selected_policy != FIXED_WEIGHTING_POLICY:
        raise ValueError("factor selection attempted to optimize a non-fixed weighting policy")
    reason = (
        f"Selected factor {selected_factor} under the fixed {selected_policy} methodology with "
        f"selection score {float(selected_row['selection_score']):.4f} from every metric-complete "
        f"independent factor under {ABSOLUTE_GUARDRAIL_VERSION}. Net Sharpe="
        f"{float(selected_row['sharpe']):.4f}, MDD={float(selected_row['max_drawdown']):.4f}, "
        f"annualized cost drag={float(selected_row['annualized_cost_drag']):.4f}, maximum "
        f"exact one-session security contribution="
        f"{float(selected_row['max_abs_security_day_contribution']):.4f}."
    )
    decision = {
        "method": "fixed_policy_factor_selection",
        "version": FACTOR_SELECTION_VERSION,
        "dynamicSelection": True,
        "weightingPolicyOptimized": False,
        "bestFactor": selected_factor,
        "weightingPolicy": selected_policy,
        "weightingPolicyVersion": POLICY_REGISTRY[selected_policy]["version"],
        "bestBaseCompositeScore": float(selected_row["base_composite_score"]),
        "bestExtremeEventPenaltyPoints": float(selected_row["extreme_event_penalty_points"]),
        "bestSelectionScore": float(selected_row["selection_score"]),
        "guardrailProfile": _absolute_guardrail_profile(config),
        "tieBreakPolicy": list(FACTOR_SELECTION_TIE_BREAK_POLICY),
        "reason": reason,
    }
    return result, selected_factor, selected_policy, reason, decision


def _grid_accounting(
    ranking: pd.DataFrame,
    definitions: pd.DataFrame,
) -> dict[str, Any]:
    canonical = _canonical_factor_definitions()
    canonical_names = set(canonical["factor"].astype(str))
    observed_definition_names = set(definitions["factor"].astype(str))
    if observed_definition_names != canonical_names:
        raise ValueError(
            "factor-policy grid canonical factor definitions are incomplete: "
            + json.dumps(
                {
                    "missing": sorted(canonical_names.difference(observed_definition_names)),
                    "unexpected": sorted(observed_definition_names.difference(canonical_names)),
                },
                ensure_ascii=False,
            )
        )
    aliases = definitions["compatibility_alias_of"].notna()
    independent = set(
        definitions.loc[
            definitions["selection_eligible"].fillna(True).astype(bool) & ~aliases,
            "factor",
        ].astype(str)
    )
    expected_pairs = {(factor, policy) for factor in independent for policy in WEIGHTING_POLICIES}
    independent_rows = ranking[ranking["factor"].isin(independent)]
    observed_pairs = list(
        zip(
            independent_rows["factor"].astype(str),
            independent_rows["policy_id"].astype(str),
            strict=True,
        )
    )
    duplicates = sorted({pair for pair in observed_pairs if observed_pairs.count(pair) > 1})
    missing = sorted(expected_pairs.difference(observed_pairs))
    unexpected = sorted(set(observed_pairs).difference(expected_pairs))
    if duplicates or missing or unexpected:
        raise ValueError(
            "factor-policy grid invariant failed: "
            + json.dumps(
                {"duplicates": duplicates, "missing": missing, "unexpected": unexpected},
                ensure_ascii=False,
            )
        )
    available = independent_rows["comparison_status"].eq("available")
    reason_counts: dict[str, int] = {}
    for codes in independent_rows.loc[~available, "exclusion_reason_codes"]:
        if not codes:
            raise ValueError("excluded independent factor-policy row has no exact reason")
        for code in codes:
            reason_counts[str(code)] = reason_counts.get(str(code), 0) + 1
    common_count = sum(
        bool(group["comparison_status"].eq("available").all())
        for _, group in independent_rows.groupby("factor", sort=False)
    )
    alias_factor_count = int(aliases.sum())
    alias_pair_count = int(
        ranking["factor"].isin(definitions.loc[aliases, "factor"].astype(str)).sum()
    )
    expected_alias_pairs = alias_factor_count * len(WEIGHTING_POLICIES)
    if alias_pair_count != expected_alias_pairs:
        raise ValueError("diagnostic alias factor-policy grid is incomplete")
    expected_count = len(expected_pairs)
    if (
        len(independent) != CANONICAL_INDEPENDENT_FACTOR_COUNT
        or alias_factor_count != CANONICAL_ALIAS_FACTOR_COUNT
        or expected_count != CANONICAL_INDEPENDENT_FACTOR_COUNT * len(WEIGHTING_POLICIES)
        or len(ranking) != CANONICAL_TOTAL_FACTOR_COUNT * len(WEIGHTING_POLICIES)
    ):
        raise ValueError("factor-policy grid does not satisfy the canonical 64/61/3 registry")
    available_count = int(available.sum())
    excluded_count = expected_count - available_count
    if available_count + excluded_count != expected_count:
        raise ValueError("available plus excluded factor-policy rows must equal expected rows")
    return {
        "version": 2,
        "independentFactorCount": len(independent),
        "expectedIndependentFactorCount": expected_count,
        "evaluatedIndependentFactorCount": len(independent_rows),
        "availableIndependentFactorCount": available_count,
        "excludedIndependentFactorCount": excluded_count,
        "missingIndependentFactorCount": 0,
        "diagnosticAliasFactorCount": alias_factor_count,
        "commonComparableFactorCount": common_count,
        "exclusionReasonCounts": dict(sorted(reason_counts.items())),
        "invariant": (
            "availableIndependentFactorCount + excludedIndependentFactorCount "
            "= expectedIndependentFactorCount"
        ),
    }


def _policy_diagnostics(
    ranking: pd.DataFrame,
    definitions: pd.DataFrame,
    selected_factor: str,
    selected_policy: str,
) -> pd.DataFrame:
    independent = set(
        definitions.loc[
            definitions["selection_eligible"].fillna(True).astype(bool)
            & definitions["compatibility_alias_of"].isna(),
            "factor",
        ].astype(str)
    )
    independent_rows = ranking[ranking["factor"].isin(independent)]
    available_sets = {
        policy: set(
            independent_rows.loc[
                independent_rows["policy_id"].eq(policy)
                & independent_rows["comparison_status"].eq("available"),
                "factor",
            ].astype(str)
        )
        for policy in WEIGHTING_POLICIES
    }
    common = set.intersection(*(available_sets[policy] for policy in WEIGHTING_POLICIES))
    metric_columns = (
        "cagr",
        "sharpe",
        "sortino",
        "calmar",
        "max_drawdown",
        "annualized_turnover",
        "annualized_cost_drag",
        "median_target_effective_names",
        "min_target_effective_names",
        "median_target_hhi",
        "max_target_hhi",
        "median_target_cash_weight",
        "median_target_top1_weight",
        "median_target_top5_weight",
        "max_target_weight",
        "max_abs_security_observation_contribution",
        "max_security_absolute_contribution_share",
        "max_abs_leave_one_security_cagr_delta",
    )
    rows: list[dict[str, object]] = []
    for policy in WEIGHTING_POLICIES:
        frame = independent_rows[independent_rows["policy_id"].eq(policy)]
        paired = frame[frame["factor"].isin(common)]
        row: dict[str, object] = {
            "policy_id": policy,
            "policy_version": POLICY_REGISTRY[policy]["version"],
            "diagnostic_only": True,
            "paired_factor_count": len(paired),
            "available_factor_count": len(available_sets[policy]),
            "excluded_factor_count": len(independent) - len(available_sets[policy]),
            "data_status": (
                "complete" if len(available_sets[policy]) == len(independent) else "partial"
            ),
            "contains_selected_pair": policy == selected_policy,
            "selected_factor_if_policy": selected_factor if policy == selected_policy else None,
            "current_available_independent_factor_count": int(
                frame["current_portfolio_available"].fillna(False).astype(bool).sum()
            ),
            "current_median_holding_count": float(
                pd.to_numeric(paired["current_holding_count"], errors="coerce").median()
            ),
            "current_median_cash_weight": float(
                pd.to_numeric(paired["current_cash_weight"], errors="coerce").median()
            ),
        }
        for metric in metric_columns:
            row[metric] = float(pd.to_numeric(paired[metric], errors="coerce").median())
        rows.append(row)
    order = {policy: position for position, policy in enumerate(WEIGHTING_POLICIES)}
    return (
        pd.DataFrame(rows)
        .assign(_order=lambda frame: frame["policy_id"].map(order))
        .sort_values("_order")
        .drop(columns="_order")
        .reset_index(drop=True)
    )


def _latest_portfolios(
    factor_scores: dict[str, pd.Series],
    market: MarketData,
    config: RunConfig,
    policy_id: str,
    trailing_liquidity: pd.DataFrame,
    trailing_market_cap: pd.DataFrame,
) -> dict[str, ModelPortfolio]:
    analysis_columns = [column for column in market.prices.columns if column != market.benchmark]
    names = _names_by_symbol(market)
    return {
        factor: construct_model_portfolio(
            factor,
            market.as_of,
            scores.reindex(analysis_columns),
            market.prices.loc[market.as_of].reindex(analysis_columns),
            market.eligibility_mask.loc[market.as_of].reindex(analysis_columns),
            config,
            policy_id=policy_id,
            trailing_dollar_volume=trailing_liquidity.loc[market.as_of].reindex(analysis_columns),
            trailing_market_cap=trailing_market_cap.loc[market.as_of].reindex(analysis_columns),
            names=names,
        )
        for factor, scores in factor_scores.items()
    }


def _benchmark_metrics(market: MarketData, config: RunConfig) -> dict[str, object]:
    if market.benchmark not in market.prices:
        return {"available": False}
    returns = mark_to_last_observed_returns(market.prices[[market.benchmark]])[market.benchmark]
    summary = metric_summary(
        returns.tail(config.evaluation_window_days),
        risk_free_rate=config.annual_cash_return,
    )
    return {"available": True, **summary}


def _date_text(value: object) -> str:
    return pd.Timestamp(value).date().isoformat()


def _factor_rank_ic_diagnostic_row(
    *,
    factor: str,
    category: str,
    panel: pd.DataFrame,
    signal_dates: pd.DatetimeIndex,
    forward_returns: pd.DataFrame,
    latest_date: pd.Timestamp,
) -> dict[str, Any]:
    """Compute exact pairwise cross-sectional Spearman IC without retaining the panel."""

    scores = (
        panel.reindex(index=signal_dates, columns=forward_returns.columns)
        .apply(pd.to_numeric, errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
    )
    future = forward_returns.reindex(index=signal_dates, columns=scores.columns)
    common = scores.notna() & future.notna()
    common_counts = common.sum(axis=1).astype(int)

    # Ranking must happen after pairwise deletion. Ranking the full future-return
    # cross-section first would change ranks whenever a factor has a missing score.
    score_ranks = scores.where(common).rank(axis=1, method="average")
    future_ranks = future.where(common).rank(axis=1, method="average")
    daily_ic = score_ranks.corrwith(future_ranks, axis=1).where(common_counts.ge(3))
    daily_ic = daily_ic.replace([np.inf, -np.inf], np.nan).dropna()
    valid_counts = common_counts.reindex(daily_ic.index)
    latest_finite = int(
        pd.to_numeric(panel.reindex(index=[latest_date]).iloc[0], errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
        .notna()
        .sum()
    )

    base: dict[str, Any] = {
        "factor": factor,
        "category": category,
        "horizonSessions": FACTOR_DIAGNOSTICS_RANK_IC_HORIZON_SESSIONS,
        "observations": int(len(daily_ic)),
        "latestFiniteCount": latest_finite,
    }
    if daily_ic.empty:
        return {
            **base,
            "available": False,
            "unavailableReason": "no_valid_cross_sectional_observations",
            "mean": None,
            "median": None,
            "standardDeviation": None,
            "positiveRate": None,
            "startDate": None,
            "endDate": None,
            "minimumSecurityCount": None,
            "averageSecurityCount": None,
            "maximumSecurityCount": None,
        }
    return {
        **base,
        "available": True,
        "unavailableReason": None,
        "mean": float(daily_ic.mean()),
        "median": float(daily_ic.median()),
        "standardDeviation": float(daily_ic.std(ddof=0)),
        "positiveRate": float(daily_ic.gt(0.0).mean()),
        "startDate": _date_text(daily_ic.index.min()),
        "endDate": _date_text(daily_ic.index.max()),
        "minimumSecurityCount": int(valid_counts.min()),
        "averageSecurityCount": float(valid_counts.mean()),
        "maximumSecurityCount": int(valid_counts.max()),
    }


def _diagnostic_row_sort_key(row: Mapping[str, Any], value_field: str) -> tuple[object, ...]:
    value = row.get(value_field)
    available = row.get("available") is True and value is not None and np.isfinite(float(value))
    return (
        0 if available else 1,
        -float(value) if available else 0.0,
        -int(row.get("observations", 0)),
        str(row.get("factor") or ""),
    )


def _mean_or_none(values: Collection[object]) -> float | None:
    numeric = pd.to_numeric(pd.Series(list(values), dtype=object), errors="coerce").dropna()
    return float(numeric.mean()) if not numeric.empty else None


def _build_factor_diagnostics(
    *,
    definitions: pd.DataFrame,
    rank_ic_rows: Mapping[str, Mapping[str, Any]],
    latest_scores: Mapping[str, pd.Series],
    signal_dates: pd.DatetimeIndex,
    diagnostic_date: pd.Timestamp,
) -> dict[str, Any]:
    aliases = definitions.loc[
        definitions["compatibility_alias_of"].notna(),
        ["factor", "compatibility_alias_of"],
    ]
    alias_rows = sorted(
        (
            {
                "factor": str(row.factor),
                "canonicalFactor": str(row.compatibility_alias_of),
            }
            for row in aliases.itertuples(index=False)
        ),
        key=lambda row: row["factor"],
    )
    independent_definitions = definitions.loc[
        definitions["compatibility_alias_of"].isna()
        & definitions["selection_eligible"].fillna(True).astype(bool)
    ].copy()
    independent = independent_definitions["factor"].astype(str).tolist()
    expected = set(independent)
    if set(rank_ic_rows) != expected or set(latest_scores) != expected:
        raise ValueError("implementation_error_factor_diagnostics_execution_set")
    categories = independent_definitions.set_index("factor")["category"].astype(str).to_dict()

    ordered_rank_ic = sorted(
        (dict(rank_ic_rows[factor]) for factor in independent),
        key=lambda row: _diagnostic_row_sort_key(row, "mean"),
    )
    for rank, row in enumerate(ordered_rank_ic, start=1):
        row["rank"] = rank

    latest_frame = pd.DataFrame({factor: latest_scores[factor] for factor in independent})
    latest_frame = latest_frame.apply(pd.to_numeric, errors="coerce").replace(
        [np.inf, -np.inf], np.nan
    )
    correlations = latest_frame.corr(method="spearman", min_periods=3)
    finite = latest_frame.notna().astype("int64")
    common_counts = finite.T.dot(finite)
    pairs: list[dict[str, Any]] = []
    peer_values: dict[str, list[tuple[str, float, int]]] = {factor: [] for factor in independent}
    for position, factor_a in enumerate(independent):
        for factor_b in independent[position + 1 :]:
            correlation = correlations.at[factor_a, factor_b]
            if not np.isfinite(correlation):
                continue
            signed = float(correlation)
            common_count = int(common_counts.at[factor_a, factor_b])
            pair = {
                "leftFactor": min(factor_a, factor_b),
                "rightFactor": max(factor_a, factor_b),
                "signedCorr": signed,
                "absCorr": abs(signed),
                "commonSecurityCount": common_count,
            }
            pairs.append(pair)
            peer_values[factor_a].append((factor_b, signed, common_count))
            peer_values[factor_b].append((factor_a, signed, common_count))

    redundancy_rows: list[dict[str, Any]] = []
    latest_counts = latest_frame.notna().sum(axis=0).astype(int).to_dict()
    for factor in independent:
        peers = sorted(peer_values[factor], key=lambda item: (-abs(item[1]), item[0]))
        base = {
            "factor": factor,
            "category": categories[factor],
            "latestFiniteCount": int(latest_counts[factor]),
        }
        if not peers:
            redundancy_rows.append(
                {
                    **base,
                    "available": False,
                    "unavailableReason": "no_valid_peer_correlation",
                    "nearestFactor": None,
                    "signedCorr": None,
                    "absCorr": None,
                    "validPeerCount": 0,
                    "highCorrPeerCount": 0,
                    "commonSecurityCount": 0,
                }
            )
            continue
        nearest, signed, common_count = peers[0]
        redundancy_rows.append(
            {
                **base,
                "available": True,
                "unavailableReason": None,
                "nearestFactor": nearest,
                "signedCorr": signed,
                "absCorr": abs(signed),
                "validPeerCount": len(peers),
                "highCorrPeerCount": sum(
                    abs(value) >= FACTOR_DIAGNOSTICS_REDUNDANCY_THRESHOLD for _, value, _ in peers
                ),
                "commonSecurityCount": common_count,
            }
        )
    redundancy_rows.sort(key=lambda row: _diagnostic_row_sort_key(row, "absCorr"))
    for rank, row in enumerate(redundancy_rows, start=1):
        row["rank"] = rank

    ordered_pairs = sorted(
        pairs,
        key=lambda row: (
            -float(row["absCorr"]),
            str(row["leftFactor"]),
            str(row["rightFactor"]),
        ),
    )
    top_pairs = [dict(row) for row in ordered_pairs[:FACTOR_DIAGNOSTICS_TOP_PAIR_COUNT]]
    for rank, row in enumerate(top_pairs, start=1):
        row["rank"] = rank

    rank_ic_by_factor = {str(row["factor"]): row for row in ordered_rank_ic}
    redundancy_by_factor = {str(row["factor"]): row for row in redundancy_rows}
    category_rows: list[dict[str, Any]] = []
    for category, group in independent_definitions.groupby("category", sort=True):
        factors = sorted(group["factor"].astype(str))
        ic_available = [
            rank_ic_by_factor[factor]
            for factor in factors
            if rank_ic_by_factor[factor]["available"] is True
        ]
        redundancy_available = [
            redundancy_by_factor[factor]
            for factor in factors
            if redundancy_by_factor[factor]["available"] is True
        ]
        category_rows.append(
            {
                "category": str(category),
                "factorCount": len(factors),
                "availableRankIcFactorCount": len(ic_available),
                "averageMeanRankIc": _mean_or_none(row["mean"] for row in ic_available),
                "averagePositiveRate": _mean_or_none(row["positiveRate"] for row in ic_available),
                "averageMaxAbsCorr": _mean_or_none(row["absCorr"] for row in redundancy_available),
                "highCorrFactorCount": sum(
                    int(row["highCorrPeerCount"]) > 0 for row in redundancy_available
                ),
                "exampleFactors": factors[:4],
            }
        )
    category_rows.sort(key=lambda row: (-int(row["factorCount"]), str(row["category"])))

    available_ic_count = sum(row["available"] is True for row in ordered_rank_ic)
    available_redundancy_count = sum(row["available"] is True for row in redundancy_rows)
    return {
        "contractVersion": FACTOR_DIAGNOSTICS_CONTRACT_VERSION,
        "scope": {
            "factorCount": len(definitions),
            "independentFactorCount": len(independent),
            "diagnosticAliasCount": len(alias_rows),
            "aliasHandling": "excluded_from_rankings",
            "aliases": alias_rows,
        },
        "rankIc": {
            "method": FACTOR_DIAGNOSTICS_RANK_IC_METHOD,
            "priceBasis": "analysis_adjusted_close",
            "horizonSessions": FACTOR_DIAGNOSTICS_RANK_IC_HORIZON_SESSIONS,
            "maximumSignalSessions": FACTOR_DIAGNOSTICS_MAX_SIGNAL_SESSIONS,
            "requestedSignalSessions": len(signal_dates),
            "requestedStartDate": _date_text(signal_dates.min()),
            "requestedEndDate": _date_text(signal_dates.max()),
            "signalDates": [_date_text(date) for date in signal_dates],
            "overlapping": True,
            "availableFactorCount": available_ic_count,
            "unavailableFactorCount": len(independent) - available_ic_count,
            "rows": ordered_rank_ic,
        },
        "redundancy": {
            "method": FACTOR_DIAGNOSTICS_REDUNDANCY_METHOD,
            "diagnosticDate": _date_text(diagnostic_date),
            "thresholdAbs": FACTOR_DIAGNOSTICS_REDUNDANCY_THRESHOLD,
            "availableFactorCount": available_redundancy_count,
            "unavailableFactorCount": len(independent) - available_redundancy_count,
            "eligiblePairCount": len(ordered_pairs),
            "highRedundancyPairCount": sum(
                float(row["absCorr"]) >= FACTOR_DIAGNOSTICS_REDUNDANCY_THRESHOLD
                for row in ordered_pairs
            ),
            "highRedundancyFactorCount": sum(
                int(row["highCorrPeerCount"]) > 0 for row in redundancy_rows
            ),
            "rows": redundancy_rows,
            "topPairs": top_pairs,
        },
        "categorySummary": category_rows,
    }


def run_analysis(
    config: RunConfig,
    *,
    market_data: MarketData | None = None,
) -> AnalysisResult:
    started = perf_counter()
    config.validate()
    market = market_data if market_data is not None else load_market_data(config)
    input_snapshot_paths = (
        write_market_data_snapshot(market, config.output_dir / "input")
        if config.export_input_snapshot
        else {}
    )
    prices = _analysis_prices(market)
    eligibility = market.eligibility_mask.reindex(columns=prices.columns).fillna(False)
    dollar_volumes = market.dollar_volumes.reindex(index=prices.index, columns=prices.columns)
    liquidity = _liquidity_context(dollar_volumes, config)
    market_caps = market.market_caps.reindex(index=prices.index, columns=prices.columns)
    definitions = _canonical_factor_definitions()
    independent_definitions = definitions.loc[
        definitions["compatibility_alias_of"].isna()
        & definitions["selection_eligible"].fillna(True).astype(bool)
    ]
    independent_factors = set(independent_definitions["factor"].astype(str))
    category_by_factor = (
        independent_definitions.set_index("factor")["category"].astype(str).to_dict()
    )
    diagnostic_session_count = min(FACTOR_DIAGNOSTICS_MAX_SIGNAL_SESSIONS, len(prices.index))
    diagnostic_signal_dates = pd.DatetimeIndex(prices.index[-diagnostic_session_count:])
    horizon = FACTOR_DIAGNOSTICS_RANK_IC_HORIZON_SESSIONS
    diagnostic_forward_returns = pd.DataFrame(
        np.nan,
        index=diagnostic_signal_dates,
        columns=prices.columns,
        dtype=float,
    )
    if len(diagnostic_signal_dates) > horizon:
        valid_signal_dates = diagnostic_signal_dates[:-horizon]
        future_price_dates = diagnostic_signal_dates[horizon:]
        base_prices = prices.reindex(index=valid_signal_dates, columns=prices.columns)
        future_prices = prices.reindex(index=future_price_dates, columns=prices.columns).copy()
        future_prices.index = valid_signal_dates
        diagnostic_forward_returns.loc[valid_signal_dates] = future_prices.divide(base_prices) - 1.0
    latest_scores: dict[str, pd.Series] = {}
    diagnostic_latest_scores: dict[str, pd.Series] = {}
    diagnostic_rank_ic_rows: dict[str, dict[str, Any]] = {}
    all_backtests: dict[str, dict[str, BacktestResult]] = {
        policy: {} for policy in WEIGHTING_POLICIES
    }

    def consume_factor(factor: str, panel: pd.DataFrame) -> None:
        latest_scores[factor] = panel.loc[market.as_of].copy()
        if factor in independent_factors:
            diagnostic_latest_scores[factor] = panel.loc[market.as_of].copy()
            diagnostic_rank_ic_rows[factor] = _factor_rank_ic_diagnostic_row(
                factor=factor,
                category=category_by_factor[factor],
                panel=panel,
                signal_dates=diagnostic_signal_dates,
                forward_returns=diagnostic_forward_returns,
                latest_date=pd.Timestamp(market.as_of),
            )
        for policy in WEIGHTING_POLICIES:
            all_backtests[policy][factor] = run_factor_backtest(
                factor,
                policy,
                prices,
                panel,
                config,
                eligibility_mask=eligibility,
                trailing_dollar_volume=liquidity,
                trailing_market_cap=market_caps,
                retain_weight_history=False,
            )

    for factor, panel in iter_factor_scores(prices, eligibility_mask=eligibility):
        consume_factor(factor, panel)
    advanced = compute_advanced_factor_scores(
        prices,
        volumes=market.volumes.reindex(columns=prices.columns),
        dollar_volumes=dollar_volumes,
        eligibility_mask=eligibility,
    )
    advanced_input_issues = _advanced_factor_input_issues(advanced.status)
    for factor, panel in advanced.scores.items():
        consume_factor(factor, panel)
    expected_factor_names = set(definitions["factor"].astype(str))
    observed_factor_names = set(latest_scores)
    if observed_factor_names != expected_factor_names:
        raise ValueError(
            "implementation_error_canonical_factor_execution_set: "
            + json.dumps(
                {
                    "missing": sorted(expected_factor_names.difference(observed_factor_names)),
                    "unexpected": sorted(observed_factor_names.difference(expected_factor_names)),
                },
                ensure_ascii=False,
            )
        )
    factor_diagnostics = _build_factor_diagnostics(
        definitions=definitions,
        rank_ic_rows=diagnostic_rank_ic_rows,
        latest_scores=diagnostic_latest_scores,
        signal_dates=diagnostic_signal_dates,
        diagnostic_date=pd.Timestamp(market.as_of),
    )
    evaluation_index = pd.DatetimeIndex(prices.index[-config.evaluation_window_days :])
    policy_grid_reasons = _policy_grid_reasons(
        all_backtests,
        evaluation_index,
        expected_factors=latest_scores,
    )
    portfolios_by_policy = {
        policy: _latest_portfolios(
            latest_scores,
            market,
            config,
            policy,
            liquidity,
            market_caps,
        )
        for policy in WEIGHTING_POLICIES
    }
    raw_by_policy: list[pd.DataFrame] = []
    for policy in WEIGHTING_POLICIES:
        raw_by_policy.append(
            _raw_factor_metrics(
                policy,
                all_backtests[policy],
                definitions,
                config,
                evaluation_index,
                portfolios=portfolios_by_policy[policy],
                policy_grid_reasons=policy_grid_reasons,
                factor_input_issues=advanced_input_issues,
            )
        )
    factor_metrics = pd.concat(raw_by_policy, ignore_index=True, sort=False)
    factor_scored = _with_exclusion_accounting(
        _score_factor_metrics(factor_metrics, config),
        config,
    )
    (
        factor_ranking,
        selected_factor,
        selected_policy,
        selected_reason,
        factor_decision,
    ) = _apply_factor_guardrails(
        factor_scored,
        config,
    )
    names = _names_by_symbol(market)
    factor_holding_histories: dict[str, dict[str, Any]] = {}

    def retain_selected_policy_history(factor: str, panel: pd.DataFrame) -> None:
        original = all_backtests[selected_policy][factor]
        replayed = run_factor_backtest(
            factor,
            selected_policy,
            prices,
            panel,
            config,
            eligibility_mask=eligibility,
            trailing_dollar_volume=liquidity,
            trailing_market_cap=market_caps,
            retain_weight_history=True,
            weight_history_tail_sessions=SELECTED_HOLDING_HISTORY_SESSION_COUNT,
        )
        _assert_selected_history_replay_matches(original, replayed)
        factor_holding_histories[factor] = _backtest_holding_history_payload(
            factor=factor,
            policy_id=selected_policy,
            backtest=replayed,
            names=names,
        )
        if factor == selected_factor:
            all_backtests[selected_policy][factor] = replayed

    for factor, panel in iter_factor_scores(prices, eligibility_mask=eligibility):
        retain_selected_policy_history(factor, panel)
    for factor, panel in advanced.scores.items():
        retain_selected_policy_history(factor, panel)
    if set(factor_holding_histories) != expected_factor_names:
        raise ValueError("implementation_error_factor_holding_history_execution_set")
    grid_accounting = _grid_accounting(factor_ranking, definitions)
    factor_decision = {
        **factor_decision,
        "evaluationStart": evaluation_index.min().date().isoformat(),
        "evaluationEnd": evaluation_index.max().date().isoformat(),
        "evaluationWindowDays": len(evaluation_index),
        "minimumObservations": config.min_evaluation_observations,
        "minimumValuationCoverage": config.min_valuation_coverage,
        "minimumDailyRiskObservations": config.min_daily_risk_observations,
        "selectionEligibleFactorCount": int(factor_ranking["selection_eligible"].sum()),
        "factorAccounting": grid_accounting,
    }
    policy_comparison = _policy_diagnostics(
        factor_ranking,
        definitions,
        selected_factor,
        selected_policy,
    )
    policy_decision = {
        "fixed": True,
        "optimized": False,
        "policyId": FIXED_WEIGHTING_POLICY,
        "policyCount": len(WEIGHTING_POLICIES),
        "commonComparableFactorCount": grid_accounting["commonComparableFactorCount"],
        "note": "Every factor is evaluated under the same fixed allocation methodology.",
    }
    portfolios = portfolios_by_policy[selected_policy]
    selected_portfolio = portfolios[selected_factor]
    return AnalysisResult(
        generated_at_utc=datetime.now(UTC),
        runtime_seconds=perf_counter() - started,
        max_rss_bytes=_max_rss_bytes(),
        config=config,
        market_data=market,
        factor_scores=latest_scores,
        backtests=all_backtests[selected_policy],
        policy_factor_metrics=factor_ranking,
        policy_comparison=policy_comparison,
        selected_policy=selected_policy,
        selected_policy_reason=selected_reason,
        policy_selection_decision=policy_decision,
        factor_ranking=factor_ranking,
        selected_factor=selected_factor,
        selected_reason=selected_reason,
        factor_selection_decision=factor_decision,
        model_portfolio=selected_portfolio,
        factor_portfolios=portfolios,
        factor_definitions=definitions,
        benchmark_metrics=_benchmark_metrics(market, config),
        factor_diagnostics=factor_diagnostics,
        factor_holding_histories=factor_holding_histories,
        grid_accounting=grid_accounting,
        result_identity=build_result_identity(config, market),
        advanced_factor_status=advanced.status,
        input_snapshot_paths=input_snapshot_paths,
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, pd.DataFrame):
        return _json_safe(value.to_dict(orient="records"))
    if isinstance(value, pd.Series):
        return _json_safe(value.to_dict())
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return _json_safe(value.tolist())
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if np.isfinite(number) else None
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def _normalized_curve(series: pd.Series, dates: pd.DatetimeIndex) -> list[float | None]:
    numeric = pd.to_numeric(series, errors="coerce")
    aligned = numeric.reindex(dates)
    valid = aligned.dropna()
    if valid.empty:
        return [None] * len(dates)
    # ``dates`` includes the session immediately before the evaluation-return
    # window. Keeping that explicit 1.0 boundary makes the first evaluation
    # return visible and prevents a browser from silently rebasing it away.
    base = float(valid.iloc[0])
    if not np.isfinite(base) or base == 0.0:
        return [None] * len(dates)
    return [float(value / base) if pd.notna(value) else None for value in aligned]


def _comparison_price_panel(market: MarketData, config: RunConfig) -> pd.DataFrame:
    """Return configured comparison prices without admitting them to the stock universe."""

    configured = list(config.comparison_benchmarks)
    separate = getattr(market, "comparison_prices", pd.DataFrame())
    panel = pd.DataFrame(index=market.prices.index)
    for symbol in configured:
        if isinstance(separate, pd.DataFrame) and symbol in separate:
            panel[symbol] = pd.to_numeric(separate[symbol].reindex(panel.index), errors="coerce")
        elif symbol in market.prices:
            # Backward-compatible replay of v2 snapshots keeps SPY in the
            # canonical analysis matrix and has no separate comparator panel.
            panel[symbol] = pd.to_numeric(
                market.prices[symbol].reindex(panel.index), errors="coerce"
            )
    return panel


def _unavailable_period_metrics(basis: str, reason: str) -> dict[str, Any]:
    return {
        "available": False,
        "unavailableReason": reason,
        "basis": basis,
        "returnObservationCount": 0,
        "requiredReturnCount": 0,
        "riskObservationCount": 0,
        "riskMetricsExact": False,
        **{metric: None for metric in PERFORMANCE_METRIC_KEYS},
    }


def _period_metric_payload(
    returns: pd.Series,
    *,
    base_value: object,
    end_value: object,
    basis: str,
    risk_free_rate: float,
    return_interval_sessions: pd.Series | None = None,
) -> dict[str, Any]:
    numeric = pd.to_numeric(returns, errors="coerce").replace([np.inf, -np.inf], np.nan)
    required_count = len(numeric)
    if required_count <= 0:
        return _unavailable_period_metrics(basis, "insufficient_return_history")
    try:
        base = float(base_value)
        end = float(end_value)
    except (TypeError, ValueError):
        return _unavailable_period_metrics(basis, "missing_boundary_value")
    if not np.isfinite(base) or not np.isfinite(end) or base <= 0.0 or end < 0.0:
        return _unavailable_period_metrics(basis, "missing_boundary_value")
    if pd.isna(numeric.iloc[-1]):
        return _unavailable_period_metrics(basis, "missing_terminal_return")

    intervals = (
        pd.to_numeric(return_interval_sessions.reindex(numeric.index), errors="coerce")
        .fillna(0)
        .astype(int)
        if return_interval_sessions is not None
        else None
    )
    if intervals is None:
        inferred: list[int] = []
        missing_run = 0
        for value in numeric:
            if pd.isna(value):
                missing_run += 1
                inferred.append(0)
            else:
                inferred.append(missing_run + 1)
                missing_run = 0
        intervals = pd.Series(inferred, index=numeric.index, dtype=int)
    single_session = numeric.where(intervals.eq(1)).dropna()
    summary = metric_summary(
        numeric,
        risk_free_rate=risk_free_rate,
        return_interval_sessions=intervals,
    )
    return {
        "available": True,
        "unavailableReason": None,
        "basis": basis,
        "returnObservationCount": int(numeric.notna().sum()),
        "requiredReturnCount": required_count,
        "riskObservationCount": len(single_session),
        "riskMetricsExact": bool(numeric.notna().all() and intervals.eq(1).all()),
        "cumulativeReturn": end / base - 1.0,
        "sharpe": summary["sharpe"],
        "annualizedVolatility": summary["volatility"],
        "maxDrawdown": summary["max_drawdown"],
        "sortino": summary["sortino"],
        "calmar": summary["calmar"],
        "cvar5": summary["cvar_95"],
        "winRate": summary["win_rate"],
    }


def _period_point_dates(
    market_dates: pd.DatetimeIndex,
    curve_dates: pd.DatetimeIndex,
    period_key: str,
    return_count: int | None,
) -> tuple[pd.DatetimeIndex, str | None]:
    if market_dates.empty:
        return pd.DatetimeIndex([]), "no_market_dates"
    if period_key == "FULL":
        if len(curve_dates) < 2:
            return pd.DatetimeIndex([]), "insufficient_return_history"
        return curve_dates, None
    if period_key == "YTD":
        end = pd.Timestamp(market_dates[-1])
        prior_year_dates = market_dates[market_dates.year < end.year]
        if prior_year_dates.empty:
            return pd.DatetimeIndex([]), "missing_prior_year_end_boundary"
        base = pd.Timestamp(prior_year_dates[-1])
        points = market_dates[(market_dates >= base) & (market_dates <= end)]
        if len(points) < 2:
            return pd.DatetimeIndex([]), "insufficient_return_history"
        return pd.DatetimeIndex(points), None
    assert return_count is not None
    if len(market_dates) < return_count + 1:
        return pd.DatetimeIndex([]), "insufficient_return_history"
    return pd.DatetimeIndex(market_dates[-(return_count + 1) :]), None


def _performance_periods_payload(
    result: AnalysisResult,
    curve_dates: pd.DatetimeIndex,
    comparison_prices: pd.DataFrame,
) -> list[dict[str, Any]]:
    market_dates = pd.DatetimeIndex(result.market_data.prices.index)
    benchmark_order = list(result.config.comparison_benchmarks)
    periods: list[dict[str, Any]] = []
    for key, label, return_count in PERFORMANCE_PERIODS:
        point_dates, period_reason = _period_point_dates(
            market_dates,
            curve_dates,
            key,
            return_count,
        )
        return_dates = point_dates[1:]
        factors: dict[str, dict[str, Any]] = {}
        for factor, backtest in result.backtests.items():
            if period_reason is not None:
                factors[factor] = _unavailable_period_metrics(
                    "net_of_costs_strategy", period_reason
                )
                continue
            equity = pd.to_numeric(backtest.equity.reindex(point_dates), errors="coerce")
            factors[factor] = _period_metric_payload(
                backtest.returns.reindex(return_dates),
                base_value=equity.iloc[0],
                end_value=equity.iloc[-1],
                basis="net_of_costs_strategy",
                risk_free_rate=result.config.annual_cash_return,
                return_interval_sessions=backtest.return_interval_sessions,
            )

        benchmarks: dict[str, dict[str, Any]] = {}
        for symbol in benchmark_order:
            if (
                symbol not in comparison_prices
                or not pd.to_numeric(comparison_prices[symbol], errors="coerce")
                .replace([np.inf, -np.inf], np.nan)
                .notna()
                .any()
            ):
                benchmarks[symbol] = _unavailable_period_metrics(
                    "adjusted_close_buy_and_hold", "comparison_price_unavailable"
                )
                continue
            if period_reason is not None:
                benchmarks[symbol] = _unavailable_period_metrics(
                    "adjusted_close_buy_and_hold", period_reason
                )
                continue
            prices = pd.to_numeric(comparison_prices[symbol].reindex(point_dates), errors="coerce")
            benchmark_returns = mark_to_last_observed_returns(prices.to_frame(symbol))[
                symbol
            ].reindex(return_dates)
            benchmarks[symbol] = _period_metric_payload(
                benchmark_returns,
                base_value=prices.iloc[0],
                end_value=prices.iloc[-1],
                basis="adjusted_close_buy_and_hold",
                risk_free_rate=result.config.annual_cash_return,
            )

        periods.append(
            {
                "key": key,
                "label": label,
                "startDate": point_dates[0].date().isoformat() if len(point_dates) else None,
                "endDate": point_dates[-1].date().isoformat() if len(point_dates) else None,
                "returnObservationCount": max(0, len(point_dates) - 1),
                "unavailableReason": period_reason,
                "factors": factors,
                "benchmarks": benchmarks,
            }
        )
    return periods


def _public_config(config: RunConfig) -> dict[str, Any]:
    return {
        "data_mode": config.data_mode,
        "start_date": config.start_date,
        "end_date": config.end_date,
        "effective_end_date": config.effective_end_date,
        "benchmark": config.benchmark,
        "chart_benchmark": config.chart_benchmark,
        "additional_comparison_benchmarks": list(config.additional_comparison_benchmarks),
        "comparison_benchmarks": list(config.comparison_benchmarks),
        "rebalance_frequency": config.rebalance_frequency,
        "top_n": config.top_n,
        "max_weight": config.max_weight,
        "transaction_cost_bps": config.transaction_cost_bps,
        "slippage_bps": config.slippage_bps,
        "total_cost_bps": config.total_cost_bps,
        "annual_cash_return": config.annual_cash_return,
        "min_history_days": config.min_history_days,
        "min_price": config.min_price,
        "min_avg_dollar_volume": config.min_avg_dollar_volume,
        "min_avg_volume": config.min_avg_volume,
        "liquidity_lookback_days": config.liquidity_lookback_days,
        "min_liquidity_observations": config.min_liquidity_observations,
        "max_price_missing_ratio": config.max_price_missing_ratio,
        "stale_after_days": config.stale_after_days,
        "data_quality_lookback_days": config.data_quality_lookback_days,
        "max_volume_missing_ratio": config.max_volume_missing_ratio,
        "max_extreme_daily_return": config.max_extreme_daily_return,
        "evaluation_window_days": config.evaluation_window_days,
        "min_evaluation_observations": config.min_evaluation_observations,
        "min_valuation_coverage": config.min_valuation_coverage,
        "min_daily_risk_observations": config.min_daily_risk_observations,
        "stability_periods": config.stability_periods,
        "score_weights": config.score_weights,
        "score_winsor_lower": config.score_winsor_lower,
        "score_winsor_upper": config.score_winsor_upper,
        "weighting_policies": list(config.weighting_policies),
        "allocation_score_weight": config.allocation_score_weight,
        "allocation_liquidity_weight": config.allocation_liquidity_weight,
        "allocation_market_cap_weight": config.allocation_market_cap_weight,
        "allocation_rank_floor": config.allocation_rank_floor,
        "market_cap_max_age_days": config.market_cap_max_age_days,
        "market_cap_min_universe_coverage": config.market_cap_min_universe_coverage,
        "selection_min_sharpe": config.selection_min_sharpe,
        "selection_max_drawdown": config.selection_max_drawdown,
        "selection_max_annualized_cost_drag": config.selection_max_annualized_cost_drag,
        "selection_min_effective_names": config.selection_min_effective_names,
        "selection_max_target_hhi": config.selection_max_target_hhi,
        "selection_max_target_weight": config.selection_max_target_weight,
        "selection_max_abs_security_day_contribution": (
            config.selection_max_abs_security_day_contribution
        ),
        "selection_max_security_absolute_contribution_share": (
            config.selection_max_security_absolute_contribution_share
        ),
        "selection_max_leave_one_security_cagr_delta": (
            config.selection_max_leave_one_security_cagr_delta
        ),
        "selection_extreme_event_action": config.selection_extreme_event_action,
        "selection_extreme_event_penalty_points": (config.selection_extreme_event_penalty_points),
        "universe_source_mode": config.universe_source_mode,
        "universe_profile": config.universe_profile,
        "candidate_universe_size": len(config.universe),
        "policy_registry_version": POLICY_REGISTRY_VERSION,
        "factor_selection_version": FACTOR_SELECTION_VERSION,
        "absolute_guardrail_version": ABSOLUTE_GUARDRAIL_VERSION,
    }


def _ordered_positive_weights(weights: pd.Series) -> list[tuple[str, float]]:
    return sorted(
        (
            (str(symbol), float(weight))
            for symbol, weight in weights.items()
            if np.isfinite(weight) and float(weight) > 1e-15
        ),
        key=lambda item: (-item[1], item[0]),
    )


def _held_portfolio_payload(result: AnalysisResult) -> dict[str, Any]:
    backtest = result.backtests[result.selected_factor]
    weights = _ordered_positive_weights(backtest.ending_weights)
    latest_scores = result.factor_scores[result.selected_factor]
    latest_prices = result.market_data.prices.loc[result.market_data.as_of]
    names = _names_by_symbol(result.market_data)
    rows = [
        {
            "rank": rank,
            "symbol": symbol,
            "name": str(names.get(symbol, symbol)),
            "factorScore": latest_scores.get(symbol),
            "latestPrice": latest_prices.get(symbol),
            "weight": float(weight),
        }
        for rank, (symbol, weight) in enumerate(weights, start=1)
    ]
    return {
        "factor": result.selected_factor,
        "weightingPolicyId": result.selected_policy,
        "asOf": result.market_data.as_of.date().isoformat(),
        "lastSignalDate": (
            backtest.last_signal_date.date().isoformat() if backtest.last_signal_date else None
        ),
        "lastExecutionDate": (
            backtest.last_execution_date.date().isoformat()
            if backtest.last_execution_date
            else None
        ),
        "valuationAvailable": bool(backtest.valuation_available.iloc[-1]),
        "cashWeight": backtest.ending_cash_weight,
        "weights": rows,
    }


def _backtest_holding_history_payload(
    *,
    factor: str,
    policy_id: str,
    backtest: BacktestResult,
    names: pd.Series,
) -> dict[str, Any]:
    if (
        backtest.weights.empty
        or backtest.pre_trade_weights.empty
        or backtest.cash_weights.empty
        or not backtest.weights.index.equals(backtest.cash_weights.index)
        or not backtest.weights.index.equals(backtest.pre_trade_weights.index)
        or len(backtest.weights) < SELECTED_HOLDING_HISTORY_SESSION_COUNT
    ):
        raise ValueError(f"backtest holding history is unavailable or incomplete: {factor}")

    history_dates = pd.DatetimeIndex(
        backtest.weights.index[-SELECTED_HOLDING_HISTORY_SESSION_COUNT:]
    )
    last_signal_date: pd.Timestamp | None = None
    last_execution_date: pd.Timestamp | None = None
    execution_metadata: dict[pd.Timestamp, tuple[pd.Timestamp | None, pd.Timestamp | None]] = {}
    for date in backtest.execution_statuses.index:
        normalized_date = pd.Timestamp(date)
        status = str(backtest.execution_statuses.loc[normalized_date])
        if status in {"executed", "executed_partial_unpriceable_targets"}:
            signal_date = backtest.signal_dates.get(normalized_date)
            if signal_date is None or pd.isna(signal_date):
                raise ValueError(f"executed backtest session has no signal date: {factor}")
            last_signal_date = pd.Timestamp(signal_date)
            last_execution_date = normalized_date
        execution_metadata[normalized_date] = (last_signal_date, last_execution_date)

    sessions: list[dict[str, Any]] = []
    full_index = pd.DatetimeIndex(backtest.weights.index)
    for date in history_dates:
        position = full_index.get_loc(date)
        if position + 1 < len(full_index):
            post_close_weights = backtest.weights.iloc[position + 1]
            post_close_cash_weight = float(backtest.cash_weights.iloc[position + 1])
        else:
            post_close_weights = backtest.ending_weights
            post_close_cash_weight = float(backtest.ending_cash_weight)
        ordered = _ordered_positive_weights(post_close_weights)
        signal_date, execution_date = execution_metadata[pd.Timestamp(date)]
        sessions.append(
            {
                "date": date.date().isoformat(),
                "valuationAvailable": bool(backtest.valuation_available.loc[date]),
                "cashWeight": post_close_cash_weight,
                "executionStatus": str(backtest.execution_statuses.loc[date]),
                "lastSignalDate": (
                    signal_date.date().isoformat() if signal_date is not None else None
                ),
                "lastExecutionDate": (
                    execution_date.date().isoformat() if execution_date is not None else None
                ),
                "weights": [
                    {
                        "rank": rank,
                        "symbol": symbol,
                        "name": str(names.get(symbol, symbol)),
                        "weight": weight,
                    }
                    for rank, (symbol, weight) in enumerate(ordered, start=1)
                ],
            }
        )

    return {
        "contractVersion": SELECTED_HOLDING_HISTORY_CONTRACT_VERSION,
        "factor": factor,
        "weightingPolicyId": policy_id,
        "weightTiming": SELECTED_HOLDING_HISTORY_WEIGHT_TIMING,
        "startDate": sessions[0]["date"],
        "endDate": sessions[-1]["date"],
        "sessionCount": len(sessions),
        "sessions": sessions,
    }


def _selected_backtest_holding_history_payload(result: AnalysisResult) -> dict[str, Any]:
    history = getattr(result, "factor_holding_histories", {}).get(result.selected_factor)
    if history is not None:
        return history
    return _backtest_holding_history_payload(
        factor=result.selected_factor,
        policy_id=result.selected_policy,
        backtest=result.backtests[result.selected_factor],
        names=_names_by_symbol(result.market_data),
    )


def _factor_holding_history_sidecar_data(result: AnalysisResult) -> dict[str, Any]:
    histories = result.factor_holding_histories
    factor_ids = sorted(result.factor_scores)
    if set(histories) != set(factor_ids):
        raise ValueError("factor holding history sidecar does not cover the canonical factor set")

    selected_history = histories.get(result.selected_factor)
    if selected_history is None:
        raise ValueError("factor holding history sidecar has no selected-factor history")
    dates = [str(session["date"]) for session in selected_history["sessions"]]
    if len(dates) != SELECTED_HOLDING_HISTORY_SESSION_COUNT:
        raise ValueError("factor holding history sidecar has an invalid canonical date count")

    symbol_names: dict[str, str] = {}
    for factor in factor_ids:
        history = histories[factor]
        factor_dates = [str(session["date"]) for session in history["sessions"]]
        if (
            history.get("factor") != factor
            or history.get("weightingPolicyId") != result.selected_policy
            or history.get("weightTiming") != SELECTED_HOLDING_HISTORY_WEIGHT_TIMING
            or factor_dates != dates
        ):
            raise ValueError(f"factor holding history provenance is inconsistent: {factor}")
        for session in history["sessions"]:
            for row in session["weights"]:
                symbol = str(row["symbol"])
                name = str(row["name"])
                if symbol in symbol_names and symbol_names[symbol] != name:
                    raise ValueError(f"factor holding history symbol name changed: {symbol}")
                symbol_names[symbol] = name

    symbols = [[symbol, symbol_names[symbol]] for symbol in sorted(symbol_names)]
    symbol_indexes = {str(row[0]): index for index, row in enumerate(symbols)}
    compact_factors: dict[str, dict[str, Any]] = {}
    for factor in factor_ids:
        history = histories[factor]
        compact_factors[factor] = {
            "factor": factor,
            "weightingPolicyId": result.selected_policy,
            "resultKey": result.result_identity["resultKey"],
            "sessions": [
                {
                    "valuationAvailable": session["valuationAvailable"],
                    "cashWeight": session["cashWeight"],
                    "executionStatus": session["executionStatus"],
                    "lastSignalDate": session["lastSignalDate"],
                    "lastExecutionDate": session["lastExecutionDate"],
                    "weights": [
                        [symbol_indexes[str(row["symbol"])], row["weight"]]
                        for row in session["weights"]
                    ],
                }
                for session in history["sessions"]
            ],
        }

    return {
        "contract": FACTOR_HOLDING_HISTORY_SIDECAR_CONTRACT,
        "contractVersion": FACTOR_HOLDING_HISTORY_SIDECAR_CONTRACT_VERSION,
        "resultKey": result.result_identity["resultKey"],
        "weightingPolicy": result.selected_policy,
        "weightTiming": SELECTED_HOLDING_HISTORY_WEIGHT_TIMING,
        "startDate": dates[0],
        "endDate": dates[-1],
        "sessionCount": len(dates),
        "dates": dates,
        "factorCount": len(factor_ids),
        "independentFactorCount": result.grid_accounting["independentFactorCount"],
        "diagnosticFactorCount": result.grid_accounting["diagnosticAliasFactorCount"],
        "factorDefinitionSha256": factor_definition_sha256(),
        "policyDefinitionSha256": policy_definition_sha256(),
        "symbols": symbols,
        "factors": compact_factors,
    }


def _factor_holding_history_sidecar_manifest(result: AnalysisResult) -> dict[str, Any]:
    sidecar = _factor_holding_history_sidecar_data(result)
    encoded = canonical_json_bytes(sidecar)
    if len(encoded) > MAX_FACTOR_HOLDING_HISTORY_SIDECAR_BYTES:
        raise ValueError(
            "factor holding history sidecar is "
            f"{len(encoded):,} bytes; limit is "
            f"{MAX_FACTOR_HOLDING_HISTORY_SIDECAR_BYTES:,}"
        )
    result_key = str(result.result_identity["resultKey"])
    return {
        "contract": FACTOR_HOLDING_HISTORY_SIDECAR_CONTRACT,
        "contractVersion": FACTOR_HOLDING_HISTORY_SIDECAR_CONTRACT_VERSION,
        "storage": "embedded",
        "path": f"data/{FACTOR_HOLDING_HISTORY_SIDECAR_DIRECTORY}/{result_key}.json",
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "bytes": len(encoded),
        "resultKey": result_key,
        "weightingPolicy": result.selected_policy,
        "weightTiming": SELECTED_HOLDING_HISTORY_WEIGHT_TIMING,
        "startDate": sidecar["startDate"],
        "endDate": sidecar["endDate"],
        "sessionCount": sidecar["sessionCount"],
        "factorCount": sidecar["factorCount"],
        "independentFactorCount": sidecar["independentFactorCount"],
        "diagnosticFactorCount": sidecar["diagnosticFactorCount"],
        "data": sidecar,
    }


def _current_transition_payload(result: AnalysisResult) -> dict[str, Any]:
    """Apply the historical turnover/cost formulas to the latest known close.

    The target itself is for the next session close.  That future pre-trade
    drift cannot be known yet, so this is an explicitly indicative as-of-close
    transition rather than a claimed executable fill.
    """

    backtest = result.backtests[result.selected_factor]
    symbols = backtest.ending_weights.index.union(result.model_portfolio.allocation.weights().index)
    held = backtest.ending_weights.reindex(symbols, fill_value=0.0).astype(float)
    target = result.model_portfolio.allocation.weights(symbols).astype(float)
    held_cash = float(backtest.ending_cash_weight)
    target_cash = float(result.model_portfolio.cash_weight)
    valuation_available = bool(
        not backtest.valuation_available.empty and backtest.valuation_available.iloc[-1]
    )
    turnover = (
        0.5 * (float((target - held).abs().sum()) + abs(target_cash - held_cash))
        if valuation_available
        else float("nan")
    )
    modeled_cost = (
        turnover * result.config.total_cost_rate if np.isfinite(turnover) else float("nan")
    )
    return {
        "status": (
            "indicative_as_of_close"
            if valuation_available
            else "unavailable_latest_held_valuation_incomplete"
        ),
        "asOf": result.market_data.as_of.date().isoformat(),
        "targetSignalDate": result.model_portfolio.as_of.date().isoformat(),
        "expectedExecutionTiming": result.model_portfolio.execution_timing,
        "actualNextClosePretradeDriftKnown": False,
        "valuationAvailable": valuation_available,
        "pretradeCashWeight": held_cash,
        "targetCashWeight": target_cash,
        "oneWayTurnover": turnover,
        "totalCostBps": result.config.total_cost_bps,
        "modeledCostFraction": modeled_cost,
        "turnoverFormula": "0.5*(sum_abs_target_minus_pretrade_stock+abs_target_minus_pretrade_cash)",
        "costFormula": "one_way_turnover*total_cost_bps/10000",
        "note": (
            "Uses the last observed close's backtest-held weights. Actual next-close turnover "
            "and cost remain unknown until that execution close is observed."
        ),
    }


def result_payload(result: AnalysisResult) -> dict[str, Any]:
    market = result.market_data
    config = result.config
    curve_dates = pd.DatetimeIndex(market.prices.index[-(config.evaluation_window_days + 1) :])
    definitions = result.factor_definitions.copy()
    for column in ("limitations", "references"):
        definitions[column] = definitions.get(column, pd.Series(dtype=object)).map(
            lambda value: list(value) if isinstance(value, tuple) else value
        )
    latest_eligible = int(
        market.eligibility_mask.drop(columns=[market.benchmark], errors="ignore").iloc[-1].sum()
    )
    exclusion_counts: dict[str, int] = {}
    if not market.quality.empty:
        for reasons in market.quality.loc[
            market.quality["role"].eq("candidate"), "exclusion_reasons"
        ]:
            for reason in reasons:
                exclusion_counts[reason] = exclusion_counts.get(reason, 0) + 1
    comparison_prices = _comparison_price_panel(market, config)
    benchmark_curves: dict[str, list[float | None] | None] = {}
    comparison_availability: dict[str, bool] = {}
    for symbol in config.comparison_benchmarks:
        series = (
            pd.to_numeric(comparison_prices[symbol], errors="coerce")
            if symbol in comparison_prices
            else pd.Series(dtype=float)
        )
        as_of_value = series.get(market.as_of) if not series.empty else None
        available = bool(pd.notna(as_of_value))
        comparison_availability[symbol] = available
        benchmark_curves[symbol] = _normalized_curve(series, curve_dates) if available else None
    benchmark_curve = benchmark_curves.get(market.benchmark)
    performance_periods = _performance_periods_payload(
        result,
        curve_dates,
        comparison_prices,
    )
    selected_backtest = result.backtests[result.selected_factor]
    payload = {
        "schemaVersion": 5,
        "resultKey": result.result_identity["resultKey"],
        "resultIdentity": result.result_identity,
        "generatedAtUtc": result.generated_at_utc.isoformat(),
        "bestFactor": result.selected_factor,
        "weightingPolicy": result.selected_policy,
        "bestFactorReason": result.selected_reason,
        "factorSelectionDecision": result.factor_selection_decision,
        "factorAccounting": result.grid_accounting,
        "factorRanking": result.factor_ranking.to_dict(orient="records"),
        "weightingMethodology": {
            "registryVersion": POLICY_REGISTRY_VERSION,
            "policyId": result.selected_policy,
            "policy": POLICY_REGISTRY[result.selected_policy],
            "optimized": False,
        },
        "contributionDiagnostics": selected_backtest.contribution_diagnostics.to_dict(),
        "allocationMethod": {
            "policyId": result.selected_policy,
            "version": POLICY_REGISTRY[result.selected_policy]["version"],
            "fixed": True,
            "historyCurrentParity": {
                "targetWeightKernel": True,
                "capAndCashContract": True,
                "turnoverFormula": "same_cash_inclusive_half_l1",
                "costFormula": "same_turnover_times_total_cost_rate",
                "historicalRebalanceGridRequired": True,
                "currentTransitionBasis": "latest_observed_close_indicative",
                "actualNextCloseTransitionKnown": False,
            },
            "parameters": {
                "topN": config.top_n,
                "maxWeight": config.max_weight,
                "rebalanceFrequency": config.rebalance_frequency,
                "transactionCostBps": config.transaction_cost_bps,
                "slippageBps": config.slippage_bps,
                "factorScoreWeight": config.allocation_score_weight,
                "liquidityWeight": config.allocation_liquidity_weight,
                "marketCapWeight": config.allocation_market_cap_weight,
                "rankFloor": config.allocation_rank_floor,
                "marketCapMaximumAgeDays": config.market_cap_max_age_days,
            },
        },
        "researchScope": {
            "researchOnly": True,
            "notInvestmentRecommendation": True,
            "evidenceStatus": "same_sample_descriptive_actual_market"
            if market.source_mode == "live_market"
            else "same_sample_descriptive",
            "limitations": list(RESEARCH_LIMITATIONS),
        },
        "researchInputs": ResearchInputs.from_config(config).to_dict(),
        "config": _public_config(config),
        "data": {
            "mode": market.source_mode,
            "synthetic": market.source_mode == "demo",
            "sourceLabel": market.source_label,
            "provider": market.provider,
            "priceBasis": market.price_basis,
            "volumeBasis": market.volume_basis,
            "inputSha256": market.input_sha256,
            "requestedThrough": market.requested_through,
            "asOf": market.as_of.date().isoformat(),
            "startDate": market.prices.index.min().date().isoformat(),
            "observations": len(market.prices),
            "requestedCandidateCount": market.requested_candidate_count,
            "providerReturnedCandidateCount": market.provider_returned_candidate_count,
            "inputSecurityCount": len(market.candidate_symbols),
            "analyzedSecurityCount": len(market.candidate_symbols),
            "analyzedSymbols": list(market.candidate_symbols),
            "latestEligibleSecurityCount": latest_eligible,
            "funnel": {
                "label": "canonical_analysis_funnel",
                "authoritative": True,
                "requestedCandidateCount": market.requested_candidate_count,
                "providerUsableCandidateCount": market.provider_returned_candidate_count,
                "analyzedSecurityCount": len(market.candidate_symbols),
                "latestEligibleSecurityCount": latest_eligible,
                "eligibilityTiming": "date_t_inputs_only",
                "eligibilityRules": [
                    "minimum_observed_history",
                    "current_minimum_price",
                    "trailing_price_coverage",
                    "trailing_extreme_return_clear",
                    "trailing_volume_coverage_when_required",
                    "trailing_liquidity",
                ],
                "exclusionCountsMayOverlap": True,
            },
            "latestEligibilityExclusionCounts": exclusion_counts,
            "rawCloseProxySymbolCount": market.raw_close_proxy_symbol_count,
            "rawCloseBasis": "provider_raw_close_unfilled",
            "rawCloseAvailable": not market.raw_closes.empty,
            "rawCloseProxyDefinition": (
                "adjusted_close_used_only_where_provider_raw_close_is_missing"
            ),
            "snapshotReadContract": SNAPSHOT_READ_CONTRACT,
            "benchmark": market.benchmark,
            "benchmarkAvailable": comparison_availability.get(market.benchmark, False),
            "chartBenchmark": config.chart_benchmark,
            "additionalComparisonBenchmarks": list(config.additional_comparison_benchmarks),
            "comparisonBenchmarkAvailability": comparison_availability,
            "comparisonSymbols": list(market.comparison_symbols),
            "comparisonPricesSha256": market.input_sha256.get("comparisonPrices"),
            "liquidityFilterApplied": config.min_avg_dollar_volume > 0.0,
            "notes": market.notes,
            "pointInTimeMarketCapAvailable": bool(
                not market.market_caps.empty and market.market_caps.notna().to_numpy().any()
            ),
            "latestMarketCapSecurityCount": int(
                market.market_caps.loc[market.as_of]
                .drop(labels=[market.benchmark], errors="ignore")
                .notna()
                .sum()
            ),
            "marketCapSourcesSha256": market.input_sha256.get("marketCapSources"),
        },
        "selectionMethod": {
            "name": "fixed_policy_factor_selection_absolute_guardrails",
            "version": FACTOR_SELECTION_VERSION,
            "guardrailVersion": ABSOLUTE_GUARDRAIL_VERSION,
            "evaluationWindowDays": config.evaluation_window_days,
            "minimumObservations": config.min_evaluation_observations,
            "minimumValuationCoverage": config.min_valuation_coverage,
            "minimumDailyRiskObservations": config.min_daily_risk_observations,
            "weights": config.score_weights,
            "netOfCosts": True,
            "signalTiming": "close_t",
            "executionTiming": "next_session_close",
            "returnExposureStarts": "following_close_to_close_session",
            "tieBreakPolicy": list(FACTOR_SELECTION_TIE_BREAK_POLICY),
            "weightingPolicyOptimized": False,
            "fixedWeightingPolicy": FIXED_WEIGHTING_POLICY,
        },
        "bestFactorPortfolio": result.model_portfolio.to_dict(),
        "backtestHeldPortfolio": _held_portfolio_payload(result),
        "bestFactorBacktestHoldingHistory": _selected_backtest_holding_history_payload(result),
        "factorHoldingHistorySidecar": _factor_holding_history_sidecar_manifest(result),
        "bestFactorTransition": _current_transition_payload(result),
        "factorPortfolios": {
            factor: portfolio.to_dict() for factor, portfolio in result.factor_portfolios.items()
        },
        "factorDefinitions": definitions.to_dict(orient="records"),
        "factorDiagnostics": result.factor_diagnostics,
        "advancedFactorStatus": result.advanced_factor_status.to_dict(orient="records"),
        "benchmarkMetrics": result.benchmark_metrics,
        "performance": {
            "contractVersion": PERFORMANCE_CONTRACT_VERSION,
            "weightingPolicyId": result.selected_policy,
            "dates": [date.date().isoformat() for date in curve_dates],
            "factorCurves": {
                factor: _normalized_curve(backtest.equity, curve_dates)
                for factor, backtest in result.backtests.items()
            },
            "benchmarkCurve": benchmark_curve,
            "benchmarkOrder": list(config.comparison_benchmarks),
            "benchmarkCurves": benchmark_curves,
            "periods": performance_periods,
        },
        "quality": market.quality.to_dict(orient="records"),
        "priceSources": market.price_sources.to_dict(orient="records"),
        "sourceHealth": market.data_sources.to_dict(orient="records"),
        "meta": {
            "factorCount": len(result.factor_scores),
            "independentFactorCount": result.grid_accounting["independentFactorCount"],
            "availableIndependentFactorCount": result.grid_accounting[
                "availableIndependentFactorCount"
            ],
            "excludedIndependentFactorCount": result.grid_accounting[
                "excludedIndependentFactorCount"
            ],
            "aliasFactorCount": result.grid_accounting["diagnosticAliasFactorCount"],
            "portfolioCount": len(result.factor_portfolios),
            "factorRunCount": len(result.factor_ranking),
            "runtimeSeconds": result.runtime_seconds,
            "maxRssBytes": result.max_rss_bytes,
            "purpose": "input_driven_momentum_factor_comparison_with_fixed_weighting",
            "factorDefinitionSha256": factor_definition_sha256(),
            "policyDefinitionSha256": policy_definition_sha256(),
            "selectionSpecSha256": selection_spec_sha256(config),
        },
    }
    return _json_safe(payload)


def write_payload_json(payload: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    path = output_dir / f"momentum_factor_results_{timestamp}.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def write_result_json(result: AnalysisResult) -> Path:
    path = write_payload_json(result_payload(result), result.config.output_dir)
    result.output_paths["json"] = str(path)
    return path


def load_result_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schemaVersion") != 5:
        raise ValueError("dashboard input must use schemaVersion 5")
    return payload
