from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import json
import re
from typing import Any, Literal, cast

import psycopg

from app.core.db import pooled_connection
from psycopg.types.json import Jsonb


ConnectionFactory = Callable[[], Any]
RealtimeJurisdictionResolutionStatus = Literal[
    "verified",
    "boundary_unverified",
    "outside_coverage",
    "ambiguous",
    "unavailable",
]
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
class RealtimeSourceHealthRow:
    adapter_key: str
    name: str
    is_enabled: bool
    configured_health_status: str
    last_success_at: datetime | None
    last_failure_at: datetime | None
    latest_run_status: str | None
    latest_run_at: datetime | None
    latest_observed_at: datetime | None
    latest_ingested_at: datetime | None
    station_count: int | None
    inventory_complete: bool = False
    is_registered: bool = True
    runtime_enabled: bool | None = None
    runtime_enabled_checked_at: datetime | None = None
    runtime_pipeline_status: str | None = None
    runtime_pipeline_checked_at: datetime | None = None
    runtime_pipeline_run_at: datetime | None = None
    runtime_pipeline_complete: bool = False
    fresh_station_count: int | None = None
    delayed_station_count: int | None = None
    stale_station_count: int | None = None
    upstream_station_count: int | None = None
    pages_fetched: int | None = None
    pagination_complete: bool | None = None
    inventory_manifest_sha256: str | None = None
    inventory_proof_status: str = "missing"


@dataclass(frozen=True)
class RealtimeJurisdictionSourceMapping:
    adapter_key: str
    signal_type: str
    coverage_scope: str
    jurisdiction_code: str
    jurisdiction_name: str | None
    requirement_role: str
    mapping_revision: str
    redundancy_of_adapter_key: str | None = None


@dataclass(frozen=True)
class RealtimeJurisdictionSignalContract:
    jurisdiction_code: str
    jurisdiction_name: str
    signal_type: str
    catalog_status: str
    mapping_revision: str
    mapping_proof_valid: bool = False


@dataclass(frozen=True)
class RealtimeJurisdictionContext:
    resolution_status: RealtimeJurisdictionResolutionStatus
    home_jurisdiction_code: str | None
    home_jurisdiction_name: str | None
    considered_jurisdictions: tuple[tuple[str, str], ...]
    signal_contracts: tuple[RealtimeJurisdictionSignalContract, ...]
    source_mappings: tuple[RealtimeJurisdictionSourceMapping, ...]

    @property
    def adapter_keys(self) -> tuple[str, ...]:
        return tuple(sorted({mapping.adapter_key for mapping in self.source_mappings}))

    @property
    def mapping_revisions(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    *(contract.mapping_revision for contract in self.signal_contracts),
                    *(mapping.mapping_revision for mapping in self.source_mappings),
                }
            )
        )


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
    # ADR-0006: never store raw query text or precise user-selected
    # coordinates. raw_input stays NULL and coordinates are coarsened to the
    # same ~1 km bucket used for query heat before they touch the database.
    privacy_bucket = _privacy_bucket(assessment.lat, assessment.lng)
    coarse_lat = _privacy_coordinate(assessment.lat)
    coarse_lng = _privacy_coordinate(assessment.lng)
    params = (
        None,
        coarse_lat,
        coarse_lng,
        coarse_lng,
        coarse_lat,
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
    radius_buckets_m: tuple[int, ...] = (500, 1000, 3000, 5000, 10000, 15000),
    observed_since: datetime | None = None,
    statement_timeout_ms: int = 1500,
    connection_factory: ConnectionFactory | None = None,
) -> tuple[NearbyCoverageRow, ...]:
    latest_rows = _query_nearby_latest_coverage_rows(
        database_url=database_url,
        lat=lat,
        lng=lng,
        radius_buckets_m=radius_buckets_m,
        # official_realtime_latest already contains one bounded row per station.
        # Keep old station rows here so the caller can distinguish "stale" from
        # "no station"; the evidence-table fallback remains lookback-bounded.
        observed_since=None,
        statement_timeout_ms=statement_timeout_ms,
        connection_factory=connection_factory,
    )
    try:
        evidence_rows = _query_nearby_evidence_coverage_rows(
            database_url=database_url,
            lat=lat,
            lng=lng,
            radius_buckets_m=radius_buckets_m,
            observed_since=observed_since,
            statement_timeout_ms=statement_timeout_ms,
            connection_factory=connection_factory,
        )
    except EvidenceRepositoryUnavailable:
        if latest_rows:
            return latest_rows
        raise
    return _merge_nearby_coverage_rows(latest_rows, evidence_rows)


