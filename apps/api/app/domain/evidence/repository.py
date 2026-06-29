from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import json
import re
from typing import Any, cast

import psycopg
from psycopg.types.json import Jsonb
from psycopg.rows import dict_row


ConnectionFactory = Callable[[], Any]
QUERY_HEAT_STATEMENT_TIMEOUT_MS = 1_200
_LATEST_OFFICIAL_RELATION = "official_realtime_latest"


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
    rainfall_mm_1h: float | None = None
    water_level_m: float | None = None
    warning_level_m: float | None = None
    flood_depth_cm: float | None = None
    realtime_risk_factor: float | None = None


@dataclass(frozen=True)
class NearbyCoverageRow:
    adapter_key: str
    source_id: str
    event_type: str
    station_id: str | None
    observed_at: datetime | None
    ingested_at: datetime
    distance_to_query_m: float
    freshness_state: str


@dataclass(frozen=True)
class EvidenceUpsert:
    id: str
    adapter_key: str
    source_id: str
    source_type: str
    event_type: str
    title: str
    summary: str
    url: str | None
    occurred_at: datetime | None
    observed_at: datetime | None
    ingested_at: datetime
    lat: float
    lng: float
    distance_to_query_m: float | None
    confidence: float
    freshness_score: float
    source_weight: float
    privacy_level: str
    raw_ref: str
    properties: dict[str, Any]


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
    result_snapshot: dict[str, Any]
    evidence_ids: tuple[str, ...]
    created_at: datetime
    expires_at: datetime


