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
    assert plan["central_backbone_minimum_complete_count"] == 21
    assert plan["central_backbone_remaining_count"] == 1

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
    assert metadata_release_by_county["連江縣"]["central_backbone_missing_signal_types"] == [
        "hydrologic_observation"
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

    public_contract_by_county = {
        item["county"]: item for item in plan["public_api_contract_reviews"]
    }
    assert set(public_contract_by_county) == {"苗栗縣", "屏東縣", "臺東縣"}
    assert (
        public_contract_by_county["屏東縣"]["tracking_status"]
        == "needs_public_read_api_contract"
    )
    assert "pteoc.pthg.gov.tw/RainStation" in " ".join(
        public_contract_by_county["屏東縣"]["candidate_source_urls"]
    )

    live_smoke_by_county = {
        item["county"]: item for item in plan["live_smoke_reviews"]
    }
    assert set(live_smoke_by_county) == {"臺北市"}
    assert live_smoke_by_county["臺北市"]["tracking_status"] == "needs_live_smoke_retry"

    priority = plan["integration_priority_queue"]
    assert [item["county"] for item in priority[:3]] == ["連江縣", "金門縣", "花蓮縣"]
    assert priority[0]["rank"] == 1
    assert priority[0]["priority_tier"] == "P0"
    assert priority[0]["workstream"] == "restore_hydrologic_backbone"
    assert "hydrologic_observation" in priority[0]["central_backbone_missing_signal_types"]
    assert priority[0]["tracking_status"] == "monitoring_open_data_release"
    assert priority[1]["workstream"] == "request_official_authorization"
    assert "local_direct_source" in priority[1]["why_now"]
    assert "observed_at" in priority[1]["required_read_api_fields"]

    signal_gaps = {item["county"]: item for item in plan["sensor_signal_gap_reviews"]}
    assert "嘉義市" in signal_gaps
    assert "雲林縣" in signal_gaps
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
    assert priority_by_county["臺北市"]["rank"] < priority_by_county["嘉義市"]["rank"]
    assert priority_by_county["嘉義市"]["priority_tier"] == "P2"
    assert priority_by_county["嘉義市"]["tracking_status"] == "needs_signal_gap_review"
    assert "measurement_value" in priority_by_county["嘉義市"]["completion_gate"]