def query_realtime_source_health_rows(
    *,
    database_url: str,
    adapter_keys: tuple[str, ...],
    statement_timeout_ms: int = 1500,
    connection_factory: ConnectionFactory | None = None,
) -> tuple[RealtimeSourceHealthRow, ...]:
    """Return public-safe runtime and observation health for selected adapters.

    ``ingestion_jobs`` is authoritative for the latest attempted run because a
    skipped attempt deliberately has no ``adapter_runs`` row.  The adapter run
    joined below is restricted to that exact job and is only used to retain the
    more precise ``partial`` status.
    """

    if not adapter_keys:
        return ()

    try:
        return _query_realtime_source_health_rows(
            database_url=database_url,
            adapter_keys=adapter_keys,
            include_latest_observations=True,
            statement_timeout_ms=statement_timeout_ms,
            connection_factory=connection_factory,
        )
    except psycopg.errors.UndefinedTable as exc:
        if not _is_missing_relation(exc, _LATEST_OFFICIAL_RELATION):
            raise EvidenceRepositoryUnavailable(str(exc)) from exc
    except (OSError, psycopg.Error) as exc:
        raise EvidenceRepositoryUnavailable(str(exc)) from exc

    try:
        return _query_realtime_source_health_rows(
            database_url=database_url,
            adapter_keys=adapter_keys,
            include_latest_observations=False,
            statement_timeout_ms=statement_timeout_ms,
            connection_factory=connection_factory,
        )
    except (OSError, psycopg.Error) as exc:
        raise EvidenceRepositoryUnavailable(str(exc)) from exc


