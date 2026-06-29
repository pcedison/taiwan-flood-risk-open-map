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
    assert set(live_smoke_by_county) == {"臺北市", "雲林縣"}
    assert live_smoke_by_county["臺北市"]["tracking_status"] == "needs_live_smoke_retry"


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
