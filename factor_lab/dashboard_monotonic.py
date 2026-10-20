from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DashboardSnapshot:
    path: str
    result_key: str | None
    data_as_of: date | None
    run_timestamp: datetime | None
    generated_at_utc: datetime | None
    latest_output_rows: int
    selected_factor_snapshot_rows: int
    primary_entities: int
    expected_factors: int
    evaluated_factors: int


@dataclass(frozen=True)
class MonotonicDashboardDecision:
    passed: bool
    baseline: DashboardSnapshot
    candidate: DashboardSnapshot
    reason: str

    def as_github_outputs(self) -> dict[str, str]:
        return {
            "passed": "true" if self.passed else "false",
            "reason": self.reason,
            "baseline_data_as_of": self.baseline.data_as_of.isoformat()
            if self.baseline.data_as_of
            else "none",
            "candidate_data_as_of": self.candidate.data_as_of.isoformat()
            if self.candidate.data_as_of
            else "none",
            "baseline_run_timestamp": self.baseline.run_timestamp.isoformat()
            if self.baseline.run_timestamp
            else "none",
            "candidate_run_timestamp": self.candidate.run_timestamp.isoformat()
            if self.candidate.run_timestamp
            else "none",
            "baseline_latest_output_rows": str(self.baseline.latest_output_rows),
            "candidate_latest_output_rows": str(self.candidate.latest_output_rows),
            "baseline_selected_factor_snapshot_rows": str(
                self.baseline.selected_factor_snapshot_rows
            ),
            "candidate_selected_factor_snapshot_rows": str(
                self.candidate.selected_factor_snapshot_rows
            ),
            "baseline_result_key": self.baseline.result_key or "none",
            "candidate_result_key": self.candidate.result_key or "none",
        }


def load_dashboard_snapshot(path: str | Path) -> DashboardSnapshot:
    payload = _load_json(path)
    if payload.get("schemaVersion") == 5:
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        model = (
            payload.get("bestFactorPortfolio")
            if isinstance(payload.get("bestFactorPortfolio"), dict)
            else {}
        )
        portfolios = (
            payload.get("factorPortfolios")
            if isinstance(payload.get("factorPortfolios"), dict)
            else {}
        )
        selected = str(payload.get("bestFactor") or "")
        selected_portfolio = (
            portfolios.get(selected) if isinstance(portfolios.get(selected), dict) else {}
        )
        generated = _parse_datetime(payload.get("generatedAtUtc"))
        identity = (
            payload.get("resultIdentity") if isinstance(payload.get("resultIdentity"), dict) else {}
        )
        accounting = (
            payload.get("factorAccounting")
            if isinstance(payload.get("factorAccounting"), dict)
            else {}
        )
        return DashboardSnapshot(
            path=str(path),
            result_key=str(identity.get("resultKey") or payload.get("resultKey") or "") or None,
            data_as_of=_parse_date(data.get("asOf")),
            run_timestamp=generated,
            generated_at_utc=generated,
            latest_output_rows=_count_rows(model.get("weights")),
            selected_factor_snapshot_rows=_count_rows(selected_portfolio.get("weights")),
            primary_entities=int(data.get("analyzedSecurityCount") or 0),
            expected_factors=int(accounting.get("expectedIndependentFactorCount") or 0),
            evaluated_factors=int(accounting.get("evaluatedIndependentFactorCount") or 0),
        )
    latest = _latest_run(payload)
    summary = latest.get("summary", {}) if isinstance(latest.get("summary"), dict) else {}
    selected_factor = summary.get("selected_factor")
    return DashboardSnapshot(
        path=str(path),
        result_key=None,
        data_as_of=_parse_date(summary.get("data_as_of") or latest.get("data_as_of")),
        run_timestamp=_parse_datetime(
            summary.get("run_timestamp_utc") or latest.get("generated_at_utc")
        ),
        generated_at_utc=_parse_datetime(payload.get("generated_at_utc")),
        latest_output_rows=_count_rows(latest.get("latest_output_rows")),
        selected_factor_snapshot_rows=_selected_factor_snapshot_rows(latest, selected_factor),
        primary_entities=_count_rows(_public_summary(payload).get("primaryEntities")),
        expected_factors=0,
        evaluated_factors=0,
    )


