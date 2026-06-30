from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "local-source-request-packets.py"
EXPECTED_PRODUCTION_OPERATIONAL_REQUIREMENTS = [
    "freshness_policy",
    "raw_snapshot_retention_policy",
    "monitored_scheduler_cadence",
    "hosted_egress_review",
    "worker_persisted_evidence_path",
]


def test_local_source_request_packets_cli_emits_json() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--format", "json"],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert [packet["county"] for packet in payload[:6]] == [
        "連江縣",
        "金門縣",
        "花蓮縣",
        "臺東縣",
        "苗栗縣",
        "屏東縣",
    ]
    assert {packet["county"] for packet in payload} >= {
        "苗栗縣",
        "屏東縣",
        "嘉義市",
    }
    assert payload[0]["packet_type"] == "metadata_release_request"
    assert payload[0]["target_signal_types"] == [
        "flood_depth",
        "sewer_water_level",
        "pump_or_gate_status",
    ]
    assert payload[0]["non_qualifying_source_names"] == [
        "連江自來水廠水庫水位月報",
        "連江縣資訊公開查詢系統即時監測值",
    ]
    assert (
        payload[0]["production_operational_requirements"]
        == EXPECTED_PRODUCTION_OPERATIONAL_REQUIREMENTS
    )
    chiayi_city = next(packet for packet in payload if packet["county"] == "嘉義市")
    assert chiayi_city["packet_type"] == "signal_gap_request"
    assert chiayi_city["target_signal_types"] == [
        "flood_depth",
        "sewer_water_level",
        "pump_or_gate_status",
    ]
    yunlin = next(packet for packet in payload if packet["county"] == "雲林縣")
    assert yunlin["packet_type"] == "signal_gap_request"
    assert yunlin["status_only_source_names"] == ["雲林 iflood 淹水感測狀態"]
    assert yunlin["target_signal_types"] == ["flood_depth"]
    pingtung = next(packet for packet in payload if packet["county"] == "屏東縣")
    assert pingtung["candidate_contract_missing_fields"] == [
        "observed_at",
        "longitude_latitude_or_joinable_station_metadata",
    ]
    assert "not_flood_depth_measurement" in " ".join(
        pingtung["candidate_contract_non_measurement_notes"]
    )


def test_local_source_request_packets_cli_filters_by_signal_type() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--format",
            "json",
            "--signal-type",
            "pump_or_gate_status",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    counties = [packet["county"] for packet in payload]

    assert len(payload) == 14
    assert "\u91d1\u9580\u7e23" in counties
    assert "\u96f2\u6797\u7e23" not in counties
    assert all(
        "pump_or_gate_status" in packet["target_signal_types"]
        for packet in payload
    )


def test_local_source_request_packets_cli_emits_signal_gap_batches_json() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--format",
            "signal-gap-batches-json",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert [batch["target_signal_type"] for batch in payload] == [
        "pump_or_gate_status",
        "flood_depth",
        "sewer_water_level",
    ]
    pump_batch = payload[0]
    assert pump_batch["batch_id"] == "signal-gap-batch/pump_or_gate_status"
    assert pump_batch["dispatch_status"] == "not_sent"
    assert pump_batch["sent_at"] is None
    assert pump_batch["follow_up_due_at"] is None
    assert pump_batch["official_reply_ref"] is None
    assert pump_batch["county_count"] == 14
    assert "\u91d1\u9580\u7e23" in pump_batch["counties"]
    assert pump_batch["private_evidence_ref_hint"] == (
        "private-ops://local-source/signal-gap-batch/pump_or_gate_status"
    )
    assert pump_batch["completion_evidence_targets"][0] == {
        "manifest_section": "signal_family_gap_evidence",
        "county": "\u9023\u6c5f\u7e23",
        "signal_type": "pump_or_gate_status",
        "accepted_statuses": [
            "accepted",
            "authorization_gated_adapter",
            "official_unavailable",
            "production_adapter",
        ],
        "evidence_ref_required": True,
        "private_evidence_ref_hint": (
            "private-ops://local-source/signal-gap/"
            "\u9023\u6c5f\u7e23/pump_or_gate_status"
        ),
    }
    assert len(pump_batch["completion_evidence_targets"]) == 14


def test_local_source_request_packets_cli_emits_signal_gap_batches_markdown() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--format",
            "signal-gap-batches-markdown",
            "--signal-type",
            "flood_depth",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    markdown = result.stdout
    assert "# Signal Gap Official Request Batches" in markdown
    assert "## flood_depth" in markdown
    assert "- Batch id: `signal-gap-batch/flood_depth`" in markdown
    assert "- Dispatch status: `not_sent`" in markdown
    assert "- County count: 5" in markdown
    assert "`private-ops://local-source/signal-gap-batch/flood_depth`" in markdown
    assert "Completion evidence targets" in markdown
    assert "signal_family_gap_evidence / flood_depth" in markdown
    assert "pump_or_gate_status" not in markdown


