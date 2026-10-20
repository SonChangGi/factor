from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

from .metrics import downside_deviation, mark_to_last_observed_returns

TRADING_DAYS = 252
MINIMUM_PEER_RETURN_COUNT = 2
MINIMUM_CONDITIONAL_REGIME_OBSERVATIONS = 21


def _safe_div(numer: pd.DataFrame, denom: pd.DataFrame) -> pd.DataFrame:
    return numer.divide(denom.replace(0, np.nan))


def _weighted_sum(parts: list[pd.DataFrame]) -> pd.DataFrame:
    if not parts:
        return pd.DataFrame()
    out = parts[0].copy()
    for part in parts[1:]:
        out = out.add(part, fill_value=np.nan)
    return out


def _true_indicator(condition: pd.DataFrame, valid: pd.DataFrame) -> pd.DataFrame:
    return condition.astype(float).where(valid)


def _aligned_eligibility_mask(
    prices: pd.DataFrame,
    eligibility_mask: pd.DataFrame | None,
) -> pd.DataFrame | None:
    if eligibility_mask is None:
        return None
    return (
        eligibility_mask.reindex(index=prices.index, columns=prices.columns)
        .fillna(False)
        .astype(bool)
    )


def total_return_momentum(prices: pd.DataFrame, lookback: int, skip: int = 21) -> pd.DataFrame:
    return prices.shift(skip).divide(prices.shift(lookback + skip)) - 1.0


def simple_momentum(prices: pd.DataFrame, lookback: int) -> pd.DataFrame:
    return prices.divide(prices.shift(lookback)) - 1.0


def two_month_momentum(prices: pd.DataFrame) -> pd.DataFrame:
    return simple_momentum(prices, 42)


def skipped_two_month_momentum(prices: pd.DataFrame) -> pd.DataFrame:
    return total_return_momentum(prices, 42, skip=21)


def unskipped_six_month_momentum(prices: pd.DataFrame) -> pd.DataFrame:
    return simple_momentum(prices, 126)


def skipped_ten_day_six_month_momentum(prices: pd.DataFrame) -> pd.DataFrame:
    return total_return_momentum(prices, 126, skip=10)


def deep_skip_twelve_month_momentum(prices: pd.DataFrame) -> pd.DataFrame:
    return total_return_momentum(prices, 252, skip=42)


def multi_horizon_momentum(prices: pd.DataFrame) -> pd.DataFrame:
    return _weighted_sum(
        [
            0.15 * simple_momentum(prices, 21),
            0.25 * total_return_momentum(prices, 63, skip=5),
            0.30 * total_return_momentum(prices, 126, skip=10),
            0.30 * total_return_momentum(prices, 252, skip=21),
        ]
    )


def volatility_adjusted_momentum(prices: pd.DataFrame) -> pd.DataFrame:
    ret_126 = total_return_momentum(prices, 126, skip=10)
    vol = mark_to_last_observed_returns(prices).rolling(63).std() * np.sqrt(TRADING_DAYS)
    return _safe_div(ret_126, vol)


def risk_adjusted_momentum(prices: pd.DataFrame) -> pd.DataFrame:
    returns = mark_to_last_observed_returns(prices)
    mean = returns.rolling(126).mean() * TRADING_DAYS
    vol = returns.rolling(126).std() * np.sqrt(TRADING_DAYS)
    return _safe_div(mean, vol)


def downside_risk_adjusted_momentum(prices: pd.DataFrame) -> pd.DataFrame:
    returns = mark_to_last_observed_returns(prices)
    downside = downside_deviation(returns, window=126, periods_per_year=TRADING_DAYS)
    return _safe_div(total_return_momentum(prices, 126, skip=10), downside)


def dual_momentum(
    prices: pd.DataFrame,
    eligibility_mask: pd.DataFrame | None = None,
) -> pd.DataFrame:
    relative = total_return_momentum(prices, 126, skip=10)
    eligible = _aligned_eligibility_mask(prices, eligibility_mask)
    if eligible is not None:
        relative = relative.where(eligible)
    relative_rank = relative.rank(axis=1, pct=True)
    absolute = prices.divide(prices.rolling(200).mean()) - 1.0
    return relative_rank.where(absolute > 0)


def moving_average_trend(prices: pd.DataFrame) -> pd.DataFrame:
    ma50 = prices.rolling(50).mean()
    ma200 = prices.rolling(200).mean()
    return prices.divide(ma200) - 1.0 + 0.5 * (ma50.divide(ma200) - 1.0)


def time_series_trend(prices: pd.DataFrame) -> pd.DataFrame:
    ma20 = prices.rolling(20).mean()
    ma100 = prices.rolling(100).mean()
    ma200 = prices.rolling(200).mean()
    valid = prices.notna() & ma20.notna() & ma100.notna() & ma200.notna()
    return (
        _true_indicator(prices > ma20, valid)
        + _true_indicator(ma20 > ma100, valid)
        + _true_indicator(ma100 > ma200, valid)
    )


def drawdown_aware_momentum(prices: pd.DataFrame) -> pd.DataFrame:
    ret_126 = total_return_momentum(prices, 126, skip=10)
    rolling_high = prices.rolling(126).max()
    drawdown = prices.divide(rolling_high) - 1.0
    return ret_126 + drawdown


def high_52week_proximity(prices: pd.DataFrame) -> pd.DataFrame:
    return prices.divide(prices.rolling(252).max()) - 1.0


def high_26week_proximity(prices: pd.DataFrame) -> pd.DataFrame:
    return prices.divide(prices.rolling(126).max()) - 1.0


def breakout_63d(prices: pd.DataFrame) -> pd.DataFrame:
    prior_high = prices.shift(1).rolling(63).max()
    return prices.divide(prior_high) - 1.0 + 0.5 * simple_momentum(prices, 21)


def breakout_126d(prices: pd.DataFrame) -> pd.DataFrame:
    prior_high = prices.shift(1).rolling(126).max()
    return prices.divide(prior_high) - 1.0 + 0.5 * simple_momentum(prices, 63)


def reversal_adjusted_momentum(prices: pd.DataFrame) -> pd.DataFrame:
    long_mom = total_return_momentum(prices, 252, skip=21)
    short_reversal = simple_momentum(prices, 21)
    return long_mom - 0.35 * short_reversal


def annualized_log_return_rate(
    prices: pd.DataFrame,
    *,
    end_lag: int,
    span: int,
) -> pd.DataFrame:
    if end_lag < 0 or span <= 0:
        raise ValueError("end_lag must be non-negative and span must be positive")
    positive_prices = prices.where(prices.gt(0))
    ratio = positive_prices.shift(end_lag).divide(positive_prices.shift(end_lag + span))
    return np.log(ratio) * (TRADING_DAYS / span)


def acceleration_momentum(prices: pd.DataFrame) -> pd.DataFrame:
    return acceleration_3m_vs_6m(prices)


def short_acceleration_momentum(prices: pd.DataFrame) -> pd.DataFrame:
    return acceleration_1m_vs_3m(prices)


def decay_adjusted_momentum(prices: pd.DataFrame) -> pd.DataFrame:
    return total_return_momentum(prices, 126, skip=10) - 0.25 * simple_momentum(prices, 21).abs()


def consistency_momentum(prices: pd.DataFrame) -> pd.DataFrame:
    returns = mark_to_last_observed_returns(prices).shift(10)
    positive = returns.gt(0).astype(float).where(returns.notna())
    positive_ratio = positive.rolling(126).mean()
    return total_return_momentum(prices, 126, skip=10) * positive_ratio


def persistent_twelve_one_momentum(prices: pd.DataFrame) -> pd.DataFrame:
    returns = mark_to_last_observed_returns(prices).shift(21)
    positive = returns.gt(0).astype(float).where(returns.notna())
    positive_ratio = positive.rolling(252, min_periods=252).mean()
    return total_return_momentum(prices, 252, skip=21) * positive_ratio


