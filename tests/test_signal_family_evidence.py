from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
API_APP = REPO_ROOT / "apps" / "api"
SCRIPT = REPO_ROOT / "scripts" / "signal_family_evidence.py"
AUDIT_SCRIPT = REPO_ROOT / "scripts" / "local-source-completion-audit.py"
PRIVATE_HANDOFF_RUNBOOK = (
    REPO_ROOT / "docs" / "runbooks" / "private-production-evidence-handoff.md"
)
sys.path.insert(0, str(API_APP))

from app.domain.realtime.local_source_action_plan import (  # noqa: E402
    ACCEPTED_SIGNAL_EVIDENCE_STATUSES,
    build_local_source_action_plan,
)
from app.domain.realtime.local_source_coverage import (  # noqa: E402
    list_local_source_coverage,
)


def test_signal_family_evidence_writes_completion_overlay(tmp_path: Path) -> None:
    manifest_path = tmp_path / "signal-family-manifest.json"
    evidence_output = tmp_path / "signal-family-evidence.json"
    completion_output = tmp_path / "signal-family-completion-evidence.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "signal-family-evidence-input/v1",
                "captured_at": "2026-06-30T18:20:00+08:00",
                "signal_family_gap_evidence": _signal_family_entries(),
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
    assert evidence["schema_version"] == "signal-family-evidence/v1"
    assert evidence["status"] == "passed"
    assert evidence["required_signal_family_count"] == len(_signal_family_entries())
    assert evidence["failures"] == []

    completion = json.loads(completion_output.read_text(encoding="utf-8"))
    assert completion == {
        "schema_version": "local-source-completion-evidence/v1",
        "captured_at": "2026-06-30T18:20:00+08:00",
        "signal_family_gap_evidence": _signal_family_entries(),
        "source_contract_evidence": [],
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
    assert gates["required_signal_families"]["status"] == "satisfied"
    assert audit_payload["overall_status"] == "incomplete"


def test_signal_family_evidence_fails_closed_for_incomplete_manifest(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "signal-family-manifest.json"
    evidence_output = tmp_path / "signal-family-evidence.json"
    completion_output = tmp_path / "signal-family-completion-evidence.json"
    entries = _signal_family_entries()
    incomplete_entries = [
        {**entries[0], "status": "request_dispatched"},
        {key: value for key, value in entries[1].items() if key != "evidence_ref"},
        *entries[2:-1],
    ]
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "signal-family-evidence-input/v1",
                "captured_at": "2026-06-30T18:20:00+08:00",
                "signal_family_gap_evidence": incomplete_entries,
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
    assert "signal_family_gap_evidence[0].status must be one of" in result.stdout
    assert "signal_family_gap_evidence[1].evidence_ref is required" in result.stdout
    assert "missing required signal family evidence" in result.stdout
    assert json.loads(evidence_output.read_text(encoding="utf-8"))["status"] == "failed"
    assert not completion_output.exists()


def test_signal_family_evidence_accepts_powershell_utf8_bom_manifest(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "signal-family-manifest.json"
    evidence_output = tmp_path / "signal-family-evidence.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "signal-family-evidence-input/v1",
                "captured_at": "2026-06-30T18:20:00+08:00",
                "signal_family_gap_evidence": _signal_family_entries(),
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


def test_private_handoff_runbook_documents_signal_family_evidence_cli() -> None:
    runbook = PRIVATE_HANDOFF_RUNBOOK.read_text(encoding="utf-8")

    assert "scripts\\signal_family_evidence.py" in runbook
    assert "--manifest-json <private-signal-family-manifest.json>" in runbook
    assert "signal-family-evidence-input/v1" in runbook
    assert "production_adapter" in runbook
    assert "authorization_gated_adapter" in runbook
    assert "official_unavailable" in runbook
    assert "request_dispatched" in runbook


def _signal_family_entries() -> list[dict[str, str]]:
    plan = build_local_source_action_plan(list_local_source_coverage())
    entries: list[dict[str, str]] = []
    for group in plan["signal_gap_priority_groups"]:
        signal_type = group["signal_type"]
        for county in group["counties"]:
            entries.append(
                {
                    "county": county,
                    "signal_type": signal_type,
                    "status": _accepted_status_for_signal(signal_type),
                    "evidence_ref": (
                        f"private-ops://local-source/signal-gap/{county}/{signal_type}"
                    ),
                    "reviewed_at": "2026-06-30T18:10:00+08:00",
                }
            )
    return entries


def _accepted_status_for_signal(signal_type: str) -> str:
    assert "official_unavailable" in ACCEPTED_SIGNAL_EVIDENCE_STATUSES
    if signal_type == "pump_or_gate_status":
        return "authorization_gated_adapter"
    if signal_type == "flood_depth":
        return "production_adapter"
    return "official_unavailable"


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