def test_local_source_request_packets_cli_emits_signal_gap_dispatch_evidence() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--format",
            "signal-gap-dispatch-evidence",
            "--signal-type",
            "flood_depth",
            "--dispatch-evidence-ref",
            "private-ops://local-source/dispatch/flood-depth-2026-06-30",
            "--dispatched-at",
            "2026-06-30T15:20:00+08:00",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["schema_version"] == "local-source-completion-evidence/v1"
    assert payload["captured_at"] == "2026-06-30T15:20:00+08:00"
    assert payload["source_contract_evidence"] == []
    assert payload["production_gate_evidence"] == []
    assert len(payload["signal_family_gap_evidence"]) == 5
    first = payload["signal_family_gap_evidence"][0]
    assert first == {
        "county": "\u9023\u6c5f\u7e23",
        "signal_type": "flood_depth",
        "status": "request_dispatched",
        "accepted_statuses": [
            "accepted",
            "authorization_gated_adapter",
            "official_unavailable",
            "production_adapter",
        ],
        "evidence_ref": (
            "private-ops://local-source/dispatch/flood-depth-2026-06-30"
        ),
        "dispatched_at": "2026-06-30T15:20:00+08:00",
    }


def test_local_source_request_packets_cli_emits_completion_evidence_template() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--format",
            "evidence-template",
            "--county",
            "\u91d1\u9580\u7e23",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["schema_version"] == "local-source-completion-evidence/v1"
    assert payload["captured_at"] == "REPLACE_WITH_CAPTURED_AT"
    assert payload["signal_family_gap_evidence"] == [
        {
            "county": "\u91d1\u9580\u7e23",
            "signal_type": "pump_or_gate_status",
            "status": "pending",
            "accepted_statuses": [
                "accepted",
                "authorization_gated_adapter",
                "official_unavailable",
                "production_adapter",
            ],
            "evidence_ref": (
                "private-ops://local-source/signal-gap/"
                "\u91d1\u9580\u7e23/pump_or_gate_status"
            ),
        }
    ]
    assert payload["production_gate_evidence"] == []
    assert payload["source_contract_evidence"] == [
        {
            "county": "\u91d1\u9580\u7e23",
            "gate": "authorization_request",
            "status": "pending",
            "accepted_statuses": [
                "accepted",
                "authorized",
                "contract_verified",
                "official_unavailable",
                "released",
            ],
            "evidence_ref": (
                "private-ops://local-source/source-contract/"
                "\u91d1\u9580\u7e23/authorization_request"
            ),
        }
    ]


def test_local_source_request_packets_cli_writes_markdown_output(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "request-packets.md"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--format",
            "markdown",
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
    assert str(output_path) in result.stderr
    markdown = output_path.read_text(encoding="utf-8")
    assert "## 花蓮縣：花蓮縣 Senslink/行動水情 即時水情 read API 授權請求" in markdown
    assert "## 金門縣：金門縣 KWIS 即時水情 read API 授權請求" in markdown
    assert "## 連江縣：連江縣地方即時水情資料釋出請求" in markdown
    assert "## 屏東縣：屏東縣地方即時水情 read API contract 請求" in markdown
    assert "## 臺北市：臺北市缺漏水資訊訊號補齊請求" in markdown
    assert "## 嘉義市：嘉義市缺漏水資訊訊號補齊請求" in markdown
    assert "## 雲林縣：雲林縣缺漏水資訊訊號補齊請求" in markdown
    assert "- 已排除官方線索：連江自來水廠水庫水位月報、連江縣資訊公開查詢系統即時監測值" in markdown
    assert "- 待補地方直連訊號：flood_depth、sewer_water_level、pump_or_gate_status" in markdown
    assert "- 待補水資訊訊號：flood_depth、sewer_water_level、pump_or_gate_status" in markdown
    assert "- 既有 status-only 來源：臺北市水門啟閉狀態" in markdown
    assert "- 既有 status-only 來源：雲林 iflood 淹水感測狀態" in markdown
    assert "- 候選系統缺少欄位：`observed_at`、`longitude_latitude_or_joinable_station_metadata`" in markdown
    assert "not_flood_depth_measurement" in markdown
    assert "- Production ops gates: freshness_policy, raw_snapshot_retention_policy, monitored_scheduler_cadence, hosted_egress_review, worker_persisted_evidence_path" in markdown
    assert "worker-persisted evidence" in markdown
