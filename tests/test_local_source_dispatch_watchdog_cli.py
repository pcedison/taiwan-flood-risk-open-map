from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "local-source-dispatch-watchdog.py"


def test_local_source_dispatch_watchdog_cli_fails_when_dispatch_required(
    tmp_path: Path,
) -> None:
    signal_gap_path = tmp_path / "signal-gap-dispatch-readiness.json"
    source_contract_path = tmp_path / "source-contract-dispatch-readiness.json"
    output_path = tmp_path / "dispatch-watchdog.json"
    markdown_path = tmp_path / "dispatch-watchdog.md"
    signal_gap_path.write_text(
        json.dumps(
            {
                "schema_version": "local-source-signal-gap-dispatch-readiness/v1",
                "captured_at": "2026-07-01T03:10:00Z",
                "summary": {
                    "signal_gap_group_count": 3,
                    "dispatch_recommended_group_count": 3,
                    "total_candidate_count": 11,
                    "total_metadata_only_count": 11,
                    "total_candidate_live_read_api_count": 0,
                },
                "groups": [
                    {
                        "target_signal_type": "pump_or_gate_status",
                        "county_count": 13,
                        "dispatch_recommended": True,
                        "dispatch_reasons": [
                            "no_live_read_api_candidate",
                            "metadata_only_candidates_require_contract_followup",
                        ],
                        "discovery": {
                            "metadata_only_count": 9,
                            "candidate_live_read_api_count": 0,
                            "metadata_only_counties": ["新北市", "桃園市", "臺中市"],
                            "counties_without_candidates": ["連江縣", "金門縣"],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    source_contract_path.write_text(
        json.dumps(
            {
                "schema_version": "local-source-contract-dispatch-readiness/v1",
                "captured_at": "2026-07-01T03:11:00Z",
                "summary": {
                    "source_contract_item_count": 6,
                    "dispatch_recommended_item_count": 6,
                    "authorization_request_count": 2,
                    "metadata_release_monitor_count": 1,
                    "public_api_contract_review_count": 3,
                },
                "groups": [
                    {
                        "gate": "authorization_request",
                        "item_count": 2,
                        "dispatch_recommended": True,
                    }
                ],
                "items": [
                    {
                        "county": "金門縣",
                        "gate": "authorization_request",
                        "packet_type": "authorization_request",
                        "tracking_status": "needs_authorization_request",
                        "target_signal_types": ["pump_or_gate_status"],
                        "dispatch_recommended": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--signal-gap-dispatch-readiness-json",
            str(signal_gap_path),
            "--source-contract-dispatch-readiness-json",
            str(source_contract_path),
            "--captured-at",
            "2026-07-01T12:30:00+08:00",
            "--output",
            str(output_path),
            "--markdown-output",
            str(markdown_path),
            "--fail-on-dispatch-required",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 1
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")

    assert payload["schema_version"] == "local-source-dispatch-watchdog/v1"
    assert payload["status"] == "dispatch_required"
    assert payload["summary"] == {
        "dispatch_required": True,
        "signal_gap_dispatch_recommended_group_count": 3,
        "signal_gap_county_item_count": 13,
        "signal_gap_total_metadata_only_count": 11,
        "signal_gap_total_live_read_api_candidate_count": 0,
        "source_contract_dispatch_recommended_item_count": 6,
        "source_contract_item_count": 6,
        "authorization_request_count": 2,
        "metadata_release_monitor_count": 1,
        "public_api_contract_review_count": 3,
    }
    assert payload["next_workstreams"] == [
        "send_official_read_api_requests",
        "resolve_authorization_gated_adapters",
    ]
    assert payload["signal_gap_groups"][0]["target_signal_type"] == (
        "pump_or_gate_status"
    )
    assert payload["source_contract_items"][0] == {
        "county": "金門縣",
        "gate": "authorization_request",
        "packet_type": "authorization_request",
        "tracking_status": "needs_authorization_request",
        "target_signal_types": ["pump_or_gate_status"],
    }
    assert "private-ops://" not in result.stdout
    assert "private-ops://" not in json.dumps(payload, ensure_ascii=False)
    assert "pump_or_gate_status" in markdown
    assert "official request" in markdown


def test_local_source_dispatch_watchdog_cli_rejects_wrong_schema(
    tmp_path: Path,
) -> None:
    signal_gap_path = tmp_path / "signal-gap-dispatch-readiness.json"
    source_contract_path = tmp_path / "source-contract-dispatch-readiness.json"
    signal_gap_path.write_text(json.dumps({"schema_version": "wrong/v1"}))
    source_contract_path.write_text(
        json.dumps(
            {
                "schema_version": "local-source-contract-dispatch-readiness/v1",
                "summary": {},
                "groups": [],
                "items": [],
            }
        )
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--signal-gap-dispatch-readiness-json",
            str(signal_gap_path),
            "--source-contract-dispatch-readiness-json",
            str(source_contract_path),
            "--captured-at",
            "2026-07-01T12:30:00+08:00",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "schema_version" in result.stderr
