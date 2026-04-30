from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any, cast

import psycopg
from psycopg.types.json import Jsonb
from psycopg.rows import dict_row


ConnectionFactory = Callable[[], Any]


class EvidenceRepositoryUnavailable(RuntimeError):
    """Raised when evidence storage cannot be queried."""


@dataclass(frozen=True)
class EvidenceRecord:
    id: str
    source_id: str
    source_type: str
    event_type: str
    title: str
    summary: str
    url: str | None
    occurred_at: datetime | None
    observed_at: datetime | None
    ingested_at: datetime
    lat: float | None
    lng: float | None
    geometry: dict[str, Any] | None
    distance_to_query_m: float | None
    confidence: float
    freshness_score: float
    source_weight: float
    privacy_level: str
    raw_ref: str | None


@dataclass(frozen=True)
class QueryHeatSnapshot:
    period: str
    query_count: int
    unique_approx_count: int
    query_count_bucket: str
    unique_approx_count_bucket: str
    updated_at: datetime
    limited: bool = False


@dataclass(frozen=True)
class RiskAssessmentPersistence:
    assessment_id: str
    lat: float
    lng: float
    radius_m: int
    location_text: str | None
    score_version: str
    realtime_score: float
    historical_score: float
    confidence_score: float
    realtime_level: str
    historical_level: str
    explanation: dict[str, Any]
    data_freshness: list[dict[str, Any]]
    evidence_ids: tuple[str, ...]
    created_at: datetime
    expires_at: datetime


def persist_risk_assessment(
    *,
    database_url: str,
    assessment: RiskAssessmentPersistence,
    connection_factory: ConnectionFactory | None = None,
) -> None:
    sql = """
        WITH inserted_query AS (
            INSERT INTO location_queries (
                input_type,
                raw_input,
                geom,
                radius_m,
                privacy_bucket,
                h3_index,
                created_at
            )
            VALUES (
                'map_click',
                %s,
                ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                %s,
                %s,
                %s,
                %s
            )
            RETURNING id
        ),
        inserted_assessment AS (
            INSERT INTO risk_assessments (
                id,
                query_id,
                score_version,
                realtime_score,
                historical_score,
                confidence_score,
                risk_level_realtime,
                risk_level_historical,
                explanation,
                data_freshness,
                created_at,
                expires_at
            )
            SELECT
                %s::uuid,
                inserted_query.id,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s::jsonb,
                %s::jsonb,
                %s,
                %s
            FROM inserted_query
            ON CONFLICT (id) DO NOTHING
            RETURNING id
        )
        INSERT INTO risk_assessment_evidence (
            risk_assessment_id,
            evidence_id,
            relevance_score,
            reason,
            created_at
        )
        SELECT
            inserted_assessment.id,
            evidence.id,
            1.0,
            'selected_for_assessment',
            %s
        FROM inserted_assessment
        JOIN evidence ON evidence.id = ANY(%s::uuid[])
        ON CONFLICT (risk_assessment_id, evidence_id) DO NOTHING
    """
    privacy_bucket = _privacy_bucket(assessment.lat, assessment.lng)
    params = (
        assessment.location_text,
        assessment.lng,
        assessment.lat,
        assessment.radius_m,
        privacy_bucket,
        privacy_bucket,
        assessment.created_at,
        assessment.assessment_id,
        assessment.score_version,
        assessment.realtime_score,
        assessment.historical_score,
        assessment.confidence_score,
        _storage_risk_level(assessment.realtime_level),
        _storage_risk_level(assessment.historical_level),
        Jsonb(assessment.explanation),
        Jsonb(assessment.data_freshness),
        assessment.created_at,
        assessment.expires_at,
        assessment.created_at,
        list(assessment.evidence_ids),
    )
    try:
        with _connect(database_url, connection_factory) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
    except (OSError, psycopg.Error) as exc:
        raise EvidenceRepositoryUnavailable(str(exc)) from exc


