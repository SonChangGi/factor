import json
from pathlib import Path
import numpy as np
import pandas as pd
from momentum_factor_lab.integrated_data import IntegratedMarket, compute_eligibility
from momentum_factor_lab.integrated_factors import compute_integrated_factors, factor_registry


def fixture_market(n=850):
    ix = pd.bdate_range("2018-01-01", periods=n)
    t = np.arange(n)
    p = pd.DataFrame(
        {
            "A": 30 * np.exp(0.0004 * t + 0.01 * np.sin(t / 7)),
            "SPY": 100 * np.exp(0.0002 * t + 0.02 * np.sin(t / 11)),
        },
        index=ix,
    )
    v = p * 0 + 1e6
    e = p.notna()
    e["SPY"] = False
    return IntegratedMarket(p, p, p * 0.999, p * 1.01, p * 0.99, v, p * 0, p * 0, e, {})


def test_registry_and_complete_migration_inventory():
    reg = factor_registry()
    assert len(reg) == 32
    assert sum(r["selectionEligible"] for r in reg) == 26
    rows = json.loads(
        (
            Path(__file__).parents[1] / "momentum_factor_lab/resources/integrated_legacy_map.json"
        ).read_text()
    )["rows"]
    assert sum(r["project"] == "best" for r in rows) == 318
    assert sum(r["project"] == "momentum" for r in rows) == 64
    assert sum(r["status"] == "invalid_definition" for r in rows) == 2


def test_formula_independent_expected_values_and_direction():
    m = fixture_market()
    s = compute_integrated_factors(m)
    ret = m.prices.A.pct_change(fill_method=None).iloc[-252:].to_numpy()
    assert np.isclose(s["VOL252"].A.iloc[-1], -np.std(ret, ddof=1) * np.sqrt(252))
    assert np.isclose(s["ES10_252"].A.iloc[-1], np.mean(sorted(ret)[:26]))
    centered = ret - ret.mean()
    assert np.isclose(s["SKEW252"].A.iloc[-1], np.mean(centered**3) / np.std(ret) ** 3)
    assert np.isclose(s["EXKURT252"].A.iloc[-1], np.mean(centered**4) / np.std(ret) ** 4 - 3)
    assert np.isclose(
        s["PARKINSON126"].A.iloc[-1], -np.sqrt(252 * np.log(1.01 / 0.99) ** 2 / (4 * np.log(2)))
    )
    for panel in s.values():
        assert panel.SPY.isna().all()


def test_future_prices_do_not_change_past_and_month_skip_is_calendar_based():
    m = fixture_market()
    a = compute_integrated_factors(m)
    cutoff = m.prices.index[650]
    for field in ("prices", "raw_close", "raw_open", "raw_high", "raw_low"):
        frame = getattr(m, field).copy()
        frame.loc[frame.index > cutoff] *= 1.8
        setattr(m, field, frame)
    b = compute_integrated_factors(m)
    for key in a:
        pd.testing.assert_frame_equal(a[key].loc[:cutoff], b[key].loc[:cutoff])
    month = m.prices.index.to_period("M")
    ends = m.prices.groupby(month).tail(1)
    k = 20
    date = ends.index[k]
    expected = ends.A.iloc[k - 1] / ends.A.iloc[k - 12] - 1
    assert np.isclose(a["MOM12_1"].loc[date, "A"], expected)


def test_monthly_max_requires_every_return_even_when_stock_remains_eligible():
    m = fixture_market(400)
    month_end = pd.Timestamp("2019-06-28")
    intact = compute_integrated_factors(m)["MAX1M"]
    june = m.prices.A.pct_change(fill_method=None).loc["2019-06"]
    assert np.isclose(intact.at[month_end, "A"], -max(june))
    for field in ("prices", "raw_close", "raw_open", "raw_high", "raw_low"):
        getattr(m, field).loc["2019-06-14", "A"] = np.nan
    m.eligibility = compute_eligibility(m.prices, m.raw_close, m.volumes)
    assert m.eligibility.at[month_end, "A"]
    scores = compute_integrated_factors(m)
    assert pd.isna(scores["MAX1M"].at[month_end, "A"])


def test_constant_returns_have_no_standardized_distribution_moments():
    m = fixture_market(400)
    for field in ("prices", "raw_close", "raw_open", "raw_high", "raw_low"):
        getattr(m, field).loc[:, "A"] = 30.0
    scores = compute_integrated_factors(m)
    assert scores["VOL252"].A.iloc[-1] == 0.0
    assert scores["SKEW252"].A.iloc[-1:].isna().all()
    assert scores["EXKURT252"].A.iloc[-1:].isna().all()
