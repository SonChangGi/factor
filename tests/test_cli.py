import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from factor_lab.config import MAX_TOP_N
from factor_lab.cli import (
    ScheduledGridPreset,
    _compact_summary,
    _config,
    _execute_run,
    _execute_scheduled_grid,
    build_parser,
    main,
)
from factor_lab.research_inputs import ResearchInputs
from factor_lab.workflow import (
    AnalysisResult,
    NoEligibleFactorError,
    result_payload,
    write_result_json,
)


def _command_parser(name: str) -> argparse.ArgumentParser:
    parser = build_parser()
    subparsers = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )
    return subparsers.choices[name]


def test_run_requires_exactly_one_live_local_or_demo_source() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["run"])
    with pytest.raises(SystemExit):
        parser.parse_args(["run", "--live", "--demo"])

    live = parser.parse_args(["run", "--live"])
    assert live.live is True
    assert _config(live).data_mode == "live_market"
    assert _config(live).selection_max_abs_security_day_contribution == pytest.approx(0.10)

    sparse_demo = parser.parse_args(["run", "--demo", "--demo-missing-ratio", "0.001"])
    assert sparse_demo.demo is True
    assert _config(sparse_demo).demo_missing_ratio == pytest.approx(0.001)

    local = parser.parse_args(
        [
            "run",
            "--prices",
            "prices.csv",
            "--volumes",
            "volumes.csv",
            "--volume-basis",
            "split_adjusted",
        ]
    )
    assert local.prices == Path("prices.csv")
    assert local.volumes == Path("volumes.csv")
    assert local.volume_basis == "split_adjusted"


def test_run_cli_maps_top_n_into_the_canonical_bounded_config() -> None:
    parser = build_parser()
    maximum = _config(parser.parse_args(["run", "--demo", "--top-n", str(MAX_TOP_N)]))
    maximum.validate()

    too_large = _config(parser.parse_args(["run", "--demo", "--top-n", str(MAX_TOP_N + 1)]))
    with pytest.raises(ValueError, match=rf"top_n must be between 1 and {MAX_TOP_N}"):
        too_large.validate()

    top_n_action = next(
        action for action in _command_parser("run")._actions if "--top-n" in action.option_strings
    )
    assert str(MAX_TOP_N) in str(top_n_action.help)


@pytest.mark.parametrize(
    ("evaluation_window_days", "minimum_observations"),
    [(21, 21), (126, 126), (252, 252), (756, 504)],
)
def test_run_cli_derives_coverage_for_the_requested_evaluation_window(
    evaluation_window_days: int,
    minimum_observations: int,
) -> None:
    args = build_parser().parse_args(
        ["run", "--demo", "--evaluation-window-days", str(evaluation_window_days)]
    )

    config = _config(args)
    config.validate()
    assert config.min_evaluation_observations == minimum_observations
    assert config.min_daily_risk_observations == minimum_observations


