from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any, cast

import psycopg
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
            ST_Y(e.geom::geometry) AS lat,
            ST_X(e.geom::geometry) AS lng,
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
            ST_Y(e.geom::geometry) AS lat,
            ST_X(e.geom::geometry) AS lng,
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
