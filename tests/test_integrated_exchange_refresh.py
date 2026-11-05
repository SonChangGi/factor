from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd
import pytest

from factor_lab import integrated_automation as automation
from factor_lab import integrated_exchange_refresh as refresh
from factor_lab.integrated_data import FIELDS, IntegratedMarket

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def baseline_data(tmp_path, monkeypatch):
    digest = sha256(refresh.RESOURCE.read_bytes()).hexdigest()
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({
        "version": "tested-v1", "earliestSession": "2026-11-05",
        "review": {"universeSourceHash": digest, "listedStocks": 2},
        "minimumReviewedCoverage": 0.95,
    }))
    monkeypatch.setattr(refresh, "POLICY", policy)
    monkeypatch.setattr(refresh, "integrated_universe", lambda: {"symbols": [
        {"symbol": "A"}, {"symbol": "TSCO"}, {"symbol": "BMWKY", "exchange": "OTC"},
    ]})
    return {"asOf": "2026-11-27", "universeSourceHash": digest,
            "requestedSymbols": ["A", "TSCO", "BMWKY"]}


def source(root, date, *, time="17:01", include_stock=True, reused_symbol=False):
    root.mkdir(exist_ok=True)
    stamp = datetime.fromisoformat(date).strftime("%m%d%Y") + time
    nasdaq, other = [root / name for name in refresh.FILENAMES]
    nasdaq.write_text(
        "Symbol|Security Name|Test Issue|ETF|Financial Status\n"
        "TSCO|Tractor Supply Company - Common Stock|N|N|N\n"
        f"File Creation Time: {stamp}||||\n"
    )
    rows = ["A|Agilent Technologies, Inc. Common Stock|N|N|N"] if include_stock else []
    rows.append("VOO|Vanguard S&P 500 ETF|N|Y|P")
    if reused_symbol:
        rows.append("BMWKY|Another Issuer Common Stock|N|N|N")
    other.write_text(
        "NASDAQ Symbol|Security Name|Test Issue|ETF|Exchange\n"
        + "\n".join(rows) + f"\nFile Creation Time: {stamp}||||\n"
    )
    return root


def market(dates):
    panel = pd.DataFrame(15.0, index=pd.to_datetime(dates), columns=["A", "TSCO", "BMWKY"])
    frames = {name: panel.copy() for name in FIELDS}
    frames["eligibility"] = panel.gt(0)
    return IntegratedMarket(**frames, metadata={"snapshotId": "market"})


def test_activation_validates_real_dates_coverage_and_reviewed_universe(baseline_data, tmp_path):
    assert refresh.exchange_plan(baseline_data, "2026-11-27") == (False, None)
    assert refresh.exchange_plan(baseline_data, "2026-11-30") == (True, None)
    directory = tmp_path / "source"
    with pytest.raises(ValueError, match="reviewed baseline"):
        refresh.exchange_plan({**baseline_data, "universeSourceHash": "unreviewed"}, "2026-11-30")
    with pytest.raises(ValueError, match="predate"):
        refresh.exchange_observation(baseline_data, "2026-11-30", source(directory, "2026-11-27"))
    with pytest.raises(ValueError, match="match completed session"):
        refresh.exchange_observation(baseline_data, "2026-11-30", source(directory, "2026-12-01"))
    with pytest.raises(ValueError, match="before.*close"):
        refresh.exchange_observation(
            baseline_data, "2026-11-30", source(directory, "2026-11-30", time="15:59")
        )
    with pytest.raises(ValueError, match="coverage"):
        refresh.exchange_observation(
            baseline_data, "2026-11-30", source(directory, "2026-11-30", include_stock=False)
        )
    observation = refresh.exchange_observation(
        baseline_data, "2026-11-30", source(directory, "2026-11-30")
    )
    assert observation["latest"]["excluded"] == {"BMWKY": "otc_legacy"}
    assert observation["latest"]["listedEtfCandidates"] == ["VOO"]
    assert len(observation["latest"]["sources"]) == 2


