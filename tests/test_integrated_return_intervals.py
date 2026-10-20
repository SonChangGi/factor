"""Independent short-path regression tests for quote-gap risk diagnostics."""

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from factor_lab.backtest import run_factor_backtest
from factor_lab.config import FIXED_WEIGHTING_POLICY, RunConfig
from factor_lab.integrated_engine import (
    IntegratedConfig,
    _monthly_candidate,
    build_research,
    metrics,
)
from factor_lab.portfolio import TargetAllocation


def _target(date):
    return TargetAllocation(
        FIXED_WEIGHTING_POLICY, date,
        rows=pd.DataFrame([dict(symbol="A", weight=1.0)]),
        cash_weight=0.0, status="available",
    )


def test_gap_recovery_keeps_nav_but_is_not_a_daily_risk_sample():
    dates = pd.bdate_range("2020-01-01", periods=7)
    prices = pd.DataFrame({"A": [100, 100, 101, np.nan, 130, 128, 129]}, index=dates)
    result = run_factor_backtest(
        "hand-check", FIXED_WEIGHTING_POLICY, prices, prices,
        RunConfig(transaction_cost_bps=0, slippage_bps=0),
        signal_targets={dates[0]: _target(dates[0])},
    )
    measured = metrics(result.returns, result.return_interval_sessions)
    # Four observed one-session returns. The 130/101 - 1 recovery spans two.
    daily = np.array([0.0, 101 / 100 - 1, 128 / 130 - 1, 129 / 128 - 1])
    assert measured["sharpe"] == pytest.approx(daily.mean() / daily.std() * np.sqrt(252))
    downside = np.sqrt(np.mean(np.minimum(daily, 0) ** 2))
    assert measured["sortino"] == pytest.approx(daily.mean() / downside * np.sqrt(252))
    assert result.equity.iloc[-1] == pytest.approx(1.29)
    assert measured["cagr"] == pytest.approx(1.29 ** (252 / 6) - 1)
    assert measured["calendarObservations"] == 6
    assert measured["observedReturnCount"] == 5
    assert measured["dailyRiskObservations"] == 4
    assert measured["multiSessionReturnObservations"] == 1
    assert measured["valuationCoverageRatio"] == pytest.approx(5 / 6)
    assert measured["dailyRiskCoverageRatio"] == pytest.approx(4 / 6)
    assert measured["riskMetricsComplete"] is True
    assert measured["riskMetricsExact"] is False


def test_complete_and_empty_risk_metadata_and_explicit_daily_gaps():
    complete = metrics(pd.Series([0.01, -0.01, 0.0]))
    assert complete["riskMetricsExact"] is True
    assert complete["dailyRiskCoverageRatio"] == 1
    empty = metrics(pd.Series(dtype=float))
    assert empty["dailyRiskObservations"] == 0
    assert empty["riskMetricsComplete"] is False
    assert np.isnan(empty["sharpe"])
    returns = pd.Series([0.01, np.nan, -0.01, 0.02])
    # pct_change(fill_method=None) never contains a catch-up. Its explicit
    # one-session mask must retain the first observed return after a gap.
    explicit = metrics(returns, returns.notna().astype(int))
    assert explicit["dailyRiskObservations"] == 3
    assert explicit["multiSessionReturnObservations"] == 0
    assert explicit["riskMetricsExact"] is False


def test_candidate_rejects_recovery_at_first_window_row():
    dates = pd.bdate_range("2020-01-01", periods=5)
    result = SimpleNamespace(
        returns=pd.Series([0.0, np.nan, 0.20, 0.01, -0.01], index=dates),
        return_interval_sessions=pd.Series([1, 0, 2, 1, 1], index=dates),
    )
    candidate = _monthly_candidate(result, dates[-1], _target(dates[-1]), None, 3)
    assert candidate["status"] == "data_error"
    assert candidate["reason"] == "multi_session_return_in_window"
    assert candidate["dataIssue"]["missingNavSessions"] == 0
    assert candidate["dataIssue"]["multiSessionReturnDates"] == [str(dates[2].date())]


def test_candidate_reports_only_missing_prices_of_actual_holdings():
    dates = pd.bdate_range("2020-01-01", periods=4)
    result = SimpleNamespace(
        returns=pd.Series([0.0, np.nan, np.nan, 0.2], index=dates),
        weights=pd.DataFrame({"A": [1.0] * 4, "UNHELD": [0.0] * 4}, index=dates),
    )
    quotes = pd.DataFrame({"A": [100, np.nan, np.nan, 120], "UNHELD": [np.nan] * 4}, index=dates)
    candidate = _monthly_candidate(result, dates[-1], _target(dates[-1]), None, 4, quotes)
    assert candidate["reason"] == "incomplete_nav"
    assert candidate["dataIssue"] == dict(
        evaluationStart=str(dates[0].date()), evaluationEnd=str(dates[-1].date()),
        missingNavSessions=2, firstMissingDate=str(dates[1].date()),
        lastMissingDate=str(dates[2].date()), symbols=["A"],
    )


def test_research_masks_recovery_without_collapsing_the_calendar(monkeypatch):
    import factor_lab.integrated_engine as engine

    dates = pd.bdate_range("2020-01-01", periods=6)
    returns = {
        "A": pd.Series([0.0, 0.01, np.nan, 0.30, -0.01, 0.02], index=dates),
        "SPY": pd.Series([0.0, 0.01, 0.02, 0.01, -0.01, 0.02], index=dates),
    }
    intervals = {"A": pd.Series([1, 1, 0, 2, 1, 1], index=dates),
                 "SPY": pd.Series(1, index=dates)}
    captured = []

    def capture(frame, *args, **kwargs):
        captured.append(frame.copy())
        return {"status": "insufficient_data"}

    monkeypatch.setattr(engine, "synchronized_bootstrap", capture)
    monkeypatch.setattr(engine, "conditional_exposures", capture)
    monkeypatch.setattr(engine, "regime_analysis", capture)
    research = build_research(returns, {}, {}, [], IntegratedConfig(bootstrap_repetitions=0), intervals)
    assert len(captured) == 5
    for frame in captured:
        assert frame.index.equals(dates)
        assert pd.isna(frame.loc[dates[2], "A"])
        assert pd.isna(frame.loc[dates[3], "A"])
        assert frame.loc[dates[4], "A"] == -0.01
    assert research["returnCoverage"][0]["excludedMultiSessionObservations"] == 1
    assert returns["A"].loc[dates[3]] == 0.30  # original NAV inputs preserved
