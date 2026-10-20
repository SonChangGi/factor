import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from factor_lab.config import WEIGHTING_POLICIES
from factor_lab.identity import canonical_json_bytes
from factor_lab.workflow import (
    FACTOR_DIAGNOSTICS_CONTRACT_VERSION,
    FACTOR_DIAGNOSTICS_RANK_IC_HORIZON_SESSIONS,
    FACTOR_DIAGNOSTICS_REDUNDANCY_THRESHOLD,
    FACTOR_HOLDING_HISTORY_SIDECAR_CONTRACT,
    MAX_FACTOR_HOLDING_HISTORY_SIDECAR_BYTES,
    SELECTED_HOLDING_HISTORY_SESSION_COUNT,
    SELECTED_HOLDING_HISTORY_WEIGHT_TIMING,
    AnalysisResult,
    _factor_rank_ic_diagnostic_row,
    _factor_holding_history_sidecar_manifest,
    _selected_backtest_holding_history_payload,
    result_payload,
    write_result_json,
)


def test_result_json_persists_schema_v5_fixed_method_and_identity(
    demo_result: AnalysisResult,
) -> None:
    path = write_result_json(demo_result)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert path.suffix == ".json"
    assert payload["schemaVersion"] == 5
    assert payload["resultKey"] == payload["resultIdentity"]["resultKey"]
    assert len(payload["resultKey"]) == 64
    assert payload["bestFactor"] == demo_result.selected_factor
    assert payload["weightingPolicy"] == demo_result.selected_policy
    assert payload["meta"]["factorCount"] == 64
    assert payload["meta"]["independentFactorCount"] == 61
    assert payload["meta"]["aliasFactorCount"] == 3
    assert payload["meta"]["factorRunCount"] == 64
    assert payload["meta"]["purpose"] == (
        "input_driven_momentum_factor_comparison_with_fixed_weighting"
    )
    assert len(payload["meta"]["factorDefinitionSha256"]) == 64
    assert len(payload["meta"]["policyDefinitionSha256"]) == 64
    assert len(payload["meta"]["selectionSpecSha256"]) == 64
    assert len(payload["factorRanking"]) == 64
    assert "factorPolicyRanking" not in payload
    assert "currentResearchTarget" not in payload
    assert "selectedWeightingPolicy" not in payload
    assert "policyFactorMetrics" not in payload
    assert "modelPortfolio" not in payload
    assert set(payload["factorPortfolios"]) == set(demo_result.factor_scores)
    assert payload["data"]["inputSha256"] == demo_result.market_data.input_sha256
    assert payload["data"]["analyzedSymbols"] == demo_result.market_data.candidate_symbols
    assert payload["priceSources"] == demo_result.market_data.price_sources.to_dict(
        orient="records"
    )
    assert payload["sourceHealth"] == demo_result.market_data.data_sources.to_dict(orient="records")
    assert payload["researchScope"]["researchOnly"] is True
    assert payload["researchScope"]["notInvestmentRecommendation"] is True
    assert len(payload["researchScope"]["limitations"]) >= 3
    assert payload["researchInputs"]["evaluationWindowDays"] == 756
    selected = next(row for row in payload["factorRanking"] if row["selected"])
    assert selected["min_target_effective_names"] <= selected["median_target_effective_names"]
    assert selected["max_target_hhi"] >= selected["median_target_hhi"]
    assert selected["current_target_effective_names"] == pytest.approx(
        payload["bestFactorPortfolio"]["concentration"]["effectiveNames"]
    )
    assert selected["current_target_hhi"] == pytest.approx(
        payload["bestFactorPortfolio"]["concentration"]["riskySleeveHhi"]
    )
    assert selected["current_target_max_weight"] == pytest.approx(
        payload["bestFactorPortfolio"]["concentration"]["maxWeight"]
    )
    assert not list(Path(demo_result.config.output_dir).glob("*.pdf"))
    assert not list(Path(demo_result.config.output_dir).glob("*.xlsx"))


