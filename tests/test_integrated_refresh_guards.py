import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from factor_lab import integrated_automation as automation


def _provider(symbols, *, missing=()):
    dates = pd.to_datetime(["2026-10-27", "2026-10-28"])
    values = {
        "Adj Close": 10.0,
        "Close": 10.0,
        "Open": 9.0,
        "High": 11.0,
        "Low": 8.0,
        "Volume": 50000.0,
        "Dividends": 0.0,
        "Stock Splits": 0.0,
    }
    frame = pd.DataFrame({(f, s): [v, v] for s in symbols for f, v in values.items()}, index=dates)
    for symbol in missing:
        frame.loc[dates[-1], ("Adj Close", symbol)] = np.nan
    return frame










def test_required_valuation_follows_cash_claim_stock_exchange_and_approved_valuation_mark():
    baseline = {
        "data": {"asOf": "2026-10-27"},
        "selection": {"holdings": [{"symbol": "CASH", "weight": 0.2}]},
        "factors": [
            {"holdings": [{"symbol": "OLD", "weight": 0.4}, {"symbol": "HALT", "weight": 0.4}]}
        ],
    }
    dates = pd.to_datetime(["2026-10-28"])
    prices = pd.DataFrame({"NEW": [12.0], "HALT": [np.nan]}, index=dates)
    marks = pd.DataFrame({"NEW": [12.0], "HALT": [11.0]}, index=dates)
    market = SimpleNamespace(
        prices=prices,
        valuation_prices=marks,
        metadata={
            "corporateActions": [
                {"symbol": "CASH", "targetSymbol": None, "cashPerUnit": 95.0, "date": "2026-10-28"},
                {"symbol": "OLD", "targetSymbol": "NEW", "unitRatio": 2.0, "date": "2026-10-28"},
            ]
        },
    )
    assert (
        automation.validate_required_valuations(market, baseline, "2026-10-28")["valuedHeldSymbols"]
        == 2
    )
    marks.at[dates[0], "NEW"] = np.nan
    with pytest.raises(automation.RefreshInputError) as error:
        automation.validate_required_valuations(market, baseline, "2026-10-28")
    assert error.value.symbols == ["NEW"]


def _probe_site(tmp_path, monkeypatch):
    site = tmp_path / "site"
    (site / "data").mkdir(parents=True)
    (site / "data/integrated-result.json").write_text(
        json.dumps(
            {
                "schemaVersion": "integrated-factor/v1",
                "data": {"asOf": "2026-10-27"},
                "selection": {"holdings": [{"symbol": "HUBB", "weight": 1.0}]},
            }
        )
    )
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({"quotes": [], "valuationMarks": [], "exchanges": []}))
    monkeypatch.setattr(automation, "POLICY", policy)
    return site, policy












def test_only_current_verified_full_bar_clears_failed_inventory_and_keeps_source_failure():
    from factor_lab.integrated_data import IntegratedMarket, compute_eligibility
    from factor_lab.integrated_repairs import amend_market
    from factor_lab.integrated_service import data_inventory

    dates = pd.bdate_range(end="2026-10-28", periods=260)
    price = pd.DataFrame({"HUBB": [10.0] * 260}, index=dates)
    price.iloc[-1, 0] = np.nan
    volume = price * 0 + 2e6
    volume.iloc[-1, 0] = 2e6
    source_failure = {
        "code": "target_session_quote_unavailable",
        "date": "2026-10-28",
        "attempts": 2,
    }
    raw = IntegratedMarket(
        price,
        price.copy(),
        price.copy(),
        price.copy(),
        price.copy(),
        volume,
        price * 0,
        price * 0,
        compute_eligibility(price, price, volume),
        metadata={
            "snapshotId": "raw",
            "requestedSymbols": ["HUBB"],
            "failedSymbols": {"HUBB": "provider quote absent"},
            "sourceTargetFailures": {"HUBB": source_failure},
        },
    )
    assert data_inventory(raw)[0]["status"] == "failed"
    quote = {
        "symbol": "HUBB",
        "date": "2026-10-28",
        "open": 10.0,
        "high": 10.0,
        "low": 10.0,
        "close": 10.0,
        "adjustedClose": 10.0,
        "volume": 2e6,
        "sourceUrl": "https://example.test/verified-bar",
        "retrievedAt": "2026-10-29",
    }
    fixed = amend_market(raw, {"inputSnapshotId": "raw", "quotes": [quote]})
    row = data_inventory(fixed)[0]
    assert row["status"] == "eligible" and row["sourceFailure"] == source_failure
    assert row["reason"] == ""
    fixed.metadata["amendments"][0]["date"] = "2026-10-27"
    assert data_inventory(fixed)[0]["status"] == "failed"
