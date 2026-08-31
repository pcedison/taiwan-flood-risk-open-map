from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, HTTPException, Query
from fastapi import Request as FastAPIRequest

from app.api.errors import error_payload
from app.api.schemas import (
    Evidence,
    EvidenceListResponse,
    GeocodeRequest,
    GeocodeResponse,
    GeoJsonGeometry,  # noqa: F401  (re-exported for tests)
    LatLng,  # noqa: F401  (re-exported for tests building Evidence payloads)
    LayersResponse,
    MapLayer,
    PlaceCandidate,
    RiskAssessmentResponse,
    RiskAssessRequest,
    TileJson,
)
from app.api.services import (
    public_evidence,
    public_geocoding,
    public_layers,
)
from app.api.services.assessment import AssessmentService
from app.api.services.client_signal import resolve_client_signal
from app.api.services.official_history import OfficialRecentHistoryLookup
from app.core.config import Settings, get_settings
from app.domain.assessment import PostgresAssessmentRepository
from app.domain.evidence import fetch_assessment_evidence
from app.domain.geocoding import build_open_data_geocoder
from app.domain.geocoding.postgis_bootstrap import fetch_postgis_geocoder_summary
from app.domain.layers import (
    LayerRecord,
    fetch_map_layer,
    fetch_map_layers,
)
from app.domain.reports.abuse import (
    RateLimitBackend,
    RateLimitExceeded,
    RateLimitUnavailable,
    check_rate_limit,
)
from app.domain.risk import score_risk

router = APIRouter(prefix="/v1", tags=["Public"])

_PUBLIC_RATE_LIMIT_MEMORY_ENVS = {"local", "development", "test"}


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


# Module-level wrappers keep these lookups monkeypatchable on this module while
# the implementations live in the geocoding service.
def _cached_nominatim_candidates(
    query: str,
    input_type: Literal["address", "landmark", "parcel"],
    limit: int,
) -> tuple[PlaceCandidate, ...]:
    settings = get_settings()
    return public_geocoding.cached_nominatim_candidates(
        query,
        input_type,
        limit,
        ttl_seconds=settings.geocode_cache_ttl_seconds,
        backend=settings.geocode_cache_backend,
        redis_url=settings.redis_url,
    )


def _cached_wikimedia_candidates(query: str, limit: int) -> tuple[PlaceCandidate, ...]:
    settings = get_settings()
    return public_geocoding.cached_wikimedia_candidates(
        query,
        limit,
        ttl_seconds=settings.geocode_cache_ttl_seconds,
        backend=settings.geocode_cache_backend,
        redis_url=settings.redis_url,
    )


def _build_geocoder():
    settings = get_settings()
    return build_open_data_geocoder(
        nominatim_lookup=_cached_nominatim_candidates,
        wikimedia_lookup=_cached_wikimedia_candidates,
        open_data_paths=settings.geocoder_open_data_paths,
        database_url=settings.database_url,
        postgis_enabled=settings.geocoder_postgis_enabled,
    )


@router.get("/geocoder/open-data/status", include_in_schema=False)
def geocoder_open_data_status() -> dict[str, Any]:
    settings = get_settings()
    payload: dict[str, Any] = {
        "checked_at": _now().isoformat(),
        "postgis_enabled": settings.geocoder_postgis_enabled,
        "bootstrap_enabled": settings.geocoder_postgis_bootstrap_enabled,
        "bundled_path_count": len(settings.geocoder_open_data_paths),
    }
    if not settings.geocoder_postgis_enabled or not settings.database_url:
        return {**payload, "status": "disabled", "row_count": 0, "source_counts": []}
    try:
        summary = fetch_postgis_geocoder_summary(settings.database_url)
    except (OSError, psycopg.Error):
        return {**payload, "status": "unavailable", "row_count": 0, "source_counts": []}

    row_count = int(summary.get("row_count") or 0)
    return {
        **payload,
        "status": "healthy" if row_count > 0 else "empty",
        "row_count": row_count,
        "source_counts": summary.get("source_counts") or [],
    }


def _legacy_static_layers(now: datetime) -> list[MapLayer]:
    return public_layers.legacy_static_layers(now)


def _static_layer_records(now: datetime) -> tuple[LayerRecord, ...]:
    return public_layers.static_layer_records(now)


def _map_layer_from_record(record: LayerRecord) -> MapLayer:
    return public_layers.map_layer_from_record(record)


def _localized_layer_name(record: LayerRecord) -> str:
    return public_layers.localized_layer_name(record)


def _localized_layer_description(record: LayerRecord) -> str | None:
    return public_layers.localized_layer_description(record)


def _localized_layer_attribution(record: LayerRecord) -> str | None:
    return public_layers.localized_layer_attribution(record)


def _layer_records(now: datetime) -> tuple[LayerRecord, ...]:
    return public_layers.layer_records(
        now,
        database_url=get_settings().database_url,
        fetch_layers=fetch_map_layers,
    )


def _static_layer_by_id(layer_id: str, now: datetime) -> LayerRecord | None:
    return public_layers.static_layer_by_id(layer_id, now)


def _layer_record(layer_id: str, now: datetime) -> LayerRecord | None:
    return public_layers.layer_record(
        layer_id,
        now,
        database_url=get_settings().database_url,
        fetch_layers=fetch_map_layers,
        fetch_layer=fetch_map_layer,
    )


def _layers(now: datetime) -> list[MapLayer]:
    return public_layers.layers(
        now,
        database_url=get_settings().database_url,
        fetch_layers=fetch_map_layers,
    )


