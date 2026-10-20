from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from factor_lab.dashboard_freshness import (
    decide_dashboard_freshness,
    expected_recent_us_close_date,
    load_dashboard_payload,
    main,
)


def _dashboard(
    timestamp: str, *, data_as_of: str = "2026-06-09", latest_run_index: int = 0
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "latest_run_index": latest_run_index,
        "runs": [{"summary": {"run_timestamp_utc": timestamp, "data_as_of": data_as_of}}],
    }


def _dashboard_v5(
    timestamp: str,
    *,
    data_as_of: str = "2026-06-09",
    result_key: str = "a" * 64,
) -> dict[str, object]:
    return {
        "schemaVersion": 5,
        "resultKey": result_key,
        "generatedAtUtc": timestamp,
        "data": {"asOf": data_as_of},
    }


def _automation(
    state: str,
    attempted_at: str,
    *,
    dashboard: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schemaVersion": 1,
        "contract": "momentum-dashboard-automation-status",
        "state": state,
        "attemptedAtUtc": attempted_at,
    }
    if dashboard is not None:
        data = dashboard.get("data")
        assert isinstance(data, dict)
        payload.update(
            {
                "targetDataAsOf": data.get("asOf"),
                "publication": {
                    "updated": state == "available",
                    "lastGoodPreserved": state != "available",
                },
                "lastGood": {
                    "resultKey": dashboard.get("resultKey"),
                    "dataAsOf": data.get("asOf"),
                    "generatedAtUtc": dashboard.get("generatedAtUtc"),
                    "path": "data/dashboard.json",
                },
            }
        )
    return payload


def test_first_state_without_public_status_skips_when_dashboard_is_fresh() -> None:
    decision = decide_dashboard_freshness(
        _dashboard_v5("2026-06-09T22:27:00Z", data_as_of="2026-06-09"),
        event_name="schedule",
        now=datetime(2026, 6, 9, 23, 47, tzinfo=UTC),
    )

    assert decision.skip is True
    assert decision.latest_run_kst is not None
    assert decision.latest_run_kst.isoformat() == "2026-06-10T07:27:00+09:00"
    assert decision.latest_data_as_of is not None
    assert decision.latest_data_as_of.isoformat() == "2026-06-09"


def test_schedule_runs_when_latest_execution_is_before_kst_cutoff() -> None:
    decision = decide_dashboard_freshness(
        _dashboard("2026-06-09T17:10:35+00:00"),
        event_name="schedule",
        now=datetime(2026, 6, 9, 23, 17, tzinfo=UTC),
    )

    assert decision.skip is False
    assert decision.latest_run_kst is not None
    assert decision.latest_run_kst.hour == 2


def test_schedule_skips_after_cutoff_with_target_date() -> None:
    decision = decide_dashboard_freshness(
        _dashboard("2026-06-09T22:27:00Z", data_as_of="2026-06-09"),
        event_name="schedule",
        now=datetime(2026, 6, 9, 23, 47, tzinfo=UTC),
    )

    assert decision.skip is True
    assert "fresh successful publication" in decision.reason
    assert decision.latest_data_as_of is not None
    assert decision.latest_data_as_of.isoformat() == "2026-06-09"
    assert decision.target_data_as_of.isoformat() == "2026-06-09"


def test_schedule_retries_when_execution_after_cutoff_has_stale_data_as_of() -> None:
    decision = decide_dashboard_freshness(
        _dashboard("2026-06-10T23:20:00Z", data_as_of="2026-06-09"),
        event_name="schedule",
        now=datetime(2026, 6, 10, 23, 47, tzinfo=UTC),
    )

    assert decision.skip is False
    assert "older than target" in decision.reason
    assert decision.target_data_as_of.isoformat() == "2026-06-10"


def test_exact_kst_cutoff_with_target_data_is_fresh() -> None:
    decision = decide_dashboard_freshness(
        _dashboard("2026-06-09T22:17:00Z", data_as_of="2026-06-09"),
        event_name="schedule",
        now=datetime(2026, 6, 9, 23, 17, tzinfo=UTC),
    )

    assert decision.skip is True


def test_generated_at_is_used_when_run_timestamp_is_missing() -> None:
    decision = decide_dashboard_freshness(
        {
            "schema_version": 1,
            "latest_run_index": 0,
            "runs": [
                {
                    "generated_at_utc": "2026-06-09T22:27:00Z",
                    "summary": {"data_as_of": "2026-06-09"},
                }
            ],
        },
        event_name="schedule",
        now=datetime(2026, 6, 9, 23, 47, tzinfo=UTC),
    )

    assert decision.skip is True
    assert decision.latest_run_kst is not None
    assert decision.latest_run_kst.hour == 7
    assert decision.latest_run_kst.minute == 27


