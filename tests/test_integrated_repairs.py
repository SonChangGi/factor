import numpy as np
import pandas as pd
import pytest

from factor_lab.integrated_data import IntegratedMarket, save_integrated_market, load_integrated_market
from factor_lab.integrated_repairs import amend_market, backtest_inputs
from factor_lab.integrated_research import forward_security_returns


def market():
    dates = pd.bdate_range("2020-01-01", periods=6)
    p = pd.DataFrame({"OLD": [10., 10., np.nan, 11., np.nan, np.nan],
                      "NEW": [20., 20., 20., 20., 22., 24.]}, index=dates)
    v = p * 0 + 1e6
    return IntegratedMarket(p, p.copy(), p.copy(), p.copy(), p.copy(), v,
                            p * 0, p * 0, p.notna(),
                            {"requestedSymbols": ["OLD", "NEW"], "snapshotId": "parent"})


def evidence(symbol, date, **extra):
    return dict(symbol=symbol, date=str(date.date()), sourceUrl="https://exchange.example/record",
                retrievedAt="2026-10-20T00:00:00Z", **extra)


def test_sourced_halt_mark_is_not_a_trade_and_round_trips(tmp_path):
    original = market()
    date = original.prices.index[2]
    fixed = amend_market(original, {"valuationMarks": [evidence("OLD", date, close=10., adjustedClose=10., volume=0)]})
    assert np.isnan(fixed.prices.at[date, "OLD"])
    assert fixed.valuation_prices.at[date, "OLD"] == 10.
    assert np.isnan(original.prices.at[date, "OLD"])
    assert not fixed.eligibility.at[date, "OLD"]
    save_integrated_market(fixed, tmp_path)
    loaded = load_integrated_market(tmp_path)
    pd.testing.assert_frame_equal(loaded.valuation_prices, fixed.valuation_prices, check_freq=False)
    assert loaded.metadata["schemaVersion"] == "integrated-market-v4"
    assert loaded.metadata["parentSnapshotId"] == "parent"


def test_close_only_patch_does_not_fabricate_candle_or_override_source():
    original = market()
    date = original.prices.index[2]
    patch = evidence("OLD", date, close=10.5, adjustedClose=10.5, volume=10000)
    fixed = amend_market(original, {"quotes": [patch]})
    assert fixed.prices.at[date, "OLD"] == 10.5
    assert pd.isna(fixed.raw_high.at[date, "OLD"])
    assert not fixed.shape_valid.at[date, "OLD"]
    assert pd.isna(original.prices.at[date, "OLD"])
    with pytest.raises(ValueError, match="Conflicting observed close"):
        amend_market(fixed, {"quotes": [{**patch, "adjustedClose": 99.}]})


def test_security_boundary_and_quarantine_remain_explicit():
    original = market()
    ix = original.prices.index
    fixed = amend_market(original, {"identityStarts": [evidence("OLD", ix[3])],
                                    "quarantines": [{"symbol": "NEW", "reason": "mixed_basis"}]})
    assert fixed.prices.OLD.iloc[:3].isna().all()
    assert fixed.prices.NEW.isna().all()
    assert original.prices.NEW.notna().all()
    assert len(fixed.metadata["requestedSymbols"]) == 2


def test_merger_units_normalize_raw_and_total_return_and_research_exit():
    original = market()
    ix = original.prices.index
    original.raw_close = original.raw_close.copy()
    original.raw_close.OLD *= 2  # TR unit is half an old raw share
    original.raw_close.NEW *= 3  # one new raw share is three TR units
    fixed = amend_market(original, {"exchanges": [evidence("OLD", ix[4], targetSymbol="NEW", shareRatio=.5)]})
    action = fixed.metadata["corporateActions"][0]
    assert action["unitRatio"] == .75
    assert action["sourceUnitAnchorDate"] == str(ix[3].date())
    r = forward_security_returns(fixed.prices, ix[3], ix[5], fixed.valuation_prices, [action])
    assert np.isclose(r.OLD, .75 * 24 / 11 - 1)
    inputs = backtest_inputs(fixed, ix)
    assert inputs["retain_contribution_history"]
    with pytest.raises(ValueError, match="omits a mandatory successor"):
        backtest_inputs(fixed, ix, ["OLD"])
    # Later prices cannot alter this historical mandatory conversion.
    fixed.prices.at[ix[5], "NEW"] *= 100
    assert action["unitRatio"] == .75


def test_missing_split_normalization_preserves_raw_dollars_and_event_return():
    original = market()
    ix = original.prices.index
    original.prices.OLD = [1., 1., 1., 26., 28., 29.]
    original.raw_close = original.prices.copy()
    original.provider_close = original.raw_close.copy()
    original.provider_open = original.raw_close.copy()
    original.provider_high = original.raw_close.copy()
    original.provider_low = original.raw_close.copy()
    original.provider_volumes = original.volumes.copy()
    original.splits = original.splits.fillna(0.)
    fixed = amend_market(original, {"splitCorrections": [evidence("OLD", ix[3], ratio=1/25)]})
    assert np.isclose(fixed.prices.OLD.pct_change().iloc[3], .04)
    assert fixed.prices.OLD.iloc[3] == original.prices.OLD.iloc[3]
    pd.testing.assert_frame_equal(fixed.raw_close, original.raw_close)
    pd.testing.assert_frame_equal(fixed.volumes, original.volumes)
    pd.testing.assert_frame_equal(fixed.provider_close * fixed.provider_volumes,
                                  original.provider_close * original.provider_volumes)
    assert fixed.splits.at[ix[3], "OLD"] == 1/25
    with pytest.raises(ValueError, match="already recorded split"):
        amend_market(fixed, {"splitCorrections": [evidence("OLD", ix[3], ratio=1/25)]})


def test_cash_merger_is_a_known_receivable_without_a_market_quote():
    original = market()
    ix = original.prices.index
    original.raw_close.OLD *= 2
    fixed = amend_market(original, {"exchanges": [evidence("OLD", ix[4], cashPerShare=24., settlementDate=None)]})
    action = fixed.metadata["corporateActions"][0]
    assert action["targetSymbol"] is None
    assert action["unitRatio"] == 0
    assert action["cashPerUnit"] == 12.
    assert action["settlementDate"] is None
    assert pd.isna(fixed.prices.OLD.iloc[-1])
    assert not fixed.eligibility.OLD.iloc[-1]
    value = forward_security_returns(fixed.prices, ix[3], ix[5], fixed.valuation_prices, [action])
    assert np.isclose(value.OLD, 12 / 11 - 1)
    # A cash conversion has no successor market column to project.
    assert backtest_inputs(fixed, ix, ["OLD"])["corporate_actions"] == [action]
