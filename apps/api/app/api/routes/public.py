import json
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from hashlib import sha256
from typing import Any, Literal, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request as FastAPIRequest

from app.api.errors import error_payload
from app.api.schemas import (
    AttentionLevel,
    DataFreshness,
    Evidence,
    EvidenceListResponse,
    EvidencePreview,
    Explanation,
    ConfidenceBlock,
    GeocodeRequest,
    GeocodeResponse,
    GeoJsonGeometry,
    LatLng,
    LayersResponse,
    MapLayer,
    PlaceCandidate,
    QueryHeat,
    RiskAssessRequest,
    RiskAssessmentResponse,
    RiskLevelBlock,
    TileJson,
)
from app.api.services import public_evidence, public_layers, public_risk
from app.core.config import get_settings
from app.domain.evidence import (
    EvidenceRecord,
    EvidenceRepositoryUnavailable,
    EvidenceUpsert,
    fetch_assessment_evidence,
    fetch_evidence_by_ids,
    fetch_query_heat_snapshot,
    persist_risk_assessment,
    query_nearby_evidence,
    RiskAssessmentPersistence,
    upsert_public_evidence,
)
from app.domain.geocoding import (
    build_open_data_geocoder,
    candidate_type_for_precision,
    geocode_limitations,
    nominatim_precision,
    requires_geocode_confirmation,
    stable_uuid,
    within_taiwan_bounds,
)
from app.domain.geocoding.postgis_bootstrap import fetch_postgis_geocoder_summary
from app.domain.history import (
    HistoricalFloodRecord,
    OfficialFloodDisasterLookup,
    historical_record_matches_location_text,
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
    OfficialRealtimeObservation,
    OfficialRealtimeSourceStatus,
    fetch_official_realtime_bundle,
)
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
from app.domain.risk import RiskEvidenceSignal, RiskScoringResult, score_risk

router = APIRouter(prefix="/v1", tags=["Public"])

LOW_ATTENTION: AttentionLevel = "低"
NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
WIKIMEDIA_API_URL = "https://zh.wikipedia.org/w/api.php"
NOMINATIM_USER_AGENT = "FloodRiskTaiwan/0.1 local-development"
TAIWAN_VIEWBOX = "119.2,25.5,122.3,21.7"
LOCAL_HISTORICAL_FALLBACK_ENVS = {"local", "development", "test", "staging", "production-beta"}
OBSERVED_HISTORICAL_EVENT_TYPES = {"flood_report", "road_closure"}
OFFICIAL_FLOOD_DISASTER_SOURCE_PREFIX = "data-gov-130016:"
HOSTED_RUNTIME_ENVS = {"staging", "production", "production-beta"}
OFFICIAL_DATA_GOV_URLS = public_evidence.OFFICIAL_DATA_GOV_URLS
_ASSESSMENT_EVIDENCE_CACHE = public_evidence._ASSESSMENT_EVIDENCE_CACHE
_RISK_ASSESSMENT_RESPONSE_CACHE: dict[str, tuple[datetime, RiskAssessmentResponse]] = {}
_PROFILE_SOURCE_TYPE_FALLBACKS = {
    "official": "official",
    "news": "news",
    "forum": "forum",
    "social": "social",
    "user_report": "user_report",
}
_PROFILE_EVENT_TYPE_FALLBACKS = {
    "rainfall",
    "water_level",
    "flood_warning",
    "flood_potential",
    "flood_report",
    "road_closure",
    "discussion",
}
_PUBLIC_RATE_LIMIT_MEMORY_ENVS = {"local", "development", "test"}


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


@lru_cache(maxsize=512)
def _cached_nominatim_candidates(
    query: str,
    input_type: Literal["address", "landmark", "parcel"],
    limit: int,
) -> tuple[PlaceCandidate, ...]:
    params = urlencode(
        {
            "q": query,
            "format": "jsonv2",
            "limit": limit,
            "countrycodes": "tw",
            "viewbox": TAIWAN_VIEWBOX,
            "bounded": 1,
            "accept-language": "zh-TW,zh,en",
        }
    )
    http_request = Request(
        f"{NOMINATIM_SEARCH_URL}?{params}",
        headers={
            "Accept": "application/json",
            "User-Agent": NOMINATIM_USER_AGENT,
        },
        method="GET",
    )
    try:
        with urlopen(http_request, timeout=2.5) as response:
            payload: Any = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return ()

    if not isinstance(payload, list):
        return ()

    candidates: list[PlaceCandidate] = []
    for index, item in enumerate(payload[:limit]):
        if not isinstance(item, dict):
            continue
        lat = _float_from_payload(item.get("lat"))
        lng = _float_from_payload(item.get("lon"))
        if lat is None or lng is None:
            continue
        display_name = item.get("display_name")
        precision = nominatim_precision(item, input_type)
        confidence = max(0.5, 0.9 - (index * 0.08))
        candidates.append(
            PlaceCandidate(
                place_id=stable_uuid("nominatim", item.get("osm_type"), item.get("osm_id"), index),
                name=str(item.get("name") or query or display_name),
                type=candidate_type_for_precision(input_type, precision),
                point=LatLng(lat=lat, lng=lng),
                admin_code=None,
                source="openstreetmap-nominatim",
                confidence=confidence,
                precision=precision,
                matched_query=query,
                requires_confirmation=requires_geocode_confirmation(precision, confidence),
                limitations=geocode_limitations(precision),
            )
        )
    return tuple(candidates)


