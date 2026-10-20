from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_lab import advanced_factors

from factor_lab.factors import (
    FACTOR_DEFINITIONS,
    FACTOR_SPECS,
    acceleration_1m_vs_3m,
    acceleration_3m_vs_6m,
    acceleration_6m_vs_12m,
    acceleration_momentum,
    annualized_log_return_rate,
    breakout_126d,
    compute_factor_scores,
    consistency_momentum,
    decay_adjusted_momentum,
    deep_skip_twelve_month_momentum,
    downside_adjusted_total_momentum,
    dual_momentum,
    factor_definition_sha256,
    factor_definitions_frame,
    high_52week_proximity,
    high_26week_proximity,
    leave_one_out_equal_weight_market_returns,
    price_efficiency_momentum,
    range_position_momentum,
    range_position_252d_momentum,
    short_acceleration_momentum,
    simple_momentum,
    skipped_two_month_momentum,
    stability_adjusted_momentum,
    total_return_momentum,
    two_month_momentum,
    unskipped_six_month_momentum,
    up_down_capture_momentum,
    validate_factor_library,
    winsorized_skip_momentum,
)


def fixture_prices(columns=2, periods=360):
    dates = pd.bdate_range("2020-01-01", periods=periods)
    data = {}
    for i in range(columns):
        base = np.linspace(100 + i, 160 + i, len(dates))
        data[f"S{i:04d}"] = base if i % 2 == 0 else base[::-1] + 80
    return pd.DataFrame(data, index=dates)


def test_at_least_fifty_five_factor_definitions_with_metadata():
    assert len(FACTOR_DEFINITIONS) >= 55
    assert set(FACTOR_DEFINITIONS) == set(FACTOR_SPECS)
    for spec in FACTOR_SPECS.values():
        assert spec.formula and spec.description and spec.category and spec.validation_notes
        assert spec.method_class in {
            "canonical_signal_formula",
            "literature_inspired_proxy",
            "research_proxy",
            "internal_heuristic",
        }
        assert not spec.canonical_replication
        assert spec.canonical_name
        assert spec.formula_version >= 1
        assert spec.component_units != "unspecified"
        assert spec.limitations
        assert spec.minimum_history_sessions >= 1

    method_counts = pd.Series([spec.method_class for spec in FACTOR_SPECS.values()]).value_counts()
    assert method_counts.to_dict() == {
        "research_proxy": 34,
        "internal_heuristic": 20,
        "canonical_signal_formula": 6,
        "literature_inspired_proxy": 2,
    }
    assert all(
        spec.references
        for spec in FACTOR_SPECS.values()
        if spec.method_class == "literature_inspired_proxy"
    )
    assert FACTOR_SPECS["acceleration"].compatibility_alias_of == "accel_3m_vs_6m"
    assert FACTOR_SPECS["short_acceleration"].compatibility_alias_of == "accel_1m_vs_3m"
    assert FACTOR_SPECS["relative_strength_6m"].compatibility_alias_of == "mom_6m"
    assert not FACTOR_SPECS["acceleration"].selection_eligible
    assert not FACTOR_SPECS["short_acceleration"].selection_eligible
    assert not FACTOR_SPECS["relative_strength_6m"].selection_eligible


def test_factor_definition_frame_and_sha_are_deterministic():
    definitions = factor_definitions_frame()
    assert len(definitions) == len(FACTOR_SPECS)
    assert {
        "method_class",
        "canonical_replication",
        "canonical_name",
        "formula_version",
        "formation_end_lag_days",
        "component_units",
        "limitations",
        "references",
        "compatibility_alias_of",
        "selection_eligible",
        "minimum_history_sessions",
    }.issubset(definitions.columns)
    digest = factor_definition_sha256()
    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")
    assert digest == factor_definition_sha256()


def test_factor_digest_covers_all_advanced_definitions(monkeypatch) -> None:
    baseline = factor_definition_sha256()
    original = advanced_factors.advanced_factor_definitions_frame
    changed = original().copy()
    changed.loc[0, "formula"] = "changed advanced definition for digest regression"
    monkeypatch.setattr(
        advanced_factors,
        "advanced_factor_definitions_frame",
        lambda: changed,
    )

    assert len(factor_definitions_frame()) + len(changed) == 64
    assert factor_definition_sha256() != baseline


@pytest.mark.parametrize("implementation", ["factors.py", "advanced_factors.py"])
def test_factor_digest_covers_core_and_advanced_source(
    monkeypatch,
    implementation: str,
) -> None:
    baseline = factor_definition_sha256()
    original_read_bytes = Path.read_bytes

    def changed_source(path: Path) -> bytes:
        content = original_read_bytes(path)
        return (
            content + b"\n# digest regression mutation\n"
            if path.name == implementation
            else content
        )

    monkeypatch.setattr(Path, "read_bytes", changed_source)
    assert factor_definition_sha256() != baseline


