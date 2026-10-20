import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from factor_lab import cli
from factor_lab.research_inputs import ResearchInputs


def saved_site(tmp_path):
    site = tmp_path / "site"
    (site / "data").mkdir(parents=True)
    (site / "index.html").write_text("last good page")
    (site / "data/dashboard.json").write_text(json.dumps({
        "schemaVersion": 5,
        "resultKey": "a" * 64,
        "data": {"asOf": "2026-09-16"},
        "generatedAtUtc": "2026-09-17T00:08:47Z",
    }))
    return site


def run_grid(site, tmp_path):
    args = cli.build_parser().parse_args([
        "run", "--live", "--output-dir", str(tmp_path / "output"),
    ])
    return cli._execute_scheduled_grid(
        args, site_dir=site, title="Recovery",
        presets=[cli.ScheduledGridPreset("latest-top20", ResearchInputs(), 0)],
        default_preset_id="latest-top20",
    )


def test_partial_candidate_write_never_replaces_last_good(tmp_path, monkeypatch):
    site = saved_site(tmp_path)
    original = (site / "data/dashboard.json").read_bytes()

    def failing_builder(args, *, site_dir, **kwargs):
        (site_dir / "index.html").write_text("incomplete candidate")
        (site_dir / "data/dashboard.json").write_text("invalid partial JSON")
        raise ValueError("private provider details must not enter public status")

    monkeypatch.setattr(cli, "_build_scheduled_grid", failing_builder)
    summary = run_grid(site, tmp_path)
    status = summary["automationStatus"]
    assert status["state"] == "failed"
    assert status["reasonCode"] == "execution_failed"
    assert status["lastGood"]["dataAsOf"] == "2026-09-16"
    assert status["publication"]["lastGoodPreserved"] is True
    assert "private provider" not in json.dumps(status)
    assert (site / "index.html").read_text() == "last good page"
    assert (site / "data/dashboard.json").read_bytes() == original
    assert not list(tmp_path.glob(".momentum-candidate-*"))


@pytest.mark.parametrize("observed,reason", [
    ("2026-09-16", "stale_market_data"),
    ("2026-09-18", "incomplete_market_session"),
])
def test_only_completed_target_session_can_enter_analysis(tmp_path, monkeypatch, observed, reason):
    site = saved_site(tmp_path)
    dates = pd.DatetimeIndex([pd.Timestamp(observed)])
    market = SimpleNamespace(
        candidate_symbols=[f"S{i:04d}" for i in range(2700)],
        prices=pd.DataFrame({"SPY": [100.0]}, index=dates),
    )
    monkeypatch.setattr(cli, "expected_recent_us_close_date", lambda now: date(2026, 9, 17))
    def collect(config):
        assert config.end_date == "2026-09-17"
        return market

    monkeypatch.setattr(cli, "load_market_data", collect)
    monkeypatch.setattr(cli, "write_market_data_snapshot", lambda market, path: {})
    monkeypatch.setattr(cli, "_compute_payload", lambda *args: pytest.fail("must not analyze"))
    summary = run_grid(site, tmp_path)
    assert summary["automationStatus"]["reasonCode"] == reason
    assert summary["automationStatus"]["targetDataAsOf"] == "2026-09-17"
    assert json.loads((site / "data/dashboard.json").read_text())["data"]["asOf"] == "2026-09-16"


def test_verified_candidate_receipt_uses_published_paths(tmp_path, monkeypatch):
    site = saved_site(tmp_path)

    def success_builder(args, *, site_dir, **kwargs):
        (site_dir / "index.html").write_text("verified candidate")
        return {"paths": {"index": str(site_dir / "index.html")}}

    monkeypatch.setattr(cli, "_build_scheduled_grid", success_builder)
    summary = run_grid(site, tmp_path)
    assert summary["paths"]["index"] == str(site / "index.html")
    assert Path(summary["paths"]["index"]).read_text() == "verified candidate"