@lru_cache(maxsize=512)
def _cached_wikimedia_candidates(query: str, limit: int) -> tuple[PlaceCandidate, ...]:
    search_params = urlencode(
        {
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": query,
            "srlimit": min(max(limit, 1), 5),
            "utf8": 1,
            "origin": "*",
        }
    )
    search_payload = _fetch_json(f"{WIKIMEDIA_API_URL}?{search_params}")
    search_results = search_payload.get("query", {}).get("search", [])
    if not isinstance(search_results, list) or not search_results:
        return ()

    page_ids = [
        str(item.get("pageid"))
        for item in search_results
        if isinstance(item, dict) and item.get("pageid") is not None
    ][:5]
    if not page_ids:
        return ()

    coord_params = urlencode(
        {
            "action": "query",
            "format": "json",
            "pageids": "|".join(page_ids),
            "prop": "coordinates",
            "colimit": "max",
            "origin": "*",
        }
    )
    coord_payload = _fetch_json(f"{WIKIMEDIA_API_URL}?{coord_params}")
    pages = coord_payload.get("query", {}).get("pages", {})
    if not isinstance(pages, dict):
        return ()

    candidates: list[PlaceCandidate] = []
    for index, page_id in enumerate(page_ids):
        page = pages.get(page_id)
        if not isinstance(page, dict):
            continue
        coordinates = page.get("coordinates")
        if not isinstance(coordinates, list) or not coordinates:
            continue
        coordinate = coordinates[0]
        if not isinstance(coordinate, dict):
            continue
        lat = _float_from_payload(coordinate.get("lat"))
        lng = _float_from_payload(coordinate.get("lon"))
        if lat is None or lng is None or not within_taiwan_bounds(lat, lng):
            continue
        title = str(page.get("title") or query)
        candidates.append(
            PlaceCandidate(
                place_id=stable_uuid("wikimedia", page_id, index),
                name=title,
                type="landmark",
                point=LatLng(lat=lat, lng=lng),
                admin_code=None,
                source="wikimedia-coordinates",
                confidence=max(0.66, 0.84 - (index * 0.06)),
                precision="poi",
                matched_query=query,
                requires_confirmation=False,
                limitations=geocode_limitations("poi"),
            )
        )
        if len(candidates) >= limit:
            break
    return tuple(candidates)


def _fetch_json(url: str) -> dict[str, Any]:
    http_request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": NOMINATIM_USER_AGENT,
        },
        method="GET",
    )
    try:
        with urlopen(http_request, timeout=3.5) as response:
            payload: Any = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _float_from_payload(value: object) -> float | None:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


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
async def geocoder_open_data_status() -> dict[str, Any]:
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


def _official_realtime_evidence(
    observation: OfficialRealtimeObservation,
) -> Evidence:
    return Evidence(
        id=stable_uuid("official-realtime", observation.source_id),
        source_id=observation.source_id,
        source_type="official",
        event_type=observation.event_type,
        title=observation.title,
        summary=observation.summary,
        url=OFFICIAL_DATA_GOV_URLS.get(observation.event_type),
        occurred_at=None,
        observed_at=observation.observed_at,
        ingested_at=observation.ingested_at,
        point=LatLng(lat=observation.lat, lng=observation.lng),
        geometry=GeoJsonGeometry(type="Point", coordinates=[observation.lng, observation.lat]),
        distance_to_query_m=observation.distance_to_query_m,
        confidence=observation.confidence,
        freshness_score=observation.freshness_score,
        source_weight=observation.source_weight,
        privacy_level="public",
        raw_ref=f"official-realtime:{observation.source_id}",
    )


def _historical_record_evidence(
    record: HistoricalFloodRecord,
    *,
    distance_to_query_m: float,
) -> Evidence:
    return Evidence(
        id=stable_uuid("historical-flood-record", record.source_id),
        source_id=record.source_id,
        source_type=record.source_type,
        event_type=record.event_type,
        title=record.title,
        summary=record.summary,
        url=_public_evidence_url(
            source_type=record.source_type,
            event_type=record.event_type,
            fallback_url=record.url,
        ),
        occurred_at=record.occurred_at,
        observed_at=record.occurred_at,
        ingested_at=record.ingested_at,
        point=LatLng(lat=record.lat, lng=record.lng),
        geometry=GeoJsonGeometry(type="Point", coordinates=[record.lng, record.lat]),
        distance_to_query_m=distance_to_query_m,
        confidence=record.confidence,
        freshness_score=record.freshness_score,
        source_weight=record.source_weight,
        privacy_level="public",
        raw_ref=f"historical-record:{record.source_id}",
    )


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


def _nearby_db_evidence(request: RiskAssessRequest) -> tuple[Evidence, ...] | None:
    settings = get_settings()
    if not settings.evidence_repository_enabled:
        return None
    try:
        records = query_nearby_evidence(
            database_url=settings.database_url,
            lat=request.point.lat,
            lng=request.point.lng,
            radius_m=request.radius_m,
            limit=50,
        )
    except EvidenceRepositoryUnavailable:
        if settings.app_env in {"staging", "production", "production-beta"}:
            return ()
        return None
    return tuple(_evidence_from_record(record) for record in records)


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


def _evidence_preview(evidence: Evidence) -> EvidencePreview:
    return EvidencePreview(
        id=evidence.id,
        source_type=evidence.source_type,
        event_type=evidence.event_type,
        title=evidence.title,
        summary=evidence.summary,
        occurred_at=evidence.occurred_at,
        observed_at=evidence.observed_at,
        ingested_at=evidence.ingested_at,
        distance_to_query_m=evidence.distance_to_query_m,
        confidence=evidence.confidence,
        url=evidence.url,
    )


def _signal_from_official_realtime(observation: OfficialRealtimeObservation) -> RiskEvidenceSignal:
    return RiskEvidenceSignal(
        source_type="official",
        event_type=observation.event_type,
        confidence=observation.confidence,
        distance_to_query_m=observation.distance_to_query_m,
        freshness_score=observation.freshness_score,
        source_weight=observation.source_weight,
        risk_factor=observation.risk_factor,
        observed_at=observation.observed_at,
    )


def _signal_from_historical_record(
    record: HistoricalFloodRecord,
    *,
    distance_to_query_m: float,
) -> RiskEvidenceSignal:
    return RiskEvidenceSignal(
        source_type=record.source_type,
        event_type=record.event_type,
        confidence=record.confidence,
        distance_to_query_m=distance_to_query_m,
        freshness_score=record.freshness_score,
        source_weight=record.source_weight,
        risk_factor=record.risk_factor,
        observed_at=record.occurred_at,
    )


