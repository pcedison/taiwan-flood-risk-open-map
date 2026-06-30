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
DATA_GOV_DATASET_EXPORT_URL = "https://data.gov.tw/api/front/dataset/export?format=json"
PRODUCTION_OPERATIONAL_REQUIREMENTS = (
    "freshness_policy",
    "raw_snapshot_retention_policy",
    "monitored_scheduler_cadence",
    "hosted_egress_review",
    "worker_persisted_evidence_path",
)


def build_local_source_action_plan(
    records: tuple[LocalSourceCoverageRecord, ...],
) -> dict[str, Any]:
    local_complete = [record for record in records if record.local_direct_complete]
    central_complete = [record for record in records if record.central_backbone_minimum_complete]
    authorization_requests = [
        _authorization_request(record)
        for record in records
        if record.next_action_code == "request_official_authorization"
    ]
    metadata_release_monitors = [
        _metadata_release_monitor(record)
        for record in records
        if "metadata_only" in record.local_direct_statuses
    ]
    public_api_contract_reviews = [
        _public_api_contract_review(record)
        for record in records
        if record.next_action_code == "verify_public_api_contract"
    ]
    live_smoke_reviews = [
        _live_smoke_review(record)
        for record in records
        if record.next_action_code == "verify_live_smoke"
    ]
    sensor_signal_gap_reviews = _sensor_signal_gap_reviews(records)
    integration_priority_queue = _integration_priority_queue(
        records,
        sensor_signal_gap_reviews=sensor_signal_gap_reviews,
    )
    signal_gap_priority_groups = _signal_gap_priority_groups(
        integration_priority_queue
    )
    return {
        "total_counties": len(records),
        "local_direct_complete_count": len(local_complete),
        "local_direct_remaining_count": len(records) - len(local_complete),
        "central_backbone_minimum_complete_count": len(central_complete),
        "central_backbone_remaining_count": len(records) - len(central_complete),
        "completion_audit": _completion_audit(
            records=records,
            local_direct_remaining_count=len(records) - len(local_complete),
            central_backbone_remaining_count=len(records) - len(central_complete),
            authorization_requests=authorization_requests,
            metadata_release_monitors=metadata_release_monitors,
            public_api_contract_reviews=public_api_contract_reviews,
            live_smoke_reviews=live_smoke_reviews,
            integration_priority_queue=integration_priority_queue,
            signal_gap_priority_groups=signal_gap_priority_groups,
        ),
        "authorization_requests": authorization_requests,
        "metadata_release_monitors": metadata_release_monitors,
        "public_api_contract_reviews": public_api_contract_reviews,
        "live_smoke_reviews": live_smoke_reviews,
        "sensor_signal_gap_reviews": sensor_signal_gap_reviews,
        "integration_priority_queue": integration_priority_queue,
        "signal_gap_priority_groups": signal_gap_priority_groups,
    }