def test_run_cli_exposes_live_coverage_policy_and_output_config() -> None:
    run = _command_parser("run")
    options = {option for action in run._actions for option in action.option_strings}
    expected = {
        "--live",
        "--prices",
        "--market-caps",
        "--demo",
        "--chart-benchmark",
        "--additional-comparison-benchmarks",
        "--min-avg-volume",
        "--stale-after-days",
        "--data-quality-lookback-days",
        "--max-volume-missing-ratio",
        "--max-extreme-daily-return",
        "--min-valuation-coverage",
        "--min-daily-risk-observations",
        "--selection-min-sharpe",
        "--selection-max-drawdown",
        "--selection-max-annualized-cost-drag",
        "--selection-min-effective-names",
        "--selection-max-target-hhi",
        "--selection-max-target-weight",
        "--selection-max-abs-security-day-contribution",
        "--selection-max-security-absolute-contribution-share",
        "--selection-max-leave-one-security-cagr-delta",
        "--selection-extreme-event-action",
        "--selection-extreme-event-penalty-points",
        "--universe",
        "--universe-source-mode",
        "--universe-profile",
        "--max-price-symbols",
        "--price-chunk-size",
        "--yahoo-chart-fallback-limit",
        "--nasdaq-fallback-limit",
        "--stooq-fallback-limit",
        "--finance-datareader-fallback-limit",
        "--retry-count",
        "--retry-backoff-seconds",
        "--market-cache-max-age-hours",
        "--refresh-market-data",
        "--sec-user-agent",
        "--output-dir",
        "--site-dir",
        "--cache-dir",
        "--export-input-snapshot",
    }
    assert expected <= options
    for removed in (
        "--report-dir",
        "--frozen-policy-path",
        "--selected-factor",
        "--factor-selection-mode",
        "--production",
        "--point-in-time-universe-provenance",
        "--score-size-score-weight",
        "--score-size-market-cap-weight",
        "--score-size-liquidity-weight",
        "--score-size-rank-floor",
        "--score-liquidity-score-weight",
        "--score-liquidity-liquidity-weight",
        "--score-liquidity-rank-floor",
        "--policy-sharpe-tolerance",
        "--policy-mdd-tolerance",
        "--policy-max-cost-drag",
        "--policy-min-effective-n",
    ):
        assert removed not in options

    local_api = _command_parser("serve-local-api")
    local_api_options = {
        option for action in local_api._actions for option in action.option_strings
    }
    assert "--allowed-origin" in local_api_options
    parsed = build_parser().parse_args(
        [
            "serve-local-api",
            "--live",
            "--allowed-origin",
            "https://research.example",
            "--allowed-origin",
            "https://preview.example",
        ]
    )
    assert parsed.allowed_origin == [
        "https://research.example",
        "https://preview.example",
    ]


def test_cli_values_map_to_run_config_without_hidden_overrides() -> None:
    args = build_parser().parse_args(
        [
            "run",
            "--live",
            "--universe",
            "AAPL,MSFT,AAPL",
            "--chart-benchmark",
            "^GSPC",
            "--additional-comparison-benchmarks",
            " qqq,QQQ,dia,SPY,^GSPC ",
            "--min-avg-volume",
            "100000",
            "--stale-after-days",
            "3",
            "--min-valuation-coverage",
            "0.95",
            "--min-daily-risk-observations",
            "400",
            "--selection-min-sharpe",
            "0.10",
            "--selection-max-drawdown",
            "0.45",
            "--selection-max-annualized-cost-drag",
            "0.008",
            "--selection-min-effective-names",
            "12",
            "--selection-max-target-hhi",
            "0.12",
            "--selection-max-target-weight",
            "0.11",
            "--selection-max-abs-security-day-contribution",
            "0.40",
            "--selection-max-security-absolute-contribution-share",
            "0.30",
            "--selection-max-leave-one-security-cagr-delta",
            "0.25",
            "--selection-extreme-event-action",
            "penalize",
            "--selection-extreme-event-penalty-points",
            "15",
            "--max-price-symbols",
            "none",
            "--yahoo-chart-fallback-limit",
            "unlimited",
            "--stooq-fallback-limit",
            "0",
            "--market-cache-max-age-hours",
            "12",
            "--refresh-market-data",
            "--output-dir",
            "outputs/live",
            "--site-dir",
            "site/live",
            "--cache-dir",
            "cache/live",
            "--export-input-snapshot",
        ]
    )
    config = _config(args)
    assert config.live is True
    assert config.universe == ["AAPL", "MSFT"]
    assert config.chart_benchmark == "^GSPC"
    assert config.additional_comparison_benchmarks == ("QQQ", "DIA")
    assert config.comparison_benchmarks == ("SPY", "^GSPC", "QQQ", "DIA")
    assert config.min_avg_volume == pytest.approx(100_000.0)
    assert config.stale_after_days == 3
    assert config.min_valuation_coverage == pytest.approx(0.95)
    assert config.min_daily_risk_observations == 400
    assert config.allocation_score_weight == pytest.approx(0.70)
    assert config.allocation_liquidity_weight == pytest.approx(0.30)
    assert config.allocation_market_cap_weight == pytest.approx(0.0)
    assert config.allocation_rank_floor == pytest.approx(0.05)
    assert config.selection_min_sharpe == pytest.approx(0.10)
    assert config.selection_max_drawdown == pytest.approx(0.45)
    assert config.selection_max_annualized_cost_drag == pytest.approx(0.008)
    assert config.selection_min_effective_names == pytest.approx(12.0)
    assert config.selection_max_target_hhi == pytest.approx(0.12)
    assert config.selection_max_target_weight == pytest.approx(0.11)
    assert config.selection_max_abs_security_day_contribution == pytest.approx(0.40)
    assert config.selection_max_security_absolute_contribution_share == pytest.approx(0.30)
    assert config.selection_max_leave_one_security_cagr_delta == pytest.approx(0.25)
    assert config.selection_extreme_event_action == "penalize"
    assert config.selection_extreme_event_penalty_points == pytest.approx(15.0)
    assert config.max_price_symbols is None
    assert config.yahoo_chart_fallback_limit is None
    assert config.stooq_fallback_limit == 0
    assert config.market_cache_max_age_hours == pytest.approx(12.0)
    assert config.refresh_market_data is True
    assert config.output_dir == Path("outputs/live")
    assert config.site_dir == Path("site/live")
    assert config.cache_dir == Path("cache/live")
    assert config.export_input_snapshot is True
    config.validate()


