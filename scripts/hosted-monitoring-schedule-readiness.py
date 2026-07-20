#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Mapping


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


EVIDENCE_SCHEMA_VERSION = "hosted-monitoring-schedule-readiness/v1"
COMPLETION_EVIDENCE_SCHEMA_VERSION = "local-source-completion-evidence/v1"
DEFAULT_REPOSITORY = "pcedison/taiwan-flood-risk-open-map"
DEFAULT_WORKFLOW_NAME = "Hosted Monitoring"
GH_RUN_LIST_MAX_ATTEMPTS = 4
GH_RUN_LIST_RETRY_SECONDS = 5
MONITORING_GATE_KEY = "production_monitoring_and_alerting"
SCHEDULED_FRESHNESS_REQUIREMENT = "scheduled_freshness_checks"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect GitHub Actions schedule-run metadata for the Hosted Monitoring "
            "workflow and emit public-safe schedule readiness evidence."
        )
    )
    parser.add_argument("--repo", default=DEFAULT_REPOSITORY)
    parser.add_argument("--workflow-name", default=DEFAULT_WORKFLOW_NAME)
    parser.add_argument(
        "--captured-at",
        help="ISO-8601 timestamp for this evidence. Defaults to current UTC.",
    )
    parser.add_argument(
        "--expected-head-sha",
        help="Expected main SHA for the latest schedule run.",
    )
    parser.add_argument(
        "--max-age-minutes",
        type=int,
        default=90,
        help="Maximum accepted age of the latest schedule run, based on updatedAt.",
    )
    parser.add_argument(
        "--runs-json",
        help=(
            "Optional JSON path with `gh run list --event schedule --json ...` output. "
            "When omitted, gh is executed."
        ),
    )
    parser.add_argument("--output", help="Optional JSON evidence output path.")
    parser.add_argument("--markdown-output", help="Optional Markdown output path.")
    parser.add_argument(
        "--completion-evidence-output",
        help=(
            "Optional completion overlay path. Written only when the schedule readiness "
            "status is passed."
        ),
    )
    parser.add_argument(
        "--fail-on-not-ready",
        action="store_true",
        help="Exit 1 when the latest schedule run is missing, failed, stale, or on the wrong SHA.",
    )
    args = parser.parse_args()

    captured_at = _parse_time(args.captured_at) if args.captured_at else _now()
    if args.runs_json:
        runs = _load_runs(Path(args.runs_json))
        source = {"mode": "provided_json", "event": "schedule"}
    else:
        runs = _gh_schedule_runs(repository=args.repo, workflow_name=args.workflow_name)
        source = {"mode": "gh_cli", "event": "schedule"}

    evidence = build_schedule_readiness(
        repository=args.repo,
        workflow_name=args.workflow_name,
        captured_at=captured_at,
        expected_head_sha=args.expected_head_sha,
        max_age_minutes=args.max_age_minutes,
        source=source,
        runs=runs,
    )
    content = _json(evidence)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
    else:
        print(content, end="")

    if args.markdown_output:
        markdown_path = Path(args.markdown_output)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_markdown(evidence), encoding="utf-8")

    if evidence["status"] == "passed" and args.completion_evidence_output:
        _write_json(
            Path(args.completion_evidence_output),
            build_completion_evidence_overlay(
                captured_at=evidence["captured_at"],
                evidence_ref=args.output or "<stdout>",
                observed_at=evidence["latest_schedule_run"]["updated_at"],
            ),
        )

    if evidence["status"] == "passed":
        print("HOSTED_MONITORING_SCHEDULE_READINESS passed", file=sys.stderr)
        return 0
    print(
        f"HOSTED_MONITORING_SCHEDULE_READINESS {evidence['status']}",
        file=sys.stderr,
    )
    return 1 if args.fail_on_not_ready else 0


