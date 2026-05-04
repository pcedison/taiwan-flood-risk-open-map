import json
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any, Literal, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

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
    TileJsonVectorLayer,
)
from app.core.config import get_settings
from app.domain.evidence import (
    EvidenceRecord,
    EvidenceRepositoryUnavailable,
    EvidenceUpsert,
    fetch_assessment_evidence,
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
from app.domain.history import (
    HistoricalFloodRecord,
    historical_record_matches_location_text,
    nearby_historical_flood_records,
)
from app.domain.history.news_enrichment import (
    OnDemandNewsSearchResult,
    search_public_flood_news,
)
from app.domain.layers import (
    LayerRecord,
    LayerRepositoryUnavailable,
    fetch_map_layer,
    fetch_map_layers,
)
from app.domain.realtime import (
    OfficialRealtimeBundle,
    OfficialRealtimeObservation,
    OfficialRealtimeSourceStatus,
    fetch_official_realtime_bundle,
)
from app.domain.risk import RiskEvidenceSignal, RiskScoringResult, score_risk

router = APIRouter(prefix="/v1", tags=["Public"])

LOW_ATTENTION: AttentionLevel = "低"
NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
WIKIMEDIA_API_URL = "https://zh.wikipedia.org/w/api.php"
NOMINATIM_USER_AGENT = "FloodRiskTaiwan/0.1 local-development"
TAIWAN_VIEWBOX = "119.2,25.5,122.3,21.7"
LOCAL_HISTORICAL_FALLBACK_ENVS = {"local", "development", "test"}
_ASSESSMENT_EVIDENCE_CACHE: dict[str, list[Evidence]] = {}


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
    )


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
        url=None,
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
        url=record.url,
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
    point = (
        LatLng(lat=record.lat, lng=record.lng)
        if record.lat is not None and record.lng is not None
        else None
    )
    geometry = (
        GeoJsonGeometry(
            type=record.geometry["type"],
            coordinates=record.geometry["coordinates"],
        )
        if record.geometry is not None
        else None
    )
    return Evidence(
        id=record.id,
        source_id=record.source_id,
        source_type=cast(Any, record.source_type),
        event_type=cast(Any, record.event_type),
        title=record.title,
        summary=record.summary,
        url=record.url,
        occurred_at=record.occurred_at,
        observed_at=record.observed_at,
        ingested_at=record.ingested_at,
        point=point,
        geometry=geometry,
        distance_to_query_m=record.distance_to_query_m,
        confidence=record.confidence,
        freshness_score=record.freshness_score,
        source_weight=record.source_weight,
        privacy_level=cast(Any, record.privacy_level),
        raw_ref=record.raw_ref,
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
    return [
        MapLayer(
            id="flood-potential",
            name="淹水潛勢",
            description="官方公開資料中的淹水潛勢範圍。",
            category="flood_potential",
            status="available",
            minzoom=8,
            maxzoom=18,
            attribution="政府開放資料",
            tilejson_url="/v1/layers/flood-potential/tilejson",
            updated_at=now,
        ),
        MapLayer(
            id="query-heat",
            name="查詢關注度",
            description="去識別化後的區域查詢關注度。",
            category="query_heat",
            status="available",
            minzoom=8,
            maxzoom=14,
            attribution="Flood Risk 去識別化統計",
            tilejson_url="/v1/layers/query-heat/tilejson",
            updated_at=now,
        ),
    ]


def _static_layer_records(now: datetime) -> tuple[LayerRecord, ...]:
    return (
        LayerRecord(
            id="flood-potential",
            name="Flood potential",
            description="Static fallback for official flood potential polygons.",
            category="flood_potential",
            status="disabled",
            minzoom=8,
            maxzoom=18,
            attribution="Government open data",
            tilejson_url="/v1/layers/flood-potential/tilejson",
            updated_at=now,
            metadata={
                "version": "static-fallback",
                "tiles": [
                    "https://tiles.placeholder.flood-risk.local/flood-potential/{z}/{x}/{y}.pbf"
                ],
                "bounds": [119.3, 21.8, 122.1, 25.4],
                "vector_layers": [
                    {
                        "id": "flood_potential",
                        "fields": {"source_id": "String", "category": "String"},
                    }
                ],
            },
        ),
        LayerRecord(
            id="query-heat",
            name="Query heat",
            description="Static fallback for privacy-preserving query density.",
            category="query_heat",
            status="disabled",
            minzoom=8,
            maxzoom=14,
            attribution="Flood Risk aggregated analytics",
            tilejson_url="/v1/layers/query-heat/tilejson",
            updated_at=now,
            metadata={
                "version": "static-fallback",
                "tiles": [
                    "https://tiles.placeholder.flood-risk.local/query-heat/{z}/{x}/{y}.pbf"
                ],
                "bounds": [119.3, 21.8, 122.1, 25.4],
                "vector_layers": [
                    {
                        "id": "query_heat",
                        "fields": {"query_count_bucket": "String", "period": "String"},
                    }
                ],
            },
        ),
    )


def _map_layer_from_record(record: LayerRecord) -> MapLayer:
    return MapLayer(
        id=record.id,
        name=record.name,
        description=record.description,
        category=cast(Any, record.category),
        status=cast(Any, record.status),
        minzoom=record.minzoom,
        maxzoom=record.maxzoom,
        attribution=record.attribution,
        tilejson_url=record.tilejson_url,
        updated_at=record.updated_at,
    )


def _layer_records(now: datetime) -> tuple[LayerRecord, ...]:
    try:
        records = fetch_map_layers(database_url=get_settings().database_url)
    except LayerRepositoryUnavailable:
        return _static_layer_records(now)
    return records or _static_layer_records(now)


def _static_layer_by_id(layer_id: str, now: datetime) -> LayerRecord | None:
    return {layer.id: layer for layer in _static_layer_records(now)}.get(layer_id)


def _layer_record(layer_id: str, now: datetime) -> LayerRecord | None:
    try:
        records = fetch_map_layers(database_url=get_settings().database_url)
    except LayerRepositoryUnavailable:
        return _static_layer_by_id(layer_id, now)
    if not records:
        return _static_layer_by_id(layer_id, now)
    try:
        return fetch_map_layer(database_url=get_settings().database_url, layer_id=layer_id)
    except LayerRepositoryUnavailable:
        return _static_layer_by_id(layer_id, now)


def _layers(now: datetime) -> list[MapLayer]:
    return [_map_layer_from_record(record) for record in _layer_records(now)]


@router.post("/geocode", response_model=GeocodeResponse)
async def geocode(request: GeocodeRequest) -> GeocodeResponse:
    return GeocodeResponse(candidates=_build_geocoder().geocode(request))


@router.post("/risk/assess", response_model=RiskAssessmentResponse)
async def assess_risk(request: RiskAssessRequest) -> RiskAssessmentResponse:
    settings = get_settings()
    created_at = _now()
    assessment_id = stable_uuid(
        "assessment",
        request.point.lat,
        request.point.lng,
        request.radius_m,
        created_at.isoformat(),
    )
    realtime_bundle = fetch_official_realtime_bundle(
        lat=request.point.lat,
        lng=request.point.lng,
        radius_m=request.radius_m,
        cwa_authorization=settings.cwa_api_authorization,
        enabled=settings.realtime_official_enabled,
        cwa_enabled=settings.source_cwa_api_enabled,
        wra_enabled=settings.source_wra_api_enabled,
        now=created_at,
    )
    db_evidence_items = _nearby_db_evidence(request)
    on_demand_news = OnDemandNewsSearchResult(
        attempted=False,
        source_id="on-demand-public-news",
        message="未啟動公開新聞補查。",
        records=(),
    )
    if db_evidence_items is None:
        historical_records = _fallback_historical_records(request)
        if not historical_records:
            on_demand_news = _on_demand_public_news_result(request, now=created_at)
        historical_evidence_items = [
            _historical_record_evidence(record, distance_to_query_m=distance_m)
            for record, distance_m in historical_records
        ]
        historical_evidence_items.extend(
            _evidence_from_upsert(record) for record in on_demand_news.records
        )
        historical_signals = (
            *tuple(
                _signal_from_historical_record(
                    record,
                    distance_to_query_m=_historical_scoring_distance(
                        record=record,
                        distance_to_query_m=distance_m,
                        radius_m=request.radius_m,
                        location_text=request.location_text,
                    ),
                )
                for record, distance_m in historical_records
            ),
            *tuple(
                _signal_from_evidence(item)
                for item in historical_evidence_items[len(historical_records) :]
            ),
        )
        historical_freshness_db_items = (
            tuple(historical_evidence_items) if on_demand_news.records else None
        )
    else:
        historical_records = (
            _fallback_historical_records(request)
            if not db_evidence_items and _use_local_historical_fallback(settings.app_env)
            else ()
        )
        if historical_records:
            historical_evidence_items = [
                _historical_record_evidence(record, distance_to_query_m=distance_m)
                for record, distance_m in historical_records
            ]
            historical_signals = tuple(
                _signal_from_historical_record(
                    record,
                    distance_to_query_m=_historical_scoring_distance(
                        record=record,
                        distance_to_query_m=distance_m,
                        radius_m=request.radius_m,
                        location_text=request.location_text,
                    ),
                )
                for record, distance_m in historical_records
            )
            historical_freshness_db_items = None
        else:
            if not db_evidence_items:
                on_demand_news = search_public_flood_news(
                    location_text=request.location_text,
                    lat=request.point.lat,
                    lng=request.point.lng,
                    radius_m=request.radius_m,
                    now=created_at,
                    max_records=settings.historical_news_on_demand_max_records,
                    timeout_seconds=settings.historical_news_on_demand_timeout_seconds,
                ) if _use_on_demand_public_news(settings) else on_demand_news
            on_demand_evidence_items = _persist_or_build_on_demand_evidence(
                on_demand_news,
                writeback_enabled=settings.historical_news_on_demand_writeback_enabled,
            )
            historical_evidence_items = [*db_evidence_items, *on_demand_evidence_items]
            historical_signals = tuple(_signal_from_evidence(item) for item in historical_evidence_items)
            historical_freshness_db_items = tuple(historical_evidence_items)
    historical_freshness = _historical_data_freshness(
        historical_records=historical_records,
        db_evidence_items=historical_freshness_db_items,
        now=created_at,
    )
    evidence_items = [
        *(_official_realtime_evidence(observation) for observation in realtime_bundle.observations),
        *historical_evidence_items,
    ]
    scoring = score_risk(
        (
            *(_signal_from_official_realtime(observation) for observation in realtime_bundle.observations),
            *historical_signals,
        ),
        now=created_at,
    )
    _cache_assessment_evidence(assessment_id, evidence_items)
    expires_at = created_at + timedelta(minutes=10)
    explanation = Explanation(
        summary=scoring.explanation_summary,
        main_reasons=list(scoring.main_reasons),
        missing_sources=_visible_source_limitations(
            realtime_bundle,
            historical_records,
            historical_freshness_db_items,
            on_demand_news,
        ),
    )
    data_freshness = [
        *(_freshness_from_status(status) for status in realtime_bundle.source_statuses),
        DataFreshness(
            source_id=historical_freshness.source_id,
            name="歷史淹水紀錄與公開新聞",
            health_status=historical_freshness.health_status,
            observed_at=historical_freshness.observed_at,
            ingested_at=historical_freshness.ingested_at,
            message=historical_freshness.message,
        ),
        *_on_demand_data_freshness(on_demand_news, now=created_at),
    ]
    _persist_assessment(
        assessment_id=assessment_id,
        request=request,
        scoring=scoring,
        explanation=explanation,
        data_freshness=data_freshness,
        evidence_items=evidence_items,
        created_at=created_at,
        expires_at=expires_at,
    )
    return RiskAssessmentResponse(
        assessment_id=assessment_id,
        location=request.point,
        radius_m=request.radius_m,
        score_version=scoring.score_version,
        created_at=created_at,
        expires_at=created_at + timedelta(minutes=10),
        realtime=RiskLevelBlock(level=scoring.realtime_level),
        historical=RiskLevelBlock(level=scoring.historical_level),
        confidence=ConfidenceBlock(level=scoring.confidence_level),
        explanation=explanation,
        evidence=[_evidence_preview(item) for item in evidence_items],
        data_freshness=data_freshness,
        query_heat=_query_heat(request, now=created_at),
    )


def _on_demand_public_news_result(
    request: RiskAssessRequest,
    *,
    now: datetime,
) -> OnDemandNewsSearchResult:
    settings = get_settings()
    if not _use_on_demand_public_news(settings):
        return OnDemandNewsSearchResult(
            attempted=False,
            source_id="on-demand-public-news",
            message="公開新聞即時補查未啟用。",
            records=(),
        )
    return search_public_flood_news(
        location_text=request.location_text,
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
    if settings.app_env.strip().lower() in {"production", "staging", "production-beta"}:
        return settings.source_news_enabled and settings.source_terms_review_ack
    return True


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
        url=record.url,
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
            name="公開新聞即時補查",
            health_status="healthy" if result.records else "unknown",
            observed_at=max(
                (record.observed_at for record in result.records if record.observed_at is not None),
                default=None,
            ),
            ingested_at=now,
            message=result.message,
        )
    ]