def _completion_audit(
    *,
    records: tuple[LocalSourceCoverageRecord, ...],
    local_direct_remaining_count: int,
    central_backbone_remaining_count: int,
    authorization_requests: list[dict[str, Any]],
    metadata_release_monitors: list[dict[str, Any]],
    public_api_contract_reviews: list[dict[str, Any]],
    live_smoke_reviews: list[dict[str, Any]],
    integration_priority_queue: list[dict[str, Any]],
    signal_gap_priority_groups: list[dict[str, Any]],
) -> dict[str, Any]:
    signal_gap_county_item_count = sum(
        int(group["county_count"]) for group in signal_gap_priority_groups
    )
    tracked_counties = {
        record.county for record in records if record.local_direct_complete
    } | {str(item["county"]) for item in integration_priority_queue}
    local_gate_status = (
        "satisfied" if len(tracked_counties) == len(records) else "incomplete"
    )
    signal_blocking_items = [
        f"{group['signal_type']}:{group['county_count']}"
        for group in signal_gap_priority_groups
    ]
    source_contract_blocking_items = [
        f"authorization_requests:{len(authorization_requests)}",
        f"metadata_release_monitors:{len(metadata_release_monitors)}",
        f"public_api_contract_reviews:{len(public_api_contract_reviews)}",
    ]
    gates = [
        _audit_gate(
            gate_key="local_direct_or_tracked_request",
            status=local_gate_status,
            evidence=(
                "Every county has local direct coverage or appears in the "
                "tracked integration priority/request workflow."
            ),
            blocking_items=[] if local_gate_status == "satisfied" else [
                "untracked_local_direct_gap"
            ],
            next_workstream=None if local_gate_status == "satisfied" else (
                "create_official_request_packet"
            ),
        ),
        _audit_gate(
            gate_key="central_backbone_minimum_coverage",
            status="satisfied" if central_backbone_remaining_count == 0 else (
                "incomplete"
            ),
            evidence=(
                f"central_backbone_remaining_count="
                f"{central_backbone_remaining_count}"
            ),
            blocking_items=[] if central_backbone_remaining_count == 0 else [
                "central_backbone_missing_counties"
            ],
            next_workstream=None if central_backbone_remaining_count == 0 else (
                "restore_hydrologic_backbone"
            ),
        ),
        _audit_gate(
            gate_key="required_signal_families",
            status="satisfied" if not signal_gap_priority_groups else "incomplete",
            evidence=(
                f"{len(signal_gap_priority_groups)} signal families remain in "
                "signal_gap_priority_groups."
            ),
            blocking_items=signal_blocking_items,
            next_workstream=(
                None
                if not signal_gap_priority_groups
                else "send_official_read_api_requests"
            ),
        ),
        _audit_gate(
            gate_key="official_authorization_and_contracts",
            status=(
                "satisfied"
                if not authorization_requests
                and not metadata_release_monitors
                and not public_api_contract_reviews
                else "incomplete"
            ),
            evidence=(
                "Formal credentials, official releases, and public read API "
                "contracts must clear before blocked local sources can become "
                "production adapters."
            ),
            blocking_items=source_contract_blocking_items,
            next_workstream="resolve_authorization_gated_adapters",
        ),
        _audit_gate(
            gate_key="hosted_worker_persisted_evidence",
            status="incomplete",
            evidence=(
                "Hosted/production must prove worker-persisted evidence, raw "
                "snapshots, staging rows, adapter runs, promoted latest rows, "
                "and scheduler cadence per README and ADR-0010."
            ),
            blocking_items=list(PRODUCTION_OPERATIONAL_REQUIREMENTS),
            next_workstream="hosted_persistence_and_scheduler_proof",
        ),
        _audit_gate(
            gate_key="production_monitoring_and_alerting",
            status="incomplete",
            evidence=(
                "Fresh/stale/failed source state needs hosted scrape jobs, "
                "alert routing ownership, and monitored scheduler evidence."
            ),
            blocking_items=[
                "hosted_alert_routing",
                "scheduled_freshness_checks",
                "worker_scheduler_alert_ownership",
            ],
            next_workstream="monitoring_and_alerting_proof",
        ),
        _audit_gate(
            gate_key="public_risk_worker_evidence_path",
            status="incomplete",
            evidence=(
                "Hosted risk responses must use worker-persisted evidence and "
                "query-point nearby coverage; direct official bridge calls are "
                "local diagnostics only."
            ),
            blocking_items=[
                "hosted_risk_response_worker_evidence_smoke",
                "query_point_nearby_coverage_smoke",
            ],
            next_workstream="hosted_risk_response_smoke",
        ),
    ]
    overall_status = (
        "satisfied" if all(gate["status"] == "satisfied" for gate in gates) else (
            "incomplete"
        )
    )
    return {
        "overall_status": overall_status,
        "summary": {
            "total_counties": len(records),
            "local_direct_remaining_count": local_direct_remaining_count,
            "central_backbone_remaining_count": central_backbone_remaining_count,
            "unresolved_priority_item_count": len(integration_priority_queue),
            "signal_gap_group_count": len(signal_gap_priority_groups),
            "signal_gap_county_item_count": signal_gap_county_item_count,
            "authorization_request_count": len(authorization_requests),
            "metadata_release_monitor_count": len(metadata_release_monitors),
            "public_api_contract_review_count": len(public_api_contract_reviews),
            "live_smoke_review_count": len(live_smoke_reviews),
        },
        "gates": gates,
        "next_priority_workstreams": [
            "send_official_read_api_requests",
            "resolve_authorization_gated_adapters",
            "hosted_persistence_and_scheduler_proof",
            "monitoring_and_alerting_proof",
        ],
    }