def low_vol_momentum(prices: pd.DataFrame) -> pd.DataFrame:
    momentum = total_return_momentum(prices, 126, skip=10)
    vol = mark_to_last_observed_returns(prices).rolling(63).std() * np.sqrt(TRADING_DAYS)
    return momentum - vol


def stability_adjusted_momentum(prices: pd.DataFrame) -> pd.DataFrame:
    momentum = total_return_momentum(prices, 126, skip=10)
    vol = mark_to_last_observed_returns(prices).rolling(126).std() * np.sqrt(TRADING_DAYS)
    return _safe_div(momentum, 1.0 + vol)


def relative_strength_6m(
    prices: pd.DataFrame,
    eligibility_mask: pd.DataFrame | None = None,
) -> pd.DataFrame:
    momentum = total_return_momentum(prices, 126, skip=10)
    eligible = _aligned_eligibility_mask(prices, eligibility_mask)
    if eligible is not None:
        momentum = momentum.where(eligible)
    return momentum.rank(axis=1, pct=True)


def trend_quality(prices: pd.DataFrame) -> pd.DataFrame:
    returns = mark_to_last_observed_returns(prices)
    smoothness = returns.rolling(126).mean().divide(returns.rolling(126).std().replace(0, np.nan))
    trend = prices.divide(prices.rolling(126).mean()) - 1.0
    return trend + smoothness


def gap_resistant_momentum(prices: pd.DataFrame) -> pd.DataFrame:
    returns = mark_to_last_observed_returns(prices)
    clipped = returns.clip(lower=-0.08, upper=0.08)
    return (1.0 + clipped).rolling(126).apply(np.prod, raw=True) - 1.0


def winsorized_skip_momentum(prices: pd.DataFrame) -> pd.DataFrame:
    returns = mark_to_last_observed_returns(prices).shift(10)
    clipped = returns.clip(lower=-0.05, upper=0.05)
    return (1.0 + clipped).rolling(126).apply(np.prod, raw=True) - 1.0


def median_return_momentum(prices: pd.DataFrame, window: int) -> pd.DataFrame:
    returns = mark_to_last_observed_returns(prices)
    return returns.rolling(window).median() * window


def price_efficiency_momentum(prices: pd.DataFrame) -> pd.DataFrame:
    returns = mark_to_last_observed_returns(prices).shift(10)
    path_length = returns.abs().rolling(126).sum()
    direct_move = total_return_momentum(prices, 126, skip=10).abs()
    efficiency = _safe_div(direct_move, path_length)
    return total_return_momentum(prices, 126, skip=10) * efficiency


def range_position_momentum(prices: pd.DataFrame) -> pd.DataFrame:
    rolling_low = prices.rolling(126).min()
    rolling_high = prices.rolling(126).max()
    range_position = _safe_div(prices - rolling_low, rolling_high - rolling_low) - 0.5
    return total_return_momentum(prices, 126, skip=10) + range_position


def winsorized_momentum(
    prices: pd.DataFrame, window: int, lower: float = -0.08, upper: float = 0.08
) -> pd.DataFrame:
    returns = mark_to_last_observed_returns(prices).clip(lower=lower, upper=upper)
    return (1.0 + returns).rolling(window).apply(np.prod, raw=True) - 1.0


def volatility_adjusted_simple_momentum(
    prices: pd.DataFrame, lookback: int, vol_window: int
) -> pd.DataFrame:
    momentum = simple_momentum(prices, lookback)
    vol = mark_to_last_observed_returns(prices).rolling(vol_window).std() * np.sqrt(TRADING_DAYS)
    return _safe_div(momentum, vol)


def downside_adjusted_total_momentum(
    prices: pd.DataFrame, lookback: int, skip: int, downside_window: int
) -> pd.DataFrame:
    returns = mark_to_last_observed_returns(prices)
    downside = downside_deviation(
        returns,
        window=downside_window,
        periods_per_year=TRADING_DAYS,
    )
    return _safe_div(total_return_momentum(prices, lookback, skip=skip), downside)


def moving_average_slope(
    prices: pd.DataFrame, window: int = 50, slope_window: int = 21
) -> pd.DataFrame:
    ma = prices.rolling(window).mean()
    return ma.divide(ma.shift(slope_window)) - 1.0


def price_vs_ma200(prices: pd.DataFrame) -> pd.DataFrame:
    return prices.divide(prices.rolling(200).mean()) - 1.0


def moving_average_stack_quality(prices: pd.DataFrame) -> pd.DataFrame:
    ma20 = prices.rolling(20).mean()
    ma50 = prices.rolling(50).mean()
    ma100 = prices.rolling(100).mean()
    ma200 = prices.rolling(200).mean()
    valid = prices.notna() & ma20.notna() & ma50.notna() & ma100.notna() & ma200.notna()
    return (
        _true_indicator(prices > ma20, valid)
        + _true_indicator(ma20 > ma50, valid)
        + _true_indicator(ma50 > ma100, valid)
        + _true_indicator(ma100 > ma200, valid)
    )


def breakout_proximity(
    prices: pd.DataFrame, high_window: int, confirmation_window: int
) -> pd.DataFrame:
    prior_high = prices.shift(1).rolling(high_window).max()
    return prices.divide(prior_high) - 1.0 + 0.5 * simple_momentum(prices, confirmation_window)


def acceleration_1m_vs_3m(prices: pd.DataFrame) -> pd.DataFrame:
    return annualized_log_return_rate(
        prices,
        end_lag=0,
        span=21,
    ) - annualized_log_return_rate(prices, end_lag=21, span=63)


def acceleration_3m_vs_6m(prices: pd.DataFrame) -> pd.DataFrame:
    return annualized_log_return_rate(
        prices,
        end_lag=0,
        span=63,
    ) - annualized_log_return_rate(prices, end_lag=63, span=126)


def acceleration_6m_vs_12m(prices: pd.DataFrame) -> pd.DataFrame:
    return annualized_log_return_rate(
        prices,
        end_lag=0,
        span=126,
    ) - annualized_log_return_rate(prices, end_lag=126, span=252)


def ulcer_adjusted_momentum(prices: pd.DataFrame) -> pd.DataFrame:
    rolling_high = prices.rolling(126).max()
    drawdown = prices.divide(rolling_high) - 1.0
    ulcer = drawdown.pow(2).rolling(126).mean().pow(0.5)
    return _safe_div(total_return_momentum(prices, 126, skip=10), ulcer)


def smooth_return_momentum(prices: pd.DataFrame) -> pd.DataFrame:
    returns = mark_to_last_observed_returns(prices)
    momentum = simple_momentum(prices, 126)
    smoothness_penalty = returns.rolling(126).std()
    return momentum - smoothness_penalty


def range_position_252d_momentum(prices: pd.DataFrame) -> pd.DataFrame:
    rolling_low = prices.rolling(252).min()
    rolling_high = prices.rolling(252).max()
    range_position = _safe_div(prices - rolling_low, rolling_high - rolling_low) - 0.5
    return total_return_momentum(prices, 252, skip=21) + range_position


def equal_weight_market_return(
    prices: pd.DataFrame,
    eligibility_mask: pd.DataFrame | None = None,
) -> pd.Series:
    """Build a date-level proxy from returns eligible on that same date."""

    returns = mark_to_last_observed_returns(prices)
    eligible = _aligned_eligibility_mask(prices, eligibility_mask)
    if eligible is not None:
        returns = returns.where(eligible)
    return returns.mean(axis=1, skipna=True).where(returns.notna().any(axis=1))


