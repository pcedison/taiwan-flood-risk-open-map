from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "hosted_worker_evidence.py"
AUDIT_SCRIPT = REPO_ROOT / "scripts" / "local-source-completion-audit.py"
PRIVATE_HANDOFF_RUNBOOK = (
    REPO_ROOT / "docs" / "runbooks" / "private-production-evidence-handoff.md"
)


def test_hosted_worker_evidence_writes_completion_overlay(tmp_path: Path) -> None:
    manifest_path = tmp_path / "hosted-worker-manifest.json"
    evidence_output = tmp_path / "hosted-worker-evidence.json"
    completion_output = tmp_path / "hosted-worker-completion-evidence.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "hosted-worker-evidence-input/v1",
                "captured_at": "2026-06-30T16:40:00+08:00",
                "freshness_policy": {
                    "status": "verified",
                    "evidence_ref": "private-ops://worker/freshness-policy",
                    "observed_at": "2026-06-30T16:30:00+08:00",
                    "max_lag_minutes": 10,
                },
                "raw_snapshot_retention_policy": {
                    "status": "verified",
                    "evidence_ref": "private-ops://worker/raw-snapshots",
                    "reviewed_at": "2026-06-30T16:20:00+08:00",
                    "retention_days": 30,
                },
                "monitored_scheduler_cadence": {
                    "status": "verified",
                    "evidence_ref": "private-ops://worker/scheduler-cadence",
                    "observed_at": "2026-06-30T16:35:00+08:00",
                    "cadence": "PT5M",
                },
                "hosted_egress_review": {
                    "status": "verified",
                    "evidence_ref": "private-ops://worker/egress-review",
                    "reviewed_at": "2026-06-30T16:25:00+08:00",
                    "reviewer": "platform-security",
                },
                "worker_persisted_evidence_path": {
                    "status": "verified",
                    "evidence_ref": "private-ops://worker/persisted-evidence",
                    "observed_at": "2026-06-30T16:36:00+08:00",
                    "adapter_keys": [
                        "official.cwa.rainfall",
                        "official.wra.water_level",
                    ],
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
    assert evidence["schema_version"] == "hosted-worker-evidence/v1"
    assert evidence["status"] == "passed"
    assert evidence["hosted_worker_evidence"]["raw_snapshot_retention_policy"] == {
        "status": "verified",
        "evidence_ref": "private-ops://worker/raw-snapshots",
        "reviewed_at": "2026-06-30T16:20:00+08:00",
        "retention_days": 30,
    }

    completion = json.loads(completion_output.read_text(encoding="utf-8"))
    assert completion == {
        "schema_version": "local-source-completion-evidence/v1",
        "captured_at": "2026-06-30T16:40:00+08:00",
        "signal_family_gap_evidence": [],
        "source_contract_evidence": [],
        "production_gate_evidence": [
            {
                "gate_key": "hosted_worker_persisted_evidence",
                "status": "accepted",
                "evidence_ref": str(evidence_output),
                "satisfied_requirements": [
                    "freshness_policy",
                    "raw_snapshot_retention_policy",
                    "monitored_scheduler_cadence",
                    "hosted_egress_review",
                    "worker_persisted_evidence_path",
                ],
                "requirement_evidence": [
                    {
                        "requirement": "freshness_policy",
                        "evidence_ref": (
                            f"{evidence_output}"
                            "#/hosted_worker_evidence/freshness_policy"
                        ),
                        "observed_at": "2026-06-30T16:30:00+08:00",
                    },
                    {
                        "requirement": "raw_snapshot_retention_policy",
                        "evidence_ref": (
                            f"{evidence_output}"
                            "#/hosted_worker_evidence/raw_snapshot_retention_policy"
                        ),
                        "reviewed_at": "2026-06-30T16:20:00+08:00",
                    },
                    {
                        "requirement": "monitored_scheduler_cadence",
                        "evidence_ref": (
                            f"{evidence_output}"
                            "#/hosted_worker_evidence/monitored_scheduler_cadence"
                        ),
                        "observed_at": "2026-06-30T16:35:00+08:00",
                    },
                    {
                        "requirement": "hosted_egress_review",
                        "evidence_ref": (
                            f"{evidence_output}"
                            "#/hosted_worker_evidence/hosted_egress_review"
                        ),
                        "reviewed_at": "2026-06-30T16:25:00+08:00",
                    },
                    {
                        "requirement": "worker_persisted_evidence_path",
                        "evidence_ref": (
                            f"{evidence_output}"
                            "#/hosted_worker_evidence/worker_persisted_evidence_path"
                        ),
                        "observed_at": "2026-06-30T16:36:00+08:00",
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
    assert gates["hosted_worker_persisted_evidence"]["status"] == "satisfied"
    assert audit_payload["overall_status"] == "incomplete"


def test_hosted_worker_evidence_fails_closed_for_incomplete_manifest(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "hosted-worker-manifest.json"
    completion_output = tmp_path / "hosted-worker-completion-evidence.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "hosted-worker-evidence-input/v1",
                "captured_at": "2026-06-30T16:40:00+08:00",
                "freshness_policy": {
                    "status": "verified",
                    "evidence_ref": "private-ops://worker/freshness-policy",
                    "observed_at": "2026-06-30T16:30:00+08:00",
                    "max_lag_minutes": 10,
                },
                "monitored_scheduler_cadence": {
                    "status": "pending",
                    "evidence_ref": "private-ops://worker/scheduler-cadence",
                    "observed_at": "2026-06-30T16:35:00+08:00",
                },
                "hosted_egress_review": {
                    "status": "verified",
                    "evidence_ref": "private-ops://worker/egress-review",
                    "reviewed_at": "2026-06-30T16:25:00+08:00",
                },
                "worker_persisted_evidence_path": {
                    "status": "verified",
                    "evidence_ref": "private-ops://worker/persisted-evidence",
                    "observed_at": "2026-06-30T16:36:00+08:00",
                    "adapter_keys": [],
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
    assert "raw_snapshot_retention_policy is required" in result.stdout
    assert "monitored_scheduler_cadence.status must be verified" in result.stdout
    assert "monitored_scheduler_cadence.cadence is required" in result.stdout
    assert "hosted_egress_review.reviewer is required" in result.stdout
    assert "worker_persisted_evidence_path.adapter_keys is required" in result.stdout
    assert "--completion-evidence-output requires --evidence-output" in result.stdout
    assert not completion_output.exists()


def test_hosted_worker_evidence_accepts_powershell_utf8_bom_manifest(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "hosted-worker-manifest.json"
    evidence_output = tmp_path / "hosted-worker-evidence.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "hosted-worker-evidence-input/v1",
                "captured_at": "2026-06-30T16:40:00+08:00",
                "freshness_policy": {
                    "status": "verified",
                    "evidence_ref": "private-ops://worker/freshness-policy",
                    "observed_at": "2026-06-30T16:30:00+08:00",
                    "max_lag_minutes": 10,
                },
                "raw_snapshot_retention_policy": {
                    "status": "verified",
                    "evidence_ref": "private-ops://worker/raw-snapshots",
                    "reviewed_at": "2026-06-30T16:20:00+08:00",
                    "retention_days": 30,
                },
                "monitored_scheduler_cadence": {
                    "status": "verified",
                    "evidence_ref": "private-ops://worker/scheduler-cadence",
                    "observed_at": "2026-06-30T16:35:00+08:00",
                    "cadence": "PT5M",
                },
                "hosted_egress_review": {
                    "status": "verified",
                    "evidence_ref": "private-ops://worker/egress-review",
                    "reviewed_at": "2026-06-30T16:25:00+08:00",
                    "reviewer": "platform-security",
                },
                "worker_persisted_evidence_path": {
                    "status": "verified",
                    "evidence_ref": "private-ops://worker/persisted-evidence",
                    "observed_at": "2026-06-30T16:36:00+08:00",
                    "adapter_keys": ["official.cwa.rainfall"],
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


def test_private_handoff_runbook_documents_hosted_worker_evidence_cli() -> None:
    runbook = PRIVATE_HANDOFF_RUNBOOK.read_text(encoding="utf-8")

    assert "scripts\\hosted_worker_evidence.py" in runbook
    assert "--manifest-json <private-hosted-worker-manifest.json>" in runbook
    assert "hosted_worker_persisted_evidence" in runbook
    assert "raw_snapshot_retention_policy" in runbook
    assert "monitored_scheduler_cadence" in runbook
    assert "hosted_egress_review" in runbook
    assert "worker_persisted_evidence_path" in runbook
