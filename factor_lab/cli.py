from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from .config import (
    MAX_TOP_N,
    RunConfig,
    minimum_evaluation_observations,
)
from .data import (
    MarketData,
    load_market_data,
)
from .dashboard import DEFAULT_SITE_TITLE, dashboard_summary, write_dashboard_site
from .identity import build_result_identity, load_analysis_cache, write_analysis_cache
from .static_grid import (
    MIN_ACTUAL_ANALYZED_SECURITY_COUNT,
    StaticGridArtifact,
    write_static_grid,
)
from .universe import normalize_symbols
from .workflow import (
    result_payload,
    run_analysis,
    write_payload_json,
)






def _add_run_arguments(run: argparse.ArgumentParser) -> None:
    source = run.add_mutually_exclusive_group(required=True)
    run.set_defaults(live=False)
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

    run.add_argument("--universe", help="Comma-separated symbols for offline or demo inputs")

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
            "Compare momentum factors from reviewed local files or a "
            "deterministic demo. This research application does not place orders."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser(
        "run",
        help="Compare all available momentum factors and build the website",
    )
    _add_run_arguments(run)

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
                "build-static-grid with the complete reviewed preset set"
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












def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command in {
            "integrated-amend", "integrated-universe",
            "integrated-apply-universe", "integrated-run", "serve-integrated",
        }:
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