def leave_one_out_equal_weight_market_returns(
    prices: pd.DataFrame,
    eligibility_mask: pd.DataFrame | None = None,
    *,
    minimum_peer_count: int = MINIMUM_PEER_RETURN_COUNT,
) -> pd.DataFrame:
    """Return each security's date-level eligible equal-weight peer return.

    A security never contributes to its own proxy.  A date/security pair is
    unavailable unless at least ``minimum_peer_count`` other eligible returns
    are finite; missing peer returns are excluded rather than imputed.
    """

    if minimum_peer_count < 1:
        raise ValueError("minimum_peer_count must be at least one")
    returns = mark_to_last_observed_returns(prices)
    eligible = _aligned_eligibility_mask(prices, eligibility_mask)
    eligible_returns = returns.where(eligible) if eligible is not None else returns
    finite = eligible_returns.notna()
    total = eligible_returns.sum(axis=1, min_count=1)
    count = finite.sum(axis=1)
    total_matrix = pd.DataFrame(
        np.broadcast_to(total.to_numpy()[:, None], eligible_returns.shape),
        index=eligible_returns.index,
        columns=eligible_returns.columns,
    )
    count_matrix = pd.DataFrame(
        np.broadcast_to(count.to_numpy()[:, None], eligible_returns.shape),
        index=eligible_returns.index,
        columns=eligible_returns.columns,
    )
    peer_sum = total_matrix - eligible_returns.fillna(0.0)
    peer_count = count_matrix - finite.astype(int)
    return peer_sum.divide(peer_count.where(peer_count.ge(minimum_peer_count)))


def residual_twelve_one_momentum(
    prices: pd.DataFrame,
    eligibility_mask: pd.DataFrame | None = None,
) -> pd.DataFrame:
    stock_return = mark_to_last_observed_returns(prices).shift(21)
    market_return = leave_one_out_equal_weight_market_returns(
        prices,
        eligibility_mask,
    ).shift(21)
    stock_mean = stock_return.rolling(252).mean()
    market_mean = market_return.rolling(252).mean()
    covariance = stock_return.mul(market_return).rolling(252).mean() - stock_mean.mul(market_mean)
    market_variance = market_return.pow(2).rolling(252).mean() - market_mean.pow(2)
    beta = covariance.divide(market_variance.replace(0, np.nan))
    return stock_return.rolling(252).sum() - beta.mul(market_return.rolling(252).sum())


def excess_information_ratio_6m(
    prices: pd.DataFrame,
    eligibility_mask: pd.DataFrame | None = None,
) -> pd.DataFrame:
    returns = mark_to_last_observed_returns(prices)
    peer_return = leave_one_out_equal_weight_market_returns(
        prices,
        eligibility_mask,
    )
    excess = returns.sub(peer_return)
    mean = excess.rolling(126).mean() * TRADING_DAYS
    tracking_error = excess.rolling(126).std() * np.sqrt(TRADING_DAYS)
    return _safe_div(mean, tracking_error)


def up_down_capture_momentum(
    prices: pd.DataFrame,
    eligibility_mask: pd.DataFrame | None = None,
) -> pd.DataFrame:
    returns = mark_to_last_observed_returns(prices)
    market_return = leave_one_out_equal_weight_market_returns(
        prices,
        eligibility_mask,
    )
    up_returns = returns.where(market_return.gt(0))
    down_returns = returns.where(market_return.lt(0))
    up_count = up_returns.rolling(126).count()
    down_count = down_returns.rolling(126).count()
    up_mean = up_returns.rolling(126, min_periods=MINIMUM_CONDITIONAL_REGIME_OBSERVATIONS).mean()
    down_mean = down_returns.rolling(
        126,
        min_periods=MINIMUM_CONDITIONAL_REGIME_OBSERVATIONS,
    ).mean()
    adequate_regimes = up_count.ge(MINIMUM_CONDITIONAL_REGIME_OBSERVATIONS) & down_count.ge(
        MINIMUM_CONDITIONAL_REGIME_OBSERVATIONS
    )
    return (up_mean - down_mean.abs()).where(adequate_regimes)


def tail_resilient_momentum(prices: pd.DataFrame) -> pd.DataFrame:
    returns = mark_to_last_observed_returns(prices)
    left_tail = returns.rolling(126).quantile(0.05)
    return total_return_momentum(prices, 126, skip=10) + left_tail


def jump_excluded_momentum(prices: pd.DataFrame) -> pd.DataFrame:
    formation_returns = mark_to_last_observed_returns(prices).shift(10)
    return formation_returns.rolling(126).sum() - formation_returns.rolling(126).max()


def high_persistence_momentum(prices: pd.DataFrame) -> pd.DataFrame:
    rolling_high = prices.rolling(126).max()
    near_high = prices.ge(rolling_high * 0.98).astype(float).where(rolling_high.notna())
    return near_high.rolling(63).mean()


FactorFn = Callable[[pd.DataFrame], pd.DataFrame]


@dataclass(frozen=True, slots=True)
class FactorSpec:
    name: str
    category: str
    formula: str
    description: str
    validation_notes: str
    fn: FactorFn
    method_class: str = "internal_heuristic"
    canonical_replication: bool = False
    canonical_name: str = ""
    formula_version: int = 1
    formation_end_lag_days: int | None = None
    component_units: str = "unspecified"
    limitations: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    compatibility_alias_of: str | None = None
    selection_eligible: bool = True
    minimum_history_sessions: int = 1