def build_schedule_readiness(
    *,
    repository: str,
    workflow_name: str,
    captured_at: datetime,
    expected_head_sha: str | None,
    max_age_minutes: int,
    source: Mapping[str, str],
    runs: list[Mapping[str, Any]],
) -> dict[str, Any]:
    schedule_runs = [run for run in runs if str(run.get("event", "")) == "schedule"]
    latest = _latest_run(schedule_runs)
    failures: list[dict[str, str]] = []
    latest_run = _latest_run_item(latest) if latest else None
    age_minutes: int | None = None
    expected_head_sha_matched = False

    if latest is None:
        failures.append(
            {
                "code": "schedule_run_missing",
                "message": "No Hosted Monitoring schedule run was found.",
            }
        )
    else:
        updated_at = _parse_time(str(latest.get("updatedAt") or latest.get("createdAt")))
        age_minutes = int((captured_at - updated_at).total_seconds() // 60)
        expected_head_sha_matched = (
            not expected_head_sha or str(latest.get("headSha", "")) == expected_head_sha
        )
        status = str(latest.get("status", ""))
        conclusion = str(latest.get("conclusion") or "")
        if status != "completed":
            failures.append(
                {
                    "code": "latest_schedule_run_not_completed",
                    "message": "Latest Hosted Monitoring schedule run has not completed yet.",
                }
            )
        if status == "completed" and conclusion != "success":
            failures.append(
                {
                    "code": "latest_schedule_run_failed",
                    "message": "Latest Hosted Monitoring schedule run did not conclude successfully.",
                }
            )
        if expected_head_sha and not expected_head_sha_matched:
            failures.append(
                {
                    "code": "latest_schedule_run_wrong_head_sha",
                    "message": "Latest Hosted Monitoring schedule run did not execute on the expected main SHA.",
                }
            )
        if age_minutes > max_age_minutes:
            failures.append(
                {
                    "code": "latest_schedule_run_stale",
                    "message": "Latest Hosted Monitoring schedule run is older than the accepted freshness window.",
                }
            )

    status = _readiness_status(failures)
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "captured_at": _format_time(captured_at),
        "repository": repository,
        "workflow_name": workflow_name,
        "source": dict(source),
        "status": status,
        "expected_head_sha": expected_head_sha,
        "latest_schedule_run": latest_run,
        "summary": {
            "schedule_run_found": latest is not None,
            "latest_schedule_run_status": latest_run["status"] if latest_run else None,
            "latest_schedule_run_conclusion": (
                latest_run["conclusion"] if latest_run else None
            ),
            "expected_head_sha_matched": expected_head_sha_matched,
            "age_minutes": age_minutes,
            "max_age_minutes": max_age_minutes,
            "completion_evidence_ready": status == "passed",
            "failure_count": len(failures),
        },
        "completion_evidence_targets": (
            _completion_evidence_targets(observed_at=latest_run["updated_at"])
            if status == "passed" and latest_run
            else []
        ),
        "failures": failures,
        "notes": [
            "This artifact uses only GitHub Actions run metadata.",
            "It does not read GitHub secrets or private monitoring manifests.",
            "A passed status can supply only the scheduled_freshness_checks requirement; alert routing and worker/scheduler ownership still require private monitoring evidence.",
        ],
    }


def render_markdown(evidence: Mapping[str, Any]) -> str:
    summary = evidence["summary"]
    lines = [
        "# Hosted Monitoring Schedule Readiness",
        "",
        f"- repository: `{evidence['repository']}`",
        f"- workflow: `{evidence['workflow_name']}`",
        f"- captured_at: `{evidence['captured_at']}`",
        f"- status: `{evidence['status']}`",
        f"- expected_head_sha: `{evidence.get('expected_head_sha') or ''}`",
        f"- latest schedule run found: `{summary['schedule_run_found']}`",
        f"- latest conclusion: `{summary['latest_schedule_run_conclusion'] or ''}`",
        f"- age_minutes: `{summary['age_minutes']}` / max `{summary['max_age_minutes']}`",
        f"- completion evidence ready: `{summary['completion_evidence_ready']}`",
        "",
    ]
    latest = evidence.get("latest_schedule_run")
    if latest:
        lines.extend(
            [
                "## Latest Schedule Run",
                "",
                f"- run: [{latest['database_id']}]({latest['url']})",
                f"- head_sha: `{latest['head_sha']}`",
                f"- status: `{latest['status']}`",
                f"- conclusion: `{latest['conclusion']}`",
                f"- updated_at: `{latest['updated_at']}`",
                "",
            ]
        )
    lines.extend(["## Failures", ""])
    if evidence["failures"]:
        for failure in evidence["failures"]:
            lines.append(f"- `{failure['code']}`: {failure['message']}")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "This report can only cover `scheduled_freshness_checks`. It does not satisfy hosted alert routing or worker/scheduler ownership.",
            "",
        ]
    )
    return "\n".join(lines)


