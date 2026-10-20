from __future__ import annotations

import hashlib
import json
import math
import shutil
from copy import deepcopy
from dataclasses import fields
from datetime import date as calendar_date
from pathlib import Path
from statistics import median
from typing import Any

from .advanced_factors import advanced_factor_definitions_frame
from .config import (
    ABSOLUTE_GUARDRAIL_VERSION,
    FACTOR_SELECTION_VERSION,
    FIXED_WEIGHTING_POLICY,
    POLICY_REGISTRY,
    POLICY_REGISTRY_VERSION,
    RunConfig,
    WEIGHTING_POLICIES,
)
from .data import (
    LIVE_SNAPSHOT_HASH_FIELDS,
    LIVE_SNAPSHOT_HASH_FIELDS_V2,
    canonical_records_sha256,
)
from .identity import (
    CANONICAL_JSON_VERSION,
    RESULT_IDENTITY_VERSION,
    canonical_json_bytes,
    canonical_sha256,
)
from .factors import factor_definitions_frame
from .portfolio import TIE_BREAK_POLICY, capped_weight_values
from .research_inputs import (
    LEGACY_RESEARCH_INPUTS_VERSION,
    TRADING_SESSIONS_PER_YEAR,
    ResearchInputError,
    ResearchInputs,
)
from .workflow import (
    FACTOR_HOLDING_HISTORY_SIDECAR_CONTRACT,
    FACTOR_HOLDING_HISTORY_SIDECAR_CONTRACT_VERSION,
    FACTOR_HOLDING_HISTORY_SIDECAR_DIRECTORY,
    FACTOR_DIAGNOSTICS_CONTRACT_VERSION,
    FACTOR_DIAGNOSTICS_MAX_SIGNAL_SESSIONS,
    FACTOR_DIAGNOSTICS_RANK_IC_HORIZON_SESSIONS,
    FACTOR_DIAGNOSTICS_RANK_IC_METHOD,
    FACTOR_DIAGNOSTICS_REDUNDANCY_METHOD,
    FACTOR_DIAGNOSTICS_REDUNDANCY_THRESHOLD,
    FACTOR_DIAGNOSTICS_TOP_PAIR_COUNT,
    MAX_FACTOR_HOLDING_HISTORY_SIDECAR_BYTES,
    PERFORMANCE_CONTRACT_VERSION,
    PERFORMANCE_METRIC_KEYS,
    PERFORMANCE_PERIODS,
    SELECTED_HOLDING_HISTORY_CONTRACT_VERSION,
    SELECTED_HOLDING_HISTORY_SESSION_COUNT,
    SELECTED_HOLDING_HISTORY_WEIGHT_TIMING,
    AnalysisResult,
    FACTOR_SELECTION_TIE_BREAK_POLICY,
    _absolute_guardrail_profile,
    result_payload,
)


DEFAULT_SITE_TITLE = "Factor"
WEB_ROOT = Path(__file__).with_name("web")
# The complete Top-30 detail now includes 64 exact current targets plus the
# 61-factor diagnostic evidence. Keep a bounded publication ceiling while
# allowing the measured 5.03 MB canonical payload without dropping evidence.
MAX_DASHBOARD_BYTES = 5_500_000

