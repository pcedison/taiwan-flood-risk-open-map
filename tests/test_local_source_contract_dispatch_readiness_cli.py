from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "local-source-contract-dispatch-readiness.py"


def test_source_contract_dispatch_readiness_cli_emits_public_safe_checklist(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "source-contract-dispatch-readiness.json"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--captured-at",
            "2026-07-01T12:10:00+08:00",
            "--output",
            str(output_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "local-source-contract-dispatch-readiness/v1"
    assert payload["captured_at"] == "2026-07-01T12:10:00+08:00"
    assert payload["summary"] == {
        "source_contract_item_count": 6,
        "dispatch_recommended_item_count": 6,
        "authorization_request_count": 2,
        "metadata_release_monitor_count": 1,
        "public_api_contract_review_count": 3,
    }
    assert [group["gate"] for group in payload["groups"]] == [
        "authorization_request",
        "metadata_release_monitor",
        "public_api_contract_review",
    ]
    assert [group["item_count"] for group in payload["groups"]] == [2, 1, 3]

    first = payload["items"][0]
    assert first["gate"] in {
        "authorization_request",
        "metadata_release_monitor",
        "public_api_contract_review",
    }
    assert first["dispatch_recommended"] is True
    assert first["dispatch_reasons"] == [
        "source_contract_completion_evidence_missing",
        "official_request_or_release_followup_required",
    ]
    assert first["accepted_completion_statuses"] == [
        "accepted",
        "authorized",
        "contract_verified",
        "official_unavailable",
        "released",
    ]
    assert "--format source-contract-dispatch-evidence" in first["dispatch_command"]
    assert "--county" in first["dispatch_command"]
    assert "REPLACE_WITH_PRIVATE_DISPATCH_EVIDENCE_REF" in first["dispatch_command"]
    assert "private-ops://" not in json.dumps(payload, ensure_ascii=False)


def test_source_contract_dispatch_readiness_cli_writes_stdout_when_no_output() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--captured-at",
            "2026-07-01T12:10:00+08:00",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "local-source-contract-dispatch-readiness/v1"
    assert payload["summary"]["source_contract_item_count"] == 6