def test_factor_shapes_match_prices():
    prices = fixture_prices()
    factors = compute_factor_scores(prices)
    assert set(factors) == set(FACTOR_DEFINITIONS)
    for scores in factors.values():
        assert scores.shape == prices.shape
        assert scores.index.equals(prices.index)


def test_all_factors_past_signal_does_not_change_when_future_price_changes():
    prices = fixture_prices(columns=4)
    changed = prices.copy()
    signal_date = prices.index[280]
    changed.loc[prices.index[300] :, "S0000"] *= 10
    for name in FACTOR_DEFINITIONS:
        before = compute_factor_scores(prices)[name].loc[signal_date]
        after = compute_factor_scores(changed)[name].loc[signal_date]
        comparable = before.dropna().index.intersection(after.dropna().index)
        assert np.allclose(before.loc[comparable], after.loc[comparable], equal_nan=True), name


def test_core_formula_manual_checks():
    dates = pd.bdate_range("2020-01-01", periods=300)
    prices = pd.DataFrame({"AAA": np.arange(1, 301, dtype=float)}, index=dates)
    assert (
        total_return_momentum(prices, 10, skip=2).iloc[20, 0]
        == prices.iloc[18, 0] / prices.iloc[8, 0] - 1
    )
    assert simple_momentum(prices, 10).iloc[20, 0] == prices.iloc[20, 0] / prices.iloc[10, 0] - 1
    assert high_52week_proximity(prices).iloc[-1, 0] == 0.0
    expected_accel = annualized_log_return_rate(
        prices,
        end_lag=0,
        span=63,
    ) - annualized_log_return_rate(prices, end_lag=63, span=126)
    pd.testing.assert_frame_equal(acceleration_momentum(prices), expected_accel)
    assert consistency_momentum(prices).iloc[-1, 0] > 0


def test_expanded_price_only_factor_formula_checks():
    dates = pd.bdate_range("2020-01-01", periods=320)
    prices = pd.DataFrame(
        {
            "SMOOTH": np.linspace(100.0, 180.0, len(dates)),
            "CHOPPY": 140.0 + np.sin(np.arange(len(dates)) / 3.0) * 8.0,
        },
        index=dates,
    )
    returns = prices.pct_change(fill_method=None)
    formation_returns = returns.shift(10)
    path_length = formation_returns.abs().rolling(126).sum()
    skipped_6m = prices.shift(10).divide(prices.shift(136)) - 1.0
    expected_efficiency = skipped_6m * skipped_6m.abs().divide(path_length.replace(0, np.nan))
    rolling_low = prices.rolling(126).min()
    rolling_high = prices.rolling(126).max()
    expected_range = (
        skipped_6m
        + (prices - rolling_low).divide((rolling_high - rolling_low).replace(0, np.nan))
        - 0.5
    )

    pd.testing.assert_frame_equal(
        price_efficiency_momentum(prices),
        expected_efficiency,
        check_names=False,
    )
    pd.testing.assert_frame_equal(
        range_position_momentum(prices),
        expected_range,
        check_names=False,
    )
    assert (
        price_efficiency_momentum(prices).iloc[-1]["SMOOTH"]
        > price_efficiency_momentum(prices).iloc[-1]["CHOPPY"]
    )