def test_month_end_is_replayed_and_ticker_reappearance_is_quarantined(baseline_data, tmp_path):
    first = source(tmp_path / "first", "2026-11-30")
    observation = refresh.exchange_observation(baseline_data, "2026-11-30", first)
    prices = market(["2026-11-27", "2026-11-30", "2026-12-01"])
    initial = replace(prices, **{name: getattr(prices, name).iloc[:2] for name in FIELDS})
    screened = refresh.apply_exchange_observation(initial, baseline_data, observation)
    assert screened.eligibility["BMWKY"].tolist() == [True, False]
    accepted = {**baseline_data, "asOf": "2026-11-30",
                "exchangeUniverse": screened.metadata["exchangeUniverse"]}
    assert refresh.exchange_observation(accepted, "2026-11-30", first) == observation
    with pytest.raises(ValueError, match="original accepted"):
        refresh.exchange_observation(accepted, "2026-11-30",
                                     source(first, "2026-11-30", time="17:31"))
    next_directory = source(tmp_path / "next", "2026-12-01", reused_symbol=True)
    next_observation = refresh.exchange_observation(accepted, "2026-12-01", next_directory)
    assert next_observation["latest"]["excluded"] == {"BMWKY": "listing_identity_review"}
    replayed = refresh.apply_exchange_observation(prices, accepted, next_observation)
    assert replayed.eligibility["BMWKY"].tolist() == [True, False, False]
    assert prices.eligibility["BMWKY"].all()
    pd.testing.assert_frame_equal(replayed.prices, prices.prices)


def test_missed_month_end_requires_and_accepts_only_exact_recovery(baseline_data, tmp_path):
    previous = refresh.exchange_observation(
        {**baseline_data, "asOf": "2026-11-25"}, "2026-11-27",
        source(tmp_path / "previous", "2026-11-27"),
    )
    accepted = {**baseline_data, "exchangeUniverse": {**previous, "signalObservations": {}}}
    assert refresh.exchange_plan(accepted, "2026-12-01") == (True, "2026-11-30")
    prices = market(["2026-11-27", "2026-11-30", "2026-12-01"])
    today = refresh.exchange_observation(
        accepted, "2026-12-01", source(tmp_path / "today", "2026-12-01")
    )
    with pytest.raises(ValueError, match="missing for month-end 2026-11-30"):
        refresh.apply_exchange_observation(prices, accepted, today)
    recovery = refresh.exchange_observation(
        accepted, "2026-11-30", source(tmp_path / "recovery", "2026-11-30")
    )
    result = refresh.apply_exchange_observation(prices, accepted, today, recovery)
    assert result.metadata["exchangeUniverse"]["signalObservations"]["2026-11-30"] == recovery["latest"]


def test_missing_directories_fail_before_price_collection(baseline_data, tmp_path, monkeypatch):
    from factor_lab import integrated_data

    monkeypatch.setattr(automation, "current_source", lambda: "source")
    monkeypatch.setattr(integrated_data, "collect_integrated_market",
                        lambda *a, **kw: pytest.fail("Unexpected price collection"))
    baseline = tmp_path / "site"
    (baseline / "data").mkdir(parents=True)
    (baseline / "data/integrated-result.json").write_text(json.dumps({
        "schemaVersion": "integrated-factor/v1", "data": baseline_data,
    }))
    original = automation.tree_hash(baseline)
    workspace = tmp_path / "workspace"
    with pytest.raises(automation.RefreshInputError, match="evidence is required"):
        automation.run(workspace, baseline, tmp_path / "candidate", "source",
                       now=datetime(2026, 11, 30, 23, tzinfo=timezone.utc))
    status = json.loads((workspace / "status.json").read_text())
    assert status["reasonCode"] == "refresh_failed"
    assert status["reason"].startswith("Exchange directory refresh:")
    assert automation.tree_hash(baseline) == original
    assert not (tmp_path / "candidate").exists()


def test_workflow_freezes_exchange_directories_before_provider_or_calculation():
    workflow = (ROOT / ".github/workflows/daily-dashboard.yml").read_text()
    assert workflow.index("--mode daily") < workflow.index("Download and verify the completed-session")
    assert workflow.index("Preserve validated exchange evidence") < workflow.index(
        "Wait for bounded provider readiness"
    )
    assert "factor-exchange-directory-v1-${{ steps.exchange.outputs.recovery }}" in workflow
    assert '--exchange-directory "outputs/factor-listings/${TARGET_SESSION}"' in workflow
