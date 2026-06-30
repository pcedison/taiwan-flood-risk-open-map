from __future__ import annotations

from app.domain.realtime.local_source_action_plan import (
    REQUIRED_REALTIME_READ_API_FIELDS,
    build_local_source_action_plan,
)
from app.domain.realtime.local_source_coverage import list_local_source_coverage


def test_local_source_action_plan_exposes_remaining_authorization_and_release_work() -> None:
    plan = build_local_source_action_plan(list_local_source_coverage())

    assert plan["local_direct_complete_count"] == 20
    assert plan["local_direct_remaining_count"] == 2
    assert plan["central_backbone_minimum_complete_count"] == 22
    assert plan["central_backbone_remaining_count"] == 0

    authorization_by_county = {
        item["county"]: item for item in plan["authorization_requests"]
    }
    assert set(authorization_by_county) == {"花蓮縣", "金門縣"}
    assert "行動水情" in authorization_by_county["花蓮縣"]["reason"]
    assert (
        authorization_by_county["花蓮縣"]["requested_counterparty"]
        == "花蓮縣政府 / Senslink 行動水情維運窗口"
    )
    assert "KWIS" in authorization_by_county["金門縣"]["reason"]
    assert authorization_by_county["金門縣"]["authorization_gated_adapter_keys"] == [
        "local.kinmen.kwis_pump_station"
    ]
    assert authorization_by_county["金門縣"]["production_adapter_keys"] == []
    assert authorization_by_county["金門縣"]["required_read_api_fields"] == list(
        REQUIRED_REALTIME_READ_API_FIELDS
    )
    assert (
        authorization_by_county["金門縣"]["requested_counterparty"]
        == "金門縣政府 / KWIS 維運窗口"
    )
    assert (
        authorization_by_county["金門縣"]["tracking_status"]
        == "needs_authorization_request"
    )
    assert authorization_by_county["金門縣"]["last_followed_up_at"] is None

    metadata_release_by_county = {
        item["county"]: item for item in plan["metadata_release_monitors"]
    }
    assert set(metadata_release_by_county) == {"連江縣"}
    assert metadata_release_by_county["連江縣"]["central_backbone_missing_signal_types"] == []
    assert metadata_release_by_county["連江縣"]["missing_signal_types"] == [
        "flood_depth",
        "sewer_water_level",
        "pump_or_gate_status",
    ]
    assert "觀測" in metadata_release_by_county["連江縣"]["request_focus"]
    assert metadata_release_by_county["連江縣"]["required_read_api_fields"] == list(
        REQUIRED_REALTIME_READ_API_FIELDS
    )
    assert (
        metadata_release_by_county["連江縣"]["requested_counterparty"]
        == "連江縣政府公開資料或防災水利窗口"
    )
    assert (
        metadata_release_by_county["連江縣"]["tracking_status"]
        == "monitoring_open_data_release"
    )
    assert metadata_release_by_county["連江縣"]["last_followed_up_at"] is None
    assert metadata_release_by_county["連江縣"]["open_data_release_monitor"] == {
        "target_county": "連江縣",
        "source_catalog": "data.gov.tw dataset export",
        "source_catalog_url": "https://data.gov.tw/api/front/dataset/export?format=json",
        "expected_current_state": "metadata_only",
        "escalate_on_state": "live_candidate_found",
        "candidate_readiness_field": "candidate_live_read_api",
        "command": (
            "PYTHONPATH=apps/workers python "
            "scripts/local-source-discovery-monitor.py "
            "--county 連江縣 --fail-on-candidate"
        ),
    }
    assert metadata_release_by_county["連江縣"]["non_qualifying_source_names"] == [
        "連江自來水廠水庫水位月報",
        "連江縣資訊公開查詢系統即時監測值",
    ]
    assert metadata_release_by_county["連江縣"]["non_qualifying_source_reasons"] == [
        "公開水庫水位為月報 PDF，沒有 observed_at/station_id/measurement_value 的即時 read API。",
        "公開即時監測頁為放流水環保 CEMS，不是淹水、水位、雨水下水道、抽水站或水門觀測。",
    ]

    public_contract_by_county = {
        item["county"]: item for item in plan["public_api_contract_reviews"]
    }
    assert set(public_contract_by_county) == {"苗栗縣", "屏東縣", "臺東縣"}
    miaoli_contract = public_contract_by_county["\u82d7\u6817\u7e23"]
    assert miaoli_contract["candidate_contract_missing_fields"] == [
        "observed_at",
        "station_or_device_id",
        "measurement_value",
        "measurement_unit_or_type",
        "longitude_latitude_or_joinable_station_metadata",
    ]
    assert any(
        "58 water-level monitoring stations" in finding
        and "10 town/city urban-planning areas" in finding
        for finding in miaoli_contract["candidate_contract_findings"]
    )
    assert any(
        "\u96e8\u6c34\u4e0b\u6c34\u9053\u5373\u6642\u6c34\u60c5\u76e3\u6e2c\u7cfb\u7d71\u5efa\u7f6e\u8a08\u756b" in finding
        and "monthly reports" in finding
        for finding in miaoli_contract["candidate_contract_findings"]
    )
    assert any(
        "HTML article/JPGs" in note
        and "not a sewer_water_level read API" in note
        for note in miaoli_contract["candidate_contract_non_measurement_notes"]
    )
    taitung_contract = public_contract_by_county["\u81fa\u6771\u7e23"]
    assert "audit.gov.tw" in " ".join(taitung_contract["candidate_source_urls"])
    assert taitung_contract["candidate_contract_missing_fields"] == [
        "observed_at",
        "station_or_device_id",
        "measurement_value",
        "measurement_unit_or_type",
        "longitude_latitude_or_joinable_station_metadata",
    ]
    assert any(
        "flood sensors, water-level stations, rain gauges, and realtime cameras"
        in finding
        and "no public read API" in finding
        for finding in taitung_contract["candidate_contract_findings"]
    )
    assert any(
        "49 CWA rainfall stations" in finding
        and "9 WRA water-level stations" in finding
        for finding in taitung_contract["candidate_contract_findings"]
    )
    assert any(
        "news article/audit summary" in note
        and "not a latest-observation read API" in note
        for note in taitung_contract["candidate_contract_non_measurement_notes"]
    )
    assert (
        public_contract_by_county["屏東縣"]["tracking_status"]
        == "needs_public_read_api_contract"
    )
    assert "pteoc.pthg.gov.tw/RainStation" in " ".join(
        public_contract_by_county["屏東縣"]["candidate_source_urls"]
    )
    pingtung_contract = public_contract_by_county["屏東縣"]
    assert pingtung_contract["candidate_contract_missing_fields"] == [
        "observed_at",
        "longitude_latitude_or_joinable_station_metadata",
    ]
    assert any(
        "RainStation/Details" in finding and "10分鐘雨量" in finding
        for finding in pingtung_contract["candidate_contract_findings"]
    )
    assert any(
        "Flood/Details" in note and "not_flood_depth_measurement" in note
        for note in pingtung_contract["candidate_contract_non_measurement_notes"]
    )
    assert any(
        "Crawler/Details" in note and "image_only_cctv" in note
        for note in pingtung_contract["candidate_contract_non_measurement_notes"]
    )

    live_smoke_by_county = {
        item["county"]: item for item in plan["live_smoke_reviews"]
    }
    assert live_smoke_by_county == {}

    priority = plan["integration_priority_queue"]
    assert [item["county"] for item in priority[:3]] == ["連江縣", "金門縣", "花蓮縣"]
    assert priority[0]["rank"] == 1
    assert priority[0]["priority_tier"] == "P0"
    assert priority[0]["workstream"] == "monitor_open_data_release"
    assert priority[0]["central_backbone_missing_signal_types"] == []
    assert priority[0]["missing_signal_types"] == [
        "flood_depth",
        "sewer_water_level",
        "pump_or_gate_status",
    ]
    assert priority[0]["tracking_status"] == "monitoring_open_data_release"
    assert priority[0]["open_data_release_monitor"]["expected_current_state"] == (
        "metadata_only"
    )
    assert priority[0]["open_data_release_monitor"]["escalate_on_state"] == (
        "live_candidate_found"
    )
    assert priority[0]["non_qualifying_source_names"] == [
        "連江自來水廠水庫水位月報",
        "連江縣資訊公開查詢系統即時監測值",
    ]
    assert priority[1]["workstream"] == "request_official_authorization"
    assert "local_direct_source" in priority[1]["why_now"]
    assert "observed_at" in priority[1]["required_read_api_fields"]
    assert priority[1]["authorization_gated_adapter_keys"] == [
        "local.kinmen.kwis_pump_station"
    ]
    assert priority[1]["production_adapter_keys"] == []
    priority_by_county = {item["county"]: item for item in priority}
    assert priority_by_county["\u82d7\u6817\u7e23"][
        "candidate_contract_missing_fields"
    ] == [
        "observed_at",
        "station_or_device_id",
        "measurement_value",
        "measurement_unit_or_type",
        "longitude_latitude_or_joinable_station_metadata",
    ]
    assert priority_by_county["屏東縣"]["candidate_contract_missing_fields"] == [
        "observed_at",
        "longitude_latitude_or_joinable_station_metadata",
    ]
    assert priority_by_county["\u81fa\u6771\u7e23"][
        "candidate_contract_missing_fields"
    ] == [
        "observed_at",
        "station_or_device_id",
        "measurement_value",
        "measurement_unit_or_type",
        "longitude_latitude_or_joinable_station_metadata",
    ]

    signal_gaps = {item["county"]: item for item in plan["sensor_signal_gap_reviews"]}
    assert "臺北市" in signal_gaps
    assert "嘉義市" in signal_gaps
    assert "雲林縣" in signal_gaps
    assert signal_gaps["臺北市"]["missing_signal_types"] == ["flood_depth"]
    assert signal_gaps["臺北市"]["status_only_signal_types"] == ["gate_status"]
    assert signal_gaps["臺北市"]["status_only_source_urls"] == [
        "https://wic.gov.taipei/OpenData/API/Evacuate/Get?stationNo=&loginId=watergate&dataKey=44D76DA6",
    ]
    assert {
        "flood_depth",
        "sewer_water_level",
        "pump_or_gate_status",
    }.issubset(set(signal_gaps["嘉義市"]["missing_signal_types"]))
    assert signal_gaps["雲林縣"]["missing_signal_types"] == ["flood_depth"]
    assert signal_gaps["雲林縣"]["status_only_source_names"] == [
        "雲林 iflood 淹水感測狀態"
    ]
    assert signal_gaps["雲林縣"]["status_only_signal_types"] == [
        "flood_sensor_status"
    ]
    assert signal_gaps["嘉義市"]["workstream"] == "fill_sensor_signal_gap"
    assert "高雄市" not in signal_gaps


