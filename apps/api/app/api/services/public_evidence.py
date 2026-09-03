from __future__ import annotations

import base64
import binascii
import json
from datetime import UTC, datetime
from typing import Any, Protocol, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from app.api.schemas import (
    Evidence,
    EvidenceListResponse,
    EvidencePreview,
    GeoJsonGeometry,
    LatLng,
)
from app.api.services import public_evidence_cache
from app.domain.evidence import (
    EvidenceRecord,
    EvidenceUpsert,
    HistoricalEvidencePagePosition,
)
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


class FetchAssessmentHistory(Protocol):
    def __call__(
        self,
        *,
        assessment_id: str,
        page_size: int,
        after: HistoricalEvidencePagePosition | None,
    ) -> tuple[EvidenceRecord, ...]: ...


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


def water_level_realtime_risk_factor(
    *,
    water_level_m: float,
    warning_level_m: float,
) -> float:
    ratio = water_level_m / warning_level_m
    if ratio >= 1.0:
        return 1.0
    if ratio >= 0.8:
        return 0.8
    if ratio >= 0.5:
        return 0.5
    if ratio >= 0.25:
        return 0.25
    return 0.0


def flood_depth_realtime_risk_factor(flood_depth_cm: float) -> float:
    if flood_depth_cm >= 50:
        return 1.0
    if flood_depth_cm >= 30:
        return 0.8
    if flood_depth_cm >= 15:
        return 0.5
    if flood_depth_cm >= 3:
        return 0.25
    return 0.0


def _evidence_realtime_risk_factor(record: EvidenceRecord) -> float | None:
    if record.realtime_risk_factor is not None:
        return record.realtime_risk_factor
    if record.event_type == "rainfall" and record.rainfall_mm_1h is not None:
        return rainfall_realtime_risk_factor(record.rainfall_mm_1h)
    if (
        record.event_type == "water_level"
        and record.water_level_m is not None
        and record.warning_level_m is not None
        and record.warning_level_m > 0
    ):
        return water_level_realtime_risk_factor(
            water_level_m=record.water_level_m,
            warning_level_m=record.warning_level_m,
        )
    if record.event_type == "flood_report" and record.flood_depth_cm is not None:
        return flood_depth_realtime_risk_factor(record.flood_depth_cm)
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
        evidence_scope=record.evidence_scope,
        location_precision=record.location_precision,
        limitations=list(record.limitations),
        event_year=record.event_year,
        temporal_precision=record.temporal_precision,
        event_start_at=record.event_start_at,
        event_end_at=record.event_end_at,
        observation_count=record.observation_count,
        episode_algorithm_version=record.episode_algorithm_version,
    )


def localized_evidence_text(record: EvidenceRecord) -> tuple[str, str]:
    if record.event_type == "flood_potential":
        return (
            "官方淹水潛勢規劃圖資",
            (
                "此筆資料表示查詢範圍與官方淹水潛勢規劃圖資相交，屬於歷史與情境參考；"
                "不代表目前正在淹水，也不是即時災害警報。"
            ),
        )
    return (record.title, record.summary)


def public_evidence_url(
    *,
    source_type: str,
    event_type: str,
    fallback_url: str | None,
) -> str | None:
    if source_type == "official":
        # Persisted official observations carry the reviewed landing page for
        # the adapter that actually produced the row.  Preserve that
        # provenance: mapping only by event type would relabel every local
        # rainfall/water/flood sensor as the central CWA/WRA dataset and, most
        # visibly, point current Tainan flood depth at the historical 130016
        # dataset.  The generic catalog remains a compatibility fallback for
        # older rows that have no source URL.
        return fallback_url or OFFICIAL_DATA_GOV_URLS.get(event_type)
    return fallback_url


def assessment_db_evidence(
    assessment_id: str,
    *,
    page_size: int,
    database_url: str,
    fetch_assessment_evidence: FetchAssessmentEvidence,
) -> tuple[Evidence, ...]:
    records = fetch_assessment_evidence(
        database_url=database_url,
        assessment_id=assessment_id,
        page_size=page_size,
    )
    return tuple(evidence_from_record(record) for record in records)


def list_assessment_history(
    assessment_id: str,
    *,
    cursor: str | None,
    page_size: int,
    fetch_history: FetchAssessmentHistory,
) -> EvidenceListResponse:
    after = decode_history_cursor(cursor, assessment_id=assessment_id) if cursor else None
    records = fetch_history(
        assessment_id=assessment_id,
        page_size=page_size,
        after=after,
    )
    has_more = len(records) > page_size
    visible = records[:page_size]
    next_cursor = (
        encode_history_cursor(
            assessment_id=assessment_id,
            position=_history_page_position(visible[-1]),
        )
        if has_more and visible
        else None
    )
    return EvidenceListResponse(
        assessment_id=assessment_id,
        items=[evidence_from_record(record) for record in visible],
        next_cursor=next_cursor,
    )


def encode_history_cursor(
    *,
    assessment_id: str,
    position: HistoricalEvidencePagePosition,
) -> str:
    payload = {
        "v": 1,
        "a": str(UUID(assessment_id)),
        "y": position.event_year,
        "t": position.event_time.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "i": str(UUID(position.evidence_id)),
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).decode("ascii")
    return encoded.rstrip("=")


