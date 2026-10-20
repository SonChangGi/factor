from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from factor_lab.config import FIXED_WEIGHTING_POLICY, RunConfig
from factor_lab.dashboard import _load_payload, write_dashboard_site
from factor_lab.workflow import (
    _absolute_guardrail_profile,
    _analysis_prices,
    _latest_portfolios,
    _liquidity_context,
    result_payload,
    run_analysis,
    write_result_json,
)


MINIMUM_SCALE_SYMBOLS = 2_701
EXPECTED_FACTOR_COUNT = 64
EXPECTED_INDEPENDENT_FACTOR_COUNT = 61
EXPECTED_ALIAS_FACTOR_COUNT = 3
LONGEST_RAW_SIGNAL_FORMATION_SESSIONS = 294


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a deterministic synthetic 2701+-symbol scale/contract stress case. "
            "This is not actual-market evidence and must not be published as a live result."
        )
    )
    parser.add_argument("--symbols", type=int, default=MINIMUM_SCALE_SYMBOLS)
    parser.add_argument("--start-date", default="2019-01-01")
    parser.add_argument("--end-date", default="2023-02-28")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--missing-ratio", type=float, default=0.0)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--site-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser


def _max_rss_bytes(usage: resource.struct_rusage) -> int:
    return int(usage.ru_maxrss if sys.platform == "darwin" else usage.ru_maxrss * 1024)


def _finite_number(value: object) -> bool:
    return (
        not isinstance(value, (bool, np.bool_))
        and isinstance(value, (int, float, np.integer, np.floating))
        and np.isfinite(float(value))
    )


def _close(left: object, right: object, *, atol: float = 1e-9) -> bool:
    return (
        _finite_number(left)
        and _finite_number(right)
        and bool(np.isclose(float(left), float(right), rtol=0.0, atol=atol))
    )


def _json_equivalent(left: object, right: object) -> bool:
    if isinstance(left, dict) and isinstance(right, dict):
        return set(left) == set(right) and all(
            _json_equivalent(left[key], right[key]) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _json_equivalent(a, b) for a, b in zip(left, right, strict=True)
        )
    if _finite_number(left) or _finite_number(right):
        return _close(left, right)
    return left == right


def _validate_payload_contract(
    payload: dict[str, Any],
    *,
    args: argparse.Namespace,
    config: RunConfig,
) -> list[str]:
    """Validate the schema-v5, one-method, input-driven stress artifact."""

    failures: list[str] = []
    decision = payload.get("factorSelectionDecision")
    if not isinstance(decision, dict) or decision.get(
        "guardrailProfile"
    ) != _absolute_guardrail_profile(config):
        failures.append("decision:absolute_guardrail_profile_exact")
    try:
        _load_payload(payload)
    except (KeyError, TypeError, ValueError) as error:
        failures.append(f"payload:schema_v5_contract:{error}")

    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    accounting = (
        payload.get("factorAccounting") if isinstance(payload.get("factorAccounting"), dict) else {}
    )
    expected_counts = {
        "requestedCandidateCount": args.symbols,
        "providerReturnedCandidateCount": args.symbols,
        "inputSecurityCount": args.symbols,
        "analyzedSecurityCount": args.symbols,
    }
    if payload.get("schemaVersion") != 5:
        failures.append("payload:schema_version")
    if data.get("mode") != "demo" or data.get("synthetic") is not True:
        failures.append("payload:synthetic_demo_identity")
    for field, expected in expected_counts.items():
        if data.get(field) != expected:
            failures.append(f"payload:{field}")
    if meta.get("factorCount") != EXPECTED_FACTOR_COUNT:
        failures.append("payload:factor_count")
    if accounting.get("expectedIndependentFactorCount") != EXPECTED_INDEPENDENT_FACTOR_COUNT:
        failures.append("payload:expected_independent_factor_count")
    if accounting.get("evaluatedIndependentFactorCount") != EXPECTED_INDEPENDENT_FACTOR_COUNT:
        failures.append("payload:evaluated_independent_factor_count")
    if payload.get("weightingPolicy") != FIXED_WEIGHTING_POLICY:
        failures.append("payload:fixed_weighting_method")
    forbidden = {
        "currentResearchTarget",
        "selectedWeightingPolicy",
        "factorPolicyRanking",
        "gridAccounting",
        "policyDiagnostics",
        "weightingPolicyRegistry",
    }
    for field in sorted(forbidden.intersection(payload)):
        failures.append(f"payload:forbidden_legacy_field:{field}")
    return list(dict.fromkeys(failures))


