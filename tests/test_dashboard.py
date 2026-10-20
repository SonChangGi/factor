import hashlib
import json
import re
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from factor_lab.config import FIXED_WEIGHTING_POLICY, POLICY_REGISTRY
from factor_lab.dashboard import (
    MAX_DASHBOARD_BYTES,
    WEB_ROOT,
    _factor_sets,
    _load_payload,
    externalize_factor_holding_history_sidecar,
    validate_factor_holding_history_sidecar_bytes,
    write_dashboard_site,
)
from factor_lab.research_inputs import (
    LEGACY_RESEARCH_INPUTS_VERSION,
    TRADING_SESSIONS_PER_YEAR,
)
from factor_lab.identity import canonical_json_bytes
from factor_lab.workflow import (
    MAX_FACTOR_HOLDING_HISTORY_SIDECAR_BYTES,
    AnalysisResult,
    result_payload,
)


Payload = dict[str, Any]
PayloadMutation = Callable[[Payload], None]


def _best_row(payload: Payload) -> dict[str, Any]:
    return next(row for row in payload["factorRanking"] if row["selected"] is True)


def test_dashboard_accepts_schema_v5_fixed_method_result(
    demo_result: AnalysisResult,
) -> None:
    payload = result_payload(demo_result)
    loaded = _load_payload(payload)
    best = _best_row(loaded)

    assert loaded is payload
    assert loaded["schemaVersion"] == 5
    assert loaded["bestFactor"] == best["factor"]
    assert loaded["weightingPolicy"] == FIXED_WEIGHTING_POLICY == best["policy_id"]
    assert best["rank"] == 1.0
    assert loaded["factorSelectionDecision"]["weightingPolicyOptimized"] is False
    assert loaded["weightingMethodology"] == {
        "registryVersion": "weighting-policy-registry-v3",
        "policyId": FIXED_WEIGHTING_POLICY,
        "policy": POLICY_REGISTRY[FIXED_WEIGHTING_POLICY],
        "optimized": False,
    }
    for removed in (
        "selectedFactor",
        "selectedWeightingPolicy",
        "factorPolicyRanking",
        "gridAccounting",
        "currentResearchTarget",
        "portfolioPolicy",
        "policyDiagnostics",
    ):
        assert removed not in loaded


def test_dashboard_accepts_complete_legacy_v1_research_inputs(
    demo_result: AnalysisResult,
) -> None:
    payload = result_payload(demo_result)
    window_days = payload["researchInputs"]["evaluationWindowDays"]
    payload["researchInputs"] = {
        **payload["researchInputs"],
        "version": LEGACY_RESEARCH_INPUTS_VERSION,
        "evaluationYears": window_days // TRADING_SESSIONS_PER_YEAR,
    }

    assert _load_payload(payload) is payload


def test_dashboard_factor_accounting_is_complete_and_single_method(
    demo_result: AnalysisResult,
) -> None:
    payload = _load_payload(result_payload(demo_result))
    accounting = payload["factorAccounting"]
    ranking = payload["factorRanking"]

    assert len(ranking) == 64
    assert len({row["factor"] for row in ranking}) == 64
    assert {row["policy_id"] for row in ranking} == {FIXED_WEIGHTING_POLICY}
    assert accounting["expectedIndependentFactorCount"] == 61
    assert accounting["evaluatedIndependentFactorCount"] == 61
    assert accounting["missingIndependentFactorCount"] == 0
    assert (
        accounting["availableIndependentFactorCount"] + accounting["excludedIndependentFactorCount"]
        == accounting["expectedIndependentFactorCount"]
    )