def test_stage2_price_only_factor_formula_checks():
    dates = pd.bdate_range("2020-01-01", periods=380)
    trend = np.linspace(100.0, 220.0, len(dates))
    seasonal = (
        150.0 + np.sin(np.arange(len(dates)) / 5.0) * 12.0 + np.linspace(0.0, 40.0, len(dates))
    )
    prices = pd.DataFrame({"TREND": trend, "SEASONAL": seasonal}, index=dates)
    returns = prices.pct_change(fill_method=None)
    skipped_12_2 = prices.shift(42).divide(prices.shift(294)) - 1.0
    unskipped_6m = prices.divide(prices.shift(126)) - 1.0
    mom_2m = prices.divide(prices.shift(42)) - 1.0
    skipped_2_1 = prices.shift(21).divide(prices.shift(63)) - 1.0
    mom_1m = prices.divide(prices.shift(21)) - 1.0
    mom_3m = prices.divide(prices.shift(63)) - 1.0
    skipped_6m = prices.shift(10).divide(prices.shift(136)) - 1.0
    skipped_12_1 = prices.shift(21).divide(prices.shift(273)) - 1.0
    rolling_high126 = prices.rolling(126).max()
    prior_high126 = prices.shift(1).rolling(126).max()
    rolling_high252 = prices.rolling(252).max()
    rolling_low252 = prices.rolling(252).min()
    vol126 = returns.rolling(126).std() * np.sqrt(252)
    winsorized = returns.shift(10).clip(lower=-0.05, upper=0.05)

    expected = {
        "mom_12_2": skipped_12_2,
        "mom_6m_unskipped": unskipped_6m,
        "mom_2m": mom_2m,
        "mom_2_1": skipped_2_1,
        "high_26w": prices.divide(rolling_high126) - 1.0,
        "breakout_126d": prices.divide(prior_high126) - 1.0 + 0.5 * mom_3m,
        "short_acceleration": annualized_log_return_rate(
            prices,
            end_lag=0,
            span=21,
        )
        - annualized_log_return_rate(prices, end_lag=21, span=63),
        "decay_adjusted": skipped_6m - 0.25 * mom_1m.abs(),
        "stability_adjusted": skipped_6m.divide((1.0 + vol126).replace(0, np.nan)),
        "winsorized_skip": (1.0 + winsorized).rolling(126).apply(np.prod, raw=True) - 1.0,
        "range_position_252d": skipped_12_1
        + (prices - rolling_low252).divide((rolling_high252 - rolling_low252).replace(0, np.nan))
        - 0.5,
    }
    actual = {
        "mom_12_2": deep_skip_twelve_month_momentum(prices),
        "mom_6m_unskipped": unskipped_six_month_momentum(prices),
        "mom_2m": two_month_momentum(prices),
        "mom_2_1": skipped_two_month_momentum(prices),
        "high_26w": high_26week_proximity(prices),
        "breakout_126d": breakout_126d(prices),
        "short_acceleration": short_acceleration_momentum(prices),
        "decay_adjusted": decay_adjusted_momentum(prices),
        "stability_adjusted": stability_adjusted_momentum(prices),
        "winsorized_skip": winsorized_skip_momentum(prices),
        "range_position_252d": range_position_252d_momentum(prices),
    }

    assert expected.keys() <= FACTOR_DEFINITIONS.keys()
    for name, expected_scores in expected.items():
        pd.testing.assert_frame_equal(actual[name], expected_scores, check_names=False)


def test_expanded_price_only_factors_handle_flat_prices_without_inf():
    dates = pd.bdate_range("2020-01-01", periods=320)
    prices = pd.DataFrame({"FLAT": np.full(len(dates), 100.0)}, index=dates)

    efficiency = price_efficiency_momentum(prices)
    range_position = range_position_momentum(prices)
    scores = compute_factor_scores(prices)

    assert not np.isinf(efficiency.to_numpy(dtype=float)).any()
    assert not np.isinf(range_position.to_numpy(dtype=float)).any()
    assert not np.isinf(scores["price_efficiency"].to_numpy(dtype=float)).any()
    assert not np.isinf(scores["range_position"].to_numpy(dtype=float)).any()
    assert efficiency.dropna(how="all").empty
    assert range_position.dropna(how="all").empty


def test_downside_adjusted_factor_uses_target_downside_deviation():
    dates = pd.bdate_range("2024-01-01", periods=5)
    daily_returns = pd.Series([-0.10, -0.05, 0.10, 0.10], index=dates[1:])
    prices = pd.DataFrame(
        {"AAA": [100.0, *(100.0 * (1.0 + daily_returns).cumprod()).tolist()]},
        index=dates,
    )

    actual = downside_adjusted_total_momentum(
        prices,
        lookback=4,
        skip=0,
        downside_window=4,
    ).iloc[-1, 0]
    momentum = prices.iloc[-1, 0] / prices.iloc[0, 0] - 1.0
    downside = np.sqrt((0.10**2 + 0.05**2) / 4) * np.sqrt(252)

    assert np.isclose(actual, momentum / downside)


def test_factor_validation_audit_passes_fixture():
    audit = validate_factor_library(fixture_prices(columns=8, periods=380))
    assert len(audit) == len(FACTOR_DEFINITIONS)
    assert audit["status"].eq("pass").all()
    assert audit["no_lookahead_check"].all()