def query_realtime_jurisdiction_context(
    *,
    database_url: str,
    lat: float,
    lng: float,
    search_radius_m: int = 15_000,
    statement_timeout_ms: int = 1500,
    connection_factory: ConnectionFactory | None = None,
) -> RealtimeJurisdictionContext:
    """Resolve the audited county/source contract for a spatial absence query.

    Client administrative hints and the precomputed profile centroids are not
    authoritative.  This query accepts exactly one active, reviewed 22-county
    MultiPolygon snapshot, requires a unique home county, and includes every
    county whose boundary lies within the full station-search radius.
    """

    sql = """
        WITH query_point AS (
            SELECT ST_SetSRID(ST_MakePoint(%s, %s), 4326) AS geom
        ),
        active_snapshot_candidates AS (
            SELECT snapshot.id
            FROM realtime_jurisdiction_boundary_snapshots snapshot
            WHERE snapshot.is_active
                AND snapshot.is_complete
                AND snapshot.expected_count = 22
                AND snapshot.imported_count = snapshot.expected_count
                AND snapshot.reviewed_at IS NOT NULL
                AND snapshot.review_ref IS NOT NULL
                AND snapshot.manifest_sha256 IS NOT NULL
                AND snapshot.manifest_sha256 = snapshot.approved_manifest_sha256
                AND (
                    SELECT count(*)
                    FROM realtime_jurisdiction_boundaries boundary_count
                    WHERE boundary_count.snapshot_id = snapshot.id
                ) = snapshot.expected_count
                AND NOT EXISTS (
                    SELECT 1
                    FROM realtime_jurisdiction_boundaries boundary_integrity
                    WHERE boundary_integrity.snapshot_id = snapshot.id
                        AND (
                            ST_IsEmpty(boundary_integrity.geom)
                            OR NOT ST_IsValid(boundary_integrity.geom)
                            OR boundary_integrity.geom_sha256
                                <> encode(
                                    digest(
                                        ST_AsEWKB(boundary_integrity.geom),
                                        'sha256'
                                    ),
                                    'hex'
                                )
                        )
                )
                AND snapshot.manifest_sha256 = (
                    SELECT encode(
                        digest(
                            convert_to(
                                COALESCE(
                                    jsonb_agg(
                                        jsonb_build_array(
                                            boundary_manifest.jurisdiction_code,
                                            boundary_manifest.geom_sha256
                                        )
                                        ORDER BY boundary_manifest.jurisdiction_code
                                    ),
                                    '[]'::jsonb
                                )::text,
                                'UTF8'
                            ),
                            'sha256'
                        ),
                        'hex'
                    )
                    FROM realtime_jurisdiction_boundaries boundary_manifest
                    WHERE boundary_manifest.snapshot_id = snapshot.id
                )
        ),
        active_snapshot AS (
            SELECT candidate.id
            FROM active_snapshot_candidates candidate
            WHERE (
                SELECT count(*) FROM active_snapshot_candidates
            ) = 1
        ),
        home_matches AS (
            SELECT
                boundary.jurisdiction_code,
                jurisdiction.jurisdiction_name
            FROM active_snapshot snapshot
            JOIN realtime_jurisdiction_boundaries boundary
                ON boundary.snapshot_id = snapshot.id
            JOIN realtime_jurisdictions jurisdiction
                ON jurisdiction.jurisdiction_code = boundary.jurisdiction_code
            CROSS JOIN query_point
            WHERE ST_Covers(boundary.geom, query_point.geom)
        ),
        home AS (
            SELECT
                min(jurisdiction_code) AS jurisdiction_code,
                min(jurisdiction_name) AS jurisdiction_name
            FROM home_matches
            HAVING count(*) = 1
        ),
        considered AS (
            SELECT
                boundary.jurisdiction_code,
                jurisdiction.jurisdiction_name
            FROM active_snapshot snapshot
            JOIN home ON true
            JOIN realtime_jurisdiction_boundaries boundary
                ON boundary.snapshot_id = snapshot.id
            JOIN realtime_jurisdictions jurisdiction
                ON jurisdiction.jurisdiction_code = boundary.jurisdiction_code
            CROSS JOIN query_point
            WHERE ST_DWithin(
                boundary.geom::geography,
                query_point.geom::geography,
                %s
            )
        ),
        contract_mapping_rows AS (
            SELECT
                considered.jurisdiction_code,
                considered.jurisdiction_name,
                contract.signal_type,
                contract.catalog_status,
                contract.mapping_revision AS contract_mapping_revision,
                contract.mapping_manifest_version,
                contract.approved_mapping_count,
                contract.approved_mapping_manifest_sha256,
                contract.reviewed_at,
                contract.review_ref,
                mapping.adapter_key,
                mapping.coverage_scope,
                mapping.jurisdiction_code AS mapping_jurisdiction_code,
                mapping.requirement_role,
                mapping.redundancy_of_adapter_key,
                mapping.mapping_revision,
                CASE
                    WHEN mapping.adapter_key IS NULL THEN false
                    WHEN mapping.requirement_role <> 'redundant_subset' THEN true
                    ELSE EXISTS (
                        SELECT 1
                        FROM realtime_source_jurisdictions parent_mapping
                        WHERE parent_mapping.adapter_key
                                = mapping.redundancy_of_adapter_key
                            AND parent_mapping.signal_type = mapping.signal_type
                            AND parent_mapping.requirement_role = 'required'
                            AND (
                                parent_mapping.coverage_scope = 'national'
                                OR parent_mapping.jurisdiction_code
                                    = contract.jurisdiction_code
                            )
                    )
                END AS redundancy_parent_valid
            FROM considered
            JOIN realtime_jurisdiction_signal_contracts contract
                ON contract.jurisdiction_code = considered.jurisdiction_code
            LEFT JOIN realtime_source_jurisdictions mapping
                ON mapping.signal_type = contract.signal_type
                AND (
                    mapping.coverage_scope = 'national'
                    OR mapping.jurisdiction_code = contract.jurisdiction_code
                )
        ),
        contract_mapping_manifests AS (
            SELECT
                jurisdiction_code,
                jurisdiction_name,
                signal_type,
                catalog_status,
                contract_mapping_revision,
                mapping_manifest_version,
                approved_mapping_count,
                approved_mapping_manifest_sha256,
                reviewed_at,
                review_ref,
                count(adapter_key)::integer AS actual_mapping_count,
                COALESCE(
                    jsonb_agg(
                        jsonb_build_array(
                            adapter_key,
                            signal_type,
                            coverage_scope,
                            mapping_jurisdiction_code,
                            requirement_role,
                            redundancy_of_adapter_key,
                            mapping_revision
                        )
                        ORDER BY
                            adapter_key,
                            coverage_scope,
                            mapping_jurisdiction_code,
                            requirement_role,
                            redundancy_of_adapter_key,
                            mapping_revision
                    ) FILTER (WHERE adapter_key IS NOT NULL),
                    '[]'::jsonb
                ) AS mapping_manifest,
                COALESCE(
                    bool_and(mapping_revision = contract_mapping_revision)
                        FILTER (WHERE adapter_key IS NOT NULL),
                    false
                ) AS mapping_revision_consistent,
                COALESCE(
                    bool_and(redundancy_parent_valid)
                        FILTER (WHERE adapter_key IS NOT NULL),
                    false
                ) AS redundancy_valid
            FROM contract_mapping_rows
            GROUP BY
                jurisdiction_code,
                jurisdiction_name,
                signal_type,
                catalog_status,
                contract_mapping_revision,
                mapping_manifest_version,
                approved_mapping_count,
                approved_mapping_manifest_sha256,
                reviewed_at,
                review_ref
        ),
        contract_mapping_digests AS (
            SELECT
                manifest.*,
                encode(
                    digest(
                        convert_to(manifest.mapping_manifest::text, 'UTF8'),
                        'sha256'
                    ),
                    'hex'
                ) AS actual_mapping_manifest_sha256
            FROM contract_mapping_manifests manifest
        ),
        contract_mapping_proofs AS (
            SELECT
                digest.*,
                (
                    digest.catalog_status = 'reviewed_complete'
                    AND digest.mapping_manifest_version
                        = 'jurisdiction-source-jsonb-v1'
                    AND digest.reviewed_at IS NOT NULL
                    AND digest.review_ref IS NOT NULL
                    AND digest.actual_mapping_count > 0
                    AND digest.actual_mapping_count
                        = digest.approved_mapping_count
                    AND digest.actual_mapping_manifest_sha256
                        = digest.approved_mapping_manifest_sha256
                    AND digest.mapping_revision_consistent
                    AND digest.redundancy_valid
                ) AS mapping_proof_valid
            FROM contract_mapping_digests digest
        ),
        resolution AS (
            SELECT
                CASE
                    WHEN (SELECT count(*) FROM active_snapshot_candidates) <> 1
                        THEN 'boundary_unverified'
                    WHEN (SELECT count(*) FROM home_matches) = 0
                        THEN 'outside_coverage'
                    WHEN (SELECT count(*) FROM home_matches) > 1
                        THEN 'ambiguous'
                    ELSE 'verified'
                END AS resolution_status,
                (SELECT jurisdiction_code FROM home) AS home_jurisdiction_code,
                (SELECT jurisdiction_name FROM home) AS home_jurisdiction_name
        )
        SELECT
            resolution.resolution_status,
            resolution.home_jurisdiction_code,
            resolution.home_jurisdiction_name,
            CASE WHEN resolution.resolution_status = 'verified' THEN COALESCE((
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'jurisdiction_code', considered.jurisdiction_code,
                        'jurisdiction_name', considered.jurisdiction_name
                    )
                    ORDER BY considered.jurisdiction_code
                )
                FROM considered
            ), '[]'::jsonb) ELSE '[]'::jsonb END AS considered_jurisdictions,
            CASE WHEN resolution.resolution_status = 'verified' THEN COALESCE((
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'jurisdiction_code', contract.jurisdiction_code,
                        'jurisdiction_name', contract.jurisdiction_name,
                        'signal_type', contract.signal_type,
                        'catalog_status', contract.catalog_status,
                        'mapping_revision', contract.contract_mapping_revision,
                        'mapping_proof_valid', contract.mapping_proof_valid
                    )
                    ORDER BY contract.jurisdiction_code, contract.signal_type
                )
                FROM contract_mapping_proofs contract
            ), '[]'::jsonb) ELSE '[]'::jsonb END AS signal_contracts,
            CASE WHEN resolution.resolution_status = 'verified' THEN COALESCE((
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'adapter_key', mapping.adapter_key,
                        'signal_type', mapping.signal_type,
                        'coverage_scope', mapping.coverage_scope,
                        'jurisdiction_code', mapping.jurisdiction_code,
                        'jurisdiction_name', jurisdiction.jurisdiction_name,
                        'requirement_role', mapping.requirement_role,
                        'mapping_revision', mapping.mapping_revision,
                        'redundancy_of_adapter_key',
                            mapping.redundancy_of_adapter_key
                    )
                    ORDER BY
                        mapping.adapter_key,
                        mapping.signal_type,
                        mapping.jurisdiction_code
                )
                FROM realtime_source_jurisdictions mapping
                LEFT JOIN realtime_jurisdictions jurisdiction
                    ON jurisdiction.jurisdiction_code = mapping.jurisdiction_code
                WHERE mapping.coverage_scope = 'national'
                    OR mapping.jurisdiction_code IN (
                        SELECT jurisdiction_code FROM considered
                    )
            ), '[]'::jsonb) ELSE '[]'::jsonb END AS source_mappings
        FROM resolution
    """
    try:
        with _connect(database_url, connection_factory) as connection:
            with connection.cursor() as cursor:
                _apply_statement_timeout(cursor, statement_timeout_ms)
                cursor.execute(sql, (lng, lat, search_radius_m))
                row = cursor.fetchone()
    except (OSError, psycopg.Error) as exc:
        raise EvidenceRepositoryUnavailable(str(exc)) from exc

    if row is None:
        return RealtimeJurisdictionContext(
            resolution_status="boundary_unverified",
            home_jurisdiction_code=None,
            home_jurisdiction_name=None,
            considered_jurisdictions=(),
            signal_contracts=(),
            source_mappings=(),
        )
    return _realtime_jurisdiction_context(row)

