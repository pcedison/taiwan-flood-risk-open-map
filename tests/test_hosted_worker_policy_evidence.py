from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "hosted_worker_policy_evidence.py"
AUDIT_SCRIPT = REPO_ROOT / "scripts" / "local-source-completion-audit.py"
PRIVATE_HANDOFF_RUNBOOK = (
    REPO_ROOT / "docs" / "runbooks" / "private-production-evidence-handoff.md"
)
GENERATED_TEMPLATE = (
    REPO_ROOT
    / "docs"
    / "data-sources"
    / "local"
    / "generated-hosted-worker-policy-evidence-template.json"
)
HOSTED_WORKER_POLICY_REQUIREMENTS = [
    "raw_snapshot_retention_policy",
    "monitored_scheduler_cadence",
    "hosted_egress_review",
]


def test_hosted_worker_policy_evidence_writes_mergeable_completion_overlay(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "hosted-worker-policy-manifest.json"
    evidence_output = tmp_path / "hosted-worker-policy-evidence.json"
    completion_output = tmp_path / "hosted-worker-policy-completion-evidence.json"
    public_freshness_completion = tmp_path / "hosted-source-freshness-completion.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "hosted-worker-policy-evidence-input/v1",
                "captured_at": "2026-06-30T18:40:00+08:00",
                "raw_snapshot_retention_policy": {
                    "status": "verified",
                    "evidence_ref": "private-ops://worker/raw-snapshots",
                    "reviewed_at": "2026-06-30T18:20:00+08:00",
                    "retention_days": 30,
                },
                "monitored_scheduler_cadence": {
                    "status": "verified",
                    "evidence_ref": "private-ops://worker/scheduler-cadence",
                    "observed_at": "2026-06-30T18:35:00+08:00",
                    "cadence": "PT5M",
                },
                "hosted_egress_review": {
                    "status": "verified",
                    "evidence_ref": "private-ops://worker/egress-review",
                    "reviewed_at": "2026-06-30T18:25:00+08:00",
                    "reviewer": "platform-security",
                },
            }
        ),
        encoding="utf-8",
    )

    result = _run_script(
        "--manifest-json",
        str(manifest_path),
        "--evidence-output",
        str(evidence_output),
        "--completion-evidence-output",
        str(completion_output),
    )

    assert result.returncode == 0, result.stdout + result.stderr

    evidence = json.loads(evidence_output.read_text(encoding="utf-8"))
    assert evidence["schema_version"] == "hosted-worker-policy-evidence/v1"
    assert evidence["status"] == "passed"
    assert evidence["hosted_worker_policy_evidence"]["raw_snapshot_retention_policy"] == {
        "status": "verified",
        "evidence_ref": "private-ops://worker/raw-snapshots",
        "reviewed_at": "2026-06-30T18:20:00+08:00",
        "retention_days": 30,
    }

    completion = json.loads(completion_output.read_text(encoding="utf-8"))
    assert completion == {
        "schema_version": "local-source-completion-evidence/v1",
        "captured_at": "2026-06-30T18:40:00+08:00",
        "signal_family_gap_evidence": [],
        "source_contract_evidence": [],
        "production_gate_evidence": [
            {
                "gate_key": "hosted_worker_persisted_evidence",
                "status": "accepted",
                "evidence_ref": str(evidence_output),
                "satisfied_requirements": [
                    "raw_snapshot_retention_policy",
                    "monitored_scheduler_cadence",
                    "hosted_egress_review",
                ],
                "requirement_evidence": [
                    {
                        "requirement": "raw_snapshot_retention_policy",
                        "evidence_ref": (
                            f"{evidence_output}"
                            "#/hosted_worker_policy_evidence/"
                            "raw_snapshot_retention_policy"
                        ),
                        "reviewed_at": "2026-06-30T18:20:00+08:00",
                    },
                    {
                        "requirement": "monitored_scheduler_cadence",
                        "evidence_ref": (
                            f"{evidence_output}"
                            "#/hosted_worker_policy_evidence/"
                            "monitored_scheduler_cadence"
                        ),
                        "observed_at": "2026-06-30T18:35:00+08:00",
                    },
                    {
                        "requirement": "hosted_egress_review",
                        "evidence_ref": (
                            f"{evidence_output}"
                            "#/hosted_worker_policy_evidence/hosted_egress_review"
                        ),
                        "reviewed_at": "2026-06-30T18:25:00+08:00",
                    },
                ],
            }
        ],
    }

    public_freshness_completion.write_text(
        json.dumps(_public_freshness_completion_overlay()),
        encoding="utf-8",
    )
    audit = subprocess.run(
        [
            sys.executable,
            str(AUDIT_SCRIPT),
            "--completion-evidence-json",
            str(public_freshness_completion),
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


def test_hosted_worker_policy_evidence_fails_closed_for_incomplete_manifest(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "hosted-worker-policy-manifest.json"
    evidence_output = tmp_path / "hosted-worker-policy-evidence.json"
    completion_output = tmp_path / "hosted-worker-policy-completion-evidence.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "hosted-worker-policy-evidence-input/v1",
                "captured_at": "2026-06-30T18:40:00+08:00",
                "raw_snapshot_retention_policy": {
                    "status": "verified",
                    "evidence_ref": "private-ops://worker/raw-snapshots",
                    "reviewed_at": "2026-06-30T18:20:00+08:00",
                    "retention_days": 0,
                },
                "monitored_scheduler_cadence": {
                    "status": "pending",
                    "evidence_ref": "private-ops://worker/scheduler-cadence",
                    "observed_at": "2026-06-30T18:35:00+08:00",
                },
                "hosted_egress_review": {
                    "status": "verified",
                    "evidence_ref": "private-ops://worker/egress-review",
                    "reviewed_at": "2026-06-30T18:25:00+08:00",
                },
            }
        ),
        encoding="utf-8",
    )

    result = _run_script(
        "--manifest-json",
        str(manifest_path),
        "--evidence-output",
        str(evidence_output),
        "--completion-evidence-output",
        str(completion_output),
    )

    assert result.returncode == 1
    assert "raw_snapshot_retention_policy.retention_days must be greater than 0" in result.stdout
    assert "monitored_scheduler_cadence.status must be verified" in result.stdout
    assert "monitored_scheduler_cadence.cadence is required" in result.stdout
    assert "hosted_egress_review.reviewer is required" in result.stdout
    assert json.loads(evidence_output.read_text(encoding="utf-8"))["status"] == "failed"
    assert not completion_output.exists()


