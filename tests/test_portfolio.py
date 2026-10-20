import numpy as np
import pandas as pd
import pytest

from factor_lab.config import FIXED_WEIGHTING_POLICY, RunConfig, WEIGHTING_POLICIES
from factor_lab.portfolio import (
    TIE_BREAK_POLICY,
    balanced_weights,
    construct_model_portfolio,
    construct_target_allocation,
)


SIGNAL_DATE = pd.Timestamp("2025-12-31")


def _config(*, top_n: int = 4, max_weight: float = 0.40) -> RunConfig:
    return RunConfig(
        demo=True,
        demo_symbol_count=50,
        top_n=top_n,
        max_weight=max_weight,
        selection_min_effective_names=min(2.0, float(top_n)),
    )


def _inputs() -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    index = pd.Index(["AAA", "BBB", "CCC", "DDD"])
    return (
        pd.Series([4.0, 3.0, 2.0, 1.0], index=index),
        pd.Series([10.0, 20.0, 30.0, 40.0], index=index),
        pd.Series(True, index=index),
        pd.Series([400.0, 300.0, 200.0, 100.0], index=index),
        pd.Series([4_000.0, 3_000.0, 2_000.0, 1_000.0], index=index),
    )


def _allocation(
    *,
    config: RunConfig | None = None,
    scores: pd.Series | None = None,
    liquidity: pd.Series | None = None,
    market_cap: pd.Series | None = None,
):
    default_scores, prices, eligibility, default_liquidity, default_market_cap = _inputs()
    return construct_target_allocation(
        FIXED_WEIGHTING_POLICY,
        SIGNAL_DATE,
        scores if scores is not None else default_scores,
        prices,
        eligibility,
        config or _config(),
        trailing_dollar_volume=(liquidity if liquidity is not None else default_liquidity),
        trailing_market_cap=(market_cap if market_cap is not None else default_market_cap),
    )


def test_only_fixed_score_liquidity_policy_is_available() -> None:
    assert WEIGHTING_POLICIES == (FIXED_WEIGHTING_POLICY,)
    result = _allocation()

    assert result.status == "available"
    assert result.rows["symbol"].tolist() == ["AAA", "BBB", "CCC", "DDD"]
    assert result.cash_weight == pytest.approx(0.0)
    assert result.policy_id == FIXED_WEIGHTING_POLICY
    assert result.policy_version == "1"
    assert result.component_status == {
        "score": "available",
        "methodology": "fixed_not_optimized",
        "liquidity": "trailing_raw_dollar_volume",
        "marketCap": "not_used",
    }


def test_fixed_raw_score_is_exact_70_30_percentile_blend_plus_floor() -> None:
    result = _allocation(config=_config(max_weight=1.0))
    rows = result.rows.set_index("symbol")

    expected = 0.05 + 0.70 * rows["scoreComponent"] + 0.30 * rows["liquidityComponent"]
    assert rows["rawPolicyScore"].tolist() == pytest.approx(expected.tolist())
    assert rows["weight"].tolist() == pytest.approx((expected / expected.sum()).tolist())
    assert rows.loc["AAA", "rawPolicyScore"] == pytest.approx(1.05)
    assert rows.loc["DDD", "rawPolicyScore"] == pytest.approx(0.30)


def test_score_and_liquidity_change_the_weight_but_market_cap_does_not() -> None:
    scores, _prices, _eligible, liquidity, market_cap = _inputs()
    baseline = _allocation(config=_config(max_weight=1.0)).rows.set_index("symbol")
    changed = _allocation(
        config=_config(max_weight=1.0),
        liquidity=liquidity.iloc[::-1].set_axis(liquidity.index),
        market_cap=market_cap.iloc[::-1].set_axis(market_cap.index),
    ).rows.set_index("symbol")

    assert baseline.loc["AAA", "weight"] > changed.loc["AAA", "weight"]
    assert baseline.loc["DDD", "weight"] < changed.loc["DDD", "weight"]
    assert changed["marketCapComponent"].eq(0.0).all()
    assert changed["trailingMarketCap"].isna().all()
    assert scores.index.tolist() == changed.index.tolist()


