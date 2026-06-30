from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
API_APP = REPO_ROOT / "apps" / "api"
SCRIPT = REPO_ROOT / "scripts" / "local-source-completion-audit.py"
sys.path.insert(0, str(API_APP))

from app.domain.realtime.local_source_action_plan import (  # noqa: E402
    PRODUCTION_GATE_REQUIRED_REQUIREMENTS,
    build_local_source_action_plan,
)
from app.domain.realtime.local_source_coverage import (  # noqa: E402
    list_local_source_coverage,
)


def test_local_source_completion_audit_cli_reports_incomplete_by_default() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["overall_status"] == "incomplete"
    assert payload["summary"]["signal_gap_county_item_count"] == 24


def test_local_source_completion_audit_cli_accepts_completion_evidence(
    tmp_path: Path,
) -> None:
    baseline = build_local_source_action_plan(list_local_source_coverage())
    evidence_path = tmp_path / "local-source-completion-evidence.json"
    evidence_path.write_text(
        json.dumps(_complete_evidence_overlay(baseline), ensure_ascii=False),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--completion-evidence-json",
            str(evidence_path),
            "--fail-on-incomplete",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    gates = {gate["gate_key"]: gate for gate in payload["gates"]}

    assert payload["overall_status"] == "satisfied"
    assert payload["next_priority_workstreams"] == []
    assert gates["required_signal_families"]["status"] == "satisfied"
    assert gates["official_authorization_and_contracts"]["status"] == "satisfied"
    assert gates["hosted_worker_persisted_evidence"]["status"] == "satisfied"


def _complete_evidence_overlay(plan: dict) -> dict:
    return {
        "schema_version": "local-source-completion-evidence/v1",
        "captured_at": "2026-06-30T12:00:00+08:00",
        "signal_family_gap_evidence": [
            {
                "county": county,
                "signal_type": group["signal_type"],
                "status": "official_unavailable",
                "evidence_ref": (
                    f"private-ops://local-source/{county}/{group['signal_type']}"
                ),
            }
            for group in plan["signal_gap_priority_groups"]
            for county in group["counties"]
        ],
        "source_contract_evidence": [
            *_source_contract_evidence(
                plan["authorization_requests"],
                gate="authorization_request",
            ),
            *_source_contract_evidence(
                plan["metadata_release_monitors"],
                gate="metadata_release_monitor",
            ),
            *_source_contract_evidence(
                plan["public_api_contract_reviews"],
                gate="public_api_contract_review",
            ),
        ],
        "production_gate_evidence": [
            {
                "gate_key": "hosted_worker_persisted_evidence",
                "status": "accepted",
                "evidence_ref": "private-ops://zeabur/worker-persisted-evidence",
                "satisfied_requirements": list(
                    PRODUCTION_GATE_REQUIRED_REQUIREMENTS[
                        "hosted_worker_persisted_evidence"
                    ]
                ),
            },
            {
                "gate_key": "production_monitoring_and_alerting",
                "status": "accepted",
                "evidence_ref": "private-ops://zeabur/alert-routing",
                "satisfied_requirements": list(
                    PRODUCTION_GATE_REQUIRED_REQUIREMENTS[
                        "production_monitoring_and_alerting"
                    ]
                ),
            },
            {
                "gate_key": "public_risk_worker_evidence_path",
                "status": "accepted",
                "evidence_ref": "private-ops://zeabur/public-risk-smoke",
                "satisfied_requirements": list(
                    PRODUCTION_GATE_REQUIRED_REQUIREMENTS[
                        "public_risk_worker_evidence_path"
                    ]
                ),
            },
        ],
    }


def _source_contract_evidence(items: list[dict], *, gate: str) -> list[dict]:
    return [
        {
            "county": item["county"],
            "gate": gate,
            "status": "accepted",
            "evidence_ref": f"private-ops://local-source/{gate}/{item['county']}",
        }
        for item in items
    ]
