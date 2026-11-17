import argparse
import json
from pathlib import Path

import pytest

from factor_lab.config import MAX_TOP_N
from factor_lab.cli import _compact_summary, _config, _execute_run, build_parser, main
from factor_lab.workflow import (
    AnalysisResult,
    result_payload,
    write_result_json,
)


def _command_parser(name: str) -> argparse.ArgumentParser:
    parser = build_parser()
    subparsers = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )
    return subparsers.choices[name]


def test_run_requires_exactly_one_local_or_demo_source() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["run"])
    with pytest.raises(SystemExit):
        parser.parse_args(["run", "--demo", "--prices", "prices.csv"])

    with pytest.raises(SystemExit):
        parser.parse_args(["run", "--live"])

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


def test_run_cli_exposes_offline_coverage_policy_and_output_config() -> None:
    run = _command_parser("run")
    options = {option for action in run._actions for option in action.option_strings}
    expected = {
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



def test_cli_values_map_to_run_config_without_hidden_overrides() -> None:
    args = build_parser().parse_args(
        [
            "run",
            "--demo",
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
    assert config.live is False
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
            "--demo",
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