_BASE_FACTOR_SPECS: dict[str, FactorSpec] = {
    spec.name: spec
    for spec in [
        FactorSpec(
            "mom_12_1",
            "traditional",
            "P[t-21] / P[t-273] - 1",
            "Traditional 12-1 cross-sectional total return momentum.",
            "Manual shifted-return and no-lookahead tests.",
            lambda p: total_return_momentum(p, 252, skip=21),
        ),
        FactorSpec(
            "mom_9_1",
            "traditional",
            "P[t-21] / P[t-210] - 1",
            "Nine-month skipped return momentum.",
            "Manual shifted-return and no-lookahead tests.",
            lambda p: total_return_momentum(p, 189, skip=21),
        ),
        FactorSpec(
            "mom_6_1",
            "traditional",
            "P[t-21] / P[t-147] - 1",
            "Traditional 6-1 cross-sectional total return momentum.",
            "Manual shifted-return and no-lookahead tests.",
            lambda p: total_return_momentum(p, 126, skip=21),
        ),
        FactorSpec(
            "mom_12_2",
            "traditional",
            "P[t-42] / P[t-294] - 1",
            "Twelve-month momentum with a two-month skip to reduce reversal contamination.",
            "Independent raw-shift golden tests.",
            deep_skip_twelve_month_momentum,
        ),
        FactorSpec(
            "mom_3_1",
            "traditional",
            "P[t-21] / P[t-84] - 1",
            "Traditional 3-1 skipped return momentum.",
            "Independent shifted-return and no-lookahead tests.",
            lambda p: total_return_momentum(p, 63, skip=21),
        ),
        FactorSpec(
            "mom_10d",
            "recent",
            "P[t] / P[t-10] - 1",
            "Ten-trading-day short-horizon momentum with high-turnover warning.",
            "Literal golden-vector simple-return tests and turnover warning audit.",
            lambda p: simple_momentum(p, 10),
        ),
        FactorSpec(
            "mom_6m_unskipped",
            "recent",
            "P[t] / P[t-126] - 1",
            "Six-month recent momentum without a skip window.",
            "Independent raw-shift golden tests.",
            unskipped_six_month_momentum,
        ),
        FactorSpec(
            "mom_3m",
            "recent",
            "P[t] / P[t-63] - 1",
            "Three-month recent momentum without skip month.",
            "Simple-return fixture tests.",
            lambda p: simple_momentum(p, 63),
        ),
        FactorSpec(
            "mom_2m",
            "recent",
            "P[t] / P[t-42] - 1",
            "Two-month short-horizon momentum for fast leadership changes.",
            "Independent raw-shift golden tests.",
            two_month_momentum,
        ),
        FactorSpec(
            "mom_2_1",
            "recent",
            "P[t-21] / P[t-63] - 1",
            "Two-month momentum that skips the most recent month.",
            "Independent raw-shift golden tests.",
            skipped_two_month_momentum,
        ),
        FactorSpec(
            "mom_6m",
            "recent",
            "P[t-10] / P[t-136] - 1",
            "Six-month momentum ending ten trading days before the signal date to avoid very recent reversal noise.",
            "Independent shifted-return and no-lookahead tests; intentionally distinct from mom_6m_unskipped.",
            skipped_ten_day_six_month_momentum,
        ),
        FactorSpec(
            "mom_12m",
            "recent",
            "P[t] / P[t-252] - 1",
            "Twelve-month simple momentum without skip month.",
            "Independent simple-return and no-lookahead tests.",
            lambda p: simple_momentum(p, 252),
        ),
        FactorSpec(
            "mom_1m",
            "recent",
            "P[t] / P[t-21] - 1",
            "One-month short-horizon momentum.",
            "Simple-return fixture tests.",
            lambda p: simple_momentum(p, 21),
        ),
        FactorSpec(
            "multi_horizon",
            "composite",
            "0.15*1m + 0.25*3m(skip5) + 0.30*6m(skip10) + 0.30*12m(skip21)",
            "Weighted 1/3/6/12-month multi-horizon momentum composite.",
            "Component helper tests plus output audit.",
            multi_horizon_momentum,
        ),
        FactorSpec(
            "vol_adjusted",
            "risk_adjusted",
            "6m(skip10) / annualized_vol_63d",
            "Six-month momentum scaled by recent annualized volatility.",
            "Division-by-zero and finite coverage audit.",
            volatility_adjusted_momentum,
        ),
        FactorSpec(
            "risk_adjusted",
            "risk_adjusted",
            "annualized_mean_return_126d / annualized_vol_126d",
            "Rolling Sharpe-like annualized return divided by volatility.",
            "Rolling mean/vol helper tests.",
            risk_adjusted_momentum,
        ),
        FactorSpec(
            "downside_risk_adjusted",
            "risk_adjusted",
            "6m(skip10) / annualized_downside_vol_126d",
            "Momentum scaled by downside volatility only.",
            "Downside fixture tests and finite audit.",
            downside_risk_adjusted_momentum,
        ),
        FactorSpec(
            "dual_momentum",
            "trend",
            "eligible_percentile_rank(6m(skip10)) where P > MA200; otherwise unavailable",
            "Eligible-universe relative momentum with an absolute MA200 trend gate.",
            "Eligibility isolation, MA200 gate, and no-lookahead audit.",
            dual_momentum,
        ),
        FactorSpec(
            "ma_trend",
            "trend",
            "P/MA200 - 1 + 0.5*(MA50/MA200 - 1)",
            "Trend persistence from price/MA200 and MA50/MA200 structure.",
            "Moving-average fixture tests.",
            moving_average_trend,
        ),
        FactorSpec(
            "time_series_trend",
            "trend",
            "I(P>MA20)+I(MA20>MA100)+I(MA100>MA200)",
            "Discrete time-series trend stack across short/intermediate/long averages.",
            "Bounded 0..3 output audit.",
            time_series_trend,
        ),
        FactorSpec(
            "drawdown_aware",
            "drawdown",
            "6m(skip10) + P/rolling_high_126 - 1",
            "Six-month momentum penalized by recent drawdown from rolling high.",
            "Drawdown sign and no-lookahead audit.",
            drawdown_aware_momentum,
        ),
        FactorSpec(
            "high_52w",
            "drawdown",
            "P / rolling_high_252 - 1",
            "Closeness to 52-week high; less negative is stronger.",
            "Manual rolling-high fixture tests.",
            high_52week_proximity,
        ),
        FactorSpec(
            "high_26w",
            "drawdown",
            "P / rolling_high_126 - 1",
            "Closeness to a 26-week high for intermediate breakout confirmation.",
            "Independent rolling-high golden tests.",
            high_26week_proximity,
        ),
        FactorSpec(
            "breakout_63d",
            "breakout",
            "P/prior_rolling_high_63 - 1 + 0.5*1m",
            "Recent breakout above the prior 63-session high with one-month confirmation.",
            "Prior rolling-high plus 1m fixture tests.",
            breakout_63d,
        ),
        FactorSpec(
            "breakout_126d",
            "breakout",
            "P/prior_rolling_high_126 - 1 + 0.5*3m",
            "Intermediate breakout above the prior 126-session high with three-month confirmation.",
            "Independent prior rolling-high golden tests.",
            breakout_126d,
        ),
        FactorSpec(
            "reversal_adjusted",
            "reversal",
            "12-1 momentum - 0.35*1m momentum",
            "12-1 momentum adjusted for short-term reversal risk.",
            "Component helper tests plus no-lookahead audit.",
            reversal_adjusted_momentum,
        ),
        FactorSpec(
            "acceleration",
            "acceleration",
            "annualized_log_rate(0,63) - annualized_log_rate(63,126)",
            "Non-overlapping three-versus-six-month annualized log-return acceleration.",
            "Non-overlap, constant-growth, and direction tests.",
            acceleration_momentum,
        ),
        FactorSpec(
            "short_acceleration",
            "acceleration",
            "annualized_log_rate(0,21) - annualized_log_rate(21,63)",
            "Non-overlapping one-versus-three-month annualized log-return acceleration.",
            "Non-overlap, constant-growth, and direction tests.",
            short_acceleration_momentum,
        ),
        FactorSpec(
            "decay_adjusted",
            "acceleration",
            "6m(skip10) - 0.25*abs(1m momentum)",
            "Six-month momentum penalized when very recent moves look overextended.",
            "Independent raw-shift golden tests.",
            decay_adjusted_momentum,
        ),
        FactorSpec(
            "consistency",
            "quality",
            "6m(skip10) * positive_daily_return_ratio_126d(skip10)",
            "Rewards skipped six-month momentum earned consistently over the same formation window.",
            "Aligned positive-ratio fixture tests.",
            consistency_momentum,
        ),
        FactorSpec(
            "persistent_12_1",
            "quality",
            "12m(skip21) * positive_daily_return_ratio_252d(skip21)",
            "Long-horizon skipped momentum scaled by the share of positive daily returns in the skipped formation window.",
            "Positive-ratio and no-lookahead tests.",
            persistent_twelve_one_momentum,
        ),
        FactorSpec(
            "low_vol_momentum",
            "risk_adjusted",
            "6m(skip10) - annualized_vol_63d",
            "Momentum penalized by high recent volatility.",
            "Low-vol ranking fixture tests.",
            low_vol_momentum,
        ),
        FactorSpec(
            "stability_adjusted",
            "risk_adjusted",
            "6m(skip10) / (1 + annualized_vol_126d)",
            "Six-month momentum damped by one-year realized volatility from price returns.",
            "Independent volatility golden tests.",
            stability_adjusted_momentum,
        ),
        FactorSpec(
            "relative_strength_6m",
            "cross_sectional",
            "cross-sectional percentile_rank(6m(skip10))",
            "Six-month relative-strength percentile within the eligible universe.",
            "Cross-sectional rank audit.",
            relative_strength_6m,
        ),
        FactorSpec(
            "trend_quality",
            "quality",
            "P/MA126 - 1 + rolling_mean_return_126/rolling_vol_126",
            "Combines trend slope with smoothness of returns.",
            "Rolling helper and finite audit.",
            trend_quality,
        ),
        FactorSpec(
            "gap_resistant",
            "robust",
            "compound daily returns clipped to [-8%, +8%] over 126d",
            "Momentum using clipped daily returns to reduce single-gap dominance.",
            "Clipped-return fixture tests.",
            gap_resistant_momentum,
        ),
        FactorSpec(
            "winsorized_skip",
            "robust",
            "compound daily returns clipped to [-5%, +5%] over 126d after 10d skip",
            "Skipped six-month momentum using winsorized daily returns to reduce gap dominance.",
            "Independent clipped-return golden tests.",
            winsorized_skip_momentum,
        ),
        FactorSpec(
            "price_efficiency",
            "quality",
            "6m(skip10) * |6m(skip10)| / sum_126(|daily_return shifted10|)",
            "Rewards skipped six-month momentum that traveled a direct, low-chop path over the same formation window.",
            "Aligned path-efficiency fixture tests and division-by-zero audit.",
            price_efficiency_momentum,
        ),
        FactorSpec(
            "range_position",
            "range",
            "6m(skip10) + (P-low_126)/(high_126-low_126) - 0.5",
            "Combines six-month momentum with where price sits inside its trailing range.",
            "Rolling-range fixture tests and flat-range audit.",
            range_position_momentum,
        ),
        FactorSpec(
            "range_position_252d",
            "range",
            "12m(skip21) + (P-low_252)/(high_252-low_252) - 0.5",
            "Combines long-horizon skipped momentum with position inside a 52-week range.",
            "Independent rolling-range golden tests.",
            range_position_252d_momentum,
        ),
        FactorSpec(
            "median_return_3m",
            "robust",
            "median(daily_return, 63d) * 63",
            "Three-month median daily return momentum to reduce outlier sensitivity.",
            "Median-return golden-vector and outlier-gap tests.",
            lambda p: median_return_momentum(p, 63),
        ),
        FactorSpec(
            "median_return_6m",
            "robust",
            "median(daily_return, 126d) * 126",
            "Six-month median daily return momentum to reduce outlier sensitivity.",
            "Median-return golden-vector and no-lookahead tests.",
            lambda p: median_return_momentum(p, 126),
        ),
        FactorSpec(
            "winsorized_3m",
            "robust",
            "compound clipped [-8%, +8%] daily returns over 63d",
            "Three-month winsorized compounded momentum.",
            "Winsorized golden-vector and outlier-gap tests.",
            lambda p: winsorized_momentum(p, 63),
        ),
        FactorSpec(
            "winsorized_12m",
            "robust",
            "compound clipped [-8%, +8%] daily returns over 252d",
            "Twelve-month winsorized compounded momentum.",
            "Winsorized no-lookahead and edge-case tests.",
            lambda p: winsorized_momentum(p, 252),
        ),
        FactorSpec(
            "vol_adjusted_3m",
            "risk_adjusted",
            "3m simple momentum / annualized_vol_63d",
            "Three-month momentum scaled by recent annualized volatility.",
            "Division-by-zero and finite coverage audit.",
            lambda p: volatility_adjusted_simple_momentum(p, 63, 63),
        ),
        FactorSpec(
            "vol_adjusted_12m",
            "risk_adjusted",
            "12-1 momentum / annualized_vol_126d",
            "Twelve-minus-one momentum scaled by intermediate volatility.",
            "Division-by-zero and no-lookahead audit.",
            lambda p: _safe_div(
                total_return_momentum(p, 252, skip=21),
                mark_to_last_observed_returns(p).rolling(126).std() * np.sqrt(TRADING_DAYS),
            ),
        ),
        FactorSpec(
            "downside_adjusted_12m",
            "risk_adjusted",
            "12-1 momentum / annualized_downside_vol_252d",
            "Twelve-minus-one momentum scaled by downside volatility.",
            "Downside risk edge-case tests.",
            lambda p: downside_adjusted_total_momentum(p, 252, 21, 252),
        ),
        FactorSpec(
            "ma_slope_50",
            "trend",
            "MA50[t] / MA50[t-21] - 1",
            "One-month slope of the 50-day moving average.",
            "Moving-average slope fixture tests.",
            moving_average_slope,
        ),
        FactorSpec(
            "price_vs_ma200",
            "trend",
            "P / MA200 - 1",
            "Distance of price above/below the 200-day moving average.",
            "Moving-average fixture tests.",
            price_vs_ma200,
        ),
        FactorSpec(
            "ma_stack_quality",
            "trend",
            "I(P>MA20)+I(MA20>MA50)+I(MA50>MA100)+I(MA100>MA200)",
            "Four-step moving-average stack quality score.",
            "Bounded 0..4 output and no-lookahead audit.",
            moving_average_stack_quality,
        ),
        FactorSpec(
            "breakout_20d",
            "breakout",
            "P/prior_rolling_high_20 - 1 + 0.5*10d",
            "Short breakout above the prior 20-session high with ten-day confirmation.",
            "Prior rolling-high golden-vector tests.",
            lambda p: breakout_proximity(p, 20, 10),
        ),
        FactorSpec(
            "accel_1m_vs_3m",
            "acceleration",
            "annualized_log_rate(0,21) - annualized_log_rate(21,63)",
            "Acceleration from the preceding three-month rate to the recent one-month rate.",
            "Non-overlapping log-rate golden tests.",
            acceleration_1m_vs_3m,
        ),
        FactorSpec(
            "accel_3m_vs_6m",
            "acceleration",
            "annualized_log_rate(0,63) - annualized_log_rate(63,126)",
            "Acceleration from the preceding six-month rate to the recent three-month rate.",
            "Non-overlapping log-rate golden tests.",
            acceleration_3m_vs_6m,
        ),
        FactorSpec(
            "accel_6m_vs_12m",
            "acceleration",
            "annualized_log_rate(0,126) - annualized_log_rate(126,252)",
            "Acceleration from the preceding twelve-month rate to the recent six-month rate.",
            "Non-overlapping log-rate golden tests.",
            acceleration_6m_vs_12m,
        ),
        FactorSpec(
            "ulcer_adjusted",
            "drawdown",
            "6m(skip10) / sqrt(mean(drawdown_126^2, 126d))",
            "Momentum scaled by Ulcer-style drawdown severity.",
            "Drawdown denominator and finite audit.",
            ulcer_adjusted_momentum,
        ),
        FactorSpec(
            "smooth_return_6m",
            "quality",
            "6m simple momentum - rolling_std_daily_return_126d",
            "Six-month return momentum penalized by daily return roughness.",
            "Smoothness edge-case tests.",
            smooth_return_momentum,
        ),
        FactorSpec(
            "residual_12_1",
            "cross_sectional",
            "sum_252(return shifted21) - beta_252_to_date_eligible_leave_one_out_equal_weight_peers * sum_252(peer_return shifted21)",
            "Twelve-minus-one beta-adjusted momentum versus date-level eligible leave-one-out peers.",
            "Leave-one-out proxy, rolling beta, rank-distinctness, and no-lookahead tests.",
            residual_twelve_one_momentum,
        ),
        FactorSpec(
            "excess_ir_6m",
            "cross_sectional",
            "annualized_mean(excess_return_vs_date_eligible_leave_one_out_peers_126d) / annualized_tracking_error_126d",
            "Six-month information-ratio style momentum versus date-level eligible leave-one-out peers.",
            "Leave-one-out proxy, tracking-error denominator, and no-lookahead tests.",
            excess_information_ratio_6m,
        ),
        FactorSpec(
            "up_down_capture_6m",
            "asymmetry",
            "mean_126(return | leave_one_out_peer_return>0, n>=21) - abs(mean_126(return | leave_one_out_peer_return<0, n>=21))",
            "Conditional return asymmetry versus eligible leave-one-out peers, with both regimes observed.",
            "No-imputation regime coverage, leave-one-out isolation, and no-lookahead tests.",
            up_down_capture_momentum,
        ),
        FactorSpec(
            "tail_resilient_6m",
            "tail_risk",
            "6m(skip10) + q05(daily_return,126d)",
            "Six-month skipped momentum penalized by poor left-tail daily returns.",
            "Rolling quantile edge-case and no-lookahead tests.",
            tail_resilient_momentum,
        ),
        FactorSpec(
            "jump_excluded_6m",
            "robust",
            "sum_126(daily_return shifted10) - max_126(daily_return shifted10)",
            "Formation-window momentum that removes the single largest daily jump to reduce one-day gap dominance.",
            "Independent shifted-return and outlier-resistance tests.",
            jump_excluded_momentum,
        ),
        FactorSpec(
            "high_persistence_6m",
            "quality",
            "mean_63(I(P >= 0.98*rolling_high_126))",
            "Fraction of recent days spent near a six-month high, capturing persistent leadership rather than one-day proximity.",
            "Rolling-high persistence and no-lookahead tests.",
            high_persistence_momentum,
        ),
    ]
}


