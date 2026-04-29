import json
import re
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import NAMESPACE_URL, UUID, uuid5

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
from app.domain.history import (
    HistoricalFloodRecord,
    historical_record_matches_location_text,
    nearby_historical_flood_records,
)
from app.domain.realtime import (
    OfficialRealtimeBundle,
    OfficialRealtimeObservation,
    OfficialRealtimeSourceStatus,
    fetch_official_realtime_bundle,
)
from app.domain.risk import RiskEvidenceSignal, score_risk

router = APIRouter(prefix="/v1", tags=["Public"])

LOW_ATTENTION: AttentionLevel = "低"
NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
WIKIMEDIA_API_URL = "https://zh.wikipedia.org/w/api.php"
NOMINATIM_USER_AGENT = "FloodRiskTaiwan/0.1 local-development"
TAIWAN_VIEWBOX = "119.2,25.5,122.3,21.7"
_ASSESSMENT_EVIDENCE_CACHE: dict[str, list[Evidence]] = {}
KNOWN_GEOCODE_POINTS: tuple[tuple[tuple[str, ...], float, float, str], ...] = (
    (
        ("台北火車站", "台北車站", "臺北車站", "taipei main station", "taipei station"),
        25.04776,
        121.51706,
        "63000000",
    ),
    (("台北101", "台北 101", "臺北101", "taipei 101"), 25.03396, 121.56447, "63000000"),
    (("台北市政府", "臺北市政府", "taipei city hall"), 25.03752, 121.56368, "63000000"),
    (("西門町", "ximending"), 25.04208, 121.50777, "63000000"),
    (("板橋車站", "banqiao station"), 25.01433, 121.46386, "65000000"),
    (("桃園機場", "桃園國際機場", "taoyuan airport"), 25.07965, 121.23422, "68000000"),
    (("新竹車站", "hsinchu station"), 24.80158, 120.9717, "10018000"),
    (("台中車站", "臺中車站", "taichung station"), 24.13716, 120.68686, "66000000"),
    (("台南車站", "臺南車站", "tainan station"), 22.99713, 120.21295, "67000000"),
    (("高雄車站", "kaohsiung station"), 22.63937, 120.30203, "64000000"),
    (("花蓮車站", "hualien station"), 23.9928, 121.60195, "10015000"),
    (("國立臺灣大學", "國立台灣大學", "台灣大學", "臺灣大學", "ntu"), 25.01682, 121.53846, "63000000"),
    (("國立成功大學", "成功大學", "成大", "ncku"), 22.9997, 120.21972, "67000000"),
    (("奇美博物館", "chimei museum"), 22.93486, 120.22688, "67000000"),
    (("台南七股鹽山", "臺南七股鹽山", "七股鹽山", "七股鹽場", "cigu salt mountain"), 23.152758, 120.102489, "67000000"),
    (("四草綠色隧道", "台南四草綠色隧道", "臺南四草綠色隧道"), 23.01916, 120.13554, "67000000"),
    (("安平古堡", "台南安平古堡", "臺南安平古堡"), 23.00155, 120.16056, "67000000"),
    (("赤崁樓", "台南赤崁樓", "臺南赤崁樓"), 22.99743, 120.20256, "67000000"),
    (("億載金城", "台南億載金城", "臺南億載金城"), 22.98718, 120.15981, "67000000"),
    (("台南孔廟", "臺南孔廟", "全臺首學"), 22.99032, 120.20401, "67000000"),
    (("神農街", "台南神農街", "臺南神農街"), 22.99753, 120.19625, "67000000"),
    (("國立故宮博物院", "故宮", "台北故宮", "taipei palace museum"), 25.10236, 121.54849, "63000000"),
    (("士林夜市", "shilin night market"), 25.08808, 121.52418, "63000000"),
    (("國立自然科學博物館", "科博館", "台中科博館"), 24.15752, 120.66602, "66000000"),
    (("逢甲夜市", "fengjia night market"), 24.17509, 120.64554, "66000000"),
    (("高鐵台南站", "高鐵臺南站", "台南高鐵站", "tainan hsr"), 22.92508, 120.28572, "67000000"),
    (("高鐵左營站", "左營高鐵站", "zuoying hsr"), 22.68739, 120.30748, "64000000"),
    (("松山機場", "台北松山機場", "taipei songshan airport"), 25.06972, 121.5525, "63000000"),
)


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _stable_uuid(*parts: object) -> str:
    return str(uuid5(NAMESPACE_URL, ":".join(str(part) for part in parts)))


def _normalize_query(query: str) -> str:
    return query.casefold().replace(" ", "").replace("臺", "台")


