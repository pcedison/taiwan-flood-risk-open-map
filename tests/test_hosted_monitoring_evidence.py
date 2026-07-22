from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "hosted_monitoring_evidence.py"
AUDIT_SCRIPT = REPO_ROOT / "scripts" / "local-source-completion-audit.py"
PRIVATE_HANDOFF_RUNBOOK = (
    REPO_ROOT / "docs" / "runbooks" / "private-production-evidence-handoff.md"
)
GENERATED_TEMPLATE = (
    REPO_ROOT
    / "docs"
    / "data-sources"
    / "local"
    / "generated-hosted-monitoring-evidence-template.json"
)
HOSTED_MONITORING_REQUIREMENTS = [
    "hosted_alert_routing",
    "scheduled_freshness_checks",
    "worker_scheduler_alert_ownership",
]


def test_hosted_monitoring_evidence_writes_completion_overlay(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "monitoring-manifest.json"
    evidence_output = tmp_path / "hosted-monitoring-evidence.json"
    completion_output = tmp_path / "monitoring-completion-evidence.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "hosted-monitoring-evidence-input/v1",
                "captured_at": "2026-06-30T16:10:00+08:00",
                "hosted_alert_routing": {
                    "status": "verified",
                    "owner": "ops-oncall",
                    "evidence_ref": "private-ops://monitoring/alert-routing",
                    "reviewed_at": "2026-06-30T16:00:00+08:00",
                },
                "scheduled_freshness_checks": {
                    "status": "verified",
                    "cadence": "PT5M",
                    "evidence_ref": "private-ops://monitoring/freshness-cron",
                    "observed_at": "2026-06-30T16:05:00+08:00",
                },
                "worker_scheduler_alert_ownership": {
                    "status": "verified",
                    "owner": "worker-platform-owner",
                    "evidence_ref": "private-ops://monitoring/worker-scheduler-owner",
                    "reviewed_at": "2026-06-30T16:00:00+08:00",
                },
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--manifest-json",
            str(manifest_path),
            "--evidence-output",
            str(evidence_output),
            "--completion-evidence-output",
            str(completion_output),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr

    evidence = json.loads(evidence_output.read_text(encoding="utf-8"))
    assert evidence["schema_version"] == "hosted-monitoring-evidence/v1"
    assert evidence["status"] == "passed"
    assert evidence["monitoring_evidence"]["scheduled_freshness_checks"] == {
        "status": "verified",
        "cadence": "PT5M",
        "evidence_ref": "private-ops://monitoring/freshness-cron",
        "observed_at": "2026-06-30T16:05:00+08:00",
    }

    completion = json.loads(completion_output.read_text(encoding="utf-8"))
    assert completion == {
        "schema_version": "local-source-completion-evidence/v1",
        "captured_at": "2026-06-30T16:10:00+08:00",
        "signal_family_gap_evidence": [],
        "source_contract_evidence": [],
        "production_gate_evidence": [
            {
                "gate_key": "production_monitoring_and_alerting",
                "status": "accepted",
                "evidence_ref": str(evidence_output),
                "satisfied_requirements": [
                    "hosted_alert_routing",
                    "scheduled_freshness_checks",
                    "worker_scheduler_alert_ownership",
                ],
                "requirement_evidence": [
                    {
                        "requirement": "hosted_alert_routing",
                        "evidence_ref": (
                            f"{evidence_output}"
                            "#/monitoring_evidence/hosted_alert_routing"
                        ),
                        "reviewed_at": "2026-06-30T16:00:00+08:00",
                    },
                    {
                        "requirement": "scheduled_freshness_checks",
                        "evidence_ref": (
                            f"{evidence_output}"
                            "#/monitoring_evidence/scheduled_freshness_checks"
                        ),
                        "observed_at": "2026-06-30T16:05:00+08:00",
                    },
                    {
                        "requirement": "worker_scheduler_alert_ownership",
                        "evidence_ref": (
                            f"{evidence_output}"
                            "#/monitoring_evidence/worker_scheduler_alert_ownership"
                        ),
                        "reviewed_at": "2026-06-30T16:00:00+08:00",
                    },
                ],
            }
        ],
    }

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
        text=True,
        check=False,
    )
    assert audit.returncode == 0, audit.stderr
    audit_payload = json.loads(audit.stdout)
    gates = {gate["gate_key"]: gate for gate in audit_payload["gates"]}
    assert gates["production_monitoring_and_alerting"]["status"] == "satisfied"
    assert audit_payload["overall_status"] == "incomplete"


