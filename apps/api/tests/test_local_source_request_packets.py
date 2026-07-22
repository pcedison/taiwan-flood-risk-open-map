from __future__ import annotations

from app.ops.local_source.local_source_action_plan import (
    REQUIRED_REALTIME_READ_API_FIELDS,
    build_local_source_action_plan,
)
from app.ops.local_source.local_source_coverage import list_local_source_coverage
from app.ops.local_source.local_source_request_packets import (
    build_completion_evidence_template,
    build_official_request_packets,
    render_official_request_packets_markdown,
)

EXPECTED_PRODUCTION_OPERATIONAL_REQUIREMENTS = [
    "freshness_policy",
    "raw_snapshot_retention_policy",
    "monitored_scheduler_cadence",
    "hosted_egress_review",
    "worker_persisted_evidence_path",
]


def test_build_official_request_packets_turns_remaining_blockers_into_requests() -> None:
    plan = build_local_source_action_plan(list_local_source_coverage())

    packets = build_official_request_packets(plan)

    assert [packet["county"] for packet in packets[:6]] == [
        "連江縣",
        "金門縣",
        "花蓮縣",
        "臺東縣",
        "苗栗縣",
        "屏東縣",
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
    assert "是否可提供最新觀測 read API" in hualien["request_body"]
    assert "既有 read API methods" not in hualien["request_body"]

    kinmen = next(packet for packet in packets if packet["county"] == "金門縣")
    assert kinmen["packet_type"] == "authorization_request"
    assert kinmen["requires_human_intervention"] is True
    assert "金門縣 KWIS 即時水情 read API 授權請求" == kinmen["subject"]
    assert "不要將設備上傳 API 當作查詢 API" in kinmen["request_body"]
    assert "observed_at" in kinmen["required_read_api_fields"]
    assert any("kwis.kinmen.gov.tw" in url for url in kinmen["source_urls"])
    assert (
        kinmen["production_operational_requirements"]
        == EXPECTED_PRODUCTION_OPERATIONAL_REQUIREMENTS
    )
    assert "raw snapshot retention" in kinmen["request_body"]
    assert "scheduler cadence" in kinmen["request_body"]
    assert "hosted egress" in kinmen["request_body"]
    assert "worker-persisted evidence" in kinmen["request_body"]
    assert any("raw snapshot retention" in item for item in kinmen["checklist"])

    lienchiang = packets[0]
    assert lienchiang["packet_type"] == "metadata_release_request"
    assert lienchiang["requires_human_intervention"] is True
    assert "連江縣地方即時水情資料釋出請求" == lienchiang["subject"]
    assert lienchiang["target_signal_types"] == [
        "flood_depth",
        "sewer_water_level",
        "pump_or_gate_status",
    ]
    assert "南竿、北竿、莒光、東引" in lienchiang["request_body"]
    assert any("matsu.gov.tw" in url for url in lienchiang["source_urls"])
    assert lienchiang["non_qualifying_source_names"] == [
        "連江自來水廠水庫水位月報",
        "連江縣資訊公開查詢系統即時監測值",
    ]
    assert lienchiang["non_qualifying_source_urls"] == [
        "https://www.matsuwater.gov.tw/load_page/reservoir_water_level_page",
        "http://erbwater.matsu.gov.tw/PUBLIC/RealTime/Get_AVGR.aspx",
    ]
    assert "放流水環保 CEMS" in " ".join(lienchiang["non_qualifying_source_reasons"])
    assert "中央最低水文骨幹已補足" in lienchiang["request_body"]
    assert "地方直連訊號：flood_depth、sewer_water_level、pump_or_gate_status" in lienchiang[
        "request_body"
    ]
    assert (
        lienchiang["production_operational_requirements"]
        == EXPECTED_PRODUCTION_OPERATIONAL_REQUIREMENTS
    )

    miaoli = next(packet for packet in packets if packet["county"] == "\u82d7\u6817\u7e23")
    assert miaoli["packet_type"] == "public_api_contract_request"
    assert miaoli["tracking_status"] == "needs_public_read_api_contract"
    assert miaoli["candidate_contract_missing_fields"] == [
        "observed_at",
        "station_or_device_id",
        "measurement_value",
        "measurement_unit_or_type",
        "longitude_latitude_or_joinable_station_metadata",
    ]
    assert any(
        "58 water-level monitoring stations" in finding
        and "10 town/city urban-planning areas" in finding
        for finding in miaoli["candidate_contract_findings"]
    )
    assert any(
        "monthly reports track uptime" in finding
        for finding in miaoli["candidate_contract_findings"]
    )
    assert any(
        "HTML article/JPGs" in note and "cannot satisfy pump_or_gate_status" in note
        for note in miaoli["candidate_contract_non_measurement_notes"]
    )
    assert "58 water-level monitoring stations" in miaoli["request_body"]
    assert "HTML article/JPGs" in miaoli["request_body"]

    taitung = next(packet for packet in packets if packet["county"] == "\u81fa\u6771\u7e23")
    assert taitung["packet_type"] == "public_api_contract_request"
    assert taitung["tracking_status"] == "needs_public_read_api_contract"
    assert any("audit.gov.tw" in url for url in taitung["source_urls"])
    assert taitung["candidate_contract_missing_fields"] == [
        "observed_at",
        "station_or_device_id",
        "measurement_value",
        "measurement_unit_or_type",
        "longitude_latitude_or_joinable_station_metadata",
    ]
    assert any(
        "49 CWA rainfall stations" in finding
        and "9 WRA water-level stations" in finding
        for finding in taitung["candidate_contract_findings"]
    )
    assert any(
        "not a latest-observation read API" in note
        for note in taitung["candidate_contract_non_measurement_notes"]
    )
    assert "49 CWA rainfall stations" in taitung["request_body"]
    assert (
        taitung["production_operational_requirements"]
        == EXPECTED_PRODUCTION_OPERATIONAL_REQUIREMENTS
    )

    pingtung = next(packet for packet in packets if packet["county"] == "屏東縣")
    assert pingtung["packet_type"] == "public_api_contract_request"
    assert pingtung["requires_human_intervention"] is True
    assert pingtung["subject"] == "屏東縣地方即時水情 read API contract 請求"
    assert "pteoc.pthg.gov.tw/RainStation" in " ".join(pingtung["source_urls"])
    assert "observed_at" in pingtung["required_read_api_fields"]
    assert pingtung["candidate_contract_missing_fields"] == [
        "observed_at",
        "longitude_latitude_or_joinable_station_metadata",
    ]
    assert any(
        "RainStation/Details" in finding and "10分鐘雨量" in finding
        for finding in pingtung["candidate_contract_findings"]
    )
    assert any(
        "Flood/Details" in note and "not_flood_depth_measurement" in note
        for note in pingtung["candidate_contract_non_measurement_notes"]
    )
    assert any(
        "Crawler/Details" in note and "image_only_cctv" in note
        for note in pingtung["candidate_contract_non_measurement_notes"]
    )
    assert "不得以 fetched_at 偽裝觀測時間" in pingtung["request_body"]
    assert (
        pingtung["production_operational_requirements"]
        == EXPECTED_PRODUCTION_OPERATIONAL_REQUIREMENTS
    )

    taipei = next(packet for packet in packets if packet["county"] == "臺北市")
    assert taipei["packet_type"] == "signal_gap_request"
    assert taipei["tracking_status"] == "needs_signal_gap_review"
    assert taipei["target_signal_types"] == ["flood_depth"]
    assert taipei["status_only_signal_types"] == ["gate_status"]
    assert taipei["status_only_source_names"] == ["臺北市水門啟閉狀態"]
    assert "status-only" in taipei["request_body"]
    assert "不得替代水位、雨量、淹水深度或下水道水位量測" in taipei["request_body"]

    assert all(packet["county"] != "雲林縣" for packet in packets)
    assert all(packet["county"] != "臺南市" for packet in packets)

    chiayi_city = next(packet for packet in packets if packet["county"] == "嘉義市")
    assert chiayi_city["packet_type"] == "signal_gap_request"
    assert chiayi_city["tracking_status"] == "needs_signal_gap_review"
    assert chiayi_city["priority_tier"] == "P2"
    assert chiayi_city["target_signal_types"] == ["pump_or_gate_status"]
    assert "既有 production adapter 仍未覆蓋所有必要水資訊訊號" in chiayi_city["request_body"]
    assert "status-only" in chiayi_city["request_body"]
    assert (
        chiayi_city["production_operational_requirements"]
        == EXPECTED_PRODUCTION_OPERATIONAL_REQUIREMENTS
    )


def test_official_request_packets_can_filter_signal_gap_batch() -> None:
    plan = build_local_source_action_plan(list_local_source_coverage())
    top_gap = plan["signal_gap_priority_groups"][0]

    packets = build_official_request_packets(
        plan,
        counties=set(top_gap["counties"]),
        signal_types={top_gap["signal_type"]},
    )

    assert top_gap["signal_type"] == "pump_or_gate_status"
    assert [packet["county"] for packet in packets] == top_gap["counties"]
    assert len(packets) == top_gap["county_count"] == 13
    assert all(
        top_gap["signal_type"] in packet["target_signal_types"]
        for packet in packets
    )

    kinmen = next(packet for packet in packets if packet["county"] == "\u91d1\u9580\u7e23")
    assert kinmen["packet_type"] == "authorization_request"
    assert kinmen["target_signal_types"] == ["pump_or_gate_status"]


def test_official_request_packets_expose_completion_evidence_targets() -> None:
    plan = build_local_source_action_plan(list_local_source_coverage())

    packets = build_official_request_packets(plan)

    kinmen = next(packet for packet in packets if packet["county"] == "\u91d1\u9580\u7e23")
    lienchiang = next(packet for packet in packets if packet["county"] == "\u9023\u6c5f\u7e23")
    pingtung = next(packet for packet in packets if packet["county"] == "\u5c4f\u6771\u7e23")
    chiayi_city = next(packet for packet in packets if packet["county"] == "\u5609\u7fa9\u5e02")

    assert kinmen["completion_evidence_targets"] == [
        {
            "manifest_section": "source_contract_evidence",
            "county": "\u91d1\u9580\u7e23",
            "gate": "authorization_request",
            "accepted_statuses": [
                "accepted",
                "authorized",
                "contract_verified",
                "official_unavailable",
                "released",
            ],
            "evidence_ref_required": True,
            "private_evidence_ref_hint": (
                "private-ops://local-source/source-contract/"
                "\u91d1\u9580\u7e23/authorization_request"
            ),
        },
        {
            "manifest_section": "signal_family_gap_evidence",
            "county": "\u91d1\u9580\u7e23",
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
                "\u91d1\u9580\u7e23/pump_or_gate_status"
            ),
        },
    ]
    assert any(
        target.get("gate") == "metadata_release_monitor"
        for target in lienchiang["completion_evidence_targets"]
    )
    assert any(
        target.get("gate") == "public_api_contract_review"
        for target in pingtung["completion_evidence_targets"]
    )
    assert chiayi_city["completion_evidence_targets"] == [
        {
            "manifest_section": "signal_family_gap_evidence",
            "county": "\u5609\u7fa9\u5e02",
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
                "\u5609\u7fa9\u5e02/pump_or_gate_status"
            ),
        },
    ]


