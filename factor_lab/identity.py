from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import rfc8785

from .config import (
    ABSOLUTE_GUARDRAIL_VERSION,
    ANALYSIS_CACHE_VERSION,
    FACTOR_SELECTION_VERSION,
    POLICY_REGISTRY,
    POLICY_REGISTRY_VERSION,
    RunConfig,
)
from .data import MarketData
from .factors import factor_definition_sha256


RESULT_IDENTITY_VERSION = "momentum-result-identity-v1"
CANONICAL_JSON_VERSION = "rfc8785-jcs-v1"
CONTRIBUTION_DIAGNOSTIC_VERSION = "realized-security-contribution-v1"

_NON_RESULT_CONFIG_FIELDS = {
    "output_dir",
    "site_dir",
    "cache_dir",
    "export_input_snapshot",
    "market_cache_max_age_hours",
    "refresh_market_data",
    "require_current_session",
    "price_chunk_size",
    "yahoo_chart_fallback_limit",
    "nasdaq_fallback_limit",
    "stooq_fallback_limit",
    "finance_datareader_fallback_limit",
    "retry_count",
    "retry_backoff_seconds",
    "sec_user_agent",
}

_ENGINE_SOURCE_FILES = (
    "advanced_factors.py",
    "backtest.py",
    "config.py",
    "data.py",
    "factors.py",
    "identity.py",
    "metrics.py",
    "market_cap.py",
    "portfolio.py",
    "workflow.py",
)


def _json_value(value: object) -> object:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def canonical_json_bytes(value: object) -> bytes:
    """Serialize I-JSON with the cross-language RFC 8785 JCS contract."""

    return rfc8785.dumps(_json_value(value))


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def normalized_research_inputs(config: RunConfig) -> dict[str, object]:
    """Return every result-affecting input without output or retry plumbing."""

    data = config.to_dict()
    for field in _NON_RESULT_CONFIG_FIELDS:
        data.pop(field, None)
    normalized = _json_value(dict(sorted(data.items())))
    if not isinstance(normalized, dict):  # pragma: no cover - construction invariant
        raise TypeError("normalized research inputs must be an object")
    return normalized


def policy_definition_sha256() -> str:
    package_root = Path(__file__).resolve().parent
    payload = {
        "registryVersion": POLICY_REGISTRY_VERSION,
        "registry": POLICY_REGISTRY,
        "implementationSources": {
            name: hashlib.sha256((package_root / name).read_bytes()).hexdigest()
            for name in ("portfolio.py", "backtest.py")
        },
    }
    return canonical_sha256(payload)


def selection_spec_sha256(config: RunConfig) -> str:
    payload = {
        "factorSelectionVersion": FACTOR_SELECTION_VERSION,
        "absoluteGuardrailVersion": ABSOLUTE_GUARDRAIL_VERSION,
        "contributionDiagnosticVersion": CONTRIBUTION_DIAGNOSTIC_VERSION,
        "scoreWeights": config.score_weights,
        "scoreWinsorLower": config.score_winsor_lower,
        "scoreWinsorUpper": config.score_winsor_upper,
        "minimumObservations": config.min_evaluation_observations,
        "minimumValuationCoverage": config.min_valuation_coverage,
        "minimumDailyRiskObservations": config.min_daily_risk_observations,
        "guardrails": {
            "minimumSharpe": config.selection_min_sharpe,
            "maximumDrawdownMagnitude": config.selection_max_drawdown,
            "maximumAnnualizedCostDrag": config.selection_max_annualized_cost_drag,
            "minimumEffectiveNames": config.selection_min_effective_names,
            "maximumTargetHhi": config.selection_max_target_hhi,
            "maximumTargetWeight": config.selection_max_target_weight,
            "maximumAbsoluteSecurityObservationContribution": (
                config.selection_max_abs_security_day_contribution
            ),
            "maximumSecurityAbsoluteContributionShare": (
                config.selection_max_security_absolute_contribution_share
            ),
            "maximumLeaveOneSecurityCagrDelta": (
                config.selection_max_leave_one_security_cagr_delta
            ),
            "extremeEventAction": config.selection_extreme_event_action,
            "extremeEventPenaltyPoints": config.selection_extreme_event_penalty_points,
        },
    }
    return canonical_sha256(payload)


def engine_sha256() -> str:
    package_root = Path(__file__).resolve().parent
    return canonical_sha256(
        {
            name: hashlib.sha256((package_root / name).read_bytes()).hexdigest()
            for name in _ENGINE_SOURCE_FILES
        }
    )


def market_snapshot_identity(market: MarketData) -> dict[str, object]:
    return {
        "sourceMode": market.source_mode,
        "sourceLabel": market.source_label,
        "provider": market.provider,
        "priceBasis": market.price_basis,
        "volumeBasis": market.volume_basis,
        "rawCloseProxySymbolCount": market.raw_close_proxy_symbol_count,
        "requestedThrough": market.requested_through,
        "dataAsOf": market.as_of.date().isoformat(),
        "inputSha256": dict(sorted(market.input_sha256.items())),
        "requestedCandidateCount": market.requested_candidate_count,
        "providerReturnedCandidateCount": market.provider_returned_candidate_count,
        "analyzedSecurityCount": len(market.candidate_symbols),
        "candidateSymbolsSha256": canonical_sha256(list(market.candidate_symbols)),
        "comparisonSymbols": list(market.comparison_symbols),
        "comparisonPricesSha256": market.input_sha256.get("comparisonPrices"),
    }


def build_result_identity(config: RunConfig, market: MarketData) -> dict[str, object]:
    raw_key_parts = {
        "identityVersion": RESULT_IDENTITY_VERSION,
        "canonicalJsonVersion": CANONICAL_JSON_VERSION,
        "analysisCacheVersion": ANALYSIS_CACHE_VERSION,
        "normalizedInputs": normalized_research_inputs(config),
        "marketSnapshot": market_snapshot_identity(market),
        "factorDefinitionSha256": factor_definition_sha256(),
        "policyDefinitionSha256": policy_definition_sha256(),
        "selectionSpecSha256": selection_spec_sha256(config),
        "engineSha256": engine_sha256(),
    }
    key_parts = _json_value(raw_key_parts)
    if not isinstance(key_parts, dict):  # pragma: no cover - construction invariant
        raise TypeError("result identity keyParts must be an object")
    return {
        "identityVersion": RESULT_IDENTITY_VERSION,
        "resultKey": canonical_sha256(key_parts),
        "keyParts": key_parts,
    }


def analysis_cache_path(config: RunConfig, result_key: str) -> Path:
    if len(result_key) != 64 or any(
        character not in "0123456789abcdef" for character in result_key
    ):
        raise ValueError("result_key must be a lowercase SHA-256 digest")
    return config.cache_dir / "analysis" / ANALYSIS_CACHE_VERSION / f"{result_key}.json"


def load_analysis_cache(
    config: RunConfig,
    identity: dict[str, object],
) -> dict[str, Any] | None:
    result_key = str(identity["resultKey"])
    path = analysis_cache_path(config, result_key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    observed = payload.get("resultIdentity")
    if observed != identity:
        return None
    if str(observed.get("resultKey")) != path.stem:
        return None
    return payload


def write_analysis_cache(
    config: RunConfig,
    identity: dict[str, object],
    payload: dict[str, Any],
) -> Path:
    if payload.get("resultIdentity") != identity:
        raise ValueError("payload resultIdentity does not match the cache identity")
    path = analysis_cache_path(config, str(identity["resultKey"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_bytes(canonical_json_bytes(payload))
    temporary.replace(path)
    return path