def test_compact_summary_exposes_selection_funnel_performance_and_allocation(
    demo_result: AnalysisResult,
) -> None:
    payload = result_payload(demo_result)
    paths = {"result": "result.json", "index": "docs/index.html"}
    summary = _compact_summary(payload, paths)
    selected = payload["bestFactor"]
    row = next(item for item in payload["factorRanking"] if item["selected"])

    assert summary["asOf"] == payload["data"]["asOf"]
    assert summary["provider"] == payload["data"]["provider"]
    assert summary["requestedCandidateCount"] == payload["data"]["requestedCandidateCount"]
    assert (
        summary["providerReturnedCandidateCount"]
        == payload["data"]["providerReturnedCandidateCount"]
    )
    assert summary["analyzedSecurityCount"] == payload["data"]["analyzedSecurityCount"]
    assert summary["eligibleSecurityCount"] == payload["data"]["latestEligibleSecurityCount"]
    assert summary["factorCount"] == payload["meta"]["factorCount"]
    assert summary["independentFactorCount"] == payload["meta"]["independentFactorCount"]
    assert summary["bestFactor"] == selected
    assert summary["bestFactorReason"] == payload["bestFactorReason"]
    assert summary["weightingPolicy"] == payload["weightingPolicy"]
    assert summary["performance"]["compositeScore"] == row["composite_score"]
    assert summary["performance"]["valuationCoverageRatio"] == row["valuation_coverage_ratio"]
    assert summary["currentAllocation"]["weights"] == payload["bestFactorPortfolio"]["weights"]
    assert (
        summary["currentAllocation"]["cashWeight"] == payload["bestFactorPortfolio"]["cashWeight"]
    )
    assert summary["runtimeSeconds"] == payload["meta"]["runtimeSeconds"]
    assert summary["maxRssBytes"] == payload["meta"]["maxRssBytes"]
    assert summary["paths"] == paths


def test_demo_run_writes_only_isolated_preview_and_preserves_public_aliases(
    demo_result: AnalysisResult,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = result_payload(demo_result)
    output_dir = tmp_path / "outputs" / "demo"
    public_site = tmp_path / "public-site"
    public_data = public_site / "data"
    public_data.mkdir(parents=True)
    sentinel = {
        "dashboard.json": b"canonical-full-market-detail\n",
        "summary.json": b"canonical-full-market-summary\n",
        "grid/v1/manifest.json": b"canonical-full-market-manifest\n",
    }
    for relative, encoded in sentinel.items():
        path = public_data / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded)

    args = build_parser().parse_args(
        [
            "run",
            "--demo",
            "--demo-symbol-count",
            "200",
            "--output-dir",
            str(output_dir),
            "--site-dir",
            str(public_site),
        ]
    )
    monkeypatch.setattr("factor_lab.cli.load_market_data", lambda config: object())
    monkeypatch.setattr(
        "factor_lab.cli.build_result_identity",
        lambda config, market: payload["resultIdentity"],
    )
    monkeypatch.setattr(
        "factor_lab.cli.load_analysis_cache",
        lambda config, identity: payload,
    )
    monkeypatch.setattr(
        "factor_lab.cli.write_payload_json",
        lambda result_payload, path: path / "cached-result.json",
    )

    summary = _execute_run(args)

    for relative, encoded in sentinel.items():
        assert (public_data / relative).read_bytes() == encoded
    assert summary["paths"]["publicationMode"] == "isolated_preview"
    assert Path(summary["paths"]["index"]) == output_dir / "site" / "index.html"
    assert (output_dir / "site" / "data" / "dashboard.json").exists()