def test_dashboard_validates_all_factor_portfolios_and_best_parity(
    demo_result: AnalysisResult,
) -> None:
    payload = _load_payload(result_payload(demo_result))
    portfolios = payload["factorPortfolios"]
    canonical_factors = {row["factor"] for row in payload["factorDefinitions"]}

    assert set(portfolios) == canonical_factors
    assert len(portfolios) == payload["meta"]["portfolioCount"] == 64
    assert payload["bestFactorPortfolio"] == portfolios[payload["bestFactor"]]
    assert all(
        portfolio["factor"] == factor
        and portfolio["weightingPolicyId"] == FIXED_WEIGHTING_POLICY
        and portfolio["weightingPolicyVersion"]
        == POLICY_REGISTRY[FIXED_WEIGHTING_POLICY]["version"]
        and portfolio["asOf"] == portfolio["signalDate"] == payload["data"]["asOf"]
        for factor, portfolio in portfolios.items()
    )


def test_dashboard_weight_rows_reconcile_fixed_formula_components(
    demo_result: AnalysisResult,
) -> None:
    payload = _load_payload(result_payload(demo_result))
    portfolio = payload["bestFactorPortfolio"]
    parameters = payload["allocationMethod"]["parameters"]

    assert parameters["factorScoreWeight"] == pytest.approx(0.70)
    assert parameters["liquidityWeight"] == pytest.approx(0.30)
    assert parameters["marketCapWeight"] == pytest.approx(0.0)
    assert parameters["rankFloor"] == pytest.approx(0.05)
    assert all(
        row["rawPolicyScore"]
        == pytest.approx(
            parameters["rankFloor"]
            + 0.70 * row["scoreComponent"]
            + 0.30 * row["liquidityComponent"]
        )
        for row in portfolio["weights"]
    )
    assert sum(row["weight"] for row in portfolio["weights"]) + portfolio[
        "cashWeight"
    ] == pytest.approx(1.0)


def test_dashboard_rejects_tampered_python_period_performance(
    demo_result: AnalysisResult,
) -> None:
    payload = deepcopy(result_payload(demo_result))
    best = payload["bestFactor"]
    payload["performance"]["periods"][0]["factors"][best]["cumulativeReturn"] = "bad"

    with pytest.raises(ValueError, match="cumulative return is invalid"):
        _load_payload(payload)


@pytest.mark.parametrize("symbol", ["SPY", "^IXIC", "QQQ"])
def test_dashboard_rejects_full_benchmark_curve_table_mismatch(
    demo_result: AnalysisResult,
    symbol: str,
) -> None:
    payload = deepcopy(result_payload(demo_result))
    performance = payload["performance"]
    full = next(period for period in performance["periods"] if period["key"] == "FULL")
    source_symbol = next(
        candidate
        for candidate, metrics in full["benchmarks"].items()
        if metrics["available"] is True
    )
    payload["data"]["comparisonBenchmarkAvailability"][symbol] = True
    performance["benchmarkCurves"][symbol] = deepcopy(performance["benchmarkCurves"][source_symbol])
    for period in performance["periods"]:
        period["benchmarks"][symbol] = deepcopy(period["benchmarks"][source_symbol])
    _load_payload(deepcopy(payload))

    full["benchmarks"][symbol]["cumulativeReturn"] += 0.01
    with pytest.raises(
        ValueError,
        match=rf"benchmark {re.escape(symbol)} FULL cumulative return",
    ):
        _load_payload(payload)


def test_dashboard_accepts_and_verifies_identity_transport(
    demo_result: AnalysisResult,
) -> None:
    payload = deepcopy(result_payload(demo_result))
    identity = payload["resultIdentity"]
    identity["canonicalKeyPartsJson"] = canonical_json_bytes(identity["keyParts"]).decode()
    assert _load_payload(payload) is payload

    payload["resultIdentity"]["canonicalKeyPartsJson"] = (
        f" {payload['resultIdentity']['canonicalKeyPartsJson']} "
    )
    with pytest.raises(ValueError, match="canonical transport"):
        _load_payload(payload)


def test_dashboard_requires_exact_factor_registry(
    demo_result: AnalysisResult,
) -> None:
    payload = result_payload(demo_result)
    payload["factorDefinitions"] = payload["factorDefinitions"][:-1]
    with pytest.raises(ValueError, match="canonical 64/61/3 registry"):
        _factor_sets(payload)


