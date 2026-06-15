from __future__ import annotations

from typing import Any, Protocol, cast

from app.api.schemas import (
    Evidence,
    EvidenceListResponse,
    EvidencePreview,
    GeoJsonGeometry,
    LatLng,
)
from app.api.services import public_evidence_cache
from app.domain.evidence import EvidenceRecord, EvidenceRepositoryUnavailable, EvidenceUpsert
from app.domain.geocoding import stable_uuid
from app.domain.history import HistoricalFloodRecord
from app.domain.realtime import OfficialRealtimeObservation
from app.domain.risk import RiskEvidenceSignal


OFFICIAL_DATA_GOV_URLS = {
    "rainfall": "https://data.gov.tw/dataset/9177",
    "water_level": "https://data.gov.tw/dataset/25768",
    "flood_potential": "https://data.gov.tw/dataset/25766",
    "flood_report": "https://data.gov.tw/dataset/130016",
}

OFFICIAL_FLOOD_DISASTER_SOURCE_PREFIX = "data-gov-130016:"

# Alias kept for tests that clear the in-process cache between cases.
_ASSESSMENT_EVIDENCE_CACHE = public_evidence_cache._MEMORY_CACHE


class FetchAssessmentEvidence(Protocol):
    def __call__(
        self,
        *,
        database_url: str,
        assessment_id: str,
        page_size: int,
    ) -> tuple[EvidenceRecord, ...]: ...


class AssessmentDbEvidence(Protocol):
    def __call__(self, assessment_id: str, *, page_size: int) -> tuple[Evidence, ...]: ...


def cache_assessment_evidence(
    assessment_id: str,
    evidence_items: list[Evidence],
    *,
    ttl_seconds: int = 0,
    backend: str = "memory",
    redis_url: str | None = None,
) -> None:
    public_evidence_cache.store_evidence(
        assessment_id,
        evidence_items,
        ttl_seconds=ttl_seconds,
        backend=backend,
        redis_url=redis_url,
    )


def rainfall_realtime_risk_factor(rainfall_1h_mm: float) -> float:
    """Intensity-aware realtime risk factor for a CWA rainfall reading.

    Mirrors the realtime bridge's thresholds so worker-persisted rainfall scores
    by actual intensity instead of mere station presence: a dry/light station
    contributes ~0 (realtime "低", not "即時資料不足"), heavy rain contributes high.
    """

    if rainfall_1h_mm >= 80:
        return 1.0
    if rainfall_1h_mm >= 40:
        return 0.7
    if rainfall_1h_mm >= 20:
        return 0.35
    if rainfall_1h_mm >= 10:
        return 0.15
    return 0.0


def _evidence_realtime_risk_factor(record: EvidenceRecord) -> float | None:
    if record.event_type == "rainfall" and record.rainfall_mm_1h is not None:
        return rainfall_realtime_risk_factor(record.rainfall_mm_1h)
    return None


def evidence_from_record(record: EvidenceRecord) -> Evidence:
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
    title, summary = localized_evidence_text(record)
    return Evidence(
        id=record.id,
        source_id=record.source_id,
        source_type=cast(Any, record.source_type),
        event_type=cast(Any, record.event_type),
        title=title,
        summary=summary,
        url=public_evidence_url(
            source_type=record.source_type,
            event_type=record.event_type,
            fallback_url=record.url,
        ),
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
        realtime_risk_factor=_evidence_realtime_risk_factor(record),
    )


def localized_evidence_text(record: EvidenceRecord) -> tuple[str, str]:
    if record.event_type == "flood_potential":
        return (
            "官方淹水潛勢規劃圖資",
            "此筆資料表示查詢範圍與官方淹水潛勢規劃圖資相交，屬於歷史與情境參考；"
            "不代表目前正在淹水，也不是即時災害警報。",
        )
    return (record.title, record.summary)


def public_evidence_url(
    *,
    source_type: str,
    event_type: str,
    fallback_url: str | None,
) -> str | None:
    if source_type == "official":
        return OFFICIAL_DATA_GOV_URLS.get(event_type, fallback_url)
    return fallback_url