_LEGACY_SCHEMA_KEYS = {
    "factorRanking",
    "modelPortfolio",
    "policyFactorMetrics",
    "tieBreakPolicy",
    "weightingPolicyComparison",
    "weightingPolicyDefinitions",
    "weightingPolicyReason",
}
_STANDARD_GUARDRAILS = (
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
)
_CONTRIBUTION_GUARDRAILS = (
    "guardrail_security_day_contribution",
    "guardrail_security_absolute_contribution_share",
    "guardrail_leave_one_security",
)
_POLICY_DIAGNOSTIC_METRICS = (
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
_FACTOR_PORTFOLIO_FIELDS = frozenset(
    {
        "weightingPolicyId",
        "weightingPolicyVersion",
        "signalDate",
        "status",
        "eligibleSecurityCount",
        "selectedSecurityCount",
        "cashWeight",
        "reasons",
        "componentStatus",
        "concentration",
        "tieBreakPolicy",
        "weights",
        "factor",
        "asOf",
        "targetType",
        "executionTiming",
        "selectionFraction",
    }
)
_FACTOR_PORTFOLIO_WEIGHT_FIELDS = frozenset(
    {
        "rank",
        "symbol",
        "name",
        "factorScore",
        "latestPrice",
        "eligibilityStatus",
        "rawPolicyScore",
        "preCapWeight",
        "weight",
        "maxWeight",
        "capBinding",
        "rankComponent",
        "trailingDollarVolume",
        "trailingMarketCap",
        "scoreComponent",
        "liquidityComponent",
        "marketCapComponent",
    }
)
_CONCENTRATION_FIELDS = frozenset(
    {
        "investedWeight",
        "cashWeight",
        "riskySleeveHhi",
        "effectiveNames",
        "top1Weight",
        "top5Weight",
        "maxWeight",
    }
)
_AVAILABLE_FACTOR_PORTFOLIO_REASONS = frozenset(
    {
        "top_n_boundary_tie_resolved_by_trailing_dollar_volume",
        "fewer_complete_policy_inputs_than_top_n",
        "max_weight_capacity_or_missing_policy_inputs",
    }
)
_UNAVAILABLE_FACTOR_PORTFOLIO_COMPONENTS = {
    "no_complete_signal_inputs": {},
    "no_finite_trailing_dollar_volume": {"liquidity": "unavailable"},
    "no_point_in_time_market_cap": {"marketCap": "unavailable"},
    "no_finite_trailing_dollar_volume+no_point_in_time_market_cap": {
        "liquidity": "unavailable",
        "marketCap": "unavailable",
    },
    "no_complete_fixed_policy_inputs": {
        "liquidity": "partial",
        "marketCap": "partial",
    },
    "top_n_boundary_tie_has_no_finite_liquidity_tie_break": {},
}


def _finite_number(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def _nonnegative_integer(value: object) -> bool:
    return _finite_number(value) and float(value).is_integer() and float(value) >= 0.0


def _required_text(value: object) -> str:
    return str(value).strip() if isinstance(value, str) else ""


def _close(left: float, right: float, tolerance: float = 1e-9) -> bool:
    return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=tolerance)


def _require_close(observed: object, expected: float, label: str) -> None:
    if not _finite_number(observed) or not _close(float(observed), expected):
        raise ValueError(f"{label} is inconsistent")


def _require_optional_close(observed: object, expected: object, label: str) -> None:
    if _finite_number(expected):
        _require_close(observed, float(expected), label)
    elif observed is not None:
        raise ValueError(f"{label} must be null")


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _ratio_severity(observed: float, threshold: float) -> float:
    if observed <= threshold:
        return 0.0
    if threshold <= 0.0:
        return 1.0
    return min(1.0, max(0.0, observed / threshold - 1.0))


def _percentile_rank(values: list[float], position: int) -> float:
    value = values[position]
    lower = sum(candidate < value for candidate in values)
    tied = sum(candidate == value for candidate in values)
    return (lower + (tied + 1.0) / 2.0) / len(values)


def _ascending_average_rank(values: list[float], position: int) -> float:
    value = values[position]
    lower = sum(candidate < value for candidate in values)
    tied = sum(candidate == value for candidate in values)
    return lower + (tied + 1.0) / 2.0


def _validate_identity(payload: dict[str, Any]) -> None:
    identity = payload.get("resultIdentity")
    core_identity_fields = {"identityVersion", "resultKey", "keyParts"}
    transport_identity_fields = {*core_identity_fields, "canonicalKeyPartsJson"}
    if not isinstance(identity, dict):
        raise ValueError("dashboard resultIdentity shape is invalid")
    identity_fields = frozenset(identity)
    if identity_fields not in {
        frozenset(core_identity_fields),
        frozenset(transport_identity_fields),
    }:
        raise ValueError("dashboard resultIdentity shape is invalid")
    key_parts = identity.get("keyParts")
    expected_key_part_fields = {
        "identityVersion",
        "canonicalJsonVersion",
        "analysisCacheVersion",
        "normalizedInputs",
        "marketSnapshot",
        "factorDefinitionSha256",
        "policyDefinitionSha256",
        "selectionSpecSha256",
        "engineSha256",
    }
    if not isinstance(key_parts, dict) or set(key_parts) != expected_key_part_fields:
        raise ValueError("dashboard resultIdentity.keyParts shape is invalid")
    result_key = identity.get("resultKey")
    if (
        identity.get("identityVersion") != RESULT_IDENTITY_VERSION
        or key_parts.get("identityVersion") != RESULT_IDENTITY_VERSION
        or key_parts.get("canonicalJsonVersion") != CANONICAL_JSON_VERSION
        or not _is_sha256(result_key)
        or payload.get("resultKey") != result_key
        or canonical_sha256(key_parts) != result_key
    ):
        raise ValueError("dashboard result identity digest is inconsistent")
    canonical_key_parts_json = identity.get("canonicalKeyPartsJson")
    if canonical_key_parts_json is not None and (
        not isinstance(canonical_key_parts_json, str)
        or canonical_key_parts_json != canonical_json_bytes(key_parts).decode("utf-8")
    ):
        raise ValueError("dashboard result identity canonical transport is inconsistent")
    for field in (
        "factorDefinitionSha256",
        "policyDefinitionSha256",
        "selectionSpecSha256",
        "engineSha256",
    ):
        if not _is_sha256(key_parts.get(field)):
            raise ValueError(f"dashboard resultIdentity.keyParts.{field} is invalid")

    normalized = key_parts.get("normalizedInputs")
    market_snapshot = key_parts.get("marketSnapshot")
    data = payload.get("data")
    config = payload.get("config")
    meta = payload.get("meta")
    if not all(
        isinstance(value, dict) for value in (normalized, market_snapshot, data, config, meta)
    ):
        raise ValueError("dashboard result identity source objects are invalid")
    assert isinstance(normalized, dict)
    assert isinstance(market_snapshot, dict)
    assert isinstance(data, dict)
    assert isinstance(config, dict)
    assert isinstance(meta, dict)
    for field, value in config.items():
        if field in normalized and normalized[field] != value:
            raise ValueError(f"dashboard normalized input {field} differs from config")
    market_fields = {
        "sourceMode": data.get("mode"),
        "sourceLabel": data.get("sourceLabel"),
        "provider": data.get("provider"),
        "priceBasis": data.get("priceBasis"),
        "volumeBasis": data.get("volumeBasis"),
        "rawCloseProxySymbolCount": data.get("rawCloseProxySymbolCount"),
        "requestedThrough": data.get("requestedThrough"),
        "dataAsOf": data.get("asOf"),
        "inputSha256": data.get("inputSha256"),
        "requestedCandidateCount": data.get("requestedCandidateCount"),
        "providerReturnedCandidateCount": data.get("providerReturnedCandidateCount"),
        "analyzedSecurityCount": data.get("analyzedSecurityCount"),
        "candidateSymbolsSha256": canonical_sha256(data.get("analyzedSymbols")),
        "comparisonSymbols": data.get("comparisonSymbols"),
        "comparisonPricesSha256": data.get("comparisonPricesSha256"),
    }
    if any(market_snapshot.get(field) != value for field, value in market_fields.items()):
        raise ValueError("dashboard result identity market snapshot differs from data")
    meta_digest_fields = {
        "factorDefinitionSha256": "factorDefinitionSha256",
        "policyDefinitionSha256": "policyDefinitionSha256",
        "selectionSpecSha256": "selectionSpecSha256",
    }
    if any(
        key_parts.get(key_field) != meta.get(meta_field)
        for key_field, meta_field in meta_digest_fields.items()
    ):
        raise ValueError("dashboard result identity definition digests differ from meta")


def _validate_data(payload: dict[str, Any]) -> str:
    data = payload.get("data")
    config = payload.get("config")
    if not isinstance(data, dict) or not isinstance(config, dict):
        raise ValueError("dashboard data and config must be objects")
    mode = data.get("mode")
    if mode not in {"live_market", "local_file", "demo"}:
        raise ValueError("dashboard data.mode is unsupported")
    expected_synthetic = mode == "demo"
    if data.get("synthetic") is not expected_synthetic:
        raise ValueError("dashboard data synthetic flag differs from data.mode")
    if config.get("data_mode") != mode:
        raise ValueError("dashboard config.data_mode differs from data.mode")
    as_of = _required_text(data.get("asOf"))
    if not as_of or not _required_text(data.get("startDate")):
        raise ValueError("dashboard data date contract is incomplete")
    if str(data["startDate"]) > as_of:
        raise ValueError("dashboard data date range is inconsistent")
    if not _nonnegative_integer(data.get("observations")) or int(data["observations"]) <= 0:
        raise ValueError("dashboard data observations are invalid")
    count_fields = (
        "requestedCandidateCount",
        "providerReturnedCandidateCount",
        "inputSecurityCount",
        "analyzedSecurityCount",
        "latestEligibleSecurityCount",
    )
    if any(not _nonnegative_integer(data.get(field)) for field in count_fields):
        raise ValueError("dashboard universe-count metadata is invalid")
    if not (
        int(data["latestEligibleSecurityCount"])
        <= int(data["analyzedSecurityCount"])
        <= int(data["inputSecurityCount"])
        <= int(data["providerReturnedCandidateCount"])
        <= int(data["requestedCandidateCount"])
    ):
        raise ValueError("dashboard universe-count funnel is inconsistent")
    funnel = data.get("funnel")
    expected_funnel = {
        "requestedCandidateCount": int(data["requestedCandidateCount"]),
        "providerUsableCandidateCount": int(data["providerReturnedCandidateCount"]),
        "analyzedSecurityCount": int(data["analyzedSecurityCount"]),
        "latestEligibleSecurityCount": int(data["latestEligibleSecurityCount"]),
    }
    if (
        not isinstance(funnel, dict)
        or funnel.get("label") != "canonical_analysis_funnel"
        or funnel.get("authoritative") is not True
        or any(funnel.get(field) != value for field, value in expected_funnel.items())
    ):
        raise ValueError("dashboard canonical data funnel is missing or inconsistent")
    if mode == "live_market":
        input_hashes = data.get("inputSha256")
        read_contract = data.get("snapshotReadContract")
        observed_hash_fields = set(input_hashes) if isinstance(input_hashes, dict) else set()
        supported_hash_fields = {
            frozenset(LIVE_SNAPSHOT_HASH_FIELDS),
            frozenset(LIVE_SNAPSHOT_HASH_FIELDS_V2),
        }
        if (
            data.get("rawCloseAvailable") is not True
            or not isinstance(input_hashes, dict)
            or frozenset(observed_hash_fields) not in supported_hash_fields
            or any(not _is_sha256(input_hashes.get(field)) for field in observed_hash_fields)
            or not isinstance(read_contract, dict)
            or read_contract.get("pandasFloatPrecision") != "round_trip"
        ):
            raise ValueError("live_market input snapshot hash contract is incomplete")
        price_sources = payload.get("priceSources")
        source_health = payload.get("sourceHealth")
        if (
            not isinstance(price_sources, list)
            or not price_sources
            or not isinstance(source_health, list)
            or not source_health
            or not _is_sha256(input_hashes.get("priceSources"))
            or not _is_sha256(input_hashes.get("dataSources"))
        ):
            raise ValueError("live_market provider provenance contract is incomplete")
        price_source_symbols: set[str] = set()
        for row in price_sources:
            if not isinstance(row, dict):
                raise ValueError("live_market priceSources contains a non-object row")
            symbol = _required_text(row.get("symbol")).upper()
            source = _required_text(row.get("price_source"))
            if not symbol or not source or symbol in price_source_symbols:
                raise ValueError("live_market priceSources rows are invalid or duplicated")
            price_source_symbols.add(symbol)
        analyzed_symbols = data.get("analyzedSymbols")
        if (
            not isinstance(analyzed_symbols, list)
            or len(analyzed_symbols) != int(data["analyzedSecurityCount"])
            or any(not _required_text(symbol) for symbol in analyzed_symbols)
        ):
            raise ValueError("live_market analyzedSymbols contract is incomplete")
        normalized_analyzed_symbols = [str(symbol).strip().upper() for symbol in analyzed_symbols]
        if len(set(normalized_analyzed_symbols)) != len(normalized_analyzed_symbols) or not set(
            normalized_analyzed_symbols
        ).issubset(price_source_symbols):
            raise ValueError("live_market priceSources do not cover the analyzed universe")
        if any(
            not isinstance(row, dict)
            or not _required_text(row.get("source"))
            or not _required_text(row.get("status"))
            for row in source_health
        ):
            raise ValueError("live_market sourceHealth source/status rows are invalid")
        if (
            canonical_records_sha256(price_sources) != input_hashes["priceSources"]
            or canonical_records_sha256(source_health) != input_hashes["dataSources"]
        ):
            raise ValueError("live_market provider provenance hashes are inconsistent")
    return as_of


def _validate_registry(payload: dict[str, Any]) -> None:
    registry = payload.get("weightingPolicyRegistry")
    if registry != {
        "registryVersion": POLICY_REGISTRY_VERSION,
        "policies": POLICY_REGISTRY,
    }:
        raise ValueError("dashboard weightingPolicyRegistry is not canonical")
    config = payload["config"]
    if config.get("policy_registry_version") != POLICY_REGISTRY_VERSION or config.get(
        "weighting_policies"
    ) != list(WEIGHTING_POLICIES):
        raise ValueError("dashboard configured weighting-policy registry is inconsistent")


def _reconstruct_run_config(payload: dict[str, Any]) -> RunConfig:
    config = payload["config"]
    run_fields = {field.name for field in fields(RunConfig)}
    try:
        return RunConfig(**{key: value for key, value in config.items() if key in run_fields})
    except (TypeError, ResearchInputError) as error:
        raise ValueError("dashboard config cannot reconstruct canonical researchInputs") from error


def _validate_research_inputs(payload: dict[str, Any]) -> None:
    reconstructed = _reconstruct_run_config(payload)
    expected = ResearchInputs.from_config(reconstructed).to_dict()
    observed = payload.get("researchInputs")
    if observed == expected:
        return
    evaluation_window_days = expected["evaluationWindowDays"]
    if (
        isinstance(observed, dict)
        and observed.get("version") == LEGACY_RESEARCH_INPUTS_VERSION
        and isinstance(evaluation_window_days, int)
        and evaluation_window_days % TRADING_SESSIONS_PER_YEAR == 0
    ):
        legacy_expected = {
            **expected,
            "version": LEGACY_RESEARCH_INPUTS_VERSION,
            "evaluationYears": (
                evaluation_window_days // TRADING_SESSIONS_PER_YEAR
            ),
        }
        if observed == legacy_expected:
            return
    raise ValueError("dashboard researchInputs differ from the result-affecting config")


def _factor_sets(payload: dict[str, Any]) -> tuple[set[str], set[str]]:
    definitions = payload.get("factorDefinitions")
    if not isinstance(definitions, list) or not definitions:
        raise ValueError("dashboard factorDefinitions must be populated")
    factors: set[str] = set()
    independent: set[str] = set()
    aliases: set[str] = set()
    for definition in definitions:
        if not isinstance(definition, dict) or not _required_text(definition.get("factor")):
            raise ValueError("dashboard factorDefinitions contains an invalid row")
        factor = str(definition["factor"])
        if factor in factors:
            raise ValueError("dashboard factorDefinitions contains duplicate factors")
        factors.add(factor)
        alias_of = definition.get("compatibility_alias_of")
        if alias_of is not None:
            if not _required_text(alias_of) or definition.get("selection_eligible") is not False:
                raise ValueError("dashboard diagnostic alias definition is inconsistent")
            aliases.add(factor)
        elif definition.get("selection_eligible", True) is True:
            independent.add(factor)
    if not independent:
        raise ValueError("dashboard has no independent factor definitions")
    if factors != independent.union(aliases):
        raise ValueError("dashboard contains a non-selectable non-alias factor definition")
    canonical = [
        *factor_definitions_frame().to_dict(orient="records"),
        *advanced_factor_definitions_frame().to_dict(orient="records"),
    ]
    canonical_factors = {str(definition["factor"]) for definition in canonical}
    canonical_aliases = {
        str(definition["factor"])
        for definition in canonical
        if _required_text(definition.get("compatibility_alias_of"))
    }
    canonical_independent = canonical_factors.difference(canonical_aliases)
    if (
        factors != canonical_factors
        or independent != canonical_independent
        or aliases != canonical_aliases
        or len(factors) != 64
        or len(independent) != 61
        or len(aliases) != 3
    ):
        raise ValueError(
            "dashboard factorDefinitions do not satisfy the canonical 64/61/3 registry"
        )
    return independent, aliases


def _validated_iso_date(value: object, label: str) -> str:
    rendered = _required_text(value)
    try:
        parsed = calendar_date.fromisoformat(rendered)
    except ValueError as error:
        raise ValueError(f"{label} is not an ISO calendar date") from error
    if parsed.isoformat() != rendered:
        raise ValueError(f"{label} is not a canonical ISO calendar date")
    return rendered


def _validate_factor_diagnostics(
    payload: dict[str, Any],
    *,
    independent: set[str],
    aliases: set[str],
) -> None:
    diagnostics = payload.get("factorDiagnostics")
    if (
        not isinstance(diagnostics, dict)
        or diagnostics.get("contractVersion") != FACTOR_DIAGNOSTICS_CONTRACT_VERSION
    ):
        raise ValueError("dashboard factorDiagnostics contract is missing or unsupported")
    definitions = payload["factorDefinitions"]
    definition_by_factor = {str(row["factor"]): row for row in definitions}
    category_by_factor = {
        factor: _required_text(definition_by_factor[factor].get("category"))
        for factor in independent
    }

    expected_alias_rows = sorted(
        (
            {
                "factor": factor,
                "canonicalFactor": str(definition_by_factor[factor]["compatibility_alias_of"]),
            }
            for factor in aliases
        ),
        key=lambda row: row["factor"],
    )
    scope = diagnostics.get("scope")
    if (
        not isinstance(scope, dict)
        or scope.get("factorCount") != len(independent) + len(aliases)
        or scope.get("independentFactorCount") != len(independent)
        or scope.get("diagnosticAliasCount") != len(aliases)
        or scope.get("aliasHandling") != "excluded_from_rankings"
        or scope.get("aliases") != expected_alias_rows
        or any(row["canonicalFactor"] not in independent for row in expected_alias_rows)
    ):
        raise ValueError("dashboard factorDiagnostics scope or alias mapping is inconsistent")

    rank_ic = diagnostics.get("rankIc")
    signal_dates = rank_ic.get("signalDates") if isinstance(rank_ic, dict) else None
    requested_sessions = (
        rank_ic.get("requestedSignalSessions") if isinstance(rank_ic, dict) else None
    )
    data_observations = payload["data"].get("observations")
    if (
        not isinstance(rank_ic, dict)
        or rank_ic.get("method") != FACTOR_DIAGNOSTICS_RANK_IC_METHOD
        or rank_ic.get("priceBasis") != "analysis_adjusted_close"
        or rank_ic.get("horizonSessions") != FACTOR_DIAGNOSTICS_RANK_IC_HORIZON_SESSIONS
        or rank_ic.get("maximumSignalSessions") != FACTOR_DIAGNOSTICS_MAX_SIGNAL_SESSIONS
        or rank_ic.get("overlapping") is not True
        or not _nonnegative_integer(requested_sessions)
        or not _nonnegative_integer(data_observations)
        or int(requested_sessions)
        != min(FACTOR_DIAGNOSTICS_MAX_SIGNAL_SESSIONS, int(data_observations))
        or not isinstance(signal_dates, list)
        or len(signal_dates) != int(requested_sessions)
        or not signal_dates
    ):
        raise ValueError("dashboard factorDiagnostics Rank-IC methodology is inconsistent")
    validated_signal_dates = [
        _validated_iso_date(value, "dashboard factorDiagnostics signal date")
        for value in signal_dates
    ]
    if (
        validated_signal_dates != sorted(set(validated_signal_dates))
        or rank_ic.get("requestedStartDate") != validated_signal_dates[0]
        or rank_ic.get("requestedEndDate") != validated_signal_dates[-1]
        or validated_signal_dates[-1] != payload["data"].get("asOf")
    ):
        raise ValueError("dashboard factorDiagnostics Rank-IC signal dates are inconsistent")
    maximum_observations = max(
        0,
        len(validated_signal_dates) - FACTOR_DIAGNOSTICS_RANK_IC_HORIZON_SESSIONS,
    )
    latest_forward_signal_date = (
        validated_signal_dates[-FACTOR_DIAGNOSTICS_RANK_IC_HORIZON_SESSIONS - 1]
        if maximum_observations
        else None
    )
    rank_rows = rank_ic.get("rows")
    if (
        not isinstance(rank_rows, list)
        or len(rank_rows) != len(independent)
        or any(not isinstance(row, dict) for row in rank_rows)
        or {str(row.get("factor")) for row in rank_rows} != independent
    ):
        raise ValueError("dashboard factorDiagnostics Rank-IC rows do not cover 61 factors")
    analyzed_count = int(payload["data"]["analyzedSecurityCount"])
    latest_eligible_count = int(payload["data"]["latestEligibleSecurityCount"])
    required_rank_fields = {
        "rank",
        "factor",
        "category",
        "available",
        "unavailableReason",
        "horizonSessions",
        "observations",
        "mean",
        "median",
        "standardDeviation",
        "positiveRate",
        "startDate",
        "endDate",
        "minimumSecurityCount",
        "averageSecurityCount",
        "maximumSecurityCount",
        "latestFiniteCount",
    }
    for position, row in enumerate(rank_rows, start=1):
        factor = str(row["factor"])
        if (
            not required_rank_fields.issubset(row)
            or row.get("rank") != position
            or row.get("category") != category_by_factor[factor]
            or not isinstance(row.get("available"), bool)
            or row.get("horizonSessions") != FACTOR_DIAGNOSTICS_RANK_IC_HORIZON_SESSIONS
            or not _nonnegative_integer(row.get("observations"))
            or int(row["observations"]) > maximum_observations
            or not _nonnegative_integer(row.get("latestFiniteCount"))
            or int(row["latestFiniteCount"]) > latest_eligible_count
        ):
            raise ValueError("dashboard factorDiagnostics Rank-IC row is invalid")
        if row["available"] is True:
            numeric_fields = ("mean", "median", "standardDeviation", "positiveRate")
            if (
                row.get("unavailableReason") is not None
                or int(row["observations"]) <= 0
                or any(not _finite_number(row.get(field)) for field in numeric_fields)
                or not -1.0 <= float(row["mean"]) <= 1.0
                or not -1.0 <= float(row["median"]) <= 1.0
                or not 0.0 <= float(row["standardDeviation"]) <= 1.0
                or not 0.0 <= float(row["positiveRate"]) <= 1.0
            ):
                raise ValueError("dashboard available Rank-IC row is inconsistent")
            start = _validated_iso_date(
                row.get("startDate"), "dashboard factorDiagnostics Rank-IC start"
            )
            end = _validated_iso_date(row.get("endDate"), "dashboard factorDiagnostics Rank-IC end")
            if (
                start not in validated_signal_dates
                or end not in validated_signal_dates
                or start > end
                or latest_forward_signal_date is None
                or end > latest_forward_signal_date
            ):
                raise ValueError("dashboard Rank-IC valid date range is inconsistent")
            minimum = row.get("minimumSecurityCount")
            average = row.get("averageSecurityCount")
            maximum = row.get("maximumSecurityCount")
            if (
                not _nonnegative_integer(minimum)
                or not _finite_number(average)
                or not _nonnegative_integer(maximum)
                or int(minimum) < 3
                or not int(minimum) <= float(average) <= int(maximum)
                or int(maximum) > analyzed_count
            ):
                raise ValueError("dashboard Rank-IC security-count statistics are inconsistent")
        elif (
            not _required_text(row.get("unavailableReason"))
            or int(row["observations"]) != 0
            or any(
                row.get(field) is not None
                for field in (
                    "mean",
                    "median",
                    "standardDeviation",
                    "positiveRate",
                    "startDate",
                    "endDate",
                    "minimumSecurityCount",
                    "averageSecurityCount",
                    "maximumSecurityCount",
                )
            )
        ):
            raise ValueError("dashboard unavailable Rank-IC row is inconsistent")
    expected_rank_order = sorted(
        rank_rows,
        key=lambda row: (
            0 if row["available"] is True else 1,
            -float(row["mean"]) if row["available"] is True else 0.0,
            -int(row["observations"]),
            str(row["factor"]),
        ),
    )
    available_rank_count = sum(row["available"] is True for row in rank_rows)
    if (
        rank_rows != expected_rank_order
        or rank_ic.get("availableFactorCount") != available_rank_count
        or rank_ic.get("unavailableFactorCount") != len(independent) - available_rank_count
        or payload["selectedFactor"] not in {row["factor"] for row in rank_rows}
    ):
        raise ValueError("dashboard factorDiagnostics Rank-IC ordering/counts are inconsistent")

    redundancy = diagnostics.get("redundancy")
    if (
        not isinstance(redundancy, dict)
        or redundancy.get("method") != FACTOR_DIAGNOSTICS_REDUNDANCY_METHOD
        or redundancy.get("diagnosticDate") != payload["data"].get("asOf")
        or not _finite_number(redundancy.get("thresholdAbs"))
        or not _close(
            float(redundancy["thresholdAbs"]),
            FACTOR_DIAGNOSTICS_REDUNDANCY_THRESHOLD,
        )
    ):
        raise ValueError("dashboard factorDiagnostics redundancy methodology is inconsistent")
    redundancy_rows = redundancy.get("rows")
    if (
        not isinstance(redundancy_rows, list)
        or len(redundancy_rows) != len(independent)
        or any(not isinstance(row, dict) for row in redundancy_rows)
        or {str(row.get("factor")) for row in redundancy_rows} != independent
    ):
        raise ValueError("dashboard factorDiagnostics redundancy rows do not cover 61 factors")
    required_redundancy_fields = {
        "rank",
        "factor",
        "category",
        "available",
        "unavailableReason",
        "nearestFactor",
        "signedCorr",
        "absCorr",
        "validPeerCount",
        "highCorrPeerCount",
        "commonSecurityCount",
        "latestFiniteCount",
    }
    latest_counts: dict[str, int] = {}
    for row in redundancy_rows:
        factor = str(row["factor"])
        if (
            not required_redundancy_fields.issubset(row)
            or row.get("category") != category_by_factor[factor]
            or not isinstance(row.get("available"), bool)
            or not _nonnegative_integer(row.get("latestFiniteCount"))
            or int(row["latestFiniteCount"]) > latest_eligible_count
            or not _nonnegative_integer(row.get("validPeerCount"))
            or int(row["validPeerCount"]) > len(independent) - 1
            or not _nonnegative_integer(row.get("highCorrPeerCount"))
            or int(row["highCorrPeerCount"]) > int(row["validPeerCount"])
            or not _nonnegative_integer(row.get("commonSecurityCount"))
        ):
            raise ValueError("dashboard factorDiagnostics redundancy row is invalid")
        latest_counts[factor] = int(row["latestFiniteCount"])
    for position, row in enumerate(redundancy_rows, start=1):
        factor = str(row["factor"])
        if row.get("rank") != position:
            raise ValueError("dashboard factorDiagnostics redundancy rank is inconsistent")
        if row["available"] is True:
            nearest = _required_text(row.get("nearestFactor"))
            if (
                row.get("unavailableReason") is not None
                or nearest not in independent
                or nearest == factor
                or not _finite_number(row.get("signedCorr"))
                or not _finite_number(row.get("absCorr"))
                or not -1.0 <= float(row["signedCorr"]) <= 1.0
                or not 0.0 <= float(row["absCorr"]) <= 1.0
                or not _close(float(row["absCorr"]), abs(float(row["signedCorr"])))
                or int(row["validPeerCount"]) <= 0
                or not 3
                <= int(row["commonSecurityCount"])
                <= min(latest_counts[factor], latest_counts[nearest])
            ):
                raise ValueError("dashboard available redundancy row is inconsistent")
        elif (
            not _required_text(row.get("unavailableReason"))
            or row.get("nearestFactor") is not None
            or row.get("signedCorr") is not None
            or row.get("absCorr") is not None
            or int(row["validPeerCount"]) != 0
            or int(row["highCorrPeerCount"]) != 0
            or int(row["commonSecurityCount"]) != 0
        ):
            raise ValueError("dashboard unavailable redundancy row is inconsistent")
    expected_redundancy_order = sorted(
        redundancy_rows,
        key=lambda row: (
            0 if row["available"] is True else 1,
            -float(row["absCorr"]) if row["available"] is True else 0.0,
            str(row["factor"]),
        ),
    )
    available_redundancy_count = sum(row["available"] is True for row in redundancy_rows)
    eligible_pair_count = redundancy.get("eligiblePairCount")
    high_pair_count = redundancy.get("highRedundancyPairCount")
    maximum_pairs = len(independent) * (len(independent) - 1) // 2
    if (
        redundancy_rows != expected_redundancy_order
        or redundancy.get("availableFactorCount") != available_redundancy_count
        or redundancy.get("unavailableFactorCount") != len(independent) - available_redundancy_count
        or not _nonnegative_integer(eligible_pair_count)
        or int(eligible_pair_count) > maximum_pairs
        or sum(int(row["validPeerCount"]) for row in redundancy_rows)
        != 2 * int(eligible_pair_count)
        or not _nonnegative_integer(high_pair_count)
        or int(high_pair_count) > int(eligible_pair_count)
        or sum(int(row["highCorrPeerCount"]) for row in redundancy_rows) != 2 * int(high_pair_count)
        or redundancy.get("highRedundancyFactorCount")
        != sum(int(row["highCorrPeerCount"]) > 0 for row in redundancy_rows)
    ):
        raise ValueError("dashboard factorDiagnostics redundancy counts are inconsistent")

    top_pairs = redundancy.get("topPairs")
    if (
        not isinstance(top_pairs, list)
        or len(top_pairs) != min(FACTOR_DIAGNOSTICS_TOP_PAIR_COUNT, int(eligible_pair_count))
        or any(not isinstance(row, dict) for row in top_pairs)
    ):
        raise ValueError("dashboard factorDiagnostics top redundancy pairs are incomplete")
    observed_pairs: set[tuple[str, str]] = set()
    for position, row in enumerate(top_pairs, start=1):
        left = _required_text(row.get("leftFactor"))
        right = _required_text(row.get("rightFactor"))
        pair = (left, right)
        if (
            row.get("rank") != position
            or left not in independent
            or right not in independent
            or left >= right
            or pair in observed_pairs
            or not _finite_number(row.get("signedCorr"))
            or not _finite_number(row.get("absCorr"))
            or not -1.0 <= float(row["signedCorr"]) <= 1.0
            or not _close(float(row["absCorr"]), abs(float(row["signedCorr"])))
            or not _nonnegative_integer(row.get("commonSecurityCount"))
            or not 3
            <= int(row["commonSecurityCount"])
            <= min(latest_counts[left], latest_counts[right])
        ):
            raise ValueError("dashboard factorDiagnostics top redundancy pair is invalid")
        observed_pairs.add(pair)
    expected_pair_order = sorted(
        top_pairs,
        key=lambda row: (
            -float(row["absCorr"]),
            str(row["leftFactor"]),
            str(row["rightFactor"]),
        ),
    )
    high_pairs_in_top = sum(
        float(row["absCorr"]) >= FACTOR_DIAGNOSTICS_REDUNDANCY_THRESHOLD for row in top_pairs
    )
    if (
        top_pairs != expected_pair_order
        or int(high_pair_count) < high_pairs_in_top
        or (
            int(eligible_pair_count) <= FACTOR_DIAGNOSTICS_TOP_PAIR_COUNT
            and int(high_pair_count) != high_pairs_in_top
        )
    ):
        raise ValueError("dashboard factorDiagnostics top redundancy pair order/count is invalid")

    category_summary = diagnostics.get("categorySummary")
    expected_categories = set(category_by_factor.values())
    if (
        not isinstance(category_summary, list)
        or len(category_summary) != len(expected_categories)
        or any(not isinstance(row, dict) for row in category_summary)
        or {str(row.get("category")) for row in category_summary} != expected_categories
    ):
        raise ValueError("dashboard factorDiagnostics category summary is incomplete")
    rank_by_factor = {str(row["factor"]): row for row in rank_rows}
    redundancy_by_factor = {str(row["factor"]): row for row in redundancy_rows}
    for row in category_summary:
        category = str(row["category"])
        factors = sorted(
            factor
            for factor, observed_category in category_by_factor.items()
            if observed_category == category
        )
        ic_available = [
            rank_by_factor[factor] for factor in factors if rank_by_factor[factor]["available"]
        ]
        redundancy_available = [
            redundancy_by_factor[factor]
            for factor in factors
            if redundancy_by_factor[factor]["available"]
        ]
        if (
            row.get("factorCount") != len(factors)
            or row.get("availableRankIcFactorCount") != len(ic_available)
            or row.get("highCorrFactorCount")
            != sum(int(item["highCorrPeerCount"]) > 0 for item in redundancy_available)
            or row.get("exampleFactors") != factors[:4]
        ):
            raise ValueError("dashboard factorDiagnostics category counts are inconsistent")
        expected_mean_ic = (
            sum(float(item["mean"]) for item in ic_available) / len(ic_available)
            if ic_available
            else None
        )
        expected_positive_rate = (
            sum(float(item["positiveRate"]) for item in ic_available) / len(ic_available)
            if ic_available
            else None
        )
        expected_mean_redundancy = (
            sum(float(item["absCorr"]) for item in redundancy_available) / len(redundancy_available)
            if redundancy_available
            else None
        )
        _require_optional_close(
            row.get("averageMeanRankIc"), expected_mean_ic, "category average Rank-IC"
        )
        _require_optional_close(
            row.get("averagePositiveRate"),
            expected_positive_rate,
            "category average positive Rank-IC rate",
        )
        _require_optional_close(
            row.get("averageMaxAbsCorr"),
            expected_mean_redundancy,
            "category average maximum absolute rank correlation",
        )
    if [(-int(row["factorCount"]), str(row["category"])) for row in category_summary] != sorted(
        (-int(row["factorCount"]), str(row["category"])) for row in category_summary
    ):
        raise ValueError("dashboard factorDiagnostics category order is inconsistent")


def _guardrail_expectations(row: dict[str, Any], config: dict[str, Any]) -> dict[str, bool]:
    def at_least(field: str, threshold: float) -> bool:
        value = row.get(field)
        return _finite_number(value) and float(value) >= threshold

    def at_most(field: str, threshold: float) -> bool:
        value = row.get(field)
        return _finite_number(value) and float(value) <= threshold

    return {
        "guardrail_sharpe": at_least("sharpe", float(config["selection_min_sharpe"])),
        "guardrail_drawdown": at_least("max_drawdown", -float(config["selection_max_drawdown"])),
        "guardrail_cost": at_most(
            "annualized_cost_drag",
            float(config["selection_max_annualized_cost_drag"]),
        ),
        "guardrail_historical_effective_names": at_least(
            "min_target_effective_names",
            float(config["selection_min_effective_names"]),
        ),
        "guardrail_current_effective_names": at_least(
            "current_target_effective_names",
            float(config["selection_min_effective_names"]),
        ),
        "guardrail_historical_target_hhi": at_most(
            "max_target_hhi", float(config["selection_max_target_hhi"])
        ),
        "guardrail_current_target_hhi": at_most(
            "current_target_hhi", float(config["selection_max_target_hhi"])
        ),
        "guardrail_historical_target_weight": at_most(
            "max_target_weight", float(config["selection_max_target_weight"])
        ),
        "guardrail_current_target_weight": at_most(
            "current_target_max_weight", float(config["selection_max_target_weight"])
        ),
        "guardrail_policy_input": at_least("policy_input_coverage_ratio", 1.0 - 1e-12),
        "guardrail_execution": (
            at_least("execution_coverage_ratio", 1.0 - 1e-12)
            and at_most("blocked_execution_count", 0.0)
            and at_most("total_unpriceable_target_count", 0.0)
        ),
        "guardrail_current_target": row.get("current_portfolio_available") is True,
        "guardrail_contribution_complete": (row.get("contribution_diagnostics_complete") is True),
        "guardrail_security_day_contribution": at_most(
            "max_abs_security_day_contribution",
            float(config["selection_max_abs_security_day_contribution"]),
        ),
        "guardrail_security_absolute_contribution_share": at_most(
            "max_security_absolute_contribution_share",
            float(config["selection_max_security_absolute_contribution_share"]),
        ),
        "guardrail_leave_one_security": at_most(
            "max_abs_leave_one_security_cagr_delta",
            float(config["selection_max_leave_one_security_cagr_delta"]),
        ),
    }


def _selection_sort_key(row: dict[str, Any]) -> tuple[object, ...]:
    descending = (
        "selection_score",
        "base_composite_score",
    )
    later_descending = (
        "sortino",
        "calmar",
        "max_drawdown",
        "cagr",
        "sharpe",
        "stability",
    )
    for field in (
        *descending,
        "max_abs_leave_one_security_cagr_delta",
        "max_abs_security_day_contribution",
        *later_descending,
        "annualized_cost_drag",
        "annualized_turnover",
    ):
        if not _finite_number(row.get(field)):
            raise ValueError(f"eligible factor-policy row has invalid {field}")
    return (
        -float(row["selection_score"]),
        -float(row["base_composite_score"]),
        float(row["max_abs_leave_one_security_cagr_delta"]),
        float(row["max_abs_security_day_contribution"]),
        *(-float(row[field]) for field in later_descending),
        float(row["annualized_cost_drag"]),
        float(row["annualized_turnover"]),
        str(row["factor"]),
        str(row["policy_id"]),
    )


def _validate_ranking_guardrails(
    rows: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Recompute every result-affecting guardrail, score, and rank from payload evidence."""

    action = config.get("selection_extreme_event_action")
    if action not in {"warn", "penalize", "exclude"}:
        raise ValueError("dashboard extreme-event action is invalid")
    for row in rows:
        expected_guards = _guardrail_expectations(row, config)
        for field, expected in expected_guards.items():
            if row.get(field) is not expected:
                raise ValueError(f"factor-policy {field} is inconsistent")
        standard_pass = all(expected_guards[field] for field in _STANDARD_GUARDRAILS)
        contribution_pass = all(expected_guards[field] for field in _CONTRIBUTION_GUARDRAILS)
        absolute_pass = standard_pass and contribution_pass
        if (
            row.get("standard_guardrail_pass") is not standard_pass
            or row.get("contribution_guardrail_pass") is not contribution_pass
            or row.get("absolute_guardrail_pass") is not absolute_pass
        ):
            raise ValueError("factor-policy aggregate guardrail flags are inconsistent")
        standard_breaches = [
            field.removeprefix("guardrail_")
            for field in _STANDARD_GUARDRAILS
            if not expected_guards[field]
        ]
        contribution_breaches = [
            field.removeprefix("guardrail_")
            for field in _CONTRIBUTION_GUARDRAILS
            if not expected_guards[field]
        ]
        if row.get("guardrail_breaches") != [*standard_breaches, *contribution_breaches]:
            raise ValueError("factor-policy guardrail breach list is inconsistent")
        if row.get("contribution_guardrail_breaches") != contribution_breaches:
            raise ValueError("factor-policy contribution breach list is inconsistent")

        contribution_values = (
            ("max_abs_security_day_contribution", "selection_max_abs_security_day_contribution"),
            (
                "max_security_absolute_contribution_share",
                "selection_max_security_absolute_contribution_share",
            ),
            (
                "max_abs_leave_one_security_cagr_delta",
                "selection_max_leave_one_security_cagr_delta",
            ),
        )
        if any(not _finite_number(row.get(field)) for field, _ in contribution_values):
            raise ValueError("factor-policy contribution diagnostics are not finite")
        expected_penalty = 0.0
        if action == "penalize" and contribution_breaches:
            severity = max(
                _ratio_severity(float(row[field]), float(config[threshold_field]))
                for field, threshold_field in contribution_values
            )
            expected_penalty = float(config["selection_extreme_event_penalty_points"]) * severity
        _require_close(
            row.get("extreme_event_penalty_points"),
            expected_penalty,
            "factor-policy extreme-event penalty",
        )
        _require_optional_close(
            row.get("base_composite_score"),
            row.get("composite_score"),
            "factor-policy base composite score",
        )
        metric_available = row.get("comparison_status") == "available"
        expected_eligible = metric_available and standard_pass
        if action == "exclude":
            expected_eligible = expected_eligible and contribution_pass
        if row.get("selection_eligible") is not expected_eligible:
            raise ValueError("factor-policy selection eligibility is inconsistent")
        if expected_eligible:
            if not _finite_number(row.get("base_composite_score")):
                raise ValueError("eligible factor-policy pair has no base score")
            expected_score = max(0.0, float(row["base_composite_score"]) - expected_penalty)
            _require_close(
                row.get("selection_score"), expected_score, "factor-policy selection score"
            )
        elif row.get("selection_score") is not None:
            raise ValueError("ineligible factor-policy selection score must be null")

        if not metric_available:
            expected_status = "data_excluded"
        elif not standard_pass:
            expected_status = "absolute_guardrail_excluded"
        elif not contribution_pass:
            expected_status = {
                "warn": "extreme_event_warning",
                "penalize": "extreme_event_penalized",
                "exclude": "extreme_event_excluded",
            }[str(action)]
        else:
            expected_status = "eligible"
        if row.get("selection_status") != expected_status:
            raise ValueError("factor-policy selection status is inconsistent")

    ordered = sorted(
        (row for row in rows if row.get("selection_eligible") is True),
        key=_selection_sort_key,
    )
    if not ordered:
        raise ValueError("dashboard has no selection-eligible factor-policy pair")
    for expected_rank, row in enumerate(ordered, start=1):
        if not _finite_number(row.get("rank")) or int(float(row["rank"])) != expected_rank:
            raise ValueError("factor-policy selection rank is inconsistent")
        if row.get("selected") is not (expected_rank == 1):
            raise ValueError("factor-policy selected flag is inconsistent")
    for row in rows:
        if row.get("selection_eligible") is not True and (
            row.get("rank") is not None or row.get("selected") is not False
        ):
            raise ValueError("ineligible factor-policy rank/selected contract is inconsistent")
    selected = ordered[0]
    if rows[0] is not selected:
        raise ValueError("selected factor-policy row must be first in the canonical ranking")
    return selected


def _validate_grid_and_selection(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], set[str]]:
    ranking = payload.get("factorPolicyRanking")
    config = payload["config"]
    if (
        not isinstance(ranking, list)
        or not ranking
        or any(not isinstance(row, dict) for row in ranking)
    ):
        raise ValueError("dashboard factorPolicyRanking must be a populated row list")
    rows = [row for row in ranking if isinstance(row, dict)]
    independent, aliases = _factor_sets(payload)
    all_factors = independent.union(aliases)
    pairs: list[tuple[str, str]] = []
    for row in rows:
        factor = _required_text(row.get("factor"))
        policy = _required_text(row.get("policy_id"))
        if factor not in all_factors or policy not in WEIGHTING_POLICIES:
            raise ValueError("dashboard factor-policy grid contains an unexpected pair")
        pairs.append((factor, policy))
    if len(pairs) != len(set(pairs)):
        raise ValueError("dashboard factor-policy grid contains duplicate pairs")
    expected_pairs = {(factor, policy) for factor in all_factors for policy in WEIGHTING_POLICIES}
    if set(pairs) != expected_pairs:
        raise ValueError("dashboard factor-policy grid is incomplete")

    reason_counts: dict[str, int] = {}
    independent_rows = [row for row in rows if str(row["factor"]) in independent]
    for row in independent_rows:
        status = row.get("comparison_status")
        codes = row.get("exclusion_reason_codes")
        if status == "available":
            if codes != []:
                raise ValueError("available independent pair has exclusion reason codes")
        else:
            if (
                not isinstance(codes, list)
                or not codes
                or not all(_required_text(code) for code in codes)
            ):
                raise ValueError("excluded independent pair has no exact reason code")
            for code in codes:
                reason_counts[str(code)] = reason_counts.get(str(code), 0) + 1
    for row in rows:
        if str(row["factor"]) in aliases and row.get("comparison_status") != "duplicate_alias":
            raise ValueError("diagnostic alias pair is not marked duplicate_alias")

    available_count = sum(row.get("comparison_status") == "available" for row in independent_rows)
    common_count = sum(
        all(
            next(
                row
                for row in independent_rows
                if row["factor"] == factor and row["policy_id"] == policy
            ).get("comparison_status")
            == "available"
            for policy in WEIGHTING_POLICIES
        )
        for factor in independent
    )
    expected_grid = {
        "version": 1,
        "independentFactorCount": len(independent),
        "policyCount": len(WEIGHTING_POLICIES),
        "expectedIndependentPairCount": len(independent) * len(WEIGHTING_POLICIES),
        "evaluatedIndependentPairCount": len(independent_rows),
        "availableIndependentPairCount": available_count,
        "excludedIndependentPairCount": len(independent_rows) - available_count,
        "missingIndependentPairCount": 0,
        "diagnosticAliasFactorCount": len(aliases),
        "diagnosticAliasPairCount": len(aliases) * len(WEIGHTING_POLICIES),
        "commonComparableFactorCount": common_count,
        "exclusionReasonCounts": dict(sorted(reason_counts.items())),
        "invariant": (
            "availableIndependentPairCount + excludedIndependentPairCount = "
            "expectedIndependentPairCount"
        ),
    }
    if payload.get("gridAccounting") != expected_grid:
        raise ValueError("dashboard gridAccounting is inconsistent with the unique grid")

    action = config.get("selection_extreme_event_action")
    if action not in {"warn", "penalize", "exclude"}:
        raise ValueError("dashboard extreme-event action is invalid")
    for row in rows:
        expected_guards = _guardrail_expectations(row, config)
        for field, expected in expected_guards.items():
            if row.get(field) is not expected:
                raise ValueError(f"factor-policy {field} is inconsistent")
        standard_pass = all(expected_guards[field] for field in _STANDARD_GUARDRAILS)
        contribution_pass = all(expected_guards[field] for field in _CONTRIBUTION_GUARDRAILS)
        absolute_pass = standard_pass and contribution_pass
        if (
            row.get("standard_guardrail_pass") is not standard_pass
            or row.get("contribution_guardrail_pass") is not contribution_pass
            or row.get("absolute_guardrail_pass") is not absolute_pass
        ):
            raise ValueError("factor-policy aggregate guardrail flags are inconsistent")
        standard_breaches = [
            field.removeprefix("guardrail_")
            for field in _STANDARD_GUARDRAILS
            if not expected_guards[field]
        ]
        contribution_breaches = [
            field.removeprefix("guardrail_")
            for field in _CONTRIBUTION_GUARDRAILS
            if not expected_guards[field]
        ]
        if row.get("guardrail_breaches") != [*standard_breaches, *contribution_breaches]:
            raise ValueError("factor-policy guardrail breach list is inconsistent")
        if row.get("contribution_guardrail_breaches") != contribution_breaches:
            raise ValueError("factor-policy contribution breach list is inconsistent")

        contribution_values = (
            ("max_abs_security_day_contribution", "selection_max_abs_security_day_contribution"),
            (
                "max_security_absolute_contribution_share",
                "selection_max_security_absolute_contribution_share",
            ),
            (
                "max_abs_leave_one_security_cagr_delta",
                "selection_max_leave_one_security_cagr_delta",
            ),
        )
        if any(not _finite_number(row.get(field)) for field, _ in contribution_values):
            raise ValueError("factor-policy contribution diagnostics are not finite")
        expected_penalty = 0.0
        if action == "penalize" and contribution_breaches:
            severity = max(
                _ratio_severity(float(row[field]), float(config[threshold_field]))
                for field, threshold_field in contribution_values
            )
            expected_penalty = float(config["selection_extreme_event_penalty_points"]) * severity
        _require_close(
            row.get("extreme_event_penalty_points"),
            expected_penalty,
            "factor-policy extreme-event penalty",
        )
        _require_optional_close(
            row.get("base_composite_score"),
            row.get("composite_score"),
            "factor-policy base composite score",
        )
        metric_available = row.get("comparison_status") == "available"
        expected_eligible = metric_available and standard_pass
        if action == "exclude":
            expected_eligible = expected_eligible and contribution_pass
        if row.get("selection_eligible") is not expected_eligible:
            raise ValueError("factor-policy selection eligibility is inconsistent")
        if expected_eligible:
            if not _finite_number(row.get("base_composite_score")):
                raise ValueError("eligible factor-policy pair has no base score")
            expected_score = max(0.0, float(row["base_composite_score"]) - expected_penalty)
            _require_close(
                row.get("selection_score"), expected_score, "factor-policy selection score"
            )
        elif row.get("selection_score") is not None:
            raise ValueError("ineligible factor-policy selection score must be null")

        if not metric_available:
            expected_status = "data_excluded"
        elif not standard_pass:
            expected_status = "absolute_guardrail_excluded"
        elif not contribution_pass:
            expected_status = {
                "warn": "extreme_event_warning",
                "penalize": "extreme_event_penalized",
                "exclude": "extreme_event_excluded",
            }[str(action)]
        else:
            expected_status = "eligible"
        if row.get("selection_status") != expected_status:
            raise ValueError("factor-policy selection status is inconsistent")

    ordered = sorted(
        (row for row in rows if row.get("selection_eligible") is True),
        key=_selection_sort_key,
    )
    if not ordered:
        raise ValueError("dashboard has no selection-eligible factor-policy pair")
    for expected_rank, row in enumerate(ordered, start=1):
        if not _finite_number(row.get("rank")) or int(float(row["rank"])) != expected_rank:
            raise ValueError("factor-policy selection rank is inconsistent")
        if row.get("selected") is not (expected_rank == 1):
            raise ValueError("factor-policy selected flag is inconsistent")
    for row in rows:
        if row.get("selection_eligible") is not True and (
            row.get("rank") is not None or row.get("selected") is not False
        ):
            raise ValueError("ineligible factor-policy rank/selected contract is inconsistent")
    selected = ordered[0]
    if rows[0] is not selected:
        raise ValueError("selected factor-policy row must be first in the canonical ranking")
    if (
        payload.get("selectedFactor") != selected.get("factor")
        or payload.get("selectedWeightingPolicy") != selected.get("policy_id")
        or not _required_text(payload.get("selectedReason"))
    ):
        raise ValueError("dashboard selected factor-policy identity is inconsistent")

    meta = payload.get("meta")
    if not isinstance(meta, dict) or any(
        meta.get(field) != expected
        for field, expected in {
            "factorCount": len(all_factors),
            "independentFactorCount": len(independent),
            "availableIndependentPairCount": expected_grid["availableIndependentPairCount"],
            "excludedIndependentPairCount": expected_grid["excludedIndependentPairCount"],
            "aliasFactorCount": len(aliases),
            "policyCount": len(WEIGHTING_POLICIES),
            "policyFactorRunCount": len(rows),
        }.items()
    ):
        raise ValueError("dashboard grid metadata is inconsistent")
    return selected, independent_rows, independent


def _configured_comparison_benchmarks(config: dict[str, Any]) -> list[str]:
    raw = [
        config.get("benchmark"),
        config.get("chart_benchmark"),
        *(
            config.get("additional_comparison_benchmarks", [])
            if isinstance(config.get("additional_comparison_benchmarks"), list)
            else []
        ),
    ]
    ordered: list[str] = []
    for value in raw:
        symbol = str(value or "").strip().upper()
        if symbol and symbol not in ordered:
            ordered.append(symbol)
    return ordered


def _validate_period_metric(
    value: object,
    *,
    expected_basis: str,
    expected_return_count: int,
) -> None:
    if not isinstance(value, dict):
        raise ValueError("dashboard period metric must be an object")
    required = {
        "available",
        "unavailableReason",
        "basis",
        "returnObservationCount",
        "requiredReturnCount",
        "riskObservationCount",
        "riskMetricsExact",
        *PERFORMANCE_METRIC_KEYS,
    }
    if not required.issubset(value) or value.get("basis") != expected_basis:
        raise ValueError("dashboard period metric contract is incomplete")
    if (
        not isinstance(value.get("available"), bool)
        or not isinstance(value.get("riskMetricsExact"), bool)
        or not _nonnegative_integer(value.get("returnObservationCount"))
        or not _nonnegative_integer(value.get("requiredReturnCount"))
        or not _nonnegative_integer(value.get("riskObservationCount"))
    ):
        raise ValueError("dashboard period metric availability/counts are invalid")
    observed = int(value["returnObservationCount"])
    required_count = int(value["requiredReturnCount"])
    risk = int(value["riskObservationCount"])
    if observed > required_count or risk > observed:
        raise ValueError("dashboard period metric observation counts are inconsistent")
    if value["available"] is True:
        if value.get("unavailableReason") is not None or required_count != expected_return_count:
            raise ValueError("dashboard available period metric boundary is inconsistent")
        if not _finite_number(value.get("cumulativeReturn")):
            raise ValueError("dashboard available period cumulative return is invalid")
        if any(
            metric_value is not None and not _finite_number(metric_value)
            for metric_value in (value.get(metric) for metric in PERFORMANCE_METRIC_KEYS)
        ):
            raise ValueError("dashboard available period metric contains a non-finite value")
    else:
        if not _required_text(value.get("unavailableReason")) or any(
            value.get(metric) is not None for metric in PERFORMANCE_METRIC_KEYS
        ):
            raise ValueError("dashboard unavailable period metric is inconsistent")


def _validate_full_period_curve_parity(
    metrics: dict[str, Any],
    curve: object,
    *,
    label: str,
    require_common_series: bool,
) -> None:
    """Tie an available FULL cumulative return to its exact plotted NAV endpoints."""

    if metrics.get("available") is not True:
        return
    common_series_available = not (
        not isinstance(curve, list)
        or len(curve) < 2
        or any(not _finite_number(value) or float(value) <= 0.0 for value in curve)
    )
    if not common_series_available and require_common_series:
        raise ValueError(f"dashboard {label} FULL common evaluation curve is invalid")
    if not common_series_available:
        return
    assert isinstance(curve, list)
    expected_return = float(curve[-1]) / float(curve[0]) - 1.0
    _require_close(
        metrics.get("cumulativeReturn"),
        expected_return,
        f"dashboard {label} FULL cumulative return and common evaluation curve",
    )


def _validate_performance(payload: dict[str, Any]) -> None:
    performance = payload.get("performance")
    config = payload["config"]
    data = payload["data"]
    if not isinstance(performance, dict):
        raise ValueError("dashboard performance contract is missing")
    dates = performance.get("dates")
    factor_curves = performance.get("factorCurves")
    if (
        performance.get("contractVersion") != PERFORMANCE_CONTRACT_VERSION
        or not isinstance(dates, list)
        or len(dates) != int(config["evaluation_window_days"]) + 1
        or not all(_required_text(date) for date in dates)
        or dates != sorted(dates)
        or dates[-1] != data.get("asOf")
        or not isinstance(factor_curves, dict)
    ):
        raise ValueError("dashboard Python performance contract is invalid")
    factor_definitions = payload.get("factorDefinitions")
    expected_factors = {
        str(row["factor"])
        for row in factor_definitions
        if isinstance(row, dict) and _required_text(row.get("factor"))
    }
    if set(factor_curves) != expected_factors:
        raise ValueError("dashboard performance factor curve set is inconsistent")
    for curve in factor_curves.values():
        if (
            not isinstance(curve, list)
            or len(curve) != len(dates)
            or any(value is not None and not _finite_number(value) for value in curve)
        ):
            raise ValueError("dashboard performance factor curve is invalid")

    comparison_order = _configured_comparison_benchmarks(config)
    if config.get("comparison_benchmarks") != comparison_order:
        raise ValueError("dashboard configured comparison benchmark order is inconsistent")
    if data.get("chartBenchmark") != config.get("chart_benchmark") or data.get(
        "additionalComparisonBenchmarks"
    ) != config.get("additional_comparison_benchmarks"):
        raise ValueError("dashboard comparison benchmark metadata is inconsistent")
    availability = data.get("comparisonBenchmarkAvailability")
    curves = performance.get("benchmarkCurves")
    if (
        performance.get("benchmarkOrder") != comparison_order
        or not isinstance(availability, dict)
        or set(availability) != set(comparison_order)
        or any(not isinstance(value, bool) for value in availability.values())
        or not isinstance(curves, dict)
        or set(curves) != set(comparison_order)
    ):
        raise ValueError("dashboard comparison benchmark order or curve keys are inconsistent")
    for symbol in comparison_order:
        curve = curves[symbol]
        if availability[symbol]:
            if (
                not isinstance(curve, list)
                or len(curve) != len(dates)
                or any(value is not None and not _finite_number(value) for value in curve)
                or curve[-1] is None
            ):
                raise ValueError("dashboard available comparison benchmark curve is invalid")
        elif curve is not None:
            raise ValueError("dashboard unavailable comparison benchmark curve must be null")
    primary = str(config.get("benchmark") or "").strip().upper()
    if performance.get("benchmarkCurve") != curves.get(primary):
        raise ValueError("dashboard legacy benchmarkCurve differs from benchmarkCurves")
    if data.get("benchmarkAvailable") is not availability.get(primary, False):
        raise ValueError("dashboard primary benchmark availability is inconsistent")

    periods = performance.get("periods")
    expected_periods = list(PERFORMANCE_PERIODS)
    if not isinstance(periods, list) or [
        period.get("key") if isinstance(period, dict) else None for period in periods
    ] != [key for key, _, _ in expected_periods]:
        raise ValueError("dashboard performance periods are incomplete or out of order")
    for period, (key, label, fixed_count) in zip(periods, expected_periods, strict=True):
        assert isinstance(period, dict)
        return_count = period.get("returnObservationCount")
        if (
            period.get("label") != label
            or not _nonnegative_integer(return_count)
            or not isinstance(period.get("factors"), dict)
            or set(period["factors"]) != expected_factors
            or not isinstance(period.get("benchmarks"), dict)
            or set(period["benchmarks"]) != set(comparison_order)
        ):
            raise ValueError("dashboard performance period contract is inconsistent")
        count = int(return_count)
        if fixed_count is not None and count != fixed_count:
            raise ValueError("dashboard fixed performance period length is inconsistent")
        if key == "FULL" and (
            count != len(dates) - 1
            or period.get("startDate") != dates[0]
            or period.get("endDate") != dates[-1]
        ):
            raise ValueError("dashboard FULL performance period is inconsistent")
        if period.get("unavailableReason") is None:
            if not _required_text(period.get("startDate")) or period.get("endDate") != dates[-1]:
                raise ValueError("dashboard performance period date boundary is invalid")
        elif not _required_text(period.get("unavailableReason")):
            raise ValueError("dashboard performance period unavailable reason is invalid")
        for factor, metrics in period["factors"].items():
            _validate_period_metric(
                metrics,
                expected_basis="net_of_costs_strategy",
                expected_return_count=count,
            )
            if key == "FULL":
                _validate_full_period_curve_parity(
                    metrics,
                    factor_curves[factor],
                    label=f"factor {factor}",
                    require_common_series=False,
                )
        for symbol, metrics in period["benchmarks"].items():
            _validate_period_metric(
                metrics,
                expected_basis="adjusted_close_buy_and_hold",
                expected_return_count=count,
            )
            if key == "FULL":
                _validate_full_period_curve_parity(
                    metrics,
                    curves[symbol],
                    label=f"benchmark {symbol}",
                    require_common_series=True,
                )


def _validate_selection_decision(payload: dict[str, Any], selected: dict[str, Any]) -> None:
    config = payload["config"]
    decision = payload.get("selectionDecision")
    performance = payload.get("performance")
    selection_method = payload.get("selectionMethod")
    dates = performance.get("dates") if isinstance(performance, dict) else None
    if not isinstance(decision, dict) or not isinstance(selection_method, dict):
        raise ValueError("dashboard selection decision objects are missing")
    if not isinstance(dates, list) or not dates or not all(_required_text(date) for date in dates):
        raise ValueError("dashboard performance date window is invalid")
    profile = {
        "id": ABSOLUTE_GUARDRAIL_VERSION,
        "version": 1,
        "policyNeutral": True,
        "rules": [
            {
                "id": "minimum_sharpe",
                "metric": "sharpe",
                "operator": ">=",
                "threshold": config["selection_min_sharpe"],
                "unit": "ratio",
            },
            {
                "id": "maximum_drawdown_magnitude",
                "metric": "max_drawdown",
                "operator": ">=",
                "threshold": -float(config["selection_max_drawdown"]),
                "unit": "fraction",
            },
            {
                "id": "maximum_annualized_cost_drag",
                "metric": "annualized_cost_drag",
                "operator": "<=",
                "threshold": config["selection_max_annualized_cost_drag"],
                "unit": "fraction_per_year",
            },
            {
                "id": "minimum_historical_target_effective_names",
                "metric": "min_target_effective_names",
                "operator": ">=",
                "threshold": config["selection_min_effective_names"],
                "unit": "names",
            },
            {
                "id": "minimum_current_target_effective_names",
                "metric": "current_target_effective_names",
                "operator": ">=",
                "threshold": config["selection_min_effective_names"],
                "unit": "names",
            },
            {
                "id": "maximum_historical_target_hhi",
                "metric": "max_target_hhi",
                "operator": "<=",
                "threshold": config["selection_max_target_hhi"],
                "unit": "fraction",
            },
            {
                "id": "maximum_current_target_hhi",
                "metric": "current_target_hhi",
                "operator": "<=",
                "threshold": config["selection_max_target_hhi"],
                "unit": "fraction",
            },
            {
                "id": "maximum_historical_target_weight",
                "metric": "max_target_weight",
                "operator": "<=",
                "threshold": config["selection_max_target_weight"],
                "unit": "fraction",
            },
            {
                "id": "maximum_current_target_weight",
                "metric": "current_target_max_weight",
                "operator": "<=",
                "threshold": config["selection_max_target_weight"],
                "unit": "fraction",
            },
            {
                "id": "maximum_security_day_contribution",
                "metric": "max_abs_security_day_contribution",
                "operator": "<=",
                "threshold": config["selection_max_abs_security_day_contribution"],
                "unit": "portfolio_return_fraction",
            },
            {
                "id": "maximum_security_absolute_contribution_share",
                "metric": "max_security_absolute_contribution_share",
                "operator": "<=",
                "threshold": config["selection_max_security_absolute_contribution_share"],
                "unit": "fraction",
            },
            {
                "id": "maximum_leave_one_security_cagr_delta",
                "metric": "max_abs_leave_one_security_cagr_delta",
                "operator": "<=",
                "threshold": config["selection_max_leave_one_security_cagr_delta"],
                "unit": "cagr_fraction",
            },
        ],
        "requiredContracts": {
            "completePolicyInputs": True,
            "completeExecutionCoverage": True,
            "currentTargetAvailable": True,
            "contributionDiagnosticsComplete": True,
        },
        "extremeEventAction": config["selection_extreme_event_action"],
        "extremeEventPenaltyPoints": config["selection_extreme_event_penalty_points"],
    }
    eligible_count = sum(
        row.get("selection_eligible") is True for row in payload["factorPolicyRanking"]
    )
    exact_fields = {
        "method": "fixed_policy_factor_selection",
        "version": FACTOR_SELECTION_VERSION,
        "dynamicSelection": True,
        "weightingPolicyOptimized": False,
        "selectedFactor": selected["factor"],
        "selectedPolicyId": selected["policy_id"],
        "selectedPolicyVersion": POLICY_REGISTRY[str(selected["policy_id"])]["version"],
        "guardrailProfile": profile,
        "tieBreakPolicy": list(FACTOR_SELECTION_TIE_BREAK_POLICY),
        "reason": payload["selectedReason"],
        "evaluationStart": dates[0],
        "evaluationEnd": dates[-1],
        "evaluationWindowDays": len(dates),
        "minimumObservations": config["min_evaluation_observations"],
        "minimumValuationCoverage": config["min_valuation_coverage"],
        "minimumDailyRiskObservations": config["min_daily_risk_observations"],
        "selectionEligibleFactorCount": eligible_count,
        "gridAccounting": payload["gridAccounting"],
    }
    if any(decision.get(field) != value for field, value in exact_fields.items()):
        raise ValueError("dashboard joint selection decision is inconsistent")
    score_fields = {
        "selectedBaseCompositeScore": "base_composite_score",
        "selectedExtremeEventPenaltyPoints": "extreme_event_penalty_points",
        "selectedSelectionScore": "selection_score",
    }
    for decision_field, row_field in score_fields.items():
        _require_close(
            decision.get(decision_field),
            float(selected[row_field]),
            f"selectionDecision.{decision_field}",
        )
    expected_method = {
        "name": "fixed_policy_factor_selection_absolute_guardrails",
        "version": FACTOR_SELECTION_VERSION,
        "guardrailVersion": ABSOLUTE_GUARDRAIL_VERSION,
        "evaluationWindowDays": len(dates),
        "minimumObservations": config["min_evaluation_observations"],
        "minimumValuationCoverage": config["min_valuation_coverage"],
        "minimumDailyRiskObservations": config["min_daily_risk_observations"],
        "weights": config["score_weights"],
        "netOfCosts": True,
        "signalTiming": "close_t",
        "executionTiming": "next_session_close",
        "returnExposureStarts": "following_close_to_close_session",
        "tieBreakPolicy": list(FACTOR_SELECTION_TIE_BREAK_POLICY),
        "weightingPolicyOptimized": False,
        "fixedWeightingPolicy": FIXED_WEIGHTING_POLICY,
    }
    if selection_method != expected_method:
        raise ValueError("dashboard selectionMethod is inconsistent")
    if (
        not isinstance(performance, dict)
        or performance.get("weightingPolicyId") != selected["policy_id"]
        or not isinstance(performance.get("factorCurves"), dict)
        or selected["factor"] not in performance["factorCurves"]
        or len(performance["factorCurves"][selected["factor"]]) != len(dates)
    ):
        raise ValueError("dashboard selected performance curve is inconsistent")


def _validate_policy_diagnostics(
    payload: dict[str, Any],
    independent_rows: list[dict[str, Any]],
    independent: set[str],
) -> None:
    diagnostics = payload.get("policyDiagnostics")
    selected_factor = str(payload["selectedFactor"])
    selected_policy = str(payload["selectedWeightingPolicy"])
    if not isinstance(diagnostics, list) or len(diagnostics) != len(WEIGHTING_POLICIES):
        raise ValueError("dashboard policyDiagnostics has an invalid policy count")
    available_sets = {
        policy: {
            str(row["factor"])
            for row in independent_rows
            if row["policy_id"] == policy and row.get("comparison_status") == "available"
        }
        for policy in WEIGHTING_POLICIES
    }
    common = set.intersection(*(available_sets[policy] for policy in WEIGHTING_POLICIES))
    expected_diagnostic_fields = {
        "policy_id",
        "policy_version",
        "diagnostic_only",
        "paired_factor_count",
        "available_factor_count",
        "excluded_factor_count",
        "data_status",
        "contains_selected_pair",
        "selected_factor_if_policy",
        "current_available_independent_factor_count",
        "current_median_holding_count",
        "current_median_cash_weight",
        *_POLICY_DIAGNOSTIC_METRICS,
    }
    for position, policy in enumerate(WEIGHTING_POLICIES):
        row = diagnostics[position]
        if not isinstance(row, dict) or row.get("policy_id") != policy:
            raise ValueError("dashboard policyDiagnostics order/identity is inconsistent")
        if set(row) != expected_diagnostic_fields:
            raise ValueError("dashboard policyDiagnostics contains non-canonical fields")
        frame = [item for item in independent_rows if item["policy_id"] == policy]
        paired = [item for item in frame if str(item["factor"]) in common]
        expected = {
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
            "current_available_independent_factor_count": sum(
                item.get("current_portfolio_available") is True for item in frame
            ),
        }
        if any(row.get(field) != value for field, value in expected.items()):
            raise ValueError("dashboard policy diagnostic counts/identity are inconsistent")
        if not paired:
            raise ValueError("dashboard policy diagnostics have no common comparable factors")
        for field in (
            "current_holding_count",
            "current_cash_weight",
            *_POLICY_DIAGNOSTIC_METRICS,
        ):
            values = [item.get(field) for item in paired]
            if any(not _finite_number(value) for value in values):
                raise ValueError(f"dashboard common policy metric {field} is not finite")
            output_field = {
                "current_holding_count": "current_median_holding_count",
                "current_cash_weight": "current_median_cash_weight",
            }.get(field, field)
            _require_close(
                row.get(output_field),
                float(median(float(value) for value in values)),
                f"policyDiagnostics[{policy}].{output_field}",
            )
    aggregate = payload.get("portfolioPolicy", {}).get("policyAggregateDiagnostics")
    expected_aggregate = {
        "fixed": True,
        "optimized": False,
        "policyId": FIXED_WEIGHTING_POLICY,
        "policyCount": len(WEIGHTING_POLICIES),
        "commonComparableFactorCount": len(common),
    }
    if (
        not isinstance(aggregate, dict)
        or set(aggregate) != {*expected_aggregate, "note"}
        or any(aggregate.get(field) != value for field, value in expected_aggregate.items())
        or not _required_text(aggregate.get("note"))
    ):
        raise ValueError("dashboard policy aggregate diagnostics are inconsistent")


def _validate_concentration(portfolio: dict[str, Any], label: str) -> None:
    concentration = portfolio.get("concentration")
    if not isinstance(concentration, dict) or set(concentration) != _CONCENTRATION_FIELDS:
        raise ValueError(f"{label} is missing concentration diagnostics")
    weights = [float(row["weight"]) for row in portfolio["weights"]]
    cash = float(portfolio["cashWeight"])
    invested = sum(weights)
    normalized = [weight / invested for weight in weights] if invested > 0.0 else []
    hhi = sum(weight * weight for weight in normalized)
    ordered = sorted(weights, reverse=True)
    expected = {
        "investedWeight": invested,
        "cashWeight": cash,
        "riskySleeveHhi": hhi,
        "effectiveNames": (1.0 / hhi if hhi > 0.0 else 0.0),
        "top1Weight": sum(ordered[:1]),
        "top5Weight": sum(ordered[:5]),
        "maxWeight": (ordered[0] if ordered else 0.0),
    }
    for field, value in expected.items():
        _require_close(concentration.get(field), value, f"{label} concentration.{field}")


def _expected_available_component_status(
    *,
    policy_id: str,
    config: dict[str, Any],
    reasons: list[str],
) -> dict[str, str]:
    if policy_id == FIXED_WEIGHTING_POLICY:
        expected = {
            "score": "available",
            "methodology": "fixed_not_optimized",
            "liquidity": "trailing_raw_dollar_volume",
            "marketCap": "not_used",
        }
    else:  # pragma: no cover - canonical registry validation prevents this branch
        raise ValueError(f"unsupported weighting policy: {policy_id}")
    if "top_n_boundary_tie_resolved_by_trailing_dollar_volume" in reasons:
        expected["selectionTieBreak"] = "trailing_dollar_volume_desc_then_symbol_asc"
    return expected


def _validate_factor_portfolio(
    portfolio: object,
    *,
    factor: str,
    policy_id: str,
    as_of: str,
    config: dict[str, Any],
    latest_eligible_count: int,
) -> dict[str, Any]:
    label = f"factorPortfolios[{factor}]"
    if not isinstance(portfolio, dict) or set(portfolio) != _FACTOR_PORTFOLIO_FIELDS:
        raise ValueError(f"dashboard {label} has a non-canonical field set")
    if (
        portfolio.get("factor") != factor
        or portfolio.get("weightingPolicyId") != policy_id
        or portfolio.get("weightingPolicyVersion") != POLICY_REGISTRY[policy_id]["version"]
        or portfolio.get("asOf") != as_of
        or portfolio.get("signalDate") != as_of
        or portfolio.get("targetType") != "factor_portfolio"
        or portfolio.get("executionTiming") != "next_available_session_close_after_signal"
        or portfolio.get("tieBreakPolicy") != TIE_BREAK_POLICY
    ):
        raise ValueError(f"dashboard {label} identity/policy/date contract is inconsistent")

    status = portfolio.get("status")
    eligible_count = portfolio.get("eligibleSecurityCount")
    selected_count = portfolio.get("selectedSecurityCount")
    weights = portfolio.get("weights")
    cash = portfolio.get("cashWeight")
    selection_fraction = portfolio.get("selectionFraction")
    reasons = portfolio.get("reasons")
    component_status = portfolio.get("componentStatus")
    if (
        status not in {"available", "unavailable"}
        or not _nonnegative_integer(eligible_count)
        or int(eligible_count) > latest_eligible_count
        or not _nonnegative_integer(selected_count)
        or not isinstance(weights, list)
        or int(selected_count) != len(weights)
        or int(selected_count) > int(eligible_count)
        or int(selected_count) > int(config["top_n"])
        or not _finite_number(cash)
        or not 0.0 <= float(cash) <= 1.0
        or not _finite_number(selection_fraction)
        or not isinstance(reasons, list)
        or not all(_required_text(reason) for reason in reasons)
        or len(reasons) != len(set(reasons))
        or not isinstance(component_status, dict)
        or not all(
            _required_text(key) and _required_text(value) for key, value in component_status.items()
        )
    ):
        raise ValueError(f"dashboard {label} status/count fields are inconsistent")
    _require_close(
        selection_fraction,
        len(weights) / int(eligible_count) if int(eligible_count) else 0.0,
        f"dashboard {label}.selectionFraction",
    )

    if status == "unavailable":
        if (
            weights != []
            or int(selected_count) != 0
            or not _close(float(cash), 1.0)
            or len(reasons) != 1
            or reasons[0] not in _UNAVAILABLE_FACTOR_PORTFOLIO_COMPONENTS
            or component_status != _UNAVAILABLE_FACTOR_PORTFOLIO_COMPONENTS[reasons[0]]
        ):
            raise ValueError(f"dashboard {label} unavailable allocation is not fail-closed")
        reason = str(reasons[0])
        if (
            (reason == "no_complete_signal_inputs" and int(eligible_count) != 0)
            or (
                reason
                in {
                    "no_finite_trailing_dollar_volume",
                    "no_point_in_time_market_cap",
                    "no_finite_trailing_dollar_volume+no_point_in_time_market_cap",
                    "no_complete_fixed_policy_inputs",
                }
                and int(eligible_count) <= 0
            )
            or (
                reason == "top_n_boundary_tie_has_no_finite_liquidity_tie_break"
                and int(eligible_count) <= int(config["top_n"])
            )
        ):
            raise ValueError(f"dashboard {label} unavailable reason/count is inconsistent")
        _validate_concentration(portfolio, label)
        return portfolio

    if (
        not weights
        or int(eligible_count) <= 0
        or any(reason not in _AVAILABLE_FACTOR_PORTFOLIO_REASONS for reason in reasons)
        or component_status
        != _expected_available_component_status(
            policy_id=policy_id,
            config=config,
            reasons=reasons,
        )
    ):
        raise ValueError(f"dashboard {label} available allocation contract is inconsistent")
    if (len(weights) < int(config["top_n"])) != (
        "fewer_complete_policy_inputs_than_top_n" in reasons
    ) or (float(cash) > 1e-12) != ("max_weight_capacity_or_missing_policy_inputs" in reasons):
        raise ValueError(f"dashboard {label} available reason flags are inconsistent")

    symbols: list[str] = []
    total = 0.0
    for expected_rank, row in enumerate(weights, start=1):
        if (
            not isinstance(row, dict)
            or set(row) != _FACTOR_PORTFOLIO_WEIGHT_FIELDS
            or row.get("rank") != expected_rank
            or not _required_text(row.get("symbol"))
            or not _required_text(row.get("name"))
            or row.get("eligibilityStatus") != "eligible"
            or not _finite_number(row.get("factorScore"))
            or not _finite_number(row.get("latestPrice"))
            or float(row["latestPrice"]) <= 0.0
            or not _finite_number(row.get("rawPolicyScore"))
            or float(row["rawPolicyScore"]) <= 0.0
            or not _finite_number(row.get("preCapWeight"))
            or float(row["preCapWeight"]) <= 0.0
            or not _finite_number(row.get("weight"))
            or not 0.0 < float(row["weight"]) <= float(config["max_weight"]) + 1e-12
            or not _finite_number(row.get("maxWeight"))
            or not _close(float(row["maxWeight"]), float(config["max_weight"]))
            or not isinstance(row.get("capBinding"), bool)
            or not _finite_number(row.get("rankComponent"))
            or not _finite_number(row.get("trailingDollarVolume"))
            or float(row["trailingDollarVolume"]) <= 0.0
            or row.get("trailingMarketCap") is not None
        ):
            raise ValueError(f"dashboard {label} contains an invalid holding")
        if policy_id == FIXED_WEIGHTING_POLICY:
            if (
                not _finite_number(row.get("scoreComponent"))
                or not 0.0 < float(row["scoreComponent"]) <= 1.0
                or not _finite_number(row.get("liquidityComponent"))
                or not 0.0 < float(row["liquidityComponent"]) <= 1.0
                or not _finite_number(row.get("marketCapComponent"))
                or not _close(float(row["marketCapComponent"]), 0.0)
            ):
                raise ValueError(f"dashboard {label} score/liquidity components are invalid")
        symbols.append(str(row["symbol"]))
        total += float(row["weight"])
    if len(symbols) != len(set(symbols)):
        raise ValueError(f"dashboard {label} contains duplicate symbols")
    if not _close(total + float(cash), 1.0):
        raise ValueError(f"dashboard {label} weights plus cash do not sum to 1")
    _validate_policy_weight_construction(
        portfolio,
        policy_id=policy_id,
        config=config,
        label=label,
    )
    _validate_concentration(portfolio, label)
    return portfolio


def _validate_factor_portfolios(
    payload: dict[str, Any],
    *,
    factors: set[str],
    selected: dict[str, Any],
    as_of: str,
) -> None:
    portfolios = payload.get("factorPortfolios")
    selected_factor = str(selected["factor"])
    selected_policy = str(selected["policy_id"])
    if not isinstance(portfolios, dict) or set(portfolios) != factors:
        raise ValueError("dashboard factorPortfolios do not cover the exact canonical 64 factors")
    meta = payload.get("meta")
    if not isinstance(meta, dict) or meta.get("portfolioCount") != len(factors):
        raise ValueError("dashboard factorPortfolios metadata count is inconsistent")
    selected_policy_rows = {
        str(row["factor"]): row
        for row in payload["factorPolicyRanking"]
        if row.get("policy_id") == selected_policy
    }
    if set(selected_policy_rows) != factors:
        raise ValueError("dashboard selected-policy static grid is incomplete")

    config = payload["config"]
    latest_eligible_count = int(payload["data"]["latestEligibleSecurityCount"])
    for factor in sorted(factors):
        portfolio = _validate_factor_portfolio(
            portfolios[factor],
            factor=factor,
            policy_id=selected_policy,
            as_of=as_of,
            config=config,
            latest_eligible_count=latest_eligible_count,
        )
        row = selected_policy_rows[factor]
        available = portfolio["status"] == "available"
        expected_reasons = [] if available else portfolio["reasons"]
        if (
            row.get("current_portfolio_available") is not available
            or row.get("current_portfolio_input_reasons") != expected_reasons
        ):
            raise ValueError(f"dashboard factorPortfolios[{factor}] static-grid status differs")
        numeric_parity = {
            "current_holding_count": float(portfolio["selectedSecurityCount"]),
            "current_cash_weight": float(portfolio["cashWeight"]),
            "current_target_effective_names": float(portfolio["concentration"]["effectiveNames"]),
            "current_target_hhi": float(portfolio["concentration"]["riskySleeveHhi"]),
            "current_target_max_weight": float(portfolio["concentration"]["maxWeight"]),
        }
        for field, expected in numeric_parity.items():
            _require_close(
                row.get(field),
                expected,
                f"dashboard factorPortfolios[{factor}] static-grid {field}",
            )

    if payload.get("currentResearchTarget") != portfolios[selected_factor]:
        raise ValueError(
            "dashboard currentResearchTarget differs from the selected factor portfolio"
        )


def _validate_policy_weight_construction(
    portfolio: dict[str, Any],
    *,
    policy_id: str,
    config: dict[str, Any],
    label: str,
) -> None:
    weights = portfolio["weights"]
    factor_scores = [float(row["factorScore"]) for row in weights]
    if any(left < right for left, right in zip(factor_scores, factor_scores[1:])):
        raise ValueError(f"{label} factor scores are not ordered descending")
    component_status = portfolio["componentStatus"]
    rank_components: list[float] = []
    for position, row in enumerate(weights):
        expected_rank_component = _ascending_average_rank(factor_scores, position)
        _require_close(
            row.get("rankComponent"),
            expected_rank_component,
            f"{label} rank component",
        )
        rank_components.append(expected_rank_component)

    score_components: list[float] | None = None
    liquidity_components: list[float] | None = None
    if policy_id == FIXED_WEIGHTING_POLICY:
        scoring_values = [max(value, 0.0) for value in factor_scores]
        if not any(value > 0.0 for value in scoring_values):
            scoring_values = factor_scores
        liquidity_values = [row.get("trailingDollarVolume") for row in weights]
        if any(not _finite_number(value) or float(value) <= 0.0 for value in liquidity_values):
            raise ValueError(f"{label} trailing liquidity inputs are invalid")
        score_components = [
            _percentile_rank(scoring_values, position) for position in range(len(weights))
        ]
        liquidity_numbers = [float(value) for value in liquidity_values]
        liquidity_components = [
            _percentile_rank(liquidity_numbers, position) for position in range(len(weights))
        ]

    raw_values: list[float] = []
    for position, row in enumerate(weights):
        if policy_id == FIXED_WEIGHTING_POLICY:
            if (
                component_status.get("methodology") != "fixed_not_optimized"
                or component_status.get("liquidity") != "trailing_raw_dollar_volume"
                or component_status.get("marketCap") != "not_used"
                or score_components is None
                or liquidity_components is None
            ):
                raise ValueError(f"{label} fixed-method components are inconsistent")
            _require_close(
                row.get("scoreComponent"),
                score_components[position],
                f"{label} score component",
            )
            _require_close(
                row.get("liquidityComponent"),
                liquidity_components[position],
                f"{label} liquidity component",
            )
            _require_close(
                row.get("marketCapComponent"),
                0.0,
                f"{label} market-cap component",
            )
            expected_raw = (
                float(config["allocation_rank_floor"])
                + float(config["allocation_score_weight"]) * score_components[position]
                + float(config["allocation_liquidity_weight"]) * liquidity_components[position]
            )
        else:  # pragma: no cover - registry validation prevents this branch
            raise ValueError(f"unsupported weighting policy: {policy_id}")
        _require_close(row.get("rawPolicyScore"), expected_raw, f"{label} raw policy score")
        raw_values.append(expected_raw)

    raw_total = sum(raw_values)
    expected_weights = capped_weight_values(raw_values, float(config["max_weight"]))
    for row, raw_value, expected_weight in zip(weights, raw_values, expected_weights, strict=True):
        _require_close(row.get("preCapWeight"), raw_value / raw_total, f"{label} pre-cap weight")
        _require_close(row.get("weight"), expected_weight, f"{label} capped weight")
        _require_close(row.get("maxWeight"), float(config["max_weight"]), f"{label} max weight")
        expected_binding = expected_weight >= float(config["max_weight"]) - 1e-12
        if row.get("capBinding") is not expected_binding:
            raise ValueError(f"{label} cap-binding flag is inconsistent")


def _validate_current_target(
    payload: dict[str, Any], *, as_of: str, selected: dict[str, Any]
) -> dict[str, Any]:
    target = payload.get("currentResearchTarget")
    config = payload["config"]
    factor = str(selected["factor"])
    policy = str(selected["policy_id"])
    label = "currentResearchTarget"
    if (
        not isinstance(target, dict)
        or target.get("factor") != factor
        or target.get("weightingPolicyId") != policy
        or target.get("weightingPolicyVersion") != POLICY_REGISTRY[policy]["version"]
        or target.get("asOf") != as_of
        or target.get("signalDate") != as_of
        or target.get("targetType") != "factor_portfolio"
        or target.get("executionTiming") != "next_available_session_close_after_signal"
        or target.get("status") != "available"
        or not _required_text(target.get("tieBreakPolicy"))
        or not isinstance(target.get("componentStatus"), dict)
        or target["componentStatus"].get("score") != "available"
        or not isinstance(target.get("reasons"), list)
        or not all(_required_text(reason) for reason in target["reasons"])
    ):
        raise ValueError("dashboard currentResearchTarget identity/status is inconsistent")
    weights = target.get("weights")
    if not isinstance(weights, list) or not weights:
        raise ValueError("dashboard currentResearchTarget has no selected allocation")
    selected_count = target.get("selectedSecurityCount")
    eligible_count = target.get("eligibleSecurityCount")
    if (
        not _nonnegative_integer(selected_count)
        or int(selected_count) != len(weights)
        or not _nonnegative_integer(eligible_count)
        or int(eligible_count) < len(weights)
        or len(weights) > int(config["top_n"])
    ):
        raise ValueError("dashboard currentResearchTarget counts are inconsistent")
    symbols: list[str] = []
    total = 0.0
    for expected_rank, row in enumerate(weights, start=1):
        if (
            not isinstance(row, dict)
            or row.get("rank") != expected_rank
            or not _required_text(row.get("symbol"))
            or not _required_text(row.get("name"))
            or row.get("eligibilityStatus") != "eligible"
            or not _finite_number(row.get("factorScore"))
            or not _finite_number(row.get("latestPrice"))
            or float(row["latestPrice"]) <= 0.0
            or not _finite_number(row.get("weight"))
            or not 0.0 < float(row["weight"]) <= float(config["max_weight"]) + 1e-12
        ):
            raise ValueError("dashboard currentResearchTarget contains an invalid holding")
        symbols.append(str(row["symbol"]))
        total += float(row["weight"])
    if len(symbols) != len(set(symbols)):
        raise ValueError("dashboard currentResearchTarget contains duplicate symbols")
    cash = target.get("cashWeight")
    if (
        not _finite_number(cash)
        or not 0.0 <= float(cash) <= 1.0
        or not _close(total + float(cash), 1.0)
    ):
        raise ValueError("dashboard currentResearchTarget weights plus cash are inconsistent")
    _require_close(
        target.get("selectionFraction"),
        len(weights) / int(eligible_count) if int(eligible_count) else 0.0,
        "currentResearchTarget.selectionFraction",
    )
    _validate_policy_weight_construction(
        target,
        policy_id=policy,
        config=config,
        label=label,
    )
    _validate_concentration(target, label)
    return target


def _validate_backtest_held_portfolio(
    payload: dict[str, Any],
    *,
    as_of: str,
    selected_factor: str,
    selected_policy: str,
) -> dict[str, Any]:
    held = payload.get("backtestHeldPortfolio")
    if (
        not isinstance(held, dict)
        or held.get("factor") != selected_factor
        or held.get("weightingPolicyId") != selected_policy
        or held.get("asOf") != as_of
        or not _required_text(held.get("lastSignalDate"))
        or not _required_text(held.get("lastExecutionDate"))
        or not isinstance(held.get("valuationAvailable"), bool)
        or not isinstance(held.get("weights"), list)
        or not _finite_number(held.get("cashWeight"))
        or not 0.0 <= float(held["cashWeight"]) <= 1.0
    ):
        raise ValueError("dashboard backtestHeldPortfolio contract is inconsistent")
    weights = held["weights"]
    if not (str(held["lastSignalDate"]) <= str(held["lastExecutionDate"]) <= as_of):
        raise ValueError("dashboard backtestHeldPortfolio dates are inconsistent")
    if held["valuationAvailable"] is True and not weights:
        raise ValueError("dashboard valued backtestHeldPortfolio has no holdings")
    symbols: list[str] = []
    total = float(held["cashWeight"])
    for expected_rank, row in enumerate(weights, start=1):
        if (
            not isinstance(row, dict)
            or row.get("rank") != expected_rank
            or not _required_text(row.get("symbol"))
            or not _required_text(row.get("name"))
            or not _finite_number(row.get("weight"))
            or not 0.0 < float(row["weight"]) <= 1.0
            or (row.get("factorScore") is not None and not _finite_number(row.get("factorScore")))
            or (
                held["valuationAvailable"] is True
                and (not _finite_number(row.get("latestPrice")) or float(row["latestPrice"]) <= 0.0)
            )
        ):
            raise ValueError("dashboard backtestHeldPortfolio has an invalid holding")
        symbols.append(str(row["symbol"]))
        total += float(row["weight"])
    if len(symbols) != len(set(symbols)):
        raise ValueError("dashboard backtestHeldPortfolio contains duplicate symbols")
    if not _close(total, 1.0):
        raise ValueError("dashboard backtestHeldPortfolio weights plus cash do not sum to 1")
    return held


def _validate_selected_backtest_holding_history(
    payload: dict[str, Any],
    *,
    held: dict[str, Any],
    as_of: str,
    selected_factor: str,
    selected_policy: str,
) -> None:
    history = payload.get("selectedBacktestHoldingHistory")
    expected_fields = {
        "contractVersion",
        "factor",
        "weightingPolicyId",
        "weightTiming",
        "startDate",
        "endDate",
        "sessionCount",
        "sessions",
    }
    if (
        not isinstance(history, dict)
        or set(history) != expected_fields
        or history.get("contractVersion") != SELECTED_HOLDING_HISTORY_CONTRACT_VERSION
        or history.get("factor") != selected_factor
        or history.get("weightingPolicyId") != selected_policy
        or history.get("weightTiming") != SELECTED_HOLDING_HISTORY_WEIGHT_TIMING
        or history.get("sessionCount") != SELECTED_HOLDING_HISTORY_SESSION_COUNT
    ):
        raise ValueError("dashboard selectedBacktestHoldingHistory identity is inconsistent")
    sessions = history.get("sessions")
    if (
        not isinstance(sessions, list)
        or len(sessions) != SELECTED_HOLDING_HISTORY_SESSION_COUNT
        or not sessions
    ):
        raise ValueError("dashboard selectedBacktestHoldingHistory sessions are incomplete")

    expected_session_fields = {
        "date",
        "valuationAvailable",
        "cashWeight",
        "executionStatus",
        "lastSignalDate",
        "lastExecutionDate",
        "weights",
    }
    expected_weight_fields = {"rank", "symbol", "name", "weight"}
    allowed_statuses = {
        "none",
        "executed",
        "executed_partial_unpriceable_targets",
        "blocked_missing_held_quote",
        "blocked_all_targets_unpriceable",
    }
    dates: list[str] = []
    previous_execution_metadata: tuple[object, object] | None = None
    for session_index, session in enumerate(sessions):
        if not isinstance(session, dict) or set(session) != expected_session_fields:
            raise ValueError("dashboard selected holding history session shape is invalid")
        date = _required_text(session.get("date"))
        signal_date = session.get("lastSignalDate")
        execution_date = session.get("lastExecutionDate")
        execution_status = session.get("executionStatus")
        if (
            not date
            or date > as_of
            or not isinstance(session.get("valuationAvailable"), bool)
            or not _finite_number(session.get("cashWeight"))
            or not 0.0 <= float(session["cashWeight"]) <= 1.0
            or execution_status not in allowed_statuses
            or not (
                (signal_date is None and execution_date is None)
                or (
                    _required_text(signal_date)
                    and _required_text(execution_date)
                    and str(signal_date) <= str(execution_date) <= date
                )
            )
        ):
            raise ValueError("dashboard selected holding history session metadata is invalid")
        metadata = (signal_date, execution_date)
        if execution_status in {"executed", "executed_partial_unpriceable_targets"}:
            if execution_date != date:
                raise ValueError(
                    "dashboard selected holding history execution date is inconsistent"
                )
        elif session_index > 0 and metadata != previous_execution_metadata:
            raise ValueError(
                "dashboard selected holding history execution metadata changed without execution"
            )
        previous_execution_metadata = metadata

        weights = session.get("weights")
        if not isinstance(weights, list) or not weights:
            raise ValueError("dashboard selected holding history weights are missing")
        symbols: list[str] = []
        total = float(session["cashWeight"])
        ordering: list[tuple[float, str]] = []
        for expected_rank, row in enumerate(weights, start=1):
            if (
                not isinstance(row, dict)
                or set(row) != expected_weight_fields
                or row.get("rank") != expected_rank
                or not _required_text(row.get("symbol"))
                or not _required_text(row.get("name"))
                or not _finite_number(row.get("weight"))
                or not 0.0 < float(row["weight"]) <= 1.0
            ):
                raise ValueError("dashboard selected holding history contains an invalid weight")
            symbol = str(row["symbol"])
            symbols.append(symbol)
            total += float(row["weight"])
            ordering.append((-float(row["weight"]), symbol))
        if (
            len(symbols) != len(set(symbols))
            or ordering != sorted(ordering)
            or not _close(total, 1.0)
        ):
            raise ValueError("dashboard selected holding history allocation is inconsistent")
        dates.append(date)

    if (
        len(dates) != len(set(dates))
        or dates != sorted(dates)
        or history.get("startDate") != dates[0]
        or history.get("endDate") != dates[-1]
        or dates[-1] != as_of
    ):
        raise ValueError("dashboard selected holding history date range is inconsistent")
    performance = payload.get("performance")
    performance_dates = performance.get("dates") if isinstance(performance, dict) else None
    if (
        not isinstance(performance_dates, list)
        or len(performance_dates) < SELECTED_HOLDING_HISTORY_SESSION_COUNT
        or dates != performance_dates[-SELECTED_HOLDING_HISTORY_SESSION_COUNT:]
    ):
        raise ValueError(
            "dashboard selected holding history dates differ from canonical performance dates"
        )

    final_session = sessions[-1]
    expected_final_weights = [
        {
            "rank": row["rank"],
            "symbol": row["symbol"],
            "name": row["name"],
            "weight": row["weight"],
        }
        for row in held["weights"]
    ]
    if (
        final_session["weights"] != expected_final_weights
        or final_session["cashWeight"] != held["cashWeight"]
        or final_session["valuationAvailable"] is not held["valuationAvailable"]
        or final_session["lastSignalDate"] != held["lastSignalDate"]
        or final_session["lastExecutionDate"] != held["lastExecutionDate"]
    ):
        raise ValueError(
            "dashboard selected holding history final session differs from backtestHeldPortfolio"
        )


def _validate_factor_holding_history_sidecar_data(
    payload: dict[str, Any],
    data: object,
    *,
    selected_history: dict[str, Any],
) -> dict[str, Any]:
    expected_fields = {
        "contract",
        "contractVersion",
        "resultKey",
        "weightingPolicy",
        "weightTiming",
        "startDate",
        "endDate",
        "sessionCount",
        "dates",
        "factorCount",
        "independentFactorCount",
        "diagnosticFactorCount",
        "factorDefinitionSha256",
        "policyDefinitionSha256",
        "symbols",
        "factors",
    }
    definitions = payload.get("factorDefinitions")
    factor_ids = (
        {
            str(row["factor"])
            for row in definitions
            if isinstance(row, dict) and _required_text(row.get("factor"))
        }
        if isinstance(definitions, list)
        else set()
    )
    independent = (
        {
            str(row["factor"])
            for row in definitions
            if isinstance(row, dict)
            and row.get("selection_eligible") is True
            and row.get("compatibility_alias_of") is None
        }
        if isinstance(definitions, list)
        else set()
    )
    diagnostic = factor_ids.difference(independent)
    performance_dates = payload.get("performance", {}).get("dates", [])
    dates = performance_dates[-SELECTED_HOLDING_HISTORY_SESSION_COUNT:]
    if (
        not isinstance(data, dict)
        or set(data) != expected_fields
        or data.get("contract") != FACTOR_HOLDING_HISTORY_SIDECAR_CONTRACT
        or data.get("contractVersion") != FACTOR_HOLDING_HISTORY_SIDECAR_CONTRACT_VERSION
        or data.get("resultKey") != payload.get("resultKey")
        or data.get("weightingPolicy") != payload.get("weightingPolicy")
        or data.get("weightTiming") != SELECTED_HOLDING_HISTORY_WEIGHT_TIMING
        or data.get("startDate") != dates[0]
        or data.get("endDate") != dates[-1]
        or data.get("sessionCount") != SELECTED_HOLDING_HISTORY_SESSION_COUNT
        or data.get("dates") != dates
        or data.get("factorCount") != len(factor_ids)
        or data.get("independentFactorCount") != len(independent)
        or data.get("diagnosticFactorCount") != len(diagnostic)
        or data.get("factorDefinitionSha256")
        != payload.get("meta", {}).get("factorDefinitionSha256")
        or data.get("policyDefinitionSha256")
        != payload.get("meta", {}).get("policyDefinitionSha256")
    ):
        raise ValueError("dashboard factor holding history sidecar provenance is inconsistent")

    raw_symbols = data.get("symbols")
    if not isinstance(raw_symbols, list):
        raise ValueError("dashboard factor holding history symbol dictionary is invalid")
    symbols: list[str] = []
    names: list[str] = []
    for row in raw_symbols:
        if (
            not isinstance(row, list)
            or len(row) != 2
            or not _required_text(row[0])
            or not _required_text(row[1])
        ):
            raise ValueError("dashboard factor holding history symbol dictionary is invalid")
        symbols.append(str(row[0]))
        names.append(str(row[1]))
    if len(symbols) != len(set(symbols)) or symbols != sorted(symbols):
        raise ValueError("dashboard factor holding history symbol dictionary is invalid")

    factors = data.get("factors")
    if not isinstance(factors, dict) or set(factors) != factor_ids:
        raise ValueError("dashboard factor holding history factor coverage is incomplete")
    allowed_statuses = {
        "none",
        "executed",
        "executed_partial_unpriceable_targets",
        "blocked_missing_held_quote",
        "blocked_all_targets_unpriceable",
    }
    selected_factor = str(payload.get("bestFactor", payload.get("selectedFactor")))
    expanded_selected_sessions: list[dict[str, Any]] = []
    top_n = int(payload["config"]["top_n"])
    for factor in sorted(factor_ids):
        factor_history = factors[factor]
        if (
            not isinstance(factor_history, dict)
            or set(factor_history) != {"factor", "weightingPolicyId", "resultKey", "sessions"}
            or factor_history.get("factor") != factor
            or factor_history.get("weightingPolicyId")
            != payload.get("weightingPolicy", payload.get("selectedWeightingPolicy"))
            or factor_history.get("resultKey") != payload.get("resultKey")
        ):
            raise ValueError("dashboard factor holding history identity is inconsistent")
        sessions = factor_history.get("sessions")
        if not isinstance(sessions, list) or len(sessions) != len(dates):
            raise ValueError("dashboard factor holding history sessions are incomplete")
        previous_execution_metadata: tuple[object, object] | None = None
        for date, session in zip(dates, sessions, strict=True):
            if not isinstance(session, dict) or set(session) != {
                "valuationAvailable",
                "cashWeight",
                "executionStatus",
                "lastSignalDate",
                "lastExecutionDate",
                "weights",
            }:
                raise ValueError("dashboard factor holding history session shape is invalid")
            signal_date = session.get("lastSignalDate")
            execution_date = session.get("lastExecutionDate")
            execution_status = session.get("executionStatus")
            if (
                not isinstance(session.get("valuationAvailable"), bool)
                or not _finite_number(session.get("cashWeight"))
                or not 0.0 <= float(session["cashWeight"]) <= 1.0
                or execution_status not in allowed_statuses
                or not (
                    (signal_date is None and execution_date is None)
                    or (
                        _required_text(signal_date)
                        and _required_text(execution_date)
                        and str(signal_date) <= str(execution_date) <= str(date)
                    )
                )
            ):
                raise ValueError("dashboard factor holding history session metadata is invalid")
            metadata = (signal_date, execution_date)
            if execution_status in {"executed", "executed_partial_unpriceable_targets"}:
                if execution_date != date:
                    raise ValueError(
                        "dashboard factor holding history execution date is inconsistent"
                    )
            elif (
                previous_execution_metadata is not None and metadata != previous_execution_metadata
            ):
                raise ValueError(
                    "dashboard factor holding history execution metadata changed without execution"
                )
            previous_execution_metadata = metadata

            raw_weights = session.get("weights")
            if not isinstance(raw_weights, list) or len(raw_weights) > top_n:
                raise ValueError("dashboard factor holding history weights are invalid")
            observed_indexes: set[int] = set()
            ordering: list[tuple[float, str]] = []
            expanded_weights: list[dict[str, Any]] = []
            total = float(session["cashWeight"])
            for rank, pair in enumerate(raw_weights, start=1):
                if (
                    not isinstance(pair, list)
                    or len(pair) != 2
                    or not isinstance(pair[0], int)
                    or isinstance(pair[0], bool)
                    or pair[0] < 0
                    or pair[0] >= len(symbols)
                    or pair[0] in observed_indexes
                    or not _finite_number(pair[1])
                    or not 0.0 < float(pair[1]) <= 1.0
                ):
                    raise ValueError("dashboard factor holding history contains an invalid weight")
                symbol_index = pair[0]
                weight = float(pair[1])
                observed_indexes.add(symbol_index)
                total += weight
                ordering.append((-weight, symbols[symbol_index]))
                expanded_weights.append(
                    {
                        "rank": rank,
                        "symbol": symbols[symbol_index],
                        "name": names[symbol_index],
                        "weight": pair[1],
                    }
                )
            if ordering != sorted(ordering) or not _close(total, 1.0):
                raise ValueError("dashboard factor holding history allocation is inconsistent")
            if factor == selected_factor:
                expanded_selected_sessions.append(
                    {
                        "date": date,
                        "valuationAvailable": session["valuationAvailable"],
                        "cashWeight": session["cashWeight"],
                        "executionStatus": execution_status,
                        "lastSignalDate": signal_date,
                        "lastExecutionDate": execution_date,
                        "weights": expanded_weights,
                    }
                )

    if expanded_selected_sessions != selected_history.get("sessions"):
        raise ValueError(
            "dashboard factor holding history selected factor differs from canonical history"
        )
    return data


def _validate_factor_holding_history_sidecar(
    payload: dict[str, Any],
    *,
    selected_history: dict[str, Any],
) -> dict[str, Any]:
    manifest = payload.get("factorHoldingHistorySidecar")
    base_fields = {
        "contract",
        "contractVersion",
        "storage",
        "path",
        "sha256",
        "bytes",
        "resultKey",
        "weightingPolicy",
        "weightTiming",
        "startDate",
        "endDate",
        "sessionCount",
        "factorCount",
        "independentFactorCount",
        "diagnosticFactorCount",
    }
    has_data = isinstance(manifest, dict) and "data" in manifest
    expected_fields = base_fields | ({"data"} if has_data else set())
    expected_path = (
        f"data/{FACTOR_HOLDING_HISTORY_SIDECAR_DIRECTORY}/{payload.get('resultKey')}.json"
    )
    if (
        not isinstance(manifest, dict)
        or set(manifest) != expected_fields
        or manifest.get("contract") != FACTOR_HOLDING_HISTORY_SIDECAR_CONTRACT
        or manifest.get("contractVersion") != FACTOR_HOLDING_HISTORY_SIDECAR_CONTRACT_VERSION
        or manifest.get("storage") != ("embedded" if has_data else "external")
        or manifest.get("path") != expected_path
        or not _is_sha256(manifest.get("sha256"))
        or not isinstance(manifest.get("bytes"), int)
        or isinstance(manifest.get("bytes"), bool)
        or not 1 <= int(manifest["bytes"]) <= MAX_FACTOR_HOLDING_HISTORY_SIDECAR_BYTES
        or manifest.get("resultKey") != payload.get("resultKey")
        or manifest.get("weightingPolicy") != payload.get("weightingPolicy")
        or manifest.get("weightTiming") != SELECTED_HOLDING_HISTORY_WEIGHT_TIMING
        or manifest.get("startDate") != selected_history.get("startDate")
        or manifest.get("endDate") != selected_history.get("endDate")
        or manifest.get("sessionCount") != SELECTED_HOLDING_HISTORY_SESSION_COUNT
        or manifest.get("factorCount") != payload.get("meta", {}).get("factorCount")
        or manifest.get("independentFactorCount")
        != payload.get("meta", {}).get("independentFactorCount")
        or manifest.get("diagnosticFactorCount") != payload.get("meta", {}).get("aliasFactorCount")
    ):
        raise ValueError("dashboard factor holding history sidecar manifest is inconsistent")
    if has_data:
        data = _validate_factor_holding_history_sidecar_data(
            payload,
            manifest["data"],
            selected_history=selected_history,
        )
        encoded = canonical_json_bytes(data)
        if (
            len(encoded) != manifest["bytes"]
            or hashlib.sha256(encoded).hexdigest() != manifest["sha256"]
        ):
            raise ValueError("dashboard factor holding history sidecar hash/size is inconsistent")
    return manifest


def validate_factor_holding_history_sidecar_bytes(
    payload: dict[str, Any],
    encoded: bytes,
) -> dict[str, Any]:
    manifest = payload.get("factorHoldingHistorySidecar")
    if len(encoded) > MAX_FACTOR_HOLDING_HISTORY_SIDECAR_BYTES:
        raise ValueError(
            "dashboard factor holding history external bytes exceed the "
            f"{MAX_FACTOR_HOLDING_HISTORY_SIDECAR_BYTES:,}-byte limit"
        )
    if (
        not isinstance(manifest, dict)
        or manifest.get("storage") != "external"
        or len(encoded) != manifest.get("bytes")
        or hashlib.sha256(encoded).hexdigest() != manifest.get("sha256")
    ):
        raise ValueError("dashboard factor holding history external bytes differ from manifest")
    try:
        data = json.loads(encoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("dashboard factor holding history sidecar is not valid JSON") from error
    selected_history = payload.get(
        "bestFactorBacktestHoldingHistory",
        payload.get("selectedBacktestHoldingHistory"),
    )
    if not isinstance(selected_history, dict):
        raise ValueError("dashboard canonical selected holding history is unavailable")
    return _validate_factor_holding_history_sidecar_data(
        payload,
        data,
        selected_history=selected_history,
    )


def externalize_factor_holding_history_sidecar(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], bytes | None]:
    public_payload = deepcopy(payload)
    manifest = public_payload.get("factorHoldingHistorySidecar")
    if not isinstance(manifest, dict) or "data" not in manifest:
        return public_payload, None
    encoded = canonical_json_bytes(manifest.pop("data"))
    manifest["storage"] = "external"
    validate_factor_holding_history_sidecar_bytes(public_payload, encoded)
    return public_payload, encoded


def _validate_current_transition(
    payload: dict[str, Any],
    *,
    held: dict[str, Any],
    target: dict[str, Any],
    as_of: str,
) -> None:
    transition = payload.get("currentTransition")
    config = payload["config"]
    valuation_available = held["valuationAvailable"]
    if (
        not isinstance(transition, dict)
        or transition.get("asOf") != as_of
        or transition.get("targetSignalDate") != target.get("signalDate")
        or transition.get("expectedExecutionTiming") != target.get("executionTiming")
        or transition.get("actualNextClosePretradeDriftKnown") is not False
        or transition.get("valuationAvailable") is not valuation_available
        or not _finite_number(transition.get("pretradeCashWeight"))
        or not _close(float(transition["pretradeCashWeight"]), float(held["cashWeight"]))
        or not _finite_number(transition.get("targetCashWeight"))
        or not _close(float(transition["targetCashWeight"]), float(target["cashWeight"]))
        or not _finite_number(transition.get("totalCostBps"))
        or not _close(float(transition["totalCostBps"]), float(config["total_cost_bps"]))
        or transition.get("turnoverFormula")
        != "0.5*(sum_abs_target_minus_pretrade_stock+abs_target_minus_pretrade_cash)"
        or transition.get("costFormula") != "one_way_turnover*total_cost_bps/10000"
    ):
        raise ValueError("dashboard currentTransition contract is inconsistent")
    if valuation_available is not True:
        if (
            transition.get("status") != "unavailable_latest_held_valuation_incomplete"
            or _finite_number(transition.get("oneWayTurnover"))
            or _finite_number(transition.get("modeledCostFraction"))
        ):
            raise ValueError("dashboard unavailable currentTransition is inconsistent")
        return
    held_weights = {str(row["symbol"]): float(row["weight"]) for row in held["weights"]}
    target_weights = {str(row["symbol"]): float(row["weight"]) for row in target["weights"]}
    symbols = set(held_weights).union(target_weights)
    expected_turnover = 0.5 * (
        sum(
            abs(target_weights.get(symbol, 0.0) - held_weights.get(symbol, 0.0))
            for symbol in symbols
        )
        + abs(float(target["cashWeight"]) - float(held["cashWeight"]))
    )
    expected_cost = expected_turnover * float(config["total_cost_bps"]) / 10_000.0
    if transition.get("status") != "indicative_as_of_close":
        raise ValueError("dashboard currentTransition status is inconsistent")
    _require_close(
        transition.get("oneWayTurnover"), expected_turnover, "currentTransition turnover"
    )
    _require_close(
        transition.get("modeledCostFraction"), expected_cost, "currentTransition modeled cost"
    )


def _validate_contribution_event(event: object, label: str, *, exact: bool) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise ValueError(f"{label} is missing")
    if (
        not _required_text(event.get("symbol"))
        or not _required_text(event.get("date"))
        or (
            event.get("intervalStart") is not None
            and not _required_text(event.get("intervalStart"))
        )
        or not _nonnegative_integer(event.get("returnIntervalSessions"))
        or int(event["returnIntervalSessions"]) < 1
        or (exact and int(event["returnIntervalSessions"]) != 1)
    ):
        raise ValueError(f"{label} identity/date interval is invalid")
    for field in (
        "contribution",
        "absoluteContribution",
        "startWeight",
        "securityReturn",
        "portfolioReturn",
    ):
        if not _finite_number(event.get(field)):
            raise ValueError(f"{label}.{field} is not finite")
    if (
        float(event["absoluteContribution"]) < 0.0
        or not _close(float(event["absoluteContribution"]), abs(float(event["contribution"])))
        or not 0.0 <= float(event["startWeight"]) <= 1.0
    ):
        raise ValueError(f"{label} contribution arithmetic is inconsistent")
    return event


def _validate_leave_one(row: object, label: str) -> dict[str, Any]:
    if not isinstance(row, dict) or not _required_text(row.get("symbol")):
        raise ValueError(f"{label} identity is invalid")
    if (
        row.get("method") != "frozen_realized_contribution_deletion"
        or row.get("reoptimized") is not False
    ):
        raise ValueError(f"{label} method contract is invalid")
    for field in ("baseCagr", "leaveOneCagr", "cagrDelta", "absoluteCagrDelta"):
        if not _finite_number(row.get(field)):
            raise ValueError(f"{label}.{field} is not finite")
    if not _close(
        float(row["cagrDelta"]), float(row["baseCagr"]) - float(row["leaveOneCagr"])
    ) or not _close(float(row["absoluteCagrDelta"]), abs(float(row["cagrDelta"]))):
        raise ValueError(f"{label} CAGR arithmetic is inconsistent")
    return row


def _validate_contribution_diagnostics(payload: dict[str, Any], selected: dict[str, Any]) -> None:
    diagnostics = payload.get("contributionDiagnostics")
    if not isinstance(diagnostics, dict):
        raise ValueError("dashboard contributionDiagnostics is missing")
    if (
        not _required_text(diagnostics.get("attributionMethod"))
        or not _required_text(diagnostics.get("attributionVersion"))
        or diagnostics.get("complete") is not True
        or diagnostics.get("reason") is not None
        or diagnostics.get("observedReturnsPreserved") is not True
        or diagnostics.get("reoptimized") is not False
        or not _required_text(diagnostics.get("evaluationStart"))
        or not _required_text(diagnostics.get("evaluationEnd"))
        or not _nonnegative_integer(diagnostics.get("activeCalendarObservations"))
        or not _nonnegative_integer(diagnostics.get("observedReturnCount"))
        or int(diagnostics["observedReturnCount"]) > int(diagnostics["activeCalendarObservations"])
    ):
        raise ValueError("dashboard contributionDiagnostics contract is inconsistent")
    exact_event = _validate_contribution_event(
        diagnostics.get("maxExactSingleSessionSecurityContribution"),
        "contributionDiagnostics.maxExactSingleSessionSecurityContribution",
        exact=True,
    )
    observed_event = _validate_contribution_event(
        diagnostics.get("maxObservedIntervalSecurityContribution"),
        "contributionDiagnostics.maxObservedIntervalSecurityContribution",
        exact=False,
    )
    _require_close(
        diagnostics.get("maxAbsSecurityDayContribution"),
        float(exact_event["absoluteContribution"]),
        "contributionDiagnostics.maxAbsSecurityDayContribution",
    )
    largest = diagnostics.get("largestAbsoluteContributionSecurity")
    if not isinstance(largest, dict) or not _required_text(largest.get("symbol")):
        raise ValueError("dashboard largest absolute contribution security is invalid")
    for field in (
        "signedContribution",
        "absoluteContribution",
        "absoluteContributionShare",
    ):
        if not _finite_number(largest.get(field)):
            raise ValueError(f"dashboard largest contribution {field} is not finite")
    for field in (
        "maxSecurityAbsoluteContributionShare",
        "totalAbsoluteSecurityContribution",
        "absoluteContributionHhi",
        "maxLeaveOneSecurityCagrDelta",
        "attributionMaxResidual",
    ):
        if not _finite_number(diagnostics.get(field)) or float(diagnostics[field]) < 0.0:
            raise ValueError(f"dashboard contributionDiagnostics.{field} is invalid")
    if (
        not 0.0 <= float(largest["absoluteContributionShare"]) <= 1.0
        or not 0.0 <= float(diagnostics["maxSecurityAbsoluteContributionShare"]) <= 1.0
        or not 0.0 <= float(diagnostics["absoluteContributionHhi"]) <= 1.0
    ):
        raise ValueError("dashboard contribution share/HHI is outside [0, 1]")
    _require_close(
        diagnostics.get("maxSecurityAbsoluteContributionShare"),
        float(largest["absoluteContributionShare"]),
        "contributionDiagnostics.maxSecurityAbsoluteContributionShare",
    )
    total_absolute = float(diagnostics["totalAbsoluteSecurityContribution"])
    if total_absolute > 0.0:
        _require_close(
            largest.get("absoluteContributionShare"),
            float(largest["absoluteContribution"]) / total_absolute,
            "largestAbsoluteContributionSecurity.absoluteContributionShare",
        )

    max_leave_one = _validate_leave_one(
        diagnostics.get("maxLeaveOneSecurity"),
        "contributionDiagnostics.maxLeaveOneSecurity",
    )
    _require_close(
        diagnostics.get("maxLeaveOneSecurityCagrDelta"),
        float(max_leave_one["absoluteCagrDelta"]),
        "contributionDiagnostics.maxLeaveOneSecurityCagrDelta",
    )
    top = diagnostics.get("topLeaveOneSecurity")
    if not isinstance(top, list) or not top or len(top) > 10:
        raise ValueError("dashboard topLeaveOneSecurity list is invalid")
    validated_top = [
        _validate_leave_one(row, f"contributionDiagnostics.topLeaveOneSecurity[{position}]")
        for position, row in enumerate(top)
    ]
    if validated_top[0] != max_leave_one:
        raise ValueError("dashboard maxLeaveOneSecurity differs from the first top sensitivity")
    expected_order = sorted(
        validated_top,
        key=lambda row: (-float(row["absoluteCagrDelta"]), str(row["symbol"])),
    )
    if validated_top != expected_order:
        raise ValueError("dashboard top leave-one-security sensitivities are not ordered")

    cross_fields = {
        "contribution_diagnostics_complete": diagnostics["complete"],
        "contribution_attribution_method": diagnostics["attributionMethod"],
        "contribution_attribution_version": diagnostics["attributionVersion"],
    }
    if any(selected.get(field) != value for field, value in cross_fields.items()):
        raise ValueError("selected pair contribution diagnostic identity differs from detail")
    scalar_cross_fields = {
        "max_abs_security_day_contribution": diagnostics["maxAbsSecurityDayContribution"],
        "max_abs_security_observation_contribution": observed_event["absoluteContribution"],
        "max_security_absolute_contribution_share": diagnostics[
            "maxSecurityAbsoluteContributionShare"
        ],
        "absolute_contribution_hhi": diagnostics["absoluteContributionHhi"],
        "max_abs_leave_one_security_cagr_delta": diagnostics["maxLeaveOneSecurityCagrDelta"],
        "attribution_max_residual": diagnostics["attributionMaxResidual"],
    }
    for field, value in scalar_cross_fields.items():
        _require_close(selected.get(field), float(value), f"selected pair {field}")
    decision = payload["selectionDecision"]
    if (
        diagnostics["evaluationStart"] != decision["evaluationStart"]
        or diagnostics["evaluationEnd"] != decision["evaluationEnd"]
    ):
        raise ValueError("dashboard contribution diagnostic window differs from selection window")


def _validate_portfolio_policy(payload: dict[str, Any], selected: dict[str, Any]) -> None:
    policy = payload.get("portfolioPolicy")
    config = payload["config"]
    selected_policy = str(selected["policy_id"])
    expected_history = {
        "targetWeightKernel": True,
        "capAndCashContract": True,
        "turnoverFormula": "same_cash_inclusive_half_l1",
        "costFormula": "same_turnover_times_total_cost_rate",
        "historicalRebalanceGridRequired": True,
        "currentTransitionBasis": "latest_observed_close_indicative",
        "actualNextCloseTransitionKnown": False,
    }
    expected_parameters = {
        "topN": config["top_n"],
        "maxWeight": config["max_weight"],
        "rebalanceFrequency": config["rebalance_frequency"],
        "transactionCostBps": config["transaction_cost_bps"],
        "slippageBps": config["slippage_bps"],
        "factorScoreWeight": config["allocation_score_weight"],
        "liquidityWeight": config["allocation_liquidity_weight"],
        "marketCapWeight": config["allocation_market_cap_weight"],
        "rankFloor": config["allocation_rank_floor"],
        "marketCapMaximumAgeDays": config["market_cap_max_age_days"],
    }
    if (
        not isinstance(policy, dict)
        or policy.get("selectedPolicyId") != selected_policy
        or policy.get("version") != POLICY_REGISTRY[selected_policy]["version"]
        or policy.get("selectedReason") != payload["selectedReason"]
        or policy.get("historyCurrentParity") != expected_history
        or policy.get("parameters") != expected_parameters
    ):
        raise ValueError("dashboard portfolioPolicy contract is inconsistent")


def _load_payload(source: AnalysisResult | dict[str, Any] | Path) -> dict[str, Any]:
    """Load and validate the input-driven schema-v5 dashboard contract.

    Schema v5 deliberately removes the old canonical/current-target and joint
    factor-policy product surfaces. Internal compatibility aliases are created
    only while calling deep reusable validators; they are never serialized.
    """

    if isinstance(source, AnalysisResult):
        payload = result_payload(source)
    elif isinstance(source, Path):
        payload = json.loads(source.read_text(encoding="utf-8"))
    else:
        payload = source
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 5:
        raise ValueError("dashboard payload must use schemaVersion 5")
    required = {
        "resultKey",
        "resultIdentity",
        "generatedAtUtc",
        "bestFactor",
        "weightingPolicy",
        "bestFactorReason",
        "factorSelectionDecision",
        "factorAccounting",
        "factorRanking",
        "weightingMethodology",
        "contributionDiagnostics",
        "allocationMethod",
        "researchScope",
        "researchInputs",
        "config",
        "data",
        "selectionMethod",
        "bestFactorPortfolio",
        "backtestHeldPortfolio",
        "bestFactorBacktestHoldingHistory",
        "factorHoldingHistorySidecar",
        "bestFactorTransition",
        "factorPortfolios",
        "factorDefinitions",
        "factorDiagnostics",
        "performance",
        "meta",
    }
    missing = sorted(required.difference(payload))
    if missing:
        raise ValueError("dashboard payload missing schema-v5 fields: " + ", ".join(missing))
    forbidden = {
        "selectedFactor",
        "selectedWeightingPolicy",
        "selectedReason",
        "selectionDecision",
        "gridAccounting",
        "factorPolicyRanking",
        "policyDiagnostics",
        "weightingPolicyRegistry",
        "portfolioPolicy",
        "currentResearchTarget",
        "selectedBacktestHoldingHistory",
        "currentTransition",
    }
    legacy = sorted(forbidden.intersection(payload))
    if legacy:
        raise ValueError("dashboard schemaVersion 5 contains removed fields: " + ", ".join(legacy))
    if not _required_text(payload.get("generatedAtUtc")):
        raise ValueError("dashboard generatedAtUtc is required")

    best_factor = _required_text(payload.get("bestFactor"))
    policy_id = _required_text(payload.get("weightingPolicy"))
    if not best_factor or policy_id != FIXED_WEIGHTING_POLICY:
        raise ValueError("dashboard best factor or fixed weighting policy is invalid")
    methodology = payload.get("weightingMethodology")
    expected_methodology = {
        "registryVersion": POLICY_REGISTRY_VERSION,
        "policyId": FIXED_WEIGHTING_POLICY,
        "policy": POLICY_REGISTRY[FIXED_WEIGHTING_POLICY],
        "optimized": False,
    }
    if methodology != expected_methodology:
        raise ValueError("dashboard fixed weighting methodology is inconsistent")

    _validate_data(payload)
    _validate_identity(payload)
    _validate_research_inputs(payload)
    _validate_performance(payload)
    independent, aliases = _factor_sets(payload)
    all_factors = independent.union(aliases)
    ranking = payload.get("factorRanking")
    if (
        not isinstance(ranking, list)
        or len(ranking) != len(all_factors)
        or any(not isinstance(row, dict) for row in ranking)
        or {str(row.get("factor")) for row in ranking} != all_factors
        or any(row.get("policy_id") != FIXED_WEIGHTING_POLICY for row in ranking)
    ):
        raise ValueError("dashboard factorRanking does not cover the canonical factor set")
    validated_selected = _validate_ranking_guardrails(ranking, payload["config"])
    selected_rows = [row for row in ranking if row.get("selected") is True]
    if (
        len(selected_rows) != 1
        or selected_rows[0] is not validated_selected
        or selected_rows[0].get("factor") != best_factor
        or selected_rows[0].get("selection_eligible") is not True
        or selected_rows[0].get("rank") != 1
    ):
        raise ValueError("dashboard factorRanking best-factor selection is inconsistent")
    selected = selected_rows[0]

    independent_rows = [row for row in ranking if str(row["factor"]) in independent]
    reason_counts: dict[str, int] = {}
    for row in independent_rows:
        status = row.get("comparison_status")
        codes = row.get("exclusion_reason_codes")
        if status == "available":
            if codes != []:
                raise ValueError("available independent factor has exclusion reason codes")
        elif (
            not isinstance(codes, list)
            or not codes
            or not all(_required_text(code) for code in codes)
        ):
            raise ValueError("excluded independent factor has no exact reason code")
        else:
            for code in codes:
                reason_counts[str(code)] = reason_counts.get(str(code), 0) + 1
    if any(
        row.get("comparison_status") != "duplicate_alias"
        for row in ranking
        if str(row["factor"]) in aliases
    ):
        raise ValueError("diagnostic alias factor is not marked duplicate_alias")
    available_count = sum(row.get("comparison_status") == "available" for row in independent_rows)
    expected_accounting = {
        "version": 2,
        "independentFactorCount": len(independent),
        "expectedIndependentFactorCount": len(independent),
        "evaluatedIndependentFactorCount": len(independent_rows),
        "availableIndependentFactorCount": available_count,
        "excludedIndependentFactorCount": len(independent) - available_count,
        "missingIndependentFactorCount": 0,
        "diagnosticAliasFactorCount": len(aliases),
        "commonComparableFactorCount": available_count,
        "exclusionReasonCounts": dict(sorted(reason_counts.items())),
        "invariant": (
            "availableIndependentFactorCount + excludedIndependentFactorCount "
            "= expectedIndependentFactorCount"
        ),
    }
    accounting = payload.get("factorAccounting")
    if accounting != expected_accounting:
        raise ValueError("dashboard factorAccounting is inconsistent")

    decision = payload.get("factorSelectionDecision")
    dates = payload["performance"]["dates"]
    reconstructed_config = _reconstruct_run_config(payload)
    if (
        not isinstance(decision, dict)
        or decision.get("method") != "fixed_policy_factor_selection"
        or decision.get("version") != FACTOR_SELECTION_VERSION
        or decision.get("dynamicSelection") is not True
        or decision.get("weightingPolicyOptimized") is not False
        or decision.get("bestFactor") != best_factor
        or decision.get("weightingPolicy") != policy_id
        or decision.get("weightingPolicyVersion") != POLICY_REGISTRY[policy_id]["version"]
        or decision.get("guardrailProfile") != _absolute_guardrail_profile(reconstructed_config)
        or decision.get("tieBreakPolicy") != list(FACTOR_SELECTION_TIE_BREAK_POLICY)
        or decision.get("evaluationStart") != dates[1]
        or decision.get("evaluationEnd") != dates[-1]
        or decision.get("evaluationWindowDays") != len(dates) - 1
        or decision.get("minimumObservations") != reconstructed_config.min_evaluation_observations
        or decision.get("minimumValuationCoverage") != reconstructed_config.min_valuation_coverage
        or decision.get("minimumDailyRiskObservations")
        != reconstructed_config.min_daily_risk_observations
        or decision.get("factorAccounting") != accounting
        or decision.get("selectionEligibleFactorCount")
        != sum(row.get("selection_eligible") is True for row in ranking)
        or decision.get("reason") != payload.get("bestFactorReason")
    ):
        raise ValueError("dashboard factorSelectionDecision is inconsistent")
    score_parity = {
        "bestBaseCompositeScore": "base_composite_score",
        "bestExtremeEventPenaltyPoints": "extreme_event_penalty_points",
        "bestSelectionScore": "selection_score",
    }
    for decision_field, ranking_field in score_parity.items():
        _require_close(
            decision.get(decision_field),
            float(selected[ranking_field]),
            f"factorSelectionDecision.{decision_field}",
        )

    allocation = payload.get("allocationMethod")
    config = payload["config"]
    expected_parameters = {
        "topN": config["top_n"],
        "maxWeight": config["max_weight"],
        "rebalanceFrequency": config["rebalance_frequency"],
        "transactionCostBps": config["transaction_cost_bps"],
        "slippageBps": config["slippage_bps"],
        "factorScoreWeight": config["allocation_score_weight"],
        "liquidityWeight": config["allocation_liquidity_weight"],
        "marketCapWeight": config["allocation_market_cap_weight"],
        "rankFloor": config["allocation_rank_floor"],
        "marketCapMaximumAgeDays": config["market_cap_max_age_days"],
    }
    if (
        not isinstance(allocation, dict)
        or allocation.get("policyId") != policy_id
        or allocation.get("version") != POLICY_REGISTRY[policy_id]["version"]
        or allocation.get("fixed") is not True
        or allocation.get("parameters") != expected_parameters
    ):
        raise ValueError("dashboard allocationMethod is inconsistent")

    # Reuse the mature portfolio, history, transition, contribution, and factor
    # diagnostic validators through non-serialized aliases.
    compat = deepcopy(payload)
    compat.update(
        {
            "selectedFactor": best_factor,
            "selectedWeightingPolicy": policy_id,
            "selectedReason": payload["bestFactorReason"],
            "selectionDecision": decision,
            "gridAccounting": accounting,
            "factorPolicyRanking": ranking,
            "weightingPolicyRegistry": {
                "registryVersion": POLICY_REGISTRY_VERSION,
                "policies": POLICY_REGISTRY,
            },
            "currentResearchTarget": payload["bestFactorPortfolio"],
            "selectedBacktestHoldingHistory": payload["bestFactorBacktestHoldingHistory"],
            "currentTransition": payload["bestFactorTransition"],
        }
    )
    _validate_factor_diagnostics(compat, independent=independent, aliases=aliases)
    _validate_factor_portfolios(
        compat,
        factors=all_factors,
        selected=selected,
        as_of=str(payload["data"]["asOf"]),
    )
    target = _validate_current_target(
        compat,
        as_of=str(payload["data"]["asOf"]),
        selected=selected,
    )
    if payload.get("bestFactorPortfolio") != payload["factorPortfolios"].get(best_factor):
        raise ValueError("dashboard bestFactorPortfolio differs from factorPortfolios")
    held = _validate_backtest_held_portfolio(
        compat,
        as_of=str(payload["data"]["asOf"]),
        selected_factor=best_factor,
        selected_policy=policy_id,
    )
    _validate_selected_backtest_holding_history(
        compat,
        held=held,
        as_of=str(payload["data"]["asOf"]),
        selected_factor=best_factor,
        selected_policy=policy_id,
    )
    _validate_factor_holding_history_sidecar(
        compat,
        selected_history=compat["selectedBacktestHoldingHistory"],
    )
    _validate_current_transition(
        compat,
        held=held,
        target=target,
        as_of=str(payload["data"]["asOf"]),
    )
    _validate_contribution_diagnostics(compat, selected)
    return payload


def _summary(payload: dict[str, Any]) -> dict[str, Any]:
    selected = next(row for row in payload["factorRanking"] if row.get("selected") is True)
    target = payload["bestFactorPortfolio"]
    data = payload["data"]
    scope = payload["researchScope"]
    meta = payload["meta"]
    return {
        "schemaVersion": 5,
        "contract": "quant-research-summary",
        "contractVersion": 4,
        "projectId": "momentum-factor-lab",
        "resultKey": payload["resultKey"],
        "resultIdentity": payload["resultIdentity"],
        "generatedAt": payload["generatedAtUtc"],
        "dataAsOf": data["asOf"],
        "dataMode": data["mode"],
        "sourceLabel": data["sourceLabel"],
        "synthetic": data["synthetic"],
        "requestedCandidateCount": data["requestedCandidateCount"],
        "providerReturnedCandidateCount": data["providerReturnedCandidateCount"],
        "universeSize": data["inputSecurityCount"],
        "analyzedSecurityCount": data["analyzedSecurityCount"],
        "eligibleSecurityCount": data["latestEligibleSecurityCount"],
        "bestFactor": payload["bestFactor"],
        "weightingPolicy": payload["weightingPolicy"],
        "bestFactorReason": payload["bestFactorReason"],
        "factorSelectionDecision": payload["factorSelectionDecision"],
        "factorAccounting": payload["factorAccounting"],
        "weightingMethodology": payload["weightingMethodology"],
        "contributionDiagnostics": payload["contributionDiagnostics"],
        "allocationMethod": payload["allocationMethod"],
        "backtestHeldPortfolio": payload["backtestHeldPortfolio"],
        "bestFactorTransition": payload["bestFactorTransition"],
        "selectionScore": selected["selection_score"],
        "compositeScore": selected["composite_score"],
        "cagr": selected["cagr"],
        "annualReturn": selected["annual_return"],
        "volatility": selected["volatility"],
        "sharpe": selected["sharpe"],
        "sortino": selected["sortino"],
        "calmar": selected["calmar"],
        "maxDrawdown": selected["max_drawdown"],
        "cvar95": selected["cvar_95"],
        "winRate": selected["win_rate"],
        "annualizedTurnover": selected["annualized_turnover"],
        "annualizedCostDrag": selected["annualized_cost_drag"],
        "observations": selected["observations"],
        "actualExposureObservations": selected["actual_exposure_observations"],
        "valuationCoverageRatio": selected["valuation_coverage_ratio"],
        "dailyRiskObservations": selected["daily_risk_observations"],
        "portfolioStatus": target["status"],
        "portfolioSize": target["selectedSecurityCount"],
        "portfolioEligibleSecurityCount": target["eligibleSecurityCount"],
        "bestFactorPortfolio": target,
        "cashWeight": target["cashWeight"],
        "maxWeight": payload["config"]["max_weight"],
        "cashReasons": list(target.get("reasons", [])),
        "concentration": target["concentration"],
        "weights": target["weights"],
        "researchOnly": bool(scope.get("researchOnly", True)),
        "notInvestmentRecommendation": bool(scope.get("notInvestmentRecommendation", True)),
        "evidenceStatus": scope.get("evidenceStatus", "same_sample_descriptive"),
        "limitations": list(scope.get("limitations", [])),
        "runtimeSeconds": meta.get("runtimeSeconds"),
        "maxRssBytes": meta.get("maxRssBytes"),
        "page": "momentum-factor-lab",
    }


def dashboard_summary(source: AnalysisResult | dict[str, Any] | Path) -> dict[str, Any]:
    """Return the validated schema-v5 summary without writing site aliases."""

    return _summary(_load_payload(source))


def write_dashboard_site(
    source: AnalysisResult | dict[str, Any] | Path,
    site_dir: Path,
    *,
    title: str = DEFAULT_SITE_TITLE,
) -> dict[str, str]:
    payload = _load_payload(source)
    payload, sidecar_bytes = externalize_factor_holding_history_sidecar(payload)
    if sidecar_bytes is None:
        raise ValueError("dashboard site source has no embedded factor holding history sidecar")
    if len(sidecar_bytes) > MAX_FACTOR_HOLDING_HISTORY_SIDECAR_BYTES:
        raise ValueError(
            "dashboard factor holding history sidecar is "
            f"{len(sidecar_bytes):,} bytes; limit is "
            f"{MAX_FACTOR_HOLDING_HISTORY_SIDECAR_BYTES:,}"
        )
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_DASHBOARD_BYTES:
        raise ValueError(
            f"dashboard payload is {len(encoded):,} bytes; limit is {MAX_DASHBOARD_BYTES:,}"
        )
    if not WEB_ROOT.exists():
        raise FileNotFoundError(f"web templates missing: {WEB_ROOT}")
    assets_dir = site_dir / "assets"
    data_dir = site_dir / "data"
    assets_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    css_bytes = (WEB_ROOT / "styles.css").read_bytes()
    shared_nav_bytes = (WEB_ROOT / "shared-nav.css").read_bytes()
    js_bytes = (WEB_ROOT / "dashboard.js").read_bytes()
    asset_version = hashlib.sha256(css_bytes + js_bytes).hexdigest()[:12]
    shared_nav_version = hashlib.sha256(shared_nav_bytes).hexdigest()[:12]
    index = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    index = (
        index.replace("__TITLE__", title)
        .replace("__ASSET_VERSION__", asset_version)
        .replace("__SHARED_NAV_VERSION__", shared_nav_version)
    )

    index_path = site_dir / "index.html"
    css_path = assets_dir / "styles.css"
    shared_nav_path = assets_dir / "shared-nav.css"
    js_path = assets_dir / "dashboard.js"
    data_path = data_dir / "dashboard.json"
    summary_path = data_dir / "summary.json"
    sidecar_path = site_dir / str(payload["factorHoldingHistorySidecar"]["path"])
    index_path.write_text(index, encoding="utf-8")
    shutil.copyfile(WEB_ROOT / "styles.css", css_path)
    shutil.copyfile(WEB_ROOT / "shared-nav.css", shared_nav_path)
    shutil.copyfile(WEB_ROOT / "dashboard.js", js_path)
    data_path.write_bytes(encoded)
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_bytes(sidecar_bytes)
    summary_path.write_text(
        json.dumps(_summary(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "index": str(index_path),
        "css": str(css_path),
        "sharedNav": str(shared_nav_path),
        "js": str(js_path),
        "data": str(data_path),
        "factorHoldingHistory": str(sidecar_path),
        "summary": str(summary_path),
    }