def test_factor_diagnostics_cover_all_independent_factors_and_exclude_aliases(
    demo_result: AnalysisResult,
) -> None:
    payload = result_payload(demo_result)
    diagnostics = payload["factorDiagnostics"]
    definitions = payload["factorDefinitions"]
    independent = {row["factor"] for row in definitions if row["compatibility_alias_of"] is None}
    aliases = {
        row["factor"]: row["compatibility_alias_of"]
        for row in definitions
        if row["compatibility_alias_of"] is not None
    }

    assert diagnostics["contractVersion"] == FACTOR_DIAGNOSTICS_CONTRACT_VERSION
    assert diagnostics["scope"] == {
        "factorCount": 64,
        "independentFactorCount": 61,
        "diagnosticAliasCount": 3,
        "aliasHandling": "excluded_from_rankings",
        "aliases": [
            {"factor": factor, "canonicalFactor": aliases[factor]} for factor in sorted(aliases)
        ],
    }
    rank_ic = diagnostics["rankIc"]
    rank_rows = rank_ic["rows"]
    assert rank_ic["horizonSessions"] == FACTOR_DIAGNOSTICS_RANK_IC_HORIZON_SESSIONS
    assert rank_ic["requestedSignalSessions"] == len(rank_ic["signalDates"]) == 756
    assert rank_ic["overlapping"] is True
    assert {row["factor"] for row in rank_rows} == independent
    assert not aliases.keys() & {row["factor"] for row in rank_rows}
    assert [row["rank"] for row in rank_rows] == list(range(1, 62))
    assert all(
        row["observations"] <= 756 - FACTOR_DIAGNOSTICS_RANK_IC_HORIZON_SESSIONS
        and row["horizonSessions"] == FACTOR_DIAGNOSTICS_RANK_IC_HORIZON_SESSIONS
        and row["latestFiniteCount"] <= payload["data"]["latestEligibleSecurityCount"]
        for row in rank_rows
    )
    best_ic = next(row for row in rank_rows if row["factor"] == payload["bestFactor"])
    assert best_ic["available"] is True
    assert best_ic["standardDeviation"] >= 0.0

    redundancy = diagnostics["redundancy"]
    redundancy_rows = redundancy["rows"]
    assert redundancy["thresholdAbs"] == pytest.approx(FACTOR_DIAGNOSTICS_REDUNDANCY_THRESHOLD)
    assert redundancy["diagnosticDate"] == payload["data"]["asOf"]
    assert {row["factor"] for row in redundancy_rows} == independent
    assert (
        sum(row["validPeerCount"] for row in redundancy_rows) == 2 * redundancy["eligiblePairCount"]
    )
    assert (
        sum(row["highCorrPeerCount"] for row in redundancy_rows)
        == 2 * redundancy["highRedundancyPairCount"]
    )
    top_pairs = redundancy["topPairs"]
    assert len(top_pairs) == 10
    assert len({(row["leftFactor"], row["rightFactor"]) for row in top_pairs}) == 10
    assert all(
        row["leftFactor"] < row["rightFactor"]
        and row["absCorr"] == pytest.approx(abs(row["signedCorr"]))
        and row["commonSecurityCount"] >= 3
        for row in top_pairs
    )


def test_rank_ic_diagnostic_uses_pairwise_ranks_and_exact_21_session_metadata() -> None:
    dates = pd.bdate_range("2026-01-02", periods=25)
    columns = ["A", "B", "C", "D"]
    panel = pd.DataFrame(
        [[1.0, 2.0, 3.0, 4.0] for _ in dates],
        index=dates,
        columns=columns,
    )
    future = pd.DataFrame(float("nan"), index=dates, columns=columns)
    future.loc[dates[:4]] = [float("nan"), 20.0, 30.0, 40.0]

    row = _factor_rank_ic_diagnostic_row(
        factor="fixture",
        category="fixture",
        panel=panel,
        signal_dates=dates,
        forward_returns=future,
        latest_date=dates[-1],
    )

    assert row["available"] is True
    assert row["horizonSessions"] == 21
    assert row["observations"] == 4
    assert row["mean"] == pytest.approx(1.0)
    assert row["median"] == pytest.approx(1.0)
    assert row["standardDeviation"] == pytest.approx(0.0)
    assert row["positiveRate"] == pytest.approx(1.0)
    assert row["startDate"] == dates[0].date().isoformat()
    assert row["endDate"] == dates[3].date().isoformat()
    assert row["minimumSecurityCount"] == 3
    assert row["averageSecurityCount"] == pytest.approx(3.0)
    assert row["maximumSecurityCount"] == 3
    assert row["latestFiniteCount"] == 4