def persist_risk_assessment(
    *,
    database_url: str,
    assessment: RiskAssessmentPersistence,
    statement_timeout_ms: int = 0,
    connection_factory: ConnectionFactory | None = None,
) -> None:
    sql = """
        WITH inserted_query AS (
            INSERT INTO location_queries (
                input_type,
                raw_input,
                lat,
                lng,
                geom,
                radius_m,
                privacy_bucket,
                h3_index,
                created_at
            )
            VALUES (
                'map_click',
                %s,
                %s,
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
                risk_level,
                explanation,
                data_freshness,
                result_snapshot,
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
                %s,
                %s::jsonb,
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
        assessment.lat,
        assessment.lng,
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
        _max_storage_risk_level(assessment.realtime_level, assessment.historical_level),
        Jsonb(assessment.explanation),
        Jsonb(assessment.data_freshness),
        Jsonb(assessment.result_snapshot),
        assessment.created_at,
        assessment.expires_at,
        assessment.created_at,
        list(assessment.evidence_ids),
    )
    try:
        with _connect(database_url, connection_factory) as connection:
            with connection.cursor() as cursor:
                _apply_statement_timeout(cursor, statement_timeout_ms)
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
    rainfall_relevance_m: int | None = None,
    water_relevance_m: int | None = None,
    official_realtime_since: datetime | None = None,
    statement_timeout_ms: int = 0,
    connection_factory: ConnectionFactory | None = None,
) -> tuple[EvidenceRecord, ...]:
    """Fetch accepted evidence near a query point.

    All evidence is selected within ``radius_m``. Official realtime station
    observations (``rainfall``/``water_level``) may additionally be selected out
    to ``rainfall_relevance_m`` / ``water_relevance_m`` so a cold small-radius
    lookup still sees the nearest rainfall/water station instead of reporting
    "即時資料不足"; the scoring distance factor down-weights the farther station.
    ``official_realtime_since`` bounds official station snapshots to recent data.
    When the relevance arguments are omitted they default to ``radius_m`` (no
    extension), preserving the strict-radius behavior.
    """

    rainfall_relevance = max(radius_m, rainfall_relevance_m or radius_m)
    water_relevance = max(radius_m, water_relevance_m or radius_m)
    bounded_limit = max(1, min(limit, 100))
    official_realtime_limit = 1
    sql = """
        WITH query_point AS (
            SELECT
                ST_SetSRID(ST_MakePoint(%s, %s), 4326) AS geom,
                ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography AS geog,
                (%s::double precision / 90000.0) AS degree_radius,
                (%s::double precision / 90000.0) AS rainfall_degree,
                (%s::double precision / 90000.0) AS water_degree
        ),
        candidate_rows AS (
            SELECT *
            FROM (
                SELECT
                    e.*,
                    (ST_Distance(e.geom, qp.geom) * 90000.0) AS computed_distance_to_query_m,
                    %s::double precision AS branch_relevance_m
                FROM evidence e
                CROSS JOIN query_point qp
                WHERE e.ingestion_status = 'accepted'
                    AND e.privacy_level IN ('public', 'aggregated')
                    AND e.geom IS NOT NULL
                    AND NOT (
                        e.source_type = 'official'
                        AND e.event_type IN ('rainfall', 'water_level')
                    )
                    AND e.geom && ST_Expand(qp.geom, qp.degree_radius)
                    AND ST_DWithin(e.geom, qp.geom, qp.degree_radius)
                ORDER BY
                    computed_distance_to_query_m ASC,
                    e.occurred_at DESC NULLS LAST,
                    e.created_at DESC
                LIMIT %s
            ) nearby_evidence
            UNION ALL
            SELECT *
            FROM (
                SELECT
                    e.*,
                    ST_Distance(e.geom::geography, qp.geog) AS computed_distance_to_query_m,
                    %s::double precision AS branch_relevance_m
                FROM evidence e
                CROSS JOIN query_point qp
                WHERE e.ingestion_status = 'accepted'
                    AND e.privacy_level IN ('public', 'aggregated')
                    AND e.geom IS NOT NULL
                    AND e.source_type = 'official'
                    AND e.event_type = 'rainfall'
                    AND (%s::timestamptz IS NULL OR e.observed_at >= %s::timestamptz)
                    AND e.geom && ST_Expand(qp.geom, qp.rainfall_degree)
                    AND ST_DWithin(e.geom, qp.geom, qp.rainfall_degree)
                ORDER BY
                    computed_distance_to_query_m ASC,
                    e.observed_at DESC NULLS LAST,
                    e.created_at DESC
                LIMIT %s
            ) rainfall_evidence
            UNION ALL
            SELECT *
            FROM (
                SELECT
                    e.*,
                    ST_Distance(e.geom::geography, qp.geog) AS computed_distance_to_query_m,
                    %s::double precision AS branch_relevance_m
                FROM evidence e
                CROSS JOIN query_point qp
                WHERE e.ingestion_status = 'accepted'
                    AND e.privacy_level IN ('public', 'aggregated')
                    AND e.geom IS NOT NULL
                    AND e.source_type = 'official'
                    AND e.event_type = 'water_level'
                    AND (%s::timestamptz IS NULL OR e.observed_at >= %s::timestamptz)
                    AND e.geom && ST_Expand(qp.geom, qp.water_degree)
                    AND ST_DWithin(e.geom, qp.geom, qp.water_degree)
                ORDER BY
                    computed_distance_to_query_m ASC,
                    e.observed_at DESC NULLS LAST,
                    e.created_at DESC
                LIMIT %s
            ) water_level_evidence
        )
        SELECT
            c.id::text AS id,
            c.source_id,
            c.source_type,
            c.event_type,
            c.title,
            c.summary,
            c.url,
            c.occurred_at,
            c.observed_at,
            c.ingested_at,
            ST_Y(ST_PointOnSurface(c.geom::geometry)) AS lat,
            ST_X(ST_PointOnSurface(c.geom::geometry)) AS lng,
            ST_AsGeoJSON(ST_PointOnSurface(c.geom::geometry)) AS geometry,
            c.computed_distance_to_query_m AS distance_to_query_m,
            c.confidence,
            COALESCE(c.freshness_score, 0.8) AS freshness_score,
            COALESCE(c.source_weight, CASE WHEN c.source_type = 'official' THEN 1.0 ELSE 0.85 END)
                AS source_weight,
            c.privacy_level,
            c.raw_ref,
            (c.properties->>'rainfall_mm_1h')::double precision AS rainfall_mm_1h,
            (c.properties->>'water_level_m')::double precision AS water_level_m,
            (c.properties->>'warning_level_m')::double precision AS warning_level_m,
            (c.properties->>'flood_depth_cm')::double precision AS flood_depth_cm,
            NULL::double precision AS realtime_risk_factor
        FROM candidate_rows c
        WHERE c.computed_distance_to_query_m <= c.branch_relevance_m
        ORDER BY
            CASE
                WHEN c.source_type = 'official'
                    AND c.event_type IN ('rainfall', 'water_level')
                THEN 0
                ELSE 1
            END ASC,
            computed_distance_to_query_m ASC,
            c.occurred_at DESC NULLS LAST,
            c.created_at DESC
        LIMIT %s
    """
    return _fetch_records(
        sql,
        (
            lng,
            lat,
            lng,
            lat,
            radius_m,
            rainfall_relevance,
            water_relevance,
            radius_m,
            bounded_limit,
            rainfall_relevance,
            official_realtime_since,
            official_realtime_since,
            official_realtime_limit,
            water_relevance,
            official_realtime_since,
            official_realtime_since,
            official_realtime_limit,
            bounded_limit,
        ),
        database_url=database_url,
        statement_timeout_ms=statement_timeout_ms,
        connection_factory=connection_factory,
    )


def query_nearby_latest_official(
    *,
    database_url: str,
    lat: float,
    lng: float,
    limit: int = 50,
    rainfall_radius_m: int = 10_000,
    water_level_radius_m: int = 3_000,
    flood_depth_radius_m: int = 1_000,
    flood_warning_radius_m: int = 10_000,
    observed_since: datetime | None = None,
    statement_timeout_ms: int = 0,
    connection_factory: ConnectionFactory | None = None,
) -> tuple[EvidenceRecord, ...]:
    bounded_limit = max(1, min(limit, 100))
    observed_since_filter = ""
    observed_since_params: tuple[datetime, ...] = ()
    if observed_since is not None:
        observed_since_filter = "AND latest.observed_at >= %s::timestamptz"
        observed_since_params = (observed_since,)
    sql = f"""
        WITH query_point_base AS (
            SELECT
                ST_SetSRID(ST_MakePoint(%s, %s), 4326) AS geom,
                ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography AS geog,
                %s::double precision AS rainfall_m,
                %s::double precision AS water_level_m,
                %s::double precision AS flood_depth_m,
                %s::double precision AS flood_warning_m
        ),
        query_point AS (
            SELECT
                *,
                (rainfall_m / 90000.0) AS rainfall_degree,
                (water_level_m / 90000.0) AS water_level_degree,
                (flood_depth_m / 90000.0) AS flood_depth_degree,
                (flood_warning_m / 90000.0) AS flood_warning_degree
            FROM query_point_base
        )
        SELECT
            COALESCE(e.id::text, latest.source_id) AS id,
            latest.source_id,
            'official' AS source_type,
            latest.event_type,
            COALESCE(
                e.title,
                CASE latest.event_type
                    WHEN 'rainfall' THEN '官方最新雨量站觀測'
                    WHEN 'water_level' THEN '官方最新水位站觀測'
                    WHEN 'flood_report' THEN '官方最新淹水觀測'
                    WHEN 'flood_warning' THEN '官方最新淹水警戒'
                    ELSE '官方最新即時觀測'
                END
            ) AS title,
            COALESCE(
                e.summary,
                CASE latest.event_type
                    WHEN 'rainfall' THEN '官方最新雨量站觀測值。'
                    WHEN 'water_level' THEN '官方最新水位站觀測值。'
                    WHEN 'flood_report' THEN '官方最新淹水感測觀測值。'
                    WHEN 'flood_warning' THEN '官方最新淹水警戒。'
                    ELSE '官方最新即時觀測值。'
                END
            ) AS summary,
            COALESCE(e.url, latest.source_url) AS url,
            e.occurred_at,
            latest.observed_at,
            latest.ingested_at,
            ST_Y(ST_PointOnSurface(latest.geom::geometry)) AS lat,
            ST_X(ST_PointOnSurface(latest.geom::geometry)) AS lng,
            ST_AsGeoJSON(ST_PointOnSurface(latest.geom::geometry)) AS geometry,
            ST_Distance(latest.geom::geography, qp.geog) AS distance_to_query_m,
            COALESCE(latest.confidence, e.confidence, 0.9) AS confidence,
            COALESCE(latest.freshness_score, e.freshness_score, 0.8) AS freshness_score,
            COALESCE(latest.source_weight, e.source_weight, 1.0) AS source_weight,
            'public' AS privacy_level,
            CONCAT(
                'official-realtime-latest:',
                latest.adapter_key,
                ':',
                latest.event_type,
                ':',
                latest.station_id
            ) AS raw_ref,
            latest.rainfall_mm_1h,
            latest.water_level_m,
            latest.warning_level_m,
            latest.flood_depth_cm,
            latest.risk_factor AS realtime_risk_factor
        FROM official_realtime_latest latest
        CROSS JOIN query_point qp
        LEFT JOIN evidence e ON e.id = latest.evidence_id
        WHERE latest.geom IS NOT NULL
            {observed_since_filter}
            AND (
                (
                    latest.event_type = 'rainfall'
                    AND latest.geom && ST_Expand(qp.geom, qp.rainfall_degree)
                    AND ST_DWithin(latest.geom::geography, qp.geog, qp.rainfall_m)
                )
                OR (
                    latest.event_type = 'water_level'
                    AND latest.geom && ST_Expand(qp.geom, qp.water_level_degree)
                    AND ST_DWithin(latest.geom::geography, qp.geog, qp.water_level_m)
                )
                OR (
                    latest.event_type = 'flood_report'
                    AND latest.geom && ST_Expand(qp.geom, qp.flood_depth_degree)
                    AND ST_DWithin(latest.geom::geography, qp.geog, qp.flood_depth_m)
                )
                OR (
                    latest.event_type = 'flood_warning'
                    AND latest.geom && ST_Expand(qp.geom, qp.flood_warning_degree)
                    AND ST_DWithin(latest.geom::geography, qp.geog, qp.flood_warning_m)
                )
            )
        ORDER BY
            distance_to_query_m ASC,
            latest.observed_at DESC,
            latest.updated_at DESC
        LIMIT %s
    """
    try:
        with _connect(database_url, connection_factory) as connection:
            with connection.cursor() as cursor:
                _apply_statement_timeout(cursor, statement_timeout_ms)
                cursor.execute(
                    sql,
                    (
                        lng,
                        lat,
                        lng,
                        lat,
                        rainfall_radius_m,
                        water_level_radius_m,
                        flood_depth_radius_m,
                        flood_warning_radius_m,
                        *observed_since_params,
                        bounded_limit,
                    ),
                )
                return tuple(_record_from_row(row) for row in cursor.fetchall())
    except psycopg.errors.UndefinedTable as exc:
        if _is_missing_relation(exc, _LATEST_OFFICIAL_RELATION):
            return ()
        raise EvidenceRepositoryUnavailable(str(exc)) from exc
    except (OSError, psycopg.Error) as exc:
        raise EvidenceRepositoryUnavailable(str(exc)) from exc


def query_nearby_realtime_coverage_rows(
    *,
    database_url: str,
    lat: float,
    lng: float,
    radius_buckets_m: tuple[int, ...] = (500, 1000, 3000, 5000),
    observed_since: datetime | None = None,
    statement_timeout_ms: int = 1500,
    connection_factory: ConnectionFactory | None = None,
) -> tuple[NearbyCoverageRow, ...]:
    max_radius_m = max(radius_buckets_m)
    observed_filter = "AND latest.observed_at >= %s::timestamptz" if observed_since else ""
    observed_params: tuple[datetime, ...] = (observed_since,) if observed_since else ()
    sql = f"""
        WITH query_point AS (
            SELECT
                ST_SetSRID(ST_MakePoint(%s, %s), 4326) AS geom,
                ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography AS geog,
                (%s::double precision / 90000.0) AS degree_radius
        )
        SELECT
            latest.adapter_key,
            latest.source_id,
            latest.event_type,
            latest.station_id,
            latest.observed_at,
            latest.ingested_at,
            ST_Distance(latest.geom::geography, qp.geog) AS distance_to_query_m,
            CASE
                WHEN latest.observed_at IS NULL THEN 'stale'
                WHEN latest.observed_at >= now() - interval '10 minutes' THEN 'fresh'
                WHEN latest.observed_at >= now() - interval '60 minutes' THEN 'stale'
                ELSE 'stale'
            END AS freshness_state
        FROM official_realtime_latest latest
        CROSS JOIN query_point qp
        WHERE latest.geom IS NOT NULL
            {observed_filter}
            AND latest.geom && ST_Expand(qp.geom, qp.degree_radius)
            AND ST_DWithin(latest.geom::geography, qp.geog, %s)
        ORDER BY distance_to_query_m ASC, latest.observed_at DESC NULLS LAST
    """
    params = (lng, lat, lng, lat, max_radius_m, *observed_params, max_radius_m)
    try:
        with _connect(database_url, connection_factory) as connection:
            with connection.cursor() as cursor:
                _apply_statement_timeout(cursor, statement_timeout_ms)
                cursor.execute(sql, params)
                return tuple(_nearby_coverage_row(row) for row in cursor.fetchall())
    except psycopg.errors.UndefinedTable as exc:
        if _is_missing_relation(exc, _LATEST_OFFICIAL_RELATION):
            return ()
        raise EvidenceRepositoryUnavailable(str(exc)) from exc
    except (OSError, psycopg.Error) as exc:
        raise EvidenceRepositoryUnavailable(str(exc)) from exc


def upsert_public_evidence(
    *,
    database_url: str,
    records: tuple[EvidenceUpsert, ...],
    connection_factory: ConnectionFactory | None = None,
) -> tuple[EvidenceRecord, ...]:
    if not records:
        return ()

    sql = """
        INSERT INTO evidence (
            id,
            data_source_id,
            source_id,
            source_type,
            event_type,
            title,
            summary,
            url,
            occurred_at,
            observed_at,
            ingested_at,
            geom,
            distance_to_query_m,
            confidence,
            freshness_score,
            source_weight,
            privacy_level,
            raw_ref,
            ingestion_status,
            properties
        )
        VALUES (
            %s::uuid,
            (SELECT id FROM data_sources WHERE adapter_key = %s),
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            ST_SetSRID(ST_MakePoint(%s, %s), 4326),
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            'accepted',
            %s::jsonb
        )
        ON CONFLICT ON CONSTRAINT evidence_source_raw_ref_unique
        DO UPDATE SET
            title = EXCLUDED.title,
            summary = EXCLUDED.summary,
            url = EXCLUDED.url,
            occurred_at = COALESCE(EXCLUDED.occurred_at, evidence.occurred_at),
            observed_at = COALESCE(EXCLUDED.observed_at, evidence.observed_at),
            ingested_at = EXCLUDED.ingested_at,
            geom = EXCLUDED.geom,
            distance_to_query_m = EXCLUDED.distance_to_query_m,
            confidence = GREATEST(evidence.confidence, EXCLUDED.confidence),
            freshness_score = GREATEST(
                COALESCE(evidence.freshness_score, 0),
                COALESCE(EXCLUDED.freshness_score, 0)
            ),
            source_weight = GREATEST(
                COALESCE(evidence.source_weight, 0),
                COALESCE(EXCLUDED.source_weight, 0)
            ),
            privacy_level = EXCLUDED.privacy_level,
            ingestion_status = 'accepted',
            properties = evidence.properties || EXCLUDED.properties,
            updated_at = now()
        RETURNING
            id::text AS id,
            source_id,
            source_type,
            event_type,
            title,
            summary,
            url,
            occurred_at,
            observed_at,
            ingested_at,
            ST_Y(ST_PointOnSurface(geom::geometry)) AS lat,
            ST_X(ST_PointOnSurface(geom::geometry)) AS lng,
            ST_AsGeoJSON(ST_PointOnSurface(geom::geometry)) AS geometry,
            distance_to_query_m,
            confidence,
            COALESCE(freshness_score, 0.8) AS freshness_score,
            COALESCE(source_weight, CASE WHEN source_type = 'official' THEN 1.0 ELSE 0.85 END)
                AS source_weight,
            privacy_level,
            raw_ref
    """
    try:
        inserted: list[EvidenceRecord] = []
        with _connect(database_url, connection_factory) as connection:
            with connection.cursor() as cursor:
                for record in records:
                    cursor.execute(sql, _upsert_params(record))
                    row = cursor.fetchone()
                    if row is not None:
                        inserted.append(_record_from_row(row))
        return tuple(inserted)
    except (OSError, psycopg.Error) as exc:
        raise EvidenceRepositoryUnavailable(str(exc)) from exc


def fetch_query_heat_snapshot(
    *,
    database_url: str,
    lat: float,
    lng: float,
    radius_m: int,
    period: str = "P7D",
    statement_timeout_ms: int = QUERY_HEAT_STATEMENT_TIMEOUT_MS,
    connection_factory: ConnectionFactory | None = None,
) -> QueryHeatSnapshot:
    sql = """
        WITH query_point AS (
            SELECT
                ST_SetSRID(ST_MakePoint(%s, %s), 4326) AS geom,
                ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography AS geog,
                (%s::double precision / 90000.0) AS degree_radius
        ),
        nearby_queries AS (
            SELECT lq.id, lq.privacy_bucket, lq.h3_index, lq.created_at
            FROM location_queries lq
            JOIN risk_assessments ra ON ra.query_id = lq.id
            CROSS JOIN query_point qp
            WHERE lq.geom IS NOT NULL
                AND lq.created_at >= now() - (%s::interval)
                AND lq.geom && ST_Expand(qp.geom, qp.degree_radius)
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
                if statement_timeout_ms > 0:
                    cursor.execute(
                        "SELECT set_config('statement_timeout', %s, true)",
                        (f"{statement_timeout_ms}ms",),
                    )
                cursor.execute(
                    sql,
                    (lng, lat, lng, lat, radius_m, _period_to_interval(period), radius_m),
                )
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
            ST_AsGeoJSON(ST_PointOnSurface(e.geom::geometry)) AS geometry,
            CASE
                WHEN e.geom IS NOT NULL THEN ST_Distance(e.geom::geography, lq.geom::geography)
                ELSE e.distance_to_query_m
            END AS distance_to_query_m,
            e.confidence,
            COALESCE(e.freshness_score, 0.8) AS freshness_score,
            COALESCE(e.source_weight, CASE WHEN e.source_type = 'official' THEN 1.0 ELSE 0.85 END)
                AS source_weight,
            e.privacy_level,
            e.raw_ref,
            (e.properties->>'rainfall_mm_1h')::double precision AS rainfall_mm_1h,
            (e.properties->>'water_level_m')::double precision AS water_level_m,
            (e.properties->>'warning_level_m')::double precision AS warning_level_m,
            (e.properties->>'flood_depth_cm')::double precision AS flood_depth_cm,
            NULL::double precision AS realtime_risk_factor
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


def fetch_evidence_by_ids(
    *,
    database_url: str,
    evidence_ids: tuple[str, ...],
    connection_factory: ConnectionFactory | None = None,
) -> tuple[EvidenceRecord, ...]:
    if not evidence_ids:
        return ()

    sql = """
        WITH requested AS (
            SELECT requested_id::uuid AS id, ordinality
            FROM unnest(%s::uuid[]) WITH ORDINALITY AS requested(requested_id, ordinality)
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
            CASE WHEN e.geom IS NOT NULL THEN ST_Y(ST_PointOnSurface(e.geom::geometry)) END AS lat,
            CASE WHEN e.geom IS NOT NULL THEN ST_X(ST_PointOnSurface(e.geom::geometry)) END AS lng,
            CASE WHEN e.geom IS NOT NULL THEN ST_AsGeoJSON(ST_PointOnSurface(e.geom::geometry)) END
                AS geometry,
            e.distance_to_query_m,
            e.confidence,
            COALESCE(e.freshness_score, 0.8) AS freshness_score,
            COALESCE(e.source_weight, CASE WHEN e.source_type = 'official' THEN 1.0 ELSE 0.85 END)
                AS source_weight,
            e.privacy_level,
            e.raw_ref,
            (e.properties->>'rainfall_mm_1h')::double precision AS rainfall_mm_1h,
            (e.properties->>'water_level_m')::double precision AS water_level_m,
            (e.properties->>'warning_level_m')::double precision AS warning_level_m,
            (e.properties->>'flood_depth_cm')::double precision AS flood_depth_cm,
            NULL::double precision AS realtime_risk_factor
        FROM requested
        JOIN evidence e ON e.id = requested.id
        WHERE e.ingestion_status = 'accepted'
            AND e.privacy_level IN ('public', 'aggregated')
        ORDER BY requested.ordinality ASC
    """
    return _fetch_records(
        sql,
        (list(evidence_ids),),
        database_url=database_url,
        connection_factory=connection_factory,
    )


def _fetch_records(
    sql: str,
    params: tuple[object, ...],
    *,
    database_url: str,
    statement_timeout_ms: int = 0,
    connection_factory: ConnectionFactory | None,
) -> tuple[EvidenceRecord, ...]:
    try:
        with _connect(database_url, connection_factory) as connection:
            with connection.cursor() as cursor:
                _apply_statement_timeout(cursor, statement_timeout_ms)
                cursor.execute(sql, params)
                return tuple(_record_from_row(row) for row in cursor.fetchall())
    except (OSError, psycopg.Error) as exc:
        raise EvidenceRepositoryUnavailable(str(exc)) from exc


def _connect(database_url: str, connection_factory: ConnectionFactory | None) -> Any:
    if connection_factory is not None:
        return connection_factory()
    return psycopg.connect(database_url, connect_timeout=2, row_factory=dict_row)


def _apply_statement_timeout(cursor: Any, statement_timeout_ms: int) -> None:
    if statement_timeout_ms <= 0:
        return
    cursor.execute(
        "SELECT set_config('statement_timeout', %s, true)",
        (f"{statement_timeout_ms}ms",),
    )


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
        rainfall_mm_1h=_optional_float(row.get("rainfall_mm_1h")),
        water_level_m=_optional_float(row.get("water_level_m")),
        warning_level_m=_optional_float(row.get("warning_level_m")),
        flood_depth_cm=_optional_float(row.get("flood_depth_cm")),
        realtime_risk_factor=_optional_float(row.get("realtime_risk_factor")),
    )