def _enforce_public_rate_limit(
    request: FastAPIRequest,
    *,
    settings: Any,
    namespace: str,
    max_requests: int,
    endpoint_name: str,
) -> None:
    if not settings.public_rate_limit_enabled:
        return

    try:
        check_rate_limit(
            client_key=_public_rate_limit_client_key(
                request,
                settings=settings,
                namespace=namespace,
            ),
            namespace=namespace,
            backend=_public_rate_limit_backend(
                settings.app_env,
                settings.public_rate_limit_backend,
            ),
            redis_url=settings.redis_url,
            max_requests=max_requests,
            window_seconds=settings.public_rate_limit_window_seconds,
        )
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=429,
            headers={"Retry-After": str(exc.retry_after_seconds)},
            detail=error_payload(
                "rate_limited",
                f"{endpoint_name} rate limit exceeded. Try again later.",
                {
                    "retry_after_seconds": exc.retry_after_seconds,
                    "window_seconds": exc.policy.window_seconds,
                },
            )["error"],
        ) from exc
    except RateLimitUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=error_payload(
                "abuse_guard_unavailable",
                f"{endpoint_name} abuse guard is temporarily unavailable.",
            )["error"],
        ) from exc


def _public_rate_limit_backend(
    app_env: str,
    configured_backend: RateLimitBackend,
) -> RateLimitBackend:
    if app_env.strip().lower() in _PUBLIC_RATE_LIMIT_MEMORY_ENVS:
        return configured_backend
    return "redis"


def _public_rate_limit_client_key(
    request: FastAPIRequest,
    *,
    settings: Any,
    namespace: str,
) -> str:
    client_signal = resolve_client_signal(
        request,
        settings.public_rate_limit_client_header,
        settings.public_rate_limit_trusted_proxy_cidrs,
    )
    salt = settings.abuse_hash_salt or f"{settings.service_id}:{settings.app_env}"
    return sha256(f"{namespace}:{salt}:{client_signal}".encode()).hexdigest()


@router.post("/geocode", response_model=GeocodeResponse)
def geocode(
    request: GeocodeRequest,
    http_request: FastAPIRequest,
) -> GeocodeResponse:
    settings = get_settings()
    _enforce_public_rate_limit(
        http_request,
        settings=settings,
        namespace="public-geocode-rate",
        max_requests=settings.geocode_rate_limit_max_requests,
        endpoint_name="Geocode",
    )
    return GeocodeResponse(candidates=_build_geocoder().geocode(request))


@router.post("/risk/assess", response_model=RiskAssessmentResponse)
def assess_risk(
    request: RiskAssessRequest,
    http_request: FastAPIRequest,
) -> RiskAssessmentResponse:
    settings = get_settings()
    _enforce_public_rate_limit(
        http_request,
        settings=settings,
        namespace="public-risk-assess-rate",
        max_requests=settings.risk_assessment_rate_limit_max_requests,
        endpoint_name="Risk assessment",
    )
    return _assessment_service(settings).assess(request, now=_now())


def _assessment_service(settings: Settings) -> AssessmentService:
    return AssessmentService(
        PostgresAssessmentRepository(
            settings.database_url,
            enabled=settings.evidence_repository_enabled,
        ),
        score_risk,
        recent_history_lookup=OfficialRecentHistoryLookup(
            database_url=settings.database_url,
            enabled=(
                settings.evidence_repository_enabled
                and settings.official_nationwide_history_citations_enabled
            ),
            timeout_seconds=min(
                settings.historical_news_on_demand_timeout_seconds,
                3.0,
            ),
        ),
    )


@router.get("/evidence/{assessment_id}", response_model=EvidenceListResponse)
def list_evidence(
    assessment_id: UUID,
    cursor: str | None = None,
    page_size: int = Query(default=20, ge=1, le=100),
) -> EvidenceListResponse:
    del cursor
    settings = get_settings()
    return public_evidence.list_assessment_evidence(
        str(assessment_id),
        page_size=page_size,
        fetch_db_evidence=_assessment_db_evidence,
        backend=settings.risk_assessment_evidence_cache_backend,
        redis_url=settings.redis_url,
    )


def _assessment_db_evidence(assessment_id: str, *, page_size: int) -> tuple[Evidence, ...]:
    return public_evidence.assessment_db_evidence(
        assessment_id,
        page_size=page_size,
        database_url=get_settings().database_url,
        fetch_assessment_evidence=fetch_assessment_evidence,
    )


def _tilejson_from_layer_record(record: LayerRecord) -> TileJson:
    return public_layers.tilejson_from_layer_record(
        record,
        allow_local_tile_fallback=get_settings().tile_dynamic_fallback_enabled,
    )


@router.get("/layers", response_model=LayersResponse)
def list_layers() -> LayersResponse:
    return LayersResponse(layers=_layers(_now()))


@router.get(
    "/layers/{layer_id}/tilejson", response_model=TileJson, response_model_exclude_none=True
)
def get_layer_tilejson(layer_id: str) -> TileJson:
    layer = _layer_record(layer_id, _now())
    if layer is None:
        raise HTTPException(
            status_code=404,
            detail=error_payload("not_found", f"Layer '{layer_id}' was not found.")["error"],
        )
    try:
        return _tilejson_from_layer_record(layer)
    except public_layers.LayerTileJsonDisabled:
        raise HTTPException(
            status_code=404,
            detail=error_payload("layer_disabled", f"Layer '{layer_id}' is disabled.")["error"],
        ) from None
    except public_layers.LayerTileJsonUnavailable:
        raise HTTPException(
            status_code=503,
            detail=error_payload(
                "tiles_unavailable",
                f"Layer '{layer_id}' has no usable tile template.",
            )["error"],
        ) from None