def _local_geocode_candidates(request: GeocodeRequest) -> list[PlaceCandidate]:
    normalized_query = _normalize_query(request.query)
    for aliases, lat, lng, admin_code in KNOWN_GEOCODE_POINTS:
        if any(_normalize_query(alias) in normalized_query for alias in aliases):
            return [
                PlaceCandidate(
                    place_id=_stable_uuid("place", request.query, request.input_type, index),
                    name=request.query if index == 0 else f"{request.query}候選地點 {index + 1}",
                    type=request.input_type,
                    point=LatLng(lat=lat + (index * 0.001), lng=lng + (index * 0.001)),
                    admin_code=admin_code,
                    source="local-taiwan-gazetteer",
                    confidence=max(0.5, 0.96 - (index * 0.08)),
                )
                for index in range(request.limit)
            ]
    return []


def _nominatim_candidates(request: GeocodeRequest) -> list[PlaceCandidate]:
    candidates = list(_cached_nominatim_candidates(request.query, request.input_type, request.limit))
    if candidates:
        return candidates

    for fallback_query in _geocode_fallback_queries(request.query):
        fallback_candidates = list(
            _cached_nominatim_candidates(fallback_query, request.input_type, request.limit)
        )
        if fallback_candidates:
            fallback_kind = "address-fallback" if _looks_like_address_fallback(fallback_query, request.query) else "taiwan-fallback"
            return [
                candidate.model_copy(
                    update={
                        "name": _fallback_candidate_name(candidate.name, fallback_kind),
                        "source": f"{candidate.source}-{fallback_kind}",
                        "confidence": min(candidate.confidence, 0.78 if fallback_kind == "address-fallback" else 0.82),
                    }
                )
                for candidate in fallback_candidates
            ]
    wikimedia_candidates = list(_cached_wikimedia_candidates(request.query, request.limit))
    if wikimedia_candidates:
        return wikimedia_candidates
    return []


def _geocode_fallback_queries(query: str) -> tuple[str, ...]:
    normalized = query.strip()
    if not normalized:
        return ()

    candidates: list[str] = list(_address_fallback_queries(normalized))
    candidates.extend(_taiwan_context_fallback_queries(normalized))

    deduplicated: list[str] = []
    for candidate in candidates:
        if candidate != normalized and candidate not in deduplicated:
            deduplicated.append(candidate)
    return tuple(deduplicated[:8])


def _address_fallback_queries(query: str) -> tuple[str, ...]:
    normalized = query.strip()
    if not normalized:
        return ()

    candidates: list[str] = []
    lane_match = re.search(r"(.+?\d+巷)(?:\d+(?:之\d+)?號?)?$", normalized)
    if lane_match:
        candidates.append(lane_match.group(1))

    road_match = re.search(r"(.+?(?:路|街|大道|巷))\d+(?:之\d+)?號?$", normalized)
    if road_match:
        candidates.append(road_match.group(1))

    expanded: list[str] = []
    for candidate in candidates:
        expanded.append(candidate)
        if not any(city in candidate for city in ("台南", "臺南", "安南區")):
            expanded.append(f"台南市安南區{candidate}")

    deduplicated: list[str] = []
    for candidate in expanded:
        if candidate != normalized and candidate not in deduplicated:
            deduplicated.append(candidate)
    return tuple(deduplicated[:4])


def _taiwan_context_fallback_queries(query: str) -> tuple[str, ...]:
    if any(token in query.casefold() for token in ("taiwan", "臺灣", "台灣")):
        return ()
    return (f"{query} 台灣", f"臺灣 {query}")


def _looks_like_address_fallback(fallback_query: str, original_query: str) -> bool:
    return fallback_query in _address_fallback_queries(original_query.strip())


