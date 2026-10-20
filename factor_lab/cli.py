from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import shutil
import tempfile
import traceback
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

from .config import (
    ABSOLUTE_GUARDRAIL_VERSION,
    MAX_TOP_N,
    RunConfig,
    minimum_evaluation_observations,
)
from .data import (
    MarketData,
    load_market_data,
    read_market_data_snapshot,
    write_market_data_snapshot,
)
from .dashboard import DEFAULT_SITE_TITLE, dashboard_summary, write_dashboard_site
from .dashboard_freshness import KST, expected_recent_us_close_date
from .identity import build_result_identity, load_analysis_cache, write_analysis_cache
from .local_api import LocalResearchAPI
from .research_inputs import ResearchInputError, ResearchInputs
from .static_grid import (
    MIN_ACTUAL_ANALYZED_SECURITY_COUNT,
    StaticGridArtifact,
    validate_static_grid,
    write_static_grid,
)
from .universe import normalize_symbols
from .workflow import (
    NoEligibleFactorError,
    result_payload,
    run_analysis,
    write_payload_json,
)


LEGACY_SCHEDULED_ARGUMENTS = frozenset(
    {
        "--approved-tradable-universe",
        "--factor-selection-mode",
        "--frozen-policy-path",
        "--max-adv-participation",
        "--offline-sample",
        "--point-in-time-universe-provenance",
        "--production",
        "--report-dir",
        "--score-size-liquidity-weight",
        "--score-size-market-cap-weight",
        "--score-size-rank-floor",
        "--score-size-score-weight",
        "--selected-factor",
        "--target-aum",
        "--policy-mdd-tolerance",
        "--policy-max-cost-drag",
        "--policy-min-effective-n",
        "--policy-sharpe-tolerance",
    }
)

_SCHEDULED_PRESET_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
AUTOMATION_STATUS_CONTRACT = "momentum-dashboard-automation-status"
AUTOMATION_STATUS_SCHEMA_VERSION = 1
AUTOMATION_STATUS_FILENAME = "automation-status.json"


@dataclass(frozen=True, slots=True)
class ScheduledGridPreset:
    preset_id: str
    research_inputs: ResearchInputs
    market_session_offset: int = 0


