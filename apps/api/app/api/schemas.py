from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

RiskLevel = Literal["低", "中", "高", "極高", "未知"]
ConfidenceLevel = Literal["低", "中", "高", "未知"]
AttentionLevel = Literal["低", "中", "高", "未知"]
GeocodePrecision = Literal[
    "exact_address",
    "road_or_lane",
    "poi",
    "admin_area",
    "map_click",
    "unknown",
]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(ContractModel):
    status: Literal["ok"]
    service: str
    version: str
    deployment_sha: str | None = None
    checked_at: datetime


class DependencyReadiness(ContractModel):
    status: Literal["healthy", "failed"]
    checked_at: datetime
    message: str | None = None


class ReadyResponse(ContractModel):
    status: Literal["ok", "down"]
    service: str
    version: str
    deployment_sha: str | None = None
    checked_at: datetime
    dependencies: dict[str, DependencyReadiness]


JobStatus = Literal["queued", "running", "succeeded", "failed", "skipped", "disabled"]
HealthStatus = Literal["healthy", "degraded", "failed", "disabled", "unknown"]
FreshnessState = Literal["fresh", "degraded", "stale", "failed"]
SourceType = Literal["official", "news", "forum", "social", "user_report", "derived"]
LegalBasis = Literal["L1", "L2", "L3", "L4", "L5"]
LocalDirectSourceStatus = Literal[
    "ready_implemented",
    "candidate",
    "needs_review",
    "metadata_only",
    "not_found",
    "needs_application",
]
LocalSourceNextAction = Literal[
    "operate_adapter",
    "verify_public_api_contract",
    "verify_live_smoke",
    "request_official_authorization",
    "monitor_open_data_release",
    "continue_official_discovery",
]


class IngestionJob(ContractModel):
    job_key: str
    status: JobStatus
    items_fetched: int = Field(ge=0)
    items_promoted: int = Field(ge=0)
    items_rejected: int = Field(ge=0)
    adapter_key: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    source_timestamp_min: datetime | None = None
    source_timestamp_max: datetime | None = None


class AdminJobsResponse(ContractModel):
    jobs: list[IngestionJob]


class DataSource(ContractModel):
    id: str
    name: str
    adapter_key: str
    source_type: SourceType
    license: str
    update_frequency: str
    health_status: HealthStatus
    legal_basis: LegalBasis
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    source_timestamp_min: datetime | None = None
    source_timestamp_max: datetime | None = None
    is_enabled: bool = True
    latest_observed_at: datetime | None = None
    latest_fetched_at: datetime | None = None
    latest_ingested_at: datetime | None = None
    lag_seconds: int | None = Field(default=None, ge=0)
    row_count: int = Field(default=0, ge=0)
    covered_counties: list[str] = Field(default_factory=list)
    covered_county_count: int = Field(default=0, ge=0)
    fresh_county_count: int = Field(default=0, ge=0)
    stale_county_count: int = Field(default=0, ge=0)
    station_count_by_county: dict[str, int] = Field(default_factory=dict)
    missing_counties: list[str] = Field(default_factory=list)
    upstream_status: str = "unknown"
    enabled_gates: list[str] = Field(default_factory=list)
    freshness_state: FreshnessState = "stale"


class AdminSourcesResponse(ContractModel):
    sources: list[DataSource]