def test_local_source_action_plan_keeps_ready_counties_out_of_blocker_queues() -> None:
    plan = build_local_source_action_plan(list_local_source_coverage())

    queued_counties = {
        item["county"]
        for queue in (
            "authorization_requests",
            "metadata_release_monitors",
            "public_api_contract_reviews",
            "live_smoke_reviews",
        )
        for item in plan[queue]
    }

    assert "臺南市" not in queued_counties
    assert "高雄市" not in queued_counties
    assert "新竹縣" not in queued_counties


def test_local_source_action_plan_prioritizes_signal_gap_reviews_after_blockers() -> None:
    plan = build_local_source_action_plan(list_local_source_coverage())

    priority_by_county = {
        item["county"]: item for item in plan["integration_priority_queue"]
    }

    assert priority_by_county["連江縣"]["rank"] < priority_by_county["嘉義市"]["rank"]
    assert priority_by_county["金門縣"]["rank"] < priority_by_county["嘉義市"]["rank"]
    assert priority_by_county["嘉義市"]["rank"] < priority_by_county["臺北市"]["rank"]
    assert priority_by_county["臺北市"]["tracking_status"] == "needs_signal_gap_review"
    assert priority_by_county["臺北市"]["missing_signal_types"] == ["flood_depth"]
    assert priority_by_county["嘉義市"]["priority_tier"] == "P2"
    assert priority_by_county["嘉義市"]["tracking_status"] == "needs_signal_gap_review"
    assert "measurement_value" in priority_by_county["嘉義市"]["completion_gate"]