def _signal_from_evidence(evidence: Evidence) -> RiskEvidenceSignal:
    return RiskEvidenceSignal(
        source_type=evidence.source_type,
        event_type=evidence.event_type,
        confidence=evidence.confidence,
        distance_to_query_m=evidence.distance_to_query_m,
        freshness_score=evidence.freshness_score,
        source_weight=evidence.source_weight,
        risk_factor=1.0,
        observed_at=evidence.observed_at or evidence.occurred_at,
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
    client_signal = _client_signal(request, settings.public_rate_limit_client_header)
    salt = settings.abuse_hash_salt or f"{settings.service_id}:{settings.app_env}"
    return sha256(f"{namespace}:{salt}:{client_signal}".encode("utf-8")).hexdigest()


def _client_signal(request: FastAPIRequest, configured_header: str | None) -> str:
    if configured_header:
        header_value = request.headers.get(configured_header)
        if header_value:
            configured_signal = header_value.split(",", 1)[0].strip()
            if configured_signal:
                return configured_signal
    if request.client is None:
        return "unknown-client"
    return request.client.host


@router.post("/geocode", response_model=GeocodeResponse)
async def geocode(
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
async def assess_risk(
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
        should_attempt_public_news_lookup=_should_attempt_public_news_lookup,
        on_demand_public_news_result=_on_demand_public_news_result,
        historical_record_evidence=_historical_record_evidence,
        evidence_from_upsert=_evidence_from_upsert,
        signal_from_historical_record=_signal_from_historical_record,
        historical_scoring_distance=_historical_scoring_distance,
        signal_from_evidence=_signal_from_evidence,
        needs_historical_event_lookup=_needs_historical_event_lookup,
        persist_or_build_on_demand_evidence=_persist_or_build_on_demand_evidence,
        historical_data_freshness=_historical_data_freshness,
        official_realtime_evidence=_official_realtime_evidence,
        display_evidence_items=_display_evidence_items,
        score_risk=score_risk,
        signal_from_official_realtime=_signal_from_official_realtime,
        cache_assessment_evidence=_cache_assessment_evidence,
        persisted_official_realtime_data_freshness=_persisted_official_realtime_data_freshness,
        visible_source_limitations=_visible_source_limitations,
        freshness_from_status=_freshness_from_status,
        official_flood_disaster_data_freshness=_official_flood_disaster_data_freshness,
        on_demand_data_freshness=_on_demand_data_freshness,
        persist_assessment=_persist_assessment,
        evidence_preview=_evidence_preview,
        query_heat=_query_heat,
    )


def _display_evidence_items(evidence_items: list[Evidence]) -> list[Evidence]:
    evidence_items = _collapse_official_flood_disaster_items(evidence_items)
    return _collapse_flood_potential_items(evidence_items)


def _collapse_flood_potential_items(evidence_items: list[Evidence]) -> list[Evidence]:
    flood_potential_items = [
        item for item in evidence_items if item.event_type == "flood_potential"
    ]
    if len(flood_potential_items) <= 1:
        return evidence_items

    non_flood_potential_items = [
        item for item in evidence_items if item.event_type != "flood_potential"
    ]
    representative = flood_potential_items[0].model_copy(
        update={
            "title": "官方淹水潛勢規劃圖資",
            "summary": (
                f"查詢範圍與 {len(flood_potential_items)} 筆官方淹水潛勢規劃圖資相交，"
                "已合併為一筆代表資料顯示；這是歷史與情境參考，不代表目前正在淹水。"
            ),
        }
    )
    return [*non_flood_potential_items, representative]


def _collapse_official_flood_disaster_items(evidence_items: list[Evidence]) -> list[Evidence]:
    official_items = [
        item for item in evidence_items if _is_official_flood_disaster_item(item)
    ]
    if len(official_items) <= 1:
        return evidence_items

    representative = _official_flood_disaster_summary_item(official_items)
    collapsed: list[Evidence] = []
    inserted = False
    for item in evidence_items:
        if not _is_official_flood_disaster_item(item):
            collapsed.append(item)
            continue
        if not inserted:
            collapsed.append(representative)
            inserted = True
    return collapsed


def _is_official_flood_disaster_item(item: Evidence) -> bool:
    return (
        item.source_type == "official"
        and item.event_type == "flood_report"
        and item.source_id.startswith(OFFICIAL_FLOOD_DISASTER_SOURCE_PREFIX)
    )


def _official_flood_disaster_summary_item(items: list[Evidence]) -> Evidence:
    closest_item = min(
        items,
        key=lambda item: item.distance_to_query_m
        if item.distance_to_query_m is not None
        else float("inf"),
    )
    candidate_times = [
        value
        for item in items
        for value in (item.observed_at, item.occurred_at)
        if value is not None
    ]
    latest_observed = max(candidate_times) if candidate_times else (
        closest_item.observed_at or closest_item.occurred_at
    )
    years = sorted(
        {
            value.year
            for item in items
            for value in (item.observed_at or item.occurred_at,)
            if value is not None
        }
    )
    year_label = _year_label(years)
    return closest_item.model_copy(
        update={
            "id": stable_uuid(
                "official-flood-disaster-summary",
                len(items),
                ",".join(sorted(item.source_id for item in items)),
            ),
            "source_id": "data-gov-130016:summary",
            "title": f"官方淹水災害情資點位彙整（{year_label}）",
            "summary": (
                f"查詢半徑內命中 {len(items)} 筆 data.gov.tw 130016 官方淹水災點快照，"
                f"命中年份：{year_label}。已合併為一筆代表資料顯示，以避免同一官方快照"
                "在證據清單重複佔版面；風險計分仍使用原始命中點位。"
            ),
            "observed_at": latest_observed,
            "occurred_at": latest_observed,
            "distance_to_query_m": min(
                (item.distance_to_query_m for item in items if item.distance_to_query_m is not None),
                default=None,
            ),
            "confidence": max(item.confidence for item in items),
            "freshness_score": max(item.freshness_score for item in items),
            "source_weight": max(item.source_weight for item in items),
            "raw_ref": f"historical-record:data-gov-130016:summary:{len(items)}",
        }
    )


def _year_label(years: list[int]) -> str:
    if not years:
        return "年份未提供"
    if len(years) <= 3:
        return "、".join(str(year) for year in years)
    return f"{years[0]}-{years[-1]}"


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
    if (
        settings.app_env.strip().lower() in HOSTED_RUNTIME_ENVS
        and not settings.realtime_official_diagnostic_fallback_enabled
    ):
        return OfficialRealtimeBundle(
            observations=(),
            source_statuses=(
                _diagnostic_realtime_disabled_status(
                    "cwa-rainfall",
                    "中央氣象署即時雨量",
                    now,
                ),
                _diagnostic_realtime_disabled_status(
                    "wra-water-level",
                    "水利署即時水位",
                    now,
                ),
            ),
        )
    return fetch_official_realtime_bundle(
        lat=lat,
        lng=lng,
        radius_m=radius_m,
        cwa_authorization=cwa_authorization,
        enabled=enabled,
        cwa_enabled=cwa_enabled,
        wra_enabled=wra_enabled,
        now=now,
    )


def _diagnostic_realtime_disabled_status(
    source_id: str,
    name: str,
    checked_at: datetime,
) -> OfficialRealtimeSourceStatus:
    return OfficialRealtimeSourceStatus(
        source_id=source_id,
        name=name,
        health_status="degraded",
        observed_at=None,
        ingested_at=checked_at,
        message=_hosted_realtime_unavailable_message(source_id=source_id, name=name),
    )


def _hosted_realtime_unavailable_message(*, source_id: str, name: str) -> str:
    if source_id == "cwa-rainfall":
        return (
            "正式站採用系統定期保存的中央氣象署即時雨量作為可信來源；"
            "目前查詢半徑內尚未取得可用的雨量快照，因此不判定即時雨量風險。"
        )
    if source_id == "wra-water-level":
        return (
            "正式站採用系統定期保存的水利署即時水位作為可信來源；"
            "目前查詢半徑內尚未取得可用的水位快照，因此不判定即時水位風險。"
        )
    return (
        f"正式站採用系統定期保存的{name}作為可信來源；"
        "目前尚未取得可用快照，因此不使用未受監控的即時 API 備援查詢。"
    )


def _persisted_official_realtime_data_freshness(
    evidence_items: tuple[Evidence, ...],
    *,
    now: datetime,
) -> list[DataFreshness]:
    freshness_items: list[DataFreshness] = []
    for event_type, source_id, name in (
        ("rainfall", "cwa-rainfall", "中央氣象署即時雨量"),
        ("water_level", "wra-water-level", "水利署即時水位"),
    ):
        source_items = [
            item
            for item in evidence_items
            if item.source_type == "official" and item.event_type == event_type
        ]
        if not source_items:
            continue
        observed_values: list[datetime] = []
        for item in source_items:
            observed_value = item.observed_at or item.occurred_at
            if observed_value is not None:
                observed_values.append(observed_value)
        latest_observed = max(observed_values) if observed_values else None
        latest_ingested = max(item.ingested_at for item in source_items)
        is_fresh = (
            latest_observed is not None
            and _is_recent_official_realtime_observation(latest_observed, now)
        )
        freshness_items.append(
            DataFreshness(
                source_id=source_id,
                name=name,
                health_status="healthy" if is_fresh else "degraded",
                observed_at=latest_observed,
                ingested_at=latest_ingested,
                feature_count=len(source_items),
                message=(
                    f"已使用 {len(source_items)} 筆系統定期保存的{name}，"
                    "作為正式站可信來源。"
                    if is_fresh
                    else (
                        f"系統定期保存的{name}已過期或缺少觀測時間；"
                        "正式站不使用未受監控的即時 API 備援查詢，因此暫不判定此即時來源風險。"
                    )
                ),
            )
        )
    return freshness_items


def _is_recent_official_realtime_observation(observed_at: datetime, now: datetime) -> bool:
    comparable_observed_at = observed_at
    if comparable_observed_at.tzinfo is None and now.tzinfo is not None:
        comparable_observed_at = comparable_observed_at.replace(tzinfo=now.tzinfo)
    comparable_now = now
    if comparable_now.tzinfo is None and comparable_observed_at.tzinfo is not None:
        comparable_now = comparable_now.replace(tzinfo=comparable_observed_at.tzinfo)
    return comparable_now - timedelta(hours=6) <= comparable_observed_at <= (
        comparable_now + timedelta(minutes=5)
    )


def _can_use_profile_fast_path(db_evidence_items: tuple[Evidence, ...] | None) -> bool:
    if db_evidence_items is None:
        return False
    return not any(item.event_type in OBSERVED_HISTORICAL_EVENT_TYPES for item in db_evidence_items)


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
    if not _profile_has_observed_history(profile):
        return None
    return profile


def _profile_has_observed_history(profile: RiskProfileRecord) -> bool:
    for count_key, raw_count in profile.evidence_counts.items():
        count = _positive_int(raw_count)
        if count is None:
            continue
        _, event_type = _profile_count_key_types(count_key)
        if event_type in OBSERVED_HISTORICAL_EVENT_TYPES:
            return True
    return False


def _profile_has_public_news(profile: RiskProfileRecord) -> bool:
    for count_key, raw_count in profile.evidence_counts.items():
        count = _positive_int(raw_count)
        if count is None:
            continue
        source_type, event_type = _profile_count_key_types(count_key)
        if source_type == "news" and event_type in OBSERVED_HISTORICAL_EVENT_TYPES:
            return True
    return False


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
            payload={
                "lat": request.point.lat,
                "lng": request.point.lng,
                "radius_m": request.radius_m,
                "location_text": request.location_text,
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
    created_at: datetime,
) -> RiskAssessmentResponse:
    realtime_scoring = score_risk(
        tuple(_signal_from_official_realtime(observation) for observation in realtime_bundle.observations),
        now=created_at,
    )
    realtime_level = (
        realtime_scoring.realtime_level
        if realtime_scoring.realtime_level != "未知"
        else _public_risk_level(profile.realtime_level)
    )
    historical_level = _public_risk_level(profile.historical_level)
    confidence_level = _public_confidence_level(profile.confidence_level)
    expires_at = profile.expires_at or created_at + timedelta(minutes=5)
    data_freshness = [
        *(_freshness_from_status(status) for status in realtime_bundle.source_statuses),
        _profile_data_freshness(profile, now=created_at),
    ]
    profile_evidence_items = _profile_evidence_items(
        profile,
        request=request,
        created_at=created_at,
    )
    _cache_assessment_evidence(assessment_id, profile_evidence_items)
    explanation = Explanation(
        summary=(
            "此結果先使用預先計算的區域風險 profile 回應，"
            "精準半徑資料會由背景工作重新整理；請視為 beta 初步參考。"
        ),
        main_reasons=_profile_main_reasons(profile),
        missing_sources=_profile_missing_source_messages(profile),
    )
    return RiskAssessmentResponse(
        assessment_id=assessment_id,
        location=request.point,
        radius_m=request.radius_m,
        score_version=profile.score_version,
        created_at=created_at,
        expires_at=expires_at,
        realtime=RiskLevelBlock(level=realtime_level),
        historical=RiskLevelBlock(level=historical_level),
        confidence=ConfidenceBlock(level=confidence_level),
        explanation=explanation,
        evidence=[_evidence_preview(item) for item in profile_evidence_items],
        data_freshness=data_freshness,
        query_heat=_query_heat(request, now=created_at),
    )


def _profile_data_freshness(profile: RiskProfileRecord, *, now: datetime) -> DataFreshness:
    return DataFreshness(
        source_id="precomputed-risk-profile",
        name="預先計算區域風險 profile",
        health_status="healthy" if profile.status == "healthy" else "degraded",
        observed_at=profile.latest_observed_at or profile.latest_occurred_at,
        ingested_at=profile.latest_ingested_at or profile.computed_at or now,
        feature_count=_profile_evidence_total(profile),
        message=(
            f"已使用預先計算的 {profile.profile_kind}:{profile.profile_scope} profile；"
            f"範圍半徑約 {profile.profile_radius_m} 公尺，"
            f"計算時間 {profile.computed_at.isoformat()}。"
        ),
    )


def _profile_main_reasons(profile: RiskProfileRecord) -> list[str]:
    reasons = [
        f"已命中預先計算的 {profile.profile_kind}:{profile.profile_scope} 區域風險 profile。",
    ]
    if profile.evidence_counts:
        reasons.append(
            f"歷史參考來自 profile 彙整的 {_profile_evidence_total(profile)} 筆公開資料："
            + _profile_evidence_count_summary(profile)
        )
        reasons.append("資料信心由來源類型、資料筆數、時間新鮮度與 coverage gap 綜合推估。")
    if profile.coverage_gaps:
        reasons.append("profile 仍有資料覆蓋限制：" + "、".join(profile.coverage_gaps))
    return reasons


def _profile_missing_source_messages(profile: RiskProfileRecord) -> list[str]:
    messages = []
    for source in profile.missing_sources:
        if source == "rainfall":
            messages.append("profile 未納入即時雨量來源；這會限制即時風險，不代表歷史參考沒有依據。")
        elif source == "water_level":
            messages.append("profile 未納入即時水位來源；這會限制即時風險，不代表歷史參考沒有依據。")
        else:
            messages.append(f"profile 未納入 {source} 來源；請把它視為資料覆蓋限制。")
    if profile.status != "healthy":
        messages.append("profile 目前不是 healthy 狀態，結果只能作為初步參考。")
    return messages


def _profile_evidence_items(
    profile: RiskProfileRecord,
    *,
    request: RiskAssessRequest,
    created_at: datetime,
) -> list[Evidence]:
    top_evidence_items = _profile_top_evidence_items(profile)
    represented_count_keys = {
        _profile_normalized_count_key(item.source_type, item.event_type)
        for item in top_evidence_items
    }
    evidence_items: list[Evidence] = list(top_evidence_items)
    for count_key, raw_count in sorted(profile.evidence_counts.items()):
        count = _positive_int(raw_count)
        if count is None:
            continue
        source_type, event_type = _profile_count_key_types(count_key)
        normalized_count_key = _profile_normalized_count_key(source_type, event_type)
        if normalized_count_key in represented_count_keys:
            continue
        label = _profile_count_label(source_type, event_type)
        evidence_items.append(
            Evidence(
                id=stable_uuid(
                    "profile-evidence-summary",
                    profile.profile_kind,
                    profile.profile_key,
                    count_key,
                ),
                source_id=f"precomputed-risk-profile:{count_key}",
                source_type=cast(Any, source_type),
                event_type=cast(Any, event_type),
                title=f"{label} profile 摘要",
                summary=(
                    f"預先計算 profile 彙整 {count} 筆{label}。"
                    "這是區域層級的摘要證據，不等於逐篇新聞清單；"
                    "精準半徑資料會由背景工作更新。"
                ),
                url=_public_evidence_url(
                    source_type=source_type,
                    event_type=event_type,
                    fallback_url=None,
                ),
                occurred_at=profile.latest_occurred_at,
                observed_at=profile.latest_observed_at,
                ingested_at=profile.latest_ingested_at or profile.computed_at or created_at,
                point=request.point,
                geometry=GeoJsonGeometry(
                    type="Point",
                    coordinates=[request.point.lng, request.point.lat],
                ),
                distance_to_query_m=profile.distance_to_query_m,
                confidence=_profile_evidence_confidence(profile),
                freshness_score=_profile_evidence_freshness_score(profile),
                source_weight=_profile_source_weight(source_type),
                privacy_level="aggregated",
                raw_ref=_profile_evidence_raw_ref(profile, count_key=count_key),
            )
        )
    return evidence_items


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


def _profile_evidence_raw_ref(profile: RiskProfileRecord, *, count_key: str) -> str:
    if not profile.top_evidence_ids:
        return f"profile:{profile.profile_kind}:{profile.profile_key}:{count_key}"
    top_ids = ",".join(profile.top_evidence_ids[:5])
    return f"profile:{profile.profile_kind}:{profile.profile_key}:{count_key}:top={top_ids}"


def _profile_count_key_types(count_key: str) -> tuple[str, str]:
    if ":" in count_key:
        source_key, event_key = count_key.split(":", 1)
    else:
        source_key = count_key
        event_key = {
            "official": "flood_potential",
            "news": "flood_report",
            "forum": "discussion",
            "social": "discussion",
            "user_report": "flood_report",
        }.get(source_key, "discussion")
    source_type = _PROFILE_SOURCE_TYPE_FALLBACKS.get(source_key, "derived")
    event_type = event_key if event_key in _PROFILE_EVENT_TYPE_FALLBACKS else "discussion"
    return source_type, event_type


def _profile_normalized_count_key(source_type: str, event_type: str) -> str:
    return f"{source_type}:{event_type}"


def _profile_count_label(source_type: str, event_type: str) -> str:
    source_labels = {
        "official": "官方",
        "news": "新聞",
        "forum": "討論區",
        "social": "社群",
        "user_report": "民眾回報",
        "derived": "衍生",
    }
    event_labels = {
        "rainfall": "雨量資料",
        "water_level": "水位資料",
        "flood_warning": "淹水警戒",
        "flood_potential": "淹水潛勢資料",
        "flood_report": "淹水事件資料",
        "road_closure": "道路封閉資料",
        "discussion": "公開討論資料",
    }
    return f"{source_labels.get(source_type, '資料')}{event_labels.get(event_type, '資料')}"


def _profile_evidence_count_summary(profile: RiskProfileRecord) -> str:
    parts = []
    for count_key, raw_count in sorted(profile.evidence_counts.items()):
        count = _positive_int(raw_count)
        if count is None:
            continue
        source_type, event_type = _profile_count_key_types(count_key)
        parts.append(f"{_profile_count_label(source_type, event_type)} {count} 筆")
    return "、".join(parts) if parts else "尚無可列出的資料筆數"


def _profile_evidence_total(profile: RiskProfileRecord) -> int:
    total = 0
    for raw_count in profile.evidence_counts.values():
        count = _positive_int(raw_count)
        if count is not None:
            total += count
    return total


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        count = int(value)
    elif isinstance(value, int):
        count = value
    elif isinstance(value, float):
        count = int(value)
    elif isinstance(value, str):
        try:
            count = int(value)
        except ValueError:
            return None
    else:
        return None
    return count if count > 0 else None


def _profile_evidence_confidence(profile: RiskProfileRecord) -> float:
    return {
        "high": 0.86,
        "medium": 0.68,
        "low": 0.46,
        "unknown": 0.25,
    }.get(profile.confidence_level, 0.55)


def _profile_evidence_freshness_score(profile: RiskProfileRecord) -> float:
    if profile.latest_observed_at or profile.latest_occurred_at:
        return 0.72
    if profile.latest_ingested_at:
        return 0.62
    return 0.5


def _profile_source_weight(source_type: str) -> float:
    return {
        "official": 1.0,
        "news": 0.72,
        "forum": 0.48,
        "social": 0.42,
        "user_report": 0.58,
        "derived": 0.5,
    }.get(source_type, 0.5)


def _public_risk_level(level: str) -> Literal["低", "中", "高", "極高", "未知"]:
    return cast(
        Literal["低", "中", "高", "極高", "未知"],
        {
            "low": "低",
            "medium": "中",
            "high": "高",
            "severe": "極高",
            "unknown": "未知",
        }.get(level, "未知"),
    )


def _public_confidence_level(level: str) -> Literal["低", "中", "高", "未知"]:
    return cast(
        Literal["低", "中", "高", "未知"],
        {
            "low": "低",
            "medium": "中",
            "high": "高",
            "unknown": "未知",
        }.get(level, "未知"),
    )


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
    if not _use_on_demand_public_news(settings):
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


def _use_on_demand_public_news(settings: Any) -> bool:
    if not settings.historical_news_on_demand_enabled:
        return False
    # On-demand lookup stores and displays citation metadata only. Full historical
    # news backfill and writeback still remain behind their own source/terms gates.
    return True


def _needs_historical_event_lookup(
    *,
    historical_records: tuple[tuple[HistoricalFloodRecord, float], ...],
    db_evidence_items: tuple[Evidence, ...] | None,
) -> bool:
    return (
        not historical_records
        and not _has_observed_historical_event(db_evidence_items or ())
    )


def _should_attempt_public_news_lookup(
    *,
    historical_records: tuple[tuple[HistoricalFloodRecord, float], ...],
    db_evidence_items: tuple[Evidence, ...] | None,
) -> bool:
    return not _has_public_news_evidence(
        historical_records=historical_records,
        db_evidence_items=db_evidence_items,
    )


def _has_public_news_evidence(
    *,
    historical_records: tuple[tuple[HistoricalFloodRecord, float], ...],
    db_evidence_items: tuple[Evidence, ...] | None,
) -> bool:
    return any(
        record.source_type == "news" and record.event_type in OBSERVED_HISTORICAL_EVENT_TYPES
        for record, _distance_m in historical_records
    ) or any(
        item.source_type == "news" and item.event_type in OBSERVED_HISTORICAL_EVENT_TYPES
        for item in (db_evidence_items or ())
    )


def _has_observed_historical_event(evidence_items: tuple[Evidence, ...]) -> bool:
    return any(
        item.event_type in OBSERVED_HISTORICAL_EVENT_TYPES
        for item in evidence_items
    )


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


def _evidence_from_upsert(record: EvidenceUpsert) -> Evidence:
    return Evidence(
        id=record.id,
        source_id=record.source_id,
        source_type=cast(Any, record.source_type),
        event_type=cast(Any, record.event_type),
        title=record.title,
        summary=record.summary,
        url=_public_evidence_url(
            source_type=record.source_type,
            event_type=record.event_type,
            fallback_url=record.url,
        ),
        occurred_at=record.occurred_at,
        observed_at=record.observed_at,
        ingested_at=record.ingested_at,
        point=LatLng(lat=record.lat, lng=record.lng),
        geometry=GeoJsonGeometry(type="Point", coordinates=[record.lng, record.lat]),
        distance_to_query_m=record.distance_to_query_m,
        confidence=record.confidence,
        freshness_score=record.freshness_score,
        source_weight=record.source_weight,
        privacy_level=cast(Any, record.privacy_level),
        raw_ref=record.raw_ref,
    )


def _on_demand_data_freshness(
    result: OnDemandNewsSearchResult,
    *,
    now: datetime,
) -> list[DataFreshness]:
    if not result.attempted:
        return []
    return [
        DataFreshness(
            source_id=result.source_id,
            name="公開新聞／Wiki 即時補查",
            health_status=result.health_status if not result.records else "healthy",
            observed_at=max(
                (record.observed_at for record in result.records if record.observed_at is not None),
                default=None,
            ),
            ingested_at=now,
            feature_count=len(result.records),
            message=result.message,
        )
    ]


def _official_flood_disaster_data_freshness(
    lookup: OfficialFloodDisasterLookup,
) -> list[DataFreshness]:
    if not lookup.attempted:
        return []
    return [
        DataFreshness(
            source_id=lookup.source_id,
            name=lookup.name,
            health_status=lookup.health_status,
            observed_at=lookup.observed_at,
            ingested_at=lookup.ingested_at,
            feature_count=len(lookup.records),
            message=lookup.message,
        )
    ]


def _cache_assessment_evidence(assessment_id: str, evidence_items: list[Evidence]) -> None:
    public_evidence.cache_assessment_evidence(assessment_id, evidence_items)


def _risk_assessment_response_cache_key(request: RiskAssessRequest, settings: Any) -> str:
    return json.dumps(
        {
            "lat": round(request.point.lat, 5),
            "lng": round(request.point.lng, 5),
            "radius_m": request.radius_m,
            "time_context": request.time_context,
            "location_text": (request.location_text or "").strip(),
            "app_env": settings.app_env,
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
    if ttl_seconds <= 0:
        return None
    cached = _RISK_ASSESSMENT_RESPONSE_CACHE.get(cache_key)
    if cached is None:
        return None
    cached_at, response = cached
    if now - cached_at >= timedelta(seconds=ttl_seconds):
        del _RISK_ASSESSMENT_RESPONSE_CACHE[cache_key]
        return None
    return response


def _cache_risk_assessment_response(
    cache_key: str,
    response: RiskAssessmentResponse,
    *,
    now: datetime,
    ttl_seconds: int,
) -> None:
    if ttl_seconds <= 0:
        return
    _RISK_ASSESSMENT_RESPONSE_CACHE[cache_key] = (now, response)
    while len(_RISK_ASSESSMENT_RESPONSE_CACHE) > 128:
        oldest_key = next(iter(_RISK_ASSESSMENT_RESPONSE_CACHE))
        del _RISK_ASSESSMENT_RESPONSE_CACHE[oldest_key]


def _persist_assessment(
    *,
    assessment_id: str,
    request: RiskAssessRequest,
    scoring: RiskScoringResult,
    explanation: Explanation,
    data_freshness: list[DataFreshness],
    evidence_items: list[Evidence],
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
                location_text=request.location_text,
                score_version=scoring.score_version,
                realtime_score=scoring.realtime_score,
                historical_score=scoring.historical_score,
                confidence_score=scoring.confidence_score,
                realtime_level=scoring.realtime_level,
                historical_level=scoring.historical_level,
                explanation=explanation.model_dump(mode="json"),
                data_freshness=[item.model_dump(mode="json") for item in data_freshness],
                result_snapshot=_assessment_result_snapshot(
                    assessment_id=assessment_id,
                    request=request,
                    scoring=scoring,
                    explanation=explanation,
                    data_freshness=data_freshness,
                    evidence_items=evidence_items,
                    created_at=created_at,
                    expires_at=expires_at,
                ),
                evidence_ids=tuple(item.id for item in evidence_items),
                created_at=created_at,
                expires_at=expires_at,
            ),
        )
    except EvidenceRepositoryUnavailable:
        return


def _assessment_result_snapshot(
    *,
    assessment_id: str,
    request: RiskAssessRequest,
    scoring: RiskScoringResult,
    explanation: Explanation,
    data_freshness: list[DataFreshness],
    evidence_items: list[Evidence],
    created_at: datetime,
    expires_at: datetime,
) -> dict[str, Any]:
    return {
        "assessment_id": assessment_id,
        "location": request.point.model_dump(mode="json"),
        "radius_m": request.radius_m,
        "location_text": request.location_text,
        "score_version": scoring.score_version,
        "scores": {
            "realtime": scoring.realtime_score,
            "historical": scoring.historical_score,
            "confidence": scoring.confidence_score,
        },
        "levels": {
            "realtime": scoring.realtime_level,
            "historical": scoring.historical_level,
            "confidence": scoring.confidence_level,
        },
        "explanation": explanation.model_dump(mode="json"),
        "evidence_ids": [item.id for item in evidence_items],
        "evidence_count": len(evidence_items),
        "data_freshness": [item.model_dump(mode="json") for item in data_freshness],
        "created_at": created_at.isoformat(),
        "expires_at": expires_at.isoformat(),
    }


def _historical_freshness_message(
    historical_records: tuple[tuple[HistoricalFloodRecord, float], ...],
) -> str:
    if not historical_records:
        return "查詢半徑內尚未有已匯入的歷史淹水紀錄；目前屬於資料不足，不能判定為低風險。"
    return (
        f"查詢半徑內找到 {len(historical_records)} 筆已匯入歷史淹水公開紀錄；"
        "目前完整新聞回填仍在 Phase 2 管線建置中。"
    )


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


def _historical_data_freshness(
    *,
    historical_records: tuple[tuple[HistoricalFloodRecord, float], ...],
    db_evidence_items: tuple[Evidence, ...] | None,
    now: datetime,
) -> DataFreshness:
    if db_evidence_items is None:
        return DataFreshness(
            source_id="historical-flood-records",
            name="Historical flood fallback records",
            health_status="healthy" if historical_records else "unknown",
            observed_at=max((record.occurred_at for record, _ in historical_records), default=None),
            ingested_at=now,
            feature_count=len(historical_records),
            message=_historical_freshness_message(historical_records),
        )

    observed_values = [
        observed_at
        for item in db_evidence_items
        for observed_at in (item.observed_at or item.occurred_at,)
        if observed_at is not None
    ]
    latest_observed = max(observed_values, default=None)
    latest_ingested = max((item.ingested_at for item in db_evidence_items), default=None)
    only_flood_potential = bool(db_evidence_items) and all(
        item.event_type == "flood_potential" for item in db_evidence_items
    )
    return DataFreshness(
        source_id="db-evidence",
        name="淹水潛勢與歷史資料庫" if only_flood_potential else "歷史淹水紀錄與公開新聞",
        health_status=(
            "degraded"
            if only_flood_potential
            else "healthy"
            if db_evidence_items
            else "unknown"
        ),
        observed_at=latest_observed,
        ingested_at=latest_ingested or now,
        feature_count=len(db_evidence_items),
        message=(
            f"查詢半徑內與 {len(db_evidence_items)} 筆淹水潛勢規劃圖資相交；"
            "這是情境參考，不是實際歷史淹水事件；仍需公開新聞或災情紀錄佐證。"
            if only_flood_potential
            else f"查詢半徑內找到 {len(db_evidence_items)} 筆已審核歷史資料。"
            if db_evidence_items
            else "查詢半徑內目前沒有已審核歷史資料；這是資料不足，不代表沒有淹水風險。"
        ),
    )


def _historical_scoring_distance(
    *,
    record: HistoricalFloodRecord,
    distance_to_query_m: float,
    radius_m: int,
    location_text: str | None,
) -> float:
    if distance_to_query_m > radius_m and historical_record_matches_location_text(
        record,
        location_text,
    ):
        return min(float(radius_m), 100.0)
    return distance_to_query_m


def _freshness_from_status(status: OfficialRealtimeSourceStatus) -> DataFreshness:
    return DataFreshness(
        source_id=status.source_id,
        name=status.name,
        health_status=status.health_status,
        observed_at=status.observed_at,
        ingested_at=status.ingested_at,
        message=status.message,
    )


def _visible_source_limitations(
    bundle: OfficialRealtimeBundle,
    historical_records: tuple[tuple[HistoricalFloodRecord, float], ...],
    db_evidence_items: tuple[Evidence, ...] | None,
    on_demand_news: OnDemandNewsSearchResult,
) -> list[str]:
    limitations: list[str] = []
    observation_types = {observation.event_type for observation in bundle.observations}
    persisted_observation_types = _persisted_official_observation_types(db_evidence_items or ())
    statuses = {status.source_id: status for status in bundle.source_statuses}

    if "rainfall" not in observation_types and "rainfall" not in persisted_observation_types:
        rainfall = statuses.get("cwa-rainfall")
        if rainfall is not None:
            limitations.append(rainfall.message or "即時雨量資料目前沒有可用測站。")
    if "water_level" not in observation_types and "water_level" not in persisted_observation_types:
        water_level = statuses.get("wra-water-level")
        if water_level is not None:
            limitations.append(water_level.message or "即時水位資料目前沒有可用測站。")
    has_historical_event = (
        bool(historical_records)
        or _has_observed_historical_event(db_evidence_items or ())
        or bool(on_demand_news.records)
    )
    if not has_historical_event:
        limitations.append(
            "查詢半徑內尚未匯入實際歷史淹水事件或公開新聞紀錄；"
            "目前資料不足，淹水潛勢圖資只能作為情境參考，不能標記為低風險或購屋安全。"
        )
    if on_demand_news.attempted and not on_demand_news.records and on_demand_news.message and not has_historical_event:
        news_message = on_demand_news.message.rstrip()
        separator = "" if news_message.endswith(("。", ".", "！", "!", "？", "?")) else "。"
        if on_demand_news.health_status == "disabled":
            limitations.append(news_message)
        else:
            limitations.append(
                f"公開新聞補查未取得可用事件：{news_message}{separator}"
                "這代表資料仍不足，不代表該地點沒有淹水紀錄。"
            )
    return limitations


def _persisted_official_observation_types(evidence_items: tuple[Evidence, ...]) -> set[str]:
    return {
        item.event_type
        for item in evidence_items
        if item.source_type == "official" and item.event_type in {"rainfall", "water_level"}
    }


@router.get("/evidence/{assessment_id}", response_model=EvidenceListResponse)
async def list_evidence(
    assessment_id: UUID,
    cursor: str | None = None,
    page_size: int = Query(default=20, ge=1, le=100),
) -> EvidenceListResponse:
    del cursor
    return public_evidence.list_assessment_evidence(
        str(assessment_id),
        page_size=page_size,
        fetch_db_evidence=_assessment_db_evidence,
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
async def list_layers() -> LayersResponse:
    return LayersResponse(layers=_layers(_now()))


@router.get("/layers/{layer_id}/tilejson", response_model=TileJson, response_model_exclude_none=True)
async def get_layer_tilejson(layer_id: str) -> TileJson:
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
