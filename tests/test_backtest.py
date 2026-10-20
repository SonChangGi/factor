import numpy as np
import pandas as pd
import pytest

from factor_lab.backtest import _rebalance_dates, run_factor_backtest
from factor_lab.config import FIXED_WEIGHTING_POLICY, RunConfig, WEIGHTING_POLICIES
from factor_lab.data import build_eligibility_mask
from factor_lab.metrics import composite_factor_scorecard, evaluation_metrics
from factor_lab.portfolio import construct_model_portfolio


def _fixture() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, RunConfig]:
    dates = pd.bdate_range("2024-01-02", periods=70)
    prices = pd.DataFrame(
        {
            "AAA": 100.0 * np.cumprod(np.repeat(1.001, len(dates))),
            "BBB": 100.0 * np.cumprod(np.repeat(0.999, len(dates))),
        },
        index=dates,
    )
    scores = pd.DataFrame({"AAA": 2.0, "BBB": 1.0}, index=dates)
    eligible = pd.DataFrame(True, index=dates, columns=prices.columns)
    config = RunConfig(
        demo=True,
        demo_symbol_count=50,
        top_n=1,
        max_weight=1.0,
        selection_min_effective_names=1.0,
        min_history_days=21,
        evaluation_window_days=252,
        min_evaluation_observations=252,
        min_daily_risk_observations=252,
    )
    return prices, scores, eligible, config