def _factor_method_metadata(
    method_class: str,
    canonical_name: str,
    formation_end_lag_days: int | None,
    component_units: str,
    minimum_history_sessions: int,
    *,
    formula_version: int = 1,
    limitations: tuple[str, ...] = (
        "Research ranking signal; not a full academic portfolio replication.",
    ),
    references: tuple[str, ...] = (),
    compatibility_alias_of: str | None = None,
    selection_eligible: bool = True,
) -> dict[str, object]:
    if method_class == "literature_inspired_proxy" and not references:
        # A formula variant without an explicit source is an internal research
        # proxy, not evidence of a literature-backed implementation.
        method_class = "research_proxy"
    return {
        "method_class": method_class,
        "canonical_replication": False,
        "canonical_name": canonical_name,
        "formula_version": formula_version,
        "formation_end_lag_days": formation_end_lag_days,
        "component_units": component_units,
        "limitations": limitations,
        "references": references,
        "compatibility_alias_of": compatibility_alias_of,
        "selection_eligible": selection_eligible,
        "minimum_history_sessions": minimum_history_sessions,
    }


MOMENTUM_REFERENCE = "https://doi.org/10.1111/j.1540-6261.1993.tb04702.x"
HIGH_52W_REFERENCE = "https://doi.org/10.1111/j.1540-6261.2004.00695.x"
TIME_SERIES_MOMENTUM_REFERENCE = "https://doi.org/10.1016/j.jfineco.2011.11.003"
RESIDUAL_MOMENTUM_REFERENCE = "https://doi.org/10.1016/j.jempfin.2011.01.003"
DUAL_MOMENTUM_REFERENCE = "https://doi.org/10.2139/ssrn.2042750"
ACCELERATION_REFERENCE = "https://doi.org/10.1016/j.physa.2020.125367"