def _audit_gate(
    *,
    gate_key: str,
    status: str,
    evidence: str,
    blocking_items: list[str],
    next_workstream: str | None,
) -> dict[str, Any]:
    return {
        "gate_key": gate_key,
        "status": status,
        "evidence": evidence,
        "blocking_items": blocking_items,
        "next_workstream": next_workstream,
    }


def _authorization_request(record: LocalSourceCoverageRecord) -> dict[str, Any]:
    return {
        "county": record.county,
        "reason": record.blocking_reason,
        "application_urls": list(record.application_urls),
        "application_note": record.application_note,
        "production_adapter_keys": list(record.production_adapter_keys),
        "authorization_gated_adapter_keys": list(
            record.authorization_gated_adapter_keys
        ),
        "requested_counterparty": _requested_counterparty(record),
        "tracking_status": "needs_authorization_request",
        "last_followed_up_at": None,
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
        "non_qualifying_source_names": list(record.non_qualifying_source_names),
        "non_qualifying_source_urls": list(record.non_qualifying_source_urls),
        "non_qualifying_source_reasons": list(record.non_qualifying_source_reasons),
        "central_backbone_missing_signal_types": list(
            record.central_backbone_missing_signal_types
        ),
        "missing_signal_types": list(record.missing_signal_types),
        "requested_counterparty": _requested_counterparty(record),
        "tracking_status": "monitoring_open_data_release",
        "last_followed_up_at": None,
        "required_read_api_fields": list(REQUIRED_REALTIME_READ_API_FIELDS),
        "open_data_release_monitor": _open_data_release_monitor(record),
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
        "candidate_contract_findings": list(record.candidate_contract_findings),
        "candidate_contract_missing_fields": list(
            record.candidate_contract_missing_fields
        ),
        "candidate_contract_non_measurement_notes": list(
            record.candidate_contract_non_measurement_notes
        ),
        "requested_counterparty": _requested_counterparty(record),
        "tracking_status": "needs_public_read_api_contract",
        "last_followed_up_at": None,
        "required_read_api_fields": list(REQUIRED_REALTIME_READ_API_FIELDS),
    }


def _live_smoke_review(record: LocalSourceCoverageRecord) -> dict[str, Any]:
    return {
        "county": record.county,
        "reason": record.blocking_reason,
        "candidate_source_names": list(record.candidate_source_names),
        "candidate_source_urls": list(record.candidate_source_urls),
        "production_adapter_keys": list(record.production_adapter_keys),
        "requested_counterparty": _requested_counterparty(record),
        "tracking_status": "needs_live_smoke_retry",
        "last_followed_up_at": None,
        "required_read_api_fields": list(REQUIRED_REALTIME_READ_API_FIELDS),
    }


def _sensor_signal_gap_reviews(
    records: tuple[LocalSourceCoverageRecord, ...],
) -> list[dict[str, Any]]:
    gap_records = sorted(
        (
            record
            for record in records
            if record.local_direct_complete
            and record.next_action_code == "operate_adapter"
            and record.missing_signal_types
        ),
        key=lambda record: (-len(record.missing_signal_types), record.county),
    )
    return [
        _integration_priority_item(rank=index + 1, record=record)
        for index, record in enumerate(gap_records)
    ]