def query_nearby_evidence(
    *,
    database_url: str,
    lat: float,
    lng: float,
    radius_m: int,
    limit: int = 50,
    connection_factory: ConnectionFactory | None = None,
) -> tuple[EvidenceRecord, ...]:
    sql = """
        WITH query_point AS (
            SELECT ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography AS geog
        )
        SELECT
            e.id::text AS id,
            e.source_id,
            e.source_type,
            e.event_type,
            e.title,
            e.summary,
            e.url,
            e.occurred_at,
            e.observed_at,
            e.ingested_at,
            ST_Y(ST_PointOnSurface(e.geom::geometry)) AS lat,
            ST_X(ST_PointOnSurface(e.geom::geometry)) AS lng,
            ST_AsGeoJSON(e.geom::geometry) AS geometry,
            ST_Distance(e.geom::geography, qp.geog) AS distance_to_query_m,
            e.confidence,
            COALESCE(e.freshness_score, 0.8) AS freshness_score,
            COALESCE(e.source_weight, CASE WHEN e.source_type = 'official' THEN 1.0 ELSE 0.85 END)
                AS source_weight,
            e.privacy_level,
            e.raw_ref
        FROM evidence e
        CROSS JOIN query_point qp
        WHERE e.ingestion_status = 'accepted'
            AND e.privacy_level IN ('public', 'aggregated')
            AND e.geom IS NOT NULL
            AND ST_DWithin(e.geom::geography, qp.geog, %s)
        ORDER BY
            distance_to_query_m ASC,
            e.occurred_at DESC NULLS LAST,
            e.created_at DESC
        LIMIT %s
    """
    return _fetch_records(
        sql,
        (lng, lat, radius_m, max(1, min(limit, 100))),
        database_url=database_url,
        connection_factory=connection_factory,
    )


def fetch_query_heat_snapshot(
    *,
    database_url: str,
    lat: float,
    lng: float,
    radius_m: int,
    period: str = "P7D",
    connection_factory: ConnectionFactory | None = None,
) -> QueryHeatSnapshot:
    sql = """
        WITH query_point AS (
            SELECT ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography AS geog
        ),
        nearby_queries AS (
            SELECT lq.id, lq.privacy_bucket, lq.h3_index, lq.created_at
            FROM location_queries lq
            CROSS JOIN query_point qp
            WHERE lq.geom IS NOT NULL
                AND lq.created_at >= now() - (%s::interval)
                AND ST_DWithin(lq.geom::geography, qp.geog, %s)
        )
        SELECT
            COUNT(*)::integer AS query_count,
            COUNT(DISTINCT COALESCE(privacy_bucket, h3_index, id::text))::integer
                AS unique_approx_count,
            COALESCE(MAX(created_at), now()) AS updated_at
        FROM nearby_queries
    """
    try:
        with _connect(database_url, connection_factory) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, (lng, lat, _period_to_interval(period), radius_m))
                row = cursor.fetchone()
    except (OSError, psycopg.Error) as exc:
        raise EvidenceRepositoryUnavailable(str(exc)) from exc

    query_count = int(row["query_count"] if isinstance(row, dict) else row[0])
    unique_approx_count = int(row["unique_approx_count"] if isinstance(row, dict) else row[1])
    updated_at = row["updated_at"] if isinstance(row, dict) else row[2]
    return QueryHeatSnapshot(
        period=period,
        query_count=query_count,
        unique_approx_count=unique_approx_count,
        query_count_bucket=_count_bucket(query_count),
        unique_approx_count_bucket=_count_bucket(unique_approx_count),
        updated_at=updated_at,
    )