def test_dashboard_validates_factor_diagnostics_contract(
    demo_result: AnalysisResult,
) -> None:
    payload = _load_payload(result_payload(demo_result))
    diagnostics = payload["factorDiagnostics"]
    rank_ic = diagnostics["rankIc"]
    redundancy = diagnostics["redundancy"]
    aliases = {row["factor"] for row in diagnostics["scope"]["aliases"]}

    assert len(rank_ic["rows"]) == len(redundancy["rows"]) == 61
    assert not aliases & {row["factor"] for row in rank_ic["rows"]}
    assert rank_ic["horizonSessions"] == 21
    assert redundancy["eligiblePairCount"] <= 61 * 60 // 2
    assert any(row["factor"] == payload["bestFactor"] for row in rank_ic["rows"])


def test_dashboard_validates_best_factor_holding_history(
    demo_result: AnalysisResult,
) -> None:
    payload = _load_payload(result_payload(demo_result))
    history = payload["bestFactorBacktestHoldingHistory"]
    held = payload["backtestHeldPortfolio"]

    assert history["contractVersion"] == 1
    assert history["sessionCount"] == len(history["sessions"]) == 21
    assert history["factor"] == payload["bestFactor"]
    assert history["weightingPolicyId"] == FIXED_WEIGHTING_POLICY
    assert history["sessions"][-1]["cashWeight"] == held["cashWeight"]
    assert history["sessions"][-1]["lastSignalDate"] == held["lastSignalDate"]
    assert history["sessions"][-1]["lastExecutionDate"] == held["lastExecutionDate"]


def _alter_result_key(payload: Payload) -> None:
    payload["resultKey"] = "0" * 64


def _duplicate_factor_row(payload: Payload) -> None:
    payload["factorRanking"].append(deepcopy(payload["factorRanking"][0]))


def _alter_factor_accounting(payload: Payload) -> None:
    payload["factorAccounting"]["evaluatedIndependentFactorCount"] -= 1


def _alter_best_factor(payload: Payload) -> None:
    payload["bestFactor"] = next(
        row["factor"]
        for row in payload["factorRanking"]
        if row["factor"] != payload["bestFactor"] and row["comparison_status"] == "available"
    )


def _alter_methodology(payload: Payload) -> None:
    payload["weightingMethodology"]["policy"]["formula"] = "tampered"


def _alter_research_inputs(payload: Payload) -> None:
    payload["researchInputs"]["topN"] += 1


def _alter_factor_portfolio(payload: Payload) -> None:
    factor = next(
        factor for factor in payload["factorPortfolios"] if factor != payload["bestFactor"]
    )
    payload["factorPortfolios"][factor]["weights"][0]["weight"] += 0.01


def _alter_best_portfolio(payload: Payload) -> None:
    payload["bestFactorPortfolio"]["weights"][0]["rawPolicyScore"] += 0.01


def _alter_history(payload: Payload) -> None:
    payload["bestFactorBacktestHoldingHistory"]["sessions"].pop(0)


def _alter_transition(payload: Payload) -> None:
    payload["bestFactorTransition"]["modeledCostFraction"] += 0.01


def _alter_diagnostic(payload: Payload) -> None:
    payload["factorDiagnostics"]["rankIc"]["rows"][0]["mean"] = 2.0


def _add_removed_field(payload: Payload) -> None:
    payload["currentResearchTarget"] = deepcopy(payload["bestFactorPortfolio"])


@pytest.mark.parametrize(
    "mutate",
    [
        _alter_result_key,
        _duplicate_factor_row,
        _alter_factor_accounting,
        _alter_best_factor,
        _alter_methodology,
        _alter_research_inputs,
        _alter_factor_portfolio,
        _alter_best_portfolio,
        _alter_history,
        _alter_transition,
        _alter_diagnostic,
        _add_removed_field,
    ],
    ids=lambda mutate: mutate.__name__,
)
def test_dashboard_rejects_mutated_contracts(
    demo_result: AnalysisResult,
    mutate: PayloadMutation,
) -> None:
    payload = deepcopy(result_payload(demo_result))
    mutate(payload)
    with pytest.raises(ValueError):
        _load_payload(payload)


