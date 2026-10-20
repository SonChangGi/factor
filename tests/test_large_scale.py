import numpy as np
import pandas as pd
import pytest

from factor_lab.backtest import run_factor_backtest
from factor_lab.config import FIXED_WEIGHTING_POLICY, RunConfig
from factor_lab.factors import simple_momentum


def test_core_backtest_supports_a_2701_security_universe() -> None:
    dates = pd.bdate_range("2023-01-02", periods=320)
    symbols = [f"S{i:04d}" for i in range(2_701)]
    rng = np.random.default_rng(7)
    returns = rng.normal(0.0002, 0.01, (len(dates), len(symbols)))
    prices = pd.DataFrame(50.0 * np.exp(np.cumsum(returns, axis=0)), index=dates, columns=symbols)
    scores = simple_momentum(prices, 63)
    eligibility = pd.DataFrame(True, index=dates, columns=symbols)
    config = RunConfig(
        demo=True,
        demo_symbol_count=2_701,
        top_n=20,
        min_history_days=252,
        evaluation_window_days=252,
        min_evaluation_observations=252,
        min_daily_risk_observations=252,
    )
    result = run_factor_backtest(
        "mom_3m",
        FIXED_WEIGHTING_POLICY,
        prices,
        scores,
        config,
        eligibility_mask=eligibility,
        trailing_dollar_volume=prices.mul(1_000_000.0),
        trailing_market_cap=prices.mul(100_000_000.0),
    )
    assert result.weights.shape == prices.shape
    assert result.weights.iloc[-1].gt(0.0).sum() == 20
    assert result.weights.iloc[-1].sum() == pytest.approx(1.0)