def test_hosted_monitoring_evidence_fails_closed_for_incomplete_manifest(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "monitoring-manifest.json"
    completion_output = tmp_path / "monitoring-completion-evidence.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "hosted-monitoring-evidence-input/v1",
                "captured_at": "2026-06-30T16:10:00+08:00",
                "hosted_alert_routing": {
                    "status": "verified",
                    "evidence_ref": "private-ops://monitoring/alert-routing",
                    "reviewed_at": "2026-06-30T16:00:00+08:00",
                },
                "scheduled_freshness_checks": {
                    "status": "pending",
                    "cadence": "PT5M",
                    "evidence_ref": "private-ops://monitoring/freshness-cron",
                    "observed_at": "2026-06-30T16:05:00+08:00",
                },
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--manifest-json",
            str(manifest_path),
            "--completion-evidence-output",
            str(completion_output),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "hosted_alert_routing.owner is required" in result.stdout
    assert "scheduled_freshness_checks.status must be verified" in result.stdout
    assert "worker_scheduler_alert_ownership is required" in result.stdout
    assert not completion_output.exists()


def test_hosted_monitoring_evidence_accepts_powershell_utf8_bom_manifest(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "monitoring-manifest.json"
    evidence_output = tmp_path / "hosted-monitoring-evidence.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "hosted-monitoring-evidence-input/v1",
                "captured_at": "2026-06-30T16:10:00+08:00",
                "hosted_alert_routing": {
                    "status": "verified",
                    "owner": "ops-oncall",
                    "evidence_ref": "private-ops://monitoring/alert-routing",
                    "reviewed_at": "2026-06-30T16:00:00+08:00",
                },
                "scheduled_freshness_checks": {
                    "status": "verified",
                    "cadence": "PT5M",
                    "evidence_ref": "private-ops://monitoring/freshness-cron",
                    "observed_at": "2026-06-30T16:05:00+08:00",
                },
                "worker_scheduler_alert_ownership": {
                    "status": "verified",
                    "owner": "worker-platform-owner",
                    "evidence_ref": "private-ops://monitoring/worker-owner",
                    "reviewed_at": "2026-06-30T16:00:00+08:00",
                },
            }
        ),
        encoding="utf-8-sig",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--manifest-json",
            str(manifest_path),
            "--evidence-output",
            str(evidence_output),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(evidence_output.read_text(encoding="utf-8"))["status"] == "passed"


def test_hosted_monitoring_evidence_writes_pending_manifest_template(
    tmp_path: Path,
) -> None:
    template_output = tmp_path / "hosted-monitoring-template.json"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--template-output",
            str(template_output),
            "--captured-at",
            "2026-07-01T01:25:00+08:00",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    template = json.loads(template_output.read_text(encoding="utf-8"))

    assert template["schema_version"] == "hosted-monitoring-evidence-input/v1"
    assert template["captured_at"] == "2026-07-01T01:25:00+08:00"
    assert template["template_status"] == "pending_private_evidence"
    assert _template_requirement_keys(template) == HOSTED_MONITORING_REQUIREMENTS

    for requirement in HOSTED_MONITORING_REQUIREMENTS:
        item = template[requirement]
        assert item["status"] == "pending"
        assert item["accepted_status"] == "verified"
        assert item["evidence_ref"].startswith("private-ops://hosted-monitoring/")

    evidence_output = tmp_path / "hosted-monitoring-evidence.json"
    validation = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--manifest-json",
            str(template_output),
            "--evidence-output",
            str(evidence_output),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert validation.returncode == 1
    assert "status must be verified" in validation.stdout
    assert json.loads(evidence_output.read_text(encoding="utf-8"))["status"] == "failed"


def test_checked_in_hosted_monitoring_template_matches_requirements() -> None:
    template = json.loads(GENERATED_TEMPLATE.read_text(encoding="utf-8"))

    assert template["schema_version"] == "hosted-monitoring-evidence-input/v1"
    assert template["template_status"] == "pending_private_evidence"
    assert _template_requirement_keys(template) == HOSTED_MONITORING_REQUIREMENTS

    for requirement in HOSTED_MONITORING_REQUIREMENTS:
        item = template[requirement]
        assert item["status"] == "pending"
        assert item["accepted_status"] == "verified"
        assert item["evidence_ref"] == f"private-ops://hosted-monitoring/{requirement}"


def test_private_handoff_runbook_documents_monitoring_evidence_cli() -> None:
    runbook = PRIVATE_HANDOFF_RUNBOOK.read_text(encoding="utf-8")

    assert "scripts\\hosted_monitoring_evidence.py" in runbook
    assert "--template-output <private-monitoring-manifest-template.json>" in runbook
    assert "--manifest-json <private-monitoring-manifest.json>" in runbook
    assert "production_monitoring_and_alerting" in runbook
    assert "hosted_alert_routing" in runbook
    assert "scheduled_freshness_checks" in runbook
    assert "worker_scheduler_alert_ownership" in runbook


def _template_requirement_keys(template: dict[str, object]) -> list[str]:
    return [
        key
        for key in template
        if key
        not in {
            "schema_version",
            "captured_at",
            "template_status",
            "notes",
        }
    ]