FACTOR_METHOD_METADATA: dict[str, dict[str, object]] = {
    "mom_12_1": _factor_method_metadata(
        "canonical_signal_formula",
        "mom_12_1",
        21,
        "simple_total_return",
        274,
        references=(MOMENTUM_REFERENCE,),
    ),
    "mom_9_1": _factor_method_metadata(
        "canonical_signal_formula",
        "mom_9_1",
        21,
        "simple_total_return",
        211,
        references=(MOMENTUM_REFERENCE,),
    ),
    "mom_6_1": _factor_method_metadata(
        "canonical_signal_formula",
        "mom_6_1",
        21,
        "simple_total_return",
        148,
        references=(MOMENTUM_REFERENCE,),
    ),
    "mom_12_2": _factor_method_metadata(
        "canonical_signal_formula",
        "mom_12_2",
        42,
        "simple_total_return",
        295,
        references=(MOMENTUM_REFERENCE,),
    ),
    "mom_3_1": _factor_method_metadata(
        "canonical_signal_formula",
        "mom_3_1",
        21,
        "simple_total_return",
        85,
        references=(MOMENTUM_REFERENCE,),
    ),
    "mom_10d": _factor_method_metadata(
        "literature_inspired_proxy", "mom_10d", 0, "simple_total_return", 11
    ),
    "mom_6m_unskipped": _factor_method_metadata(
        "literature_inspired_proxy", "mom_6m_unskipped", 0, "simple_total_return", 127
    ),
    "mom_3m": _factor_method_metadata(
        "literature_inspired_proxy", "mom_3m", 0, "simple_total_return", 64
    ),
    "mom_2m": _factor_method_metadata(
        "literature_inspired_proxy", "mom_2m", 0, "simple_total_return", 43
    ),
    "mom_2_1": _factor_method_metadata(
        "literature_inspired_proxy", "mom_2_1", 21, "simple_total_return", 64
    ),
    "mom_6m": _factor_method_metadata(
        "literature_inspired_proxy", "mom_6m", 10, "simple_total_return", 137
    ),
    "mom_12m": _factor_method_metadata(
        "literature_inspired_proxy", "mom_12m", 0, "simple_total_return", 253
    ),
    "mom_1m": _factor_method_metadata(
        "literature_inspired_proxy", "mom_1m", 0, "simple_total_return", 22
    ),
    "multi_horizon": _factor_method_metadata(
        "internal_heuristic", "multi_horizon_weighted_return", None, "weighted_simple_returns", 274
    ),
    "vol_adjusted": _factor_method_metadata(
        "literature_inspired_proxy",
        "vol_adjusted_mom_6m",
        None,
        "return_per_annualized_volatility",
        137,
    ),
    "risk_adjusted": _factor_method_metadata(
        "literature_inspired_proxy",
        "rolling_sharpe_like_6m",
        0,
        "annualized_return_per_annualized_volatility",
        127,
    ),
    "downside_risk_adjusted": _factor_method_metadata(
        "literature_inspired_proxy",
        "downside_adjusted_mom_6m",
        None,
        "return_per_annualized_downside_deviation",
        137,
        limitations=(
            "Zero downside deviation remains unavailable rather than using an invented denominator floor.",
            "Current risk overlay extends through the signal date while the momentum numerator ends at t-10.",
        ),
    ),
    "dual_momentum": _factor_method_metadata(
        "literature_inspired_proxy",
        "relative_momentum_with_ma200_absolute_gate",
        None,
        "eligible_percentile_rank_or_unavailable",
        200,
        formula_version=2,
        limitations=(
            "MA200 is an absolute-trend proxy, not excess return over a risk-free asset.",
            "Legacy factor key retained for output compatibility.",
        ),
        references=(DUAL_MOMENTUM_REFERENCE,),
    ),
    "ma_trend": _factor_method_metadata(
        "internal_heuristic", "ma50_ma200_trend_composite", 0, "raw_return_spread", 200
    ),
    "time_series_trend": _factor_method_metadata(
        "internal_heuristic",
        "ma_stack_20_100_200",
        0,
        "discrete_score_0_to_3",
        200,
        limitations=(
            "Moving-average hierarchy, not sign- or volatility-scaled time-series momentum.",
            "Legacy factor key retained for output compatibility.",
        ),
        references=(TIME_SERIES_MOMENTUM_REFERENCE,),
    ),
    "drawdown_aware": _factor_method_metadata(
        "internal_heuristic",
        "momentum_plus_drawdown_6m",
        None,
        "raw_return_sum",
        137,
        limitations=(
            "Adds raw skipped return and current drawdown without cross-sectional component standardization.",
        ),
    ),
    "high_52w": _factor_method_metadata(
        "canonical_signal_formula",
        "high_52w_proximity",
        0,
        "price_ratio_minus_one",
        252,
        references=(HIGH_52W_REFERENCE,),
    ),
    "high_26w": _factor_method_metadata(
        "literature_inspired_proxy", "high_26w_proximity", 0, "price_ratio_minus_one", 126
    ),
    "breakout_63d": _factor_method_metadata(
        "internal_heuristic", "prior_high_breakout_63d", 0, "raw_return_sum", 64, formula_version=2
    ),
    "breakout_126d": _factor_method_metadata(
        "internal_heuristic",
        "prior_high_breakout_126d",
        0,
        "raw_return_sum",
        127,
        formula_version=2,
    ),
    "reversal_adjusted": _factor_method_metadata(
        "literature_inspired_proxy",
        "reversal_adjusted_momentum",
        None,
        "weighted_simple_returns",
        274,
    ),
    "acceleration": _factor_method_metadata(
        "internal_heuristic",
        "annualized_log_accel_3m_vs_6m",
        0,
        "annualized_log_return_rate_difference",
        190,
        formula_version=2,
        references=(ACCELERATION_REFERENCE,),
        compatibility_alias_of="accel_3m_vs_6m",
        selection_eligible=False,
    ),
    "short_acceleration": _factor_method_metadata(
        "internal_heuristic",
        "annualized_log_accel_1m_vs_3m",
        0,
        "annualized_log_return_rate_difference",
        85,
        formula_version=2,
        references=(ACCELERATION_REFERENCE,),
        compatibility_alias_of="accel_1m_vs_3m",
        selection_eligible=False,
    ),
    "decay_adjusted": _factor_method_metadata(
        "internal_heuristic", "recent_move_penalized_mom_6m", None, "weighted_simple_returns", 137
    ),
    "consistency": _factor_method_metadata(
        "literature_inspired_proxy",
        "formation_aligned_consistency_mom_6m",
        10,
        "simple_return_times_positive_ratio",
        137,
        formula_version=2,
    ),
    "persistent_12_1": _factor_method_metadata(
        "literature_inspired_proxy",
        "persistent_mom_12_1",
        21,
        "simple_return_times_positive_ratio",
        274,
    ),
    "low_vol_momentum": _factor_method_metadata(
        "literature_inspired_proxy",
        "low_vol_momentum",
        None,
        "mixed_horizon_return_difference",
        137,
        limitations=(
            "Subtracts annualized volatility from a six-month return without cross-sectional component standardization.",
        ),
    ),
    "stability_adjusted": _factor_method_metadata(
        "internal_heuristic", "stability_adjusted_mom_6m", None, "return_ratio", 137
    ),
    "relative_strength_6m": _factor_method_metadata(
        "literature_inspired_proxy",
        "eligible_percentile_rank_mom_6m",
        10,
        "eligible_percentile_rank",
        137,
        compatibility_alias_of="mom_6m",
        selection_eligible=False,
        limitations=("Monotonic rank transform of mom_6m; retained for output compatibility.",),
    ),
    "trend_quality": _factor_method_metadata(
        "internal_heuristic", "trend_quality_composite", 0, "raw_component_sum", 127
    ),
    "gap_resistant": _factor_method_metadata(
        "literature_inspired_proxy", "gap_clipped_mom_6m", 0, "compounded_clipped_return", 127
    ),
    "winsorized_skip": _factor_method_metadata(
        "literature_inspired_proxy", "winsorized_skip_mom_6m", 10, "compounded_clipped_return", 137
    ),
    "price_efficiency": _factor_method_metadata(
        "literature_inspired_proxy",
        "formation_aligned_price_efficiency_mom_6m",
        10,
        "simple_return_times_path_efficiency",
        137,
        formula_version=2,
    ),
    "range_position": _factor_method_metadata(
        "internal_heuristic",
        "range_position_mom_6m",
        None,
        "raw_component_sum",
        137,
        limitations=(
            "Adds a current range-position overlay to skipped return without component standardization.",
        ),
    ),
    "range_position_252d": _factor_method_metadata(
        "internal_heuristic",
        "range_position_mom_12_1",
        None,
        "raw_component_sum",
        274,
        limitations=(
            "Adds a current range-position overlay to skipped return without component standardization.",
        ),
    ),
    "median_return_3m": _factor_method_metadata(
        "literature_inspired_proxy",
        "median_daily_return_3m",
        0,
        "linearized_median_daily_return",
        64,
    ),
    "median_return_6m": _factor_method_metadata(
        "literature_inspired_proxy",
        "median_daily_return_6m",
        0,
        "linearized_median_daily_return",
        127,
    ),
    "winsorized_3m": _factor_method_metadata(
        "literature_inspired_proxy", "winsorized_mom_3m", 0, "compounded_clipped_return", 64
    ),
    "winsorized_12m": _factor_method_metadata(
        "literature_inspired_proxy", "winsorized_mom_12m", 0, "compounded_clipped_return", 253
    ),
    "vol_adjusted_3m": _factor_method_metadata(
        "literature_inspired_proxy",
        "vol_adjusted_mom_3m",
        0,
        "return_per_annualized_volatility",
        64,
    ),
    "vol_adjusted_12m": _factor_method_metadata(
        "literature_inspired_proxy",
        "vol_adjusted_mom_12_1",
        None,
        "return_per_annualized_volatility",
        274,
    ),
    "downside_adjusted_12m": _factor_method_metadata(
        "literature_inspired_proxy",
        "downside_adjusted_mom_12_1",
        None,
        "return_per_annualized_downside_deviation",
        274,
        limitations=(
            "Zero downside deviation remains unavailable rather than using an invented denominator floor.",
            "Current risk overlay extends through the signal date while the momentum numerator ends at t-21.",
        ),
    ),
    "ma_slope_50": _factor_method_metadata(
        "literature_inspired_proxy", "ma50_slope_1m", 0, "moving_average_return", 71
    ),
    "price_vs_ma200": _factor_method_metadata(
        "literature_inspired_proxy", "price_vs_ma200", 0, "price_ratio_minus_one", 200
    ),
    "ma_stack_quality": _factor_method_metadata(
        "internal_heuristic", "ma_stack_20_50_100_200", 0, "discrete_score_0_to_4", 200
    ),
    "breakout_20d": _factor_method_metadata(
        "internal_heuristic", "prior_high_breakout_20d", 0, "raw_return_sum", 21, formula_version=2
    ),
    "accel_1m_vs_3m": _factor_method_metadata(
        "internal_heuristic",
        "annualized_log_accel_1m_vs_3m",
        0,
        "annualized_log_return_rate_difference",
        85,
        formula_version=2,
        references=(ACCELERATION_REFERENCE,),
    ),
    "accel_3m_vs_6m": _factor_method_metadata(
        "internal_heuristic",
        "annualized_log_accel_3m_vs_6m",
        0,
        "annualized_log_return_rate_difference",
        190,
        formula_version=2,
        references=(ACCELERATION_REFERENCE,),
    ),
    "accel_6m_vs_12m": _factor_method_metadata(
        "internal_heuristic",
        "annualized_log_accel_6m_vs_12m",
        0,
        "annualized_log_return_rate_difference",
        379,
        formula_version=2,
        references=(ACCELERATION_REFERENCE,),
    ),
    "ulcer_adjusted": _factor_method_metadata(
        "literature_inspired_proxy",
        "ulcer_adjusted_mom_6m",
        None,
        "return_per_ulcer_index",
        251,
        limitations=(
            "Zero Ulcer denominator remains unavailable rather than using an invented floor.",
            "Small positive denominators can produce large raw scores; portfolios use ranks, not score-proportional weights.",
        ),
    ),
    "smooth_return_6m": _factor_method_metadata(
        "internal_heuristic",
        "daily_roughness_penalized_mom_6m",
        0,
        "mixed_horizon_return_difference",
        127,
        limitations=(
            "Subtracts one-day return volatility from a six-month cumulative return without unit standardization.",
        ),
    ),
    "residual_12_1": _factor_method_metadata(
        "literature_inspired_proxy",
        "eligible_peer_beta_adjusted_return_12_1",
        21,
        "arithmetic_return_sum",
        274,
        formula_version=2,
        limitations=(
            "Single leave-one-out equal-weight peer proxy, not a multi-factor residual regression.",
            "Arithmetic daily-return sum omits alpha and idiosyncratic-volatility standardization.",
            "Legacy factor key retained for output compatibility.",
        ),
        references=(RESIDUAL_MOMENTUM_REFERENCE,),
    ),
    "excess_ir_6m": _factor_method_metadata(
        "literature_inspired_proxy",
        "leave_one_out_excess_ir_6m",
        0,
        "annualized_excess_return_per_tracking_error",
        127,
        formula_version=2,
    ),
    "up_down_capture_6m": _factor_method_metadata(
        "literature_inspired_proxy",
        "conditional_return_asymmetry_6m",
        0,
        "conditional_daily_return_difference",
        127,
        formula_version=2,
        limitations=(
            "Return difference, not benchmark up/down capture ratios.",
            "Both regimes require at least 21 finite stock-return observations.",
            "Legacy factor key retained for output compatibility.",
        ),
    ),
    "tail_resilient_6m": _factor_method_metadata(
        "internal_heuristic",
        "left_tail_adjusted_mom_6m",
        None,
        "mixed_horizon_return_sum",
        137,
        limitations=(
            "Adds a one-day return quantile to a six-month cumulative return without component standardization.",
            "Current tail overlay extends through the signal date while the momentum numerator ends at t-10.",
        ),
    ),
    "jump_excluded_6m": _factor_method_metadata(
        "literature_inspired_proxy",
        "largest_jump_excluded_mom_6m",
        10,
        "arithmetic_daily_return_sum",
        137,
    ),
    "high_persistence_6m": _factor_method_metadata(
        "literature_inspired_proxy", "high_persistence_6m", 0, "fraction_0_to_1", 188
    ),
}