def _query_realtime_source_health_rows(
    *,
    database_url: str,
    adapter_keys: tuple[str, ...],
    include_latest_observations: bool,
    statement_timeout_ms: int,
    connection_factory: ConnectionFactory | None,
) -> tuple[RealtimeSourceHealthRow, ...]:
    latest_observations_cte = """
        , latest_observations AS (
            SELECT
                latest.adapter_key,
                max(latest.observed_at) AS latest_observed_at,
                max(latest.ingested_at) AS latest_ingested_at,
                count(DISTINCT latest.station_id)::integer AS station_count,
                count(DISTINCT latest.station_id) FILTER (
                    WHERE latest.observed_at >= now() - interval '10 minutes'
                )::integer AS fresh_station_count,
                count(DISTINCT latest.station_id) FILTER (
                    WHERE latest.observed_at < now() - interval '10 minutes'
                        AND latest.observed_at >= now() - interval '1 hour'
                )::integer AS delayed_station_count,
                count(DISTINCT latest.station_id) FILTER (
                    WHERE latest.observed_at IS NULL
                        OR latest.observed_at < now() - interval '1 hour'
                )::integer AS stale_station_count
            FROM official_realtime_latest latest
            JOIN requested ON requested.adapter_key = latest.adapter_key
            GROUP BY latest.adapter_key
        )
    """
    observation_columns = """
            latest_observations.latest_observed_at,
            latest_observations.latest_ingested_at,
            COALESCE(latest_observations.station_count, 0)::integer AS station_count,
            COALESCE(latest_observations.fresh_station_count, 0)::integer
                AS fresh_station_count,
            COALESCE(latest_observations.delayed_station_count, 0)::integer
                AS delayed_station_count,
            COALESCE(latest_observations.stale_station_count, 0)::integer
                AS stale_station_count
    """
    observation_join = """
        LEFT JOIN latest_observations
            ON latest_observations.adapter_key = requested.adapter_key
    """
    inventory_complete_column = """
            CASE
                WHEN data_sources.station_inventory_reviewed
                    AND data_sources.station_inventory_min_count IS NOT NULL
                    AND data_sources.approved_station_manifest_sha256
                        = latest_inventory.manifest_sha256
                    AND data_sources.approved_station_manifest_version
                        = latest_inventory.manifest_version
                    AND data_sources.station_inventory_reviewed_at IS NOT NULL
                    AND latest_inventory.inventory_complete
                    AND latest_inventory.upstream_total IS NOT NULL
                    AND latest_inventory.pagination_complete
                    AND latest_inventory.pages_fetched > 0
                    AND latest_inventory.source_items_seen
                        = latest_inventory.upstream_total
                    AND latest_inventory.station_ids_seen
                        = latest_inventory.upstream_total
                    AND latest_inventory.missing_station_id_count = 0
                    AND latest_inventory.duplicate_station_id_count = 0
                    AND data_sources.runtime_enabled IS true
                    AND data_sources.runtime_enabled_checked_at
                        >= now() - interval '30 minutes'
                    AND data_sources.runtime_pipeline_status = 'succeeded'
                    AND data_sources.runtime_pipeline_complete
                    AND data_sources.runtime_pipeline_run_at = latest_runtime.latest_run_at
                    AND latest_runtime.latest_run_status = 'succeeded'
                    AND latest_runtime.items_fetched = latest_runtime.items_promoted
                    AND latest_runtime.items_rejected = 0
                    AND latest_runtime.items_promoted = latest_inventory.upstream_total
                    AND latest_inventory.upstream_total
                        >= data_sources.station_inventory_min_count
                    AND COALESCE(latest_observations.station_count, 0)
                        = latest_inventory.upstream_total
                    AND NOT EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements_text(
                            latest_inventory.station_ids
                        ) manifest_station(station_id)
                        WHERE NOT EXISTS (
                            SELECT 1
                            FROM official_realtime_latest manifest_latest
                            WHERE manifest_latest.adapter_key = requested.adapter_key
                                AND manifest_latest.station_id
                                    = manifest_station.station_id
                        )
                    )
                    AND NOT EXISTS (
                        SELECT 1
                        FROM official_realtime_latest extra_latest
                        WHERE extra_latest.adapter_key = requested.adapter_key
                            AND NOT (
                                latest_inventory.station_ids
                                ? extra_latest.station_id
                            )
                    )
                THEN true
                ELSE false
            END AS inventory_complete
    """
    if not include_latest_observations:
        latest_observations_cte = ""
        observation_columns = """
            data_sources.source_timestamp_max AS latest_observed_at,
            data_sources.last_success_at AS latest_ingested_at,
            NULL::integer AS station_count,
            NULL::integer AS fresh_station_count,
            NULL::integer AS delayed_station_count,
            NULL::integer AS stale_station_count
        """
        observation_join = ""
        inventory_complete_column = "false AS inventory_complete"

    sql = f"""
        WITH requested AS (
            SELECT unnest(%s::text[]) AS adapter_key
        ),
        latest_jobs AS (
            SELECT DISTINCT ON (jobs.adapter_key)
                jobs.id,
                jobs.adapter_key,
                jobs.status,
                jobs.items_fetched,
                jobs.items_promoted,
                jobs.items_rejected,
                COALESCE(jobs.started_at, jobs.created_at) AS latest_run_at
            FROM ingestion_jobs jobs
            JOIN requested ON requested.adapter_key = jobs.adapter_key
            ORDER BY
                jobs.adapter_key,
                COALESCE(jobs.started_at, jobs.created_at) DESC,
                jobs.created_at DESC,
                jobs.id DESC
        ),
        latest_runtime AS (
            SELECT
                latest_job.id AS ingestion_job_id,
                latest_job.adapter_key,
                CASE
                    WHEN latest_adapter_run.status = 'partial' THEN 'partial'
                    ELSE latest_job.status
                END AS latest_run_status,
                latest_job.latest_run_at,
                latest_job.items_fetched,
                latest_job.items_promoted,
                latest_job.items_rejected
            FROM latest_jobs latest_job
            LEFT JOIN adapter_runs latest_adapter_run
                ON latest_adapter_run.ingestion_job_id = latest_job.id
                AND latest_adapter_run.adapter_key = latest_job.adapter_key
        )
        {latest_observations_cte}
        SELECT
            requested.adapter_key,
            COALESCE(data_sources.name, requested.adapter_key) AS name,
            (data_sources.adapter_key IS NOT NULL) AS is_registered,
            COALESCE(data_sources.is_enabled, false) AS is_enabled,
            COALESCE(data_sources.health_status, 'unknown') AS configured_health_status,
            data_sources.last_success_at,
            data_sources.last_failure_at,
            data_sources.runtime_enabled,
            data_sources.runtime_enabled_checked_at,
            data_sources.runtime_pipeline_status,
            data_sources.runtime_pipeline_checked_at,
            data_sources.runtime_pipeline_run_at,
            COALESCE(data_sources.runtime_pipeline_complete, false)
                AS runtime_pipeline_complete,
            latest_runtime.latest_run_status,
            latest_runtime.latest_run_at,
            {observation_columns},
            latest_inventory.upstream_total AS upstream_station_count,
            latest_inventory.pages_fetched,
            latest_inventory.pagination_complete,
            latest_inventory.manifest_sha256 AS inventory_manifest_sha256,
            CASE
                WHEN latest_inventory.ingestion_job_id IS NULL THEN 'missing'
                WHEN NOT latest_inventory.inventory_complete THEN 'incomplete'
                WHEN NOT COALESCE(data_sources.station_inventory_reviewed, false)
                    THEN 'awaiting_review'
                WHEN data_sources.approved_station_manifest_sha256
                    IS DISTINCT FROM latest_inventory.manifest_sha256
                    OR data_sources.approved_station_manifest_version
                        IS DISTINCT FROM latest_inventory.manifest_version
                    THEN 'checksum_mismatch'
                ELSE 'approved'
            END AS inventory_proof_status,
            {inventory_complete_column}
        FROM requested
        LEFT JOIN data_sources ON data_sources.adapter_key = requested.adapter_key
        LEFT JOIN latest_runtime ON latest_runtime.adapter_key = requested.adapter_key
        LEFT JOIN station_inventory_snapshots latest_inventory
            ON latest_inventory.ingestion_job_id = latest_runtime.ingestion_job_id
            AND latest_inventory.adapter_key = requested.adapter_key
        {observation_join}
        ORDER BY requested.adapter_key ASC
    """
    with _connect(database_url, connection_factory) as connection:
        with connection.cursor() as cursor:
            _apply_statement_timeout(cursor, statement_timeout_ms)
            cursor.execute(sql, (list(adapter_keys),))
            return tuple(_realtime_source_health_row(row) for row in cursor.fetchall())


