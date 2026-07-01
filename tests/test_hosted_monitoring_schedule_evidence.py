from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "hosted_monitoring_schedule_evidence.py"
AUDIT_SCRIPT = REPO_ROOT / "scripts" / "local-source-completion-audit.py"


def test_hosted_monitoring_schedule_evidence_writes_partial_completion_overlay(
    tmp_path: Path,
) -> None:
    evidence_output = tmp_path / "hosted-monitoring-schedule-evidence.json"
    completion_output = tmp_path / "hosted-monitoring-schedule-completion-evidence.json"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--event-name",
            "schedule",
            "--workflow-name",
            "Hosted Monitoring",
            "--run-id",
            "28493575175",
            "--run-url",
            "https://github.com/pcedison/taiwan-flood-risk-open-map/actions/runs/28493575175",
            "--cron",
            "*/30 * * * *",
            "--captured-at",
            "2026-07-01T05:30:00Z",
            "--evidence-output",
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
    assert evidence == {
        "schema_version": "hosted-monitoring-schedule-evidence/v1",
        "captured_at": "2026-07-01T05:30:00Z",
        "status": "passed",
        "schedule_evidence": {
            "event_name": "schedule",
            "workflow_name": "Hosted Monitoring",
            "run_id": "28493575175",
            "run_url": (
                "https://github.com/pcedison/taiwan-flood-risk-open-map/actions/runs/28493575175"
            ),
            "cron": "*/30 * * * *",
            "observed_at": "2026-07-01T05:30:00Z",
        },
        "completion_evidence_targets": [
            {
                "gate_key": "production_monitoring_and_alerting",
                "status": "accepted",
                "satisfied_requirements": ["scheduled_freshness_checks"],
                "requirement_evidence": [
                    {
                        "requirement": "scheduled_freshness_checks",
                        "evidence_ref": "<evidence-output>#/schedule_evidence",
                        "observed_at": "2026-07-01T05:30:00Z",
                    }
                ],
            }
        ],
        "failures": [],
    }

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
                    "evidence_ref": f"{evidence_output}#/schedule_evidence",
                    "observed_at": "2026-07-01T05:30:00Z",
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


def test_hosted_monitoring_schedule_evidence_skips_completion_for_manual_run(
    tmp_path: Path,
) -> None:
    evidence_output = tmp_path / "hosted-monitoring-schedule-evidence.json"
    completion_output = tmp_path / "hosted-monitoring-schedule-completion-evidence.json"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--event-name",
            "workflow_dispatch",
            "--workflow-name",
            "Hosted Monitoring",
            "--run-id",
            "28493575175",
            "--run-url",
            "https://github.com/pcedison/taiwan-flood-risk-open-map/actions/runs/28493575175",
            "--cron",
            "*/30 * * * *",
            "--captured-at",
            "2026-07-01T05:30:00Z",
            "--evidence-output",
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
    assert evidence["status"] == "skipped"
    assert evidence["completion_evidence_targets"] == []
    assert evidence["failures"] == []
    assert not completion_output.exists()
