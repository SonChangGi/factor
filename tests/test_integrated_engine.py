import numpy as np
import pandas as pd
from momentum_factor_lab.backtest import run_factor_backtest
from momentum_factor_lab.config import RunConfig, FIXED_WEIGHTING_POLICY
from momentum_factor_lab.portfolio import TargetAllocation
from momentum_factor_lab.integrated_engine import (
    metrics,
    rank_candidates,
    completed_monthends,
    IntegratedConfig,
    run_integrated_analysis,
)
from momentum_factor_lab.integrated_research import holm_adjust, synchronized_bootstrap
from momentum_factor_lab.integrated_data import IntegratedMarket


def allocation(date, symbol=None):
    rows = pd.DataFrame([dict(symbol=symbol, weight=1.0)]) if symbol else pd.DataFrame()
    return TargetAllocation(FIXED_WEIGHTING_POLICY, date, rows=rows, status="available")


def test_actual_switch_and_cash_costs_and_missing_signal_hold():
    dates = pd.bdate_range("2020-01-01", periods=8)
    prices = pd.DataFrame(
        {
            "A": [100, 100, 110, 121, 121, 121, 121, 121],
            "B": [100, 100, 100, 100, 100, 110, 121, 121],
        },
        index=dates,
    )
    targets = {
        dates[0]: allocation(dates[0], "A"),
        dates[3]: allocation(dates[3], "B"),
        dates[5]: allocation(dates[5]),
    }
    result = run_factor_backtest(
        "selected",
        FIXED_WEIGHTING_POLICY,
        prices,
        prices,
        RunConfig(transaction_cost_bps=10, slippage_bps=0),
        signal_targets=targets,
    )
    assert np.isclose(result.returns.iloc[1], -0.001)
    assert np.isclose(result.returns.iloc[2], 0.1)
    assert np.isclose(result.returns.iloc[3], 0.1)  # no target means hold
    assert np.isclose(result.returns.iloc[4], -0.001)  # genuine A->B switch
    assert np.isclose(result.returns.iloc[5], 0.1)
    assert np.isclose(result.returns.iloc[6], 1.1 * 0.999 - 1)  # earn before close then cash
    assert result.ending_cash_weight == 1.0
    assert result.returns.iloc[7] == 0.0


def test_unpriceable_hold_cannot_be_liquidated_by_cash_signal():
    dates = pd.bdate_range("2020-01-01", periods=5)
    p = pd.DataFrame({"A": [100, 100, np.nan, 110, 110]}, index=dates)
    result = run_factor_backtest(
        "x",
        FIXED_WEIGHTING_POLICY,
        p,
        p,
        RunConfig(),
        signal_targets={dates[0]: allocation(dates[0], "A"), dates[1]: allocation(dates[1])},
    )
    assert pd.isna(result.returns.iloc[2])
    assert result.execution_statuses.iloc[2] == "blocked_missing_held_quote"
    assert result.ending_weights["A"] == 1.0


def test_metrics_all_observations_sortino_and_stability():
    r = pd.Series([0.01, -0.02, 0.03, 0.0] * 189)
    m = metrics(r)
    assert np.isclose(
        m["sortino"], r.mean() / np.sqrt(np.mean(np.minimum(r, 0) ** 2)) * np.sqrt(252)
    )
    assert np.isclose(m["cagr"], np.prod(1 + r) ** (1 / 3) - 1)
    assert np.isclose(m["calmar"], m["cagr"] / abs(m["mdd"]))


def test_rank_fixed_weights_and_holm():
    rows = {
        str(i): dict(
            status="eligible",
            turnover=0,
            metrics=dict(cagr=i, sortino=i, calmar=i, mdd=-3 + i, sharpe=i, stability=i),
        )
        for i in range(3)
    }
    assert rank_candidates(rows) == ["2", "1", "0"]
    assert np.isclose(rows["2"]["score"], 100)
    assert holm_adjust({"a": 0.01, "b": 0.04, "c": 0.03}) == {"a": 0.03, "c": 0.06, "b": 0.06}


def test_completed_months_not_partial_and_bootstrap_shared_blocks():
    idx = pd.bdate_range("2020-01-01", "2020-03-15")
    assert list(completed_monthends(idx).month) == [1, 2]
    r = pd.Series(np.random.default_rng(1).normal(0, 0.01, 100))
    b = synchronized_bootstrap(pd.DataFrame({"X": r, "SPY": r}), 100, 20)
    assert b["results"][0]["lower"] == b["results"][0]["upper"] == 0.0


