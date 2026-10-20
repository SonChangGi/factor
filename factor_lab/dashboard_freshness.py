from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import exchange_calendars as xcals

KST = ZoneInfo("Asia/Seoul")
DEFAULT_CUTOFF_HOUR_KST = 7
DEFAULT_CUTOFF_MINUTE_KST = 17
AUTOMATION_STATUS_CONTRACT = "momentum-dashboard-automation-status"
AUTOMATION_STATUS_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class DashboardFreshnessDecision:
    """Decision used by scheduled GitHub Actions fallback runs."""

    skip: bool
    event_name: str
    latest_run_kst: datetime | None
    latest_data_as_of: date | None
    latest_automation_state: str | None
    latest_automation_attempt_kst: datetime | None
    latest_successful_publication_kst: datetime | None
    target_data_as_of: date
    cutoff_kst: datetime
    reason: str

    def as_github_outputs(self) -> dict[str, str]:
        return {
            "skip": "true" if self.skip else "false",
            "event_name": self.event_name,
            "latest_run_kst": self.latest_run_kst.isoformat() if self.latest_run_kst else "none",
            "latest_data_as_of": self.latest_data_as_of.isoformat()
            if self.latest_data_as_of
            else "none",
            "latest_automation_state": self.latest_automation_state or "none",
            "latest_automation_attempt_kst": (
                self.latest_automation_attempt_kst.isoformat()
                if self.latest_automation_attempt_kst
                else "none"
            ),
            "latest_successful_publication_kst": (
                self.latest_successful_publication_kst.isoformat()
                if self.latest_successful_publication_kst
                else "none"
            ),
            "target_data_as_of": self.target_data_as_of.isoformat(),
            "cutoff_kst": self.cutoff_kst.isoformat(),
            "reason": self.reason,
        }


def decide_dashboard_freshness(
    dashboard: dict[str, Any],
    *,
    event_name: str,
    automation_status: dict[str, Any] | None = None,
    now: datetime | None = None,
    cutoff_hour_kst: int = DEFAULT_CUTOFF_HOUR_KST,
    cutoff_minute_kst: int = DEFAULT_CUTOFF_MINUTE_KST,
) -> DashboardFreshnessDecision:
    """Skip duplicate schedules only after a fresh, successful publication."""

    now_kst = _to_kst(now) if now else datetime.now(KST)
    cutoff_kst = datetime.combine(
        now_kst.date(), time(hour=cutoff_hour_kst, minute=cutoff_minute_kst), tzinfo=KST
    )
    latest_run_kst = latest_dashboard_run_kst(dashboard)
    latest_data_as_of = latest_dashboard_data_as_of(dashboard)
    normalized_automation_status = automation_status or {}
    latest_automation_state = _automation_state(normalized_automation_status)
    latest_automation_attempt_kst = _parse_timestamp_to_kst(
        normalized_automation_status.get("attemptedAtUtc")
    )
    latest_successful_publication_kst = latest_run_kst
    if (
        latest_automation_attempt_kst is not None
        and _available_status_matches_dashboard(
            normalized_automation_status,
            dashboard,
        )
        and (
            latest_successful_publication_kst is None
            or latest_automation_attempt_kst > latest_successful_publication_kst
        )
    ):
        # An analysis cache hit republishes the validated aliases without
        # changing the immutable payload's generatedAtUtc. The bound status
        # attempt is therefore the authoritative successful publication time.
        latest_successful_publication_kst = latest_automation_attempt_kst
    target_data_as_of = expected_recent_us_close_date(now_kst)
    latest_failure_is_actionable = latest_automation_state in {
        "degraded",
        "unavailable",
        "failed",
    } and (
        latest_automation_attempt_kst is None
        or latest_run_kst is None
        or latest_automation_attempt_kst >= latest_run_kst
    )
    if event_name != "schedule":
        skip = False
        reason = "manual dashboard execution required"
    elif latest_failure_is_actionable:
        skip = False
        reason = (
            "latest scheduled automation state is "
            f"{latest_automation_state}; retry is required"
        )
    elif latest_data_as_of is None:
        skip = False
        reason = "published dashboard has no valid market-data date"
    elif latest_data_as_of < target_data_as_of:
        skip = False
        reason = (
            f"published market-data date {latest_data_as_of.isoformat()} is older than "
            f"target {target_data_as_of.isoformat()}"
        )
    elif latest_successful_publication_kst is None:
        skip = False
        reason = "published dashboard has no valid generation timestamp"
    elif latest_successful_publication_kst < cutoff_kst:
        skip = False
        reason = "latest successful publication predates the daily KST cutoff"
    else:
        skip = True
        reason = "dashboard already has a fresh successful publication for the target close"
    return DashboardFreshnessDecision(
        skip=skip,
        event_name=event_name,
        latest_run_kst=latest_run_kst,
        latest_data_as_of=latest_data_as_of,
        latest_automation_state=latest_automation_state,
        latest_automation_attempt_kst=latest_automation_attempt_kst,
        latest_successful_publication_kst=latest_successful_publication_kst,
        target_data_as_of=target_data_as_of,
        cutoff_kst=cutoff_kst,
        reason=reason,
    )