def test_every_factor_matches_independent_formula_construction():
    prices = fixture_prices(columns=5, periods=380)
    returns = prices.pct_change(fill_method=None)
    mom_12_1 = total_return_momentum(prices, 252, skip=21)
    mom_12_2 = prices.shift(42).divide(prices.shift(294)) - 1.0
    mom_9_1 = total_return_momentum(prices, 189, skip=21)
    mom_6_1 = total_return_momentum(prices, 126, skip=21)
    mom_3_1 = prices.shift(21).divide(prices.shift(84)) - 1.0
    mom_10d = prices.divide(prices.shift(10)) - 1.0
    mom_6m_unskipped = prices.divide(prices.shift(126)) - 1.0
    mom_3m = simple_momentum(prices, 63)
    mom_2m = prices.divide(prices.shift(42)) - 1.0
    mom_2_1 = prices.shift(21).divide(prices.shift(63)) - 1.0
    mom_6m_simple = prices.divide(prices.shift(126)) - 1.0
    mom_6m = prices.shift(10).divide(prices.shift(136)) - 1.0
    mom_12m = prices.divide(prices.shift(252)) - 1.0
    mom_1m = simple_momentum(prices, 21)
    mom_6m_skip10 = prices.shift(10).divide(prices.shift(136)) - 1.0
    vol63 = returns.rolling(63).std() * np.sqrt(252)
    mean126 = returns.rolling(126).mean() * 252
    vol126 = returns.rolling(126).std() * np.sqrt(252)
    downside = returns.clip(upper=0.0).pow(2).rolling(126).mean().pow(0.5) * np.sqrt(252)
    ma20 = prices.rolling(20).mean()
    ma50 = prices.rolling(50).mean()
    ma100 = prices.rolling(100).mean()
    ma126 = prices.rolling(126).mean()
    ma200 = prices.rolling(200).mean()
    trend_stack_valid = prices.notna() & ma20.notna() & ma100.notna() & ma200.notna()
    ma_stack_valid = prices.notna() & ma20.notna() & ma50.notna() & ma100.notna() & ma200.notna()
    positive = returns.shift(10).gt(0).astype(float).where(returns.shift(10).notna())
    positive_skip21 = returns.shift(21).gt(0).astype(float).where(returns.shift(21).notna())
    prior_high20 = prices.shift(1).rolling(20).max()
    prior_high63 = prices.shift(1).rolling(63).max()
    prior_high126 = prices.shift(1).rolling(126).max()
    rolling_low126 = prices.rolling(126).min()
    rolling_high126 = prices.rolling(126).max()
    rolling_low252 = prices.rolling(252).min()
    rolling_high252 = prices.rolling(252).max()
    clipped = returns.clip(lower=-0.08, upper=0.08)
    winsorized = returns.shift(10).clip(lower=-0.05, upper=0.05)
    path_length = returns.shift(10).abs().rolling(126).sum()
    direct_move = mom_6m_skip10.abs()
    ulcer_drawdown = prices.divide(rolling_high126) - 1.0
    ulcer = ulcer_drawdown.pow(2).rolling(126).mean().pow(0.5)
    peer_return = leave_one_out_equal_weight_market_returns(prices)
    stock_return_shifted = returns.shift(21)
    market_return_shifted = peer_return.shift(21)
    stock_mean = stock_return_shifted.rolling(252).mean()
    market_mean = market_return_shifted.rolling(252).mean()
    covariance = stock_return_shifted.mul(market_return_shifted).rolling(
        252
    ).mean() - stock_mean.mul(market_mean)
    market_variance = market_return_shifted.pow(2).rolling(252).mean() - market_mean.pow(2)
    beta = covariance.divide(market_variance.replace(0, np.nan))
    excess = returns.sub(peer_return)
    tracking_error = excess.rolling(126).std() * np.sqrt(252)
    up_returns = returns.where(peer_return.gt(0))
    down_returns = returns.where(peer_return.lt(0))
    up_mean = up_returns.rolling(126, min_periods=21).mean()
    down_mean = down_returns.rolling(126, min_periods=21).mean()
    adequate_regimes = up_returns.rolling(126).count().ge(21) & down_returns.rolling(
        126
    ).count().ge(21)
    left_tail = returns.rolling(126).quantile(0.05)
    shifted_returns = returns.shift(10)
    near_high = prices.ge(rolling_high126 * 0.98).astype(float).where(rolling_high126.notna())
    expected = {
        "mom_12_1": mom_12_1,
        "mom_9_1": mom_9_1,
        "mom_6_1": mom_6_1,
        "mom_12_2": mom_12_2,
        "mom_3_1": mom_3_1,
        "mom_10d": mom_10d,
        "mom_6m_unskipped": mom_6m_unskipped,
        "mom_3m": mom_3m,
        "mom_2m": mom_2m,
        "mom_2_1": mom_2_1,
        "mom_6m": mom_6m,
        "mom_12m": mom_12m,
        "mom_1m": mom_1m,
        "multi_horizon": 0.15 * mom_1m
        + 0.25 * total_return_momentum(prices, 63, skip=5)
        + 0.30 * total_return_momentum(prices, 126, skip=10)
        + 0.30 * total_return_momentum(prices, 252, skip=21),
        "vol_adjusted": total_return_momentum(prices, 126, skip=10).divide(
            vol63.replace(0, np.nan)
        ),
        "risk_adjusted": mean126.divide(vol126.replace(0, np.nan)),
        "downside_risk_adjusted": total_return_momentum(prices, 126, skip=10).divide(
            downside.replace(0, np.nan)
        ),
        "dual_momentum": total_return_momentum(prices, 126, skip=10)
        .rank(axis=1, pct=True)
        .where(prices.divide(ma200) - 1.0 > 0),
        "ma_trend": prices.divide(ma200) - 1.0 + 0.5 * (ma50.divide(ma200) - 1.0),
        "time_series_trend": (
            (prices > ma20).astype(float).where(trend_stack_valid)
            + (ma20 > ma100).astype(float).where(trend_stack_valid)
            + (ma100 > ma200).astype(float).where(trend_stack_valid)
        ),
        "drawdown_aware": total_return_momentum(prices, 126, skip=10)
        + prices.divide(rolling_high126)
        - 1.0,
        "high_52w": prices.divide(rolling_high252) - 1.0,
        "high_26w": prices.divide(rolling_high126) - 1.0,
        "breakout_63d": prices.divide(prior_high63) - 1.0 + 0.5 * mom_1m,
        "breakout_126d": prices.divide(prior_high126) - 1.0 + 0.5 * mom_3m,
        "reversal_adjusted": mom_12_1 - 0.35 * mom_1m,
        "acceleration": acceleration_3m_vs_6m(prices),
        "short_acceleration": acceleration_1m_vs_3m(prices),
        "decay_adjusted": mom_6m_skip10 - 0.25 * mom_1m.abs(),
        "consistency": total_return_momentum(prices, 126, skip=10) * positive.rolling(126).mean(),
        "persistent_12_1": mom_12_1 * positive_skip21.rolling(252, min_periods=252).mean(),
        "low_vol_momentum": total_return_momentum(prices, 126, skip=10) - vol63,
        "stability_adjusted": mom_6m_skip10.divide((1.0 + vol126).replace(0, np.nan)),
        "relative_strength_6m": total_return_momentum(prices, 126, skip=10).rank(axis=1, pct=True),
        "trend_quality": prices.divide(ma126)
        - 1.0
        + returns.rolling(126).mean().divide(returns.rolling(126).std().replace(0, np.nan)),
        "gap_resistant": (1.0 + clipped).rolling(126).apply(np.prod, raw=True) - 1.0,
        "winsorized_skip": (1.0 + winsorized).rolling(126).apply(np.prod, raw=True) - 1.0,
        "price_efficiency": total_return_momentum(prices, 126, skip=10)
        * direct_move.divide(path_length.replace(0, np.nan)),
        "range_position": total_return_momentum(prices, 126, skip=10)
        + (prices - rolling_low126).divide((rolling_high126 - rolling_low126).replace(0, np.nan))
        - 0.5,
        "range_position_252d": mom_12_1
        + (prices - rolling_low252).divide((rolling_high252 - rolling_low252).replace(0, np.nan))
        - 0.5,
        "median_return_3m": returns.rolling(63).median() * 63,
        "median_return_6m": returns.rolling(126).median() * 126,
        "winsorized_3m": (1.0 + clipped).rolling(63).apply(np.prod, raw=True) - 1.0,
        "winsorized_12m": (1.0 + clipped).rolling(252).apply(np.prod, raw=True) - 1.0,
        "vol_adjusted_3m": mom_3m.divide(vol63.replace(0, np.nan)),
        "vol_adjusted_12m": mom_12_1.divide(
            (returns.rolling(126).std() * np.sqrt(252)).replace(0, np.nan)
        ),
        "downside_adjusted_12m": mom_12_1.divide(
            (returns.clip(upper=0.0).pow(2).rolling(252).mean().pow(0.5) * np.sqrt(252)).replace(
                0, np.nan
            )
        ),
        "ma_slope_50": ma50.divide(ma50.shift(21)) - 1.0,
        "price_vs_ma200": prices.divide(ma200) - 1.0,
        "ma_stack_quality": (
            (prices > ma20).astype(float).where(ma_stack_valid)
            + (ma20 > ma50).astype(float).where(ma_stack_valid)
            + (ma50 > ma100).astype(float).where(ma_stack_valid)
            + (ma100 > ma200).astype(float).where(ma_stack_valid)
        ),
        "breakout_20d": prices.divide(prior_high20) - 1.0 + 0.5 * mom_10d,
        "accel_1m_vs_3m": acceleration_1m_vs_3m(prices),
        "accel_3m_vs_6m": acceleration_3m_vs_6m(prices),
        "accel_6m_vs_12m": acceleration_6m_vs_12m(prices),
        "ulcer_adjusted": total_return_momentum(prices, 126, skip=10).divide(
            ulcer.replace(0, np.nan)
        ),
        "smooth_return_6m": mom_6m_simple - returns.rolling(126).std(),
        "residual_12_1": stock_return_shifted.rolling(252).sum()
        - beta.mul(market_return_shifted.rolling(252).sum()),
        "excess_ir_6m": (excess.rolling(126).mean() * 252).divide(
            tracking_error.replace(0, np.nan)
        ),
        "up_down_capture_6m": (up_mean - down_mean.abs()).where(adequate_regimes),
        "tail_resilient_6m": mom_6m_skip10 + left_tail,
        "jump_excluded_6m": shifted_returns.rolling(126).sum() - shifted_returns.rolling(126).max(),
        "high_persistence_6m": near_high.rolling(63).mean(),
    }
    scores = compute_factor_scores(prices)
    assert set(expected).issubset(scores)
    for name, expected_scores in expected.items():
        pd.testing.assert_frame_equal(
            scores[name], expected_scores.replace([np.inf, -np.inf], np.nan), check_names=False
        )