def test_fixed_method_factor_registry_and_accounting_survive_serialization(
    demo_result: AnalysisResult,
) -> None:
    payload = result_payload(demo_result)
    factors = set(payload["factorPortfolios"])
    observed = {(row["policy_id"], row["factor"]) for row in payload["factorRanking"]}

    assert observed == {
        (policy_id, factor) for policy_id in WEIGHTING_POLICIES for factor in factors
    }
    methodology = payload["weightingMethodology"]
    assert methodology["policyId"] == WEIGHTING_POLICIES[0]
    assert methodology["optimized"] is False
    assert methodology["policy"]["implementationId"]
    accounting = payload["factorAccounting"]
    assert accounting["expectedIndependentFactorCount"] == 61
    assert accounting["missingIndependentFactorCount"] == 0
    assert (
        accounting["availableIndependentFactorCount"] + accounting["excludedIndependentFactorCount"]
        == accounting["expectedIndependentFactorCount"]
    )
    assert payload["selectionMethod"]["weightingPolicyOptimized"] is False
    assert payload["selectionMethod"]["fixedWeightingPolicy"] == WEIGHTING_POLICIES[0]
    assert payload["allocationMethod"]["fixed"] is True


def test_best_factor_fixed_method_portfolio_and_performance_reconcile(
    demo_result: AnalysisResult,
) -> None:
    payload = result_payload(demo_result)
    best_factor = payload["bestFactor"]
    best_policy = payload["weightingPolicy"]
    best_rows = [row for row in payload["factorRanking"] if row["selected"]]
    portfolio = payload["bestFactorPortfolio"]

    assert len(best_rows) == 1
    ranking = best_rows[0]
    assert ranking["rank"] == 1
    assert ranking["comparison_status"] == "available"
    assert ranking["selection_eligible"] is True
    assert ranking["factor"] == best_factor
    assert ranking["policy_id"] == best_policy
    assert payload["weightingMethodology"]["policyId"] == best_policy
    assert payload["performance"]["weightingPolicyId"] == best_policy
    assert portfolio == payload["factorPortfolios"][best_factor]
    assert portfolio["factor"] == best_factor
    assert portfolio["weightingPolicyId"] == best_policy
    assert portfolio["asOf"] == portfolio["signalDate"] == payload["data"]["asOf"]
    assert sum(row["weight"] for row in portfolio["weights"]) + portfolio[
        "cashWeight"
    ] == pytest.approx(1.0)
    assert len({row["symbol"] for row in portfolio["weights"]}) == len(portfolio["weights"])
    assert payload["contributionDiagnostics"]["observedReturnsPreserved"] is True
    assert payload["contributionDiagnostics"]["reoptimized"] is False


