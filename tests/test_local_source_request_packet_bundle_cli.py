from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "local-source-request-packet-bundle.py"


def test_local_source_request_packet_bundle_cli_writes_operator_bundle(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "bundle"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--captured-at",
            "2026-07-01T15:40:00+08:00",
            "--output-dir",
            str(output_dir),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""

    expected_files = {
        "local-source-request-packet-bundle-manifest.json",
        "local-source-request-packet-bundle.md",
        "local-source-official-request-packets.json",
        "local-source-official-request-packets.md",
        "local-source-official-request-completion-template.json",
        "local-source-signal-gap-request-batches.json",
        "local-source-signal-gap-request-batches.md",
        "local-source-signal-gap-dispatch-template.json",
        "local-source-source-contract-dispatch-template.json",
        "local-source-request-dispatch-evidence-draft.json",
        "local-source-dispatch-coverage-checklist.json",
        "local-source-request-dispatch-queue.json",
    }
    assert {path.name for path in output_dir.iterdir()} == expected_files

    manifest = json.loads(
        (output_dir / "local-source-request-packet-bundle-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["schema_version"] == "local-source-request-packet-bundle/v1"
    assert manifest["captured_at"] == "2026-07-01T15:40:00+08:00"
    assert manifest["summary"] == {
        "official_request_packet_count": 16,
        "official_completion_target_count": 23,
        "signal_gap_batch_count": 3,
        "signal_gap_county_item_count": 17,
        "source_contract_completion_target_count": 6,
        "request_dispatch_evidence_draft_item_count": 23,
        "dispatch_queue_item_count": 9,
        "signal_gap_dispatch_queue_item_count": 3,
        "source_contract_dispatch_queue_item_count": 6,
    }
    assert manifest["remaining_completion_gates"] == [
        "required_signal_families",
        "official_authorization_and_contracts",
    ]
    assert [file["path"] for file in manifest["files"]] == sorted(expected_files)

    signal_dispatch_template = json.loads(
        (output_dir / "local-source-signal-gap-dispatch-template.json").read_text(
            encoding="utf-8"
        )
    )
    assert signal_dispatch_template["captured_at"] == "REPLACE_WITH_DISPATCHED_AT"
    assert len(signal_dispatch_template["signal_family_gap_evidence"]) == 17
    assert {
        item["evidence_ref"]
        for item in signal_dispatch_template["signal_family_gap_evidence"]
    } == {"REPLACE_WITH_PRIVATE_DISPATCH_EVIDENCE_REF"}

    source_contract_template = json.loads(
        (
            output_dir / "local-source-source-contract-dispatch-template.json"
        ).read_text(encoding="utf-8")
    )
    assert len(source_contract_template["source_contract_evidence"]) == 6
    assert {
        item["evidence_ref"]
        for item in source_contract_template["source_contract_evidence"]
    } == {"REPLACE_WITH_PRIVATE_DISPATCH_EVIDENCE_REF"}

    dispatch_evidence_draft = json.loads(
        (
            output_dir / "local-source-request-dispatch-evidence-draft.json"
        ).read_text(encoding="utf-8")
    )
    assert (
        dispatch_evidence_draft["schema_version"]
        == "local-source-completion-evidence/v1"
    )
    assert dispatch_evidence_draft["captured_at"] == "REPLACE_WITH_DISPATCHED_AT"
    assert len(dispatch_evidence_draft["signal_family_gap_evidence"]) == 17
    assert len(dispatch_evidence_draft["source_contract_evidence"]) == 6
    assert dispatch_evidence_draft["production_gate_evidence"] == []
    assert {
        item["status"]
        for item in dispatch_evidence_draft["signal_family_gap_evidence"]
    } == {"request_dispatched"}
    assert {
        item["status"]
        for item in dispatch_evidence_draft["source_contract_evidence"]
    } == {"request_dispatched"}
    assert {
        item["evidence_ref"]
        for item in dispatch_evidence_draft["signal_family_gap_evidence"]
    } == {"REPLACE_WITH_PRIVATE_DISPATCH_EVIDENCE_REF"}
    assert {
        item["evidence_ref"]
        for item in dispatch_evidence_draft["source_contract_evidence"]
    } == {"REPLACE_WITH_PRIVATE_DISPATCH_EVIDENCE_REF"}

    dispatch_checklist = json.loads(
        (
            output_dir / "local-source-dispatch-coverage-checklist.json"
        ).read_text(encoding="utf-8")
    )
    assert (
        dispatch_checklist["schema_version"]
        == "local-source-dispatch-coverage-checklist/v1"
    )
    assert dispatch_checklist["secret_name"] == (
        "LOCAL_SOURCE_REQUEST_DISPATCH_EVIDENCE_B64"
    )
    assert dispatch_checklist["summary"] == {
        "total_dispatch_item_count": 23,
        "signal_family_gap_dispatch_item_count": 17,
        "source_contract_dispatch_item_count": 6,
    }
    assert {
        item["completion_gate"]
        for item in dispatch_checklist["signal_family_gap_dispatch_items"]
    } == {"required_signal_families"}
    assert {
        item["completion_gate"]
        for item in dispatch_checklist["source_contract_dispatch_items"]
    } == {"official_authorization_and_contracts"}
    assert "private-ops://" not in json.dumps(
        dispatch_checklist,
        ensure_ascii=False,
    )

    dispatch_queue = json.loads(
        (output_dir / "local-source-request-dispatch-queue.json").read_text(
            encoding="utf-8"
        )
    )
    assert (
        dispatch_queue["schema_version"]
        == "local-source-request-dispatch-queue/v1"
    )
    assert dispatch_queue["captured_at"] == "2026-07-01T15:40:00+08:00"
    assert dispatch_queue["secret_name"] == (
        "LOCAL_SOURCE_REQUEST_DISPATCH_EVIDENCE_B64"
    )
    assert dispatch_queue["summary"] == {
        "dispatch_queue_item_count": 9,
        "signal_gap_dispatch_queue_item_count": 3,
        "source_contract_dispatch_queue_item_count": 6,
        "signal_gap_completion_target_count": 17,
        "source_contract_completion_target_count": 6,
    }
    assert [item["queue_id"] for item in dispatch_queue["items"][:3]] == [
        "signal-gap-batch/pump_or_gate_status",
        "signal-gap-batch/flood_depth",
        "signal-gap-batch/sewer_water_level",
    ]
    first_signal_item = dispatch_queue["items"][0]
    assert first_signal_item["request_type"] == "signal_gap_batch_request"
    assert first_signal_item["completion_gate"] == "required_signal_families"
    assert first_signal_item["target_signal_type"] == "pump_or_gate_status"
    assert first_signal_item["completion_target_count"] == 13
    assert first_signal_item["status"] == "needs_dispatch"
    assert first_signal_item["private_dispatch_manifest_section"] == (
        "signal_family_gap_evidence"
    )
    assert {
        item["completion_gate"]
        for item in dispatch_queue["items"]
        if item["request_type"] == "source_contract_request"
    } == {"official_authorization_and_contracts"}
    assert {
        item["private_dispatch_manifest_section"]
        for item in dispatch_queue["items"]
        if item["request_type"] == "source_contract_request"
    } == {"source_contract_evidence"}
    assert "private-ops://" not in json.dumps(dispatch_queue, ensure_ascii=False)
    assert "REPLACE_WITH_PRIVATE_DISPATCH_EVIDENCE_REF" not in json.dumps(
        dispatch_queue,
        ensure_ascii=False,
    )

    summary_markdown = (
        output_dir / "local-source-request-packet-bundle.md"
    ).read_text(encoding="utf-8")
    assert "# Local Source Request Packet Bundle" in summary_markdown
    assert "official_request_packet_count: 16" in summary_markdown
    assert "signal_gap_county_item_count: 17" in summary_markdown
    assert "These templates are not completion evidence until placeholders are replaced" in (
        summary_markdown
    )