def test_local_source_action_plan_groups_signal_gap_priorities() -> None:
    plan = build_local_source_action_plan(list_local_source_coverage())

    groups = plan["signal_gap_priority_groups"]

    assert [group["signal_type"] for group in groups] == [
        "pump_or_gate_status",
        "flood_depth",
        "sewer_water_level",
    ]
    pump_or_gate = groups[0]
    assert pump_or_gate["rank"] == 1
    assert pump_or_gate["county_count"] == 14
    assert pump_or_gate["recommended_workstream"] == "bulk_signal_gap_discovery"
    assert pump_or_gate["completion_gate"] == (
        "For every listed county, add a production adapter, an authorization-gated "
        "adapter, or an official unavailable/blocked-source record for pump_or_gate_status."
    )
    assert pump_or_gate["discovery_monitor"]["target_signal_type"] == (
        "pump_or_gate_status"
    )
    assert pump_or_gate["discovery_monitor"]["candidate_readiness_field"] == (
        "candidate_live_read_api"
    )
    assert "--signal-type pump_or_gate_status" in pump_or_gate["discovery_monitor"][
        "command"
    ]
    assert "--county 金門縣" in pump_or_gate["discovery_monitor"]["command"]
    assert "--county 嘉義市" in pump_or_gate["discovery_monitor"]["command"]
    assert pump_or_gate["counties"][:4] == [
        "連江縣",
        "金門縣",
        "臺東縣",
        "苗栗縣",
    ]
    assert "嘉義市" in pump_or_gate["counties"]
    assert pump_or_gate["highest_priority_tier"] == "P0"
    assert pump_or_gate["tracking_statuses"]["needs_signal_gap_review"] == 10
    assert pump_or_gate["tracking_statuses"]["needs_public_read_api_contract"] == 2
    assert pump_or_gate["tracking_statuses"]["needs_authorization_request"] == 1
    assert pump_or_gate["tracking_statuses"]["monitoring_open_data_release"] == 1
    request_batch = pump_or_gate["official_request_batch"]
    assert request_batch["target_signal_type"] == "pump_or_gate_status"
    assert request_batch["packet_type"] == "signal_gap_batch_request"
    assert request_batch["county_count"] == 14
    assert request_batch["counties"] == pump_or_gate["counties"]
    assert request_batch["required_read_api_fields"] == list(
        REQUIRED_REALTIME_READ_API_FIELDS
    )
    assert request_batch["production_operational_requirements"] == [
        "freshness_policy",
        "raw_snapshot_retention_policy",
        "monitored_scheduler_cadence",
        "hosted_egress_review",
        "worker_persisted_evidence_path",
    ]
    assert request_batch["next_step"] == "send_official_read_api_requests"
    assert (
        "scripts/local-source-request-packets.py --format markdown"
        in request_batch["packet_generator_command"]
    )
    assert "--signal-type pump_or_gate_status" in request_batch[
        "packet_generator_command"
    ]

    by_signal = {group["signal_type"]: group for group in groups}
    assert by_signal["flood_depth"]["county_count"] == 5
    assert by_signal["sewer_water_level"]["county_count"] == 5