def test_new_factor_golden_vectors_and_edge_cases():
    dates = pd.bdate_range("2024-01-01", periods=90)
    prices = pd.DataFrame({"AAA": np.arange(1, 91, dtype=float), "CONST": 10.0}, index=dates)
    scores = compute_factor_scores(prices)

    assert scores["mom_3_1"].iloc[84, 0] == prices.iloc[63, 0] / prices.iloc[0, 0] - 1.0
    assert scores["mom_10d"].iloc[20, 0] == prices.iloc[20, 0] / prices.iloc[10, 0] - 1.0
    assert scores["mom_2m"].iloc[50, 0] == prices.iloc[50, 0] / prices.iloc[8, 0] - 1.0
    assert scores["median_return_3m"].iloc[-1, 0] > 0
    prior_high = prices["AAA"].shift(1).rolling(20).max().iloc[-1]
    expected_breakout = (
        prices["AAA"].iloc[-1] / prior_high - 1.0 + 0.5 * scores["mom_10d"].iloc[-1, 0]
    )
    assert np.isclose(scores["breakout_20d"].iloc[-1, 0], expected_breakout)
    assert scores["breakout_20d"].iloc[-1, 0] > 0.5 * scores["mom_10d"].iloc[-1, 0]
    pd.testing.assert_series_equal(
        scores["accel_1m_vs_3m"].iloc[-1],
        acceleration_1m_vs_3m(prices).iloc[-1],
    )
    assert np.isfinite(scores["ma_stack_quality"].dropna().to_numpy()).all()
    assert scores["winsorized_3m"].shape == prices.shape
    assert scores["vol_adjusted_3m"]["CONST"].dropna().empty


