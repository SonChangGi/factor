import numpy as np
import pandas as pd
import pytest
from momentum_factor_lab.integrated_data import IntegratedMarket
from momentum_factor_lab.integrated_engine import IntegratedConfig, completed_monthends
from momentum_factor_lab.integrated_variants import (
    variant_scores,
    resolve_experiment,
    run_legacy_experiment,
)


def market_fixture():
    dates = pd.bdate_range("2015-01-01", periods=450)
    prices = pd.DataFrame(
        {f"S{i}": 100 + np.arange(len(dates)) * (i + 1) / 20 for i in range(20)}, index=dates
    )
    volume = prices * 0 + 1e6
    return IntegratedMarket(
        prices,
        prices,
        prices,
        prices,
        prices,
        volume,
        prices * 0,
        prices * 0,
        prices.notna(),
        {"snapshotId": "variant-fixture", "requestedSymbols": list(prices.columns)},
    )


def test_best_and_momentum_offsets_are_not_silently_equated():
    market = market_fixture()
    date = completed_monthends(market.prices.index)[-1]
    pos = market.prices.index.get_loc(date)
    best = variant_scores(
        market, {"project": "best", "id": "momentum_12_1"}, pd.DatetimeIndex([date])
    )
    momentum = variant_scores(market, {"project": "momentum", "id": "mom_12_1"})
    p = market.prices["S19"]
    assert np.isclose(best.loc[date, "S19"], p.iloc[pos - 21] / p.iloc[pos - 252] - 1)
    assert np.isclose(momentum.loc[date, "S19"], p.iloc[pos - 21] / p.iloc[pos - 273] - 1)
    assert not np.isclose(best.loc[date, "S19"], momentum.loc[date, "S19"])


def test_variant_fixed_accounting_next_close_and_pool_exclusion():
    market = market_fixture()
    out = run_legacy_experiment(
        market, IntegratedConfig(bootstrap_repetitions=0), {"project": "best", "id": "momentum_6m"}
    )
    assert out["resultIdentity"]["strategyType"] == "fixed_factor_experiment"
    assert out["registry"][0]["selectionEligible"] is False
    first = out["selection"]["nav"][0]
    executed = next(
        row for row in out["selection"]["history"] if row["executionStatus"] == "executed"
    )
    assert first["date"] == executed["executionDate"]
    assert executed["signalDate"] < executed["executionDate"]
    assert np.isclose(first["value"], 0.999)
    assert len(out["factors"]) == 1 and out["selection"]["current"]["status"] == "fixed"


def test_invalid_fundamental_and_unknown_definitions_rejected():
    from momentum_factor_lab.integrated_variants import experiment_catalog

    blocked = [
        row
        for row in experiment_catalog()
        if row["status"] in ("deferred_fundamental", "invalid_definition")
    ]
    assert len(blocked) == 10
    for row in blocked:
        with pytest.raises(ValueError):
            resolve_experiment({"project": row["project"], "id": row["legacyId"]})
    with pytest.raises(ValueError):
        resolve_experiment({"project": "best", "id": "unknown"})


def test_missing_session_not_collapsed_into_lookback():
    market = market_fixture()
    date = completed_monthends(market.prices.index)[-1]
    position = market.prices.index.get_loc(date)
    market.prices.iloc[position - 30, 0] = np.nan
    scores = variant_scores(
        market, {"project": "best", "id": "momentum_12_1"}, pd.DatetimeIndex([date])
    )
    assert pd.isna(scores.loc[date, "S0"])