def test_full_actual_run_refuses_to_collapse_public_multi_preset_docs_grid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    public_manifest = tmp_path / "docs" / "data" / "grid" / "v1" / "manifest.json"
    public_manifest.parent.mkdir(parents=True)
    public_manifest.write_bytes(b"three-preset-grid\n")
    args = build_parser().parse_args(
        [
            "run",
            "--live",
            "--output-dir",
            str(tmp_path / "outputs"),
            "--site-dir",
            "docs",
        ]
    )
    payload = {
        "resultKey": "a" * 64,
        "data": {
            "mode": "live_market",
            "synthetic": False,
            "analyzedSecurityCount": 2_700,
        },
    }
    monkeypatch.setattr("factor_lab.cli.load_market_data", lambda config: object())
    monkeypatch.setattr(
        "factor_lab.cli._compute_payload",
        lambda config, market: (payload, config.output_dir / "result.json"),
    )

    with pytest.raises(ValueError, match="cannot replace the public multi-preset docs grid"):
        _execute_run(args)

    assert public_manifest.read_bytes() == b"three-preset-grid\n"


def test_scheduled_dashboard_reads_run_site_and_title_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "dashboard.json"
    path.write_text(
        json.dumps(
            {
                "title": "Saved dashboard",
                "site_dir": "saved-site",
                "default_static_grid_preset": "default",
                "static_grid_presets": [
                    {"id": "default", "inputOverrides": {}, "marketSessionOffset": 0},
                    {
                        "id": "top30",
                        "inputOverrides": {
                            "evaluationWindowDays": 1_000,
                            "topN": 30,
                        },
                        "marketSessionOffset": 0,
                    },
                ],
                "run_args": [
                    "--live",
                    "--start-date",
                    "2016-01-01",
                    "--output-dir",
                    "outputs/scheduled",
                    "--export-input-snapshot",
                ],
            }
        ),
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    def fake_execute(
        args: argparse.Namespace,
        *,
        site_dir: Path,
        title: str,
        presets: list[ScheduledGridPreset],
        default_preset_id: str,
    ) -> dict[str, object]:
        captured.update(
            args=args,
            site_dir=site_dir,
            title=title,
            presets=presets,
            default_preset_id=default_preset_id,
        )
        return {"sentinel": True}

    monkeypatch.setattr("factor_lab.cli._execute_scheduled_grid", fake_execute)
    assert main(["scheduled-dashboard", "--config", str(path), "--json"]) == 0

    run_args = captured["args"]
    assert isinstance(run_args, argparse.Namespace)
    assert run_args.live is True
    assert run_args.start_date == "2016-01-01"
    assert run_args.export_input_snapshot is True
    assert captured["site_dir"] == Path("saved-site")
    assert captured["title"] == "Saved dashboard"
    assert captured["default_preset_id"] == "default"
    presets = captured["presets"]
    assert isinstance(presets, list)
    assert [preset.preset_id for preset in presets] == ["default", "top30"]
    assert [preset.research_inputs.top_n for preset in presets] == [20, 30]
    assert [preset.research_inputs.evaluation_window_days for preset in presets] == [
        756,
        1_000,
    ]
    output = json.loads(capsys.readouterr().out)
    assert output["scheduledDashboard"] == {
        "config": str(path),
        "siteDir": "saved-site",
        "title": "Saved dashboard",
    }


def test_scheduled_dashboard_rejects_removed_unused_history_limit(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "dashboard.json"
    path.write_text(
        json.dumps({"history_limit": 17, "run_args": ["--live"]}),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as exc_info:
        main(["scheduled-dashboard", "--config", str(path)])
    assert exc_info.value.code == 2
    assert "history_limit' was removed" in capsys.readouterr().err


def test_scheduled_dashboard_requires_multiple_versioned_static_presets(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "dashboard.json"
    path.write_text(
        json.dumps(
            {
                "run_args": ["--live"],
                "default_static_grid_preset": "only",
                "static_grid_presets": [
                    {"id": "only", "inputOverrides": {}, "marketSessionOffset": 0}
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc_info:
        main(["scheduled-dashboard", "--config", str(path)])

    assert exc_info.value.code == 2
    assert "at least two presets" in capsys.readouterr().err


def test_scheduled_dashboard_rejects_removed_legacy_arguments(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "dashboard.json"
    path.write_text(
        json.dumps({"run_args": ["--live", "--report-dir", "reports/old"]}),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as exc_info:
        main(["scheduled-dashboard", "--config", str(path)])
    assert exc_info.value.code == 2
    assert "removed legacy arguments: --report-dir" in capsys.readouterr().err


def test_scheduled_dashboard_rejects_removed_relative_policy_arguments(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "dashboard.json"
    path.write_text(
        json.dumps(
            {
                "run_args": [
                    "--live",
                    "--policy-sharpe-tolerance",
                    "0.05",
                    "--score-size-market-cap-weight",
                    "0.25",
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc_info:
        main(["scheduled-dashboard", "--config", str(path)])

    assert exc_info.value.code == 2
    error = capsys.readouterr().err
    assert "removed legacy arguments" in error
    assert "--policy-sharpe-tolerance" in error
    assert "--score-size-market-cap-weight" in error


def test_scheduled_grid_recomputes_every_declared_input_and_market_offset_preset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = build_parser().parse_args(
        [
            "run",
            "--live",
            "--output-dir",
            str(tmp_path / "outputs"),
            "--site-dir",
            str(tmp_path / "site"),
        ]
    )
    dates = pd.bdate_range("2024-01-02", periods=12)
    monkeypatch.setattr(
        "factor_lab.cli.expected_recent_us_close_date", lambda now: dates[-1].date()
    )
    base_market = SimpleNamespace(
        candidate_symbols=[f"S{index:04d}" for index in range(2_700)],
        prices=pd.DataFrame({"SPY": 100.0}, index=dates),
        comparison_prices=pd.DataFrame(index=dates),
        requested_through=dates[-1].date().isoformat(),
    )
    read_configs = []
    computed_configs = []
    published = {}

    monkeypatch.setattr("factor_lab.cli.load_market_data", lambda config: base_market)
    monkeypatch.setattr(
        "factor_lab.cli.write_market_data_snapshot",
        lambda market, path: {"manifest": str(path / "market_data_manifest.json")},
    )

    def fake_read_snapshot(config, path):
        read_configs.append(config)
        return SimpleNamespace(
            candidate_symbols=base_market.candidate_symbols,
            prices=base_market.prices.loc[: config.end_date]
            if config.end_date
            else base_market.prices,
            requested_through=config.effective_end_date,
        )

    monkeypatch.setattr("factor_lab.cli.read_market_data_snapshot", fake_read_snapshot)

    def fake_compute(config, market):
        computed_configs.append(config)
        as_of = config.end_date or dates[-1].date().isoformat()
        result_key = f"{config.top_n:04d}{as_of.replace('-', '')}".ljust(64, "a")
        payload = {
            "resultKey": result_key,
            "data": {
                "mode": "live_market",
                "synthetic": False,
                "asOf": as_of,
                "analyzedSecurityCount": len(market.candidate_symbols),
            },
            "researchInputs": ResearchInputs.from_config(config).to_dict(),
        }
        return payload, config.output_dir / f"{result_key}.json"

    monkeypatch.setattr("factor_lab.cli._compute_payload", fake_compute)
    monkeypatch.setattr(
        "factor_lab.cli._require_full_actual_publication",
        lambda payload, config: None,
    )
    monkeypatch.setattr(
        "factor_lab.cli.dashboard_summary",
        lambda payload: {"resultKey": payload["resultKey"]},
    )
    monkeypatch.setattr(
        "factor_lab.cli.write_dashboard_site",
        lambda payload, site_dir, title: {"index": str(site_dir / "index.html")},
    )

    def fake_write_grid(data_dir, artifacts, *, default_result_key, write_default_aliases):
        published.update(
            artifacts=list(artifacts),
            default_result_key=default_result_key,
            write_default_aliases=write_default_aliases,
        )
        return {"manifest": data_dir / "grid" / "v1" / "manifest.json"}

    monkeypatch.setattr("factor_lab.cli.write_static_grid", fake_write_grid)
    monkeypatch.setattr("factor_lab.cli.validate_static_grid", lambda path: {})
    monkeypatch.setattr(
        "factor_lab.cli._compact_summary",
        lambda payload, paths: {"resultKey": payload["resultKey"], "paths": paths},
    )
    presets = [
        ScheduledGridPreset("latest-top20", ResearchInputs(top_n=20), 0),
        ScheduledGridPreset("latest-top30", ResearchInputs(top_n=30), 0),
        ScheduledGridPreset("prior-seven", ResearchInputs(top_n=20), 7),
    ]

    summary = _execute_scheduled_grid(
        args,
        site_dir=tmp_path / "site",
        title="Scheduled grid",
        presets=presets,
        default_preset_id="latest-top20",
    )

    assert len(computed_configs) == 3
    assert [config.top_n for config in computed_configs] == [20, 30, 20]
    assert computed_configs[0].end_date == dates[-1].date().isoformat()
    assert computed_configs[1].end_date == dates[-1].date().isoformat()
    assert computed_configs[2].end_date == dates[-8].date().isoformat()
    assert len(read_configs) == 2
    assert len(published["artifacts"]) == 3
    assert [artifact.preset_id for artifact in published["artifacts"]] == [
        "latest-top20",
        "latest-top30",
        "prior-seven",
    ]
    assert published["default_result_key"] == summary["resultKey"]
    assert published["write_default_aliases"] is True
    assert [receipt["marketSessionOffset"] for receipt in summary["staticGridPresets"]] == [
        0,
        0,
        7,
    ]
    assert summary["automationStatus"]["state"] == "available"
    assert Path(summary["paths"]["automationStatus"]).exists()


def test_scheduled_grid_preserves_last_good_when_no_factor_is_eligible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site_dir = tmp_path / "site"
    data_dir = site_dir / "data"
    data_dir.mkdir(parents=True)
    dashboard_path = data_dir / "dashboard.json"
    dashboard_bytes = json.dumps(
        {
            "schemaVersion": 5,
            "resultKey": "f" * 64,
            "generatedAtUtc": "2026-07-27T23:06:06Z",
            "data": {"asOf": "2026-07-27"},
        }
    ).encode()
    dashboard_path.write_bytes(dashboard_bytes)
    manifest_path = data_dir / "grid" / "v1" / "manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_bytes(b"last-good-grid\n")

    args = build_parser().parse_args(
        [
            "run",
            "--live",
            "--output-dir",
            str(tmp_path / "outputs"),
            "--site-dir",
            str(site_dir),
        ]
    )
    dates = pd.bdate_range("2026-07-01", periods=20)
    monkeypatch.setattr(
        "factor_lab.cli.expected_recent_us_close_date", lambda now: dates[-1].date()
    )
    base_market = SimpleNamespace(
        candidate_symbols=[f"S{index:04d}" for index in range(2_700)],
        prices=pd.DataFrame({"SPY": 100.0}, index=dates),
        comparison_prices=pd.DataFrame(index=dates),
        requested_through=dates[-1].date().isoformat(),
        as_of=dates[-1],
    )
    monkeypatch.setattr("factor_lab.cli.load_market_data", lambda config: base_market)
    monkeypatch.setattr(
        "factor_lab.cli.write_market_data_snapshot",
        lambda market, path: {"manifest": str(path / "market_data_manifest.json")},
    )

    error = NoEligibleFactorError(
        [
            {
                "factor": "mom_12_1",
                "policy_id": "score_liquidity_rank",
                "guardrail_breaches": ["minimum_sharpe", "maximum_drawdown"],
            }
        ]
    )
    monkeypatch.setattr(
        "factor_lab.cli._compute_payload",
        lambda config, market: (_ for _ in ()).throw(error),
    )

    summary = _execute_scheduled_grid(
        args,
        site_dir=site_dir,
        title="Scheduled grid",
        presets=[
            ScheduledGridPreset("latest-top20", ResearchInputs(top_n=20), 0),
            ScheduledGridPreset("latest-top30", ResearchInputs(top_n=30), 0),
        ],
        default_preset_id="latest-top20",
    )

    status = summary["automationStatus"]
    assert status["state"] == "degraded"
    assert status["reasonCode"] == "no_eligible_factor"
    assert status["targetDataAsOf"] == dates[-1].date().isoformat()
    assert status["analysis"]["eligibleFactorCount"] == 0
    assert status["analysis"]["guardrailsRelaxed"] is False
    assert status["analysis"]["fallbackFactorSelected"] is False
    assert status["publication"] == {
        "updated": False,
        "lastGoodPreserved": True,
        "policy": "preserve_last_good",
    }
    assert status["lastGood"]["resultKey"] == "f" * 64
    assert dashboard_path.read_bytes() == dashboard_bytes
    assert manifest_path.read_bytes() == b"last-good-grid\n"
    assert json.loads(Path(summary["paths"]["automationStatus"]).read_text()) == status


def test_committed_dashboard_config_runs_full_packaged_live_universe() -> None:
    payload = json.loads(Path(".github/factor-dashboard-config.json").read_text(encoding="utf-8"))
    run_args = payload["run_args"]
    args = build_parser().parse_args(["run", *run_args])
    config = _config(args)

    assert config.live is True
    assert config.start_date == "2016-01-01"
    assert config.end_date is None
    assert config.universe_source_mode == "packaged"
    assert config.universe_profile == "large_liquid"
    assert len(config.universe) >= 2_700
    assert config.max_price_symbols is None
    assert config.refresh_market_data is True
    assert config.min_avg_dollar_volume == pytest.approx(5_000_000.0)
    assert config.stooq_fallback_limit == 0
    assert config.finance_datareader_fallback_limit == 0
    assert config.export_input_snapshot is True
    assert payload["default_static_grid_preset"] == "latest-top20"
    assert [preset["marketSessionOffset"] for preset in payload["static_grid_presets"]] == [
        0,
        0,
        7,
    ]
    assert [
        preset.get("inputOverrides", {}).get("topN", 20)
        for preset in payload["static_grid_presets"]
    ] == [
        20,
        30,
        20,
    ]
    assert "--end-date" not in run_args
    assert "--max-price-symbols" not in run_args
    assert not (
        {item for item in run_args if item.startswith("--")}
        & {
            "--report-dir",
            "--selected-factor",
            "--factor-selection-mode",
            "--frozen-policy-path",
            "--target-aum",
            "--max-adv-participation",
        }
    )
    config.validate()


def test_build_site_command_reuses_schema_v3_result(
    demo_result: AnalysisResult,
    tmp_path: Path,
) -> None:
    result_path = write_result_json(demo_result)
    site = tmp_path / "site"
    assert main(["build-site", "--input", str(result_path), "--site-dir", str(site)]) == 0
    assert (site / "index.html").exists()
    assert (site / "data" / "dashboard.json").exists()
    result = json.loads(result_path.read_text(encoding="utf-8"))
    site_payload = json.loads((site / "data" / "dashboard.json").read_text(encoding="utf-8"))
    summary = json.loads((site / "data" / "summary.json").read_text(encoding="utf-8"))
    assert result["generatedAtUtc"] == site_payload["generatedAtUtc"]
    assert summary["generatedAt"] == result["generatedAtUtc"]


def test_build_site_defaults_to_isolated_preview_and_rejects_public_alias_bypass(
    demo_result: AnalysisResult,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = build_parser()
    parsed = parser.parse_args(["build-site", "--input", "result.json"])
    assert parsed.site_dir == Path("outputs/site-preview")

    result_path = write_result_json(demo_result).resolve()
    public_data = tmp_path / "docs" / "data"
    public_data.mkdir(parents=True)
    sentinel = public_data / "dashboard.json"
    sentinel.write_bytes(b"canonical actual-market alias\n")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "build-site",
                "--input",
                str(result_path),
                "--site-dir",
                "docs",
            ]
        )

    assert exc_info.value.code == 2
    assert "build-site cannot write the public docs aliases" in capsys.readouterr().err
    assert sentinel.read_bytes() == b"canonical actual-market alias\n"