class LocalSourceCoverage(ContractModel):
    county: str
    local_direct_statuses: list[LocalDirectSourceStatus]
    local_direct_complete: bool = False
    central_backbone_available: bool = False
    production_adapter_keys: list[str] = Field(default_factory=list)
    production_source_urls: list[str] = Field(default_factory=list)
    central_backbone_adapter_keys: list[str] = Field(default_factory=list)
    central_backbone_signal_types: list[str] = Field(default_factory=list)
    central_backbone_required_signal_types: list[str] = Field(default_factory=list)
    central_backbone_minimum_complete: bool = False
    central_backbone_missing_signal_types: list[str] = Field(default_factory=list)
    central_backbone_coverage_level: str = "incomplete"
    rainfall_available: bool = False
    water_level_available: bool = False
    flood_depth_available: bool = False
    sewer_water_level_available: bool = False
    pump_or_gate_status_available: bool = False
    status_only_available: bool = False
    missing_signal_types: list[str] = Field(default_factory=list)
    candidate_source_names: list[str] = Field(default_factory=list)
    candidate_source_urls: list[str] = Field(default_factory=list)
    candidate_contract_findings: list[str] = Field(default_factory=list)
    candidate_contract_missing_fields: list[str] = Field(default_factory=list)
    candidate_contract_non_measurement_notes: list[str] = Field(default_factory=list)
    metadata_source_names: list[str] = Field(default_factory=list)
    metadata_source_urls: list[str] = Field(default_factory=list)
    status_only_source_names: list[str] = Field(default_factory=list)
    status_only_source_urls: list[str] = Field(default_factory=list)
    status_only_signal_types: list[str] = Field(default_factory=list)
    non_qualifying_source_names: list[str] = Field(default_factory=list)
    non_qualifying_source_urls: list[str] = Field(default_factory=list)
    non_qualifying_source_reasons: list[str] = Field(default_factory=list)
    application_urls: list[str] = Field(default_factory=list)
    requires_application: bool = False
    application_note: str | None = None
    next_action_code: LocalSourceNextAction
    upgrade_priority: int = Field(ge=1, le=5)
    blocking_reason: str | None = None
    notes: list[str] = Field(default_factory=list)


class LocalSourceCoverageSummary(ContractModel):
    total_counties: int = Field(ge=0)
    local_direct_complete_count: int = Field(ge=0)
    local_direct_incomplete_count: int = Field(ge=0)
    local_direct_incomplete_counties: list[str] = Field(default_factory=list)
    central_backbone_minimum_complete_count: int = Field(ge=0)
    central_backbone_minimum_incomplete_count: int = Field(ge=0)
    counties_missing_hydrologic_backbone: list[str] = Field(default_factory=list)
    central_backbone_required_families: list[str] = Field(default_factory=list)
    central_backbone_missing_families: list[str] = Field(default_factory=list)
    central_backbone_family_complete: bool = False
    central_backbone_required_adapter_keys: list[str] = Field(default_factory=list)
    central_backbone_missing_adapter_keys: list[str] = Field(default_factory=list)
    request_official_authorization_count: int = Field(ge=0)
    verify_live_smoke_count: int = Field(ge=0)
    verify_public_api_contract_count: int = Field(ge=0)
    counties_requiring_official_authorization: list[str] = Field(default_factory=list)
    counties_requiring_live_smoke: list[str] = Field(default_factory=list)
    counties_requiring_public_api_contract: list[str] = Field(default_factory=list)
    counties_requiring_metadata_release_monitoring: list[str] = Field(default_factory=list)
    counties_requiring_official_discovery: list[str] = Field(default_factory=list)


class AdminLocalSourceCoverageResponse(ContractModel):
    generated_at: datetime
    summary: LocalSourceCoverageSummary
    counties: list[LocalSourceCoverage]


class LocalSourceAuthorizationRequest(ContractModel):
    county: str
    reason: str | None = None
    application_urls: list[str] = Field(default_factory=list)
    application_note: str | None = None
    production_adapter_keys: list[str] = Field(default_factory=list)
    authorization_gated_adapter_keys: list[str] = Field(default_factory=list)
    requested_counterparty: str
    tracking_status: str
    last_followed_up_at: datetime | None = None
    required_read_api_fields: list[str] = Field(default_factory=list)
    request_focus: str


class LocalSourceOpenDataReleaseMonitor(ContractModel):
    target_county: str
    source_catalog: str
    source_catalog_url: str
    expected_current_state: str
    escalate_on_state: str
    candidate_readiness_field: str
    command: str


class LocalSourceSignalGapDiscoveryMonitor(ContractModel):
    target_signal_type: str
    source_catalog: str
    source_catalog_url: str
    candidate_readiness_field: str
    county_count: int = Field(ge=0)
    command: str


