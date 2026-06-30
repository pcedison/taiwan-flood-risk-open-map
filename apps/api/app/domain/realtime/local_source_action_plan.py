from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.domain.realtime.local_source_coverage import LocalSourceCoverageRecord


COMPLETION_EVIDENCE_SCHEMA_VERSION = "local-source-completion-evidence/v1"
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
PRODUCTION_EVIDENCE_GATE_KEYS = (
    "hosted_worker_persisted_evidence",
    "production_deployment_evidence",
    "production_monitoring_and_alerting",
    "public_risk_worker_evidence_path",
)
PRODUCTION_GATE_REQUIRED_REQUIREMENTS = {
    "hosted_worker_persisted_evidence": PRODUCTION_OPERATIONAL_REQUIREMENTS,
    "production_deployment_evidence": (
        "main_branch_deployed_sha",
        "ready_dependency_smoke",
    ),
    "production_monitoring_and_alerting": (
        "hosted_alert_routing",
        "scheduled_freshness_checks",
        "worker_scheduler_alert_ownership",
    ),
    "public_risk_worker_evidence_path": (
        "hosted_risk_response_worker_evidence_smoke",
        "query_point_nearby_coverage_smoke",
    ),
}
ACCEPTED_SIGNAL_EVIDENCE_STATUSES = {
    "accepted",
    "authorization_gated_adapter",
    "official_unavailable",
    "production_adapter",
}
DISPATCHED_SIGNAL_EVIDENCE_STATUSES = {
    "request_dispatched",
}
DISPATCHED_SOURCE_CONTRACT_EVIDENCE_STATUSES = {
    "request_dispatched",
}
ACCEPTED_SOURCE_CONTRACT_EVIDENCE_STATUSES = {
    "accepted",
    "authorized",
    "contract_verified",
    "official_unavailable",
    "released",
}
ACCEPTED_PRODUCTION_GATE_EVIDENCE_STATUSES = {
    "accepted",
    "satisfied",
    "verified",
}


@dataclass(frozen=True)
class CompletionEvidenceState:
    schema_version: str | None
    captured_at: str | None
    signal_family_gap_keys: frozenset[tuple[str, str]]
    signal_family_gap_dispatch_keys: frozenset[tuple[str, str]]
    source_contract_keys: frozenset[tuple[str, str]]
    source_contract_dispatch_keys: frozenset[tuple[str, str]]
    production_gate_keys: frozenset[str]
    production_gate_requirement_keys: frozenset[tuple[str, str]]
    validation_errors: tuple[str, ...]

    def to_summary(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "captured_at": self.captured_at,
            "signal_family_gap_evidence_count": len(self.signal_family_gap_keys),
            "signal_family_gap_dispatch_count": len(
                self.signal_family_gap_dispatch_keys
            ),
            "source_contract_evidence_count": len(self.source_contract_keys),
            "source_contract_dispatch_count": len(self.source_contract_dispatch_keys),
            "production_gate_evidence_count": len(self.production_gate_keys),
            "production_gate_requirement_evidence_count": len(
                self.production_gate_requirement_keys
            ),
            "validation_errors": list(self.validation_errors),
        }