def test_integrated_small_run_future_changes_leave_past_unchanged():
    dates = pd.bdate_range("2016-01-01", periods=850)
    rng = np.random.default_rng(4)
    values = 100 * np.cumprod(1 + rng.normal(0.0004, 0.006, (len(dates), 21)), axis=0)
    p = pd.DataFrame(values, index=dates, columns=[f"S{i}" for i in range(20)] + ["SPY"])
    volumes = p * 0 + 1_000_000
    eligible = p.notna()
    eligible["SPY"] = False
    market = IntegratedMarket(
        p,
        p,
        p,
        p,
        p,
        volumes,
        p * 0,
        p * 0,
        eligible,
        {"snapshotId": "test", "requestedSymbols": list(p.columns[:-1])},
    )
    scores = pd.DataFrame(np.tile(np.arange(21), (len(p), 1)), index=dates, columns=p.columns)
    config = IntegratedConfig(bootstrap_repetitions=0)
    first = run_integrated_analysis(market, config, {"MOM12_1": scores})
    assert first["schemaVersion"] == "integrated-factor/v1"
    assert first["selection"]["history"][-1]["status"] in ("selected", "cash")
    cutoff = dates[800]
    market.prices = p.copy()
    market.prices.loc[cutoff:] *= 1.5
    second = run_integrated_analysis(market, config, {"MOM12_1": scores})
    a = [x for x in first["selection"]["history"] if x["date"] < str(cutoff.date())]
    b = [x for x in second["selection"]["history"] if x["date"] < str(cutoff.date())]
    assert a == b


def test_all_risk_fail_is_cash_but_missing_nav_defers():
    from momentum_factor_lab.integrated_engine import _monthly_candidate

    dates = pd.bdate_range("2016-01-01", periods=850)
    p = pd.DataFrame(
        {f"S{i}": 100 * (0.999 ** np.arange(len(dates))) for i in range(20)}, index=dates
    )
    v = p * 0 + 1e6
    e = p.notna()
    market = IntegratedMarket(p, p, p, p, p, v, p * 0, p * 0, e, {"snapshotId": "risk-test"})
    scores = pd.DataFrame(np.tile(np.arange(20), (len(p), 1)), index=dates, columns=p.columns)
    out = run_integrated_analysis(
        market, IntegratedConfig(bootstrap_repetitions=0), {"MOM12_1": scores}
    )
    assert out["selection"]["history"][-1]["status"] == "cash"
    assert out["selection"]["cashWeight"] == 1
    assert out["selection"]["nav"][0]["value"] == 1
    from types import SimpleNamespace

    r = pd.Series(0.001, index=dates)
    r.iloc[-5] = np.nan
    fake = SimpleNamespace(returns=r)
    candidate = _monthly_candidate(
        fake, dates[-1], allocation(dates[-1], "S0"), p.pct_change(fill_method=None), 756
    )
    assert candidate["status"] == "data_error"


def test_pending_target_at_exchange_monthend_has_future_execution():
    dates = pd.bdate_range("2016-01-01", "2019-05-31")
    p = pd.DataFrame(
        {f"S{i}": 100 * (1.0001 ** np.arange(len(dates))) for i in range(20)}, index=dates
    )
    v = p * 0 + 1e6
    e = p.notna()
    market = IntegratedMarket(p, p, p, p, p, v, p * 0, p * 0, e, {"snapshotId": "pending-test"})
    out = run_integrated_analysis(market, IntegratedConfig(bootstrap_repetitions=0), {"MOM12_1": p})
    assert out["selection"]["pending"]["executionDate"] == "2019-06-03"
    assert out["selection"]["pending"]["executionStatus"] == "pending"


def test_stress_executes_each_requested_scenario():
    from momentum_factor_lab.integrated_engine import run_stress_suite

    dates = pd.bdate_range("2016-01-01", periods=100)
    p = pd.DataFrame(
        {f"S{i}": 100 * (1.0001 ** np.arange(len(dates))) for i in range(20)}, index=dates
    )
    v = p * 0 + 1e6
    e = p.notna()
    market = IntegratedMarket(p, p, p, p, p, v, p * 0, p * 0, e, {"snapshotId": "stress-test"})
    result = run_stress_suite(
        market, IntegratedConfig(bootstrap_repetitions=0, evaluation_window_days=21), {"MOM12_1": p}
    )
    assert {r["id"] for r in result} == {"cost20", "cost40", "delay2", "top10", "top30", "equal"}
    assert all(r["nav"] for r in result)