def decode_history_cursor(
    value: str,
    *,
    assessment_id: str,
) -> HistoricalEvidencePagePosition:
    if not value or len(value) > 2048:
        raise ValueError("invalid history cursor")
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        if not isinstance(payload, dict) or payload.get("v") != 1:
            raise ValueError
        bound_assessment = str(UUID(str(payload["a"])))
        expected_assessment = str(UUID(assessment_id))
        if bound_assessment != expected_assessment:
            raise ValueError
        event_year = int(payload["y"])
        if not 1900 <= event_year <= 2100:
            raise ValueError
        event_time = datetime.fromisoformat(str(payload["t"]).replace("Z", "+00:00"))
        if event_time.tzinfo is None or event_time.utcoffset() is None:
            raise ValueError
        evidence_id = str(UUID(str(payload["i"])))
    except (
        KeyError,
        TypeError,
        ValueError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        binascii.Error,
    ) as exc:
        raise ValueError("invalid history cursor") from exc
    return HistoricalEvidencePagePosition(
        event_year=event_year,
        event_time=event_time,
        evidence_id=evidence_id,
    )


def _history_page_position(record: EvidenceRecord) -> HistoricalEvidencePagePosition:
    taipei = ZoneInfo("Asia/Taipei")
    event_time = (
        record.event_end_at
        or record.event_start_at
        or record.occurred_at
        or record.observed_at
    )
    event_year = record.event_year
    if event_year is None:
        fallback = event_time or record.ingested_at
        event_year = fallback.astimezone(taipei).year
    if record.temporal_precision == "year":
        event_time = datetime(event_year, 1, 1, tzinfo=taipei)
    elif event_time is None:
        event_time = record.ingested_at
    return HistoricalEvidencePagePosition(
        event_year=event_year,
        event_time=event_time,
        evidence_id=record.id,
    )


def list_assessment_evidence(
    assessment_id: str,
    *,
    page_size: int,
    fetch_db_evidence: AssessmentDbEvidence,
    backend: str = "memory",
    redis_url: str | None = None,
) -> EvidenceListResponse:
    # The persisted association and current source gates are the authorization
    # boundary. Legacy memory/Redis entries can outlive source enablement and
    # therefore must never authorize the v1 detail response.
    del backend, redis_url
    items = list(fetch_db_evidence(assessment_id, page_size=page_size))
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
        evidence_scope="current",
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
        evidence_scope="historical",
        event_year=(
            record.event_year
            if record.event_year is not None
            else record.occurred_at.year
            if record.occurred_at is not None
            else None
        ),
        temporal_precision=record.temporal_precision,
        event_start_at=(
            record.occurred_at if record.temporal_precision != "year" else None
        ),
        event_end_at=(
            record.occurred_at if record.temporal_precision != "year" else None
        ),
    )


def evidence_from_upsert(record: EvidenceUpsert) -> Evidence:
    evidence_scope = record.properties.get("evidence_scope", "historical")
    location_precision = record.properties.get("location_precision", "unknown")
    limitations = record.properties.get("limitations", [])
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
        evidence_scope=cast(Any, evidence_scope),
        location_precision=cast(Any, location_precision),
        limitations=(
            [str(value) for value in limitations] if isinstance(limitations, list) else []
        ),
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
        location_precision=evidence.location_precision,
        limitations=list(evidence.limitations),
        evidence_scope=evidence.evidence_scope,
        event_year=evidence.event_year,
        temporal_precision=evidence.temporal_precision,
        event_start_at=evidence.event_start_at,
        event_end_at=evidence.event_end_at,
        observation_count=evidence.observation_count,
        episode_algorithm_version=evidence.episode_algorithm_version,
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
            evidence.realtime_risk_factor if evidence.realtime_risk_factor is not None else 1.0
        ),
        observed_at=evidence.observed_at or evidence.occurred_at,
        evidence_scope=evidence.evidence_scope,
    )


def display_evidence_items(evidence_items: list[Evidence]) -> list[Evidence]:
    return sorted(collapse_flood_potential_items(evidence_items), key=_display_sort_key)


def _display_sort_key(item: Evidence) -> tuple[int, float, float, str]:
    scope_rank = {"current": 0, "context": 1, "historical": 2}.get(
        item.evidence_scope,
        3,
    )
    if (
        item.evidence_scope == "historical"
        and item.temporal_precision == "year"
        and item.event_year is not None
    ):
        event_time = datetime(item.event_year, 1, 1, tzinfo=ZoneInfo("Asia/Taipei"))
    elif item.evidence_scope == "historical":
        event_time = (
            item.event_end_at
            or item.event_start_at
            or item.occurred_at
            or item.observed_at
        )
    else:
        event_time = item.observed_at or item.occurred_at or item.ingested_at
    if event_time is None:
        event_time = item.ingested_at
    timestamp = event_time.timestamp() if event_time is not None else 0.0
    distance = item.distance_to_query_m if item.distance_to_query_m is not None else float("inf")
    return scope_rank, -timestamp, distance, item.id


def select_evidence_preview_items(
    evidence_items: list[Evidence],
    *,
    limit: int,
) -> list[Evidence]:
    """Reserve one item per scope/signal family before filling the preview."""

    if limit <= 0:
        return []
    reserved_indices: list[int] = []
    seen_families: set[tuple[str, str]] = set()
    for index, item in enumerate(evidence_items):
        family = (item.evidence_scope, item.event_type)
        if family in seen_families:
            continue
        seen_families.add(family)
        reserved_indices.append(index)
        if len(reserved_indices) == limit:
            return [evidence_items[index] for index in reserved_indices]

    reserved = set(reserved_indices)
    selected = [evidence_items[index] for index in reserved_indices]
    selected.extend(item for index, item in enumerate(evidence_items) if index not in reserved)
    return selected[:limit]


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