def test_repaired_factors_are_distinct_and_require_full_history():
    prices = fixture_prices(columns=3, periods=420)
    scores = compute_factor_scores(prices)

    assert not scores["mom_6m"].equals(scores["mom_6m_unskipped"])
    assert scores["time_series_trend"].iloc[:199].dropna(how="all").empty
    assert scores["ma_stack_quality"].iloc[:199].dropna(how="all").empty
    assert "persistent_12_1" in scores
    assert "residual_12_1" in scores
    assert scores["tail_resilient_6m"].shape == prices.shape
    assert scores["high_persistence_6m"].dropna(how="all").to_numpy().min() >= 0.0
    assert scores["high_persistence_6m"].dropna(how="all").to_numpy().max() <= 1.0
    assert not scores["jump_excluded_6m"].equals(scores["mom_6m"])


def test_residual_momentum_changes_cross_sectional_ranks_vs_raw_momentum():
    dates = pd.bdate_range("2022-01-03", periods=340)
    market = np.linspace(-0.01, 0.012, len(dates))
    idiosyncratic_a = np.sin(np.linspace(0, 16, len(dates))) * 0.003 + 0.0005
    idiosyncratic_b = np.cos(np.linspace(0, 12, len(dates))) * 0.002 - 0.0001
    idiosyncratic_c = np.linspace(0.0004, -0.0003, len(dates))
    returns = pd.DataFrame(
        {
            "HIGH_BETA": 1.8 * market + idiosyncratic_a,
            "LOW_BETA": 0.4 * market + idiosyncratic_b,
            "IDIO": 0.2 * market + idiosyncratic_c,
            "DEFENSIVE": -0.1 * market + 0.0002,
        },
        index=dates,
    )
    prices = 100 * (1 + returns).cumprod()
    scores = compute_factor_scores(prices)
    signal_date = scores["residual_12_1"].dropna(how="all").index[-1]

    raw_rank = scores["mom_12_1"].loc[signal_date].rank()
    residual_rank = scores["residual_12_1"].loc[signal_date].rank()

    assert not raw_rank.equals(residual_rank)