def _fallback_candidate_name(name: str, fallback_kind: str) -> str:
    if fallback_kind == "address-fallback":
        return f"{name}（由門牌定位到巷道）"
    return name


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
        candidates.append(
            PlaceCandidate(
                place_id=_stable_uuid("nominatim", item.get("osm_type"), item.get("osm_id"), index),
                name=str(item.get("name") or query or display_name),
                type=input_type,
                point=LatLng(lat=lat, lng=lng),
                admin_code=None,
                source="openstreetmap-nominatim",
                confidence=max(0.5, 0.9 - (index * 0.08)),
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
        if lat is None or lng is None or not _within_taiwan_bounds(lat, lng):
            continue
        title = str(page.get("title") or query)
        candidates.append(
            PlaceCandidate(
                place_id=_stable_uuid("wikimedia", page_id, index),
                name=title,
                type="landmark",
                point=LatLng(lat=lat, lng=lng),
                admin_code=None,
                source="wikimedia-coordinates",
                confidence=max(0.66, 0.84 - (index * 0.06)),
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


def _within_taiwan_bounds(lat: float, lng: float) -> bool:
    return 21.7 <= lat <= 25.5 and 119.2 <= lng <= 122.3


def _official_realtime_evidence(
    observation: OfficialRealtimeObservation,
) -> Evidence:
    return Evidence(
        id=_stable_uuid("official-realtime", observation.source_id),
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
        id=_stable_uuid("historical-flood-record", record.source_id),
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


def _layers(now: datetime) -> list[MapLayer]:
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


@router.post("/geocode", response_model=GeocodeResponse)
async def geocode(request: GeocodeRequest) -> GeocodeResponse:
    local_candidates = _local_geocode_candidates(request)
    if local_candidates:
        return GeocodeResponse(candidates=local_candidates)
    return GeocodeResponse(candidates=_nominatim_candidates(request))


@router.post("/risk/assess", response_model=RiskAssessmentResponse)
async def assess_risk(request: RiskAssessRequest) -> RiskAssessmentResponse:
    settings = get_settings()
    created_at = _now()
    assessment_id = _stable_uuid(
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
        now=created_at,
    )
    historical_records = nearby_historical_flood_records(
        lat=request.point.lat,
        lng=request.point.lng,
        radius_m=request.radius_m,
        location_text=request.location_text,
    )
    evidence_items = [
        *(_official_realtime_evidence(observation) for observation in realtime_bundle.observations),
        *(
            _historical_record_evidence(record, distance_to_query_m=distance_m)
            for record, distance_m in historical_records
        ),
    ]
    scoring = score_risk(
        (
            *(_signal_from_official_realtime(observation) for observation in realtime_bundle.observations),
            *(
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
        ),
        now=created_at,
    )
    _cache_assessment_evidence(assessment_id, evidence_items)
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
        explanation=Explanation(
            summary=scoring.explanation_summary,
            main_reasons=list(scoring.main_reasons),
            missing_sources=_visible_source_limitations(realtime_bundle, historical_records),
        ),
        evidence=[_evidence_preview(item) for item in evidence_items],
        data_freshness=[
            *(_freshness_from_status(status) for status in realtime_bundle.source_statuses),
            DataFreshness(
                source_id="historical-flood-records",
                name="歷史淹水紀錄與公開新聞",
                health_status="healthy" if historical_records else "unknown",
                observed_at=max((record.occurred_at for record, _ in historical_records), default=None),
                ingested_at=created_at,
                message=_historical_freshness_message(historical_records),
            )
        ],
        query_heat=QueryHeat(
            period="P7D",
            attention_level=LOW_ATTENTION,
            query_count_bucket="1-9",
            unique_approx_count_bucket="1-9",
            updated_at=created_at,
        ),
    )


def _cache_assessment_evidence(assessment_id: str, evidence_items: list[Evidence]) -> None:
    _ASSESSMENT_EVIDENCE_CACHE[assessment_id] = evidence_items
    while len(_ASSESSMENT_EVIDENCE_CACHE) > 256:
        oldest_key = next(iter(_ASSESSMENT_EVIDENCE_CACHE))
        del _ASSESSMENT_EVIDENCE_CACHE[oldest_key]


def _historical_freshness_message(
    historical_records: tuple[tuple[HistoricalFloodRecord, float], ...],
) -> str:
    if not historical_records:
        return "查詢半徑內尚未有已匯入的歷史淹水紀錄；購屋判讀不可只依即時雨量或水位。"
    return (
        f"查詢半徑內找到 {len(historical_records)} 筆已匯入歷史淹水公開紀錄；"
        "目前完整新聞回填仍在 Phase 2 管線建置中。"
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
    if not historical_records:
        limitations.append("查詢半徑內尚未匯入歷史淹水紀錄；目前不應把即時低風險解讀為購屋安全。")
    return limitations


@router.get("/evidence/{assessment_id}", response_model=EvidenceListResponse)
async def list_evidence(
    assessment_id: UUID,
    cursor: str | None = None,
    page_size: int = Query(default=20, ge=1, le=100),
) -> EvidenceListResponse:
    del cursor
    items = _ASSESSMENT_EVIDENCE_CACHE.get(str(assessment_id), [])[:page_size]
    return EvidenceListResponse(
        assessment_id=str(assessment_id),
        items=items,
        next_cursor=None,
    )


@router.get("/layers", response_model=LayersResponse)
async def list_layers() -> LayersResponse:
    return LayersResponse(layers=_layers(_now()))


@router.get("/layers/{layer_id}/tilejson", response_model=TileJson, response_model_exclude_none=True)
async def get_layer_tilejson(layer_id: str) -> TileJson:
    layer_by_id = {layer.id: layer for layer in _layers(_now())}
    layer = layer_by_id.get(layer_id)
    if layer is None:
        raise HTTPException(
            status_code=404,
            detail=error_payload("not_found", f"Layer '{layer_id}' was not found.")["error"],
        )

    vector_layer_id = layer_id.replace("-", "_")
    return TileJson(
        tilejson="3.0.0",
        name=layer.name,
        version="2026-04-28",
        attribution=layer.attribution,
        scheme="xyz",
        tiles=[f"https://tiles.example.test/{layer_id}/{{z}}/{{x}}/{{y}}.pbf"],
        minzoom=layer.minzoom,
        maxzoom=layer.maxzoom,
        bounds=[119.3, 21.8, 122.1, 25.4],
        vector_layers=[
            TileJsonVectorLayer(
                id=vector_layer_id,
                fields={"source_id": "String", "category": "String"},
            )
        ],
    )