def test_manual_dispatch_never_skips_even_after_kst_cutoff() -> None:
    decision = decide_dashboard_freshness(
        _dashboard("2026-06-09T23:20:00+00:00", data_as_of="2026-06-09"),
        event_name="workflow_dispatch",
        now=datetime(2026, 6, 9, 23, 47, tzinfo=UTC),
    )

    assert decision.skip is False


def test_latest_degraded_automation_state_forces_watchdog_retry() -> None:
    decision = decide_dashboard_freshness(
        _dashboard_v5("2026-06-09T22:27:00Z", data_as_of="2026-06-09"),
        event_name="schedule",
        automation_status=_automation("degraded", "2026-06-09T23:00:00Z"),
        now=datetime(2026, 6, 9, 23, 47, tzinfo=UTC),
    )

    assert decision.skip is False
    assert decision.latest_automation_state == "degraded"
    assert decision.latest_automation_attempt_kst is not None
    assert "retry is required" in decision.reason


def test_failure_older_than_latest_success_does_not_trigger_duplicate_retry() -> None:
    decision = decide_dashboard_freshness(
        _dashboard_v5("2026-06-09T22:27:00Z", data_as_of="2026-06-09"),
        event_name="schedule",
        automation_status=_automation("degraded", "2026-06-09T20:00:00Z"),
        now=datetime(2026, 6, 9, 23, 47, tzinfo=UTC),
    )

    assert decision.skip is True


def test_bound_available_attempt_marks_cache_hit_as_successful_publication() -> None:
    dashboard = _dashboard_v5(
        "2026-06-09T18:00:00Z",
        data_as_of="2026-06-09",
    )

    decision = decide_dashboard_freshness(
        dashboard,
        event_name="schedule",
        automation_status=_automation(
            "available",
            "2026-06-09T22:32:00Z",
            dashboard=dashboard,
        ),
        now=datetime(2026, 6, 9, 23, 47, tzinfo=UTC),
    )

    assert decision.skip is True
    assert decision.latest_run_kst is not None
    assert decision.latest_run_kst < decision.cutoff_kst
    assert decision.latest_successful_publication_kst is not None
    assert (
        decision.latest_successful_publication_kst.isoformat()
        == "2026-06-10T07:32:00+09:00"
    )


def test_unbound_available_attempt_cannot_make_stale_dashboard_fresh() -> None:
    dashboard = _dashboard_v5(
        "2026-06-09T18:00:00Z",
        data_as_of="2026-06-09",
    )
    other_dashboard = _dashboard_v5(
        "2026-06-09T18:00:00Z",
        data_as_of="2026-06-09",
        result_key="b" * 64,
    )

    decision = decide_dashboard_freshness(
        dashboard,
        event_name="schedule",
        automation_status=_automation(
            "available",
            "2026-06-09T22:32:00Z",
            dashboard=other_dashboard,
        ),
        now=datetime(2026, 6, 9, 23, 47, tzinfo=UTC),
    )

    assert decision.skip is False
    assert decision.latest_successful_publication_kst == decision.latest_run_kst
    assert "predates" in decision.reason


def test_remote_dashboard_and_status_pair_avoids_last_good_race() -> None:
    remote_dashboard = _dashboard_v5(
        "2026-06-09T18:00:00Z",
        data_as_of="2026-06-09",
        result_key="b" * 64,
    )
    remote_status = _automation(
        "available",
        "2026-06-09T22:32:00Z",
        dashboard=remote_dashboard,
    )
    stale_local_status = _automation(
        "degraded",
        "2026-06-09T23:00:00Z",
        dashboard=_dashboard_v5(
            "2026-06-09T17:00:00Z",
            data_as_of="2026-06-09",
            result_key="a" * 64,
        ),
    )

    remote_pair = decide_dashboard_freshness(
        remote_dashboard,
        event_name="schedule",
        automation_status=remote_status,
        now=datetime(2026, 6, 9, 23, 47, tzinfo=UTC),
    )
    mixed_pair = decide_dashboard_freshness(
        remote_dashboard,
        event_name="schedule",
        automation_status=stale_local_status,
        now=datetime(2026, 6, 9, 23, 47, tzinfo=UTC),
    )

    assert remote_pair.skip is True
    assert mixed_pair.skip is False


def test_invalid_dashboard_payload_fails_open(tmp_path: Path) -> None:
    data_path = tmp_path / "dashboard.json"
    data_path.write_text("{not json", encoding="utf-8")

    decision = decide_dashboard_freshness(
        load_dashboard_payload(data_path),
        event_name="schedule",
        now=datetime(2026, 6, 9, 23, 47, tzinfo=UTC),
    )

    assert decision.skip is False
    assert decision.latest_run_kst is None