def test_local_source_action_plan_audits_completion_gates() -> None:
    plan = build_local_source_action_plan(list_local_source_coverage())

    audit = plan["completion_audit"]

    assert audit["overall_status"] == "incomplete"
    assert audit["summary"] == {
        "total_counties": 22,
        "local_direct_remaining_count": 2,
        "central_backbone_remaining_count": 0,
        "unresolved_priority_item_count": 18,
        "signal_gap_group_count": 3,
        "signal_gap_county_item_count": 24,
        "authorization_request_count": 2,
        "metadata_release_monitor_count": 1,
        "public_api_contract_review_count": 3,
        "live_smoke_review_count": 0,
    }
    gates = {gate["gate_key"]: gate for gate in audit["gates"]}

    assert gates["central_backbone_minimum_coverage"]["status"] == "satisfied"
    assert gates["local_direct_or_tracked_request"]["status"] == "satisfied"

    signal_gate = gates["required_signal_families"]
    assert signal_gate["status"] == "incomplete"
    assert signal_gate["blocking_items"] == [
        "pump_or_gate_status:14",
        "flood_depth:5",
        "sewer_water_level:5",
    ]
    assert signal_gate["next_workstream"] == "send_official_read_api_requests"

    hosted_gate = gates["hosted_worker_persisted_evidence"]
    assert hosted_gate["status"] == "incomplete"
    assert "worker-persisted evidence" in hosted_gate["evidence"]

    assert audit["next_priority_workstreams"][:3] == [
        "send_official_read_api_requests",
        "resolve_authorization_gated_adapters",
        "hosted_persistence_and_scheduler_proof",
    ]


