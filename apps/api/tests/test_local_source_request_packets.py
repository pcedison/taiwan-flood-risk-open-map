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

    assert [packet["county"] for packet in packets] == [
        "花蓮縣",
        "金門縣",
        "連江縣",
        "苗栗縣",
        "屏東縣",
        "臺東縣",
    ]
    hualien = packets[0]
    assert hualien["packet_type"] == "authorization_request"
    assert hualien["subject"] == "花蓮縣 Senslink/行動水情 即時水情 read API 授權請求"
    assert hualien["requested_counterparty"] == "花蓮縣政府 / Senslink 行動水情維運窗口"

    kinmen = packets[1]
    assert kinmen["packet_type"] == "authorization_request"
    assert kinmen["requires_human_intervention"] is True
    assert "金門縣 KWIS 即時水情 read API 授權請求" == kinmen["subject"]
    assert "不是設備上傳 API" in kinmen["request_body"]
    assert "observed_at" in kinmen["required_read_api_fields"]
    assert any("kwis.kinmen.gov.tw" in url for url in kinmen["source_urls"])

    lienchiang = packets[2]
    assert lienchiang["packet_type"] == "metadata_release_request"
    assert lienchiang["requires_human_intervention"] is True
    assert "連江縣即時水文觀測資料釋出請求" == lienchiang["subject"]
    assert lienchiang["target_signal_types"] == ["hydrologic_observation"]
    assert "南竿、北竿、莒光、東引" in lienchiang["request_body"]
    assert any("matsu.gov.tw" in url for url in lienchiang["source_urls"])

    pingtung = packets[4]
    assert pingtung["packet_type"] == "public_api_contract_request"
    assert pingtung["requires_human_intervention"] is True
    assert pingtung["subject"] == "屏東縣地方即時水情 read API contract 請求"
    assert "pteoc.pthg.gov.tw/RainStation" in " ".join(pingtung["source_urls"])
    assert "observed_at" in pingtung["required_read_api_fields"]


def test_render_official_request_packets_markdown_is_ready_for_outreach() -> None:
    plan = build_local_source_action_plan(list_local_source_coverage())
    packets = build_official_request_packets(plan)

    markdown = render_official_request_packets_markdown(packets)

    assert markdown.startswith("# 地方即時水情官方請求包")
    assert "## 花蓮縣：花蓮縣 Senslink/行動水情 即時水情 read API 授權請求" in markdown
    assert "## 金門縣：金門縣 KWIS 即時水情 read API 授權請求" in markdown
    assert "## 連江縣：連江縣即時水文觀測資料釋出請求" in markdown
    assert "## 屏東縣：屏東縣地方即時水情 read API contract 請求" in markdown
    assert "- 需要人工介入：是" in markdown
    assert "- 追蹤狀態：needs_public_read_api_contract" in markdown
    assert "- [ ] 確認是否可提供最新觀測 read API" in markdown
    assert "`observed_at`" in markdown
    assert "hydrologic_observation" in markdown


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
