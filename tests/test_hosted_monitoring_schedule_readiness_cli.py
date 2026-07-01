from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "hosted-monitoring-schedule-readiness.py"
AUDIT_SCRIPT = REPO_ROOT / "scripts" / "local-source-completion-audit.py"


def test_hosted_monitoring_schedule_readiness_accepts_recent_successful_schedule(
    tmp_path: Path,
) -> None:
    runs_json = tmp_path / "runs.json"
    evidence_output = tmp_path / "hosted-monitoring-schedule-readiness.json"
    completion_output = tmp_path / "hosted-monitoring-schedule-completion-evidence.json"
    runs_json.write_text(
        json.dumps(
            [
                {
                    "databaseId": 28499999999,
                    "status": "completed",
                    "conclusion": "success",
                    "event": "schedule",
                    "headSha": "2d86ca32718ae4ef65a8e30c59c84028b0000a1b",
                    "createdAt": "2026-07-01T06:30:00Z",
                    "updatedAt": "2026-07-01T06:30:44Z",
                    "url": "https://github.com/pcedison/taiwan-flood-risk-open-map/actions/runs/28499999999",
                    "workflowName": "Hosted Monitoring",
                }
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo",
            "pcedison/taiwan-flood-risk-open-map",
            "--workflow-name",
            "Hosted Monitoring",
            "--captured-at",
            "2026-07-01T06:45:00Z",
            "--expected-head-sha",
            "2d86ca32718ae4ef65a8e30c59c84028b0000a1b",
            "--max-age-minutes",
            "60",
            "--runs-json",
            str(runs_json),
            "--output",
            str(evidence_output),
            "--completion-evidence-output",
            str(completion_output),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads(evidence_output.read_text(encoding="utf-8"))
    assert evidence["schema_version"] == "hosted-monitoring-schedule-readiness/v1"
    assert evidence["status"] == "passed"
    assert evidence["summary"] == {
        "schedule_run_found": True,
        "latest_schedule_run_status": "completed",
        "latest_schedule_run_conclusion": "success",
        "expected_head_sha_matched": True,
        "age_minutes": 14,
        "max_age_minutes": 60,
        "completion_evidence_ready": True,
        "failure_count": 0,
    }
    assert evidence["latest_schedule_run"]["database_id"] == "28499999999"
    assert evidence["completion_evidence_targets"] == [
        {
            "gate_key": "production_monitoring_and_alerting",
            "status": "accepted",
            "satisfied_requirements": ["scheduled_freshness_checks"],
            "requirement_evidence": [
                {
                    "requirement": "scheduled_freshness_checks",
                    "evidence_ref": "<evidence-output>#/latest_schedule_run",
                    "observed_at": "2026-07-01T06:30:44Z",
                }
            ],
        }
    ]

    completion = json.loads(completion_output.read_text(encoding="utf-8"))
    assert completion["production_gate_evidence"] == [
        {
            "gate_key": "production_monitoring_and_alerting",
            "status": "accepted",
            "evidence_ref": str(evidence_output),
            "satisfied_requirements": ["scheduled_freshness_checks"],
            "requirement_evidence": [
                {
                    "requirement": "scheduled_freshness_checks",
                    "evidence_ref": f"{evidence_output}#/latest_schedule_run",
                    "observed_at": "2026-07-01T06:30:44Z",
                }
            ],
        }
    ]

    audit = subprocess.run(
        [
            sys.executable,
            str(AUDIT_SCRIPT),
            "--completion-evidence-json",
            str(completion_output),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        text=True,
        check=False,
    )
    assert audit.returncode == 0, audit.stderr
    gates = {gate["gate_key"]: gate for gate in json.loads(audit.stdout)["gates"]}
    assert gates["production_monitoring_and_alerting"]["blocking_items"] == [
        "hosted_alert_routing",
        "worker_scheduler_alert_ownership",
    ]


def test_hosted_monitoring_schedule_readiness_rejects_failed_wrong_sha_schedule(
    tmp_path: Path,
) -> None:
    runs_json = tmp_path / "runs.json"
    evidence_output = tmp_path / "hosted-monitoring-schedule-readiness.json"
    markdown_output = tmp_path / "hosted-monitoring-schedule-readiness.md"
    completion_output = tmp_path / "hosted-monitoring-schedule-completion-evidence.json"
    runs_json.write_text(
        json.dumps(
            [
                {
                    "databaseId": 28493475510,
                    "status": "completed",
                    "conclusion": "failure",
                    "event": "schedule",
                    "headSha": "9d671d2a4a63ec30ff8a79204b7346304404f15f",
                    "createdAt": "2026-07-01T04:26:34Z",
                    "updatedAt": "2026-07-01T04:26:42Z",
                    "url": "https://github.com/pcedison/taiwan-flood-risk-open-map/actions/runs/28493475510",
                    "workflowName": "Hosted Monitoring",
                }
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo",
            "pcedison/taiwan-flood-risk-open-map",
            "--workflow-name",
            "Hosted Monitoring",
            "--captured-at",
            "2026-07-01T06:45:00Z",
            "--expected-head-sha",
            "2d86ca32718ae4ef65a8e30c59c84028b0000a1b",
            "--max-age-minutes",
            "60",
            "--runs-json",
            str(runs_json),
            "--output",
            str(evidence_output),
            "--markdown-output",
            str(markdown_output),
            "--completion-evidence-output",
            str(completion_output),
            "--fail-on-not-ready",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        text=True,
        check=False,
    )

    assert result.returncode == 1
    evidence = json.loads(evidence_output.read_text(encoding="utf-8"))
    assert evidence["status"] == "failed"
    assert evidence["summary"] == {
        "schedule_run_found": True,
        "latest_schedule_run_status": "completed",
        "latest_schedule_run_conclusion": "failure",
        "expected_head_sha_matched": False,
        "age_minutes": 138,
        "max_age_minutes": 60,
        "completion_evidence_ready": False,
        "failure_count": 3,
    }
    assert evidence["completion_evidence_targets"] == []
    assert evidence["failures"] == [
        {
            "code": "latest_schedule_run_failed",
            "message": "Latest Hosted Monitoring schedule run did not conclude successfully.",
        },
        {
            "code": "latest_schedule_run_wrong_head_sha",
            "message": "Latest Hosted Monitoring schedule run did not execute on the expected main SHA.",
        },
        {
            "code": "latest_schedule_run_stale",
            "message": "Latest Hosted Monitoring schedule run is older than the accepted freshness window.",
        },
    ]
    assert not completion_output.exists()

    markdown = markdown_output.read_text(encoding="utf-8")
    assert "# Hosted Monitoring Schedule Readiness" in markdown
    assert "status: `failed`" in markdown
    assert "`latest_schedule_run_failed`" in markdown
