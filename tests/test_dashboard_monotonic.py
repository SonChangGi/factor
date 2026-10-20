from __future__ import annotations

import json
from pathlib import Path

from factor_lab.dashboard_monotonic import (
    decide_monotonic_dashboard,
    load_dashboard_snapshot,
    main,
)


def _write_dashboard(path: Path, *, data_as_of: str, run_timestamp: str) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at_utc": run_timestamp,
                "latest_run_index": 0,
                "runs": [
                    {
                        "summary": {
                            "data_as_of": data_as_of,
                            "run_timestamp_utc": run_timestamp,
                            "selected_factor": "mom_9_1",
                        },
                        "latest_output_rows": [
                            {"symbol": f"S{index:02d}", "rank": index + 1} for index in range(12)
                        ],
                        "factor_score_snapshots": [
                            {
                                "date": data_as_of,
                                "factor": "mom_9_1",
                                "rows": [
                                    [f"S{index:02d}", 1.0 - index / 100] for index in range(12)
                                ],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_dashboard_v5(
    path: Path,
    *,
    data_as_of: str,
    run_timestamp: str,
    holding_count: int = 20,
    analyzed_count: int = 2_857,
) -> Path:
    weights = [
        {"symbol": f"S{index:02d}", "weight": 1.0 / holding_count} for index in range(holding_count)
    ]
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 5,
                "resultKey": "a" * 64,
                "resultIdentity": {
                    "identityVersion": "momentum-result-identity-v1",
                    "resultKey": "a" * 64,
                    "keyParts": {},
                },
                "generatedAtUtc": run_timestamp,
                "bestFactor": "mom_12m",
                "data": {
                    "asOf": data_as_of,
                    "analyzedSecurityCount": analyzed_count,
                },
                "bestFactorPortfolio": {"weights": weights},
                "factorPortfolios": {"mom_12m": {"weights": weights}},
                "factorAccounting": {
                    "expectedIndependentFactorCount": 61,
                    "evaluatedIndependentFactorCount": 61,
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_schema_v5_snapshot_uses_best_factor_identity_and_counts(tmp_path: Path) -> None:
    snapshot = load_dashboard_snapshot(
        _write_dashboard_v5(
            tmp_path / "v5.json",
            data_as_of="2026-07-10",
            run_timestamp="2026-07-11T01:00:00Z",
        )
    )

    assert snapshot.data_as_of is not None
    assert snapshot.data_as_of.isoformat() == "2026-07-10"
    assert snapshot.run_timestamp is not None
    assert snapshot.latest_output_rows == 20
    assert snapshot.selected_factor_snapshot_rows == 20
    assert snapshot.primary_entities == 2_857
    assert snapshot.result_key == "a" * 64
    assert snapshot.expected_factors == 61
    assert snapshot.evaluated_factors == 61


def test_schema_v5_monotonic_guard_rejects_collapsed_holdings(tmp_path: Path) -> None:
    baseline = load_dashboard_snapshot(
        _write_dashboard_v5(
            tmp_path / "baseline-v5.json",
            data_as_of="2026-07-10",
            run_timestamp="2026-07-11T01:00:00Z",
        )
    )
    candidate = load_dashboard_snapshot(
        _write_dashboard_v5(
            tmp_path / "candidate-v5.json",
            data_as_of="2026-07-10",
            run_timestamp="2026-07-11T02:00:00Z",
            holding_count=5,
        )
    )

    decision = decide_monotonic_dashboard(baseline, candidate)

    assert decision.passed is False
    assert "publication floor" in decision.reason


def test_monotonic_guard_allows_equal_or_newer_candidate(tmp_path: Path) -> None:
    baseline = load_dashboard_snapshot(
        _write_dashboard(
            tmp_path / "baseline.json",
            data_as_of="2026-06-10",
            run_timestamp="2026-06-10T12:00:00Z",
        )
    )
    candidate = load_dashboard_snapshot(
        _write_dashboard(
            tmp_path / "candidate.json",
            data_as_of="2026-06-10",
            run_timestamp="2026-06-11T01:00:00Z",
        )
    )

    decision = decide_monotonic_dashboard(baseline, candidate)

    assert decision.passed
    assert "not older" in decision.reason


def test_monotonic_guard_blocks_older_data_as_of(tmp_path: Path) -> None:
    baseline = load_dashboard_snapshot(
        _write_dashboard(
            tmp_path / "baseline.json",
            data_as_of="2026-06-10",
            run_timestamp="2026-06-10T12:00:00Z",
        )
    )
    candidate = load_dashboard_snapshot(
        _write_dashboard(
            tmp_path / "candidate.json",
            data_as_of="2026-06-09",
            run_timestamp="2026-06-11T01:00:00Z",
        )
    )

    decision = decide_monotonic_dashboard(baseline, candidate)

    assert not decision.passed
    assert "data_as_of" in decision.reason


def test_monotonic_guard_blocks_older_run_timestamp(tmp_path: Path) -> None:
    baseline = load_dashboard_snapshot(
        _write_dashboard(
            tmp_path / "baseline.json",
            data_as_of="2026-06-10",
            run_timestamp="2026-06-10T12:00:00Z",
        )
    )
    candidate = load_dashboard_snapshot(
        _write_dashboard(
            tmp_path / "candidate.json",
            data_as_of="2026-06-10",
            run_timestamp="2026-06-10T11:59:00Z",
        )
    )

    decision = decide_monotonic_dashboard(baseline, candidate)

    assert not decision.passed
    assert "run_timestamp" in decision.reason


def test_monotonic_guard_normalizes_naive_timestamps(tmp_path: Path) -> None:
    baseline = load_dashboard_snapshot(
        _write_dashboard(
            tmp_path / "baseline.json",
            data_as_of="2026-06-10",
            run_timestamp="2026-06-10T12:00:00Z",
        )
    )
    candidate = load_dashboard_snapshot(
        _write_dashboard(
            tmp_path / "candidate.json",
            data_as_of="2026-06-10",
            run_timestamp="2026-06-10T12:01:00",
        )
    )

    decision = decide_monotonic_dashboard(baseline, candidate)

    assert decision.passed


def test_monotonic_guard_cli_returns_nonzero_on_regression(tmp_path: Path, capsys) -> None:
    baseline = _write_dashboard(
        tmp_path / "baseline.json", data_as_of="2026-06-10", run_timestamp="2026-06-10T12:00:00Z"
    )
    candidate = _write_dashboard(
        tmp_path / "candidate.json", data_as_of="2026-06-09", run_timestamp="2026-06-11T01:00:00Z"
    )

    exit_code = main(["--baseline", str(baseline), "--candidate", str(candidate)])

    stdout = capsys.readouterr().out
    assert exit_code == 1
    assert "passed=false" in stdout
    assert "baseline_data_as_of=2026-06-10" in stdout
    assert "candidate_data_as_of=2026-06-09" in stdout