def _last_good_reference(site_dir: Path) -> dict[str, Any] | None:
    dashboard_path = site_dir / "data" / "dashboard.json"
    try:
        payload = json.loads(dashboard_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    data_as_of = data.get("asOf") if isinstance(data, dict) else None
    result_key = payload.get("resultKey")
    generated_at = payload.get("generatedAtUtc")
    if not any(isinstance(value, str) and value for value in (data_as_of, result_key, generated_at)):
        return None
    return {
        "resultKey": result_key if isinstance(result_key, str) else None,
        "dataAsOf": data_as_of if isinstance(data_as_of, str) else None,
        "generatedAtUtc": generated_at if isinstance(generated_at, str) else None,
        "path": "data/dashboard.json",
    }


def _automation_timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _write_automation_status(site_dir: Path, status: dict[str, Any]) -> Path:
    data_dir = site_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / AUTOMATION_STATUS_FILENAME
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def _unavailable_automation_status(
    *,
    site_dir: Path,
    preset_id: str,
    target_data_as_of: str | None,
    error: NoEligibleFactorError,
    preset_data_as_of: str | None = None,
) -> tuple[dict[str, Any], Path]:
    last_good = _last_good_reference(site_dir)
    status = {
        "schemaVersion": AUTOMATION_STATUS_SCHEMA_VERSION,
        "contract": AUTOMATION_STATUS_CONTRACT,
        "project": "momentum-factor-lab",
        "state": "degraded" if last_good is not None else "unavailable",
        "reasonCode": (
            "no_eligible_factor" if error.comparable_factor_count else "no_comparable_factor"
        ),
        "attemptedAtUtc": _automation_timestamp(),
        "targetDataAsOf": target_data_as_of,
        "affectedPresetId": preset_id,
        "affectedPresetDataAsOf": preset_data_as_of,
        "analysis": {
            "guardrailVersion": ABSOLUTE_GUARDRAIL_VERSION,
            "evaluatedFactorCount": error.evaluated_factor_count,
            "comparableFactorCount": error.comparable_factor_count,
            "eligibleFactorCount": 0,
            "guardrailBreachCounts": error.guardrail_breach_counts,
            "comparisonStatusCounts": error.comparison_status_counts,
            "exclusionReasonCounts": error.exclusion_reason_counts,
            "selectionStatusCounts": error.selection_status_counts,
            "factorDetails": error.factor_details,
            "guardrailsRelaxed": False,
            "fallbackFactorSelected": False,
        },
        "publication": {
            "updated": False,
            "lastGoodPreserved": last_good is not None,
            "policy": "preserve_last_good",
        },
        "lastGood": last_good,
    }
    return status, _write_automation_status(site_dir, status)


def _available_automation_status(
    *,
    site_dir: Path,
    payload: dict[str, Any],
    preset_count: int,
) -> tuple[dict[str, Any], Path]:
    data = payload.get("data")
    data_as_of = data.get("asOf") if isinstance(data, dict) else None
    status = {
        "schemaVersion": AUTOMATION_STATUS_SCHEMA_VERSION,
        "contract": AUTOMATION_STATUS_CONTRACT,
        "project": "momentum-factor-lab",
        "state": "available",
        "reasonCode": "published",
        "attemptedAtUtc": _automation_timestamp(),
        "targetDataAsOf": data_as_of if isinstance(data_as_of, str) else None,
        "affectedPresetId": None,
        "analysis": {
            "guardrailVersion": ABSOLUTE_GUARDRAIL_VERSION,
            "presetCount": preset_count,
            "guardrailsRelaxed": False,
            "fallbackFactorSelected": False,
        },
        "publication": {
            "updated": True,
            "lastGoodPreserved": False,
            "policy": "validated_static_grid",
        },
        "lastGood": {
            "resultKey": payload.get("resultKey"),
            "dataAsOf": data_as_of if isinstance(data_as_of, str) else None,
            "generatedAtUtc": payload.get("generatedAtUtc"),
            "path": "data/dashboard.json",
        },
    }
    return status, _write_automation_status(site_dir, status)


def _optional_nonnegative_int(value: str) -> int | None:
    normalized = value.strip().lower()
    if normalized in {"none", "null", "unlimited"}:
        return None
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative or 'none'")
    return parsed


def _optional_positive_int(value: str) -> int | None:
    parsed = _optional_nonnegative_int(value)
    if parsed is not None and parsed < 1:
        raise argparse.ArgumentTypeError("value must be positive or 'none'")
    return parsed


def _add_run_arguments(run: argparse.ArgumentParser) -> None:
    source = run.add_mutually_exclusive_group(required=True)
    source.add_argument("--live", action="store_true", help="Use current public market data")
    source.add_argument("--prices", type=Path, help="Local wide or long-form adjusted-price CSV")
    source.add_argument("--demo", action="store_true", help="Use the deterministic synthetic demo")
    run.add_argument("--volumes", type=Path, help="Optional local share-volume CSV")
    run.add_argument(
        "--market-caps",
        type=Path,
        help="Optional local point-in-time market-cap CSV; required for local portfolio analysis",
    )
    run.add_argument(
        "--volume-basis",
        choices=["split_adjusted"],
        help="Required with --volumes; confirms split-consistent share volume",
    )

    dates = run.add_argument_group("dates and portfolio")
    dates.add_argument("--start-date", default="2016-01-01")
    dates.add_argument("--end-date")
    dates.add_argument("--benchmark", default="SPY")
    dates.add_argument("--chart-benchmark", default="^IXIC")
    dates.add_argument(
        "--additional-comparison-benchmarks",
        default="QQQ",
        help="Comma-separated additional adjusted-price comparators; default: QQQ",
    )
    dates.add_argument(
        "--top-n",
        type=int,
        default=20,
        help=f"Number of holdings per factor, from 1 through {MAX_TOP_N}",
    )
    dates.add_argument("--max-weight", type=float, default=0.10)
    dates.add_argument("--rebalance-frequency", choices=["W", "ME", "QE"], default="ME")
    dates.add_argument("--transaction-cost-bps", type=float, default=5.0)
    dates.add_argument("--slippage-bps", type=float, default=5.0)
    dates.add_argument("--annual-cash-return", type=float, default=0.0)

    eligibility = run.add_argument_group("eligibility and data quality")
    eligibility.add_argument("--min-history-days", type=int, default=252)
    eligibility.add_argument("--min-price", type=float, default=5.0)
    eligibility.add_argument("--min-avg-dollar-volume", type=float, default=0.0)
    eligibility.add_argument("--min-avg-volume", type=float, default=0.0)
    eligibility.add_argument("--liquidity-lookback-days", type=int, default=63)
    eligibility.add_argument("--min-liquidity-observations", type=int, default=42)
    eligibility.add_argument("--max-price-missing-ratio", type=float, default=0.05)
    eligibility.add_argument("--stale-after-days", type=int, default=7)
    eligibility.add_argument("--data-quality-lookback-days", type=int, default=252)
    eligibility.add_argument("--max-volume-missing-ratio", type=float, default=0.10)
    eligibility.add_argument("--max-extreme-daily-return", type=float, default=0.80)

    evaluation = run.add_argument_group("factor evaluation and coverage")
    evaluation.add_argument("--evaluation-window-days", type=int, default=756)
    evaluation.add_argument("--min-evaluation-observations", type=int)
    evaluation.add_argument("--min-valuation-coverage", type=float, default=0.98)
    evaluation.add_argument("--min-daily-risk-observations", type=int)
    evaluation.add_argument("--stability-periods", type=int, default=3)
    evaluation.add_argument("--score-sortino-weight", type=float, default=0.25)
    evaluation.add_argument("--score-calmar-weight", type=float, default=0.20)
    evaluation.add_argument("--score-max-drawdown-weight", type=float, default=0.20)
    evaluation.add_argument("--score-cagr-weight", type=float, default=0.15)
    evaluation.add_argument("--score-sharpe-weight", type=float, default=0.10)
    evaluation.add_argument("--score-stability-weight", type=float, default=0.10)
    evaluation.add_argument("--score-winsor-lower", type=float, default=0.05)
    evaluation.add_argument("--score-winsor-upper", type=float, default=0.95)

    policy = run.add_argument_group("fixed weighting methodology and factor-selection guards")
    policy.add_argument("--selection-min-sharpe", type=float, default=0.0)
    policy.add_argument("--selection-max-drawdown", type=float, default=0.60)
    policy.add_argument("--selection-max-annualized-cost-drag", type=float, default=0.02)
    policy.add_argument("--selection-min-effective-names", type=float, default=10.0)
    policy.add_argument("--selection-max-target-hhi", type=float, default=0.15)
    policy.add_argument("--selection-max-target-weight", type=float, default=0.15)
    policy.add_argument(
        "--selection-max-abs-security-day-contribution",
        type=float,
        default=0.10,
    )
    policy.add_argument(
        "--selection-max-security-absolute-contribution-share",
        type=float,
        default=0.35,
    )
    policy.add_argument(
        "--selection-max-leave-one-security-cagr-delta",
        type=float,
        default=0.25,
    )
    policy.add_argument(
        "--selection-extreme-event-action",
        choices=["warn", "penalize", "exclude"],
        default="exclude",
    )
    policy.add_argument(
        "--selection-extreme-event-penalty-points",
        type=float,
        default=20.0,
    )

    live = run.add_argument_group("live acquisition")
    live.add_argument(
        "--universe",
        help="Comma-separated packaged stock symbols; omitted uses the complete broad universe",
    )
    live.add_argument(
        "--universe-source-mode",
        choices=["packaged", "refresh"],
        default="packaged",
    )
    live.add_argument(
        "--universe-profile",
        choices=["large_liquid", "extended_current", "aggressive_stock_only"],
        default="large_liquid",
    )
    live.add_argument(
        "--max-price-symbols",
        type=_optional_positive_int,
        default=None,
        help="Optional live smoke-test cap; 'none' keeps the full universe",
    )
    live.add_argument("--price-chunk-size", type=int, default=25)
    live.add_argument(
        "--yahoo-chart-fallback-limit",
        type=_optional_nonnegative_int,
        default=250,
    )
    live.add_argument(
        "--nasdaq-fallback-limit",
        type=_optional_nonnegative_int,
        default=250,
    )
    live.add_argument(
        "--stooq-fallback-limit",
        type=_optional_nonnegative_int,
        default=0,
    )
    live.add_argument(
        "--finance-datareader-fallback-limit",
        type=_optional_nonnegative_int,
        default=0,
    )
    live.add_argument("--retry-count", type=int, default=2)
    live.add_argument("--retry-backoff-seconds", type=float, default=0.5)
    live.add_argument("--market-cache-max-age-hours", type=float, default=24.0)
    live.add_argument(
        "--refresh-market-data",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Bypass provider price caches and recheck the requested market snapshot",
    )
    live.add_argument(
        "--sec-user-agent",
        help=(
            "SEC EDGAR identification header (not an API key); the environment may also "
            "supply MOMENTUM_FACTOR_LAB_SEC_USER_AGENT"
        ),
    )

    demo = run.add_argument_group("demo")
    demo.add_argument("--demo-symbol-count", type=int, default=200)
    demo.add_argument("--demo-seed", type=int, default=42)
    demo.add_argument(
        "--demo-missing-ratio",
        type=float,
        default=0.0,
        help="Deterministic candidate-cell gap ratio (0 or at least 0.001)",
    )

    output = run.add_argument_group("outputs and reproducibility")
    output.add_argument("--output-dir", type=Path, default=Path("outputs/sample"))
    output.add_argument("--site-dir", type=Path, default=Path("docs"))
    output.add_argument("--cache-dir", type=Path, default=Path(".cache/factor_lab"))
    output.add_argument(
        "--export-input-snapshot",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Write the canonical input panels and hashes used by the run",
    )
    output.add_argument("--title", default=DEFAULT_SITE_TITLE)
    output.add_argument("--json", action="store_true", help="Print a compact run summary as JSON")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="factor",
        description=(
            "Compare momentum factors from live public data, reviewed local files, or a "
            "deterministic demo. This research application does not place orders."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser(
        "run",
        help="Compare all available momentum factors and build the website",
    )
    _add_run_arguments(run)

    local_api = subparsers.add_parser(
        "serve-local-api",
        help="Serve arbitrary full-universe actual-market inputs through local Python",
    )
    _add_run_arguments(local_api)
    local_api.add_argument("--host", default="127.0.0.1")
    local_api.add_argument("--port", type=int, default=8765)
    local_api.add_argument("--allow-non-loopback", action="store_true", default=False)
    local_api.add_argument(
        "--allowed-origin",
        action="append",
        help="Additional exact HTTP(S) browser Origin allowed to call the loopback API",
    )

    site = subparsers.add_parser("build-site", help="Rebuild the site from schema-v5 JSON")
    site.add_argument("--input", type=Path, required=True)
    site.add_argument("--site-dir", type=Path, default=Path("outputs/site-preview"))
    site.add_argument("--title", default=DEFAULT_SITE_TITLE)

    grid = subparsers.add_parser(
        "build-static-grid",
        help="Publish a bounded sparse grid from precomputed schema-v5 detail/summary pairs",
    )
    grid.add_argument("--site-dir", type=Path, default=Path("docs"))
    grid.add_argument(
        "--artifact",
        action="append",
        nargs=2,
        type=Path,
        metavar=("DETAIL_JSON", "SUMMARY_JSON"),
        required=True,
    )
    grid.add_argument(
        "--preset-id",
        action="append",
        help=(
            "Stable lowercase preset identifier paired by position with --artifact; "
            "supply one for every artifact or omit all"
        ),
    )
    grid.add_argument("--default-result-key", required=True)
    grid.add_argument(
        "--write-default-aliases",
        action=argparse.BooleanOptionalAction,
        default=True,
    )

    scheduled = subparsers.add_parser(
        "scheduled-dashboard",
        help="Run saved run_args and rebuild the configured static dashboard",
    )
    scheduled.add_argument(
        "--config",
        type=Path,
        default=Path(".github/factor-dashboard-config.json"),
    )
    scheduled.add_argument("--site-dir", type=Path, help="Override config site_dir")
    scheduled.add_argument("--title", help="Override config title")
    scheduled.add_argument("--json", action="store_true", help="Print the compact summary as JSON")
    from .integrated_cli import add_integrated_commands
    add_integrated_commands(subparsers)
    return parser


def _config(args: argparse.Namespace) -> RunConfig:
    derived_minimum_observations = minimum_evaluation_observations(args.evaluation_window_days)
    return RunConfig(
        start_date=args.start_date,
        end_date=args.end_date,
        live=args.live,
        prices_path=args.prices,
        volumes_path=args.volumes,
        market_caps_path=args.market_caps,
        volume_basis=args.volume_basis,
        demo=args.demo,
        demo_symbol_count=args.demo_symbol_count,
        demo_seed=args.demo_seed,
        demo_missing_ratio=args.demo_missing_ratio,
        benchmark=args.benchmark,
        chart_benchmark=args.chart_benchmark,
        additional_comparison_benchmarks=tuple(
            normalize_symbols(args.additional_comparison_benchmarks)
        ),
        rebalance_frequency=args.rebalance_frequency,
        top_n=args.top_n,
        max_weight=args.max_weight,
        transaction_cost_bps=args.transaction_cost_bps,
        slippage_bps=args.slippage_bps,
        annual_cash_return=args.annual_cash_return,
        min_history_days=args.min_history_days,
        min_price=args.min_price,
        min_avg_dollar_volume=args.min_avg_dollar_volume,
        min_avg_volume=args.min_avg_volume,
        liquidity_lookback_days=args.liquidity_lookback_days,
        min_liquidity_observations=args.min_liquidity_observations,
        max_price_missing_ratio=args.max_price_missing_ratio,
        stale_after_days=args.stale_after_days,
        data_quality_lookback_days=args.data_quality_lookback_days,
        max_volume_missing_ratio=args.max_volume_missing_ratio,
        max_extreme_daily_return=args.max_extreme_daily_return,
        evaluation_window_days=args.evaluation_window_days,
        min_evaluation_observations=(
            args.min_evaluation_observations
            if args.min_evaluation_observations is not None
            else derived_minimum_observations
        ),
        min_valuation_coverage=args.min_valuation_coverage,
        min_daily_risk_observations=(
            args.min_daily_risk_observations
            if args.min_daily_risk_observations is not None
            else derived_minimum_observations
        ),
        stability_periods=args.stability_periods,
        score_sortino_weight=args.score_sortino_weight,
        score_calmar_weight=args.score_calmar_weight,
        score_max_drawdown_weight=args.score_max_drawdown_weight,
        score_cagr_weight=args.score_cagr_weight,
        score_sharpe_weight=args.score_sharpe_weight,
        score_stability_weight=args.score_stability_weight,
        score_winsor_lower=args.score_winsor_lower,
        score_winsor_upper=args.score_winsor_upper,
        selection_min_sharpe=args.selection_min_sharpe,
        selection_max_drawdown=args.selection_max_drawdown,
        selection_max_annualized_cost_drag=args.selection_max_annualized_cost_drag,
        selection_min_effective_names=args.selection_min_effective_names,
        selection_max_target_hhi=args.selection_max_target_hhi,
        selection_max_target_weight=args.selection_max_target_weight,
        selection_max_abs_security_day_contribution=(
            args.selection_max_abs_security_day_contribution
        ),
        selection_max_security_absolute_contribution_share=(
            args.selection_max_security_absolute_contribution_share
        ),
        selection_max_leave_one_security_cagr_delta=(
            args.selection_max_leave_one_security_cagr_delta
        ),
        selection_extreme_event_action=args.selection_extreme_event_action,
        selection_extreme_event_penalty_points=args.selection_extreme_event_penalty_points,
        output_dir=args.output_dir,
        site_dir=args.site_dir,
        cache_dir=args.cache_dir,
        export_input_snapshot=args.export_input_snapshot,
        market_cache_max_age_hours=args.market_cache_max_age_hours,
        refresh_market_data=args.refresh_market_data,
        max_price_symbols=args.max_price_symbols,
        price_chunk_size=args.price_chunk_size,
        yahoo_chart_fallback_limit=args.yahoo_chart_fallback_limit,
        nasdaq_fallback_limit=args.nasdaq_fallback_limit,
        stooq_fallback_limit=args.stooq_fallback_limit,
        finance_datareader_fallback_limit=args.finance_datareader_fallback_limit,
        retry_count=args.retry_count,
        retry_backoff_seconds=args.retry_backoff_seconds,
        sec_user_agent=args.sec_user_agent,
        universe_source_mode=args.universe_source_mode,
        universe_profile=args.universe_profile,
        universe=normalize_symbols(args.universe),
    )


PERFORMANCE_FIELDS = {
    "composite_score": "compositeScore",
    "cagr": "cagr",
    "sortino": "sortino",
    "calmar": "calmar",
    "max_drawdown": "maxDrawdown",
    "sharpe": "sharpe",
    "stability": "stability",
    "annualized_turnover": "annualizedTurnover",
    "annualized_cost_drag": "annualizedCostDrag",
    "observations": "observations",
    "actual_exposure_observations": "actualExposureObservations",
    "daily_risk_observations": "dailyRiskObservations",
    "valuation_coverage_ratio": "valuationCoverageRatio",
    "risk_metrics_exact": "riskMetricsExact",
}


def _compact_summary(payload: dict[str, Any], paths: dict[str, str]) -> dict[str, Any]:
    ranking = payload.get("factorRanking")
    selected = payload.get("bestFactor")
    selected_policy = payload.get("weightingPolicy")
    if (
        not isinstance(ranking, list)
        or not isinstance(selected, str)
        or not isinstance(selected_policy, str)
    ):
        raise ValueError("result payload is missing best-factor metadata")
    selected_rows = [
        row
        for row in ranking
        if isinstance(row, dict)
        and row.get("factor") == selected
        and row.get("policy_id") == selected_policy
        and row.get("selected") is True
    ]
    if len(selected_rows) != 1:
        raise ValueError("result payload must contain exactly one selected best-factor row")
    selected_row = selected_rows[0]
    data = payload.get("data")
    meta = payload.get("meta")
    portfolio = payload.get("bestFactorPortfolio")
    if not isinstance(data, dict) or not isinstance(meta, dict) or not isinstance(portfolio, dict):
        raise ValueError("result payload is missing data, factor, or allocation metadata")
    performance = {
        output_name: selected_row.get(input_name)
        for input_name, output_name in PERFORMANCE_FIELDS.items()
    }
    current_allocation = {
        "factor": portfolio.get("factor"),
        "weightingPolicyId": portfolio.get("weightingPolicyId"),
        "asOf": portfolio.get("asOf"),
        "status": portfolio.get("status"),
        "eligibleSecurityCount": portfolio.get("eligibleSecurityCount"),
        "selectedSecurityCount": portfolio.get("selectedSecurityCount"),
        "weights": portfolio.get("weights", []),
        "cashWeight": portfolio.get("cashWeight"),
        "reasons": portfolio.get("reasons", []),
        "concentration": portfolio.get("concentration", {}),
    }
    return {
        "schemaVersion": 5,
        "resultKey": payload.get("resultKey"),
        "resultIdentity": payload.get("resultIdentity"),
        "generatedAtUtc": payload.get("generatedAtUtc"),
        "asOf": data.get("asOf"),
        "dataMode": data.get("mode"),
        "provider": data.get("provider"),
        "requestedCandidateCount": data.get("requestedCandidateCount"),
        "providerReturnedCandidateCount": data.get("providerReturnedCandidateCount"),
        "analyzedSecurityCount": data.get("analyzedSecurityCount"),
        "eligibleSecurityCount": data.get("latestEligibleSecurityCount"),
        "factorCount": meta.get("factorCount"),
        "independentFactorCount": meta.get("independentFactorCount"),
        "availableIndependentFactorCount": meta.get("availableIndependentFactorCount"),
        "bestFactor": selected,
        "bestFactorReason": payload.get("bestFactorReason"),
        "weightingPolicy": selected_policy,
        "performance": performance,
        "currentAllocation": current_allocation,
        "bestFactorTransition": payload.get("bestFactorTransition"),
        "runtimeSeconds": meta.get("runtimeSeconds"),
        "maxRssBytes": meta.get("maxRssBytes"),
        "paths": dict(paths),
    }


def _compute_payload(
    config: RunConfig,
    market: MarketData,
) -> tuple[dict[str, Any], Path]:
    identity = build_result_identity(config, market)
    payload = load_analysis_cache(config, identity)
    if payload is None:
        result = run_analysis(config, market_data=market)
        payload = result_payload(result)
        write_analysis_cache(config, identity, payload)
    result_path = write_payload_json(payload, config.output_dir)
    return payload, result_path


def _require_full_actual_publication(payload: dict[str, Any], config: RunConfig) -> None:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    if data.get("mode") != "live_market" or data.get("synthetic") is not False:
        raise ValueError("static publication requires actual live-market data")
    if config.max_price_symbols is not None:
        raise ValueError("static publication requires the uncapped full universe")
    analyzed = int(data.get("analyzedSecurityCount") or 0)
    if analyzed < MIN_ACTUAL_ANALYZED_SECURITY_COUNT:
        raise ValueError(
            "full-universe static publication requires at least "
            f"{MIN_ACTUAL_ANALYZED_SECURITY_COUNT:,} analyzed securities"
        )


def _execute_run(
    args: argparse.Namespace,
    *,
    site_dir: Path | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    config = _config(args)
    if site_dir is not None:
        config.site_dir = site_dir
    market = load_market_data(config)
    payload, result_path = _compute_payload(config, market)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    publish_full_actual_market = (
        data.get("mode") == "live_market" and config.max_price_symbols is None
    )
    if publish_full_actual_market:
        if config.site_dir.resolve() == Path("docs").resolve():
            raise ValueError(
                "run cannot replace the public multi-preset docs grid; use "
                "scheduled-dashboard or build-static-grid with the complete reviewed preset set"
            )
        _require_full_actual_publication(payload, config)
        paths = write_dashboard_site(payload, config.site_dir, title=title or args.title)
        summary_payload = dashboard_summary(payload)
        grid_paths = write_static_grid(
            config.site_dir / "data",
            [
                StaticGridArtifact(
                    detail=payload,
                    summary=summary_payload,
                    preset_id="latest",
                )
            ],
            default_result_key=str(payload["resultKey"]),
            write_default_aliases=True,
        )
        paths["gridManifest"] = str(grid_paths["manifest"])
    else:
        # Demo, local-file, and explicitly truncated live runs are useful previews, but
        # they must never replace the default actual-market aliases under docs/data.
        preview_site_dir = config.output_dir / "site"
        paths = write_dashboard_site(payload, preview_site_dir, title=title or args.title)
        paths["publicationMode"] = "isolated_preview"
    paths["result"] = str(result_path)
    return _compact_summary(payload, paths)


def _print_run_summary(summary: dict[str, Any]) -> None:
    performance = summary["performance"]
    allocation = summary["currentAllocation"]
    score = performance.get("compositeScore")
    score_text = f"{score:.2f}" if isinstance(score, int | float) else "unavailable"
    print(
        f"best_factor={summary['bestFactor']} score={score_text} "
        f"policy={summary['weightingPolicy']}"
    )
    print(
        "universe="
        f"{summary['requestedCandidateCount']} requested / "
        f"{summary['providerReturnedCandidateCount']} provider / "
        f"{summary['analyzedSecurityCount']} analyzed / "
        f"{summary['eligibleSecurityCount']} eligible"
    )
    print(
        f"portfolio={allocation['selectedSecurityCount']} "
        f"cash={allocation['cashWeight']} as_of={summary['asOf']}"
    )
    print(f"website={summary['paths']['index']}")
    print(f"result={summary['paths']['result']}")


def _scheduled_grid_presets(
    payload: dict[str, Any],
    run_namespace: argparse.Namespace,
) -> tuple[list[ScheduledGridPreset], str]:
    raw_presets = payload.get("static_grid_presets")
    if not isinstance(raw_presets, list) or len(raw_presets) < 2:
        raise ValueError(
            "dashboard config field 'static_grid_presets' must contain at least two presets"
        )
    base_config = _config(run_namespace)
    try:
        base_inputs = ResearchInputs.from_config(base_config)
    except (ResearchInputError, ValueError) as exc:
        raise ValueError(f"scheduled base inputs are not public ResearchInputs: {exc}") from exc

    presets: list[ScheduledGridPreset] = []
    seen_ids: set[str] = set()
    seen_tuples: set[tuple[str, int]] = set()
    for index, raw in enumerate(raw_presets):
        if not isinstance(raw, dict):
            raise ValueError(f"static_grid_presets[{index}] must be an object")
        unknown = sorted(set(raw).difference({"id", "inputOverrides", "marketSessionOffset"}))
        if unknown:
            raise ValueError(
                f"static_grid_presets[{index}] has unknown fields: " + ", ".join(unknown)
            )
        preset_id = raw.get("id")
        if not isinstance(preset_id, str) or not _SCHEDULED_PRESET_ID.fullmatch(preset_id):
            raise ValueError(
                f"static_grid_presets[{index}].id must be a lowercase stable identifier"
            )
        if preset_id in seen_ids:
            raise ValueError(f"duplicate static-grid preset id: {preset_id}")
        overrides = raw.get("inputOverrides", {})
        if not isinstance(overrides, dict):
            raise ValueError(f"static_grid_presets[{index}].inputOverrides must be an object")
        merged = base_inputs.to_dict()
        merged.update(overrides)
        try:
            research_inputs = ResearchInputs.from_mapping(merged)
        except (ResearchInputError, ValueError) as exc:
            raise ValueError(f"invalid static-grid preset {preset_id}: {exc}") from exc
        offset = raw.get("marketSessionOffset", 0)
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0 or offset > 2_520:
            raise ValueError(
                f"static_grid_presets[{index}].marketSessionOffset must be an integer in [0, 2520]"
            )
        tuple_key = (research_inputs.state_key, offset)
        if tuple_key in seen_tuples:
            raise ValueError(f"duplicate static-grid preset tuple: {preset_id}")
        seen_ids.add(preset_id)
        seen_tuples.add(tuple_key)
        presets.append(
            ScheduledGridPreset(
                preset_id=preset_id,
                research_inputs=research_inputs,
                market_session_offset=offset,
            )
        )

    default_id = payload.get("default_static_grid_preset")
    if not isinstance(default_id, str) or default_id not in seen_ids:
        raise ValueError("dashboard config field 'default_static_grid_preset' must name a preset")
    default = next(preset for preset in presets if preset.preset_id == default_id)
    if default.market_session_offset != 0:
        raise ValueError("default static-grid preset must use marketSessionOffset 0")
    if default.research_inputs != base_inputs:
        raise ValueError("default static-grid preset must match the scheduled base inputs")
    return presets, default_id


def _load_scheduled_config(
    args: argparse.Namespace,
) -> tuple[argparse.Namespace, Path, str, list[ScheduledGridPreset], str]:
    try:
        payload = json.loads(args.config.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"dashboard config not found: {args.config}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"dashboard config is not valid JSON: {args.config}") from exc
    if not isinstance(payload, dict):
        raise ValueError("dashboard config must be a JSON object")
    run_args = payload.get("run_args")
    if (
        not isinstance(run_args, list)
        or not run_args
        or not all(isinstance(item, str) for item in run_args)
    ):
        raise ValueError("dashboard config field 'run_args' must be a non-empty list of strings")
    supplied_flags = {item.split("=", maxsplit=1)[0] for item in run_args if item.startswith("--")}
    legacy = sorted(supplied_flags.intersection(LEGACY_SCHEDULED_ARGUMENTS))
    if legacy:
        raise ValueError("dashboard config contains removed legacy arguments: " + ", ".join(legacy))

    tokens = run_args if run_args[:1] == ["run"] else ["run", *run_args]
    error = io.StringIO()
    try:
        with contextlib.redirect_stderr(error):
            run_namespace = build_parser().parse_args(tokens)
    except SystemExit as exc:
        detail = error.getvalue().strip().splitlines()
        message = detail[-1] if detail else "invalid run_args"
        raise ValueError(f"dashboard config run_args are invalid: {message}") from exc
    if run_namespace.command != "run":
        raise ValueError("dashboard config run_args must select the run command")

    raw_site_dir = args.site_dir if args.site_dir is not None else payload.get("site_dir")
    if raw_site_dir is None:
        site_dir = run_namespace.site_dir
    elif isinstance(raw_site_dir, (str, Path)) and str(raw_site_dir).strip():
        site_dir = Path(raw_site_dir)
    else:
        raise ValueError("dashboard config field 'site_dir' must be a non-empty path string")

    raw_title = args.title if args.title is not None else payload.get("title", run_namespace.title)
    if not isinstance(raw_title, str) or not raw_title.strip():
        raise ValueError("dashboard config field 'title' must be a non-empty string")

    if "history_limit" in payload:
        raise ValueError("dashboard config field 'history_limit' was removed because it was unused")
    presets, default_preset_id = _scheduled_grid_presets(payload, run_namespace)
    return run_namespace, site_dir, raw_title, presets, default_preset_id


def _execute_scheduled_grid(
    run_namespace: argparse.Namespace,
    *,
    site_dir: Path,
    title: str,
    presets: list[ScheduledGridPreset],
    default_preset_id: str,
) -> dict[str, Any]:
    """Publish a fully built candidate, preserving last-good on every failure."""

    target = expected_recent_us_close_date(datetime.now(KST)).isoformat()
    site_dir = Path(site_dir)
    site_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".momentum-candidate-", dir=site_dir.parent) as tmp:
        candidate = Path(tmp) / "site"
        if site_dir.exists():
            shutil.copytree(site_dir, candidate)
        else:
            candidate.mkdir()
        try:
            summary = _build_scheduled_grid(
                run_namespace,
                site_dir=candidate,
                title=title,
                presets=presets,
                default_preset_id=default_preset_id,
                target_data_as_of=target,
            )
        except Exception as error:
            # Public state carries no raw exception, provider URL, or local path.
            traceback.print_exc()
            summary = _failed_scheduled_summary(
                site_dir=site_dir,
                target=target,
                reason="execution_failed",
                diagnostics={"errorType": type(error).__name__},
            )
        else:
            backup = Path(tmp) / "last-good"
            if site_dir.exists():
                site_dir.rename(backup)
            try:
                candidate.rename(site_dir)
            except BaseException:
                if backup.exists():
                    backup.rename(site_dir)
                raise
            # The returned receipt must refer to the committed destination.
            def rebase_paths(value: Any) -> Any:
                if isinstance(value, dict):
                    return {key: rebase_paths(item) for key, item in value.items()}
                if isinstance(value, list):
                    return [rebase_paths(item) for item in value]
                if isinstance(value, str) and value.startswith(str(candidate) + "/"):
                    return str(site_dir) + value[len(str(candidate)):]
                return value

            summary = rebase_paths(summary)
    return summary


def _failed_scheduled_summary(
    *,
    site_dir: Path,
    target: str,
    reason: str,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    last_good = _last_good_reference(site_dir)
    status = {
        "schemaVersion": AUTOMATION_STATUS_SCHEMA_VERSION,
        "contract": AUTOMATION_STATUS_CONTRACT,
        "project": "momentum-factor-lab",
        "state": "failed",
        "reasonCode": reason,
        "attemptedAtUtc": _automation_timestamp(),
        "targetDataAsOf": target,
        "affectedPresetId": None,
        "analysis": {"guardrailsRelaxed": False, "fallbackFactorSelected": False},
        "diagnostics": diagnostics,
        "publication": {
            "updated": False,
            "lastGoodPreserved": last_good is not None,
            "policy": "preserve_last_good",
        },
        "lastGood": last_good,
    }
    path = _write_automation_status(site_dir, status)
    return {"automationStatus": status, "paths": {"automationStatus": str(path)}}


def _build_scheduled_grid(
    run_namespace: argparse.Namespace,
    *,
    site_dir: Path,
    title: str,
    presets: list[ScheduledGridPreset],
    default_preset_id: str,
    target_data_as_of: str,
) -> dict[str, Any]:
    """Rebuild all presets in a private staging tree from one actual snapshot."""

    base_config = _config(run_namespace)
    base_config.site_dir = site_dir
    if not base_config.live or base_config.demo or base_config.prices_path is not None:
        raise ValueError("scheduled static grids require live actual-market data")
    if base_config.max_price_symbols is not None:
        raise ValueError("scheduled static grids require the uncapped full universe")
    if base_config.end_date is not None:
        raise ValueError("scheduled base run must omit --end-date so offset presets roll forward")
    # Resolve the rolling request once, before any provider is called. An
    # unbounded latest download can otherwise include an unfinished session.
    base_config.end_date = target_data_as_of
    base_config.require_current_session = True

    base_inputs = ResearchInputs.from_config(base_config)
    base_market = load_market_data(base_config)
    if len(base_market.candidate_symbols) < MIN_ACTUAL_ANALYZED_SECURITY_COUNT:
        raise ValueError(
            "scheduled static grids require at least "
            f"{MIN_ACTUAL_ANALYZED_SECURITY_COUNT:,} analyzed securities"
        )
    snapshot_dir = base_config.output_dir / "input"
    write_market_data_snapshot(base_market, snapshot_dir)
    sessions = list(base_market.prices.dropna(axis=0, how="all").index.unique())
    if not sessions:
        raise ValueError("scheduled actual-market snapshot has no observed sessions")
    observed = sessions[-1].date().isoformat()
    if observed != target_data_as_of:
        return _failed_scheduled_summary(
            site_dir=site_dir,
            target=target_data_as_of,
            reason=(
                "stale_market_data"
                if observed < target_data_as_of
                else "incomplete_market_session"
            ),
            diagnostics={"observedDataAsOf": observed},
        )

    # A few repaired quotes can advance the maximum date while most holdings
    # remain unpriced. Reject that partial session before expensive analysis.
    prior_rows = base_market.prices.loc[base_market.prices.index < sessions[-1]]
    if not prior_rows.empty:
        candidates = [symbol for symbol in base_market.candidate_symbols
                      if symbol in base_market.prices.columns]
        previous = prior_rows.iloc[-1].reindex(candidates)
        recent = previous.gt(0) & previous.lt(float("inf"))
        current = base_market.prices.iloc[-1].reindex(candidates)
        present = current.gt(0) & current.lt(float("inf"))
        expected_count = int(recent.sum())
        available_count = int((recent & present).sum())
        if expected_count and available_count / expected_count < 0.90:
            return _failed_scheduled_summary(
                site_dir=site_dir, target=target_data_as_of, reason="incomplete_market_data",
                diagnostics={
                    "observedDataAsOf": observed,
                    "previousSessionPricedCandidateCount": expected_count,
                    "targetSessionPricedCandidateCount": available_count,
                    "targetSessionCoverageRatio": available_count / expected_count,
                    "minimumTargetSessionCoverageRatio": 0.90,
                    "missingTargetSymbols": list(current.index[recent & ~present])[:100],
                },
            )

    # Every published preset needs the full comparison curve, including the
    # prior-session preset. Reject unresolved history before running backtests.
    comparison = base_market.comparison_prices
    history_count = max(
        preset.research_inputs.apply(base_config).evaluation_window_days
        + 1 + preset.market_session_offset for preset in presets
    )
    required_dates = base_market.prices.index[-history_count:]
    if "^IXIC" in base_config.comparison_benchmarks and "^IXIC" in comparison:
        index_prices = comparison["^IXIC"].reindex(required_dates)
        gaps = index_prices.index[~(index_prices.gt(0) & index_prices.lt(float("inf")))]
        if len(gaps):
            return _failed_scheduled_summary(
                site_dir=site_dir, target=target_data_as_of, reason="incomplete_market_data",
                diagnostics={"comparisonSymbol": "^IXIC",
                             "missingComparisonDates": [str(day.date()) for day in gaps]},
            )

    artifacts: list[StaticGridArtifact] = []
    results: dict[str, tuple[dict[str, Any], Path]] = {}
    preset_receipts: list[dict[str, Any]] = []
    default_preset = next(preset for preset in presets if preset.preset_id == default_preset_id)
    ordered_presets = [default_preset, *[preset for preset in presets if preset != default_preset]]
    for preset in ordered_presets:
        if preset.market_session_offset >= len(sessions):
            raise ValueError(
                f"static-grid preset {preset.preset_id} requests session offset "
                f"{preset.market_session_offset}, but only {len(sessions)} sessions are available"
            )
        config = preset.research_inputs.apply(base_config)
        config.site_dir = site_dir
        if preset.preset_id != default_preset_id:
            config.output_dir = base_config.output_dir / "grid-presets" / preset.preset_id
            config.export_input_snapshot = False
        if preset.market_session_offset:
            config.end_date = sessions[-1 - preset.market_session_offset].date().isoformat()
        config.refresh_market_data = False
        config.validate()

        use_base_market = (
            preset.market_session_offset == 0 and preset.research_inputs == base_inputs
        )
        if use_base_market:
            market = base_market
        else:
            market = read_market_data_snapshot(config, snapshot_dir)
            market.requested_through = config.effective_end_date
        try:
            payload, result_path = _compute_payload(config, market)
        except NoEligibleFactorError as error:
            market_as_of = getattr(market, "as_of", None)
            preset_data_as_of = (
                str(market_as_of)[:10]
                if market_as_of is not None
                else (config.end_date or str(sessions[-1].date()))
            )
            automation_status, automation_status_path = _unavailable_automation_status(
                site_dir=site_dir,
                preset_id=preset.preset_id,
                target_data_as_of=target_data_as_of,
                error=error,
                preset_data_as_of=preset_data_as_of,
            )
            return {
                "automationStatus": automation_status,
                "paths": {"automationStatus": str(automation_status_path)},
            }
        _require_full_actual_publication(payload, config)
        summary_payload = dashboard_summary(payload)
        artifacts.append(
            StaticGridArtifact(
                detail=payload,
                summary=summary_payload,
                preset_id=preset.preset_id,
            )
        )
        results[preset.preset_id] = (payload, result_path)
        preset_receipts.append(
            {
                "id": preset.preset_id,
                "marketSessionOffset": preset.market_session_offset,
                "resultKey": payload["resultKey"],
                "dataAsOf": payload["data"]["asOf"],
                "researchInputs": payload["researchInputs"],
            }
        )
        if use_base_market:
            base_market = None

    default_payload, default_result_path = results[default_preset_id]
    paths = write_dashboard_site(default_payload, site_dir, title=title)
    grid_paths = write_static_grid(
        site_dir / "data",
        artifacts,
        default_result_key=str(default_payload["resultKey"]),
        write_default_aliases=True,
    )
    validate_static_grid(grid_paths["manifest"])
    paths["gridManifest"] = str(grid_paths["manifest"])
    paths["result"] = str(default_result_path)
    summary = _compact_summary(default_payload, paths)
    summary["staticGridPresets"] = preset_receipts
    automation_status, automation_status_path = _available_automation_status(
        site_dir=site_dir,
        payload=default_payload,
        preset_count=len(preset_receipts),
    )
    summary["automationStatus"] = automation_status
    summary["paths"]["automationStatus"] = str(automation_status_path)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command in {"integrated-collect", "integrated-amend", "integrated-run", "serve-integrated"}:
            from .integrated_cli import dispatch
            return dispatch(args)
        if args.command == "build-site":
            if args.site_dir.resolve() == Path("docs").resolve():
                raise ValueError(
                    "build-site cannot write the public docs aliases; use build-static-grid "
                    "with a validated actual-market detail/summary pair"
                )
            paths = write_dashboard_site(args.input, args.site_dir, title=args.title)
            print(json.dumps(paths, ensure_ascii=False, indent=2))
            return 0
        if args.command == "build-static-grid":
            preset_ids = args.preset_id or [None] * len(args.artifact)
            if len(preset_ids) != len(args.artifact):
                raise ValueError(
                    "build-static-grid requires one --preset-id per --artifact or none"
                )
            artifacts = [
                StaticGridArtifact(
                    detail=json.loads(detail_path.read_text(encoding="utf-8")),
                    summary=json.loads(summary_path.read_text(encoding="utf-8")),
                    preset_id=preset_id,
                )
                for (detail_path, summary_path), preset_id in zip(
                    args.artifact,
                    preset_ids,
                    strict=True,
                )
            ]
            paths = write_static_grid(
                args.site_dir / "data",
                artifacts,
                default_result_key=args.default_result_key,
                write_default_aliases=args.write_default_aliases,
            )
            print(
                json.dumps(
                    {key: str(path) for key, path in paths.items()},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.command == "serve-local-api":
            config = _config(args)
            service = LocalResearchAPI(
                config,
                bind_host=args.host,
                allow_non_loopback=args.allow_non_loopback,
                allowed_origins=args.allowed_origin,
            )
            server = service.create_http_server(port=args.port)
            host, port = server.server_address[:2]
            print(f"local_api=http://{host}:{port}")
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                return 0
            finally:
                server.server_close()
                service.close()
            return 0
        if args.command == "scheduled-dashboard":
            run_namespace, site_dir, title, presets, default_preset_id = _load_scheduled_config(
                args
            )
            summary = _execute_scheduled_grid(
                run_namespace,
                site_dir=site_dir,
                title=title,
                presets=presets,
                default_preset_id=default_preset_id,
            )
            summary["scheduledDashboard"] = {
                "config": str(args.config),
                "siteDir": str(site_dir),
                "title": title,
            }
            if args.json:
                print(json.dumps(summary, ensure_ascii=False, indent=2))
            elif summary.get("automationStatus", {}).get("state") in {
                "degraded",
                "unavailable",
                "failed",
            }:
                automation = summary["automationStatus"]
                print(
                    f"automation_state={automation['state']} "
                    f"reason={automation['reasonCode']} "
                    f"target_data_as_of={automation['targetDataAsOf']} "
                    f"last_good_preserved={automation['publication']['lastGoodPreserved']}"
                )
            else:
                _print_run_summary(summary)
            automation = summary.get("automationStatus", {})
            if (
                automation.get("state") == "failed"
                or automation.get("reasonCode") == "no_comparable_factor"
            ):
                return 2
            return 0

        summary = _execute_run(args)
        if args.json:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            _print_run_summary(summary)
        return 0
    except ValueError as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