def test_dashboard_rejects_schema_v4_and_compatibility_fields(
    demo_result: AnalysisResult,
) -> None:
    payload = deepcopy(result_payload(demo_result))
    payload["schemaVersion"] = 4
    with pytest.raises(ValueError, match="schemaVersion 5"):
        _load_payload(payload)


def test_dashboard_summary_preserves_identity_and_best_allocation(
    demo_result: AnalysisResult,
    tmp_path: Path,
) -> None:
    paths = write_dashboard_site(demo_result, tmp_path / "site")
    payload = json.loads(Path(paths["data"]).read_text())
    summary = json.loads(Path(paths["summary"]).read_text())

    assert summary["schemaVersion"] == payload["schemaVersion"] == 5
    assert summary["contract"] == "quant-research-summary"
    assert summary["contractVersion"] == 4
    assert summary["resultIdentity"] == payload["resultIdentity"]
    assert summary["bestFactor"] == payload["bestFactor"]
    assert summary["weightingPolicy"] == FIXED_WEIGHTING_POLICY
    assert summary["bestFactorPortfolio"] == payload["bestFactorPortfolio"]
    assert summary["weights"] == payload["bestFactorPortfolio"]["weights"]
    assert summary["cashWeight"] == payload["bestFactorPortfolio"]["cashWeight"]
    assert summary["factorAccounting"] == payload["factorAccounting"]

    manifest = payload["factorHoldingHistorySidecar"]
    sidecar_bytes = Path(paths["factorHoldingHistory"]).read_bytes()
    assert manifest["contractVersion"] == 2
    assert manifest["storage"] == "external"
    assert "data" not in manifest
    assert manifest["bytes"] == len(sidecar_bytes)
    assert manifest["sha256"] == hashlib.sha256(sidecar_bytes).hexdigest()
    sidecar = validate_factor_holding_history_sidecar_bytes(payload, sidecar_bytes)
    assert set(sidecar["factors"]) == set(payload["factorPortfolios"])


def test_dashboard_external_sidecar_fails_closed_above_limit(
    demo_result: AnalysisResult,
) -> None:
    payload, sidecar_bytes = externalize_factor_holding_history_sidecar(result_payload(demo_result))
    assert sidecar_bytes is not None
    oversized = b"x" * (MAX_FACTOR_HOLDING_HISTORY_SIDECAR_BYTES + 1)
    payload["factorHoldingHistorySidecar"]["bytes"] = len(oversized)
    payload["factorHoldingHistorySidecar"]["sha256"] = hashlib.sha256(oversized).hexdigest()
    with pytest.raises(ValueError, match="external bytes exceed"):
        validate_factor_holding_history_sidecar_bytes(payload, oversized)


def test_dashboard_path_input_assets_and_size_limits(
    demo_result: AnalysisResult,
    tmp_path: Path,
) -> None:
    source = tmp_path / "result.json"
    source.write_text(json.dumps(result_payload(demo_result), ensure_ascii=False))
    paths = write_dashboard_site(source, tmp_path / "site", title="Fixed Method Test")
    written = json.loads(Path(paths["data"]).read_text())
    index = Path(paths["index"]).read_text()

    assert "Fixed Method Test" in index
    assert "__TITLE__" not in index
    assert "__ASSET_VERSION__" not in index
    assert "__SHARED_NAV_VERSION__" not in index
    assert written["schemaVersion"] == 5
    assert Path(paths["css"]).read_bytes() == (WEB_ROOT / "styles.css").read_bytes()
    assert Path(paths["sharedNav"]).read_bytes() == (WEB_ROOT / "shared-nav.css").read_bytes()
    assert Path(paths["js"]).read_bytes() == (WEB_ROOT / "dashboard.js").read_bytes()
    assert MAX_DASHBOARD_BYTES == 5_500_000
    assert Path(paths["data"]).stat().st_size < MAX_DASHBOARD_BYTES
    assert Path(paths["factorHoldingHistory"]).stat().st_size < (
        MAX_FACTOR_HOLDING_HISTORY_SIDECAR_BYTES
    )