def _policy_panels(prices: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    dollar_volume = pd.DataFrame(
        20_000_000.0,
        index=prices.index,
        columns=prices.columns,
    )
    market_cap = pd.DataFrame(
        2_000_000_000.0,
        index=prices.index,
        columns=prices.columns,
    )
    return dollar_volume, market_cap


def _attribution_config(*, top_n: int, max_weight: float) -> RunConfig:
    return RunConfig(
        demo=True,
        demo_symbol_count=50,
        top_n=top_n,
        max_weight=max_weight,
        selection_min_effective_names=float(top_n),
        min_history_days=21,
        evaluation_window_days=252,
        min_evaluation_observations=252,
        min_daily_risk_observations=252,
        transaction_cost_bps=0.0,
        slippage_bps=0.0,
    )


def _run(
    prices: pd.DataFrame,
    scores: pd.DataFrame,
    config: RunConfig,
    eligibility: pd.DataFrame,
    *,
    factor: str = "factor",
    policy_id: str = FIXED_WEIGHTING_POLICY,
    trailing_dollar_volume: pd.DataFrame | None = None,
    trailing_market_cap: pd.DataFrame | None = None,
):
    if trailing_dollar_volume is None or trailing_market_cap is None:
        default_liquidity, default_market_cap = _policy_panels(prices)
        trailing_dollar_volume = (
            default_liquidity if trailing_dollar_volume is None else trailing_dollar_volume
        )
        trailing_market_cap = (
            default_market_cap if trailing_market_cap is None else trailing_market_cap
        )
    return run_factor_backtest(
        factor,
        policy_id,
        prices,
        scores,
        config,
        eligibility_mask=eligibility,
        trailing_dollar_volume=trailing_dollar_volume,
        trailing_market_cap=trailing_market_cap,
    )


def test_evaluation_window_changes_the_trailing_analysis_metrics() -> None:
    dates = pd.bdate_range("2025-01-02", periods=300)
    returns = pd.Series(
        np.r_[np.full(174, -0.002), np.full(126, 0.002)],
        index=dates,
    )
    zeros = pd.Series(0.0, index=dates)

    short = evaluation_metrics(
        returns,
        zeros,
        zeros,
        window_days=126,
        stability_periods=3,
    )
    long = evaluation_metrics(
        returns,
        zeros,
        zeros,
        window_days=252,
        stability_periods=3,
    )

    assert short["observations"] == 126
    assert long["observations"] == 252
    assert short["cagr"] > 0.0
    assert short["cagr"] > long["cagr"]


def test_month_end_signal_uses_next_close_without_capturing_that_session_return() -> None:
    prices, scores, eligible, config = _fixture()
    config.transaction_cost_bps = 0.0
    config.slippage_bps = 0.0

    result = _run(prices, scores, config, eligible)

    signal = _rebalance_dates(prices.index, "ME")[0]
    execution_close = prices.index[prices.index.get_loc(signal) + 1]
    effective = prices.index[prices.index.get_loc(signal) + 2]
    assert result.weights.loc[signal].sum() == 0.0
    assert result.weights.loc[execution_close].sum() == 0.0
    assert result.weights.loc[effective, "AAA"] == 1.0
    assert result.signal_dates.loc[execution_close] == signal
    assert result.returns.loc[execution_close] == pytest.approx(0.0)
    assert result.returns.loc[effective] == pytest.approx(0.001)


def test_weight_history_tail_retains_only_exact_recent_sessions() -> None:
    prices, scores, eligible, config = _fixture()
    full = _run(prices, scores, config, eligible)
    tail = run_factor_backtest(
        "factor",
        FIXED_WEIGHTING_POLICY,
        prices,
        scores,
        config,
        eligibility_mask=eligible,
        trailing_dollar_volume=_policy_panels(prices)[0],
        trailing_market_cap=_policy_panels(prices)[1],
        retain_weight_history=True,
        weight_history_tail_sessions=7,
    )

    assert tail.weights.equals(full.weights.tail(7))
    assert tail.pre_trade_weights.equals(full.pre_trade_weights.tail(7))
    assert tail.cash_weights.equals(full.cash_weights.tail(7))
    assert tail.returns.equals(full.returns)
    assert tail.ending_weights.equals(full.ending_weights)
    assert tail.ending_cash_weight == full.ending_cash_weight


def test_weight_history_tail_requires_positive_retained_history() -> None:
    prices, scores, eligible, config = _fixture()

    with pytest.raises(ValueError, match="positive integer"):
        run_factor_backtest(
            "factor",
            FIXED_WEIGHTING_POLICY,
            prices,
            scores,
            config,
            eligibility_mask=eligible,
            trailing_dollar_volume=_policy_panels(prices)[0],
            trailing_market_cap=_policy_panels(prices)[1],
            retain_weight_history=False,
            weight_history_tail_sessions=7,
        )
    with pytest.raises(ValueError, match="positive integer"):
        run_factor_backtest(
            "factor",
            FIXED_WEIGHTING_POLICY,
            prices,
            scores,
            config,
            eligibility_mask=eligible,
            trailing_dollar_volume=_policy_panels(prices)[0],
            trailing_market_cap=_policy_panels(prices)[1],
            weight_history_tail_sessions=0,
        )


def test_real_extreme_move_is_earned_before_causal_gate_blocks_later_signals() -> None:
    prices, scores, _, config = _fixture()
    config.transaction_cost_bps = 0.0
    config.slippage_bps = 0.0
    config.data_quality_lookback_days = 20
    config.max_extreme_daily_return = 0.80
    signal = _rebalance_dates(prices.index, "ME")[0]
    execution = prices.index[prices.index.get_loc(signal) + 1]
    jump_date = prices.index[prices.index.get_loc(execution) + 5]
    pre_jump_price = float(prices.loc[prices.index[prices.index.get_loc(jump_date) - 1], "AAA"])
    event_multiplier = 3.0
    prices.loc[jump_date:, "AAA"] = pre_jump_price * event_multiplier
    volumes = pd.DataFrame(1_000_000.0, index=prices.index, columns=prices.columns)
    eligibility = build_eligibility_mask(prices, volumes, config)

    result = _run(prices, scores, config, eligibility)

    assert result.weights.loc[jump_date, "AAA"] == pytest.approx(1.0)
    assert result.returns.loc[jump_date] == pytest.approx(event_multiplier - 1.0)
    assert not eligibility.loc[jump_date, "AAA"]
    later_signal = _rebalance_dates(prices.index, "ME")[1]
    assert not eligibility.loc[later_signal, "AAA"]


@pytest.mark.parametrize("policy_id", WEIGHTING_POLICIES)
def test_post_signal_policy_inputs_cannot_change_first_execution_target(policy_id: str) -> None:
    prices, scores, eligible, config = _fixture()
    config.top_n = 2
    config.max_weight = 0.75
    config.transaction_cost_bps = 0.0
    config.slippage_bps = 0.0
    dollar_volume, market_cap = _policy_panels(prices)

    baseline = _run(
        prices,
        scores,
        config,
        eligible,
        policy_id=policy_id,
        trailing_dollar_volume=dollar_volume,
        trailing_market_cap=market_cap,
    )
    signal = _rebalance_dates(prices.index, "ME")[0]
    execution = prices.index[prices.index.get_loc(signal) + 1]
    first_exposure = prices.index[prices.index.get_loc(signal) + 2]
    changed_scores = scores.copy()
    changed_dollar_volume = dollar_volume.copy()
    changed_market_cap = market_cap.copy()
    changed_scores.loc[execution:, ["AAA", "BBB"]] = [1.0, 10.0]
    changed_dollar_volume.loc[execution:, ["AAA", "BBB"]] = [1.0, 1_000_000_000.0]
    changed_market_cap.loc[execution:, ["AAA", "BBB"]] = [1.0, 10_000_000_000.0]

    changed = _run(
        prices,
        changed_scores,
        config,
        eligible,
        policy_id=policy_id,
        trailing_dollar_volume=changed_dollar_volume,
        trailing_market_cap=changed_market_cap,
    )

    assert changed.signal_dates.loc[execution] == signal
    assert changed.weights.loc[first_exposure].tolist() == pytest.approx(
        baseline.weights.loc[first_exposure].tolist()
    )


@pytest.mark.parametrize("policy_id", WEIGHTING_POLICIES)
def test_historical_execution_target_matches_current_target_kernel_exactly(
    policy_id: str,
) -> None:
    prices, scores, eligible, config = _fixture()
    config.top_n = 2
    config.max_weight = 0.75
    config.transaction_cost_bps = 0.0
    config.slippage_bps = 0.0
    dollar_volume, market_cap = _policy_panels(prices)

    history = _run(
        prices,
        scores,
        config,
        eligible,
        policy_id=policy_id,
        trailing_dollar_volume=dollar_volume,
        trailing_market_cap=market_cap,
    )
    signal = _rebalance_dates(prices.index, "ME")[0]
    current = construct_model_portfolio(
        "factor",
        signal,
        scores.loc[signal],
        prices.loc[signal],
        eligible.loc[signal],
        config,
        policy_id=policy_id,
        trailing_dollar_volume=dollar_volume.loc[signal],
        trailing_market_cap=market_cap.loc[signal],
    )
    first_exposure = history.first_market_exposure_return_date

    assert first_exposure is not None
    assert history.policy_id == current.allocation.policy_id == policy_id
    assert history.weights.loc[first_exposure].tolist() == pytest.approx(
        current.allocation.weights(prices.columns).tolist()
    )
    assert 1.0 - history.weights.loc[first_exposure].sum() == pytest.approx(current.cash_weight)


@pytest.mark.parametrize(
    "bad_index",
    [
        pd.bdate_range("2024-01-03", periods=70),
        pd.DatetimeIndex(
            list(pd.bdate_range("2024-01-02", periods=69))
            + [pd.bdate_range("2024-01-02", periods=69)[-1]]
        ),
    ],
)
def test_backtest_requires_exact_unique_increasing_date_index(
    bad_index: pd.DatetimeIndex,
) -> None:
    prices, scores, eligible, config = _fixture()
    changed_scores = scores.copy()
    changed_scores.index = bad_index

    with pytest.raises(ValueError, match="exact same date index|unique and increasing"):
        _run(prices, changed_scores, config, eligible)


def test_backtest_rejects_misaligned_policy_panel_index() -> None:
    prices, scores, eligible, config = _fixture()
    dollar_volume, market_cap = _policy_panels(prices)
    market_cap = market_cap.iloc[1:]

    with pytest.raises(ValueError, match="trailing_market_cap must share"):
        _run(
            prices,
            scores,
            config,
            eligible,
            policy_id=FIXED_WEIGHTING_POLICY,
            trailing_dollar_volume=dollar_volume,
            trailing_market_cap=market_cap,
        )


def test_entry_cost_is_charged_once_from_one_way_turnover() -> None:
    prices, scores, eligible, config = _fixture()
    config.transaction_cost_bps = 5.0
    config.slippage_bps = 5.0

    result = _run(prices, scores, config, eligible)

    entry_date = result.turnover[result.turnover.gt(0.0)].index[0]
    assert result.turnover.loc[entry_date] == pytest.approx(1.0)
    assert result.costs.loc[entry_date] == pytest.approx(0.001)
    assert result.returns.loc[entry_date] == pytest.approx(-0.001)
    assert result.costs.drop(index=entry_date).eq(0.0).all()
    assert result.contribution_diagnostics.attribution_max_residual < 1e-12


def test_missing_return_on_a_held_asset_is_not_filled_with_zero() -> None:
    prices, scores, eligible, config = _fixture()
    baseline = _run(prices, scores, config, eligible)
    held_date = baseline.weights.index[baseline.weights["AAA"].gt(0.0)][5]
    changed = prices.copy()
    changed.loc[held_date, "AAA"] = np.nan

    result = _run(changed, scores, config, eligible)

    assert pd.isna(result.returns.loc[held_date])


def test_held_quote_gap_recovers_exact_sleeve_nav_and_coholder_move() -> None:
    prices, scores, eligible, config = _fixture()
    prices.loc[:, :] = 100.0
    config.top_n = 2
    config.max_weight = 0.5
    config.transaction_cost_bps = 0.0
    config.slippage_bps = 0.0
    baseline = _run(prices, scores, config, eligible)
    exposed = baseline.weights.index[baseline.weights.sum(axis=1).gt(0.0)]
    gap_date, recovery_date = exposed[5], exposed[6]
    changed = prices.copy()
    changed.loc[gap_date, "AAA"] = np.nan
    changed.loc[gap_date, "BBB"] = 110.0
    changed.loc[recovery_date:, ["AAA", "BBB"]] = 121.0

    result = _run(changed, scores, config, eligible)

    assert pd.isna(result.returns.loc[gap_date])
    assert result.returns.loc[recovery_date] == pytest.approx(0.21)
    assert result.return_interval_sessions.loc[recovery_date] == 2
    assert result.equity.loc[recovery_date] == pytest.approx(1.21)
    next_date = result.weights.index[result.weights.index.get_loc(recovery_date) + 1]
    assert result.weights.loc[next_date, "AAA"] == pytest.approx(0.5)
    assert result.weights.loc[next_date, "BBB"] == pytest.approx(0.5)
    assert result.stale_holding_counts.loc[gap_date] == 1
    event = result.contribution_diagnostics.max_observed_interval_security_contribution
    assert event is not None
    assert event.symbol == "AAA"
    assert event.date == recovery_date
    assert event.return_interval_sessions == 2
    assert event.contribution == pytest.approx(0.105)
    assert result.contribution_diagnostics.max_exact_single_session_security_contribution is None
    assert result.contribution_diagnostics.attribution_max_residual < 1e-12


def test_staggered_held_quote_gaps_preserve_exact_multi_sleeve_catchup() -> None:
    prices, scores, eligible, config = _fixture()
    prices.loc[:, :] = 100.0
    config.top_n = 2
    config.max_weight = 0.5
    config.transaction_cost_bps = 0.0
    config.slippage_bps = 0.0
    baseline = _run(prices, scores, config, eligible)
    exposed = baseline.weights.index[baseline.weights.sum(axis=1).gt(0.0)]
    first_gap, second_gap, recovery = exposed[5], exposed[6], exposed[7]
    changed = prices.copy()
    changed.loc[first_gap, ["AAA", "BBB"]] = [np.nan, 110.0]
    changed.loc[second_gap, ["AAA", "BBB"]] = [110.0, np.nan]
    changed.loc[recovery:, ["AAA", "BBB"]] = 121.0

    result = _run(changed, scores, config, eligible)

    assert result.returns.loc[[first_gap, second_gap]].isna().all()
    assert result.returns.loc[recovery] == pytest.approx(0.21)
    assert result.return_interval_sessions.loc[recovery] == 3


def test_unheld_quote_gap_does_not_change_portfolio_return() -> None:
    prices, scores, eligible, config = _fixture()
    baseline = _run(prices, scores, config, eligible)
    held_date = baseline.weights.index[baseline.weights["AAA"].gt(0.0)][5]
    changed = prices.copy()
    changed.loc[held_date, "BBB"] = np.nan

    result = _run(changed, scores, config, eligible)

    assert result.returns.loc[held_date] == pytest.approx(baseline.returns.loc[held_date])
    assert result.valuation_available.loc[held_date]


def test_terminal_held_quote_gap_keeps_ending_nav_unknown() -> None:
    prices, scores, eligible, config = _fixture()
    baseline = _run(prices, scores, config, eligible)
    assert baseline.weights.iloc[-1]["AAA"] > 0.0
    changed = prices.copy()
    changed.iloc[-1, changed.columns.get_loc("AAA")] = np.nan

    result = _run(changed, scores, config, eligible)

    assert pd.isna(result.returns.iloc[-1])
    assert pd.isna(result.equity.iloc[-1])
    assert not result.valuation_available.iloc[-1]
    assert result.return_interval_sessions.iloc[-1] == 0
    assert not result.contribution_diagnostics.complete
    assert "ending_nav_unavailable" in str(result.contribution_diagnostics.reason)


def test_ineligible_high_score_cannot_enter() -> None:
    prices, scores, eligible, config = _fixture()
    eligible["AAA"] = False

    result = _run(prices, scores, config, eligible)

    nonzero = result.weights[result.weights.sum(axis=1).gt(0.0)]
    assert not nonzero.empty
    assert nonzero["AAA"].eq(0.0).all()
    assert nonzero["BBB"].gt(0.0).all()


def test_missing_execution_close_cannot_create_an_assumed_fill() -> None:
    prices, scores, eligible, config = _fixture()
    signal = _rebalance_dates(prices.index, "ME")[0]
    execution_close = prices.index[prices.index.get_loc(signal) + 1]
    first_exposure_close = prices.index[prices.index.get_loc(signal) + 2]
    prices.loc[execution_close, "AAA"] = np.nan

    result = _run(prices, scores, config, eligible)

    assert result.weights.loc[first_exposure_close, "AAA"] == 0.0
    assert result.cash_weights.loc[first_exposure_close] == pytest.approx(1.0)
    assert result.selected_security_counts.loc[execution_close] == 0.0
    assert result.turnover.loc[execution_close] == 0.0
    assert result.costs.loc[execution_close] == 0.0


def test_missing_held_execution_close_cancels_rebalance_without_phantom_sale() -> None:
    prices, scores, eligible, config = _fixture()
    config.transaction_cost_bps = 0.0
    config.slippage_bps = 0.0
    baseline = _run(prices, scores, config, eligible)
    execution_dates = list(baseline.signal_dates.index)
    assert len(execution_dates) >= 2
    second_execution = execution_dates[1]
    second_signal = baseline.signal_dates.loc[second_execution]
    switched_scores = scores.copy()
    switched_scores.loc[second_signal:, ["AAA", "BBB"]] = [1.0, 2.0]
    changed = prices.copy()
    changed.loc[second_execution, "AAA"] = np.nan

    result = _run(changed, switched_scores, config, eligible)
    following_date = result.weights.index[result.weights.index.get_loc(second_execution) + 1]

    assert result.execution_statuses.loc[second_execution] == "blocked_missing_held_quote"
    assert result.turnover.loc[second_execution] == 0.0
    assert result.costs.loc[second_execution] == 0.0
    assert result.weights.loc[following_date, "AAA"] == pytest.approx(1.0)
    assert result.weights.loc[following_date, "BBB"] == 0.0


def test_cash_warmup_is_not_counted_as_factor_evidence() -> None:
    dates = pd.bdate_range("2020-01-02", periods=800)
    prices = pd.DataFrame({"AAA": np.linspace(100.0, 180.0, len(dates))}, index=dates)
    scores = pd.DataFrame(np.nan, index=dates, columns=["AAA"])
    scores.loc[dates[650] :, "AAA"] = 1.0
    eligible = pd.DataFrame(True, index=dates, columns=["AAA"])
    config = RunConfig(
        demo=True,
        demo_symbol_count=50,
        top_n=1,
        max_weight=1.0,
        selection_min_effective_names=1.0,
        min_history_days=21,
        evaluation_window_days=756,
        min_evaluation_observations=504,
        min_daily_risk_observations=504,
        stability_periods=2,
        transaction_cost_bps=0.0,
        slippage_bps=0.0,
    )
    result = _run(prices, scores, config, eligible, factor="late")
    metrics = evaluation_metrics(
        result.returns,
        result.turnover,
        result.costs,
        window_days=756,
        stability_periods=2,
        gross_exposure=result.gross_exposure,
        strategy_active=result.strategy_active,
        valuation_available=result.valuation_available,
        execution_statuses=result.execution_statuses,
        policy_input_statuses=result.policy_input_statuses,
        policy_input_reasons=result.policy_input_reasons,
        return_interval_sessions=result.return_interval_sessions,
    )
    scorecard = composite_factor_scorecard(
        pd.DataFrame([{"factor": "late", "comparison_eligible": True, **metrics}]),
        weights={"sortino": 1.0},
        winsor_lower=0.0,
        winsor_upper=1.0,
        min_observations=504,
    )

    assert result.first_nonempty_execution_date is not None
    assert result.returns.loc[: result.first_nonempty_execution_date].iloc[:-1].isna().all()
    assert metrics["observations"] < 200
    assert metrics["actual_exposure_observations"] < metrics["observations"]
    assert scorecard.loc[0, "comparison_status"] == "insufficient_history"
    assert pd.isna(scorecard.loc[0, "composite_score"])


def test_turnover_and_cost_use_drifted_execution_close_weights() -> None:
    prices, scores, eligible, config = _fixture()
    prices.loc[:, :] = 100.0
    config.top_n = 2
    config.max_weight = 0.5
    config.transaction_cost_bps = 5.0
    config.slippage_bps = 5.0
    baseline = _run(prices, scores, config, eligible)
    executions = list(baseline.signal_dates.index)
    second_execution = executions[1]
    prior = prices.index[prices.index.get_loc(second_execution) - 1]
    prices.loc[second_execution, "AAA"] = 200.0
    prices.loc[prior, ["AAA", "BBB"]] = 100.0

    result = _run(prices, scores, config, eligible)

    assert result.pre_trade_weights.loc[second_execution, "AAA"] == pytest.approx(2.0 / 3.0)
    assert result.pre_trade_weights.loc[second_execution, "BBB"] == pytest.approx(1.0 / 3.0)
    assert result.turnover.loc[second_execution] == pytest.approx(1.0 / 6.0)
    # Pre-trade NAV is 1.5 times the previous complete NAV after AAA doubles.
    assert result.costs.loc[second_execution] == pytest.approx(
        1.5 * (1.0 / 6.0) * config.total_cost_rate
    )


def test_missing_policy_inputs_are_recorded_with_reason_and_never_traded() -> None:
    prices, scores, eligible, config = _fixture()
    liquidity = pd.DataFrame(np.nan, index=prices.index, columns=prices.columns)

    result = _run(
        prices,
        scores,
        config,
        eligible,
        policy_id=FIXED_WEIGHTING_POLICY,
        trailing_dollar_volume=liquidity,
    )
    signal = _rebalance_dates(prices.index, "ME")[0]
    execution = prices.index[prices.index.get_loc(signal) + 1]

    assert result.policy_input_statuses.loc[execution] == "unavailable"
    assert result.policy_input_reasons.loc[execution] == ("no_finite_trailing_dollar_volume",)
    assert result.signal_dates.empty
    assert result.turnover.eq(0.0).all()
    assert result.costs.eq(0.0).all()
    assert result.returns.isna().all()


@pytest.mark.parametrize(
    ("shock_symbol", "column_order"),
    [
        ("LEADER_A", ["LEADER_A", "LEADER_B"]),
        ("LEADER_B", ["LEADER_B", "LEADER_A"]),
    ],
)
def test_realized_contribution_diagnostics_follow_the_input_event_without_ticker_constants(
    shock_symbol: str,
    column_order: list[str],
) -> None:
    dates = pd.bdate_range("2024-01-02", periods=70)
    prices = pd.DataFrame(100.0, index=dates, columns=column_order)
    scores = pd.DataFrame(
        {symbol: 2.0 if symbol == shock_symbol else 1.0 for symbol in column_order},
        index=dates,
    )
    eligible = pd.DataFrame(True, index=dates, columns=column_order)
    config = _attribution_config(top_n=1, max_weight=1.0)
    baseline = _run(prices, scores, config, eligible)
    exposed = baseline.weights.index[baseline.weights[shock_symbol].gt(0.0)]
    event_date = exposed[5]
    changed = prices.copy()
    changed.loc[event_date:, shock_symbol] = 200.0

    result = _run(changed, scores, config, eligible)
    diagnostics = result.contribution_diagnostics
    event = diagnostics.max_exact_single_session_security_contribution

    assert diagnostics.attribution_method == "frozen_realized_share_sleeve_contribution"
    assert diagnostics.attribution_version == "1"
    assert diagnostics.complete
    assert diagnostics.reason is None
    assert diagnostics.attribution_max_residual < 1e-12
    assert event is not None
    assert event.symbol == shock_symbol
    assert event.date == event_date
    assert event.return_interval_sessions == 1
    assert event.contribution == pytest.approx(1.0)
    assert result.returns.loc[event_date] == pytest.approx(1.0)
    assert diagnostics.largest_absolute_contribution_security is not None
    assert diagnostics.largest_absolute_contribution_security.symbol == shock_symbol
    assert diagnostics.max_security_absolute_contribution_share == pytest.approx(1.0)
    assert diagnostics.max_leave_one_security is not None
    assert diagnostics.max_leave_one_security.symbol == shock_symbol
    assert diagnostics.max_leave_one_security.leave_one_cagr == pytest.approx(0.0)
    assert diagnostics.max_leave_one_security_cagr_delta == pytest.approx(
        diagnostics.max_leave_one_security.base_cagr
    )
    assert len(diagnostics.top_leave_one_security) == 1
    assert not any(
        isinstance(value, pd.DataFrame)
        for value in (
            diagnostics.max_exact_single_session_security_contribution,
            diagnostics.max_observed_interval_security_contribution,
            diagnostics.largest_absolute_contribution_security,
            diagnostics.top_leave_one_security,
        )
    )


def test_window_level_absolute_contribution_share_uses_absolute_path_totals() -> None:
    dates = pd.bdate_range("2024-01-02", periods=70)
    symbols = ["ALPHA", "BETA"]
    prices = pd.DataFrame(100.0, index=dates, columns=symbols)
    scores = pd.DataFrame({"ALPHA": 2.0, "BETA": 1.0}, index=dates)
    eligible = pd.DataFrame(True, index=dates, columns=symbols)
    config = _attribution_config(top_n=2, max_weight=0.5)
    baseline = _run(prices, scores, config, eligible)
    exposed = baseline.weights.index[baseline.weights.sum(axis=1).gt(0.0)]
    event_date = exposed[5]
    changed = prices.copy()
    changed.loc[event_date:, "ALPHA"] = 120.0
    changed.loc[event_date:, "BETA"] = 110.0

    result = _run(changed, scores, config, eligible)
    diagnostics = result.contribution_diagnostics
    largest = diagnostics.largest_absolute_contribution_security

    assert diagnostics.complete
    assert diagnostics.attribution_max_residual < 1e-12
    assert largest is not None
    assert largest.symbol == "ALPHA"
    assert largest.absolute_contribution == pytest.approx(0.10)
    assert largest.absolute_contribution_share == pytest.approx(2.0 / 3.0)
    assert diagnostics.total_absolute_security_contribution == pytest.approx(0.15)
    assert diagnostics.absolute_contribution_hhi == pytest.approx(5.0 / 9.0)
    assert diagnostics.max_observed_interval_security_contribution is not None
    assert diagnostics.max_observed_interval_security_contribution.symbol == "ALPHA"
    assert diagnostics.max_observed_interval_security_contribution.date == event_date
    assert len(diagnostics.top_leave_one_security) == 2
    assert diagnostics.top_leave_one_security[0].symbol == "ALPHA"


def test_flat_active_strategy_has_complete_zero_contribution_diagnostics() -> None:
    dates = pd.bdate_range("2024-01-02", periods=70)
    prices = pd.DataFrame(100.0, index=dates, columns=["FLAT"])
    scores = pd.DataFrame(1.0, index=dates, columns=["FLAT"])
    eligible = pd.DataFrame(True, index=dates, columns=["FLAT"])
    result = _run(
        prices,
        scores,
        _attribution_config(top_n=1, max_weight=1.0),
        eligible,
    )
    diagnostics = result.contribution_diagnostics

    assert diagnostics.complete
    assert diagnostics.reason is None
    assert diagnostics.max_exact_single_session_security_contribution is None
    assert diagnostics.max_observed_interval_security_contribution is None
    assert diagnostics.largest_absolute_contribution_security is None
    assert diagnostics.max_abs_security_day_contribution == 0.0
    assert diagnostics.max_security_absolute_contribution_share == 0.0
    assert diagnostics.max_leave_one_security_cagr_delta == 0.0
    assert diagnostics.top_leave_one_security == ()
    assert diagnostics.attribution_max_residual < 1e-12


def test_leave_one_output_is_bounded_to_the_ten_largest_generic_securities() -> None:
    dates = pd.bdate_range("2024-01-02", periods=70)
    symbols = [f"SEC_{position:02d}" for position in range(12)]
    prices = pd.DataFrame(100.0, index=dates, columns=symbols)
    scores = pd.DataFrame(
        {symbol: float(len(symbols) - position) for position, symbol in enumerate(symbols)},
        index=dates,
    )
    eligible = pd.DataFrame(True, index=dates, columns=symbols)
    config = _attribution_config(top_n=len(symbols), max_weight=1.0 / len(symbols))
    baseline = _run(prices, scores, config, eligible)
    exposed = baseline.weights.index[baseline.weights.sum(axis=1).gt(0.0)]
    event_date = exposed[5]
    changed = prices.copy()
    for position, symbol in enumerate(symbols, start=1):
        changed.loc[event_date:, symbol] = 100.0 * (1.0 + position / 100.0)

    result = _run(changed, scores, config, eligible)
    diagnostics = result.contribution_diagnostics

    assert diagnostics.complete
    assert len(diagnostics.top_leave_one_security) == 10
    assert diagnostics.top_leave_one_security[0].symbol == symbols[-1]
    assert diagnostics.largest_absolute_contribution_security is not None
    assert diagnostics.largest_absolute_contribution_security.symbol == symbols[-1]
    assert diagnostics.max_security_absolute_contribution_share == pytest.approx(12.0 / 78.0)
    assert diagnostics.attribution_max_residual < 1e-12


def test_contribution_diagnostics_use_only_the_declared_evaluation_window() -> None:
    dates = pd.bdate_range("2023-01-02", periods=320)
    prices = pd.DataFrame(100.0, index=dates, columns=["WINDOWED"])
    scores = pd.DataFrame(1.0, index=dates, columns=["WINDOWED"])
    eligible = pd.DataFrame(True, index=dates, columns=["WINDOWED"])
    config = _attribution_config(top_n=1, max_weight=1.0)
    baseline = _run(prices, scores, config, eligible)
    exposed = baseline.weights.index[baseline.weights["WINDOWED"].gt(0.0)]
    outside_event = exposed[5]
    inside_event = dates[-10]
    assert outside_event < dates[-config.evaluation_window_days]
    changed = prices.copy()
    changed.loc[outside_event:, "WINDOWED"] = 200.0
    changed.loc[inside_event:, "WINDOWED"] = 300.0

    result = _run(changed, scores, config, eligible)
    diagnostics = result.contribution_diagnostics
    event = diagnostics.max_exact_single_session_security_contribution

    assert diagnostics.evaluation_start == dates[-config.evaluation_window_days]
    assert diagnostics.evaluation_end == dates[-1]
    assert event is not None
    assert event.date == inside_event
    assert event.contribution == pytest.approx(0.5)
    assert diagnostics.attribution_max_residual < 1e-12