def assessment_db_evidence(
    assessment_id: str,
    *,
    page_size: int,
    database_url: str,
    fetch_assessment_evidence: FetchAssessmentEvidence,
) -> tuple[Evidence, ...]:
    try:
        records = fetch_assessment_evidence(
            database_url=database_url,
            assessment_id=assessment_id,
            page_size=page_size,
        )
    except EvidenceRepositoryUnavailable:
        return ()
    return tuple(evidence_from_record(record) for record in records)


def list_assessment_evidence(
    assessment_id: str,
    *,
    page_size: int,
    fetch_db_evidence: AssessmentDbEvidence,
    backend: str = "memory",
    redis_url: str | None = None,
) -> EvidenceListResponse:
    cached_items = public_evidence_cache.cached_evidence(
        assessment_id,
        backend=backend,
        redis_url=redis_url,
    )
    if cached_items is None:
        items = list(fetch_db_evidence(assessment_id, page_size=page_size))
    else:
        items = cached_items[:page_size]
    return EvidenceListResponse(
        assessment_id=assessment_id,
        items=items,
        next_cursor=None,
    )


def official_realtime_evidence(observation: OfficialRealtimeObservation) -> Evidence:
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


def historical_record_evidence(
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
        url=public_evidence_url(
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


def evidence_from_upsert(record: EvidenceUpsert) -> Evidence:
    return Evidence(
        id=record.id,
        source_id=record.source_id,
        source_type=cast(Any, record.source_type),
        event_type=cast(Any, record.event_type),
        title=record.title,
        summary=record.summary,
        url=public_evidence_url(
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


def evidence_preview(evidence: Evidence) -> EvidencePreview:
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


def signal_from_official_realtime(observation: OfficialRealtimeObservation) -> RiskEvidenceSignal:
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


def signal_from_historical_record(
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


def signal_from_evidence(evidence: Evidence) -> RiskEvidenceSignal:
    return RiskEvidenceSignal(
        source_type=evidence.source_type,
        event_type=evidence.event_type,
        confidence=evidence.confidence,
        distance_to_query_m=evidence.distance_to_query_m,
        freshness_score=evidence.freshness_score,
        source_weight=evidence.source_weight,
        risk_factor=(
            evidence.realtime_risk_factor
            if evidence.realtime_risk_factor is not None
            else 1.0
        ),
        observed_at=evidence.observed_at or evidence.occurred_at,
    )


def display_evidence_items(evidence_items: list[Evidence]) -> list[Evidence]:
    evidence_items = collapse_official_flood_disaster_items(evidence_items)
    return collapse_flood_potential_items(evidence_items)


def collapse_flood_potential_items(evidence_items: list[Evidence]) -> list[Evidence]:
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


def collapse_official_flood_disaster_items(evidence_items: list[Evidence]) -> list[Evidence]:
    official_items = [
        item for item in evidence_items if is_official_flood_disaster_item(item)
    ]
    if len(official_items) <= 1:
        return evidence_items

    representative = official_flood_disaster_summary_item(official_items)
    collapsed: list[Evidence] = []
    inserted = False
    for item in evidence_items:
        if not is_official_flood_disaster_item(item):
            collapsed.append(item)
            continue
        if not inserted:
            collapsed.append(representative)
            inserted = True
    return collapsed


def is_official_flood_disaster_item(item: Evidence) -> bool:
    return (
        item.source_type == "official"
        and item.event_type == "flood_report"
        and item.source_id.startswith(OFFICIAL_FLOOD_DISASTER_SOURCE_PREFIX)
    )


def official_flood_disaster_summary_item(items: list[Evidence]) -> Evidence:
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
    label = year_label(years)
    return closest_item.model_copy(
        update={
            "id": stable_uuid(
                "official-flood-disaster-summary",
                len(items),
                ",".join(sorted(item.source_id for item in items)),
            ),
            "source_id": "data-gov-130016:summary",
            "title": f"官方淹水災害情資點位彙整（{label}）",
            "summary": (
                f"查詢半徑內命中 {len(items)} 筆 data.gov.tw 130016 官方淹水災點快照，"
                f"命中年份：{label}。已合併為一筆代表資料顯示，以避免同一官方快照"
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


def year_label(years: list[int]) -> str:
    if not years:
        return "年份未提供"
    if len(years) <= 3:
        return "、".join(str(year) for year in years)
    return f"{years[0]}-{years[-1]}"
