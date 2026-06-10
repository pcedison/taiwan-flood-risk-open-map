from __future__ import annotations

from typing import Any, Protocol, cast

from app.api.schemas import Evidence, EvidenceListResponse, GeoJsonGeometry, LatLng
from app.domain.evidence import EvidenceRecord, EvidenceRepositoryUnavailable


OFFICIAL_DATA_GOV_URLS = {
    "rainfall": "https://data.gov.tw/dataset/9177",
    "water_level": "https://data.gov.tw/dataset/25768",
    "flood_potential": "https://data.gov.tw/dataset/25766",
    "flood_report": "https://data.gov.tw/dataset/130016",
}

_ASSESSMENT_EVIDENCE_CACHE: dict[str, list[Evidence]] = {}


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


def cache_assessment_evidence(assessment_id: str, evidence_items: list[Evidence]) -> None:
    _ASSESSMENT_EVIDENCE_CACHE[assessment_id] = evidence_items
    while len(_ASSESSMENT_EVIDENCE_CACHE) > 256:
        oldest_key = next(iter(_ASSESSMENT_EVIDENCE_CACHE))
        del _ASSESSMENT_EVIDENCE_CACHE[oldest_key]


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
) -> EvidenceListResponse:
    cached_items = _ASSESSMENT_EVIDENCE_CACHE.get(assessment_id)
    if cached_items is None:
        items = list(fetch_db_evidence(assessment_id, page_size=page_size))
    else:
        items = cached_items[:page_size]
    return EvidenceListResponse(
        assessment_id=assessment_id,
        items=items,
        next_cursor=None,
    )
