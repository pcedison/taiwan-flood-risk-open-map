from __future__ import annotations

from app.domain.realtime.local_source_action_plan import build_local_source_action_plan
from app.domain.realtime.local_source_coverage import list_local_source_coverage
from app.domain.realtime.local_source_request_packets import (
    build_official_request_packets,
    render_official_request_packets_markdown,
)


def test_build_official_request_packets_turns_remaining_blockers_into_requests() -> None:
    plan = build_local_source_action_plan(list_local_source_coverage())

    packets = build_official_request_packets(plan)

    assert [packet["county"] for packet in packets] == ["金門縣", "連江縣"]
    kinmen = packets[0]
    assert kinmen["packet_type"] == "authorization_request"
    assert kinmen["requires_human_intervention"] is True
    assert "金門縣 KWIS 即時水情 read API 授權請求" == kinmen["subject"]
    assert "不是設備上傳 API" in kinmen["request_body"]
    assert "observed_at" in kinmen["required_read_api_fields"]
    assert any("kwis.kinmen.gov.tw" in url for url in kinmen["source_urls"])

    lienchiang = packets[1]
    assert lienchiang["packet_type"] == "metadata_release_request"
    assert lienchiang["requires_human_intervention"] is True
    assert "連江縣即時水文觀測資料釋出請求" == lienchiang["subject"]
    assert lienchiang["target_signal_types"] == ["hydrologic_observation"]
    assert "南竿、北竿、莒光、東引" in lienchiang["request_body"]
    assert any("matsu.gov.tw" in url for url in lienchiang["source_urls"])


def test_render_official_request_packets_markdown_is_ready_for_outreach() -> None:
    plan = build_local_source_action_plan(list_local_source_coverage())
    packets = build_official_request_packets(plan)

    markdown = render_official_request_packets_markdown(packets)

    assert markdown.startswith("# 地方即時水情官方請求包")
    assert "## 金門縣：金門縣 KWIS 即時水情 read API 授權請求" in markdown
    assert "## 連江縣：連江縣即時水文觀測資料釋出請求" in markdown
    assert "- 需要人工介入：是" in markdown
    assert "- [ ] 確認是否可提供最新觀測 read API" in markdown
    assert "`observed_at`" in markdown
    assert "hydrologic_observation" in markdown
