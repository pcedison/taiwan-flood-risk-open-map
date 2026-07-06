import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import re
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request as FastAPIRequest

from app.api.errors import error_payload
from app.api.schemas import (
    AttentionLevel,
    DataFreshness,
    Evidence,
    EvidenceListResponse,
    Explanation,
    GeocodeRequest,
    GeocodeResponse,
    GeoJsonGeometry,  # noqa: F401  (re-exported for tests)
    LatLng,  # noqa: F401  (re-exported for tests building Evidence payloads)
    LayersResponse,
    MapLayer,
    NearbyRealtimeCoverage,
    PlaceCandidate,
    QueryHeat,
    RiskAssessRequest,
    RiskAssessmentResponse,
    TileJson,
)
from app.api.services import (
    public_evidence,
    public_freshness,
    public_geocoding,
    public_layers,
    public_profiles,
    public_response_cache,
    public_risk,
)
from app.api.services.client_signal import resolve_client_signal
from app.core.config import get_settings
from app.domain.evidence import (
    EvidenceRecord,
    EvidenceRepositoryUnavailable,
    fetch_assessment_evidence,
    fetch_evidence_by_ids,
    fetch_query_heat_snapshot,
    persist_risk_assessment,
    query_nearby_evidence,
    RiskAssessmentPersistence,
    upsert_public_evidence,
)
from app.domain.evidence.repository import (
    query_nearby_latest_official,
    query_nearby_realtime_coverage_rows,
)
from app.domain.geocoding import build_open_data_geocoder
from app.domain.geocoding.postgis_bootstrap import fetch_postgis_geocoder_summary
from app.domain.history import (
    HistoricalFloodRecord,
    OfficialFloodDisasterLookup,
    lookup_official_flood_disaster_points,
    nearby_historical_flood_records,
    nearest_public_news_location_text,
)
from app.domain.history.news_enrichment import (
    OnDemandNewsSearchResult,
    search_public_flood_news,
)
from app.domain.layers import (
    LayerRecord,
    fetch_map_layer,
    fetch_map_layers,
)
from app.domain.realtime import (
    OfficialRealtimeBundle,
    OfficialRealtimeSourceStatus,  # noqa: F401  (re-exported for tests)
    fetch_official_realtime_bundle,
)
from app.domain.realtime.nearby_coverage import build_nearby_realtime_coverage
from app.domain.reports.abuse import (
    RateLimitBackend,
    RateLimitExceeded,
    RateLimitUnavailable,
    check_rate_limit,
)
from app.domain.profiles import (
    RiskProfileRecord,
    RiskProfileRepositoryUnavailable,
    enqueue_profile_refresh_job,
    fetch_best_profile_for_point,
)
from app.domain.risk import RiskScoringResult

router = APIRouter(prefix="/v1", tags=["Public"])

LOW_ATTENTION: AttentionLevel = "低"
LOCAL_HISTORICAL_FALLBACK_ENVS = {"local", "development", "test", "staging", "production-beta"}
_ASSESSMENT_EVIDENCE_CACHE = public_evidence._ASSESSMENT_EVIDENCE_CACHE
_RISK_ASSESSMENT_RESPONSE_CACHE = public_response_cache._MEMORY_CACHE
_PUBLIC_RATE_LIMIT_MEMORY_ENVS = {"local", "development", "test"}
_LATEST_OFFICIAL_RAW_REF_PREFIX = "official-realtime-latest:"
_LEGACY_OFFICIAL_STATION_SOURCES = {
    ("rainfall", "cwa-rainfall"): "official.cwa.rainfall",
    ("water_level", "wra-water-level"): "official.wra.water_level",
}
_STATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


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
    except Exception:
        return {**payload, "status": "unavailable", "row_count": 0, "source_counts": []}

    row_count = int(summary.get("row_count") or 0)
    return {
        **payload,
        "status": "healthy" if row_count > 0 else "empty",
        "row_count": row_count,
        "source_counts": summary.get("source_counts") or [],
    }


# Evidence/signal converters live in the evidence service; these aliases keep
# the names monkeypatchable on this module and wired into the dependency bag.
_official_realtime_evidence = public_evidence.official_realtime_evidence
_historical_record_evidence = public_evidence.historical_record_evidence
_evidence_from_upsert = public_evidence.evidence_from_upsert
_evidence_preview = public_evidence.evidence_preview
_signal_from_official_realtime = public_evidence.signal_from_official_realtime
_signal_from_historical_record = public_evidence.signal_from_historical_record
_signal_from_evidence = public_evidence.signal_from_evidence
_display_evidence_items = public_evidence.display_evidence_items
_official_flood_disaster_summary_item = public_evidence.official_flood_disaster_summary_item