def test_ineligible_huge_return_cannot_contaminate_eligible_cross_sectional_scores():
    dates = pd.bdate_range("2022-01-03", periods=360)
    day = np.arange(len(dates), dtype=float)
    market = 0.004 * np.sin(day / 5.0) + 0.0003
    returns = pd.DataFrame(
        {
            "A": market + 0.0015 * np.cos(day / 9.0),
            "B": 0.6 * market - 0.0010 * np.sin(day / 7.0),
            "C": 0.8 * market + 0.0007 * np.cos(day / 13.0),
            "X": 0.0001 + 0.0002 * np.cos(day / 11.0),
        },
        index=dates,
    )
    prices = 100.0 * (1.0 + returns).cumprod()
    changed = prices.copy()
    changed.loc[dates[-60] :, "X"] *= 1_000_000.0
    eligibility = pd.DataFrame(True, index=dates, columns=prices.columns)
    eligibility["X"] = False
    factor_names = [
        "relative_strength_6m",
        "residual_12_1",
        "excess_ir_6m",
        "up_down_capture_6m",
    ]

    unmasked_before = compute_factor_scores(prices)
    unmasked_after = compute_factor_scores(changed)
    masked_before = compute_factor_scores(prices, eligibility_mask=eligibility)
    masked_after = compute_factor_scores(changed, eligibility_mask=eligibility)
    signal_date = dates[-1]

    for name in factor_names:
        assert not np.allclose(
            unmasked_before[name].loc[signal_date, ["A", "B"]],
            unmasked_after[name].loc[signal_date, ["A", "B"]],
        )
        pd.testing.assert_series_equal(
            masked_before[name].loc[signal_date, ["A", "B"]],
            masked_after[name].loc[signal_date, ["A", "B"]],
        )
        assert masked_after[name].loc[signal_date, ["A", "B"]].notna().all()

    expected_relative_rank = (
        total_return_momentum(changed, 126, skip=10).where(eligibility).rank(axis=1, pct=True)
    )
    pd.testing.assert_series_equal(
        masked_after["relative_strength_6m"].loc[signal_date],
        expected_relative_rank.loc[signal_date],
    )
    assert all(scores["X"].isna().all() for scores in masked_after.values())


def test_leave_one_out_peer_return_excludes_self_and_requires_two_peers():
    dates = pd.bdate_range("2025-01-01", periods=8)
    returns = pd.DataFrame(
        {
            "A": [0.01, 0.02, -0.01, 0.03, 0.01, -0.02, 0.04],
            "B": [0.00, 0.01, 0.02, -0.01, 0.03, 0.01, -0.01],
            "C": [-0.01, 0.03, 0.01, 0.02, -0.02, 0.04, 0.02],
        },
        index=dates[1:],
    )
    prices = pd.DataFrame(
        {
            name: [100.0, *(100.0 * (1.0 + values).cumprod()).tolist()]
            for name, values in returns.items()
        },
        index=dates,
    )
    peer = leave_one_out_equal_weight_market_returns(prices)

    assert np.isclose(peer.loc[dates[-1], "A"], returns.loc[dates[-1], ["B", "C"]].mean())
    assert np.isclose(peer.loc[dates[-1], "B"], returns.loc[dates[-1], ["A", "C"]].mean())

    changed = prices.copy()
    changed.loc[dates[-1], "A"] *= 2.0
    changed_peer = leave_one_out_equal_weight_market_returns(changed)
    assert np.isclose(
        changed_peer.loc[dates[-1], "A"],
        peer.loc[dates[-1], "A"],
    )
    assert changed_peer.loc[dates[-1], "B"] != peer.loc[dates[-1], "B"]

    two_name_peer = leave_one_out_equal_weight_market_returns(prices[["A", "B"]])
    assert two_name_peer.isna().all().all()