def test_top_n_boundary_tie_uses_trailing_dollar_volume_then_symbol() -> None:
    scores = pd.Series({"AAA": 3.0, "BBB": 2.0, "CCC": 2.0, "DDD": 2.0})
    liquidity = pd.Series({"AAA": 1.0, "BBB": 10.0, "CCC": 20.0, "DDD": 20.0})
    market_cap = pd.Series(100.0, index=scores.index)
    result = _allocation(
        config=_config(top_n=2, max_weight=0.50),
        scores=scores,
        liquidity=liquidity,
        market_cap=market_cap,
    )

    assert result.status == "available"
    assert result.rows["symbol"].tolist() == ["AAA", "CCC"]
    assert result.rows["weight"].tolist() == pytest.approx([0.5, 0.5])
    assert "top_n_boundary_tie_resolved_by_trailing_dollar_volume" in result.reasons
    assert result.component_status["selectionTieBreak"] == (
        "trailing_dollar_volume_desc_then_symbol_asc"
    )
    assert result.tie_break_policy == TIE_BREAK_POLICY


def test_missing_required_liquidity_component_fails_closed() -> None:
    _scores, _prices, _eligible, default_liquidity, default_market_cap = _inputs()
    result = construct_target_allocation(
        FIXED_WEIGHTING_POLICY,
        SIGNAL_DATE,
        _scores,
        _prices,
        _eligible,
        _config(),
        trailing_dollar_volume=pd.Series(np.nan, index=default_liquidity.index),
        trailing_market_cap=default_market_cap,
    )

    assert result.status == "unavailable"
    assert result.cash_weight == 1.0
    assert "no_finite_trailing_dollar_volume" in result.reasons[0]


def test_fixed_policy_respects_cap_and_leaves_explicit_cash() -> None:
    result = _allocation(config=_config(top_n=3, max_weight=0.20))
    weights = result.rows["weight"]

    assert result.status == "available"
    assert len(weights) == 3
    assert np.isfinite(weights).all()
    assert weights.le(0.20 + 1e-12).all()
    assert weights.sum() == pytest.approx(0.60)
    assert result.cash_weight == pytest.approx(0.40)
    assert weights.sum() + result.cash_weight == pytest.approx(1.0)
    assert "max_weight_capacity_or_missing_policy_inputs" in result.reasons


def test_model_portfolio_is_exact_wrapper_of_fixed_target_kernel() -> None:
    scores, prices, eligibility, liquidity, market_cap = _inputs()
    config = _config()
    target = _allocation(config=config)
    current = construct_model_portfolio(
        "mom",
        SIGNAL_DATE,
        scores,
        prices,
        eligibility,
        config,
        policy_id=FIXED_WEIGHTING_POLICY,
        trailing_dollar_volume=liquidity,
        trailing_market_cap=market_cap,
        names=pd.Series({symbol: f"Name {symbol}" for symbol in scores.index}),
    )

    assert current.status == target.status == "available"
    assert current.rows["symbol"].tolist() == target.rows["symbol"].tolist()
    assert current.rows["weight"].tolist() == pytest.approx(target.rows["weight"].tolist())
    assert current.cash_weight == pytest.approx(target.cash_weight)
    assert current.to_dict()["targetType"] == "factor_portfolio"
    assert current.to_dict()["executionTiming"] == "next_available_session_close_after_signal"


def test_balanced_weights_helper_remains_ranked_capped_and_cash_explicit() -> None:
    scores = pd.Series({"C": 1.0, "A": 3.0, "B": 2.0, "D": 0.0})
    weights = balanced_weights(scores, top_n=3, max_weight=0.20)

    assert weights.loc[["A", "B", "C"]].tolist() == pytest.approx([0.20] * 3)
    assert weights["D"] == 0.0
    assert weights.sum() == pytest.approx(0.60)


def test_missing_signal_inputs_produce_unavailable_status() -> None:
    result = construct_target_allocation(
        FIXED_WEIGHTING_POLICY,
        SIGNAL_DATE,
        pd.Series({"AAA": np.nan}),
        pd.Series({"AAA": 10.0}),
        pd.Series({"AAA": True}),
        _config(top_n=1, max_weight=1.0),
        trailing_dollar_volume=pd.Series({"AAA": 1.0}),
        trailing_market_cap=pd.Series({"AAA": 1.0}),
    )

    assert result.status == "unavailable"
    assert result.cash_weight == 1.0
    assert result.reasons == ["no_complete_signal_inputs"]