def test_completion_evidence_template_is_pending_draft_from_request_packets() -> None:
    plan = build_local_source_action_plan(list_local_source_coverage())
    packets = build_official_request_packets(plan)

    template = build_completion_evidence_template(
        packets,
        captured_at="2026-06-30T12:00:00+08:00",
    )

    assert template["schema_version"] == "local-source-completion-evidence/v1"
    assert template["captured_at"] == "2026-06-30T12:00:00+08:00"
    assert template["production_gate_evidence"] == []
    assert len(template["source_contract_evidence"]) == 6
    assert len(template["signal_family_gap_evidence"]) == 17

    kinmen = next(
        item
        for item in template["source_contract_evidence"]
        if item["county"] == "\u91d1\u9580\u7e23"
    )
    assert kinmen == {
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

    chiayi_pump_or_gate = next(
        item
        for item in template["signal_family_gap_evidence"]
        if item["county"] == "\u5609\u7fa9\u5e02"
        and item["signal_type"] == "pump_or_gate_status"
    )
    assert chiayi_pump_or_gate == {
        "county": "\u5609\u7fa9\u5e02",
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
            "\u5609\u7fa9\u5e02/pump_or_gate_status"
        ),
    }


def test_render_official_request_packets_markdown_is_ready_for_outreach() -> None:
    plan = build_local_source_action_plan(list_local_source_coverage())
    packets = build_official_request_packets(plan)

    markdown = render_official_request_packets_markdown(packets)

    assert markdown.startswith("# 地方即時水情官方請求包")
    assert "## 花蓮縣：花蓮縣 Senslink/行動水情 即時水情 read API 授權請求" in markdown
    assert "## 金門縣：金門縣 KWIS 即時水情 read API 授權請求" in markdown
    assert "## 連江縣：連江縣地方即時水情資料釋出請求" in markdown
    assert "## 屏東縣：屏東縣地方即時水情 read API contract 請求" in markdown
    assert "## 臺北市：臺北市缺漏水資訊訊號補齊請求" in markdown
    assert "## 嘉義市：嘉義市缺漏水資訊訊號補齊請求" in markdown
    assert "## 雲林縣：雲林縣缺漏水資訊訊號補齊請求" not in markdown
    assert "## 臺南市：臺南市缺漏水資訊訊號補齊請求" not in markdown
    assert "- 需要人工介入：是" in markdown
    assert "- 追蹤狀態：needs_public_read_api_contract" in markdown
    assert "- 追蹤狀態：needs_signal_gap_review" in markdown
    assert "- [ ] 確認是否可提供最新觀測 read API" in markdown
    assert "`observed_at`" in markdown
    assert "中央最低水文骨幹已補足" in markdown
    assert "- 待補地方直連訊號：flood_depth、sewer_water_level、pump_or_gate_status" in markdown
    assert "KWIS_Get_Pump_Basic_Unit_Data" in markdown
    assert "KWIS_IOT_Data_Service.asmx?WSDL" in markdown
    assert "(7)" in markdown
    assert "Data: []" in markdown
    assert "- 已排除官方線索：連江自來水廠水庫水位月報、連江縣資訊公開查詢系統即時監測值" in markdown
    assert "放流水環保 CEMS" in markdown
    assert "49 CWA rainfall stations" in markdown
    assert "9 WRA water-level stations" in markdown
    assert "not a latest-observation read API" in markdown
    assert "- 待補水資訊訊號：pump_or_gate_status" in markdown
    assert "- 既有 status-only 來源：臺北市水門啟閉狀態" in markdown
    assert "- 候選系統缺少欄位：`observed_at`、`longitude_latitude_or_joinable_station_metadata`" in markdown
    assert "58 water-level monitoring stations" in markdown
    assert "10 town/city urban-planning areas" in markdown
    assert "HTML article/JPGs" in markdown
    assert "not a sewer_water_level read API" in markdown
    assert "not_flood_depth_measurement" in markdown
    assert "image_only_cctv" in markdown
    assert "- Production ops gates: freshness_policy, raw_snapshot_retention_policy, monitored_scheduler_cadence, hosted_egress_review, worker_persisted_evidence_path" in markdown
    assert "raw snapshot retention" in markdown
    assert "scheduler cadence" in markdown
    assert "hosted egress" in markdown
    assert "worker-persisted evidence" in markdown
    assert "Completion evidence targets:" in markdown
    assert "source_contract_evidence / authorization_request" in markdown
    assert "source_contract_evidence / public_api_contract_review" in markdown
    assert "signal_family_gap_evidence / flood_depth" in markdown
    assert "private-ops://local-source/source-contract/" in markdown
    assert "private-ops://local-source/signal-gap/" in markdown