def fetch_assessment_evidence(
    *,
    database_url: str,
    assessment_id: str,
    page_size: int = 20,
    connection_factory: ConnectionFactory | None = None,
) -> tuple[EvidenceRecord, ...]:
    sql = """
        SELECT
            e.id::text AS id,
            e.source_id,
            e.source_type,
            e.event_type,
            e.title,
            e.summary,
            e.url,
            e.occurred_at,
            e.observed_at,
            e.ingested_at,
            ST_Y(ST_PointOnSurface(e.geom::geometry)) AS lat,
            ST_X(ST_PointOnSurface(e.geom::geometry)) AS lng,
            ST_AsGeoJSON(e.geom::geometry) AS geometry,
            CASE
                WHEN e.geom IS NOT NULL THEN ST_Distance(e.geom::geography, lq.geom::geography)
                ELSE e.distance_to_query_m
            END AS distance_to_query_m,
            e.confidence,
            COALESCE(e.freshness_score, 0.8) AS freshness_score,
            COALESCE(e.source_weight, CASE WHEN e.source_type = 'official' THEN 1.0 ELSE 0.85 END)
                AS source_weight,
            e.privacy_level,
            e.raw_ref
        FROM risk_assessment_evidence rae
        JOIN risk_assessments ra ON ra.id = rae.risk_assessment_id
        JOIN location_queries lq ON lq.id = ra.query_id
        JOIN evidence e ON e.id = rae.evidence_id
        WHERE ra.id = %s
            AND e.ingestion_status = 'accepted'
            AND e.privacy_level IN ('public', 'aggregated')
        ORDER BY
            rae.created_at ASC,
            e.occurred_at DESC NULLS LAST,
            e.created_at DESC
        LIMIT %s
    """
    return _fetch_records(
        sql,
        (assessment_id, max(1, min(page_size, 100))),
        database_url=database_url,
        connection_factory=connection_factory,
    )


def _fetch_records(
    sql: str,
    params: tuple[object, ...],
    *,
    database_url: str,
    connection_factory: ConnectionFactory | None,
) -> tuple[EvidenceRecord, ...]:
    try:
        with _connect(database_url, connection_factory) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                return tuple(_record_from_row(row) for row in cursor.fetchall())
    except (OSError, psycopg.Error) as exc:
        raise EvidenceRepositoryUnavailable(str(exc)) from exc


def _connect(database_url: str, connection_factory: ConnectionFactory | None) -> Any:
    if connection_factory is not None:
        return connection_factory()
    return psycopg.connect(database_url, connect_timeout=2, row_factory=dict_row)


def _record_from_row(row: dict[str, Any]) -> EvidenceRecord:
    return EvidenceRecord(
        id=str(row["id"]),
        source_id=str(row["source_id"]),
        source_type=str(row["source_type"]),
        event_type=str(row["event_type"]),
        title=str(row["title"]),
        summary=str(row["summary"]),
        url=str(row["url"]) if row.get("url") is not None else None,
        occurred_at=row.get("occurred_at"),
        observed_at=row.get("observed_at"),
        ingested_at=row["ingested_at"],
        lat=_optional_float(row.get("lat")),
        lng=_optional_float(row.get("lng")),
        geometry=_geometry(row.get("geometry")),
        distance_to_query_m=_optional_float(row.get("distance_to_query_m")),
        confidence=float(row["confidence"]),
        freshness_score=float(row["freshness_score"]),
        source_weight=float(row["source_weight"]),
        privacy_level=str(row["privacy_level"]),
        raw_ref=str(row["raw_ref"]) if row.get("raw_ref") is not None else None,
    )


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(cast(Any, value))


def _geometry(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        payload = json.loads(value)
        return payload if isinstance(payload, dict) else None
    return None


def _period_to_interval(period: str) -> str:
    if period == "P1D":
        return "1 day"
    if period == "P30D":
        return "30 days"
    return "7 days"


def _count_bucket(count: int) -> str:
    if count <= 0:
        return "0"
    if count < 10:
        return "1-9"
    if count < 50:
        return "10-49"
    if count < 100:
        return "50-99"
    if count < 500:
        return "100-499"
    return "500+"


def _privacy_bucket(lat: float, lng: float) -> str:
    return f"{round(lat, 2):.2f},{round(lng, 2):.2f}"


def _storage_risk_level(level: str) -> str:
    if level == "雿?":
        return "low"
    if level == "銝?":
        return "medium"
    if level == "擃?":
        return "high"
    if level == "璆菟?":
        return "severe"
    return "unknown"