def test_up_down_conditional_signal_never_imputes_a_missing_regime():
    dates = pd.bdate_range("2024-01-01", periods=127)

    def prices_from_returns(frame: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame(
            {
                name: [100.0, *(100.0 * (1.0 + values).cumprod()).tolist()]
                for name, values in frame.items()
            },
            index=dates,
        )

    sparse_down_market = np.full(126, 0.001)
    sparse_down_market[::14] = -0.001
    sparse_returns = pd.DataFrame(
        {
            "A": np.where(sparse_down_market > 0, 0.002, -0.001),
            "B": sparse_down_market,
            "C": sparse_down_market * 0.8,
        },
        index=dates[1:],
    )
    sparse_score = up_down_capture_momentum(prices_from_returns(sparse_returns))
    assert sparse_score.iloc[-1].isna().all()

    covered_market = np.full(126, 0.001)
    covered_market[:21] = -0.001
    covered_returns = pd.DataFrame(
        {
            "A": np.where(covered_market > 0, 0.002, -0.001),
            "B": covered_market,
            "C": covered_market * 0.8,
        },
        index=dates[1:],
    )
    covered_score = up_down_capture_momentum(prices_from_returns(covered_returns))
    assert np.isclose(covered_score.iloc[-1]["A"], 0.001)
    assert covered_score.iloc[-1].notna().all()

    missing_stock_observations = prices_from_returns(covered_returns)
    missing_stock_observations.loc[dates[1:3], "A"] = np.nan
    missing_stock_score = up_down_capture_momentum(missing_stock_observations)
    assert pd.isna(missing_stock_score.iloc[-1]["A"])


def test_nonoverlapping_acceleration_is_zero_for_constant_growth_and_directional():
    dates = pd.bdate_range("2020-01-01", periods=420)
    constant = pd.DataFrame(
        {"A": 100.0 * np.exp(np.arange(len(dates)) * 0.001)},
        index=dates,
    )
    assert abs(acceleration_1m_vs_3m(constant).iloc[-1, 0]) < 1e-12
    assert abs(acceleration_3m_vs_6m(constant).iloc[-1, 0]) < 1e-12
    assert abs(acceleration_6m_vs_12m(constant).iloc[-1, 0]) < 1e-12
    assert acceleration_1m_vs_3m(constant).iloc[:84].isna().all().all()
    assert acceleration_3m_vs_6m(constant).iloc[:189].isna().all().all()
    assert acceleration_6m_vs_12m(constant).iloc[:378].isna().all().all()

    accelerating_log_returns = np.full(len(dates) - 1, 0.001)
    accelerating_log_returns[-21:] = 0.003
    accelerating = pd.DataFrame(
        {
            "A": [
                100.0,
                *(100.0 * np.exp(np.cumsum(accelerating_log_returns))).tolist(),
            ]
        },
        index=dates,
    )
    assert acceleration_1m_vs_3m(accelerating).iloc[-1, 0] > 0

    decelerating_log_returns = np.full(len(dates) - 1, 0.003)
    decelerating_log_returns[-21:] = 0.001
    decelerating = pd.DataFrame(
        {
            "A": [
                100.0,
                *(100.0 * np.exp(np.cumsum(decelerating_log_returns))).tolist(),
            ]
        },
        index=dates,
    )
    assert acceleration_1m_vs_3m(decelerating).iloc[-1, 0] < 0
    pd.testing.assert_frame_equal(
        acceleration_momentum(constant),
        acceleration_3m_vs_6m(constant),
    )
    pd.testing.assert_frame_equal(
        short_acceleration_momentum(constant),
        acceleration_1m_vs_3m(constant),
    )


def test_dual_momentum_uses_eligible_relative_rank_and_ma200_gate():
    dates = pd.bdate_range("2023-01-02", periods=240)
    prices = pd.DataFrame(
        {
            "FAST": 100.0 * np.exp(np.arange(len(dates)) * 0.0020),
            "SLOW": 100.0 * np.exp(np.arange(len(dates)) * 0.0010),
            "DOWN": 100.0 * np.exp(np.arange(len(dates)) * -0.0010),
            "EXCLUDED": 100.0 * np.exp(np.arange(len(dates)) * 0.0040),
        },
        index=dates,
    )
    eligibility = pd.DataFrame(True, index=dates, columns=prices.columns)
    eligibility["EXCLUDED"] = False

    score = dual_momentum(prices, eligibility)
    assert score.iloc[-1]["FAST"] == 1.0
    assert score.iloc[-1]["SLOW"] == 2.0 / 3.0
    assert pd.isna(score.iloc[-1]["DOWN"])
    assert pd.isna(score.iloc[-1]["EXCLUDED"])


def test_breakout_uses_prior_high_and_formation_overlays_ignore_recent_skip():
    dates = pd.bdate_range("2022-01-03", periods=320)
    prices = pd.DataFrame(
        {"A": 100.0 * np.exp(np.arange(len(dates)) * 0.001)},
        index=dates,
    )
    score = compute_factor_scores(prices)
    prior_high = prices["A"].shift(1).rolling(20).max().iloc[-1]
    breakout_leg = prices["A"].iloc[-1] / prior_high - 1.0
    assert breakout_leg > 0
    assert np.isclose(
        score["breakout_20d"].iloc[-1, 0],
        breakout_leg + 0.5 * score["mom_10d"].iloc[-1, 0],
    )

    changed = prices.copy()
    changed.iloc[-9:, 0] *= np.linspace(1.1, 1.9, 9)
    assert np.isclose(
        consistency_momentum(prices).iloc[-1, 0],
        consistency_momentum(changed).iloc[-1, 0],
    )
    assert np.isclose(
        price_efficiency_momentum(prices).iloc[-1, 0],
        price_efficiency_momentum(changed).iloc[-1, 0],
    )