def build_local_source_action_plan(
    records: tuple[LocalSourceCoverageRecord, ...],
    *,
    completion_evidence: Mapping[str, Any] | None = None,
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
            completion_evidence=completion_evidence,
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
    completion_evidence: Mapping[str, Any] | None,
) -> dict[str, Any]:
    evidence_state = _completion_evidence_state(completion_evidence)
    signal_gap_county_item_count = sum(
        int(group["county_count"]) for group in signal_gap_priority_groups
    )
    tracked_counties = {
        record.county for record in records if record.local_direct_complete
    } | {str(item["county"]) for item in integration_priority_queue}
    local_gate_status = (
        "satisfied" if len(tracked_counties) == len(records) else "incomplete"
    )
    signal_blocking_items = _signal_family_blocking_items(
        signal_gap_priority_groups,
        evidence_state=evidence_state,
    )
    source_contract_blocking_items = _source_contract_blocking_items(
        authorization_requests=authorization_requests,
        metadata_release_monitors=metadata_release_monitors,
        public_api_contract_reviews=public_api_contract_reviews,
        evidence_state=evidence_state,
    )
    signal_gate_satisfied = not signal_blocking_items
    source_contract_gate_satisfied = not source_contract_blocking_items
    hosted_blocking_items = _production_gate_blocking_items(
        "hosted_worker_persisted_evidence",
        evidence_state=evidence_state,
    )
    deployment_blocking_items = _production_gate_blocking_items(
        "production_deployment_evidence",
        evidence_state=evidence_state,
    )
    monitoring_blocking_items = _production_gate_blocking_items(
        "production_monitoring_and_alerting",
        evidence_state=evidence_state,
    )
    public_risk_blocking_items = _production_gate_blocking_items(
        "public_risk_worker_evidence_path",
        evidence_state=evidence_state,
    )
    hosted_evidence_satisfied = not hosted_blocking_items
    deployment_evidence_satisfied = not deployment_blocking_items
    monitoring_evidence_satisfied = not monitoring_blocking_items
    public_risk_evidence_satisfied = not public_risk_blocking_items
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
            status="satisfied" if signal_gate_satisfied else "incomplete",
            evidence=_signal_family_gate_evidence(
                signal_gap_priority_groups,
                evidence_state=evidence_state,
                satisfied=signal_gate_satisfied,
            ),
            blocking_items=signal_blocking_items,
            next_workstream=(
                None
                if signal_gate_satisfied
                else "send_official_read_api_requests"
            ),
        ),
        _audit_gate(
            gate_key="official_authorization_and_contracts",
            status="satisfied" if source_contract_gate_satisfied else "incomplete",
            evidence=_source_contract_gate_evidence(
                required_count=(
                    len(authorization_requests)
                    + len(metadata_release_monitors)
                    + len(public_api_contract_reviews)
                ),
                evidence_state=evidence_state,
                satisfied=source_contract_gate_satisfied,
            ),
            blocking_items=source_contract_blocking_items,
            next_workstream=(
                None
                if source_contract_gate_satisfied
                else "resolve_authorization_gated_adapters"
            ),
        ),
        _audit_gate(
            gate_key="hosted_worker_persisted_evidence",
            status="satisfied" if hosted_evidence_satisfied else "incomplete",
            evidence=_production_gate_evidence(
                "hosted_worker_persisted_evidence",
                default_evidence=(
                    "Hosted/production must prove worker-persisted evidence, raw "
                    "snapshots, staging rows, adapter runs, promoted latest rows, "
                    "and scheduler cadence per README and ADR-0010."
                ),
                evidence_state=evidence_state,
                satisfied=hosted_evidence_satisfied,
            ),
            blocking_items=hosted_blocking_items,
            next_workstream=(
                None
                if hosted_evidence_satisfied
                else "hosted_persistence_and_scheduler_proof"
            ),
        ),
        _audit_gate(
            gate_key="production_deployment_evidence",
            status="satisfied" if deployment_evidence_satisfied else "incomplete",
            evidence=_production_gate_evidence(
                "production_deployment_evidence",
                default_evidence=(
                    "Production deployment must prove the main branch merge SHA "
                    "is returned by hosted /health and /ready, with ready "
                    "dependencies healthy."
                ),
                evidence_state=evidence_state,
                satisfied=deployment_evidence_satisfied,
            ),
            blocking_items=deployment_blocking_items,
            next_workstream=(
                None
                if deployment_evidence_satisfied
                else "verify_main_branch_deployment"
            ),
        ),
        _audit_gate(
            gate_key="production_monitoring_and_alerting",
            status="satisfied" if monitoring_evidence_satisfied else "incomplete",
            evidence=_production_gate_evidence(
                "production_monitoring_and_alerting",
                default_evidence=(
                    "Fresh/stale/failed source state needs hosted scrape jobs, "
                    "alert routing ownership, and monitored scheduler evidence."
                ),
                evidence_state=evidence_state,
                satisfied=monitoring_evidence_satisfied,
            ),
            blocking_items=monitoring_blocking_items,
            next_workstream=(
                None
                if monitoring_evidence_satisfied
                else "monitoring_and_alerting_proof"
            ),
        ),
        _audit_gate(
            gate_key="public_risk_worker_evidence_path",
            status="satisfied" if public_risk_evidence_satisfied else "incomplete",
            evidence=_production_gate_evidence(
                "public_risk_worker_evidence_path",
                default_evidence=(
                    "Hosted risk responses must use worker-persisted evidence and "
                    "query-point nearby coverage; direct official bridge calls are "
                    "local diagnostics only."
                ),
                evidence_state=evidence_state,
                satisfied=public_risk_evidence_satisfied,
            ),
            blocking_items=public_risk_blocking_items,
            next_workstream=(
                None if public_risk_evidence_satisfied else "hosted_risk_response_smoke"
            ),
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
        "evidence_overlay": evidence_state.to_summary(),
        "gates": gates,
        "next_priority_workstreams": _next_priority_workstreams(gates),
    }