if set(FACTOR_METHOD_METADATA) != set(_BASE_FACTOR_SPECS):
    missing = sorted(set(_BASE_FACTOR_SPECS) - set(FACTOR_METHOD_METADATA))
    extra = sorted(set(FACTOR_METHOD_METADATA) - set(_BASE_FACTOR_SPECS))
    raise RuntimeError(f"factor metadata registry mismatch: missing={missing}, extra={extra}")

FACTOR_SPECS: dict[str, FactorSpec] = {
    name: replace(spec, **FACTOR_METHOD_METADATA[name]) for name, spec in _BASE_FACTOR_SPECS.items()
}

FACTOR_DEFINITIONS: dict[str, FactorFn] = {name: spec.fn for name, spec in FACTOR_SPECS.items()}

EligibilityAwareFactorFn = Callable[[pd.DataFrame, pd.DataFrame | None], pd.DataFrame]
ELIGIBILITY_AWARE_FACTOR_FNS: dict[str, EligibilityAwareFactorFn] = {
    "dual_momentum": dual_momentum,
    "relative_strength_6m": relative_strength_6m,
    "residual_12_1": residual_twelve_one_momentum,
    "excess_ir_6m": excess_information_ratio_6m,
    "up_down_capture_6m": up_down_capture_momentum,
}