def build_completion_evidence_overlay(
    *,
    captured_at: str,
    evidence_ref: str,
    observed_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": COMPLETION_EVIDENCE_SCHEMA_VERSION,
        "captured_at": captured_at,
        "signal_family_gap_evidence": [],
        "source_contract_evidence": [],
        "production_gate_evidence": [
            {
                "gate_key": MONITORING_GATE_KEY,
                "status": "accepted",
                "evidence_ref": evidence_ref,
                "satisfied_requirements": [SCHEDULED_FRESHNESS_REQUIREMENT],
                "requirement_evidence": [
                    {
                        "requirement": SCHEDULED_FRESHNESS_REQUIREMENT,
                        "evidence_ref": f"{evidence_ref}#/latest_schedule_run",
                        "observed_at": observed_at,
                    }
                ],
            }
        ],
    }


def _completion_evidence_targets(*, observed_at: str) -> list[dict[str, Any]]:
    return [
        {
            "gate_key": MONITORING_GATE_KEY,
            "status": "accepted",
            "satisfied_requirements": [SCHEDULED_FRESHNESS_REQUIREMENT],
            "requirement_evidence": [
                {
                    "requirement": SCHEDULED_FRESHNESS_REQUIREMENT,
                    "evidence_ref": "<evidence-output>#/latest_schedule_run",
                    "observed_at": observed_at,
                }
            ],
        }
    ]


def _latest_run(runs: list[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    if not runs:
        return None
    return max(runs, key=lambda run: _parse_time(str(run.get("createdAt"))))


def _latest_run_item(run: Mapping[str, Any]) -> dict[str, str | None]:
    return {
        "database_id": str(run.get("databaseId", "")),
        "status": str(run.get("status", "")),
        "conclusion": str(run.get("conclusion") or ""),
        "event": str(run.get("event", "")),
        "head_sha": str(run.get("headSha", "")),
        "created_at": str(run.get("createdAt", "")),
        "updated_at": str(run.get("updatedAt") or run.get("createdAt", "")),
        "url": str(run.get("url", "")),
        "workflow_name": str(run.get("workflowName", "")),
    }


def _readiness_status(failures: list[Mapping[str, str]]) -> str:
    if not failures:
        return "passed"
    codes = [failure["code"] for failure in failures]
    if "schedule_run_missing" in codes:
        return "missing"
    if "latest_schedule_run_not_completed" in codes:
        return "running"
    if "latest_schedule_run_failed" in codes:
        return "failed"
    if "latest_schedule_run_wrong_head_sha" in codes:
        return "wrong_sha"
    if "latest_schedule_run_stale" in codes:
        return "stale"
    return "failed"


def _load_runs(path: Path) -> list[Mapping[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit(f"Expected a JSON list in {path}")
    return [row for row in payload if isinstance(row, Mapping)]


def _gh_schedule_runs(*, repository: str, workflow_name: str) -> list[Mapping[str, Any]]:
    command = [
        "gh",
        "run",
        "list",
        "--repo",
        repository,
        "--workflow",
        workflow_name,
        "--event",
        "schedule",
        "--limit",
        "20",
        "--json",
        "databaseId,status,conclusion,event,headSha,createdAt,updatedAt,url,workflowName",
    ]
    for attempt in range(1, GH_RUN_LIST_MAX_ATTEMPTS + 1):
        result = subprocess.run(
            command,
            capture_output=True,
            encoding="utf-8",
            text=True,
            check=False,
        )
        if result.returncode == 0:
            break
        error = result.stderr.strip() or "gh run list failed"
        if attempt == GH_RUN_LIST_MAX_ATTEMPTS or not _is_retryable_gh_error(error):
            raise SystemExit(error)
        delay = GH_RUN_LIST_RETRY_SECONDS * attempt
        print(
            f"gh run list transient failure (attempt {attempt}/"
            f"{GH_RUN_LIST_MAX_ATTEMPTS}); retrying in {delay}s: {error}",
            file=sys.stderr,
        )
        time.sleep(delay)
    payload = json.loads(result.stdout or "[]")
    if not isinstance(payload, list):
        raise SystemExit("gh run list returned non-list JSON")
    return [row for row in payload if isinstance(row, Mapping)]


def _is_retryable_gh_error(error: str) -> bool:
    normalized = error.lower()
    return any(
        marker in normalized
        for marker in (
            "http 429",
            "http 500",
            "http 502",
            "http 503",
            "http 504",
            "timed out",
            "timeout",
            "connection reset",
            "temporary failure",
        )
    )


def _parse_time(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _format_time(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json(payload), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