def test_lienchiang_packet_tracks_p0_local_direct_release_priority() -> None:
    plan = build_local_source_action_plan(list_local_source_coverage())
    top_priority = plan["integration_priority_queue"][0]

    packets = build_official_request_packets(plan)
    lienchiang = next(packet for packet in packets if packet["county"] == "連江縣")

    assert top_priority["county"] == "連江縣"
    assert lienchiang["priority_rank"] == top_priority["rank"] == 1
    assert lienchiang["priority_tier"] == "P0"
    assert lienchiang["workstream"] == "monitor_open_data_release"
    assert lienchiang["completion_gate"] == top_priority["completion_gate"]
    assert lienchiang["target_signal_types"] == [
        "flood_depth",
        "sewer_water_level",
        "pump_or_gate_status",
    ]
    assert lienchiang["non_qualifying_source_names"] == top_priority[
        "non_qualifying_source_names"
    ]
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
        == "token_gated_read_methods_require_authorization"
    )
    assert kinmen["insufficient_api_purposes"] == [
        "credentialed_read_api_without_authorized_token",
        "device_upload_api",
        "third_party_upload_integration",
    ]
    assert kinmen["required_api_purpose"] == "latest_observation_read_api"
    assert "upload-only" in kinmen["request_clarification"]
    assert "read API" in kinmen["request_clarification"]
    assert kinmen["credential_requirements"] == [
        "KWIS_key",
        "account",
        "password",
        "Token",
    ]
    assert kinmen["known_read_method_names"] == [
        "KWIS_Get_Rain_Gauge_Basic_Unit_Data",
        "KWIS_Get_Water_Level_Gauge_Basic_Unit_Data",
        "KWIS_Get_Flood_Sensing_Device_Basic_Unit_Data",
        "KWIS_Get_Pump_Basic_Unit_Data",
        "KWIS_Get_Monitoring_Station_Sensor_Device_List",
    ]
    assert any(
        "KWIS_IOT_Data_Service.asmx?WSDL" in url
        for url in kinmen["known_read_endpoint_urls"]
    )
    assert any(
        "KWIS_Get_Pump_Basic_Unit_Data" in url
        for url in kinmen["known_read_endpoint_urls"]
    )
    assert "(7)" in kinmen["unauthorized_smoke_result"]
    assert "Data: []" in kinmen["unauthorized_smoke_result"]


def test_tainan_no_longer_emits_signal_gap_packet_after_civil_iot_coverage() -> None:
    plan = build_local_source_action_plan(list_local_source_coverage())

    packets = build_official_request_packets(plan)

    assert all(packet["county"] != "\u81fa\u5357\u5e02" for packet in packets)


def test_rendered_packets_do_not_list_resolved_tainan_signal_gap_sources() -> None:
    plan = build_local_source_action_plan(list_local_source_coverage())
    packets = build_official_request_packets(plan)

    markdown = render_official_request_packets_markdown(packets)

    assert "\u81fa\u5357\u5e02\u7ba1\u5340\u57df\u6392\u6c34\u4e4b\u6c34\u4f4d\u7ad9\u540d\u7a31\u53ca\u4f4d\u7f6e" not in markdown
    assert "https://soa.tainan.gov.tw/Api/Service/Get/6c525fc0-f70a-433e-8529-8e11e65e85e9" not in markdown
    assert "\u81fa\u5357\u5e02\u7ba1\u5340\u57df\u6392\u6c34\u5373\u6642\u5f71\u50cf" not in markdown
