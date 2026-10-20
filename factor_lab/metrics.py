from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def _active_return_window(returns: pd.Series) -> pd.Series:
    """Drop only leading unavailable observations, preserving active gaps."""

    if returns.empty:
        return returns
    valid_positions = np.flatnonzero(returns.notna().to_numpy())
    if valid_positions.size == 0:
        return returns.iloc[0:0]
    return returns.iloc[int(valid_positions[0]) :]


def mark_to_last_observed_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Preserve catch-up returns across internal gaps without pricing the gap.

    Missing quote dates remain ``NaN``.  The next observed quote is compared
    with the last observed price, preserving the cumulative move across the
    gap.  Terminal gaps remain unknown and are never interpreted as a zero
    return.  The lab does not invent a terminal price that is absent from the
    supplied research file.
    """

    numeric_prices = prices.apply(pd.to_numeric, errors="coerce")
    marked_prices = numeric_prices.ffill()
    returns = marked_prices.pct_change(fill_method=None)
    return returns.where(numeric_prices.notna()).replace([np.inf, -np.inf], np.nan)


def downside_deviation(
    returns: pd.Series | pd.DataFrame,
    target_return: float = 0.0,
    *,
    window: int | None = None,
    periods_per_year: int = 1,
) -> float | pd.Series | pd.DataFrame:
    """Return target downside deviation using all valid observations.

    Downside deviation is ``sqrt(mean(min(return - target, 0) ** 2))``.
    Non-downside observations therefore contribute zero to the numerator and
    remain in the denominator.  This is intentionally different from taking
    the standard deviation of only negative returns (or of negative returns
    mixed with zeroes), both of which estimate a different quantity.
    """

    downside_squared = (returns - target_return).clip(upper=0.0).pow(2)
    if window is None:
        result = (
            downside_squared.mean().pow(0.5)
            if isinstance(returns, pd.DataFrame)
            else float(np.sqrt(downside_squared.mean()))
        )
    else:
        result = downside_squared.rolling(window, min_periods=window).mean().pow(0.5)
    return result * np.sqrt(periods_per_year)


def max_drawdown(returns: pd.Series) -> float:
    active = _active_return_window(returns)
    if active.empty:
        return 0.0
    observed = active.dropna()
    if observed.empty:
        return 0.0
    # Internal unavailable closes are omitted, while a later complete NAV
    # return contains the full catch-up move.  The resulting drawdown is exact
    # at observed portfolio closes and explicitly a lower bound inside gaps.
    equity = pd.concat(
        [pd.Series([1.0]), (1.0 + observed).cumprod().reset_index(drop=True)],
        ignore_index=True,
    )
    drawdown = equity / equity.cummax() - 1.0
    return float(drawdown.min())


def cagr(returns: pd.Series, periods_per_year: int = TRADING_DAYS) -> float:
    active = _active_return_window(returns)
    if active.empty:
        return 0.0
    if pd.isna(active.iloc[-1]):
        return float("nan")
    total = float((1.0 + active.dropna()).prod())
    years = max(len(active) / periods_per_year, 1e-9)
    if total <= 0:
        return -1.0
    return total ** (1.0 / years) - 1.0


def annualized_volatility(returns: pd.Series, periods_per_year: int = TRADING_DAYS) -> float:
    active = _active_return_window(returns).dropna()
    if len(active) < 2:
        return 0.0
    return float(active.std(ddof=0) * np.sqrt(periods_per_year))


def conditional_value_at_risk(returns: pd.Series, tail: float = 0.05) -> float:
    """Average of the worst tail daily returns.

    The dashboard uses the same definition so table values remain consistent
    with backend exports: sort ascending daily returns, take the worst 5% by
    default, and report their arithmetic mean.
    """

    active = _active_return_window(returns)
    if active.empty:
        return 0.0
    ordered = active.dropna().sort_values()
    if ordered.empty:
        return 0.0
    tail_count = max(1, int(np.ceil(len(ordered) * tail)))
    return float(ordered.iloc[:tail_count].mean())


def sharpe_ratio(returns: pd.Series, risk_free_rate: float = 0.0) -> float:
    active = _active_return_window(returns).dropna()
    if len(active) < 2:
        return 0.0
    excess = active - risk_free_rate / TRADING_DAYS
    vol = excess.std(ddof=0)
    if vol == 0 or pd.isna(vol):
        return 0.0
    return float(excess.mean() / vol * np.sqrt(TRADING_DAYS))


def sortino_ratio(returns: pd.Series, risk_free_rate: float = 0.0) -> float:
    active = _active_return_window(returns).dropna()
    if len(active) < 2:
        return 0.0
    daily_target = risk_free_rate / TRADING_DAYS
    excess = active - daily_target
    downside_dev = float(downside_deviation(active, daily_target))
    if downside_dev == 0 or pd.isna(downside_dev):
        return float("inf") if excess.mean() > 0 else 0.0
    return float(excess.mean() / downside_dev * np.sqrt(TRADING_DAYS))


def calmar_ratio(returns: pd.Series) -> float:
    growth = cagr(returns)
    if not np.isfinite(growth):
        return float("nan")
    mdd = abs(max_drawdown(returns))
    if pd.isna(mdd):
        return float("nan")
    if mdd == 0:
        return float("inf") if growth > 0 else 0.0
    return float(growth / mdd)


def metric_summary(
    returns: pd.Series,
    turnover: pd.Series | None = None,
    costs: pd.Series | None = None,
    *,
    risk_free_rate: float = 0.0,
    gross_exposure: pd.Series | None = None,
    strategy_active: pd.Series | None = None,
    valuation_available: pd.Series | None = None,
    stale_holding_counts: pd.Series | None = None,
    stale_holding_weights: pd.Series | None = None,
    execution_statuses: pd.Series | None = None,
    unpriceable_target_counts: pd.Series | None = None,
    policy_input_statuses: pd.Series | None = None,
    policy_input_reasons: pd.Series | None = None,
    return_interval_sessions: pd.Series | None = None,
    target_cash_weights: pd.Series | None = None,
    target_hhi: pd.Series | None = None,
    target_effective_names: pd.Series | None = None,
    target_top1_weights: pd.Series | None = None,
    target_top5_weights: pd.Series | None = None,
    target_max_weights: pd.Series | None = None,
) -> dict[str, object]:
    numeric_returns = pd.to_numeric(returns, errors="coerce")
    if strategy_active is not None:
        active_flags = strategy_active.reindex(numeric_returns.index).fillna(False).astype(bool)
        active_positions = np.flatnonzero(active_flags.to_numpy())
        active = (
            numeric_returns.iloc[int(active_positions[0]) :]
            if active_positions.size
            else numeric_returns.iloc[0:0]
        )
    else:
        active = _active_return_window(numeric_returns)
    observed = active.dropna()
    calendar_observations = float(len(active))
    observations = float(len(observed))
    missing_observations = float(active.isna().sum())
    ending_nav_available = bool(not active.empty and pd.notna(active.iloc[-1]))
    return_coverage_ratio = observations / calendar_observations if calendar_observations else 0.0

    if return_interval_sessions is None:
        inferred: list[int] = []
        missing_run = 0
        for value in active:
            if pd.isna(value):
                missing_run += 1
                inferred.append(0)
            else:
                inferred.append(missing_run + 1)
                missing_run = 0
        intervals = pd.Series(inferred, index=active.index, dtype=int)
    else:
        intervals = (
            pd.to_numeric(return_interval_sessions.reindex(active.index), errors="coerce")
            .fillna(0)
            .astype(int)
        )
    single_session_returns = active.where(intervals.eq(1)).dropna()
    multi_session_return_observations = float((active.notna() & intervals.gt(1)).sum())
    daily_risk_observations = float(len(single_session_returns))
    risk_metrics_complete = bool(ending_nav_available and daily_risk_observations >= 2)
    risk_metrics_exact = bool(risk_metrics_complete and missing_observations == 0)
    mdd = max_drawdown(active)
    aligned_turnover = (
        pd.to_numeric(turnover.reindex(active.index), errors="coerce")
        if turnover is not None
        else pd.Series(dtype=float)
    )
    turnover_events = aligned_turnover[aligned_turnover.gt(0.0)]
    cost_series = (
        pd.to_numeric(costs.reindex(active.index), errors="coerce").dropna()
        if costs is not None
        else pd.Series(dtype=float)
    )
    total_turnover = float(turnover_events.sum()) if not turnover_events.empty else 0.0
    total_cost = float(cost_series.sum()) if not cost_series.empty else 0.0

    exposure = (
        pd.to_numeric(gross_exposure.reindex(active.index), errors="coerce").fillna(0.0)
        if gross_exposure is not None
        else pd.Series(np.where(active.notna(), 1.0, 0.0), index=active.index, dtype=float)
    )
    exposed_calendar = exposure.gt(1e-15)
    actual_exposure_calendar_observations = float(exposed_calendar.sum())
    actual_exposure_observations = float((exposed_calendar & active.notna()).sum())
    cash_only_active_observations = float((~exposed_calendar & active.notna()).sum())
    if valuation_available is not None:
        valuation = valuation_available.reindex(active.index).fillna(False).astype(bool)
        quote_gap_observations = float((~valuation).sum())
    else:
        quote_gap_observations = missing_observations
    if stale_holding_counts is not None:
        stale_counts = pd.to_numeric(
            stale_holding_counts.reindex(active.index), errors="coerce"
        ).fillna(0.0)
    else:
        stale_counts = pd.Series(0.0, index=active.index)
    if stale_holding_weights is not None:
        stale_weights = pd.to_numeric(
            stale_holding_weights.reindex(active.index), errors="coerce"
        ).fillna(0.0)
    else:
        stale_weights = pd.Series(0.0, index=active.index)
    if execution_statuses is not None:
        statuses = execution_statuses.reindex(active.index).fillna("none").astype(str)
        blocked_execution_count = float(statuses.str.startswith("blocked_").sum())
        execution_count = float(statuses.str.startswith("executed").sum())
        full_execution_count = float(statuses.eq("executed").sum())
        partial_execution_count = float(statuses.eq("executed_partial_unpriceable_targets").sum())
        attempted_execution_count = (
            full_execution_count + partial_execution_count + blocked_execution_count
        )
        execution_coverage_ratio = (
            full_execution_count / attempted_execution_count if attempted_execution_count else 0.0
        )
    else:
        blocked_execution_count = 0.0
        execution_count = float(len(turnover_events))
        full_execution_count = execution_count
        partial_execution_count = 0.0
        attempted_execution_count = execution_count
        execution_coverage_ratio = 1.0
    if unpriceable_target_counts is not None:
        unpriceable = pd.to_numeric(
            unpriceable_target_counts.reindex(active.index), errors="coerce"
        ).fillna(0.0)
        unpriceable_target_observations = float(unpriceable.gt(0.0).sum())
        total_unpriceable_target_count = float(unpriceable.sum())
    else:
        unpriceable_target_observations = 0.0
        total_unpriceable_target_count = 0.0
    if policy_input_statuses is not None:
        policy_status = (
            policy_input_statuses.reindex(active.index).fillna("not_scheduled").astype(str)
        )
        scheduled_policy = policy_status.ne("not_scheduled")
        scheduled_policy_signal_count = float(scheduled_policy.sum())
        available_policy_signal_count = float(policy_status.eq("available").sum())
        unavailable_policy_signal_count = float(
            (scheduled_policy & ~policy_status.eq("available")).sum()
        )
        policy_input_coverage_ratio = (
            available_policy_signal_count / scheduled_policy_signal_count
            if scheduled_policy_signal_count
            else 0.0
        )
    else:
        scheduled_policy_signal_count = 0.0
        available_policy_signal_count = 0.0
        unavailable_policy_signal_count = 0.0
        policy_input_coverage_ratio = 1.0
    policy_input_reason_counts: dict[str, int] = {}
    if policy_input_reasons is not None:
        reason_values = policy_input_reasons.reindex(active.index)
        for value in reason_values:
            reasons = value if isinstance(value, (list, tuple, set)) else ()
            for reason in reasons:
                rendered = str(reason).strip()
                if rendered:
                    policy_input_reason_counts[rendered] = (
                        policy_input_reason_counts.get(rendered, 0) + 1
                    )

    def target_stat(series: pd.Series | None, method: str) -> float:
        if series is None:
            return float("nan")
        values = pd.to_numeric(series.reindex(active.index), errors="coerce").dropna()
        if values.empty:
            return float("nan")
        return float(getattr(values, method)())

    return {
        "cagr": cagr(active),
        "annual_return": (
            float(single_session_returns.mean() * TRADING_DAYS)
            if not single_session_returns.empty
            else (0.0 if active.empty else float("nan"))
        ),
        "volatility": annualized_volatility(single_session_returns),
        "sharpe": sharpe_ratio(single_session_returns, risk_free_rate=risk_free_rate),
        "sortino": sortino_ratio(single_session_returns, risk_free_rate=risk_free_rate),
        "calmar": calmar_ratio(active),
        "max_drawdown": mdd,
        "mdd": mdd,
        "cvar_95": conditional_value_at_risk(single_session_returns, tail=0.05),
        "win_rate": (
            float((single_session_returns > 0).mean())
            if not single_session_returns.empty
            else (0.0 if active.empty else float("nan"))
        ),
        "avg_turnover": float(turnover_events.mean()) if not turnover_events.empty else 0.0,
        "total_turnover": total_turnover,
        "turnover_events": float(len(turnover_events)),
        "annualized_turnover": (
            total_turnover / calendar_observations * TRADING_DAYS if calendar_observations else 0.0
        ),
        "total_cost": total_cost,
        "avg_daily_cost": total_cost / calendar_observations if calendar_observations else 0.0,
        "annualized_cost_drag": (
            total_cost / calendar_observations * TRADING_DAYS if calendar_observations else 0.0
        ),
        "observations": observations,
        "calendar_observations": calendar_observations,
        "missing_observations": missing_observations,
        "return_coverage_ratio": return_coverage_ratio,
        "risk_metrics_complete": risk_metrics_complete,
        "risk_metrics_exact": risk_metrics_exact,
        "ending_nav_available": ending_nav_available,
        "daily_risk_observations": daily_risk_observations,
        "multi_session_return_observations": multi_session_return_observations,
        "actual_exposure_observations": actual_exposure_observations,
        "actual_exposure_calendar_observations": actual_exposure_calendar_observations,
        "cash_only_active_observations": cash_only_active_observations,
        "quote_gap_observations": quote_gap_observations,
        "valuation_coverage_ratio": (
            1.0 - quote_gap_observations / calendar_observations if calendar_observations else 0.0
        ),
        "stale_holding_observations": float(stale_counts.gt(0.0).sum()),
        "max_stale_holding_count": float(stale_counts.max()) if not stale_counts.empty else 0.0,
        "max_stale_holding_weight": float(stale_weights.max()) if not stale_weights.empty else 0.0,
        "execution_count": execution_count,
        "full_execution_count": full_execution_count,
        "partial_execution_count": partial_execution_count,
        "attempted_execution_count": attempted_execution_count,
        "execution_coverage_ratio": execution_coverage_ratio,
        "blocked_execution_count": blocked_execution_count,
        "unpriceable_target_observations": unpriceable_target_observations,
        "total_unpriceable_target_count": total_unpriceable_target_count,
        "scheduled_policy_signal_count": scheduled_policy_signal_count,
        "available_policy_signal_count": available_policy_signal_count,
        "unavailable_policy_signal_count": unavailable_policy_signal_count,
        "policy_input_coverage_ratio": policy_input_coverage_ratio,
        "policy_input_reason_counts": policy_input_reason_counts,
        "median_target_cash_weight": target_stat(target_cash_weights, "median"),
        "max_target_cash_weight": target_stat(target_cash_weights, "max"),
        "median_target_hhi": target_stat(target_hhi, "median"),
        "max_target_hhi": target_stat(target_hhi, "max"),
        "median_target_effective_names": target_stat(target_effective_names, "median"),
        "min_target_effective_names": target_stat(target_effective_names, "min"),
        "median_target_top1_weight": target_stat(target_top1_weights, "median"),
        "median_target_top5_weight": target_stat(target_top5_weights, "median"),
        "max_target_weight": target_stat(target_max_weights, "max"),
        "annual_risk_free_rate": float(risk_free_rate),
    }


def subperiod_stability(
    returns: pd.Series,
    *,
    periods: int = 3,
) -> tuple[float, list[float]]:
    """Score whether net performance persists across contiguous subperiods.

    The raw stability value is the median subperiod CAGR minus its standard
    deviation.  A steady but weak factor is still held back by the other
    composite components; this term only rewards persistence among otherwise
    competitive factors.
    """

    active = _active_return_window(returns)
    if active.empty or periods < 2:
        return float("nan"), []
    chunks = [chunk for chunk in np.array_split(active, periods) if len(chunk)]
    if len(chunks) < periods:
        return float("nan"), []
    values = [cagr(pd.Series(chunk, dtype=float)) for chunk in chunks]
    if not np.isfinite(values).all():
        return float("nan"), values
    return float(np.median(values) - np.std(values, ddof=0)), values


def evaluation_metrics(
    returns: pd.Series,
    turnover: pd.Series,
    costs: pd.Series,
    *,
    window_days: int,
    stability_periods: int,
    risk_free_rate: float = 0.0,
    gross_exposure: pd.Series | None = None,
    strategy_active: pd.Series | None = None,
    valuation_available: pd.Series | None = None,
    stale_holding_counts: pd.Series | None = None,
    stale_holding_weights: pd.Series | None = None,
    execution_statuses: pd.Series | None = None,
    unpriceable_target_counts: pd.Series | None = None,
    policy_input_statuses: pd.Series | None = None,
    policy_input_reasons: pd.Series | None = None,
    return_interval_sessions: pd.Series | None = None,
    target_cash_weights: pd.Series | None = None,
    target_hhi: pd.Series | None = None,
    target_effective_names: pd.Series | None = None,
    target_top1_weights: pd.Series | None = None,
    target_top5_weights: pd.Series | None = None,
    target_max_weights: pd.Series | None = None,
    evaluation_index: pd.DatetimeIndex | None = None,
) -> dict[str, object]:
    """Return the net trailing metrics used by the factor comparison."""

    window_returns = (
        returns.reindex(evaluation_index)
        if evaluation_index is not None
        else returns.tail(window_days)
    )
    window_turnover = turnover.reindex(window_returns.index)
    window_costs = costs.reindex(window_returns.index)
    summary = metric_summary(
        window_returns,
        window_turnover,
        window_costs,
        risk_free_rate=risk_free_rate,
        gross_exposure=(
            gross_exposure.reindex(window_returns.index) if gross_exposure is not None else None
        ),
        strategy_active=(
            strategy_active.reindex(window_returns.index) if strategy_active is not None else None
        ),
        valuation_available=(
            valuation_available.reindex(window_returns.index)
            if valuation_available is not None
            else None
        ),
        stale_holding_counts=(
            stale_holding_counts.reindex(window_returns.index)
            if stale_holding_counts is not None
            else None
        ),
        stale_holding_weights=(
            stale_holding_weights.reindex(window_returns.index)
            if stale_holding_weights is not None
            else None
        ),
        execution_statuses=(
            execution_statuses.reindex(window_returns.index)
            if execution_statuses is not None
            else None
        ),
        unpriceable_target_counts=(
            unpriceable_target_counts.reindex(window_returns.index)
            if unpriceable_target_counts is not None
            else None
        ),
        policy_input_statuses=(
            policy_input_statuses.reindex(window_returns.index)
            if policy_input_statuses is not None
            else None
        ),
        policy_input_reasons=(
            policy_input_reasons.reindex(window_returns.index)
            if policy_input_reasons is not None
            else None
        ),
        return_interval_sessions=(
            return_interval_sessions.reindex(window_returns.index)
            if return_interval_sessions is not None
            else None
        ),
        target_cash_weights=target_cash_weights,
        target_hhi=target_hhi,
        target_effective_names=target_effective_names,
        target_top1_weights=target_top1_weights,
        target_top5_weights=target_top5_weights,
        target_max_weights=target_max_weights,
    )
    stability, subperiod_cagrs = subperiod_stability(
        window_returns,
        periods=stability_periods,
    )
    summary["stability"] = stability
    summary["subperiod_cagrs"] = subperiod_cagrs
    return summary


def _winsorized_percentile(series: pd.Series, lower: float, upper: float) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").astype(float)
    finite = values.replace([np.inf, -np.inf], np.nan).dropna()
    if finite.empty:
        scores = pd.Series(np.nan, index=series.index, dtype=float)
        positive_infinite = values.eq(np.inf)
        negative_infinite = values.eq(-np.inf)
        if positive_infinite.any():
            scores.loc[positive_infinite] = 100.0
        if negative_infinite.any():
            scores.loc[negative_infinite] = 0.0
        return scores
    low = float(finite.quantile(lower))
    high = float(finite.quantile(upper))
    clipped = values.replace(np.inf, high).replace(-np.inf, low).clip(low, high)
    return clipped.rank(method="average", pct=True, ascending=True).mul(100.0)


def composite_factor_scorecard(
    raw_metrics: pd.DataFrame,
    *,
    weights: dict[str, float],
    winsor_lower: float,
    winsor_upper: float,
    min_observations: int,
    min_valuation_coverage: float = 0.0,
    min_daily_risk_observations: int = 2,
) -> pd.DataFrame:
    """Build a transparent 0..100 robust cross-factor performance score."""

    required = set(weights) | {
        "factor",
        "observations",
        "risk_metrics_complete",
        "valuation_coverage_ratio",
        "daily_risk_observations",
        "policy_input_coverage_ratio",
        "execution_coverage_ratio",
    }
    missing = sorted(required.difference(raw_metrics.columns))
    if missing:
        raise ValueError("raw factor metrics missing columns: " + ", ".join(missing))
    result = raw_metrics.copy()
    history_eligible = pd.to_numeric(result["observations"], errors="coerce").ge(
        min_observations
    ) & result["risk_metrics_complete"].fillna(False).astype(bool)
    coverage_eligible = pd.to_numeric(result["valuation_coverage_ratio"], errors="coerce").ge(
        min_valuation_coverage
    ) & pd.to_numeric(result["daily_risk_observations"], errors="coerce").ge(
        min_daily_risk_observations
    )
    comparison_eligible = (
        result["comparison_eligible"].fillna(False).astype(bool)
        if "comparison_eligible" in result
        else pd.Series(True, index=result.index, dtype=bool)
    )
    policy_input_eligible = pd.to_numeric(
        result["policy_input_coverage_ratio"], errors="coerce"
    ).ge(1.0 - 1e-12)
    execution_eligible = pd.to_numeric(result["execution_coverage_ratio"], errors="coerce").ge(
        1.0 - 1e-12
    )
    eligible = (
        history_eligible
        & coverage_eligible
        & policy_input_eligible
        & execution_eligible
        & comparison_eligible
    )
    component_columns: list[str] = []
    for metric, weight in weights.items():
        column = f"{metric}_score"
        component_columns.append(column)
        eligible_values = result[metric].where(eligible)
        scores = _winsorized_percentile(
            eligible_values,
            winsor_lower,
            winsor_upper,
        )
        result[column] = scores.where(eligible)
        result[f"{metric}_weight"] = float(weight)
    complete = result[component_columns].notna().all(axis=1) & eligible
    result["composite_score"] = 0.0
    for metric, weight in weights.items():
        result.loc[complete, "composite_score"] += result.loc[complete, f"{metric}_score"] * float(
            weight
        )
    result.loc[~complete, "composite_score"] = np.nan
    result["comparison_status"] = "insufficient_history"
    result.loc[history_eligible & ~coverage_eligible, "comparison_status"] = (
        "insufficient_valuation_or_daily_risk_coverage"
    )
    result.loc[
        history_eligible & coverage_eligible & ~policy_input_eligible,
        "comparison_status",
    ] = "insufficient_policy_input_coverage"
    result.loc[
        history_eligible & coverage_eligible & policy_input_eligible & ~execution_eligible,
        "comparison_status",
    ] = "incomplete_execution_coverage"
    if "comparison_ineligible_status" in result:
        ineligible_status = result["comparison_ineligible_status"].fillna("not_comparable")
    else:
        ineligible_status = pd.Series("not_comparable", index=result.index)
    result.loc[~comparison_eligible, "comparison_status"] = ineligible_status.loc[
        ~comparison_eligible
    ]
    result.loc[complete, "comparison_status"] = "available"
    descending_tie_break_metrics = [
        metric
        for metric in (
            "sortino",
            "calmar",
            "max_drawdown",
            "cagr",
            "sharpe",
            "stability",
        )
        if metric in result
    ]
    ascending_tie_break_metrics = [
        metric for metric in ("annualized_turnover",) if metric in result
    ]
    result = result.sort_values(
        [
            "composite_score",
            *descending_tie_break_metrics,
            *ascending_tie_break_metrics,
            "factor",
        ],
        ascending=(
            [False] * (1 + len(descending_tie_break_metrics))
            + [True] * (len(ascending_tie_break_metrics) + 1)
        ),
        na_position="last",
        kind="stable",
    ).reset_index(drop=True)
    result["rank"] = np.where(
        result["composite_score"].notna(),
        result["composite_score"].notna().cumsum(),
        np.nan,
    )
    return result