class LocalSourceSignalGapOfficialRequestBatch(ContractModel):
    target_signal_type: str
    packet_type: str
    county_count: int = Field(ge=0)
    counties: list[str] = Field(default_factory=list)
    requested_counterparties: list[str] = Field(default_factory=list)
    tracking_statuses: list[str] = Field(default_factory=list)
    required_read_api_fields: list[str] = Field(default_factory=list)
    production_operational_requirements: list[str] = Field(default_factory=list)
    next_step: str
    packet_generator_command: str
    completion_gate: str


class LocalSourceCompletionAuditSummary(ContractModel):
    total_counties: int = Field(ge=0)
    local_direct_remaining_count: int = Field(ge=0)
    central_backbone_remaining_count: int = Field(ge=0)
    unresolved_priority_item_count: int = Field(ge=0)
    signal_gap_group_count: int = Field(ge=0)
    signal_gap_county_item_count: int = Field(ge=0)
    authorization_request_count: int = Field(ge=0)
    metadata_release_monitor_count: int = Field(ge=0)
    public_api_contract_review_count: int = Field(ge=0)
    live_smoke_review_count: int = Field(ge=0)


class LocalSourceCompletionAuditGate(ContractModel):
    gate_key: str
    status: str
    evidence: str
    blocking_items: list[str] = Field(default_factory=list)
    next_workstream: str | None = None


class LocalSourceCompletionEvidenceOverlay(ContractModel):
    schema_version: str | None = None
    captured_at: str | None = None
    follow_up_as_of: str | None = None
    signal_family_gap_evidence_count: int = Field(ge=0)
    signal_family_gap_dispatch_count: int = Field(ge=0)
    signal_family_gap_dispatch_follow_up_count: int = Field(ge=0)
    signal_family_gap_dispatch_overdue_count: int = Field(ge=0)
    signal_family_gap_next_follow_up_due_at: str | None = None
    source_contract_evidence_count: int = Field(ge=0)
    source_contract_dispatch_count: int = Field(ge=0)
    source_contract_dispatch_follow_up_count: int = Field(ge=0)
    source_contract_dispatch_overdue_count: int = Field(ge=0)
    source_contract_next_follow_up_due_at: str | None = None
    production_gate_evidence_count: int = Field(ge=0)
    production_gate_requirement_evidence_count: int = Field(ge=0)
    validation_errors: list[str] = Field(default_factory=list)


class LocalSourceCompletionAudit(ContractModel):
    overall_status: str
    summary: LocalSourceCompletionAuditSummary
    evidence_overlay: LocalSourceCompletionEvidenceOverlay
    gates: list[LocalSourceCompletionAuditGate] = Field(default_factory=list)
    next_priority_workstreams: list[str] = Field(default_factory=list)


class LocalSourceMetadataReleaseMonitor(ContractModel):
    county: str
    reason: str | None = None
    metadata_source_names: list[str] = Field(default_factory=list)
    metadata_source_urls: list[str] = Field(default_factory=list)
    non_qualifying_source_names: list[str] = Field(default_factory=list)
    non_qualifying_source_urls: list[str] = Field(default_factory=list)
    non_qualifying_source_reasons: list[str] = Field(default_factory=list)
    central_backbone_missing_signal_types: list[str] = Field(default_factory=list)
    missing_signal_types: list[str] = Field(default_factory=list)
    requested_counterparty: str
    tracking_status: str
    last_followed_up_at: datetime | None = None
    required_read_api_fields: list[str] = Field(default_factory=list)
    open_data_release_monitor: LocalSourceOpenDataReleaseMonitor | None = None
    request_focus: str


class LocalSourcePublicApiContractReview(ContractModel):
    county: str
    reason: str | None = None
    candidate_source_names: list[str] = Field(default_factory=list)
    candidate_source_urls: list[str] = Field(default_factory=list)
    candidate_contract_findings: list[str] = Field(default_factory=list)
    candidate_contract_missing_fields: list[str] = Field(default_factory=list)
    candidate_contract_non_measurement_notes: list[str] = Field(default_factory=list)
    requested_counterparty: str
    tracking_status: str
    last_followed_up_at: datetime | None = None
    required_read_api_fields: list[str] = Field(default_factory=list)