def _nearby_coverage_row(row: dict[str, Any]) -> NearbyCoverageRow:
    return NearbyCoverageRow(
        adapter_key=str(row["adapter_key"]),
        source_id=str(row["source_id"]),
        event_type=str(row["event_type"]),
        station_id=str(row["station_id"]) if row.get("station_id") is not None else None,
        observed_at=row.get("observed_at"),
        ingested_at=row["ingested_at"],
        distance_to_query_m=float(row["distance_to_query_m"]),
        freshness_state=str(row["freshness_state"]),
    )


def _upsert_params(record: EvidenceUpsert) -> tuple[object, ...]:
    return (
        record.id,
        record.adapter_key,
        record.source_id,
        record.source_type,
        record.event_type,
        record.title,
        record.summary,
        record.url,
        record.occurred_at,
        record.observed_at,
        record.ingested_at,
        record.lng,
        record.lat,
        record.distance_to_query_m,
        record.confidence,
        record.freshness_score,
        record.source_weight,
        record.privacy_level,
        record.raw_ref,
        Jsonb(record.properties),
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


def _is_missing_relation(exc: psycopg.errors.UndefinedTable, relation: str) -> bool:
    diag = getattr(exc, "diag", None)
    table_name = getattr(diag, "table_name", None)
    if isinstance(table_name, str) and table_name:
        return table_name == relation
    return re.search(rf'relation "{re.escape(relation)}"', str(exc)) is not None


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


def _max_storage_risk_level(*levels: str) -> str:
    rank = {"unknown": 0, "low": 1, "medium": 2, "high": 3, "severe": 4}
    storage_levels = [_storage_risk_level(level) for level in levels]
    return max(storage_levels, key=lambda level: rank[level], default="unknown")