def test_best_backtest_history_is_sparse_recent_and_exactly_reconciled(
    demo_result: AnalysisResult,
) -> None:
    payload = result_payload(demo_result)
    best_factor = payload["bestFactor"]
    best_backtest = demo_result.backtests[best_factor]
    history = payload["bestFactorBacktestHoldingHistory"]
    held = payload["backtestHeldPortfolio"]

    assert not best_backtest.weights.empty
    assert not best_backtest.pre_trade_weights.empty
    assert len(best_backtest.cash_weights) == len(best_backtest.weights)
    assert all(
        backtest.weights.empty
        for factor, backtest in demo_result.backtests.items()
        if factor != best_factor
    )
    assert set(demo_result.factor_holding_histories) == set(demo_result.factor_scores)
    assert all(
        factor_history["weightingPolicyId"] == payload["weightingPolicy"]
        and [session["date"] for session in factor_history["sessions"]]
        == payload["performance"]["dates"][-SELECTED_HOLDING_HISTORY_SESSION_COUNT:]
        for factor_history in demo_result.factor_holding_histories.values()
    )
    assert history["contractVersion"] == 1
    assert history["factor"] == best_factor
    assert history["weightingPolicyId"] == payload["weightingPolicy"]
    assert history["weightTiming"] == SELECTED_HOLDING_HISTORY_WEIGHT_TIMING
    assert history["sessionCount"] == SELECTED_HOLDING_HISTORY_SESSION_COUNT
    assert len(history["sessions"]) == SELECTED_HOLDING_HISTORY_SESSION_COUNT
    assert [session["date"] for session in history["sessions"]] == payload["performance"]["dates"][
        -SELECTED_HOLDING_HISTORY_SESSION_COUNT:
    ]
    assert history["startDate"] == history["sessions"][0]["date"]
    assert history["endDate"] == history["sessions"][-1]["date"] == payload["data"]["asOf"]
    assert all(
        len(session["weights"]) <= demo_result.config.top_n
        and sum(row["weight"] for row in session["weights"]) + session["cashWeight"]
        == pytest.approx(1.0)
        for session in history["sessions"]
    )
    expected_final_weights = [
        {
            "rank": row["rank"],
            "symbol": row["symbol"],
            "name": row["name"],
            "weight": row["weight"],
        }
        for row in held["weights"]
    ]
    final_session = history["sessions"][-1]
    assert final_session["weights"] == expected_final_weights
    assert final_session["cashWeight"] == held["cashWeight"]
    assert final_session["lastSignalDate"] == held["lastSignalDate"]
    assert final_session["lastExecutionDate"] == held["lastExecutionDate"]

    sidecar_manifest = payload["factorHoldingHistorySidecar"]
    sidecar = sidecar_manifest["data"]
    encoded = canonical_json_bytes(sidecar)
    assert sidecar_manifest["contract"] == FACTOR_HOLDING_HISTORY_SIDECAR_CONTRACT
    assert sidecar_manifest["storage"] == "embedded"
    assert sidecar_manifest["bytes"] == len(encoded)
    assert sidecar_manifest["sha256"] == hashlib.sha256(encoded).hexdigest()
    assert sidecar["dates"] == payload["performance"]["dates"][-21:]
    assert set(sidecar["factors"]) == set(demo_result.factor_scores)
    assert sidecar["factorCount"] == 64
    assert sidecar["independentFactorCount"] == 61
    assert sidecar["diagnosticFactorCount"] == 3