def _completion_evidence_state(
    completion_evidence: Mapping[str, Any] | None,
) -> CompletionEvidenceState:
    if completion_evidence is None:
        return CompletionEvidenceState(
            schema_version=None,
            captured_at=None,
            signal_family_gap_keys=frozenset(),
            signal_family_gap_dispatch_keys=frozenset(),
            source_contract_keys=frozenset(),
            source_contract_dispatch_keys=frozenset(),
            production_gate_keys=frozenset(),
            production_gate_requirement_keys=frozenset(),
            validation_errors=(),
        )

    errors: list[str] = []
    schema_version = completion_evidence.get("schema_version")
    captured_at = completion_evidence.get("captured_at")
    if schema_version != COMPLETION_EVIDENCE_SCHEMA_VERSION:
        errors.append(
            f"schema_version must be {COMPLETION_EVIDENCE_SCHEMA_VERSION!r}"
        )
        return CompletionEvidenceState(
            schema_version=schema_version if isinstance(schema_version, str) else None,
            captured_at=captured_at if isinstance(captured_at, str) else None,
            signal_family_gap_keys=frozenset(),
            signal_family_gap_dispatch_keys=frozenset(),
            source_contract_keys=frozenset(),
            source_contract_dispatch_keys=frozenset(),
            production_gate_keys=frozenset(),
            production_gate_requirement_keys=frozenset(),
            validation_errors=tuple(errors),
        )

    production_gate_requirement_keys = frozenset(
        _accepted_production_gate_requirement_keys(
            completion_evidence.get("production_gate_evidence"),
            errors,
        )
    )
    return CompletionEvidenceState(
        schema_version=schema_version,
        captured_at=captured_at if isinstance(captured_at, str) else None,
        signal_family_gap_keys=frozenset(
            _accepted_signal_family_gap_keys(
                completion_evidence.get("signal_family_gap_evidence"),
                errors,
            )
        ),
        signal_family_gap_dispatch_keys=frozenset(
            _dispatched_signal_family_gap_keys(
                completion_evidence.get("signal_family_gap_evidence"),
                errors,
            )
        ),
        source_contract_keys=frozenset(
            _accepted_source_contract_keys(
                completion_evidence.get("source_contract_evidence"),
                errors,
            )
        ),
        source_contract_dispatch_keys=frozenset(
            _dispatched_source_contract_keys(
                completion_evidence.get("source_contract_evidence"),
                errors,
            )
        ),
        production_gate_keys=frozenset(
            _completed_production_gate_keys(production_gate_requirement_keys)
        ),
        production_gate_requirement_keys=production_gate_requirement_keys,
        validation_errors=tuple(errors),
    )


