from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

RiskLevel = Literal["低", "中", "高", "極高", "未知"]
ConfidenceLevel = Literal["低", "中", "高", "未知"]
AttentionLevel = Literal["低", "中", "高", "未知"]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(ContractModel):
    status: Literal["ok"]
    service: str
    version: str
    checked_at: datetime


class DependencyReadiness(ContractModel):
    status: Literal["healthy", "failed"]
    checked_at: datetime
    message: str | None = None


class ReadyResponse(ContractModel):
    status: Literal["ok", "down"]
    service: str
    version: str
    checked_at: datetime
    dependencies: dict[str, DependencyReadiness]


JobStatus = Literal["queued", "running", "succeeded", "failed", "skipped", "disabled"]
HealthStatus = Literal["healthy", "degraded", "failed", "disabled", "unknown"]
SourceType = Literal["official", "news", "forum", "social", "user_report", "derived"]
LegalBasis = Literal["L1", "L2", "L3", "L4", "L5"]


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


class AdminSourcesResponse(ContractModel):
    sources: list[DataSource]


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


class GeocodeResponse(ContractModel):
    candidates: list[PlaceCandidate]


class UserReportCreateRequest(ContractModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    point: LatLng
    summary: str = Field(min_length=1, max_length=500)


class UserReportCreateResponse(ContractModel):
    report_id: str
    status: Literal["pending"]


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


class DataFreshness(ContractModel):
    source_id: str
    name: str
    health_status: Literal["healthy", "degraded", "failed", "disabled", "unknown"]
    observed_at: datetime | None = None
    ingested_at: datetime | None = None
    message: str | None = None


class QueryHeat(ContractModel):
    period: str
    attention_level: AttentionLevel
    query_count_bucket: str | None = None
    unique_approx_count_bucket: str | None = None
    updated_at: datetime


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
    scheme: Literal["xyz", "tms"] = "xyz"
    tiles: list[str] = Field(min_length=1)
    minzoom: int | None = Field(default=None, ge=0, le=24)
    maxzoom: int | None = Field(default=None, ge=0, le=24)
    bounds: list[float] | None = Field(default=None, min_length=4, max_length=4)
    center: list[float] | None = Field(default=None, min_length=3, max_length=3)
    vector_layers: list[TileJsonVectorLayer] | None = None