def test_ic_uses_next_close_to_next_close_and_direction():
    from momentum_factor_lab.integrated_research import monthly_signal_diagnostics

    dates = pd.bdate_range("2020-01-01", "2020-03-04")
    prices = pd.DataFrame(100.0, index=dates, columns=list("ABCDE"))
    signal_dates = pd.DatetimeIndex(["2020-01-31", "2020-02-28"])
    prices.loc["2020-01-31"] = [500, 400, 300, 200, 100]  # must not determine forward return
    prices.loc["2020-02-03"] = [100] * 5
    prices.loc["2020-03-02"] = [110, 120, 130, 140, 150]
    scores = pd.DataFrame(
        np.tile(np.arange(5), (len(dates), 1)), index=dates, columns=prices.columns
    )
    ic, quintiles = monthly_signal_diagnostics(scores, prices, signal_dates, "lower")
    assert np.isclose(ic[0]["buy"], 1.0) and np.isclose(ic[0]["raw"], -1.0)
    assert np.isclose(quintiles[0]["spread"], 0.4)


def test_bootstrap_does_not_stitch_missing_sessions():
    frame = pd.DataFrame({"A": [0.01, np.nan, 0.02, np.nan, 0.03], "SPY": [0.0] * 5})
    result = synchronized_bootstrap(frame, 100, 2)
    assert result["status"] == "insufficient_data"


def test_metric_boundary_states_distinguish_empty_from_zero():
    from momentum_factor_lab.integrated_engine import annotate_metric_states, clean

    out = {"metrics": metrics(pd.Series(dtype=float))}
    annotate_metric_states(out)
    assert out["metricStates"]["cagr"] == "insufficient_data"
    assert clean(out)["metrics"]["cagr"] is None
    out = {"metrics": metrics(pd.Series([0.01] * 756))}
    annotate_metric_states(out)
    assert out["metricStates"]["sortino"] == "positive_infinity"
    assert out["metricStates"]["calmar"] == "positive_infinity"


def test_overlap_snapshots_use_drifted_actual_holdings_and_mark_missing():
    from momentum_factor_lab.integrated_engine import actual_holding_snapshots

    dates = pd.bdate_range("2020-01-01", periods=5)
    prices = pd.DataFrame({"A": [100, 100, 120, np.nan, 120], "B": [100] * 5}, index=dates)
    target = TargetAllocation(
        FIXED_WEIGHTING_POLICY,
        dates[0],
        rows=pd.DataFrame([{"symbol": "A", "weight": 0.5}, {"symbol": "B", "weight": 0.5}]),
        status="available",
    )
    result = run_factor_backtest(
        "fixed",
        FIXED_WEIGHTING_POLICY,
        prices,
        prices,
        RunConfig(transaction_cost_bps=0, slippage_bps=0),
        signal_targets={dates[0]: target},
    )
    snapshots = actual_holding_snapshots(result, dates, index=dates)
    assert snapshots[dates[0]]["status"] == "not_started"
    assert np.isclose(snapshots[dates[2]]["weights"]["A"], 0.6 / 1.1)
    assert snapshots[dates[2]]["weights"]["A"] != 0.5
    assert snapshots[dates[3]]["status"] == "unavailable_valuation"


def test_terminal_missing_held_quote_marks_factor_partial_data():
    dates = pd.bdate_range("2016-01-01", periods=80)
    p = pd.DataFrame(
        {f"S{i}": 100 * (1.0001 ** np.arange(len(dates))) for i in range(20)}, index=dates
    )
    scores = p.copy()
    p.loc[dates[-1], "S19"] = np.nan
    volume = p * 0 + 1e6
    eligible = p.notna()
    market = IntegratedMarket(
        p, p, p, p, p, volume, p * 0, p * 0, eligible, {"snapshotId": "partial-test"}
    )
    out = run_integrated_analysis(
        market,
        IntegratedConfig(bootstrap_repetitions=0, evaluation_window_days=21),
        {"MOM12_1": scores},
    )
    row = out["factors"][0]
    assert row["status"] == "partial_data"
    assert 0 < row["valuationCoverage"] < 1
    assert row["lastValuedDate"] == str(dates[-2].date())
    assert row["metrics"]["cagr"] is None
