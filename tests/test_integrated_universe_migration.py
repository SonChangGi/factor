import json
from pathlib import Path

import pandas as pd
import pytest

from factor_lab import integrated_universe_migration as migration
from factor_lab.integrated_exchange_refresh import apply_exchange_observation, exchange_plan
from factor_lab.integrated_data import FIELDS, IntegratedMarket


@pytest.fixture
def contract(tmp_path, monkeypatch):
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({
        "schemaVersion": "factor-reviewed-universe/v1", "version": "test-v1",
        "applyThrough": "2026-11-04", "excluded": {"OTC": "otc_legacy"},
        "listedStockCount": 1, "sources": [],
    }))
    monkeypatch.setattr(migration, "POLICY", policy)
    return migration.historical_contract()


def market():
    dates = pd.to_datetime(["2026-10-30", "2026-11-04", "2026-11-05"])
    values = pd.DataFrame(10.0, index=dates, columns=["A", "OTC"])
    fields = {field: values.copy() for field in FIELDS}
    fields["eligibility"] = values.gt(0)
    return IntegratedMarket(**fields, metadata={"requestedSymbols": ["A", "OTC"]})


def test_migration_changes_only_reviewed_eligibility_and_preserves_original(contract):
    original = market()
    result = migration.apply_historical_universe(original, contract)
    assert result.eligibility.OTC.tolist() == [False, False, True]
    assert original.eligibility.OTC.all()
    pd.testing.assert_frame_equal(result.prices, original.prices)
    with pytest.raises(ValueError, match="reviewed policy"):
        migration.apply_historical_universe(original, {**contract, "excluded": {}})


def test_daily_refresh_replays_historical_cohort_before_new_session_rules(contract):
    original = market()
    current = {"policyVersion": "forward", "policySha256": "a" * 64, "latest": {
        "session": "2026-11-05", "excluded": {"OTC": "otc_legacy"},
    }}
    result = apply_exchange_observation(original, {
        "asOf": "2026-11-04", "historicalUniverse": contract,
    }, current)
    assert result.eligibility.OTC.tolist() == [False, False, False]
    assert result.metadata["historicalUniverse"] == contract


def test_daily_refresh_after_migration_requires_missing_month_end_evidence(contract, monkeypatch):
    from factor_lab import integrated_exchange_refresh as refresh

    # An active prospective policy is needed even when its first observation is later.
    monkeypatch.setattr(refresh, "reviewed_policy", lambda *args: ({"version": "v1"}, "digest"))
    assert exchange_plan({
        "asOf": "2026-11-04", "historicalUniverse": contract,
    }, "2026-12-01") == (True, "2026-11-30")


def test_publication_rejects_historical_targets_from_excluded_security(contract):
    result = {
        "data": {"historicalUniverse": contract, "requestedSymbols": ["A", "OTC"]},
        "resultIdentity": {"codeHashFiles": {
            "resources/integrated_historical_universe.json": contract["policySha256"],
        }},
        "selection": {"history": [{"signalDate": "2026-10-30", "targetHoldings": [{"symbol": "A"}]}]},
        "factors": [],
    }
    migration.validate_historical_targets(result)
    result["selection"]["history"][0]["targetHoldings"] = [{"symbol": "OTC"}]
    with pytest.raises(ValueError, match="excluded security"):
        migration.validate_historical_targets(result)


def test_migration_requires_exact_reviewed_baseline_before_any_workspace_creation(tmp_path):
    baseline = tmp_path / "site"
    (baseline / "data").mkdir(parents=True)
    (baseline / "data/integrated-result.json").write_text(json.dumps({
        "resultIdentity": {"resultId": "different", "inputHash": "different"},
    }))
    from factor_lab.integrated_automation import current_source
    workspace = tmp_path / "run"
    with pytest.raises(ValueError, match="exact reviewed"):
        migration.migrate(workspace, baseline, tmp_path / "candidate", tmp_path, current_source())
    assert not workspace.exists()


def test_manual_migration_shares_daily_concurrency_and_has_no_collection():
    text = (Path(__file__).resolve().parents[1] / ".github/workflows/reviewed-universe.yml").read_text()
    assert "daily-factor-dashboard-${{ github.ref }}" in text
    assert "schedule:" not in text
    assert "collect_integrated_market" not in text
    assert "--mode daily" in text and "confirm-input-cache" in text
    assert "git push" in text and "expected_source_sha" in text
    assert text.index("bash scripts/check_release.sh") < text.index("git commit")
    assert "node-version: '22'" in text