def _fallback_historical_records(
    request: RiskAssessRequest,
) -> tuple[tuple[HistoricalFloodRecord, float], ...]:
    return nearby_historical_flood_records(
        lat=request.point.lat,
        lng=request.point.lng,
        radius_m=request.radius_m,
        location_text=request.location_text,
    )


def _official_flood_disaster_lookup(
    request: RiskAssessRequest,
    *,
    now: datetime,
) -> OfficialFloodDisasterLookup:
    settings = get_settings()
    return lookup_official_flood_disaster_points(
        lat=request.point.lat,
        lng=request.point.lng,
        radius_m=request.radius_m,
        csv_path=settings.official_flood_disaster_points_path,
        enabled=settings.official_flood_disaster_points_enabled,
        now=now,
    )


def _use_local_historical_fallback(app_env: str) -> bool:
    return app_env.strip().lower() in LOCAL_HISTORICAL_FALLBACK_ENVS


# Realtime official station relevance: a cold small-radius lookup still surfaces
# the nearest rainfall/water station so realtime risk is not reported as
# "即時資料不足" when a station sits just outside the query radius. Match the
# bridge's 10 km rainfall relevance; intensity-aware scoring keeps dry or light
# rain from overstating far-station risk.
REALTIME_RAINFALL_RELEVANCE_M = 10000
REALTIME_WATER_RELEVANCE_M = 3000
REALTIME_FLOOD_DEPTH_RELEVANCE_M = 1000
REALTIME_FLOOD_WARNING_RELEVANCE_M = 10000
REALTIME_OFFICIAL_LOOKBACK = timedelta(hours=3)
EVIDENCE_QUERY_STATEMENT_TIMEOUT_MS = 6000
ASSESSMENT_PERSIST_STATEMENT_TIMEOUT_MS = 1500


def _nearby_realtime_coverage(
    request: RiskAssessRequest,
    *,
    now: datetime,
) -> NearbyRealtimeCoverage:
    settings = get_settings()
    if not settings.evidence_repository_enabled:
        return _unavailable_nearby_realtime_coverage(request, now=now)
    try:
        rows = query_nearby_realtime_coverage_rows(
            database_url=settings.database_url,
            lat=request.point.lat,
            lng=request.point.lng,
            observed_since=now - REALTIME_OFFICIAL_LOOKBACK,
            statement_timeout_ms=EVIDENCE_QUERY_STATEMENT_TIMEOUT_MS,
        )
    except EvidenceRepositoryUnavailable:
        return _unavailable_nearby_realtime_coverage(request, now=now)
    return build_nearby_realtime_coverage(
        rows=rows,
        query_radius_m=request.radius_m,
        evaluated_at=now,
    )


def _unavailable_nearby_realtime_coverage(
    request: RiskAssessRequest,
    *,
    now: datetime,
) -> NearbyRealtimeCoverage:
    return build_nearby_realtime_coverage(
        rows=(),
        query_radius_m=request.radius_m,
        evaluated_at=now,
        repository_unavailable=True,
    )


def _nearby_db_evidence(request: RiskAssessRequest) -> tuple[Evidence, ...] | None:
    settings = get_settings()
    if not settings.evidence_repository_enabled:
        return None
    official_realtime_since = _now() - REALTIME_OFFICIAL_LOOKBACK
    try:
        latest_records = query_nearby_latest_official(
            database_url=settings.database_url,
            lat=request.point.lat,
            lng=request.point.lng,
            limit=50,
            rainfall_radius_m=REALTIME_RAINFALL_RELEVANCE_M,
            water_level_radius_m=REALTIME_WATER_RELEVANCE_M,
            flood_depth_radius_m=REALTIME_FLOOD_DEPTH_RELEVANCE_M,
            flood_warning_radius_m=REALTIME_FLOOD_WARNING_RELEVANCE_M,
            observed_since=official_realtime_since,
            statement_timeout_ms=EVIDENCE_QUERY_STATEMENT_TIMEOUT_MS,
        )
    except EvidenceRepositoryUnavailable:
        latest_records = ()

    try:
        evidence_records = query_nearby_evidence(
            database_url=settings.database_url,
            lat=request.point.lat,
            lng=request.point.lng,
            radius_m=request.radius_m,
            limit=50,
            rainfall_relevance_m=REALTIME_RAINFALL_RELEVANCE_M,
            water_relevance_m=REALTIME_WATER_RELEVANCE_M,
            official_realtime_since=official_realtime_since,
            statement_timeout_ms=EVIDENCE_QUERY_STATEMENT_TIMEOUT_MS,
        )
    except EvidenceRepositoryUnavailable:
        if settings.app_env in {"staging", "production", "production-beta"}:
            return None
        return None
    records = _merge_nearby_evidence_records(
        latest_records,
        evidence_records,
        limit=50,
    )
    return tuple(_evidence_from_record(record) for record in records)