def decide_monotonic_dashboard(
    baseline: DashboardSnapshot,
    candidate: DashboardSnapshot,
    *,
    min_latest_output_rows: int = 10,
    min_selected_factor_snapshot_rows: int = 10,
    min_retention_ratio: float = 0.5,
) -> MonotonicDashboardDecision:
    if baseline.result_key and not candidate.result_key:
        return MonotonicDashboardDecision(
            passed=False,
            baseline=baseline,
            candidate=candidate,
            reason="candidate dashboard is missing result identity while remote baseline has one",
        )
    if (
        candidate.expected_factors < 1 or candidate.evaluated_factors != candidate.expected_factors
    ) and candidate.result_key:
        return MonotonicDashboardDecision(
            passed=False,
            baseline=baseline,
            candidate=candidate,
            reason="candidate factor accounting is incomplete",
        )
    if baseline.data_as_of and candidate.data_as_of and candidate.data_as_of < baseline.data_as_of:
        return MonotonicDashboardDecision(
            passed=False,
            baseline=baseline,
            candidate=candidate,
            reason="candidate dashboard data_as_of is older than remote baseline",
        )
    if (
        baseline.run_timestamp
        and candidate.run_timestamp
        and candidate.run_timestamp < baseline.run_timestamp
    ):
        return MonotonicDashboardDecision(
            passed=False,
            baseline=baseline,
            candidate=candidate,
            reason="candidate dashboard run_timestamp is older than remote baseline",
        )
    if baseline.data_as_of and not candidate.data_as_of:
        return MonotonicDashboardDecision(
            passed=False,
            baseline=baseline,
            candidate=candidate,
            reason="candidate dashboard is missing data_as_of while remote baseline has one",
        )
    if baseline.run_timestamp and not candidate.run_timestamp:
        return MonotonicDashboardDecision(
            passed=False,
            baseline=baseline,
            candidate=candidate,
            reason="candidate dashboard is missing run_timestamp while remote baseline has one",
        )

    if candidate.latest_output_rows < min_latest_output_rows:
        return MonotonicDashboardDecision(
            passed=False,
            baseline=baseline,
            candidate=candidate,
            reason=f"candidate latest_output_rows collapsed below minimum publication floor ({candidate.latest_output_rows} < {min_latest_output_rows})",
        )
    if candidate.selected_factor_snapshot_rows < min_selected_factor_snapshot_rows:
        return MonotonicDashboardDecision(
            passed=False,
            baseline=baseline,
            candidate=candidate,
            reason=(
                "candidate selected-factor score snapshot rows collapsed below minimum publication floor "
                f"({candidate.selected_factor_snapshot_rows} < {min_selected_factor_snapshot_rows})"
            ),
        )
    if baseline.latest_output_rows and candidate.latest_output_rows < int(
        baseline.latest_output_rows * min_retention_ratio
    ):
        return MonotonicDashboardDecision(
            passed=False,
            baseline=baseline,
            candidate=candidate,
            reason=(
                "candidate latest_output_rows retained too little of the remote baseline "
                f"({candidate.latest_output_rows}/{baseline.latest_output_rows})"
            ),
        )
    if baseline.selected_factor_snapshot_rows and candidate.selected_factor_snapshot_rows < int(
        baseline.selected_factor_snapshot_rows * min_retention_ratio
    ):
        return MonotonicDashboardDecision(
            passed=False,
            baseline=baseline,
            candidate=candidate,
            reason=(
                "candidate selected-factor score snapshot retained too little of the remote baseline "
                f"({candidate.selected_factor_snapshot_rows}/{baseline.selected_factor_snapshot_rows})"
            ),
        )
    return MonotonicDashboardDecision(
        passed=True,
        baseline=baseline,
        candidate=candidate,
        reason="candidate dashboard is not older than remote baseline",
    )


def _load_json(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _latest_run(payload: dict[str, Any]) -> dict[str, Any]:
    runs = payload.get("runs")
    if isinstance(runs, list) and runs:
        latest_index = payload.get("latest_run_index", len(runs) - 1)
        try:
            latest = runs[int(latest_index)]
        except (IndexError, TypeError, ValueError):
            latest = runs[-1]
        return latest if isinstance(latest, dict) else {}
    return payload


def _public_summary(payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload.get("public_summary")
    if isinstance(summary, dict):
        return summary
    summary = payload.get("summary")
    if isinstance(summary, dict) and summary.get("contract") == "quant-research-summary":
        return summary
    return {}


def _count_rows(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _selected_factor_snapshot_rows(latest: dict[str, Any], selected_factor: Any) -> int:
    snapshots = latest.get("factor_score_snapshots")
    if not isinstance(snapshots, list):
        return 0
    selected = str(selected_factor or "")
    candidates: list[tuple[date | None, int]] = []
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        if selected and str(snapshot.get("factor") or "") != selected:
            continue
        row_count = _count_rows(snapshot.get("rows"))
        candidates.append(
            (_parse_date(snapshot.get("date") or snapshot.get("score_date")), row_count)
        )
    if not candidates:
        return 0
    candidates.sort(key=lambda item: item[0] or date.min)
    return candidates[-1][1]


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prevent generated dashboard data from moving backwards."
    )
    parser.add_argument("--baseline", required=True, help="Remote/current dashboard JSON baseline")
    parser.add_argument("--candidate", required=True, help="Generated dashboard JSON candidate")
    parser.add_argument("--min-latest-output-rows", type=int, default=10)
    parser.add_argument("--min-selected-factor-snapshot-rows", type=int, default=10)
    parser.add_argument("--min-retention-ratio", type=float, default=0.5)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    decision = decide_monotonic_dashboard(
        load_dashboard_snapshot(args.baseline),
        load_dashboard_snapshot(args.candidate),
        min_latest_output_rows=args.min_latest_output_rows,
        min_selected_factor_snapshot_rows=args.min_selected_factor_snapshot_rows,
        min_retention_ratio=args.min_retention_ratio,
    )
    for key, value in decision.as_github_outputs().items():
        print(f"{key}={value}")
    return 0 if decision.passed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