def test_historical_preset_failure_keeps_the_current_run_target(tmp_path, monkeypatch):
    site = saved_site(tmp_path)
    dates = pd.bdate_range(end="2026-09-17", periods=20)
    market = SimpleNamespace(
        candidate_symbols=[f"S{i:04d}" for i in range(2700)],
        prices=pd.DataFrame({"SPY": 100.0}, index=dates), as_of=dates[-1],
        comparison_prices=pd.DataFrame(index=dates),
    )
    monkeypatch.setattr(cli, "expected_recent_us_close_date", lambda now: dates[-1].date())
    monkeypatch.setattr(cli, "load_market_data", lambda config: market)
    monkeypatch.setattr(cli, "write_market_data_snapshot", lambda market, path: {})
    monkeypatch.setattr(cli, "read_market_data_snapshot", lambda config, path: SimpleNamespace(
        as_of=pd.Timestamp(config.end_date), requested_through=config.end_date,
    ))
    monkeypatch.setattr(cli, "dashboard_summary", lambda payload: {})

    def compute(config, snapshot):
        if config.end_date < "2026-09-17":
            raise cli.NoEligibleFactorError([{
                "factor": "mom_12_1", "guardrail_breaches": ["sharpe"],
            }])
        return {
            "resultKey": "b" * 64,
            "data": {"mode": "live_market", "synthetic": False,
                     "asOf": "2026-09-17", "analyzedSecurityCount": 2700},
            "researchInputs": ResearchInputs().to_dict(),
        }, tmp_path / "result.json"

    monkeypatch.setattr(cli, "_compute_payload", compute)
    args = cli.build_parser().parse_args(["run", "--live", "--output-dir", str(tmp_path / "out")])
    summary = cli._execute_scheduled_grid(
        args, site_dir=site, title="Recovery", default_preset_id="latest-top20",
        presets=[cli.ScheduledGridPreset("latest-top20", ResearchInputs(), 0),
                 cli.ScheduledGridPreset("historical", ResearchInputs(), 7)],
    )
    status = summary["automationStatus"]
    assert status["targetDataAsOf"] == "2026-09-17"
    assert status["affectedPresetDataAsOf"] == str(dates[-8].date())
    assert status["affectedPresetId"] == "historical"
    assert json.loads((site / "data/dashboard.json").read_text())["data"]["asOf"] == "2026-09-16"


@pytest.mark.parametrize("state,reason,expected", [
    ("failed", "execution_failed", 2),
    ("degraded", "no_comparable_factor", 2),
    ("degraded", "no_eligible_factor", 0),
])
def test_scheduler_exit_distinguishes_failure_from_valid_no_selection(
    tmp_path, monkeypatch, state, reason, expected,
):
    monkeypatch.setattr(cli, "_execute_scheduled_grid", lambda *args, **kwargs: {
        "automationStatus": {
            "state": state, "reasonCode": reason, "targetDataAsOf": "2026-09-17",
            "publication": {"lastGoodPreserved": True},
        },
    })
    config = Path(".github/factor-dashboard-config.json")
    assert cli.main(["scheduled-dashboard", "--config", str(config), "--json"]) == expected


def test_partial_latest_session_is_rejected_before_analysis(tmp_path, monkeypatch):
    site = saved_site(tmp_path)
    dates = pd.to_datetime(['2026-09-18', '2026-09-21'])
    symbols = [f'S{i:04d}' for i in range(2700)]
    prices = pd.DataFrame(100., index=dates, columns=symbols)
    prices.loc[dates[-1], symbols[16:]] = float('nan')
    market = SimpleNamespace(candidate_symbols=symbols, prices=prices)
    monkeypatch.setattr(cli, 'expected_recent_us_close_date', lambda now: dates[-1].date())
    monkeypatch.setattr(cli, 'load_market_data', lambda config: market)
    monkeypatch.setattr(cli, 'write_market_data_snapshot', lambda *args: {})
    monkeypatch.setattr(cli, '_compute_payload', lambda *args: pytest.fail('must not analyze'))
    summary = run_grid(site, tmp_path)
    status = summary['automationStatus']
    assert status['reasonCode'] == 'incomplete_market_data'
    assert status['diagnostics']['targetSessionPricedCandidateCount'] == 16
    assert status['publication']['lastGoodPreserved'] is True
    assert json.loads((site / 'data/dashboard.json').read_text())['data']['asOf'] == '2026-09-16'


def test_missing_comparison_history_is_rejected_before_backtests(tmp_path, monkeypatch):
    site = saved_site(tmp_path)
    original = (site / 'data/dashboard.json').read_bytes()
    dates = pd.to_datetime(['2026-09-21', '2026-09-22', '2026-09-23'])
    market = SimpleNamespace(
        candidate_symbols=[f'S{i:04d}' for i in range(2700)],
        prices=pd.DataFrame({'SPY': 100.}, index=dates),
        comparison_prices=pd.DataFrame({'^IXIC': [27122.09, float('nan'), 26936.04]}, index=dates),
    )
    monkeypatch.setattr(cli, 'expected_recent_us_close_date', lambda now: dates[-1].date())
    monkeypatch.setattr(cli, 'load_market_data', lambda config: market)
    monkeypatch.setattr(cli, 'write_market_data_snapshot', lambda *args: {})
    monkeypatch.setattr(cli, '_compute_payload', lambda *args: pytest.fail('must not analyze'))
    status = run_grid(site, tmp_path)['automationStatus']
    assert status['reasonCode'] == 'incomplete_market_data'
    assert status['diagnostics']['missingComparisonDates'] == ['2026-09-22']
    assert status['publication']['lastGoodPreserved'] is True
    assert (site / 'data/dashboard.json').read_bytes() == original