def _integration_priority_queue(
    records: tuple[LocalSourceCoverageRecord, ...],
    *,
    sensor_signal_gap_reviews: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    signal_gap_counties = {item["county"] for item in sensor_signal_gap_reviews}
    candidates = [
        record
        for record in records
        if _needs_integration_work(record, signal_gap_counties=signal_gap_counties)
    ]
    ordered = sorted(candidates, key=_integration_sort_key)
    return [
        _integration_priority_item(rank=index + 1, record=record)
        for index, record in enumerate(ordered)
    ]


def _needs_integration_work(
    record: LocalSourceCoverageRecord,
    *,
    signal_gap_counties: set[str],
) -> bool:
    return (
        not record.central_backbone_minimum_complete
        or not record.local_direct_complete
        or record.next_action_code != "operate_adapter"
        or record.county in signal_gap_counties
    )


def _integration_sort_key(record: LocalSourceCoverageRecord) -> tuple[int, int, int, int, str]:
    return (
        0 if not record.central_backbone_minimum_complete else 1,
        0 if not record.local_direct_complete else 1,
        _workstream_priority(record),
        -len(record.missing_signal_types),
        record.county,
    )


def _integration_priority_item(
    *,
    rank: int,
    record: LocalSourceCoverageRecord,
) -> dict[str, Any]:
    return {
        "rank": rank,
        "priority_tier": _priority_tier(record),
        "county": record.county,
        "workstream": _workstream(record),
        "next_action_code": record.next_action_code,
        "tracking_status": _tracking_status(record),
        "requested_counterparty": _requested_counterparty(record),
        "blocking_reason": record.blocking_reason,
        "why_now": _why_now(record),
        "completion_gate": _completion_gate(record),
        "missing_signal_types": list(record.missing_signal_types),
        "central_backbone_missing_signal_types": list(
            record.central_backbone_missing_signal_types
        ),
        "production_adapter_keys": list(record.production_adapter_keys),
        "authorization_gated_adapter_keys": list(
            record.authorization_gated_adapter_keys
        ),
        "metadata_source_names": list(record.metadata_source_names),
        "metadata_source_urls": list(record.metadata_source_urls),
        "candidate_source_names": list(record.candidate_source_names),
        "candidate_source_urls": list(record.candidate_source_urls),
        "candidate_contract_findings": list(record.candidate_contract_findings),
        "candidate_contract_missing_fields": list(
            record.candidate_contract_missing_fields
        ),
        "candidate_contract_non_measurement_notes": list(
            record.candidate_contract_non_measurement_notes
        ),
        "status_only_source_names": list(record.status_only_source_names),
        "status_only_source_urls": list(record.status_only_source_urls),
        "status_only_signal_types": list(record.status_only_signal_types),
        "non_qualifying_source_names": list(record.non_qualifying_source_names),
        "non_qualifying_source_urls": list(record.non_qualifying_source_urls),
        "non_qualifying_source_reasons": list(record.non_qualifying_source_reasons),
        "application_urls": list(record.application_urls),
        "required_read_api_fields": list(REQUIRED_REALTIME_READ_API_FIELDS),
        "open_data_release_monitor": _open_data_release_monitor(record),
    }


def _open_data_release_monitor(
    record: LocalSourceCoverageRecord,
) -> dict[str, Any] | None:
    if record.next_action_code not in {
        "monitor_open_data_release",
        "continue_official_discovery",
    }:
        return None
    expected_state = (
        "metadata_only" if "metadata_only" in record.local_direct_statuses else "no_candidate"
    )
    return {
        "target_county": record.county,
        "source_catalog": "data.gov.tw dataset export",
        "source_catalog_url": DATA_GOV_DATASET_EXPORT_URL,
        "expected_current_state": expected_state,
        "escalate_on_state": "live_candidate_found",
        "candidate_readiness_field": "candidate_live_read_api",
        "command": (
            "PYTHONPATH=apps/workers python "
            "scripts/local-source-discovery-monitor.py "
            f"--county {record.county} --fail-on-candidate"
        ),
    }


def _signal_gap_priority_groups(
    integration_priority_queue: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in integration_priority_queue:
        for signal_type in item["missing_signal_types"]:
            grouped.setdefault(signal_type, []).append(item)

    ordered = sorted(
        grouped.items(),
        key=lambda entry: (-len(entry[1]), entry[0]),
    )
    return [
        _signal_gap_priority_group(rank=index + 1, signal_type=signal_type, items=items)
        for index, (signal_type, items) in enumerate(ordered)
    ]


def _signal_gap_priority_group(
    *,
    rank: int,
    signal_type: str,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    tracking_statuses: dict[str, int] = {}
    for item in items:
        tracking_status = str(item["tracking_status"])
        tracking_statuses[tracking_status] = tracking_statuses.get(tracking_status, 0) + 1
    return {
        "rank": rank,
        "signal_type": signal_type,
        "county_count": len(items),
        "counties": [str(item["county"]) for item in items],
        "highest_priority_tier": str(items[0]["priority_tier"]),
        "recommended_workstream": "bulk_signal_gap_discovery",
        "tracking_statuses": tracking_statuses,
        "discovery_monitor": _signal_group_discovery_monitor(
            signal_type=signal_type,
            counties=[str(item["county"]) for item in items],
        ),
        "official_request_batch": _signal_group_official_request_batch(
            signal_type=signal_type,
            items=items,
        ),
        "completion_gate": (
            "For every listed county, add a production adapter, an authorization-gated "
            f"adapter, or an official unavailable/blocked-source record for {signal_type}."
        ),
    }


def _signal_group_official_request_batch(
    *,
    signal_type: str,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    counties = [str(item["county"]) for item in items]
    county_args = " ".join(f"--county {county}" for county in counties)
    requested_counterparties = tuple(
        dict.fromkeys(str(item["requested_counterparty"]) for item in items)
    )
    tracking_statuses = tuple(
        dict.fromkeys(str(item["tracking_status"]) for item in items)
    )
    return {
        "target_signal_type": signal_type,
        "packet_type": "signal_gap_batch_request",
        "county_count": len(counties),
        "counties": counties,
        "requested_counterparties": list(requested_counterparties),
        "tracking_statuses": list(tracking_statuses),
        "required_read_api_fields": list(REQUIRED_REALTIME_READ_API_FIELDS),
        "production_operational_requirements": list(
            PRODUCTION_OPERATIONAL_REQUIREMENTS
        ),
        "next_step": "send_official_read_api_requests",
        "packet_generator_command": (
            "PYTHONPATH=apps/api python scripts/local-source-request-packets.py "
            f"--format markdown --signal-type {signal_type} {county_args}"
        ),
        "completion_gate": (
            "Each county must provide a latest-observation read API, an "
            "authorization-gated adapter path, or an official unavailable-source "
            f"record for {signal_type}, plus production ops evidence."
        ),
    }


def _signal_group_discovery_monitor(
    *,
    signal_type: str,
    counties: list[str],
) -> dict[str, Any]:
    county_args = " ".join(f"--county {county}" for county in counties)
    return {
        "target_signal_type": signal_type,
        "source_catalog": "data.gov.tw dataset export",
        "source_catalog_url": DATA_GOV_DATASET_EXPORT_URL,
        "candidate_readiness_field": "candidate_live_read_api",
        "county_count": len(counties),
        "command": (
            "PYTHONPATH=apps/workers python "
            "scripts/local-source-discovery-monitor.py "
            f"--signal-type {signal_type} --fail-on-candidate {county_args}"
        ),
    }


def _workstream_priority(record: LocalSourceCoverageRecord) -> int:
    if not record.central_backbone_minimum_complete:
        return 0
    if not record.local_direct_complete:
        return 1
    return {
        "request_official_authorization": 2,
        "verify_live_smoke": 3,
        "verify_public_api_contract": 4,
        "monitor_open_data_release": 5,
        "continue_official_discovery": 6,
        "operate_adapter": 7,
    }[record.next_action_code]


def _priority_tier(record: LocalSourceCoverageRecord) -> str:
    if not record.central_backbone_minimum_complete or not record.local_direct_complete:
        return "P0"
    if record.next_action_code in {"request_official_authorization", "verify_live_smoke"}:
        return "P1"
    if record.next_action_code == "verify_public_api_contract" or record.missing_signal_types:
        return "P2"
    return "P3"


def _workstream(record: LocalSourceCoverageRecord) -> str:
    if not record.central_backbone_minimum_complete:
        return "restore_hydrologic_backbone"
    if record.next_action_code == "request_official_authorization":
        return "request_official_authorization"
    if record.next_action_code == "verify_live_smoke":
        return "verify_live_smoke"
    if record.next_action_code == "verify_public_api_contract":
        return "verify_public_read_api_contract"
    if record.next_action_code == "monitor_open_data_release":
        return "monitor_open_data_release"
    if record.next_action_code == "continue_official_discovery":
        return "continue_official_discovery"
    if record.missing_signal_types:
        return "fill_sensor_signal_gap"
    return "operate_adapter"


def _tracking_status(record: LocalSourceCoverageRecord) -> str:
    if record.missing_signal_types and record.next_action_code == "operate_adapter":
        return "needs_signal_gap_review"
    return {
        "request_official_authorization": "needs_authorization_request",
        "verify_live_smoke": "needs_live_smoke_retry",
        "verify_public_api_contract": "needs_public_read_api_contract",
        "monitor_open_data_release": "monitoring_open_data_release",
        "continue_official_discovery": "continue_official_discovery",
        "operate_adapter": "operating_adapter",
    }[record.next_action_code]


def _why_now(record: LocalSourceCoverageRecord) -> str:
    reasons: list[str] = []
    if not record.central_backbone_minimum_complete:
        reasons.append(
            "central_backbone is missing hydrologic observation coverage for this county"
        )
    if not record.local_direct_complete:
        reasons.append("local_direct_source is not complete")
    if record.requires_application:
        reasons.append("official authorization is required before a production read API can run")
    if "needs_review" in record.local_direct_statuses:
        reasons.append("candidate or status-only source needs live smoke and field semantics review")
    if "candidate" in record.local_direct_statuses:
        reasons.append("candidate source needs a public read API contract review")
    if record.missing_signal_types and record.next_action_code == "operate_adapter":
        reasons.append(
            "existing adapters do not cover every required water signal family"
        )
    return "；".join(reasons) or "adapter is operating; keep freshness and monitoring active"


def _completion_gate(record: LocalSourceCoverageRecord) -> str:
    if not record.central_backbone_minimum_complete:
        return (
            "取得至少一個可公開追溯的水位、淹水深度、雨水下水道、抽水站或水門"
            "即時 read API，並提供 observed_at、station_or_device_id、measurement_value、"
            "measurement_unit_or_type 與座標。"
        )
    if not record.local_direct_complete:
        return (
            "完成地方直出 production adapter，或留下含 required_read_api_fields 的官方"
            "授權/釋出請求並可追蹤 follow-up 狀態。"
        )
    if record.next_action_code == "request_official_authorization":
        return "取得官方授權或公開 read API contract，確認用途不是設備上傳 API。"
    if record.next_action_code == "verify_live_smoke":
        return "live smoke 連續成功，並確認 observed_at、station id、measurement_value、單位、座標與欄位語意。"
    if record.next_action_code == "verify_public_api_contract":
        return "公開 read API contract 補齊 observed_at、station id、measurement_value、單位與座標 metadata。"
    if record.missing_signal_types:
        return (
            "補齊缺少的 signal families，或以官方證據記錄為無法取得；可用資料必須含 "
            "observed_at、station_or_device_id、measurement_value、measurement_unit_or_type 與座標。"
        )
    return "持續以 worker scheduler 寫入 raw snapshot、staging、adapter run 與 promoted evidence。"


def _requested_counterparty(record: LocalSourceCoverageRecord) -> str:
    if record.county == "金門縣":
        return "金門縣政府 / KWIS 維運窗口"
    if record.county == "連江縣":
        return "連江縣政府公開資料或防災水利窗口"
    if record.county == "花蓮縣":
        return "花蓮縣政府 / Senslink 行動水情維運窗口"
    return f"{record.county}政府公開資料或水利防災維運窗口"