def test_factor_holding_history_sidecar_builder_fails_closed_above_public_limit(
    demo_result: AnalysisResult,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oversized = b"x" * (MAX_FACTOR_HOLDING_HISTORY_SIDECAR_BYTES + 1)
    monkeypatch.setattr(
        "factor_lab.workflow.canonical_json_bytes",
        lambda _value: oversized,
    )

    with pytest.raises(
        ValueError,
        match=rf"limit is {MAX_FACTOR_HOLDING_HISTORY_SIDECAR_BYTES:,}",
    ):
        _factor_holding_history_sidecar_manifest(demo_result)


def test_post_close_history_uses_next_session_start_weights_and_final_ending_weights() -> None:
    dates = pd.bdate_range(end="2026-07-10", periods=21)
    weights = pd.DataFrame(0.0, index=dates, columns=["OLD", "NEW"])
    weights.loc[:, "OLD"] = 0.6
    weights.loc[:, "NEW"] = 0.4
    execution_date = pd.Timestamp("2026-07-01")
    next_date = dates[dates.get_loc(execution_date) + 1]
    weights.loc[next_date:, "OLD"] = 0.2
    weights.loc[next_date:, "NEW"] = 0.8
    ending_weights = pd.Series({"OLD": 0.3, "NEW": 0.7}, dtype=float)
    statuses = pd.Series("none", index=dates, dtype=object)
    statuses.loc[execution_date] = "executed"
    backtest = SimpleNamespace(
        weights=weights,
        pre_trade_weights=weights.copy(),
        cash_weights=pd.Series(0.0, index=dates, dtype=float),
        ending_weights=ending_weights,
        ending_cash_weight=0.0,
        execution_statuses=statuses,
        signal_dates=pd.Series(
            {execution_date: pd.Timestamp("2026-06-30")},
            dtype="datetime64[ns]",
        ),
        valuation_available=pd.Series(True, index=dates, dtype=bool),
    )
    result = SimpleNamespace(
        selected_factor="fixture_factor",
        selected_policy="fixture_policy",
        backtests={"fixture_factor": backtest},
        market_data=SimpleNamespace(
            universe=pd.DataFrame({"symbol": ["OLD", "NEW"], "name": ["Old Name", "New Name"]})
        ),
    )

    history = _selected_backtest_holding_history_payload(result)
    execution_session = next(
        session for session in history["sessions"] if session["date"] == "2026-07-01"
    )
    final_session = history["sessions"][-1]

    assert execution_session["executionStatus"] == "executed"
    assert execution_session["lastSignalDate"] == "2026-06-30"
    assert execution_session["lastExecutionDate"] == "2026-07-01"
    assert {row["symbol"]: row["weight"] for row in execution_session["weights"]} == {
        "OLD": 0.2,
        "NEW": 0.8,
    }
    assert final_session["date"] == "2026-07-10"
    assert {row["symbol"]: row["weight"] for row in final_session["weights"]} == {
        "OLD": 0.3,
        "NEW": 0.7,
    }


def test_current_transition_uses_cash_inclusive_half_l1_and_one_cost_charge(
    demo_result: AnalysisResult,
) -> None:
    payload = result_payload(demo_result)
    held = payload["backtestHeldPortfolio"]
    target = payload["bestFactorPortfolio"]
    transition = payload["bestFactorTransition"]
    held_weights = {row["symbol"]: row["weight"] for row in held["weights"]}
    target_weights = {row["symbol"]: row["weight"] for row in target["weights"]}
    symbols = set(held_weights) | set(target_weights)
    expected_turnover = 0.5 * (
        sum(
            abs(target_weights.get(symbol, 0.0) - held_weights.get(symbol, 0.0))
            for symbol in symbols
        )
        + abs(target["cashWeight"] - held["cashWeight"])
    )

    assert transition["asOf"] == payload["data"]["asOf"]
    assert transition["targetSignalDate"] == target["signalDate"]
    assert transition["actualNextClosePretradeDriftKnown"] is False
    assert transition["turnoverFormula"] == (
        "0.5*(sum_abs_target_minus_pretrade_stock+abs_target_minus_pretrade_cash)"
    )
    assert transition["costFormula"] == "one_way_turnover*total_cost_bps/10000"
    assert transition["targetCashWeight"] == pytest.approx(target["cashWeight"])
    assert transition["totalCostBps"] == pytest.approx(payload["config"]["total_cost_bps"])
    if transition["valuationAvailable"]:
        assert transition["oneWayTurnover"] == pytest.approx(expected_turnover)
        assert transition["modeledCostFraction"] == pytest.approx(
            expected_turnover * payload["config"]["total_cost_bps"] / 10_000.0
        )
    else:
        assert transition["oneWayTurnover"] is None
        assert transition["modeledCostFraction"] is None


def test_data_mode_and_requested_to_eligible_funnel_are_explicit(
    demo_result: AnalysisResult,
) -> None:
    data = result_payload(demo_result)["data"]
    counts = [
        data["requestedCandidateCount"],
        data["providerReturnedCandidateCount"],
        data["inputSecurityCount"],
        data["analyzedSecurityCount"],
        data["latestEligibleSecurityCount"],
    ]

    assert data["mode"] == "demo"
    assert data["synthetic"] is True
    assert all(isinstance(value, int) and value >= 0 for value in counts)
    assert counts == sorted(counts, reverse=True)
    assert data["inputSecurityCount"] == data["analyzedSecurityCount"] == 50


def test_all_performance_curves_share_the_fixed_policy_dates(
    demo_result: AnalysisResult,
) -> None:
    payload = result_payload(demo_result)
    performance = payload["performance"]
    dates = performance["dates"]

    assert performance["weightingPolicyId"] == payload["weightingPolicy"]
    assert len(dates) == demo_result.config.evaluation_window_days + 1
    assert set(performance["factorCurves"]) == set(demo_result.factor_scores)
    assert all(len(curve) == len(dates) for curve in performance["factorCurves"].values())


def test_performance_curve_includes_the_first_evaluation_return(
    demo_result: AnalysisResult,
) -> None:
    payload = result_payload(demo_result)
    performance = payload["performance"]
    dates = pd.DatetimeIndex(performance["dates"])
    selected = payload["bestFactor"]
    equity = demo_result.backtests[selected].equity
    evaluation_start = dates[1]
    base = float(equity.loc[dates[0]])

    curve = performance["factorCurves"][selected]
    assert curve[0] == pytest.approx(1.0)
    assert curve[1] == pytest.approx(float(equity.loc[evaluation_start]) / base)
    assert curve[-1] == pytest.approx(float(equity.loc[dates[-1]]) / base)
    ranking = next(row for row in payload["factorRanking"] if row["selected"] is True)
    implied_total_return = (1.0 + ranking["cagr"]) ** (ranking["calendar_observations"] / 252.0)
    assert curve[-1] == pytest.approx(implied_total_return)


def test_selection_method_copy_uses_the_actual_public_config(
    demo_result: AnalysisResult,
) -> None:
    payload = result_payload(demo_result)
    config = payload["config"]

    assert config["score_winsor_lower"] == pytest.approx(0.05)
    assert config["score_winsor_upper"] == pytest.approx(0.95)
    assert config["stability_periods"] == 3


def test_python_period_performance_uses_exact_boundaries_and_explicit_comparators(
    demo_result: AnalysisResult,
) -> None:
    payload = result_payload(demo_result)
    performance = payload["performance"]
    selected = payload["bestFactor"]
    comparison_order = ["SPY", "^IXIC", "QQQ"]

    assert performance["contractVersion"] == "python-period-performance-v1"
    assert performance["benchmarkOrder"] == comparison_order
    assert list(performance["benchmarkCurves"]) == comparison_order
    assert performance["benchmarkCurve"] == performance["benchmarkCurves"]["SPY"]
    assert payload["data"]["chartBenchmark"] == "^IXIC"
    assert payload["data"]["additionalComparisonBenchmarks"] == ["QQQ"]
    assert list(payload["data"]["comparisonBenchmarkAvailability"]) == comparison_order

    periods = {period["key"]: period for period in performance["periods"]}
    assert list(periods) == ["1W", "1M", "3M", "6M", "1Y", "YTD", "FULL"]
    assert all(
        set(period["factors"]) == set(demo_result.factor_scores) for period in periods.values()
    )
    assert all(list(period["benchmarks"]) == comparison_order for period in periods.values())

    one_week = periods["1W"]
    point_dates = demo_result.market_data.prices.index[-6:]
    equity = demo_result.backtests[selected].equity.reindex(point_dates)
    best_metrics = one_week["factors"][selected]
    assert one_week["startDate"] == point_dates[0].date().isoformat()
    assert one_week["endDate"] == point_dates[-1].date().isoformat()
    assert one_week["returnObservationCount"] == 5
    assert best_metrics["basis"] == "net_of_costs_strategy"
    assert best_metrics["returnObservationCount"] <= 5
    assert best_metrics["cumulativeReturn"] == pytest.approx(
        float(equity.iloc[-1] / equity.iloc[0] - 1.0)
    )

    full = periods["FULL"]
    assert full["startDate"] == performance["dates"][0]
    assert full["endDate"] == performance["dates"][-1]
    assert full["returnObservationCount"] == len(performance["dates"]) - 1
    for symbol, available in payload["data"]["comparisonBenchmarkAvailability"].items():
        benchmark_metrics = one_week["benchmarks"][symbol]
        assert benchmark_metrics["basis"] == "adjusted_close_buy_and_hold"
        if available:
            assert benchmark_metrics["available"] is True
            assert benchmark_metrics["unavailableReason"] is None
        else:
            assert benchmark_metrics["available"] is False
            assert benchmark_metrics["unavailableReason"] == "comparison_price_unavailable"


def test_payload_is_compact_enough_for_static_web(demo_result: AnalysisResult) -> None:
    encoded = json.dumps(
        result_payload(demo_result),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    assert len(encoded) < 5_000_000