class LocalSourceLiveSmokeReview(ContractModel):
    county: str
    reason: str | None = None
    candidate_source_names: list[str] = Field(default_factory=list)
    candidate_source_urls: list[str] = Field(default_factory=list)
    production_adapter_keys: list[str] = Field(default_factory=list)
    requested_counterparty: str
    tracking_status: str
    last_followed_up_at: datetime | None = None
    required_read_api_fields: list[str] = Field(default_factory=list)


class LocalSourceIntegrationPriorityItem(ContractModel):
    rank: int = Field(ge=1)
    priority_tier: str
    county: str
    workstream: str
    next_action_code: str
    tracking_status: str
    requested_counterparty: str
    blocking_reason: str | None = None
    why_now: str
    completion_gate: str
    missing_signal_types: list[str] = Field(default_factory=list)
    central_backbone_missing_signal_types: list[str] = Field(default_factory=list)
    production_adapter_keys: list[str] = Field(default_factory=list)
    authorization_gated_adapter_keys: list[str] = Field(default_factory=list)
    metadata_source_names: list[str] = Field(default_factory=list)
    metadata_source_urls: list[str] = Field(default_factory=list)
    candidate_source_names: list[str] = Field(default_factory=list)
    candidate_source_urls: list[str] = Field(default_factory=list)
    candidate_contract_findings: list[str] = Field(default_factory=list)
    candidate_contract_missing_fields: list[str] = Field(default_factory=list)
    candidate_contract_non_measurement_notes: list[str] = Field(default_factory=list)
    status_only_source_names: list[str] = Field(default_factory=list)
    status_only_source_urls: list[str] = Field(default_factory=list)
    status_only_signal_types: list[str] = Field(default_factory=list)
    non_qualifying_source_names: list[str] = Field(default_factory=list)
    non_qualifying_source_urls: list[str] = Field(default_factory=list)
    non_qualifying_source_reasons: list[str] = Field(default_factory=list)
    application_urls: list[str] = Field(default_factory=list)
    required_read_api_fields: list[str] = Field(default_factory=list)
    open_data_release_monitor: LocalSourceOpenDataReleaseMonitor | None = None


class LocalSourceSignalGapPriorityGroup(ContractModel):
    rank: int = Field(ge=1)
    signal_type: str
    county_count: int = Field(ge=0)
    counties: list[str] = Field(default_factory=list)
    highest_priority_tier: str
    recommended_workstream: str
    tracking_statuses: dict[str, int] = Field(default_factory=dict)
    discovery_monitor: LocalSourceSignalGapDiscoveryMonitor
    official_request_batch: LocalSourceSignalGapOfficialRequestBatch
    completion_gate: str


class LocalSourceActionPlan(ContractModel):
    total_counties: int = Field(ge=0)
    local_direct_complete_count: int = Field(ge=0)
    local_direct_remaining_count: int = Field(ge=0)
    central_backbone_minimum_complete_count: int = Field(ge=0)
    central_backbone_remaining_count: int = Field(ge=0)
    completion_audit: LocalSourceCompletionAudit
    authorization_requests: list[LocalSourceAuthorizationRequest] = Field(
        default_factory=list
    )
    metadata_release_monitors: list[LocalSourceMetadataReleaseMonitor] = Field(
        default_factory=list
    )
    public_api_contract_reviews: list[LocalSourcePublicApiContractReview] = Field(
        default_factory=list
    )
    live_smoke_reviews: list[LocalSourceLiveSmokeReview] = Field(default_factory=list)
    sensor_signal_gap_reviews: list[LocalSourceIntegrationPriorityItem] = Field(
        default_factory=list
    )
    integration_priority_queue: list[LocalSourceIntegrationPriorityItem] = Field(
        default_factory=list
    )
    signal_gap_priority_groups: list[LocalSourceSignalGapPriorityGroup] = Field(
        default_factory=list
    )


class AdminLocalSourceActionPlanResponse(ContractModel):
    generated_at: datetime
    plan: LocalSourceActionPlan