def _merge_nearby_evidence_records(
    latest_records: tuple[EvidenceRecord, ...],
    evidence_records: tuple[EvidenceRecord, ...],
    *,
    limit: int,
) -> tuple[EvidenceRecord, ...]:
    merged: list[EvidenceRecord] = []
    seen: set[tuple[str, str]] = set()
    for record in (*latest_records, *evidence_records):
        dedupe_key = _nearby_evidence_dedupe_key(record)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        merged.append(record)
        if len(merged) >= limit:
            break
    return tuple(merged)


def _nearby_evidence_dedupe_key(record: EvidenceRecord) -> tuple[str, str]:
    station_key = _official_realtime_station_key(record)
    if station_key is not None:
        return (record.event_type, station_key)
    return (record.event_type, record.raw_ref or record.source_id)


def _official_realtime_station_key(record: EvidenceRecord) -> str | None:
    if record.raw_ref and record.raw_ref.startswith(_LATEST_OFFICIAL_RAW_REF_PREFIX):
        latest_key = _latest_official_station_key(record.raw_ref)
        if latest_key is not None:
            return latest_key

    if record.source_type != "official":
        return None
    return _legacy_official_station_key(record)


def _latest_official_station_key(raw_ref: str) -> str | None:
    payload = raw_ref.removeprefix(_LATEST_OFFICIAL_RAW_REF_PREFIX)
    parts = payload.split(":", 2)
    if len(parts) != 3:
        return None
    adapter_key, event_type, station_id = parts
    if not _is_valid_station_id(station_id):
        return None
    return f"{adapter_key}:{event_type}:{station_id}"


def _legacy_official_station_key(record: EvidenceRecord) -> str | None:
    parts = record.source_id.split(":", 2)
    if len(parts) != 3:
        return None
    source_head, station_id, observed_at = parts
    adapter_key = _LEGACY_OFFICIAL_STATION_SOURCES.get((record.event_type, source_head))
    if adapter_key is None:
        return None
    if not _is_valid_station_id(station_id):
        return None
    if not _is_iso_observed_at(observed_at):
        return None
    return f"{adapter_key}:{record.event_type}:{station_id}"


def _is_valid_station_id(station_id: str) -> bool:
    return bool(_STATION_ID_RE.fullmatch(station_id))