def _accepted_signal_family_gap_keys(
    value: Any,
    errors: list[str],
) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for index, item in enumerate(_list_evidence(value, "signal_family_gap_evidence", errors)):
        county = item.get("county")
        signal_type = item.get("signal_type")
        status = item.get("status")
        if not _non_empty_string(county):
            errors.append(f"signal_family_gap_evidence[{index}].county is required")
            continue
        if not _non_empty_string(signal_type):
            errors.append(f"signal_family_gap_evidence[{index}].signal_type is required")
            continue
        if status not in ACCEPTED_SIGNAL_EVIDENCE_STATUSES:
            continue
        if not _non_empty_string(item.get("evidence_ref")):
            errors.append(f"signal_family_gap_evidence[{index}].evidence_ref is required")
            continue
        keys.add((str(county).strip(), str(signal_type).strip()))
    return keys


def _dispatched_signal_family_gap_keys(
    value: Any,
    errors: list[str],
) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for index, item in enumerate(_list_evidence(value, "signal_family_gap_evidence", errors)):
        county = item.get("county")
        signal_type = item.get("signal_type")
        status = item.get("status")
        if status not in DISPATCHED_SIGNAL_EVIDENCE_STATUSES:
            continue
        if not _non_empty_string(county):
            errors.append(f"signal_family_gap_evidence[{index}].county is required")
            continue
        if not _non_empty_string(signal_type):
            errors.append(f"signal_family_gap_evidence[{index}].signal_type is required")
            continue
        if not _non_empty_string(item.get("evidence_ref")):
            errors.append(f"signal_family_gap_evidence[{index}].evidence_ref is required")
            continue
        keys.add((str(county).strip(), str(signal_type).strip()))
    return keys


def _accepted_source_contract_keys(
    value: Any,
    errors: list[str],
) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for index, item in enumerate(_list_evidence(value, "source_contract_evidence", errors)):
        county = item.get("county")
        gate = item.get("gate")
        status = item.get("status")
        if not _non_empty_string(county):
            errors.append(f"source_contract_evidence[{index}].county is required")
            continue
        if gate not in {
            "authorization_request",
            "metadata_release_monitor",
            "public_api_contract_review",
        }:
            errors.append(f"source_contract_evidence[{index}].gate is invalid")
            continue
        if status not in ACCEPTED_SOURCE_CONTRACT_EVIDENCE_STATUSES:
            continue
        if not _non_empty_string(item.get("evidence_ref")):
            errors.append(f"source_contract_evidence[{index}].evidence_ref is required")
            continue
        keys.add((str(county).strip(), str(gate).strip()))
    return keys


def _dispatched_source_contract_keys(
    value: Any,
    errors: list[str],
) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for index, item in enumerate(_list_evidence(value, "source_contract_evidence", errors)):
        county = item.get("county")
        gate = item.get("gate")
        status = item.get("status")
        if status not in DISPATCHED_SOURCE_CONTRACT_EVIDENCE_STATUSES:
            continue
        if not _non_empty_string(county):
            errors.append(f"source_contract_evidence[{index}].county is required")
            continue
        if gate not in {
            "authorization_request",
            "metadata_release_monitor",
            "public_api_contract_review",
        }:
            errors.append(f"source_contract_evidence[{index}].gate is invalid")
            continue
        if not _non_empty_string(item.get("evidence_ref")):
            errors.append(f"source_contract_evidence[{index}].evidence_ref is required")
            continue
        keys.add((str(county).strip(), str(gate).strip()))
    return keys