def _cache_assessment_evidence(assessment_id: str, evidence_items: list[Evidence]) -> None:
    _ASSESSMENT_EVIDENCE_CACHE[assessment_id] = evidence_items
    while len(_ASSESSMENT_EVIDENCE_CACHE) > 256:
        oldest_key = next(iter(_ASSESSMENT_EVIDENCE_CACHE))
        del _ASSESSMENT_EVIDENCE_CACHE[oldest_key]


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
    return DataFreshness(
        source_id="db-evidence",
        name="Historical flood evidence database",
        health_status="healthy" if db_evidence_items else "unknown",
        observed_at=latest_observed,
        ingested_at=latest_ingested or now,
        message=(
            f"查詢半徑內找到 {len(db_evidence_items)} 筆已審核歷史資料。"
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
    statuses = {status.source_id: status for status in bundle.source_statuses}

    if "rainfall" not in observation_types:
        rainfall = statuses.get("cwa-rainfall")
        if rainfall is not None:
            limitations.append(rainfall.message or "即時雨量資料目前沒有可用測站。")
    if "water_level" not in observation_types:
        water_level = statuses.get("wra-water-level")
        if water_level is not None:
            limitations.append(water_level.message or "即時水位資料目前沒有可用測站。")
    if not historical_records and not db_evidence_items:
        limitations.append("查詢半徑內尚未匯入歷史淹水紀錄；目前資料不足，不能標記為低風險或購屋安全。")
    if on_demand_news.attempted and not on_demand_news.records and on_demand_news.message:
        limitations.append(
            f"公開新聞補查未取得可用事件：{on_demand_news.message}。"
            "這代表資料仍不足，不代表該地點沒有淹水紀錄。"
        )
    return limitations


@router.get("/evidence/{assessment_id}", response_model=EvidenceListResponse)
async def list_evidence(
    assessment_id: UUID,
    cursor: str | None = None,
    page_size: int = Query(default=20, ge=1, le=100),
) -> EvidenceListResponse:
    del cursor
    cached_items = _ASSESSMENT_EVIDENCE_CACHE.get(str(assessment_id))
    if cached_items is None:
        items = list(_assessment_db_evidence(str(assessment_id), page_size=page_size))
    else:
        items = cached_items[:page_size]
    return EvidenceListResponse(
        assessment_id=str(assessment_id),
        items=items,
        next_cursor=None,
    )


def _assessment_db_evidence(assessment_id: str, *, page_size: int) -> tuple[Evidence, ...]:
    try:
        records = fetch_assessment_evidence(
            database_url=get_settings().database_url,
            assessment_id=assessment_id,
            page_size=page_size,
        )
    except EvidenceRepositoryUnavailable:
        return ()
    return tuple(_evidence_from_record(record) for record in records)


def _tilejson_from_layer_record(record: LayerRecord) -> TileJson:
    metadata = record.metadata
    return TileJson(
        tilejson=str(metadata.get("tilejson", "3.0.0")),
        name=str(metadata.get("name", record.name)),
        version=_optional_str(metadata.get("version")),
        attribution=_optional_str(metadata.get("attribution")) or record.attribution,
        scheme=cast(Any, metadata.get("scheme", "xyz")),
        tiles=_string_list(
            metadata.get("tiles"),
            fallback=[
                "https://tiles.placeholder.flood-risk.local/"
                f"{record.id}/{{z}}/{{x}}/{{y}}.pbf"
            ],
        ),
        minzoom=_optional_int(metadata.get("minzoom")) if "minzoom" in metadata else record.minzoom,
        maxzoom=_optional_int(metadata.get("maxzoom")) if "maxzoom" in metadata else record.maxzoom,
        bounds=_number_list(metadata.get("bounds"), expected_length=4),
        center=_number_list(metadata.get("center"), expected_length=3),
        vector_layers=_tilejson_vector_layers(record),
    )


def _tilejson_vector_layers(record: LayerRecord) -> list[TileJsonVectorLayer]:
    vector_layers = record.metadata.get("vector_layers")
    if isinstance(vector_layers, list) and vector_layers:
        return [
            TileJsonVectorLayer(
                id=str(item.get("id", record.id.replace("-", "_"))),
                description=_optional_str(item.get("description")),
                minzoom=_optional_int(item.get("minzoom")),
                maxzoom=_optional_int(item.get("maxzoom")),
                fields=_string_dict(item.get("fields")),
            )
            for item in vector_layers
            if isinstance(item, dict)
        ]
    return [
        TileJsonVectorLayer(
            id=record.id.replace("-", "_"),
            fields={"source_id": "String", "category": "String"},
        )
    ]


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(cast(Any, value))
    except (TypeError, ValueError):
        return None


def _string_list(value: object, *, fallback: list[str]) -> list[str]:
    if isinstance(value, list):
        items = [str(item) for item in value if item]
        if items:
            return items
    return fallback


def _number_list(value: object, *, expected_length: int) -> list[float] | None:
    if not isinstance(value, list) or len(value) != expected_length:
        return None
    try:
        return [float(cast(Any, item)) for item in value]
    except (TypeError, ValueError):
        return None


def _string_dict(value: object) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    return {str(key): str(item) for key, item in value.items()}


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
    return _tilejson_from_layer_record(layer)