def test_hosted_worker_policy_evidence_accepts_powershell_utf8_bom_manifest(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "hosted-worker-policy-manifest.json"
    evidence_output = tmp_path / "hosted-worker-policy-evidence.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "hosted-worker-policy-evidence-input/v1",
                "captured_at": "2026-06-30T18:40:00+08:00",
                "raw_snapshot_retention_policy": {
                    "status": "verified",
                    "evidence_ref": "private-ops://worker/raw-snapshots",
                    "reviewed_at": "2026-06-30T18:20:00+08:00",
                    "retention_days": 30,
                },
                "monitored_scheduler_cadence": {
                    "status": "verified",
                    "evidence_ref": "private-ops://worker/scheduler-cadence",
                    "observed_at": "2026-06-30T18:35:00+08:00",
                    "cadence": "PT5M",
                },
                "hosted_egress_review": {
                    "status": "verified",
                    "evidence_ref": "private-ops://worker/egress-review",
                    "reviewed_at": "2026-06-30T18:25:00+08:00",
                    "reviewer": "platform-security",
                },
            }
        ),
        encoding="utf-8-sig",
    )

    result = _run_script(
        "--manifest-json",
        str(manifest_path),
        "--evidence-output",
        str(evidence_output),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(evidence_output.read_text(encoding="utf-8"))["status"] == "passed"


def test_hosted_worker_policy_evidence_writes_pending_manifest_template(
    tmp_path: Path,
) -> None:
    template_output = tmp_path / "hosted-worker-policy-template.json"

    result = _run_script(
        "--template-output",
        str(template_output),
        "--captured-at",
        "2026-07-01T01:20:00+08:00",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    template = json.loads(template_output.read_text(encoding="utf-8"))

    assert template["schema_version"] == "hosted-worker-policy-evidence-input/v1"
    assert template["captured_at"] == "2026-07-01T01:20:00+08:00"
    assert template["template_status"] == "pending_private_evidence"
    assert _template_requirement_keys(template) == HOSTED_WORKER_POLICY_REQUIREMENTS

    for requirement in HOSTED_WORKER_POLICY_REQUIREMENTS:
        item = template[requirement]
        assert item["status"] == "pending"
        assert item["accepted_status"] == "verified"
        assert item["evidence_ref"].startswith("private-ops://hosted-worker-policy/")

    evidence_output = tmp_path / "hosted-worker-policy-evidence.json"
    validation = _run_script(
        "--manifest-json",
        str(template_output),
        "--evidence-output",
        str(evidence_output),
    )

    assert validation.returncode == 1
    assert "status must be verified" in validation.stdout
    assert json.loads(evidence_output.read_text(encoding="utf-8"))["status"] == "failed"


def test_checked_in_hosted_worker_policy_template_matches_requirements() -> None:
    template = json.loads(GENERATED_TEMPLATE.read_text(encoding="utf-8"))

    assert template["schema_version"] == "hosted-worker-policy-evidence-input/v1"
    assert template["template_status"] == "pending_private_evidence"
    assert _template_requirement_keys(template) == HOSTED_WORKER_POLICY_REQUIREMENTS

    for requirement in HOSTED_WORKER_POLICY_REQUIREMENTS:
        item = template[requirement]
        assert item["status"] == "pending"
        assert item["accepted_status"] == "verified"
        assert item["evidence_ref"] == f"private-ops://hosted-worker-policy/{requirement}"


def test_hosted_worker_policy_evidence_requires_evidence_output_for_completion_overlay(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "hosted-worker-policy-manifest.json"
    completion_output = tmp_path / "hosted-worker-policy-completion-evidence.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "hosted-worker-policy-evidence-input/v1",
                "captured_at": "2026-06-30T18:40:00+08:00",
                "raw_snapshot_retention_policy": {
                    "status": "verified",
                    "evidence_ref": "private-ops://worker/raw-snapshots",
                    "reviewed_at": "2026-06-30T18:20:00+08:00",
                    "retention_days": 30,
                },
                "monitored_scheduler_cadence": {
                    "status": "verified",
                    "evidence_ref": "private-ops://worker/scheduler-cadence",
                    "observed_at": "2026-06-30T18:35:00+08:00",
                    "cadence": "PT5M",
                },
                "hosted_egress_review": {
                    "status": "verified",
                    "evidence_ref": "private-ops://worker/egress-review",
                    "reviewed_at": "2026-06-30T18:25:00+08:00",
                    "reviewer": "platform-security",
                },
            }
        ),
        encoding="utf-8",
    )

    result = _run_script(
        "--manifest-json",
        str(manifest_path),
        "--completion-evidence-output",
        str(completion_output),
    )

    assert result.returncode == 1
    assert "--completion-evidence-output requires --evidence-output" in result.stdout
    assert not completion_output.exists()