def latest_dashboard_data_as_of(dashboard: dict[str, Any]) -> date | None:
    """Extract the actual market-data date from schema-v5 or legacy payloads."""

    if dashboard.get("schemaVersion") == 5:
        data = dashboard.get("data")
        return _parse_date(data.get("asOf")) if isinstance(data, dict) else None

    latest = _latest_dashboard_run(dashboard)
    if latest is None:
        return None
    summary = latest.get("summary", {})
    if not isinstance(summary, dict):
        summary = {}
    return _parse_date(summary.get("data_as_of") or latest.get("data_as_of"))


def expected_recent_us_close_date(now_kst: datetime) -> date:
    """Return the latest NYSE session whose regular close has completed."""

    now_utc = _to_kst(now_kst).astimezone(UTC)
    # Explicit year bounds also cover the preceding session on New Year's Day
    # and avoid depending on the library's default calendar construction range.
    schedule = xcals.get_calendar(
        "XNYS", start=f"{now_utc.year - 1}-01-01", end=f"{now_utc.year}-12-31"
    ).schedule
    # previous_close excludes an exact close timestamp; publication permits it.
    completed = schedule.index[schedule["close"] <= now_utc]
    if completed.empty:
        raise ValueError(f"NYSE calendar has no completed session before {now_utc.isoformat()}")
    return completed[-1].date()


def _latest_dashboard_run(dashboard: dict[str, Any]) -> dict[str, Any] | None:
    runs = dashboard.get("runs")
    if not isinstance(runs, list) or not runs:
        return None
    latest_index = dashboard.get("latest_run_index", len(runs) - 1)
    try:
        latest = runs[int(latest_index)]
    except (IndexError, TypeError, ValueError):
        return None
    return latest if isinstance(latest, dict) else None


def latest_dashboard_run_kst(dashboard: dict[str, Any]) -> datetime | None:
    """Extract the generation timestamp from schema-v5 or legacy payloads."""

    if dashboard.get("schemaVersion") == 5:
        return _parse_timestamp_to_kst(dashboard.get("generatedAtUtc"))

    latest = _latest_dashboard_run(dashboard)
    if latest is None:
        return None
    summary = latest.get("summary", {})
    if not isinstance(summary, dict):
        summary = {}
    raw_timestamp = summary.get("run_timestamp_utc") or latest.get("generated_at_utc")
    return _parse_timestamp_to_kst(raw_timestamp)


def load_dashboard_payload(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _automation_state(payload: dict[str, Any]) -> str | None:
    value = payload.get("state")
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized or None


def _available_status_matches_dashboard(
    status: dict[str, Any],
    dashboard: dict[str, Any],
) -> bool:
    """Accept a success timestamp only when it is bound to this dashboard."""

    if (
        status.get("contract") != AUTOMATION_STATUS_CONTRACT
        or status.get("schemaVersion") != AUTOMATION_STATUS_SCHEMA_VERSION
        or _automation_state(status) != "available"
    ):
        return False
    publication = status.get("publication")
    last_good = status.get("lastGood")
    data = dashboard.get("data")
    if (
        not isinstance(publication, dict)
        or publication.get("updated") is not True
        or not isinstance(last_good, dict)
        or not isinstance(data, dict)
    ):
        return False
    expected = {
        "resultKey": dashboard.get("resultKey"),
        "dataAsOf": data.get("asOf"),
        "generatedAtUtc": dashboard.get("generatedAtUtc"),
        "path": "data/dashboard.json",
    }
    if not all(isinstance(value, str) and value for value in expected.values()):
        return False
    return (
        status.get("targetDataAsOf") == expected["dataAsOf"]
        and all(last_good.get(key) == value for key, value in expected.items())
    )


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _parse_timestamp_to_kst(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return _to_kst(parsed)


def _to_kst(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(KST)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Decide whether a scheduled dashboard fallback should run."
    )
    parser.add_argument(
        "--event-name", required=True, help="GitHub event name, e.g. schedule or workflow_dispatch"
    )
    parser.add_argument(
        "--data-path", default="docs/data/dashboard.json", help="Dashboard JSON path to inspect"
    )
    parser.add_argument(
        "--status-path",
        default="docs/data/automation-status.json",
        help="Latest scheduled automation status JSON path to inspect",
    )
    parser.add_argument(
        "--now-utc", default=None, help="Optional ISO timestamp for deterministic tests"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    now = _parse_timestamp_to_kst(args.now_utc) if args.now_utc else None
    decision = decide_dashboard_freshness(
        load_dashboard_payload(args.data_path),
        event_name=args.event_name,
        automation_status=load_dashboard_payload(args.status_path),
        now=now,
    )
    for key, value in decision.as_github_outputs().items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