class LatLng(ContractModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class GeocodeRequest(ContractModel):
    query: str = Field(min_length=1, max_length=300)
    input_type: Literal["address", "landmark", "parcel"] = "address"
    limit: int = Field(default=5, ge=1, le=10)


class PlaceCandidate(ContractModel):
    place_id: str
    name: str
    type: Literal["address", "parcel", "landmark", "admin_area", "poi"]
    point: LatLng
    admin_code: str | None = None
    source: str
    confidence: float = Field(ge=0, le=1)
    precision: GeocodePrecision = "unknown"
    matched_query: str | None = None
    requires_confirmation: bool = False
    limitations: list[str] = Field(default_factory=list)


class GeocodeResponse(ContractModel):
    candidates: list[PlaceCandidate]


class UserReportCreateRequest(ContractModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    point: LatLng
    summary: str = Field(min_length=1, max_length=500)
    challenge_token: str | None = Field(default=None, min_length=1, max_length=4096)


class UserReportCreateResponse(ContractModel):
    report_id: str
    status: Literal["pending"]


UserReportStatus = Literal["pending", "approved", "rejected", "spam", "deleted"]
UserReportModerationStatus = Literal["approved", "rejected", "spam"]
UserReportModerationReason = Literal[
    "verified_flood_signal",
    "duplicate",
    "not_flood_related",
    "insufficient_detail",
    "abuse_or_spam",
    "out_of_scope",
]
UserReportPrivacyRedactionReason = Literal[
    "reporter_request",
    "affected_person_request",
    "private_data_exposure",
    "retention_expiry",
    "operator_error",
]

_MODERATION_REASONS_BY_STATUS: dict[
    UserReportModerationStatus, set[UserReportModerationReason]
] = {
    "approved": {"verified_flood_signal"},
    "rejected": {
        "duplicate",
        "not_flood_related",
        "insufficient_detail",
        "out_of_scope",
    },
    "spam": {"abuse_or_spam"},
}


class AdminUserReport(ContractModel):
    report_id: str
    status: UserReportStatus
    point: LatLng
    summary: str
    created_at: datetime
    reviewed_at: datetime | None = None


class AdminUserReportsResponse(ContractModel):
    reports: list[AdminUserReport]


class UserReportModerationRequest(ContractModel):
    status: UserReportModerationStatus
    reason_code: UserReportModerationReason

    @model_validator(mode="after")
    def reason_matches_status(self) -> Self:
        allowed_reasons = _MODERATION_REASONS_BY_STATUS[self.status]
        if self.reason_code not in allowed_reasons:
            raise ValueError("reason_code is not allowed for moderation status")
        return self


class UserReportModerationResponse(ContractModel):
    report: AdminUserReport


class UserReportPrivacyRedactionRequest(ContractModel):
    reason_code: UserReportPrivacyRedactionReason


class AdminUserReportPrivacyRedaction(ContractModel):
    report_id: str
    status: Literal["deleted"]
    privacy_level: Literal["redacted"]
    redacted_at: datetime


class UserReportPrivacyRedactionResponse(ContractModel):
    redaction: AdminUserReportPrivacyRedaction


class RiskAssessRequest(ContractModel):
    point: LatLng
    radius_m: int = Field(default=500, ge=50, le=2000)
    time_context: Literal["now"]
    location_text: str | None = Field(default=None, max_length=300)


class RiskLevelBlock(ContractModel):
    level: RiskLevel


class ConfidenceBlock(ContractModel):
    level: ConfidenceLevel


class Explanation(ContractModel):
    summary: str = Field(min_length=1)
    main_reasons: list[str] = Field(default_factory=list)
    missing_sources: list[str] = Field(default_factory=list)


class EvidencePreview(ContractModel):
    id: str
    source_type: Literal["official", "news", "forum", "social", "user_report", "derived"]
    event_type: Literal[
        "rainfall",
        "water_level",
        "flood_warning",
        "flood_potential",
        "flood_report",
        "status_only",
        "road_closure",
        "discussion",
    ]
    title: str
    summary: str
    occurred_at: datetime | None = None
    observed_at: datetime | None = None
    ingested_at: datetime
    distance_to_query_m: float | None = Field(default=None, ge=0)
    confidence: float = Field(ge=0, le=1)
    url: str | None = None


class DataFreshness(ContractModel):
    source_id: str
    name: str
    health_status: Literal["healthy", "degraded", "failed", "disabled", "unknown"]
    observed_at: datetime | None = None
    ingested_at: datetime | None = None
    feature_count: int | None = Field(default=None, ge=0)
    message: str | None = None


class QueryHeat(ContractModel):
    period: str
    attention_level: AttentionLevel
    query_count_bucket: str | None = None
    unique_approx_count_bucket: str | None = None
    updated_at: datetime


NearbyCoverageLevel = Literal["high", "medium", "low", "no_local_sensor", "unavailable"]
NearbySignalAvailability = Literal[
    "fresh_nearby",
    "degraded_nearby",
    "regional_reference",
    "stale_observation",
    "source_unavailable",
    "source_status_unknown",
    "no_station",
]
NearbySourceHealthReason = Literal[
    "operational",
    "delayed",
    "upstream_unavailable",
    "pipeline_unavailable",
    "pipeline_stalled",
    "disabled",
    "not_yet_observed",
]
NearbyMissingCause = Literal[
    "none",
    "no_station_in_range",
    "inventory_unverified",
    "stale_observation",
    "source_degraded",
    "source_failed",
    "update_pipeline_stalled",
    "source_not_configured",
    "jurisdiction_unverified",
    "health_unknown",
]
NearbyCoverageSignalType = Literal[
    "rainfall",
    "water_level",
    "flood_depth",
    "sewer_water_level",
    "pump_or_gate_status",
    "flood_warning",
    "status_only",
]


class NearbySourceHealth(ContractModel):
    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,119}$")
    name: str
    signal_types: list[NearbyCoverageSignalType]
    coverage_scope: Literal["national", "local"]
    health_status: HealthStatus
    reason_code: NearbySourceHealthReason
    observed_at: datetime | None = None
    checked_at: datetime | None = None
    station_count: int | None = Field(default=None, ge=0)
    upstream_station_count: int | None = Field(default=None, ge=0)
    pages_fetched: int | None = Field(default=None, ge=0)
    pagination_complete: bool | None = None
    inventory_manifest_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    inventory_proof_status: Literal[
        "missing",
        "incomplete",
        "awaiting_review",
        "checksum_mismatch",
        "approved",
    ] = "missing"
    inventory_complete: bool = False
    jurisdictions: list[str] = Field(default_factory=list)
    required_for_absence: bool = True
    message: str


class NearbyCoverageSignal(ContractModel):
    signal_type: NearbyCoverageSignalType
    label: str
    coverage_level: NearbyCoverageLevel
    availability_state: NearbySignalAvailability = "no_station"
    nearest_distance_m: float | None = Field(default=None, ge=0)
    nearest_source_id: str | None = None
    nearest_observed_at: datetime | None = None
    counts_by_radius_m: dict[str, int]
    fresh_count: int = Field(ge=0)
    degraded_count: int = Field(default=0, ge=0)
    stale_count: int = Field(ge=0)
    status_only_count: int = Field(ge=0)
    nearest_freshness_state: Literal["fresh", "degraded", "stale"] | None = None
    source_health_status: HealthStatus = "unknown"
    source_count: int = Field(default=0, ge=0)
    failed_source_count: int = Field(default=0, ge=0)
    missing_cause: NearbyMissingCause = "health_unknown"
    missing_reason: str | None = None


class NearbyRealtimeCoverage(ContractModel):
    overall_level: NearbyCoverageLevel
    evaluated_at: datetime
    query_radius_m: int = Field(ge=50, le=2000)
    radius_buckets_m: list[int]
    summary: str
    signal_breakdown: list[NearbyCoverageSignal]
    missing_signal_types: list[NearbyCoverageSignalType]
    limitations: list[str]
    source_health: list[NearbySourceHealth] = Field(default_factory=list)
    source_health_status: HealthStatus = "unknown"
    source_health_checked: bool = False
    jurisdiction_status: Literal[
        "verified",
        "boundary_unverified",
        "outside_coverage",
        "ambiguous",
        "unavailable",
    ] = "unavailable"
    jurisdiction_checked: bool = Field(
        default=False,
        description="True only when one checksum-verified 22-county boundary snapshot resolves a unique home jurisdiction.",
    )
    jurisdiction_catalog_complete: bool = Field(
        default=False,
        description="True only when every considered county/signal contract is reviewed and its current source-mapping count, checksum, revision, and redundancy parents match the approval.",
    )
    home_jurisdiction: str | None = None
    considered_jurisdictions: list[str] = Field(default_factory=list)
    jurisdiction_mapping_revisions: list[str] = Field(
        default_factory=list,
        description="Public review revisions for the exact source mappings applicable to this spatial query.",
    )
    jurisdiction_unverified_signal_types: list[NearbyCoverageSignalType] = Field(
        default_factory=list
    )
    county_level_note: str = Field(
        description='縣市層級涵蓋只作背景參考，不代表查詢點附近的感測器覆蓋；附近涵蓋會依查詢點重新計算。'
    )


class RiskAssessmentResponse(ContractModel):

    assessment_id: str
    location: LatLng
    radius_m: int
    score_version: str
    created_at: datetime
    expires_at: datetime
    realtime: RiskLevelBlock
    historical: RiskLevelBlock
    confidence: ConfidenceBlock
    explanation: Explanation
    evidence: list[EvidencePreview]
    data_freshness: list[DataFreshness]
    query_heat: QueryHeat
    nearby_realtime_coverage: NearbyRealtimeCoverage


class GeoJsonGeometry(ContractModel):
    type: Literal["Point", "LineString", "Polygon", "MultiPolygon"]
    coordinates: list[Any]


class Evidence(EvidencePreview):
    source_id: str
    url: str | None = None
    point: LatLng | None = None
    geometry: GeoJsonGeometry | None = None
    freshness_score: float = Field(ge=0, le=1)
    source_weight: float = Field(ge=0)
    privacy_level: Literal["public", "aggregated", "redacted"]
    raw_ref: str | None = None
    # Internal-only: intensity-aware realtime risk factor for official rainfall/
    # water_level evidence (None = use the default 1.0). Excluded from responses.
    realtime_risk_factor: float | None = Field(default=None, exclude=True)


class EvidenceListResponse(ContractModel):
    assessment_id: str
    items: list[Evidence]
    next_cursor: str | None


class MapLayer(ContractModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9.-]{0,79}$")
    name: str
    description: str | None = None
    category: Literal[
        "flood_potential",
        "rainfall",
        "water_level",
        "warning",
        "evidence",
        "query_heat",
    ]
    status: Literal["available", "degraded", "disabled"]
    minzoom: int | None = Field(default=None, ge=0, le=24)
    maxzoom: int | None = Field(default=None, ge=0, le=24)
    attribution: str | None = None
    tilejson_url: str
    updated_at: datetime | None = None


class LayersResponse(ContractModel):
    layers: list[MapLayer]


class TileJsonVectorLayer(BaseModel):
    id: str
    description: str | None = None
    minzoom: int | None = None
    maxzoom: int | None = None
    fields: dict[str, str] | None = None


class TileJson(BaseModel):
    tilejson: str
    name: str
    version: str | None = None
    attribution: str | None = None
    status: Literal["available", "degraded", "disabled"] | None = None
    scheme: Literal["xyz", "tms"] = "xyz"
    tiles: list[str] = Field(min_length=1)
    tile_url_source: Literal["metadata", "local_vector_tile_endpoint"] | None = None
    cache_control: str | None = None
    minzoom: int | None = Field(default=None, ge=0, le=24)
    maxzoom: int | None = Field(default=None, ge=0, le=24)
    bounds: list[float] | None = Field(default=None, min_length=4, max_length=4)
    center: list[float] | None = Field(default=None, min_length=3, max_length=3)
    updated_at: datetime | None = None
    vector_layers: list[TileJsonVectorLayer] | None = None