def test_local_source_action_plan_applies_completion_evidence_overlay() -> None:
    baseline = build_local_source_action_plan(list_local_source_coverage())
    evidence = _complete_evidence_overlay(baseline)

    plan = build_local_source_action_plan(
        list_local_source_coverage(),
        completion_evidence=evidence,
    )
    audit = plan["completion_audit"]
    gates = {gate["gate_key"]: gate for gate in audit["gates"]}

    assert audit["overall_status"] == "satisfied"
    assert audit["next_priority_workstreams"] == []
    assert audit["evidence_overlay"] == {
        "schema_version": "local-source-completion-evidence/v1",
        "captured_at": "2026-06-30T12:00:00+08:00",
        "signal_family_gap_evidence_count": 24,
        "source_contract_evidence_count": 6,
        "production_gate_evidence_count": 3,
        "validation_errors": [],
    }
    assert gates["required_signal_families"]["status"] == "satisfied"
    assert gates["required_signal_families"]["blocking_items"] == []
    assert gates["official_authorization_and_contracts"]["status"] == "satisfied"
    assert gates["official_authorization_and_contracts"]["blocking_items"] == []
    assert gates["hosted_worker_persisted_evidence"]["status"] == "satisfied"
    assert gates["production_monitoring_and_alerting"]["status"] == "satisfied"
    assert gates["public_risk_worker_evidence_path"]["status"] == "satisfied"


def test_tainan_signal_gap_exposes_static_metadata_and_non_measurement_leads() -> None:
    plan = build_local_source_action_plan(list_local_source_coverage())

    tainan = next(
        item
        for item in plan["sensor_signal_gap_reviews"]
        if item["county"] == "\u81fa\u5357\u5e02"
    )

    assert tainan["metadata_source_names"] == [
        "\u81fa\u5357\u5e02\u7ba1\u5340\u57df\u6392\u6c34\u4e4b\u6c34\u4f4d\u7ad9\u540d\u7a31\u53ca\u4f4d\u7f6e",
        "114\u5e74\u5ea6\u62bd\u6c34\u7ad9\u57fa\u672c\u8cc7\u6599",
        "114\u5e74\u5ea6\u6c34\u9580\u57fa\u672c\u8cc7\u6599",
    ]
    assert tainan["metadata_source_urls"] == [
        "https://soa.tainan.gov.tw/Api/Service/Get/6c525fc0-f70a-433e-8529-8e11e65e85e9",
        "https://soa.tainan.gov.tw/Api/Service/Get/d9311994-b4c3-4952-8493-b7e49d17fbd3",
        "https://soa.tainan.gov.tw/Api/Service/Get/3be620b5-4381-4195-bc2f-2eff62a46291",
    ]
    assert tainan["non_qualifying_source_names"] == [
        "\u81fa\u5357\u5e02\u7ba1\u5340\u57df\u6392\u6c34\u5373\u6642\u5f71\u50cf",
        "\u6c34\u5229\u7f72\u8207\u53f0\u5357\u5e02\u5408\u5efa\u6df9\u6c34\u611f\u6e2c\u5668\u611f\u6e2c\u8cc7\u6599",
    ]
    assert any(
        "ImageUrl" in reason and "image-only CCTV" in reason
        for reason in tainan["non_qualifying_source_reasons"]
    )
    assert any(
        "data:null" in reason
        for reason in tainan["non_qualifying_source_reasons"]
    )


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
            },
            {
                "gate_key": "production_monitoring_and_alerting",
                "status": "accepted",
                "evidence_ref": "private-ops://zeabur/alert-routing",
            },
            {
                "gate_key": "public_risk_worker_evidence_path",
                "status": "accepted",
                "evidence_ref": "private-ops://zeabur/public-risk-smoke",
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