def _recompute_all_current_portfolios(
    result: Any,
    payload: dict[str, Any],
) -> tuple[list[str], dict[str, dict[str, Any]], int]:
    """Rebuild all 64 current portfolios under the one fixed methodology."""

    config = result.config
    market = result.market_data
    policy_id = str(payload["weightingPolicy"])
    best_factor = str(payload["bestFactor"])
    prices = _analysis_prices(market)
    liquidity = _liquidity_context(
        market.dollar_volumes.reindex(index=prices.index, columns=prices.columns),
        config,
    )
    market_caps = market.market_caps.reindex(index=prices.index, columns=prices.columns)
    recomputed = _latest_portfolios(
        result.factor_scores,
        market,
        config,
        policy_id,
        liquidity,
        market_caps,
    )
    failures: list[str] = []
    ranking = payload.get("factorRanking")
    serialized_portfolios = payload.get("factorPortfolios")
    if not isinstance(ranking, list):
        return ["recomputed_current:serialized_ranking_not_a_list"], {}, 0
    if not isinstance(serialized_portfolios, dict):
        return ["recomputed_current:serialized_portfolios_not_an_object"], {}, 0
    rows = {
        str(row.get("factor")): row
        for row in ranking
        if isinstance(row, dict) and row.get("policy_id") == policy_id
    }
    if set(rows) != set(recomputed):
        failures.append("recomputed_current:serialized_factor_set")
    if set(serialized_portfolios) != set(recomputed):
        failures.append("recomputed_current:serialized_portfolio_factor_set")

    available = 0
    holding_counts: list[float] = []
    cash_weights: list[float] = []
    for factor, portfolio in recomputed.items():
        label = f"recomputed_current:{policy_id}:{factor}"
        portfolio_payload = portfolio.to_dict()
        serialized = serialized_portfolios.get(factor)
        if not isinstance(serialized, dict) or not _json_equivalent(portfolio_payload, serialized):
            failures.append(f"{label}:serialized_factor_portfolio_parity")
        row = rows.get(factor)
        concentration = portfolio_payload.get("concentration")
        if not isinstance(row, dict) or not isinstance(concentration, dict):
            failures.append(f"{label}:serialized_current_row_missing")
            continue
        available_now = portfolio.status == "available"
        available += int(available_now)
        holding_counts.append(float(portfolio_payload["selectedSecurityCount"]))
        cash_weights.append(float(portfolio_payload["cashWeight"]))
        expected_values = {
            "current_portfolio_available": available_now,
            "current_holding_count": portfolio_payload["selectedSecurityCount"],
            "current_cash_weight": portfolio_payload["cashWeight"],
            "current_target_effective_names": concentration["effectiveNames"],
            "current_target_hhi": concentration["riskySleeveHhi"],
            "current_target_max_weight": concentration["maxWeight"],
        }
        for field, expected in expected_values.items():
            observed = row.get(field)
            matches = (
                observed is expected if isinstance(expected, bool) else _close(observed, expected)
            )
            if not matches:
                failures.append(f"{label}:serialized_current_row_{field}")

    best = recomputed[best_factor].to_dict()
    if not _json_equivalent(best, payload.get("bestFactorPortfolio")):
        failures.append(f"recomputed_current:{policy_id}:{best_factor}:serialized_best_parity")
    summary = {
        "checkedPortfolioCount": len(recomputed),
        "availablePortfolioCount": available,
        "medianHoldingCount": float(np.median(holding_counts)),
        "medianCashWeight": float(np.median(cash_weights)),
    }
    return failures, {policy_id: summary}, len(recomputed)


def _reject_public_output_paths(args: argparse.Namespace) -> None:
    repository = Path(__file__).resolve().parents[1]
    public_roots = {repository / "docs", repository / "public"}
    for candidate in (args.output_dir, args.site_dir, args.report):
        resolved = candidate.expanduser().resolve()
        if any(resolved == root or root in resolved.parents for root in public_roots):
            raise ValueError("synthetic stress artifacts cannot be written to public paths")