def _accepted_production_gate_requirement_keys(
    value: Any,
    errors: list[str],
) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for index, item in enumerate(_list_evidence(value, "production_gate_evidence", errors)):
        gate_key = item.get("gate_key")
        status = item.get("status")
        if gate_key not in PRODUCTION_EVIDENCE_GATE_KEYS:
            errors.append(f"production_gate_evidence[{index}].gate_key is invalid")
            continue
        if status not in ACCEPTED_PRODUCTION_GATE_EVIDENCE_STATUSES:
            continue
        if not _non_empty_string(item.get("evidence_ref")):
            errors.append(f"production_gate_evidence[{index}].evidence_ref is required")
            continue
        requirements = item.get("satisfied_requirements")
        if not isinstance(requirements, list):
            errors.append(
                f"production_gate_evidence[{index}].satisfied_requirements is required"
            )
            continue
        allowed_requirements = set(PRODUCTION_GATE_REQUIRED_REQUIREMENTS[str(gate_key)])
        requirement_evidence_keys = _accepted_production_gate_requirement_detail_keys(
            item.get("requirement_evidence"),
            evidence_index=index,
            gate_key=str(gate_key),
            allowed_requirements=allowed_requirements,
            errors=errors,
        )
        for requirement_index, requirement in enumerate(requirements):
            if not _non_empty_string(requirement):
                errors.append(
                    "production_gate_evidence"
                    f"[{index}].satisfied_requirements[{requirement_index}]"
                    " must be a non-empty string"
                )
                continue
            requirement_key = str(requirement).strip()
            if requirement_key not in allowed_requirements:
                errors.append(
                    f"production_gate_evidence[{index}].satisfied_requirements"
                    f"[{requirement_index}] is invalid for {gate_key}"
                )
                continue
            if requirement_key not in requirement_evidence_keys:
                errors.append(
                    f"production_gate_evidence[{index}].requirement_evidence "
                    f"missing accepted evidence for {requirement_key}"
                )
                continue
            keys.add((str(gate_key), requirement_key))
    return keys


def _accepted_production_gate_requirement_detail_keys(
    value: Any,
    *,
    evidence_index: int,
    gate_key: str,
    allowed_requirements: set[str],
    errors: list[str],
) -> set[str]:
    if not isinstance(value, list):
        errors.append(
            f"production_gate_evidence[{evidence_index}].requirement_evidence is required"
        )
        return set()

    keys: set[str] = set()
    for detail_index, detail in enumerate(value):
        if not isinstance(detail, Mapping):
            errors.append(
                "production_gate_evidence"
                f"[{evidence_index}].requirement_evidence[{detail_index}] "
                "must be an object"
            )
            continue
        requirement = detail.get("requirement")
        if not _non_empty_string(requirement):
            errors.append(
                "production_gate_evidence"
                f"[{evidence_index}].requirement_evidence[{detail_index}]"
                ".requirement is required"
            )
            continue
        requirement_key = str(requirement).strip()
        if requirement_key not in allowed_requirements:
            errors.append(
                "production_gate_evidence"
                f"[{evidence_index}].requirement_evidence[{detail_index}]"
                f".requirement is invalid for {gate_key}"
            )
            continue
        if not _non_empty_string(detail.get("evidence_ref")):
            errors.append(
                "production_gate_evidence"
                f"[{evidence_index}].requirement_evidence[{detail_index}]"
                ".evidence_ref is required"
            )
            continue
        if not (
            _non_empty_string(detail.get("observed_at"))
            or _non_empty_string(detail.get("reviewed_at"))
        ):
            errors.append(
                "production_gate_evidence"
                f"[{evidence_index}].requirement_evidence[{detail_index}] "
                "requires observed_at or reviewed_at"
            )
            continue
        keys.add(requirement_key)
    return keys


def _completed_production_gate_keys(
    requirement_keys: frozenset[tuple[str, str]],
) -> set[str]:
    completed: set[str] = set()
    for gate_key, requirements in PRODUCTION_GATE_REQUIRED_REQUIREMENTS.items():
        missing_requirements = [
            requirement
            for requirement in requirements
            if (gate_key, requirement) not in requirement_keys
        ]
        if not missing_requirements:
            completed.add(gate_key)
    return completed


