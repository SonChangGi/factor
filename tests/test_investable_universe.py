import json

import pandas as pd
import pytest

from factor_lab.config import RunConfig
from factor_lab.integrated_data import (
    FIELDS, IntegratedMarket, load_integrated_market, save_integrated_market,
)
from factor_lab.integrated_engine import IntegratedConfig, _allocation
from factor_lab.integrated_service import data_inventory
from factor_lab.investable_universe import apply_exchange_screen, build_universe_screen


def directories(tmp_path, *, date="11042026", other_date=None):
    nasdaq = tmp_path / "nasdaqlisted.txt"
    other = tmp_path / "otherlisted.txt"
    nasdaq.write_text(
        "Symbol|Security Name|Test Issue|ETF|Financial Status\n"
        "SATS|Strive, Inc. - Series A Preferred Stock|N|N|N\n"
        "ECHO|EchoStar Corporation - Class A Common Stock|N|N|N\n"
        "TSCO|Tractor Supply Company - Common Stock|N|N|D\n"
        "OTCX|Test listing|Y|N|N\n"
        f"File Creation Time: {date}21:31||||\n"
    )
    other.write_text(
        "NASDAQ Symbol|Security Name|Test Issue|ETF|Exchange\n"
        "BRK.B|Berkshire Hathaway Inc. Common Stock|N|N|N\n"
        "BABA|Alibaba Group American Depositary Shares|N|N|N\n"
        "VOO|Vanguard S&P 500 ETF|N|Y|P\n"
        "TQQQ|An unreviewed leveraged fund|N|Y|P\n"
        f"File Creation Time: {other_date or date}21:31||||\n"
    )
    return nasdaq, other


def result(symbols, date="2026-11-03"):
    rows = [
        {"symbol": symbol, "status": "eligible", "observedAt": date}
        for symbol in symbols
    ]
    return {
        "data": {"asOf": date, "symbols": rows, "requestedSymbols": list(symbols)},
        "resultIdentity": {"resultId": "reviewed"},
    }


def test_current_screen_uses_listing_and_price_evidence_independently(tmp_path):
    symbols = ["BRK-B", "BABA", "BMWKY", "OTCX", "SATS", "TSCO", "TQQQ"]
    inputs = result(symbols)
    inputs["data"]["symbols"][2]["exchange"] = "OTC"
    screen = build_universe_screen(inputs, *directories(tmp_path))
    rows = {r["symbol"]: r for r in screen["rows"]}
    assert screen["marketSessionLag"] == 1
    assert screen["eligibleSymbols"] == ["BABA", "BRK-B", "TSCO"]
    assert rows["BABA"]["category"] == "adr"
    assert rows["BRK-B"]["listedSymbol"] == "BRK.B"
    assert rows["TSCO"]["listingFinancialStatus"] == "D"
    assert rows["BMWKY"]["decision"] == "otc_legacy"
    assert rows["OTCX"]["decision"] == "listing_unconfirmed"
    assert rows["SATS"]["decision"] == "ticker_reused"
    assert rows["ECHO"]["decision"] == rows["VOO"]["decision"] == "provider_data_required"
    assert rows["TQQQ"]["decision"] == "product_unreviewed"
    assert screen["listedEtfCandidates"] == ["VOO"]


def test_dates_gate_current_screen(tmp_path):
    inputs = result(["TSCO"], date="2026-10-30")
    screen = build_universe_screen(inputs, *directories(tmp_path))
    assert screen["eligibleSymbols"] == []
    assert screen["decisionCounts"]["market_data_stale"] == 1
    with pytest.raises(ValueError, match="different creation dates"):
        build_universe_screen(inputs, *directories(tmp_path, other_date="11032026"))
    with pytest.raises(ValueError, match="predate"):
        build_universe_screen(result(["TSCO"], "2026-11-05"), *directories(tmp_path))


def test_frozen_selection_mask_only_changes_evidenced_day(tmp_path):
    dates = pd.to_datetime(["2026-11-03", "2026-11-04"])
    symbols = ["TSCO", "BMWKY", "SATS", "SPY"]
    inputs = pd.DataFrame(15.0, index=dates, columns=symbols)
    fields = {field: inputs.copy() for field in FIELDS}
    fields["eligibility"] = inputs.gt(0)
    fields["eligibility"]["SPY"] = False
    market = IntegratedMarket(
        **fields, metadata={"requestedSymbols": symbols[:-1], "snapshotId": "original"},
    )
    with pytest.raises(ValueError, match="final session"):
        apply_exchange_screen(market, *directories(tmp_path, date="11052026"))
    screened = apply_exchange_screen(market, *directories(tmp_path))
    assert market.eligibility["BMWKY"].tolist() == [True, True]
    assert screened.eligibility["BMWKY"].tolist() == [True, False]
    assert screened.eligibility["SATS"].tolist() == [True, False]
    assert screened.eligibility["TSCO"].tolist() == [True, True]
    assert screened.eligibility["SPY"].tolist() == [False, False]
    pd.testing.assert_frame_equal(screened.prices, market.prices)
    output = tmp_path / "derived"
    save_integrated_market(screened, output)
    reloaded = load_integrated_market(output)
    assert reloaded.metadata["exchangeScreen"]["parentSnapshotId"] == "original"
    assert json.loads((output / "manifest.json").read_text())["files"]["eligibility.csv.gz"]
    rows = {r["symbol"]: r for r in data_inventory(reloaded)}
    assert rows["BMWKY"]["status"] == "excluded"
    assert "otc_legacy" in rows["BMWKY"]["reason"]
    assert "ticker_reused" in rows["SATS"]["reason"]

    scores = pd.DataFrame([[1, 3, 2, 0], [1, 3, 2, 0]], index=dates, columns=symbols)
    config = IntegratedConfig(top_n=1, max_weight=1)
    run_config = RunConfig(top_n=1, max_weight=1)
    early = _allocation(dates[0], scores, reloaded, inputs, config, run_config)
    current = _allocation(dates[-1], scores, reloaded, inputs, config, run_config)
    assert early.rows["symbol"].tolist() == ["BMWKY"]
    assert current.rows["symbol"].tolist() == ["TSCO"]