def test_invalid_latest_index_fails_open() -> None:
    decision = decide_dashboard_freshness(
        _dashboard("2026-06-09T23:20:00+00:00", data_as_of="2026-06-09", latest_run_index=99),
        event_name="schedule",
        now=datetime(2026, 6, 9, 23, 47, tzinfo=UTC),
    )

    assert decision.skip is False


def test_expected_recent_us_close_date_skips_weekends() -> None:
    assert (
        expected_recent_us_close_date(datetime(2026, 6, 15, 8, 30, tzinfo=UTC)).isoformat()
        == "2026-06-12"
    )


@pytest.mark.parametrize(
    ("now_utc", "expected"),
    [
        ("2026-09-17T19:59:59+00:00", "2026-09-16"),
        ("2026-09-17T20:00:00+00:00", "2026-09-17"),
        ("2026-03-06T20:59:59+00:00", "2026-03-05"),
        ("2026-03-06T21:00:00+00:00", "2026-03-06"),
        ("2026-03-09T19:59:59+00:00", "2026-03-06"),
        ("2026-03-09T20:00:00+00:00", "2026-03-09"),
        ("2026-11-02T20:59:59+00:00", "2026-10-30"),
        ("2026-11-02T21:00:00+00:00", "2026-11-02"),
        ("2026-11-27T17:59:59+00:00", "2026-11-25"),
        ("2026-11-27T18:00:00+00:00", "2026-11-27"),
        ("2026-12-24T17:59:59+00:00", "2026-12-23"),
        ("2026-12-24T18:00:00+00:00", "2026-12-24"),
        ("2026-01-01T23:00:00+00:00", "2025-12-31"),
        ("2026-04-03T23:00:00+00:00", "2026-04-02"),
        ("2026-06-19T23:00:00+00:00", "2026-06-18"),
        ("2026-07-03T23:00:00+00:00", "2026-07-02"),
        ("2026-09-07T23:00:00+00:00", "2026-09-04"),
        ("2025-01-09T23:00:00+00:00", "2025-01-08"),
        ("2012-10-30T23:00:00+00:00", "2012-10-26"),
    ],
)
def test_recent_completed_nyse_session_handles_close_boundaries_and_holidays(
    now_utc: str,
    expected: str,
) -> None:
    now = datetime.fromisoformat(now_utc)
    assert expected_recent_us_close_date(now).isoformat() == expected
    now_kst = now.astimezone(ZoneInfo("Asia/Seoul"))
    assert expected_recent_us_close_date(now_kst).isoformat() == expected


def test_holiday_watchdog_accepts_the_last_completed_market_session() -> None:
    decision = decide_dashboard_freshness(
        _dashboard_v5("2026-09-07T22:27:00Z", data_as_of="2026-09-04"),
        event_name="schedule",
        now=datetime(2026, 9, 7, 23, 47, tzinfo=UTC),
    )

    assert decision.target_data_as_of.isoformat() == "2026-09-04"
    assert decision.skip is True


def test_dashboard_freshness_cli_emits_github_outputs(tmp_path: Path, capsys) -> None:
    data_path = tmp_path / "dashboard.json"
    data_path.write_text(
        '{"schema_version":1,"latest_run_index":0,"runs":[{"summary":{"run_timestamp_utc":"2026-06-09T22:27:00Z","data_as_of":"2026-06-09"}}]}',
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--event-name",
            "schedule",
            "--data-path",
            str(data_path),
            "--status-path",
            str(tmp_path / "automation-status.json"),
            "--now-utc",
            "2026-06-09T23:47:00+00:00",
        ]
    )

    stdout = capsys.readouterr().out
    assert exit_code == 0
    assert "skip=true" in stdout
    assert "latest_run_kst=2026-06-10T07:27:00+09:00" in stdout
    assert "latest_data_as_of=2026-06-09" in stdout
    assert "latest_automation_state=none" in stdout
    assert "target_data_as_of=2026-06-09" in stdout


def test_dashboard_freshness_cli_retries_after_degraded_status_commit(
    tmp_path: Path,
    capsys,
) -> None:
    data_path = tmp_path / "dashboard.json"
    status_path = tmp_path / "automation-status.json"
    data_path.write_text(
        json.dumps(
            _dashboard_v5("2026-06-09T22:27:00Z", data_as_of="2026-06-09")
        ),
        encoding="utf-8",
    )
    status_path.write_text(
        json.dumps(_automation("degraded", "2026-06-09T23:00:00Z")),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--event-name",
            "schedule",
            "--data-path",
            str(data_path),
            "--status-path",
            str(status_path),
            "--now-utc",
            "2026-06-09T23:47:00+00:00",
        ]
    )

    stdout = capsys.readouterr().out
    assert exit_code == 0
    assert "skip=false" in stdout
    assert "latest_automation_state=degraded" in stdout
    assert "retry is required" in stdout
