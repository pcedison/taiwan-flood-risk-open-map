from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "local-source-request-followups.py"


def test_local_source_request_followups_cli_reports_overdue_without_private_refs(
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / "dispatch-evidence.json"
    evidence_path.write_text(
        json.dumps(
            {
                "schema_version": "local-source-completion-evidence/v1",
                "captured_at": "2026-06-30T22:35:00+08:00",
                "signal_family_gap_evidence": [
                    {
                        "county": "\u9023\u6c5f\u7e23",
                        "signal_type": "flood_depth",
                        "status": "request_dispatched",
                        "evidence_ref": (
                            "private-ops://local-source/dispatch/flood-depth"
                        ),
                        "dispatched_at": "2026-06-30T22:30:00+08:00",
                        "follow_up_due_at": "2026-07-07T09:00:00+08:00",
                    },
                    {
                        "county": "\u6f8e\u6e56\u7e23",
                        "signal_type": "flood_depth",
                        "status": "request_dispatched",
                        "evidence_ref": (
                            "private-ops://local-source/dispatch/flood-depth"
                        ),
                        "dispatched_at": "2026-06-30T22:30:00+08:00",
                        "follow_up_due_at": "2026-07-09T09:00:00+08:00",
                    },
                    {
                        "county": "\u81fa\u5317\u5e02",
                        "signal_type": "flood_depth",
                        "status": "request_dispatched",
                        "evidence_ref": (
                            "private-ops://local-source/dispatch/flood-depth"
                        ),
                        "dispatched_at": "2026-06-30T22:30:00+08:00",
                    },
                ],
                "source_contract_evidence": [
                    {
                        "county": "\u91d1\u9580\u7e23",
                        "gate": "authorization_request",
                        "status": "request_dispatched",
                        "evidence_ref": (
                            "private-ops://local-source/source-contract-dispatch/"
                            "2026-06-30"
                        ),
                        "dispatched_at": "2026-06-30T22:35:00+08:00",
                        "follow_up_due_at": "2026-07-07T09:00:00+08:00",
                    }
                ],
                "production_gate_evidence": [],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--completion-evidence-json",
            str(evidence_path),
            "--as-of",
            "2026-07-08T00:00:00+08:00",
            "--fail-on-overdue",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "local-source-request-followups/v1"
    assert payload["as_of"] == "2026-07-08T00:00:00+08:00"
    assert payload["summary"] == {
        "dispatch_item_count": 4,
        "follow_up_scheduled_count": 3,
        "missing_follow_up_count": 1,
        "pending_count": 1,
        "overdue_count": 2,
        "next_follow_up_due_at": "2026-07-07T09:00:00+08:00",
    }
    assert payload["overdue_items"] == [
        {
            "section": "signal_family_gap_evidence",
            "county": "\u9023\u6c5f\u7e23",
            "signal_type": "flood_depth",
            "follow_up_due_at": "2026-07-07T09:00:00+08:00",
        },
        {
            "section": "source_contract_evidence",
            "county": "\u91d1\u9580\u7e23",
            "gate": "authorization_request",
            "follow_up_due_at": "2026-07-07T09:00:00+08:00",
        },
    ]
    assert "private-ops://" not in result.stdout


def test_local_source_request_followups_cli_writes_output_when_no_overdue(
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / "dispatch-evidence.json"
    output_path = tmp_path / "followups.json"
    evidence_path.write_text(
        json.dumps(
            {
                "schema_version": "local-source-completion-evidence/v1",
                "captured_at": "2026-06-30T22:35:00+08:00",
                "signal_family_gap_evidence": [
                    {
                        "county": "\u9023\u6c5f\u7e23",
                        "signal_type": "flood_depth",
                        "status": "request_dispatched",
                        "evidence_ref": (
                            "private-ops://local-source/dispatch/flood-depth"
                        ),
                        "dispatched_at": "2026-06-30T22:30:00+08:00",
                        "follow_up_due_at": "2026-07-07T09:00:00+08:00",
                    }
                ],
                "source_contract_evidence": [],
                "production_gate_evidence": [],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--completion-evidence-json",
            str(evidence_path),
            "--as-of",
            "2026-07-01T00:00:00+08:00",
            "--output",
            str(output_path),
            "--fail-on-overdue",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["summary"]["overdue_count"] == 0
    assert payload["summary"]["pending_count"] == 1