def _merge_nearby_coverage_rows(
    latest_rows: tuple[NearbyCoverageRow, ...],
    evidence_rows: tuple[NearbyCoverageRow, ...],
) -> tuple[NearbyCoverageRow, ...]:
    merged: dict[tuple[str, str, str], NearbyCoverageRow] = {}
    for row in (*latest_rows, *evidence_rows):
        identity = (row.adapter_key, row.event_type, row.station_id or row.source_id)
        current = merged.get(identity)
        if current is None or _coverage_row_recency(row) > _coverage_row_recency(current):
            merged[identity] = row
    return tuple(sorted(merged.values(), key=lambda row: row.distance_to_query_m))


def _coverage_row_recency(row: NearbyCoverageRow) -> tuple[bool, datetime, datetime]:
    return (
        row.observed_at is not None,
        row.observed_at or row.ingested_at,
        row.ingested_at,
    )


def _query_nearby_latest_coverage_rows(
    *,
    database_url: str,
    lat: float,
    lng: float,
    radius_buckets_m: tuple[int, ...],
    observed_since: datetime | None,
    statement_timeout_ms: int,
    connection_factory: ConnectionFactory | None,
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
                WHEN latest.observed_at >= now() - interval '30 minutes' THEN 'degraded'
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


def _query_nearby_evidence_coverage_rows(
    *,
    database_url: str,
    lat: float,
    lng: float,
    radius_buckets_m: tuple[int, ...],
    observed_since: datetime | None,
    statement_timeout_ms: int,
    connection_factory: ConnectionFactory | None,
) -> tuple[NearbyCoverageRow, ...]:
    max_radius_m = max(radius_buckets_m)
    observed_filter = "AND e.observed_at >= %s::timestamptz" if observed_since else ""
    observed_params: tuple[datetime, ...] = (observed_since,) if observed_since else ()
    sql = f"""
        WITH query_point AS (
            SELECT
                ST_SetSRID(ST_MakePoint(%s, %s), 4326) AS geom,
                ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography AS geog,
                (%s::double precision / 90000.0) AS degree_radius
        ),
        candidate_rows AS (
            SELECT
                COALESCE(ds.adapter_key, e.source_id) AS adapter_key,
                e.source_id,
                e.event_type,
                COALESCE(
                    NULLIF(e.properties->>'station_id', ''),
                    CASE
                        WHEN split_part(e.source_id, ':', 3) <> ''
                        THEN split_part(e.source_id, ':', 2)
                        ELSE e.source_id
                    END
                ) AS station_id,
                e.observed_at,
                e.ingested_at,
                ST_Distance(e.geom::geography, qp.geog) AS distance_to_query_m,
                CASE
                    WHEN e.observed_at IS NULL THEN 'stale'
                    WHEN e.observed_at >= now() - interval '10 minutes' THEN 'fresh'
                    WHEN e.observed_at >= now() - interval '30 minutes' THEN 'degraded'
                    ELSE 'stale'
                END AS freshness_state
            FROM evidence e
            LEFT JOIN data_sources ds ON ds.id = e.data_source_id
            CROSS JOIN query_point qp
            WHERE e.source_type = 'official'
                AND e.ingestion_status = 'accepted'
                AND e.privacy_level IN ('public', 'aggregated')
                AND e.geom IS NOT NULL
                AND e.event_type IN (
                    'rainfall',
                    'water_level'
                )
                {observed_filter}
                AND e.geom && ST_Expand(qp.geom, qp.degree_radius)
                AND ST_DWithin(e.geom::geography, qp.geog, %s)
        )
        SELECT
            adapter_key,
            source_id,
            event_type,
            station_id,
            observed_at,
            ingested_at,
            distance_to_query_m,
            freshness_state
        FROM (
            SELECT DISTINCT ON (adapter_key, event_type, station_id)
                *
            FROM candidate_rows
            ORDER BY
                adapter_key,
                event_type,
                station_id,
                observed_at DESC NULLS LAST,
                ingested_at DESC
        ) latest_evidence
        ORDER BY distance_to_query_m ASC, observed_at DESC NULLS LAST
        LIMIT 200
    """
    params = (lng, lat, lng, lat, max_radius_m, *observed_params, max_radius_m)
    try:
        with _connect(database_url, connection_factory) as connection:
            with connection.cursor() as cursor:
                _apply_statement_timeout(cursor, statement_timeout_ms)
                cursor.execute(sql, params)
                return tuple(_nearby_coverage_row(row) for row in cursor.fetchall())
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
    return pooled_connection(database_url)


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
    source_id = str(row["source_id"])
    return NearbyCoverageRow(
        adapter_key=str(row["adapter_key"]),
        source_id=source_id,
        event_type=str(row["event_type"]),
        station_id=_normalized_station_id(
            str(row["station_id"]) if row.get("station_id") is not None else None,
            source_id,
        ),
        observed_at=row.get("observed_at"),
        ingested_at=row["ingested_at"],
        distance_to_query_m=float(row["distance_to_query_m"]),
        freshness_state=str(row["freshness_state"]),
    )


def _realtime_source_health_row(row: dict[str, Any]) -> RealtimeSourceHealthRow:
    return RealtimeSourceHealthRow(
        adapter_key=str(row["adapter_key"]),
        name=str(row["name"]),
        is_enabled=bool(row["is_enabled"]),
        configured_health_status=str(row["configured_health_status"]),
        last_success_at=row.get("last_success_at"),
        last_failure_at=row.get("last_failure_at"),
        latest_run_status=(
            str(row["latest_run_status"]) if row.get("latest_run_status") is not None else None
        ),
        latest_run_at=row.get("latest_run_at"),
        latest_observed_at=row.get("latest_observed_at"),
        latest_ingested_at=row.get("latest_ingested_at"),
        station_count=(int(row["station_count"]) if row.get("station_count") is not None else None),
        inventory_complete=bool(row.get("inventory_complete", False)),
        is_registered=bool(row.get("is_registered", True)),
        runtime_enabled=(
            bool(row["runtime_enabled"]) if row.get("runtime_enabled") is not None else None
        ),
        runtime_enabled_checked_at=row.get("runtime_enabled_checked_at"),
        runtime_pipeline_status=(
            str(row["runtime_pipeline_status"])
            if row.get("runtime_pipeline_status") is not None
            else None
        ),
        runtime_pipeline_checked_at=row.get("runtime_pipeline_checked_at"),
        runtime_pipeline_run_at=row.get("runtime_pipeline_run_at"),
        runtime_pipeline_complete=bool(row.get("runtime_pipeline_complete", False)),
        fresh_station_count=(
            int(row["fresh_station_count"])
            if row.get("fresh_station_count") is not None
            else None
        ),
        delayed_station_count=(
            int(row["delayed_station_count"])
            if row.get("delayed_station_count") is not None
            else None
        ),
        stale_station_count=(
            int(row["stale_station_count"])
            if row.get("stale_station_count") is not None
            else None
        ),
        upstream_station_count=(
            int(row["upstream_station_count"])
            if row.get("upstream_station_count") is not None
            else None
        ),
        pages_fetched=(
            int(row["pages_fetched"]) if row.get("pages_fetched") is not None else None
        ),
        pagination_complete=(
            bool(row["pagination_complete"])
            if row.get("pagination_complete") is not None
            else None
        ),
        inventory_manifest_sha256=(
            str(row["inventory_manifest_sha256"])
            if row.get("inventory_manifest_sha256") is not None
            else None
        ),
        inventory_proof_status=str(row.get("inventory_proof_status") or "missing"),
    )


def _realtime_jurisdiction_context(row: dict[str, Any]) -> RealtimeJurisdictionContext:
    raw_resolution_status = str(
        row.get("resolution_status") or "boundary_unverified"
    )
    resolution_status: RealtimeJurisdictionResolutionStatus = (
        cast(RealtimeJurisdictionResolutionStatus, raw_resolution_status)
        if raw_resolution_status
        in {
            "verified",
            "boundary_unverified",
            "outside_coverage",
            "ambiguous",
            "unavailable",
        }
        else "boundary_unverified"
    )
    considered_payload = _json_list(row.get("considered_jurisdictions"))
    contracts_payload = _json_list(row.get("signal_contracts"))
    mappings_payload = _json_list(row.get("source_mappings"))

    considered = tuple(
        (
            str(item["jurisdiction_code"]),
            str(item["jurisdiction_name"]),
        )
        for item in considered_payload
        if isinstance(item, dict)
        and item.get("jurisdiction_code") is not None
        and item.get("jurisdiction_name") is not None
    )
    contracts = tuple(
        RealtimeJurisdictionSignalContract(
            jurisdiction_code=str(item["jurisdiction_code"]),
            jurisdiction_name=str(item["jurisdiction_name"]),
            signal_type=str(item["signal_type"]),
            catalog_status=str(item["catalog_status"]),
            mapping_revision=str(item["mapping_revision"]),
            mapping_proof_valid=bool(item.get("mapping_proof_valid", False)),
        )
        for item in contracts_payload
        if isinstance(item, dict)
        and all(
            item.get(key) is not None
            for key in (
                "jurisdiction_code",
                "jurisdiction_name",
                "signal_type",
                "catalog_status",
                "mapping_revision",
            )
        )
    )
    mappings = tuple(
        RealtimeJurisdictionSourceMapping(
            adapter_key=str(item["adapter_key"]),
            signal_type=str(item["signal_type"]),
            coverage_scope=str(item["coverage_scope"]),
            jurisdiction_code=str(item["jurisdiction_code"]),
            jurisdiction_name=(
                str(item["jurisdiction_name"])
                if item.get("jurisdiction_name") is not None
                else None
            ),
            requirement_role=str(item["requirement_role"]),
            mapping_revision=str(item["mapping_revision"]),
            redundancy_of_adapter_key=(
                str(item["redundancy_of_adapter_key"])
                if item.get("redundancy_of_adapter_key") is not None
                else None
            ),
        )
        for item in mappings_payload
        if isinstance(item, dict)
        and all(
            item.get(key) is not None
            for key in (
                "adapter_key",
                "signal_type",
                "coverage_scope",
                "jurisdiction_code",
                "requirement_role",
                "mapping_revision",
            )
        )
    )
    return RealtimeJurisdictionContext(
        resolution_status=resolution_status,
        home_jurisdiction_code=(
            str(row["home_jurisdiction_code"])
            if row.get("home_jurisdiction_code") is not None
            else None
        ),
        home_jurisdiction_name=(
            str(row["home_jurisdiction_name"])
            if row.get("home_jurisdiction_name") is not None
            else None
        ),
        considered_jurisdictions=considered,
        signal_contracts=contracts,
        source_mappings=mappings,
    )


def _json_list(value: object) -> list[object]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    return list(value) if isinstance(value, list) else []


def _normalized_station_id(station_id: str | None, source_id: str) -> str | None:
    candidate = station_id or source_id
    parts = candidate.split(":", 2)
    if len(parts) == 3 and parts[1]:
        return parts[1]
    return candidate or None


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


def _privacy_coordinate(value: float) -> float:
    """Coarsen a coordinate to ~1 km so precise points never persist (ADR-0006)."""
    return round(value, 2)


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