def _list_evidence(
    value: Any,
    field: str,
    errors: list[str],
) -> list[Mapping[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        errors.append(f"{field} must be a list")
        return []
    items: list[Mapping[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            errors.append(f"{field}[{index}] must be an object")
            continue
        items.append(item)
    return items


def _signal_family_blocking_items(
    signal_gap_priority_groups: list[dict[str, Any]],
    *,
    evidence_state: CompletionEvidenceState,
) -> list[str]:
    blocking_items: list[str] = []
    for group in signal_gap_priority_groups:
        signal_type = str(group["signal_type"])
        missing_counties = [
            str(county)
            for county in group["counties"]
            if (str(county), signal_type) not in evidence_state.signal_family_gap_keys
        ]
        if missing_counties:
            blocking_items.append(f"{signal_type}:{len(missing_counties)}")
    return blocking_items


def _source_contract_blocking_items(
    *,
    authorization_requests: list[dict[str, Any]],
    metadata_release_monitors: list[dict[str, Any]],
    public_api_contract_reviews: list[dict[str, Any]],
    evidence_state: CompletionEvidenceState,
) -> list[str]:
    required = (
        ("authorization_requests", "authorization_request", authorization_requests),
        ("metadata_release_monitors", "metadata_release_monitor", metadata_release_monitors),
        (
            "public_api_contract_reviews",
            "public_api_contract_review",
            public_api_contract_reviews,
        ),
    )
    blocking_items: list[str] = []
    for label, gate, items in required:
        missing_count = sum(
            1
            for item in items
            if (str(item["county"]), gate) not in evidence_state.source_contract_keys
        )
        if missing_count:
            blocking_items.append(f"{label}:{missing_count}")
    return blocking_items


def _signal_family_gate_evidence(
    signal_gap_priority_groups: list[dict[str, Any]],
    *,
    evidence_state: CompletionEvidenceState,
    satisfied: bool,
) -> str:
    if satisfied:
        return (
            f"{len(evidence_state.signal_family_gap_keys)} accepted signal-family "
            "evidence items cover current missing signal families."
        )
    dispatched_count = len(evidence_state.signal_family_gap_dispatch_keys)
    if dispatched_count:
        total_count = sum(
            int(group["county_count"]) for group in signal_gap_priority_groups
        )
        return (
            f"Dispatch evidence supplied for {dispatched_count}/{total_count} "
            "signal-family items; official reply, production adapter, or "
            "official-unavailable evidence is still required."
        )
    return (
        f"{len(signal_gap_priority_groups)} signal families remain in "
        "signal_gap_priority_groups."
    )


def _source_contract_gate_evidence(
    *,
    required_count: int,
    evidence_state: CompletionEvidenceState,
    satisfied: bool,
) -> str:
    if satisfied:
        return (
            f"{len(evidence_state.source_contract_keys)} accepted source-contract "
            "evidence items cover current authorization and contract blockers."
        )
    dispatched_count = len(evidence_state.source_contract_dispatch_keys)
    if dispatched_count:
        return (
            f"Dispatch evidence supplied for {dispatched_count}/{required_count} "
            "source-contract blockers; official authorization, released metadata, "
            "contract verification, or official-unavailable evidence is still required."
        )
    return (
        "Formal credentials, official releases, and public read API contracts "
        "must clear before blocked local sources can become production adapters."
    )


def _production_gate_blocking_items(
    gate_key: str,
    *,
    evidence_state: CompletionEvidenceState,
) -> list[str]:
    return [
        requirement
        for requirement in PRODUCTION_GATE_REQUIRED_REQUIREMENTS[gate_key]
        if (gate_key, requirement) not in evidence_state.production_gate_requirement_keys
    ]


def _production_gate_evidence(
    gate_key: str,
    *,
    default_evidence: str,
    evidence_state: CompletionEvidenceState,
    satisfied: bool,
) -> str:
    if satisfied:
        return f"Accepted completion evidence supplied for all {gate_key} requirements."
    accepted_count = sum(
        1
        for requirement in PRODUCTION_GATE_REQUIRED_REQUIREMENTS[gate_key]
        if (gate_key, requirement) in evidence_state.production_gate_requirement_keys
    )
    if accepted_count:
        total_count = len(PRODUCTION_GATE_REQUIRED_REQUIREMENTS[gate_key])
        return (
            f"Accepted completion evidence supplied for {accepted_count}/"
            f"{total_count} {gate_key} requirements."
        )
    return default_evidence


def _next_priority_workstreams(gates: list[dict[str, Any]]) -> list[str]:
    workstreams: dict[str, None] = {}
    for gate in gates:
        if gate["status"] == "satisfied":
            continue
        next_workstream = gate.get("next_workstream")
        if next_workstream:
            workstreams[str(next_workstream)] = None
    return list(workstreams)


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


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