def test_private_handoff_runbook_documents_hosted_worker_policy_evidence_cli() -> None:
    runbook = PRIVATE_HANDOFF_RUNBOOK.read_text(encoding="utf-8")

    assert "scripts\\hosted_worker_policy_evidence.py" in runbook
    assert "--template-output <private-hosted-worker-policy-manifest-template.json>" in runbook
    assert "--manifest-json <private-hosted-worker-policy-manifest.json>" in runbook
    assert "hosted-worker-policy-evidence-input/v1" in runbook
    assert "raw_snapshot_retention_policy" in runbook
    assert "monitored_scheduler_cadence" in runbook
    assert "hosted_egress_review" in runbook


def _public_freshness_completion_overlay() -> dict:
    return {
        "schema_version": "local-source-completion-evidence/v1",
        "captured_at": "2026-06-30T18:36:00+08:00",
        "signal_family_gap_evidence": [],
        "source_contract_evidence": [],
        "production_gate_evidence": [
            {
                "gate_key": "hosted_worker_persisted_evidence",
                "status": "accepted",
                "evidence_ref": "private-ops://hosted-source-freshness/admin-smoke",
                "satisfied_requirements": [
                    "freshness_policy",
                    "worker_persisted_evidence_path",
                ],
                "requirement_evidence": [
                    {
                        "requirement": "freshness_policy",
                        "evidence_ref": "private-ops://hosted-source-freshness/admin-smoke",
                        "observed_at": "2026-06-30T18:36:00+08:00",
                    },
                    {
                        "requirement": "worker_persisted_evidence_path",
                        "evidence_ref": "private-ops://hosted-source-freshness/admin-smoke",
                        "observed_at": "2026-06-30T18:36:00+08:00",
                    },
                ],
            }
        ],
    }


def _run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        text=True,
        check=False,
    )


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
