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
    request_queue_path = tmp_path / "request-dispatch-queue.json"
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
    request_queue_path.write_text(
        json.dumps(
            {
                "schema_version": "local-source-request-dispatch-queue/v1",
                "captured_at": "2026-07-01T03:12:00Z",
                "summary": {
                    "dispatch_queue_item_count": 9,
                    "signal_gap_dispatch_queue_item_count": 3,
                    "source_contract_dispatch_queue_item_count": 6,
                    "signal_gap_completion_target_count": 17,
                    "source_contract_completion_target_count": 6,
                },
                "items": [
                    {
                        "rank": 1,
                        "queue_id": "signal-gap-batch/pump_or_gate_status",
                        "request_type": "signal_gap_batch_request",
                        "status": "needs_dispatch",
                        "completion_gate": "required_signal_families",
                        "target_signal_type": "pump_or_gate_status",
                        "completion_target_count": 13,
                        "county_count": 13,
                        "requested_counterparties": [
                            "Flood control office batch",
                        ],
                        "tracking_statuses": [
                            "needs_signal_gap_review",
                        ],
                        "completion_gate_requirement": "latest-observation read API or official unavailable record required",
                        "required_read_api_fields": [
                            "observed_at",
                            "station_or_device_id",
                        ],
                        "accepted_completion_statuses": [
                            "accepted",
                            "official_unavailable",
                        ],
                    },
                    {
                        "rank": 4,
                        "queue_id": "source-contract/authorization_request/kinmen",
                        "request_type": "source_contract_request",
                        "status": "needs_dispatch",
                        "completion_gate": "official_authorization_and_contracts",
                        "source_contract_gate": "authorization_request",
                        "county": "kinmen",
                        "completion_target_count": 1,
                        "requested_counterparties": [
                            "Kinmen KWIS operator",
                        ],
                        "tracking_statuses": [
                            "needs_authorization_request",
                        ],
                        "required_read_api_fields": [
                            "observed_at",
                            "measurement_value",
                        ],
                        "accepted_completion_statuses": [
                            "authorized",
                            "official_unavailable",
                        ],
                    },
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
            "--request-dispatch-queue-json",
            str(request_queue_path),
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
        "request_dispatch_queue_item_count": 9,
        "request_dispatch_queue_signal_gap_item_count": 3,
        "request_dispatch_queue_source_contract_item_count": 6,
    }
    assert payload["next_workstreams"] == [
        "send_official_read_api_requests",
        "resolve_authorization_gated_adapters",
    ]
    assert payload["operator_next_steps"] == [
        (
            "Review the uploaded local-source request packet bundle before sending "
            "official requests."
        ),
        (
            "Send signal-family read API requests for 3 unresolved groups: "
            "pump_or_gate_status."
        ),
        (
            "Send source-contract follow-up for 6 items across authorization, "
            "metadata release, and public API contract review gates."
        ),
        (
            "After dispatch, generate private dispatch evidence and store it in "
            "LOCAL_SOURCE_REQUEST_DISPATCH_EVIDENCE_B64 only after review."
        ),
        (
            "Do not mark completion until accepted official reply, production "
            "adapter, authorization-gated adapter, or official-unavailable evidence "
            "is recorded."
        ),
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
    assert payload["request_dispatch_queue_items"] == [
        {
            "rank": 1,
            "queue_id": "signal-gap-batch/pump_or_gate_status",
            "request_type": "signal_gap_batch_request",
            "completion_gate": "required_signal_families",
            "target_signal_type": "pump_or_gate_status",
            "source_contract_gate": "",
            "county": "",
            "status": "needs_dispatch",
            "completion_target_count": 13,
            "county_count": 13,
            "completion_gate_requirement": (
                "latest-observation read API or official unavailable record required"
            ),
            "required_read_api_fields": [
                "observed_at",
                "station_or_device_id",
            ],
            "accepted_completion_statuses": [
                "accepted",
                "official_unavailable",
            ],
            "requested_counterparty": "Flood control office batch",
            "requested_counterparties": [
                "Flood control office batch",
            ],
            "tracking_status": "needs_signal_gap_review",
            "tracking_statuses": [
                "needs_signal_gap_review",
            ],
        },
        {
            "rank": 4,
            "queue_id": "source-contract/authorization_request/kinmen",
            "request_type": "source_contract_request",
            "completion_gate": "official_authorization_and_contracts",
            "target_signal_type": "",
            "source_contract_gate": "authorization_request",
            "county": "kinmen",
            "status": "needs_dispatch",
            "completion_target_count": 1,
            "county_count": 0,
            "completion_gate_requirement": "",
            "required_read_api_fields": [
                "observed_at",
                "measurement_value",
            ],
            "accepted_completion_statuses": [
                "authorized",
                "official_unavailable",
            ],
            "requested_counterparty": "Kinmen KWIS operator",
            "requested_counterparties": [
                "Kinmen KWIS operator",
            ],
            "tracking_status": "needs_authorization_request",
            "tracking_statuses": [
                "needs_authorization_request",
            ],
        },
    ]
    assert "private-ops://" not in result.stdout
    assert "private-ops://" not in json.dumps(payload, ensure_ascii=False)
    assert "pump_or_gate_status" in markdown
    assert "Request Dispatch Queue" in markdown
    assert "signal-gap-batch/pump_or_gate_status" in markdown
    assert "required fields: `observed_at`, `station_or_device_id`" in markdown
    assert "accepted statuses: `accepted`, `official_unavailable`" in markdown
    assert "Flood control office batch" in markdown
    assert "Kinmen KWIS operator" in markdown
    assert "Operator Next Steps" in markdown
    assert "LOCAL_SOURCE_REQUEST_DISPATCH_EVIDENCE_B64" in markdown
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