def iter_factor_scores(
    prices: pd.DataFrame,
    eligibility_mask: pd.DataFrame | None = None,
) -> Iterator[tuple[str, pd.DataFrame]]:
    """Yield one factor panel at a time with date-level eligibility applied.

    Eligibility affects only the date-t cross-sectional population, the
    date-t equal-weight market proxy, and whether a score is exposed at date t.
    The underlying price histories remain intact for every lookback formula.
    Sequential yielding lets broad-universe workflows release each full score
    panel after its backtest instead of retaining every factor in memory.
    """

    eligible = _aligned_eligibility_mask(prices, eligibility_mask)
    for name, spec in FACTOR_SPECS.items():
        eligibility_aware_fn = ELIGIBILITY_AWARE_FACTOR_FNS.get(name)
        raw_score = (
            eligibility_aware_fn(prices, eligible)
            if eligibility_aware_fn is not None
            else spec.fn(prices)
        )
        cleaned_score = raw_score.replace([np.inf, -np.inf], np.nan)
        yield name, cleaned_score.where(eligible) if eligible is not None else cleaned_score


def compute_factor_scores(
    prices: pd.DataFrame,
    eligibility_mask: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """Materialize all factor panels for formula-level tests and small analyses."""

    return dict(iter_factor_scores(prices, eligibility_mask=eligibility_mask))


def factor_definitions_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "factor": spec.name,
                "category": spec.category,
                "formula": spec.formula,
                "description": spec.description,
                "validation_notes": spec.validation_notes,
                "method_class": spec.method_class,
                "canonical_replication": spec.canonical_replication,
                "canonical_name": spec.canonical_name,
                "formula_version": spec.formula_version,
                "formation_end_lag_days": spec.formation_end_lag_days,
                "component_units": spec.component_units,
                "limitations": spec.limitations,
                "references": spec.references,
                "compatibility_alias_of": spec.compatibility_alias_of,
                "selection_eligible": spec.selection_eligible,
                "minimum_history_sessions": spec.minimum_history_sessions,
            }
            for spec in FACTOR_SPECS.values()
        ]
    )


def _digest_json_value(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _digest_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_digest_json_value(item) for item in value]
    if isinstance(value, np.generic):
        value = value.item()
    if value is None:
        return None
    missing = pd.isna(value)
    if isinstance(missing, (bool, np.bool_)) and bool(missing):
        return None
    return value


def factor_definition_sha256() -> str:
    """Hash all core/advanced definitions and their direct implementation sources."""

    from . import advanced_factors, metrics

    definitions = pd.concat(
        [factor_definitions_frame(), advanced_factors.advanced_factor_definitions_frame()],
        ignore_index=True,
        sort=False,
    )
    if definitions["factor"].duplicated().any():
        duplicates = sorted(definitions.loc[definitions["factor"].duplicated(), "factor"])
        raise RuntimeError(f"duplicate factor definitions in digest input: {duplicates}")
    records = sorted(
        (_digest_json_value(record) for record in definitions.to_dict(orient="records")),
        key=lambda record: str(record["factor"]),
    )
    source_paths = {
        "coreFactors": Path(__file__),
        "advancedFactors": Path(advanced_factors.__file__),
        "sharedFactorMetrics": Path(metrics.__file__),
    }
    source_digests = {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in sorted(source_paths.items())
    }
    payload = json.dumps(
        {
            "definitions": records,
            "definitionCount": len(records),
            "implementationSourceSha256": source_digests,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_factor_library(prices: pd.DataFrame, *, max_symbols: int = 50) -> pd.DataFrame:
    sample = prices.dropna(axis=1, how="all").iloc[:, :max_symbols]
    if sample.empty:
        return pd.DataFrame(
            [
                {
                    "factor": name,
                    "metadata_check": True,
                    "shape_check": False,
                    "finite_coverage": 0.0,
                    "no_lookahead_check": False,
                    "status": "fail",
                    "detail": "no price sample available",
                }
                for name in FACTOR_SPECS
            ]
        )
    base_scores = compute_factor_scores(sample)
    rows: list[dict[str, object]] = []
    signal_pos = min(max(260, len(sample.index) // 2), max(len(sample.index) - 2, 0))
    signal_date = sample.index[signal_pos]
    changed = sample.copy()
    if signal_pos + 1 < len(changed.index):
        changed.iloc[signal_pos + 1 :] = changed.iloc[signal_pos + 1 :] * 7.0
    changed_scores = compute_factor_scores(changed)
    for name, spec in FACTOR_SPECS.items():
        scores = base_scores[name]
        metadata_check = all(
            [
                spec.name,
                spec.category,
                spec.formula,
                spec.description,
                spec.validation_notes,
                spec.method_class,
                spec.canonical_name,
                spec.component_units,
                spec.limitations,
                spec.minimum_history_sessions >= 1,
            ]
        )
        shape_check = (
            scores.shape == sample.shape
            and scores.index.equals(sample.index)
            and list(scores.columns) == list(sample.columns)
        )
        finite_count = int(np.isfinite(scores.to_numpy(dtype=float, copy=True)).sum())
        finite_coverage = finite_count / scores.size if scores.size else 0.0
        expected_post_warmup = (
            max(len(sample.index) - spec.minimum_history_sessions + 1, 0) * sample.shape[1]
        )
        post_warmup_finite_coverage = (
            finite_count / expected_post_warmup if expected_post_warmup > 0 else 0.0
        )
        before = scores.loc[signal_date]
        after = changed_scores[name].loc[signal_date]
        comparable = before.dropna().index.intersection(after.dropna().index)
        if len(comparable) == 0:
            no_lookahead = True
        else:
            no_lookahead = bool(
                np.allclose(before.loc[comparable], after.loc[comparable], equal_nan=True)
            )
        status = (
            "pass"
            if metadata_check
            and shape_check
            and post_warmup_finite_coverage > 0.01
            and no_lookahead
            else "fail"
        )
        rows.append(
            {
                "factor": name,
                "category": spec.category,
                "metadata_check": bool(metadata_check),
                "shape_check": bool(shape_check),
                "finite_coverage": finite_coverage,
                "post_warmup_finite_coverage": post_warmup_finite_coverage,
                "no_lookahead_check": no_lookahead,
                "formula": spec.formula,
                "validation_notes": spec.validation_notes,
                "validation_sample_symbols": sample.shape[1],
                "validation_signal_date": str(signal_date.date())
                if hasattr(signal_date, "date")
                else str(signal_date),
                "status": status,
            }
        )
    return pd.DataFrame(rows)