def _is_iso_observed_at(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _evidence_from_record(record: EvidenceRecord) -> Evidence:
    return public_evidence.evidence_from_record(record)


def _localized_evidence_text(record: EvidenceRecord) -> tuple[str, str]:
    return public_evidence.localized_evidence_text(record)


def _public_evidence_url(
    *,
    source_type: str,
    event_type: str,
    fallback_url: str | None,
) -> str | None:
    return public_evidence.public_evidence_url(
        source_type=source_type,
        event_type=event_type,
        fallback_url=fallback_url,
    )


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
    return sha256(f"{namespace}:{salt}:{client_signal}".encode("utf-8")).hexdigest()


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
    return public_risk.assess_risk(
        request,
        settings=settings,
        created_at=_now(),
        dependencies=_risk_assessment_dependencies(),
    )


def _risk_assessment_dependencies() -> public_risk.RiskAssessmentDependencies:
    return public_risk.RiskAssessmentDependencies(
        risk_assessment_response_cache_key=_risk_assessment_response_cache_key,
        cached_risk_assessment_response=_cached_risk_assessment_response,
        fetch_official_realtime_bundle=_official_realtime_bundle_for_risk,
        nearby_realtime_coverage=_nearby_realtime_coverage,
        nearby_db_evidence=_nearby_db_evidence,
        official_flood_disaster_lookup=_official_flood_disaster_lookup,
        can_use_profile_fast_path=_can_use_profile_fast_path,
        precomputed_risk_profile=_precomputed_risk_profile,
        profile_has_public_news=_profile_has_public_news,
        enqueue_profile_refresh=_enqueue_profile_refresh,
        profile_backed_response=_profile_backed_response,
        cache_risk_assessment_response=_cache_risk_assessment_response,
        fallback_historical_records=_fallback_historical_records,
        use_local_historical_fallback=_use_local_historical_fallback,
        on_demand_public_news_result=_on_demand_public_news_result,
        needs_historical_event_lookup=_needs_historical_event_lookup,
        persist_or_build_on_demand_evidence=_persist_or_build_on_demand_evidence,
        historical_data_freshness=_historical_data_freshness,
        display_evidence_items=_display_evidence_items,
        cache_assessment_evidence=_cache_assessment_evidence,
        persisted_official_realtime_data_freshness=_persisted_official_realtime_data_freshness,
        visible_source_limitations=_visible_source_limitations,
        official_flood_disaster_data_freshness=_official_flood_disaster_data_freshness,
        on_demand_data_freshness=_on_demand_data_freshness,
        persist_assessment=_persist_assessment,
        query_heat=_query_heat,
    )


def _official_realtime_bundle_for_risk(
    *,
    lat: float,
    lng: float,
    radius_m: int,
    cwa_authorization: str | None,
    enabled: bool,
    cwa_enabled: bool,
    wra_enabled: bool,
    now: datetime,
) -> OfficialRealtimeBundle:
    settings = get_settings()
    return fetch_official_realtime_bundle(
        lat=lat,
        lng=lng,
        radius_m=radius_m,
        cwa_authorization=cwa_authorization,
        enabled=enabled,
        cwa_enabled=cwa_enabled,
        wra_enabled=wra_enabled,
        now=now,
        app_env=settings.app_env,
        diagnostic_fallback_enabled=settings.realtime_official_diagnostic_fallback_enabled,
    )


# Freshness and source-limitation helpers live in the freshness service.
_persisted_official_realtime_data_freshness = (
    public_freshness.persisted_official_realtime_data_freshness
)


_can_use_profile_fast_path = public_profiles.can_use_profile_fast_path
_profile_has_public_news = public_profiles.profile_has_public_news


def _precomputed_risk_profile(
    request: RiskAssessRequest,
    *,
    now: datetime,
) -> RiskProfileRecord | None:
    settings = get_settings()
    if not settings.evidence_repository_enabled:
        return None
    try:
        profile = fetch_best_profile_for_point(
            database_url=settings.database_url,
            lat=request.point.lat,
            lng=request.point.lng,
            radius_m=request.radius_m,
            now=now,
        )
    except RiskProfileRepositoryUnavailable:
        return None
    if profile is None:
        return None
    if not public_profiles.profile_has_observed_history(profile):
        return None
    return profile


def _enqueue_profile_refresh(profile: RiskProfileRecord, *, request: RiskAssessRequest) -> None:
    settings = get_settings()
    if not settings.evidence_repository_enabled:
        return
    try:
        enqueue_profile_refresh_job(
            database_url=settings.database_url,
            profile_kind=profile.profile_kind,
            profile_key=profile.profile_key,
            priority=10,
            reason="cold_lookup_profile_refresh",
            # ADR-0006: job payloads persist in worker_runtime_jobs, so only
            # coarse (~1 km) coordinates and no raw query text may enter them.
            payload={
                "lat": round(request.point.lat, 2),
                "lng": round(request.point.lng, 2),
                "radius_m": request.radius_m,
            },
        )
    except RiskProfileRepositoryUnavailable:
        return


def _profile_backed_response(
    *,
    request: RiskAssessRequest,
    assessment_id: str,
    profile: RiskProfileRecord,
    realtime_bundle: OfficialRealtimeBundle,
    nearby_realtime_coverage: NearbyRealtimeCoverage,
    created_at: datetime,
) -> RiskAssessmentResponse:
    return public_profiles.profile_backed_response(
        request=request,
        assessment_id=assessment_id,
        profile=profile,
        realtime_bundle=realtime_bundle,
        nearby_realtime_coverage=nearby_realtime_coverage,
        created_at=created_at,
        top_evidence_items=_profile_top_evidence_items(profile),
        query_heat=_query_heat(request, now=created_at),
        cache_assessment_evidence=_cache_assessment_evidence,
    )


def _profile_top_evidence_items(profile: RiskProfileRecord) -> tuple[Evidence, ...]:
    if not profile.top_evidence_ids:
        return ()
    try:
        records = fetch_evidence_by_ids(
            database_url=get_settings().database_url,
            evidence_ids=profile.top_evidence_ids,
        )
    except EvidenceRepositoryUnavailable:
        return ()
    return tuple(_evidence_from_record(record) for record in records)


def _on_demand_public_news_result(
    request: RiskAssessRequest,
    *,
    now: datetime,
) -> OnDemandNewsSearchResult:
    settings = get_settings()
    location_text = nearest_public_news_location_text(
        lat=request.point.lat,
        lng=request.point.lng,
        radius_m=request.radius_m,
        preferred_text=request.location_text,
    )
    if not public_freshness.use_on_demand_public_news(settings):
        return OnDemandNewsSearchResult(
            attempted=bool(location_text),
            source_id="on-demand-public-news",
            message=(
                "公開新聞／Wiki 即時補查未啟用；系統仍會使用已匯入的官方快照、"
                "歷史事件與 citation-only 新聞證據。"
            ),
            records=(),
            health_status="disabled",
        )
    return search_public_flood_news(
        location_text=location_text,
        lat=request.point.lat,
        lng=request.point.lng,
        radius_m=request.radius_m,
        now=now,
        max_records=settings.historical_news_on_demand_max_records,
        timeout_seconds=settings.historical_news_on_demand_timeout_seconds,
    )


_needs_historical_event_lookup = public_freshness.needs_historical_event_lookup
_should_attempt_public_news_lookup = public_freshness.should_attempt_public_news_lookup


def _persist_or_build_on_demand_evidence(
    result: OnDemandNewsSearchResult,
    *,
    writeback_enabled: bool,
) -> tuple[Evidence, ...]:
    if not result.records:
        return ()
    if writeback_enabled:
        try:
            inserted = upsert_public_evidence(
                database_url=get_settings().database_url,
                records=result.records,
            )
            if inserted:
                return tuple(_evidence_from_record(record) for record in inserted)
        except EvidenceRepositoryUnavailable:
            pass
    return tuple(_evidence_from_upsert(record) for record in result.records)


_on_demand_data_freshness = public_freshness.on_demand_data_freshness
_official_flood_disaster_data_freshness = public_freshness.official_flood_disaster_data_freshness


def _cache_assessment_evidence(assessment_id: str, evidence_items: list[Evidence]) -> None:
    settings = get_settings()
    public_evidence.cache_assessment_evidence(
        assessment_id,
        evidence_items,
        ttl_seconds=settings.risk_assessment_evidence_cache_ttl_seconds,
        backend=settings.risk_assessment_evidence_cache_backend,
        redis_url=settings.redis_url,
    )


def _risk_assessment_response_cache_key(request: RiskAssessRequest, settings: Any) -> str:
    return json.dumps(
        {
            "lat": round(request.point.lat, 5),
            "lng": round(request.point.lng, 5),
            "radius_m": request.radius_m,
            "time_context": request.time_context,
            "location_text": (request.location_text or "").strip(),
            "app_env": settings.app_env,
            "cache_version": "realtime-evidence-v3-nearby-coverage",
            "realtime_official_enabled": settings.realtime_official_enabled,
            "realtime_official_diagnostic_fallback_enabled": (
                settings.realtime_official_diagnostic_fallback_enabled
            ),
            "source_cwa_api_enabled": settings.source_cwa_api_enabled,
            "source_wra_api_enabled": settings.source_wra_api_enabled,
            "source_news_enabled": settings.source_news_enabled,
            "source_terms_review_ack": settings.source_terms_review_ack,
            "historical_news_on_demand_enabled": (
                settings.historical_news_on_demand_enabled
            ),
            "historical_news_on_demand_writeback_enabled": (
                settings.historical_news_on_demand_writeback_enabled
            ),
            "historical_news_on_demand_max_records": (
                settings.historical_news_on_demand_max_records
            ),
            "historical_news_on_demand_timeout_seconds": (
                settings.historical_news_on_demand_timeout_seconds
            ),
            "official_flood_disaster_points_enabled": (
                settings.official_flood_disaster_points_enabled
            ),
            "evidence_repository_enabled": settings.evidence_repository_enabled,
        },
        ensure_ascii=True,
        sort_keys=True,
    )


def _cached_risk_assessment_response(
    cache_key: str,
    *,
    now: datetime,
    ttl_seconds: int,
) -> RiskAssessmentResponse | None:
    settings = get_settings()
    return public_response_cache.cached_response(
        cache_key,
        now=now,
        ttl_seconds=ttl_seconds,
        backend=settings.risk_assessment_response_cache_backend,
        redis_url=settings.redis_url,
    )


def _cache_risk_assessment_response(
    cache_key: str,
    response: RiskAssessmentResponse,
    *,
    now: datetime,
    ttl_seconds: int,
) -> None:
    settings = get_settings()
    public_response_cache.store_response(
        cache_key,
        response,
        now=now,
        ttl_seconds=ttl_seconds,
        backend=settings.risk_assessment_response_cache_backend,
        redis_url=settings.redis_url,
    )


def _persist_assessment(
    *,
    assessment_id: str,
    request: RiskAssessRequest,
    scoring: RiskScoringResult,
    explanation: Explanation,
    data_freshness: list[DataFreshness],
    evidence_items: list[Evidence],
    nearby_realtime_coverage: NearbyRealtimeCoverage,
    created_at: datetime,
    expires_at: datetime,
) -> None:
    settings = get_settings()
    if not settings.evidence_repository_enabled:
        return
    try:
        persist_risk_assessment(
            database_url=settings.database_url,
            assessment=RiskAssessmentPersistence(
                assessment_id=assessment_id,
                lat=request.point.lat,
                lng=request.point.lng,
                radius_m=request.radius_m,
                score_version=scoring.score_version,
                realtime_score=scoring.realtime_score,
                historical_score=scoring.historical_score,
                confidence_score=scoring.confidence_score,
                realtime_level=scoring.realtime_level,
                historical_level=scoring.historical_level,
                explanation=explanation.model_dump(mode="json"),
                data_freshness=[item.model_dump(mode="json") for item in data_freshness],
                result_snapshot=public_risk.assessment_result_snapshot(
                    assessment_id=assessment_id,
                    request=request,
                    scoring=scoring,
                    explanation=explanation,
                    data_freshness=data_freshness,
                    evidence_items=evidence_items,
                    nearby_realtime_coverage=nearby_realtime_coverage,
                    created_at=created_at,
                    expires_at=expires_at,
                ),
                evidence_ids=tuple(item.id for item in evidence_items),
                created_at=created_at,
                expires_at=expires_at,
            ),
            statement_timeout_ms=ASSESSMENT_PERSIST_STATEMENT_TIMEOUT_MS,
        )
    except EvidenceRepositoryUnavailable:
        return


def _query_heat(request: RiskAssessRequest, *, now: datetime) -> QueryHeat:
    settings = get_settings()
    if not settings.evidence_repository_enabled:
        return QueryHeat(
            period="P7D",
            attention_level=LOW_ATTENTION,
            query_count_bucket="limited-db-disabled",
            unique_approx_count_bucket="limited-db-disabled",
            updated_at=now,
        )
    try:
        snapshot = fetch_query_heat_snapshot(
            database_url=settings.database_url,
            lat=request.point.lat,
            lng=request.point.lng,
            radius_m=request.radius_m,
            period="P7D",
        )
    except EvidenceRepositoryUnavailable:
        return QueryHeat(
            period="P7D",
            attention_level=LOW_ATTENTION,
            query_count_bucket="limited-db-unavailable",
            unique_approx_count_bucket="limited-db-unavailable",
            updated_at=now,
        )

    return QueryHeat(
        period=snapshot.period,
        attention_level=LOW_ATTENTION,
        query_count_bucket=snapshot.query_count_bucket,
        unique_approx_count_bucket=snapshot.unique_approx_count_bucket,
        updated_at=snapshot.updated_at,
    )


_historical_data_freshness = public_freshness.historical_data_freshness


def _historical_scoring_distance(
    *,
    record: HistoricalFloodRecord,
    distance_to_query_m: float,
    radius_m: int,
    location_text: str | None,
) -> float:
    return distance_to_query_m


_freshness_from_status = public_freshness.freshness_from_status
_visible_source_limitations = public_freshness.visible_source_limitations


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


@router.get("/layers/{layer_id}/tilejson", response_model=TileJson, response_model_exclude_none=True)
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
            detail=error_payload("layer_disabled", f"Layer '{layer_id}' is disabled.")[
                "error"
            ],
        ) from None
    except public_layers.LayerTileJsonUnavailable:
        raise HTTPException(
            status_code=503,
            detail=error_payload(
                "tiles_unavailable",
                f"Layer '{layer_id}' has no usable tile template.",
            )["error"],
        ) from None
