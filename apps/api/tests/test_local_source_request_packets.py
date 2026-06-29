from __future__ import annotations

from app.domain.realtime.local_source_action_plan import (
    REQUIRED_REALTIME_READ_API_FIELDS,
    build_local_source_action_plan,
)
from app.domain.realtime.local_source_coverage import list_local_source_coverage
from app.domain.realtime.local_source_request_packets import (
    build_official_request_packets,
    render_official_request_packets_markdown,
)


def test_build_official_request_packets_turns_remaining_blockers_into_requests() -> None:
    plan = build_local_source_action_plan(list_local_source_coverage())

    packets = build_official_request_packets(plan)

    assert [packet["county"] for packet in packets[:6]] == [
        "連江縣",
        "金門縣",
        "花蓮縣",
        "臺北市",
        "臺東縣",
        "苗栗縣",
    ]
    assert {packet["county"] for packet in packets} >= {
        "苗栗縣",
        "屏東縣",
        "嘉義市",
    }
    hualien = next(packet for packet in packets if packet["county"] == "花蓮縣")
    assert hualien["packet_type"] == "authorization_request"
    assert hualien["subject"] == "花蓮縣 Senslink/行動水情 即時水情 read API 授權請求"
    assert hualien["requested_counterparty"] == "花蓮縣政府 / Senslink 行動水情維運窗口"

    kinmen = next(packet for packet in packets if packet["county"] == "金門縣")
    assert kinmen["packet_type"] == "authorization_request"
    assert kinmen["requires_human_intervention"] is True
    assert "金門縣 KWIS 即時水情 read API 授權請求" == kinmen["subject"]
    assert "不是設備上傳 API" in kinmen["request_body"]
    assert "observed_at" in kinmen["required_read_api_fields"]
    assert any("kwis.kinmen.gov.tw" in url for url in kinmen["source_urls"])

    lienchiang = packets[0]
    assert lienchiang["packet_type"] == "metadata_release_request"
    assert lienchiang["requires_human_intervention"] is True
    assert "連江縣即時水文觀測資料釋出請求" == lienchiang["subject"]
    assert lienchiang["target_signal_types"] == ["hydrologic_observation"]
    assert "南竿、北竿、莒光、東引" in lienchiang["request_body"]
    assert any("matsu.gov.tw" in url for url in lienchiang["source_urls"])

    pingtung = next(packet for packet in packets if packet["county"] == "屏東縣")
    assert pingtung["packet_type"] == "public_api_contract_request"
    assert pingtung["requires_human_intervention"] is True
    assert pingtung["subject"] == "屏東縣地方即時水情 read API contract 請求"
    assert "pteoc.pthg.gov.tw/RainStation" in " ".join(pingtung["source_urls"])
    assert "observed_at" in pingtung["required_read_api_fields"]

    taipei = next(packet for packet in packets if packet["county"] == "臺北市")
    assert taipei["packet_type"] == "live_smoke_review_request"
    assert taipei["tracking_status"] == "needs_live_smoke_retry"
    assert "狀態或開關資料不得替代水位、雨量或淹水深度" in taipei["request_body"]

    yunlin = next(packet for packet in packets if packet["county"] == "雲林縣")
    assert yunlin["packet_type"] == "signal_gap_request"
    assert yunlin["tracking_status"] == "needs_signal_gap_review"
    assert yunlin["target_signal_types"] == ["flood_depth"]
    assert yunlin["status_only_source_names"] == ["雲林 iflood 淹水感測狀態"]
    assert yunlin["status_only_signal_types"] == ["flood_sensor_status"]
    assert "status-only" in yunlin["request_body"]

    chiayi_city = next(packet for packet in packets if packet["county"] == "嘉義市")
    assert chiayi_city["packet_type"] == "signal_gap_request"
    assert chiayi_city["tracking_status"] == "needs_signal_gap_review"
    assert chiayi_city["priority_tier"] == "P2"
    assert chiayi_city["target_signal_types"] == [
        "flood_depth",
        "sewer_water_level",
        "pump_or_gate_status",
    ]
    assert "既有 production adapter 仍未覆蓋所有必要水資訊訊號" in chiayi_city["request_body"]
    assert "status-only" in chiayi_city["request_body"]


def test_render_official_request_packets_markdown_is_ready_for_outreach() -> None:
    plan = build_local_source_action_plan(list_local_source_coverage())
    packets = build_official_request_packets(plan)

    markdown = render_official_request_packets_markdown(packets)

    assert markdown.startswith("# 地方即時水情官方請求包")
    assert "## 花蓮縣：花蓮縣 Senslink/行動水情 即時水情 read API 授權請求" in markdown
    assert "## 金門縣：金門縣 KWIS 即時水情 read API 授權請求" in markdown
    assert "## 連江縣：連江縣即時水文觀測資料釋出請求" in markdown
    assert "## 屏東縣：屏東縣地方即時水情 read API contract 請求" in markdown
    assert "## 嘉義市：嘉義市缺漏水資訊訊號補齊請求" in markdown
    assert "## 雲林縣：雲林縣缺漏水資訊訊號補齊請求" in markdown
    assert "- 需要人工介入：是" in markdown
    assert "- 追蹤狀態：needs_public_read_api_contract" in markdown
    assert "- 追蹤狀態：needs_signal_gap_review" in markdown
    assert "- [ ] 確認是否可提供最新觀測 read API" in markdown
    assert "`observed_at`" in markdown
    assert "hydrologic_observation" in markdown
    assert "- 待補水資訊訊號：flood_depth、sewer_water_level、pump_or_gate_status" in markdown
    assert "- 既有 status-only 來源：雲林 iflood 淹水感測狀態" in markdown


def test_lienchiang_packet_tracks_p0_hydrologic_backbone_priority() -> None:
    plan = build_local_source_action_plan(list_local_source_coverage())
    top_priority = plan["integration_priority_queue"][0]

    packets = build_official_request_packets(plan)
    lienchiang = next(packet for packet in packets if packet["county"] == "連江縣")

    assert top_priority["county"] == "連江縣"
    assert lienchiang["priority_rank"] == top_priority["rank"] == 1
    assert lienchiang["priority_tier"] == "P0"
    assert lienchiang["workstream"] == "restore_hydrologic_backbone"
    assert lienchiang["completion_gate"] == top_priority["completion_gate"]
    assert lienchiang["target_signal_types"] == ["hydrologic_observation"]
    assert lienchiang["required_read_api_fields"] == list(
        REQUIRED_REALTIME_READ_API_FIELDS
    )


def test_kinmen_packet_marks_upload_api_as_insufficient_for_read_adapter() -> None:
    plan = build_local_source_action_plan(list_local_source_coverage())

    packets = build_official_request_packets(plan)
    kinmen = next(packet for packet in packets if packet["county"] == "金門縣")

    assert kinmen["priority_rank"] == 2
    assert kinmen["priority_tier"] == "P0"
    assert kinmen["workstream"] == "request_official_authorization"
    assert (
        kinmen["api_contract_risk"]
        == "known_public_docs_are_upload_or_application_focused"
    )
    assert kinmen["insufficient_api_purposes"] == [
        "device_upload_api",
        "third_party_upload_integration",
    ]
    assert kinmen["required_api_purpose"] == "latest_observation_read_api"
    assert "upload-only" in kinmen["request_clarification"]
    assert "read API" in kinmen["request_clarification"]