def main() -> int:
    args = _parser().parse_args()
    if args.symbols < MINIMUM_SCALE_SYMBOLS:
        raise ValueError(
            f"large-scale contract requires at least {MINIMUM_SCALE_SYMBOLS} candidate symbols"
        )
    _reject_public_output_paths(args)
    config = RunConfig(
        demo=True,
        demo_symbol_count=args.symbols,
        demo_seed=args.seed,
        demo_missing_ratio=args.missing_ratio,
        start_date=args.start_date,
        end_date=args.end_date,
        output_dir=args.output_dir,
        site_dir=args.site_dir,
    )
    started = time.perf_counter()
    result = run_analysis(config)
    result_path = write_result_json(result)
    site_paths = write_dashboard_site(result, config.site_dir)
    payload = result_payload(result)

    validation_failures = _validate_payload_contract(payload, args=args, config=config)
    current_failures, current_summaries, checked = _recompute_all_current_portfolios(
        result, payload
    )
    validation_failures.extend(current_failures)
    ranking = payload["factorRanking"]
    selected_row = next(row for row in ranking if row["selected"] is True)
    best_portfolio = payload["bestFactorPortfolio"]
    status_counts = Counter(str(row["comparison_status"]) for row in ranking)
    reason_counts: Counter[str] = Counter()
    for row in ranking:
        reason_counts.update(str(code) for code in row.get("exclusion_reason_codes", []))

    candidates = result.market_data.candidate_symbols
    candidate_prices = result.market_data.prices.loc[:, candidates]
    denominator = max(1, (len(candidate_prices.index) - 1) * len(candidates))
    missing_cells = int(candidate_prices.iloc[:-1].isna().to_numpy().sum())
    final_missing_cells = int(candidate_prices.iloc[-1].isna().sum())
    realized_missing_ratio = missing_cells / denominator
    if args.missing_ratio == 0.0 and missing_cells:
        validation_failures.append("fixture:clean_case_contains_missing_candidate_prices")
    if args.missing_ratio and realized_missing_ratio < args.missing_ratio:
        validation_failures.append("fixture:realized_missing_ratio_below_request")
    if final_missing_cells:
        validation_failures.append("fixture:final_candidate_quotes_missing")

    session_count = int(payload["data"]["observations"])
    pre_evaluation_sessions = session_count - config.evaluation_window_days
    if pre_evaluation_sessions < LONGEST_RAW_SIGNAL_FORMATION_SESSIONS:
        validation_failures.append("fixture:insufficient_pre_evaluation_signal_formation")
    available_rows = [row for row in ranking if row["comparison_status"] == "available"]
    min_observations = min(float(row["observations"]) for row in available_rows)
    min_risk_observations = min(float(row["daily_risk_observations"]) for row in available_rows)
    wall_seconds = time.perf_counter() - started
    usage = resource.getrusage(resource.RUSAGE_SELF)
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    report = {
        "validationStatus": "passed" if not validation_failures else "failed",
        "purpose": "deterministic_synthetic_scale_and_schema_v5_validation_only",
        "syntheticStress": True,
        "actualMarketEvidence": False,
        "publicationAllowed": False,
        "warning": (
            "Synthetic data validates scale, the fixed allocation method, factor accounting, "
            "and portfolio invariants only. It is not a current-market result."
        ),
        "stressMode": "sparse_missing" if args.missing_ratio else "clean",
        "config": {
            "symbols": args.symbols,
            "startDate": args.start_date,
            "endDate": args.end_date,
            "seed": args.seed,
            "requestedMissingRatio": args.missing_ratio,
            "researchInputs": payload["researchInputs"],
        },
        "result": {
            "schemaVersion": payload["schemaVersion"],
            "resultKey": payload["resultKey"],
            "bestFactor": payload["bestFactor"],
            "weightingPolicy": payload["weightingPolicy"],
            "bestSelectionScore": selected_row["selection_score"],
            "bestHoldingCount": best_portfolio["selectedSecurityCount"],
            "bestCashWeight": best_portfolio["cashWeight"],
            "factorAccounting": payload["factorAccounting"],
            "factorCount": payload["meta"]["factorCount"],
            "portfolioCount": payload["meta"]["portfolioCount"],
        },
        "fixedMethodPortfolioValidation": {
            "expectedPortfolioCount": EXPECTED_FACTOR_COUNT,
            "checkedPortfolioCount": checked,
            "methodSummaries": current_summaries,
            "failures": current_failures,
        },
        "factorStatusCounts": dict(sorted(status_counts.items())),
        "factorExclusionReasonCounts": dict(sorted(reason_counts.items())),
        "evaluationCoverage": {
            "minimumObservedEvaluationObservations": min_observations,
            "minimumObservedDailyRiskObservations": min_risk_observations,
        },
        "missingness": {
            "candidateMissingCellsExcludingFinalDate": missing_cells,
            "realizedMissingRatioExcludingFinalDate": realized_missing_ratio,
            "finalCandidateMissingCells": final_missing_cells,
        },
        "validationFailures": validation_failures,
        "performance": {
            "analysisWallSeconds": result.runtime_seconds,
            "harnessWallSeconds": wall_seconds,
            "analysisPeakRssBytes": result.max_rss_bytes,
            "harnessPeakRssBytes": _max_rss_bytes(usage),
            "payloadBytes": len(encoded),
            "resultJsonBytes": result_path.stat().st_size,
            "dashboardJsonBytes": Path(site_paths["data"]).stat().st_size,
        },
        "paths": {"result": str(result_path), **site_paths, "report": str(args.report)},
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if validation_failures:
        raise RuntimeError(
            f"large-scale validation failed with {len(validation_failures)} issue(s); "
            f"see {args.report}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
