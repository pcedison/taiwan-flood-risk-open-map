from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
API_APP = REPO_ROOT / "apps" / "api"
SCRIPT = REPO_ROOT / "scripts" / "source_contract_evidence.py"
AUDIT_SCRIPT = REPO_ROOT / "scripts" / "local-source-completion-audit.py"
PRIVATE_HANDOFF_RUNBOOK = (
    REPO_ROOT / "docs" / "runbooks" / "private-production-evidence-handoff.md"
)
sys.path.insert(0, str(API_APP))

from app.domain.realtime.local_source_action_plan import (  # noqa: E402
    ACCEPTED_SOURCE_CONTRACT_EVIDENCE_STATUSES,
    build_local_source_action_plan,
)
from app.domain.realtime.local_source_coverage import (  # noqa: E402
    list_local_source_coverage,
)


def test_source_contract_evidence_writes_completion_overlay(tmp_path: Path) -> None:
    manifest_path = tmp_path / "source-contract-manifest.json"
    evidence_output = tmp_path / "source-contract-evidence.json"
    completion_output = tmp_path / "source-contract-completion-evidence.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "source-contract-evidence-input/v1",
                "captured_at": "2026-06-30T17:10:00+08:00",
                "source_contract_evidence": _source_contract_entries(),
            },
            ensure_ascii=False,
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
    assert evidence["schema_version"] == "source-contract-evidence/v1"
    assert evidence["status"] == "passed"
    assert evidence["required_source_contract_count"] == len(_source_contract_entries())
    assert evidence["failures"] == []

    completion = json.loads(completion_output.read_text(encoding="utf-8"))
    assert completion == {
        "schema_version": "local-source-completion-evidence/v1",
        "captured_at": "2026-06-30T17:10:00+08:00",
        "signal_family_gap_evidence": [],
        "source_contract_evidence": _source_contract_entries(),
        "production_gate_evidence": [],
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
    assert gates["official_authorization_and_contracts"]["status"] == "satisfied"
    assert audit_payload["overall_status"] == "incomplete"


def test_source_contract_evidence_fails_closed_for_incomplete_manifest(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "source-contract-manifest.json"
    evidence_output = tmp_path / "source-contract-evidence.json"
    completion_output = tmp_path / "source-contract-completion-evidence.json"
    entries = _source_contract_entries()
    incomplete_entries = [
        {**entries[0], "status": "pending"},
        {key: value for key, value in entries[1].items() if key != "evidence_ref"},
        *entries[2:-1],
    ]
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "source-contract-evidence-input/v1",
                "captured_at": "2026-06-30T17:10:00+08:00",
                "source_contract_evidence": incomplete_entries,
            },
            ensure_ascii=False,
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
    assert "source_contract_evidence[0].status must be one of" in result.stdout
    assert "source_contract_evidence[1].evidence_ref is required" in result.stdout
    assert "missing required source contract evidence" in result.stdout
    assert json.loads(evidence_output.read_text(encoding="utf-8"))["status"] == "failed"
    assert not completion_output.exists()


def test_source_contract_evidence_accepts_powershell_utf8_bom_manifest(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "source-contract-manifest.json"
    evidence_output = tmp_path / "source-contract-evidence.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "source-contract-evidence-input/v1",
                "captured_at": "2026-06-30T17:10:00+08:00",
                "source_contract_evidence": _source_contract_entries(),
            },
            ensure_ascii=False,
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


def test_private_handoff_runbook_documents_source_contract_evidence_cli() -> None:
    runbook = PRIVATE_HANDOFF_RUNBOOK.read_text(encoding="utf-8")

    assert "scripts\\source_contract_evidence.py" in runbook
    assert "source-contract-dispatch-evidence" in runbook
    assert "--manifest-json <private-source-contract-manifest.json>" in runbook
    assert "source-contract-evidence-input/v1" in runbook
    assert "authorization_request" in runbook
    assert "metadata_release_monitor" in runbook
    assert "public_api_contract_review" in runbook


def _source_contract_entries() -> list[dict[str, str]]:
    plan = build_local_source_action_plan(list_local_source_coverage())
    entries: list[dict[str, str]] = []
    for gate, bucket in (
        ("authorization_request", "authorization_requests"),
        ("metadata_release_monitor", "metadata_release_monitors"),
        ("public_api_contract_review", "public_api_contract_reviews"),
    ):
        for item in plan[bucket]:
            county = item["county"]
            entries.append(
                {
                    "county": county,
                    "gate": gate,
                    "status": _accepted_status_for_gate(gate),
                    "evidence_ref": (
                        f"private-ops://local-source/source-contract/{county}/{gate}"
                    ),
                    "reviewed_at": "2026-06-30T17:00:00+08:00",
                }
            )
    return entries


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


def _accepted_status_for_gate(gate: str) -> str:
    assert "official_unavailable" in ACCEPTED_SOURCE_CONTRACT_EVIDENCE_STATUSES
    if gate == "authorization_request":
        return "authorized"
    if gate == "metadata_release_monitor":
        return "released"
    return "contract_verified"
