from __future__ import annotations

from typing import Any

from app.domain.realtime.local_source_coverage import LocalSourceCoverageRecord


REQUIRED_REALTIME_READ_API_FIELDS = (
    "observed_at",
    "station_or_device_id",
    "measurement_value",
    "measurement_unit_or_type",
    "longitude_latitude_or_joinable_station_metadata",
    "official_source_url_and_license",
)


def build_local_source_action_plan(
    records: tuple[LocalSourceCoverageRecord, ...],
) -> dict[str, Any]:
    local_complete = [record for record in records if record.local_direct_complete]
    central_complete = [record for record in records if record.central_backbone_minimum_complete]
    return {
        "total_counties": len(records),
        "local_direct_complete_count": len(local_complete),
        "local_direct_remaining_count": len(records) - len(local_complete),
        "central_backbone_minimum_complete_count": len(central_complete),
        "central_backbone_remaining_count": len(records) - len(central_complete),
        "authorization_requests": [
            _authorization_request(record)
            for record in records
            if record.next_action_code == "request_official_authorization"
            and not record.local_direct_complete
        ],
        "metadata_release_monitors": [
            _metadata_release_monitor(record)
            for record in records
            if not record.local_direct_complete and "metadata_only" in record.local_direct_statuses
        ],
        "public_api_contract_reviews": [
            _public_api_contract_review(record)
            for record in records
            if not record.local_direct_complete and "candidate" in record.local_direct_statuses
        ],
        "live_smoke_reviews": [
            _live_smoke_review(record)
            for record in records
            if not record.local_direct_complete and "needs_review" in record.local_direct_statuses
        ],
    }


def _authorization_request(record: LocalSourceCoverageRecord) -> dict[str, Any]:
    return {
        "county": record.county,
        "reason": record.blocking_reason,
        "application_urls": list(record.application_urls),
        "application_note": record.application_note,
        "required_read_api_fields": list(REQUIRED_REALTIME_READ_API_FIELDS),
        "request_focus": (
            "請官方提供可查詢最新觀測值的 read API contract，而不是設備上傳 API；"
            "需包含觀測時間、設備或測站 ID、測值、單位或量測類型、座標或可 join 的站點 metadata。"
        ),
    }


def _metadata_release_monitor(record: LocalSourceCoverageRecord) -> dict[str, Any]:
    return {
        "county": record.county,
        "reason": record.blocking_reason,
        "metadata_source_names": list(record.metadata_source_names),
        "metadata_source_urls": list(record.metadata_source_urls),
        "central_backbone_missing_signal_types": list(
            record.central_backbone_missing_signal_types
        ),
        "request_focus": (
            "請官方釋出即時水文觀測 read API，至少包含水位、淹水深度、雨水下水道、"
            "抽水站或水門任一類觀測資料，並提供觀測時間、站點 ID、測值與座標。"
        ),
    }


def _public_api_contract_review(record: LocalSourceCoverageRecord) -> dict[str, Any]:
    return {
        "county": record.county,
        "reason": record.blocking_reason,
        "candidate_source_names": list(record.candidate_source_names),
        "candidate_source_urls": list(record.candidate_source_urls),
        "required_read_api_fields": list(REQUIRED_REALTIME_READ_API_FIELDS),
    }


def _live_smoke_review(record: LocalSourceCoverageRecord) -> dict[str, Any]:
    return {
        "county": record.county,
        "reason": record.blocking_reason,
        "candidate_source_names": list(record.candidate_source_names),
        "candidate_source_urls": list(record.candidate_source_urls),
        "production_adapter_keys": list(record.production_adapter_keys),
    }
