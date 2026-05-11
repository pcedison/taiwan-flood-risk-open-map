from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from typing import Any, Literal, cast


ConnectionFactory = Callable[[], Any]
ProfileRefreshStatus = Literal["succeeded", "failed", "skipped", "cancelled"]


class ProfileRefreshJobUnavailable(RuntimeError):
    """Raised when profile refresh jobs cannot be claimed or completed."""


@dataclass(frozen=True)
class ProfileRefreshJob:
    id: str
    profile_kind: str
    profile_key: str
    priority: int
    reason: str
    attempts: int
    max_attempts: int
    payload: dict[str, Any]
    run_after: datetime
    lease_expires_at: datetime | None


@dataclass(frozen=True)
class ProfileRebuildSummary:
    profile_kind: str
    profile_key: str
    evidence_count: int
    top_evidence_ids: tuple[str, ...]
    realtime_level: str
    historical_level: str
    confidence_level: str
    computed_at: datetime


@dataclass(frozen=True)
class ProfileSeedSummary:
    profile_kind: str
    seeded: int
    refresh_jobs_enqueued: int
    source: str


def claim_profile_refresh_jobs(
    *,
    database_url: str | None = None,
    worker_id: str,
    limit: int = 1,
    lease_seconds: int = 300,
    connection_factory: ConnectionFactory | None = None,
) -> tuple[ProfileRefreshJob, ...]:
    if database_url is None and connection_factory is None:
        raise ValueError("database_url or connection_factory is required")
    if limit < 1:
        raise ValueError("limit must be positive")
    if lease_seconds < 1:
        raise ValueError("lease_seconds must be positive")

    sql = """
        WITH candidate_jobs AS (
            SELECT id
            FROM profile_refresh_jobs
            WHERE status = 'queued'
                AND run_after <= now()
            ORDER BY
                priority DESC,
                run_after ASC,
                created_at ASC
            LIMIT %s
            FOR UPDATE SKIP LOCKED
        ),
        claimed_jobs AS (
            UPDATE profile_refresh_jobs jobs
            SET
                status = 'running',
                leased_by = %s,
                lease_expires_at = now() + (%s::text || ' seconds')::interval,
                attempts = attempts + 1,
                started_at = COALESCE(started_at, now()),
                updated_at = now()
            FROM candidate_jobs
            WHERE jobs.id = candidate_jobs.id
            RETURNING
                jobs.id::text AS id,
                jobs.profile_kind,
                jobs.profile_key,
                jobs.priority,
                jobs.reason,
                jobs.attempts,
                jobs.max_attempts,
                jobs.payload,
                jobs.run_after,
                jobs.lease_expires_at
        )
        SELECT *
        FROM claimed_jobs
        ORDER BY priority DESC, run_after ASC
    """

    try:
        with _connect(database_url, connection_factory) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, (limit, worker_id, lease_seconds))
                rows = cursor.fetchall()
            _commit(connection)
    except Exception as exc:
        raise ProfileRefreshJobUnavailable(str(exc)) from exc

    return tuple(_job_from_row(row) for row in rows)


def seed_admin_area_profiles_from_geocoder(
    *,
    database_url: str | None = None,
    source_key: str = "moi-village-boundary-twd97-geographic",
    scope: str = "village",
    profile_radius_m: int = 2000,
    limit: int | None = None,
    enqueue_refresh: bool = True,
    connection_factory: ConnectionFactory | None = None,
) -> ProfileSeedSummary:
    if database_url is None and connection_factory is None:
        raise ValueError("database_url or connection_factory is required")
    if scope not in {"county", "town", "village"}:
        raise ValueError("scope must be county, town, or village")
    if profile_radius_m < 1:
        raise ValueError("profile_radius_m must be positive")
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")

    sql = """
        WITH source_rows AS (
            SELECT
                source_key,
                source_record_id,
                name,
                admin_code,
                metadata,
                geom,
                centroid
            FROM geocoder_open_data_entries
            WHERE source_key = %s
                AND precision = 'admin_area'
                AND place_type = 'admin_area'
                AND centroid IS NOT NULL
            ORDER BY source_record_id NULLS LAST, name
            LIMIT COALESCE(%s::integer, 2147483647)
        ),
        normalized_profiles AS (
            SELECT
                %s || ':' || COALESCE(NULLIF(admin_code, ''), NULLIF(source_record_id, ''), md5(name))
                    AS area_key,
                %s AS scope,
                COALESCE(
                    NULLIF(metadata #>> '{raw,COUNTYNAME}', ''),
                    NULLIF(metadata #>> '{raw,county}', ''),
                    substring(name from '^(.+?[縣市])'),
                    'unknown'
                ) AS county_name,
                NULLIF(
                    COALESCE(
                        NULLIF(metadata #>> '{raw,TOWNNAME}', ''),
                        NULLIF(metadata #>> '{raw,town}', ''),
                        substring(name from '^[^縣市]+[縣市](.+?[鄉鎮市區])')
                    ),
                    ''
                ) AS town_name,
                NULLIF(
                    COALESCE(
                        NULLIF(metadata #>> '{raw,VILLNAME}', ''),
                        NULLIF(metadata #>> '{raw,village}', ''),
                        substring(name from '([^鄉鎮市區]+[里村])$')
                    ),
                    ''
                ) AS village_name,
                CASE
                    WHEN GeometryType(geom) IN ('POINT', 'MULTIPOINT')
                        THEN ST_Buffer(centroid::geography, %s)::geometry
                    ELSE geom
                END AS geom,
                centroid,
                %s AS profile_radius_m
            FROM source_rows
        ),
        upserted AS (
            INSERT INTO admin_area_profiles (
                area_key,
                scope,
                county_name,
                town_name,
                village_name,
                geom,
                centroid,
                profile_radius_m,
                score_version,
                status,
                computed_at,
                updated_at
            )
            SELECT
                area_key,
                scope,
                county_name,
                town_name,
                village_name,
                geom,
                centroid,
                profile_radius_m,
                'risk-v0.1.0',
                'stale',
                now(),
                now()
            FROM normalized_profiles
            ON CONFLICT (area_key)
            DO UPDATE SET
                scope = EXCLUDED.scope,
                county_name = EXCLUDED.county_name,
                town_name = EXCLUDED.town_name,
                village_name = EXCLUDED.village_name,
                geom = EXCLUDED.geom,
                centroid = EXCLUDED.centroid,
                profile_radius_m = EXCLUDED.profile_radius_m,
                updated_at = now()
            RETURNING area_key
        ),
        enqueued AS (
            INSERT INTO profile_refresh_jobs (
                profile_kind,
                profile_key,
                priority,
                reason,
                payload,
                created_at,
                updated_at
            )
            SELECT
                'admin_area',
                area_key,
                20,
                'profile_seed',
                jsonb_build_object(
                    'source', 'geocoder_open_data_entries',
                    'source_key', %s::text,
                    'scope', %s::text
                ),
                now(),
                now()
            FROM upserted
            WHERE %s
            ON CONFLICT DO NOTHING
            RETURNING id
        )
        SELECT
            (SELECT count(*)::integer FROM upserted) AS seeded,
            (SELECT count(*)::integer FROM enqueued) AS refresh_jobs_enqueued
    """

    try:
        with _connect(database_url, connection_factory) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql,
                    (
                        source_key,
                        limit,
                        scope,
                        scope,
                        profile_radius_m,
                        profile_radius_m,
                        source_key,
                        scope,
                        enqueue_refresh,
                    ),
                )
                row = cursor.fetchone()
            _commit(connection)
    except Exception as exc:
        raise ProfileRefreshJobUnavailable(str(exc)) from exc

    return ProfileSeedSummary(
        profile_kind="admin_area",
        seeded=int(row["seeded"]) if row is not None else 0,
        refresh_jobs_enqueued=int(row["refresh_jobs_enqueued"]) if row is not None else 0,
        source=source_key,
    )


def seed_grid_profiles_from_query_heat(
    *,
    database_url: str | None = None,
    grid_system: str = "h3",
    grid_resolution: str = "8",
    profile_radius_m: int = 1000,
    limit: int | None = None,
    include_privacy_bucket_fallback: bool = False,
    enqueue_refresh: bool = True,
    connection_factory: ConnectionFactory | None = None,
) -> ProfileSeedSummary:
    if database_url is None and connection_factory is None:
        raise ValueError("database_url or connection_factory is required")
    if grid_system not in {"h3", "geohash"}:
        raise ValueError("grid_system must be h3 or geohash")
    if profile_radius_m < 1:
        raise ValueError("profile_radius_m must be positive")
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")

    sql = """
        WITH source_cells AS (
            SELECT
                COALESCE(
                    NULLIF(lq.h3_index, ''),
                    CASE WHEN %s THEN NULLIF(lq.privacy_bucket, '') END
                ) AS raw_grid_key,
                COUNT(*)::integer AS query_count,
                MAX(lq.created_at) AS latest_query_at,
                ST_Centroid(ST_Collect(lq.geom)) AS centroid
            FROM location_queries lq
            WHERE lq.geom IS NOT NULL
                AND COALESCE(
                    NULLIF(lq.h3_index, ''),
                    CASE WHEN %s THEN NULLIF(lq.privacy_bucket, '') END
                ) IS NOT NULL
            GROUP BY COALESCE(
                NULLIF(lq.h3_index, ''),
                CASE WHEN %s THEN NULLIF(lq.privacy_bucket, '') END
            )
            ORDER BY MAX(lq.created_at) DESC, COUNT(*) DESC
            LIMIT COALESCE(%s::integer, 2147483647)
        ),
        normalized_profiles AS (
            SELECT
                CASE
                    WHEN raw_grid_key LIKE 'h3:%%' OR raw_grid_key LIKE 'geohash:%%'
                        THEN raw_grid_key
                    ELSE %s::text || ':' || raw_grid_key
                END AS grid_key,
                centroid,
                ST_Buffer(centroid::geography, %s)::geometry AS geom,
                query_count,
                latest_query_at
            FROM source_cells
        ),
        upserted AS (
            INSERT INTO risk_grid_profiles (
                grid_key,
                grid_system,
                grid_resolution,
                geom,
                centroid,
                profile_radius_m,
                score_version,
                status,
                coverage_gaps,
                computed_at,
                updated_at
            )
            SELECT
                grid_key,
                %s::text,
                %s::text,
                geom,
                centroid,
                %s,
                'risk-v0.1.0',
                'stale',
                jsonb_build_array('grid_geometry_approximated_from_query_heat'),
                now(),
                now()
            FROM normalized_profiles
            ON CONFLICT (grid_key)
            DO UPDATE SET
                grid_system = EXCLUDED.grid_system,
                grid_resolution = EXCLUDED.grid_resolution,
                geom = EXCLUDED.geom,
                centroid = EXCLUDED.centroid,
                profile_radius_m = EXCLUDED.profile_radius_m,
                coverage_gaps = EXCLUDED.coverage_gaps,
                updated_at = now()
            RETURNING grid_key
        ),
        enqueued AS (
            INSERT INTO profile_refresh_jobs (
                profile_kind,
                profile_key,
                priority,
                reason,
                payload,
                created_at,
                updated_at
            )
            SELECT
                'risk_grid',
                grid_key,
                30,
                'query_heat_priority',
                jsonb_build_object(
                    'source', 'location_queries',
                    'grid_system', %s::text,
                    'grid_resolution', %s::text
                ),
                now(),
                now()
            FROM upserted
            WHERE %s
            ON CONFLICT DO NOTHING
            RETURNING id
        )
        SELECT
            (SELECT count(*)::integer FROM upserted) AS seeded,
            (SELECT count(*)::integer FROM enqueued) AS refresh_jobs_enqueued
    """

    try:
        with _connect(database_url, connection_factory) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql,
                    (
                        include_privacy_bucket_fallback,
                        include_privacy_bucket_fallback,
                        include_privacy_bucket_fallback,
                        limit,
                        grid_system,
                        profile_radius_m,
                        grid_system,
                        grid_resolution,
                        profile_radius_m,
                        grid_system,
                        grid_resolution,
                        enqueue_refresh,
                    ),
                )
                row = cursor.fetchone()
            _commit(connection)
    except Exception as exc:
        raise ProfileRefreshJobUnavailable(str(exc)) from exc

    return ProfileSeedSummary(
        profile_kind="risk_grid",
        seeded=int(row["seeded"]) if row is not None else 0,
        refresh_jobs_enqueued=int(row["refresh_jobs_enqueued"]) if row is not None else 0,
        source="location_queries",
    )


def complete_profile_refresh_job(
    *,
    database_url: str | None = None,
    job_id: str,
    status: ProfileRefreshStatus,
    error_message: str | None = None,
    connection_factory: ConnectionFactory | None = None,
) -> bool:
    if database_url is None and connection_factory is None:
        raise ValueError("database_url or connection_factory is required")
    if status == "failed" and not error_message:
        raise ValueError("failed profile refresh jobs require error_message")

    sql = """
        UPDATE profile_refresh_jobs
        SET
            status = %s,
            finished_at = now(),
            lease_expires_at = NULL,
            last_error = %s,
            updated_at = now()
        WHERE id = %s::uuid
            AND status = 'running'
        RETURNING id::text AS id
    """

    try:
        with _connect(database_url, connection_factory) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, (status, error_message, job_id))
                row = cursor.fetchone()
            _commit(connection)
    except Exception as exc:
        raise ProfileRefreshJobUnavailable(str(exc)) from exc

    return row is not None


def rebuild_risk_profile(
    *,
    database_url: str | None = None,
    profile_kind: str,
    profile_key: str,
    now: datetime | None = None,
    connection_factory: ConnectionFactory | None = None,
) -> ProfileRebuildSummary | None:
    if database_url is None and connection_factory is None:
        raise ValueError("database_url or connection_factory is required")
    if profile_kind not in {"admin_area", "risk_grid"}:
        raise ValueError("profile_kind must be 'admin_area' or 'risk_grid'")

    profile_table = "admin_area_profiles" if profile_kind == "admin_area" else "risk_grid_profiles"
    key_column = "area_key" if profile_kind == "admin_area" else "grid_key"
    resolved_now = now or datetime.now(UTC)
    sql = f"""
        WITH target_profile AS (
            SELECT
                id,
                {key_column} AS profile_key,
                geom,
                COALESCE(centroid, ST_PointOnSurface(geom)) AS center_geom,
                profile_radius_m
            FROM {profile_table}
            WHERE {key_column} = %s
            FOR UPDATE
        ),
        profile_evidence AS (
            SELECT
                e.id,
                e.source_type,
                e.event_type,
                e.confidence,
                COALESCE(
                    e.freshness_score,
                    CASE WHEN e.source_type = 'official' THEN 0.8 ELSE 0.7 END
                ) AS freshness_score,
                COALESCE(
                    e.source_weight,
                    CASE WHEN e.source_type = 'official' THEN 1.0 ELSE 0.85 END
                ) AS source_weight,
                e.observed_at,
                e.occurred_at,
                e.ingested_at,
                e.created_at,
                ST_Distance(e.geom::geography, tp.center_geom::geography) AS distance_to_profile_m
            FROM evidence e
            JOIN target_profile tp ON true
            WHERE e.ingestion_status = 'accepted'
                AND e.privacy_level IN ('public', 'aggregated')
                AND e.geom IS NOT NULL
                AND (
                    ST_Intersects(e.geom, tp.geom)
                    OR ST_DWithin(e.geom::geography, tp.center_geom::geography, tp.profile_radius_m)
                )
        ),
        evidence_counts AS (
            SELECT COALESCE(
                jsonb_object_agg(count_key, count_value),
                '{{}}'::jsonb
            ) AS counts
            FROM (
                SELECT source_type || ':' || event_type AS count_key, COUNT(*)::integer AS count_value
                FROM profile_evidence
                GROUP BY source_type, event_type
            ) grouped_counts
        ),
        top_evidence AS (
            SELECT COALESCE(array_agg(id ORDER BY sort_rank, occurred_at DESC NULLS LAST, created_at DESC), ARRAY[]::uuid[]) AS ids
            FROM (
                SELECT
                    id,
                    occurred_at,
                    created_at,
                    CASE
                        WHEN event_type IN ('flood_report', 'road_closure') THEN 0
                        WHEN event_type = 'flood_potential' THEN 1
                        ELSE 2
                    END AS sort_rank
                FROM profile_evidence
                ORDER BY sort_rank, occurred_at DESC NULLS LAST, created_at DESC
                LIMIT 5
            ) ranked_evidence
        ),
        event_scores AS (
            SELECT
                event_type,
                SUM(
                    CASE event_type
                        WHEN 'rainfall' THEN 40.0
                        WHEN 'water_level' THEN 35.0
                        WHEN 'flood_warning' THEN 50.0
                        WHEN 'flood_report' THEN 35.0
                        WHEN 'road_closure' THEN 15.0
                        WHEN 'flood_potential' THEN 40.0
                        ELSE 0.0
                    END
                    * LEAST(GREATEST(confidence, 0.0), 1.0)
                    * LEAST(GREATEST(freshness_score, 0.0), 1.0)
                    * GREATEST(source_weight, 0.0)
                    * CASE
                        WHEN distance_to_profile_m <= 100 THEN 1.0
                        WHEN distance_to_profile_m <= 500 THEN 0.75
                        ELSE 0.5
                    END
                ) AS score
            FROM profile_evidence
            GROUP BY event_type
        ),
        scored AS (
            SELECT
                COUNT(pe.id)::integer AS evidence_count,
                LEAST(
                    COALESCE(SUM(
                        CASE
                            WHEN es.event_type IN ('rainfall', 'water_level', 'flood_warning')
                                THEN es.score
                            WHEN es.event_type IN ('flood_report', 'road_closure')
                                AND EXISTS (
                                    SELECT 1
                                    FROM profile_evidence recent
                                    WHERE recent.event_type = es.event_type
                                        AND COALESCE(recent.observed_at, recent.occurred_at)
                                            BETWEEN %s::timestamptz - interval '6 hours'
                                                AND %s::timestamptz + interval '5 minutes'
                                )
                                THEN es.score
                            ELSE 0.0
                        END
                    ), 0.0),
                    100.0
                ) AS realtime_score,
                LEAST(
                    COALESCE(SUM(
                        CASE
                            WHEN es.event_type = 'flood_potential' THEN LEAST(es.score, 40.0)
                            WHEN es.event_type IN ('flood_report', 'road_closure') THEN es.score
                            ELSE 0.0
                        END
                    ), 0.0),
                    100.0
                ) AS historical_score,
                CASE
                    WHEN COUNT(pe.id) = 0 THEN 0.0
                    ELSE LEAST(
                        (
                            SUM(pe.confidence * pe.source_weight)
                            / NULLIF(SUM(pe.source_weight), 0)
                        )
                        + CASE WHEN BOOL_OR(pe.source_type = 'official') THEN 0.06 ELSE 0.0 END,
                        1.0
                    )
                END AS confidence_score,
                BOOL_OR(pe.event_type IN ('rainfall', 'water_level', 'flood_warning')) AS has_realtime,
                BOOL_OR(pe.event_type IN ('flood_potential', 'flood_report', 'road_closure')) AS has_historical,
                BOOL_OR(pe.event_type IN ('flood_report', 'road_closure')) AS has_observed_history,
                BOOL_OR(pe.event_type = 'rainfall') AS has_rainfall,
                BOOL_OR(pe.event_type = 'water_level') AS has_water_level,
                MAX(pe.observed_at) AS latest_observed_at,
                MAX(pe.occurred_at) AS latest_occurred_at,
                MAX(pe.ingested_at) AS latest_ingested_at
            FROM profile_evidence pe
            FULL JOIN event_scores es ON es.event_type = pe.event_type
        ),
        profile_update AS (
            UPDATE {profile_table} profile
            SET
                score_version = 'risk-v0.1.0',
                realtime_level = CASE
                    WHEN NOT COALESCE(scored.has_realtime, false) THEN 'unknown'
                    WHEN scored.realtime_score >= 85 THEN 'severe'
                    WHEN scored.realtime_score >= 55 THEN 'high'
                    WHEN scored.realtime_score >= 25 THEN 'medium'
                    ELSE 'low'
                END,
                historical_level = CASE
                    WHEN NOT COALESCE(scored.has_historical, false) THEN 'unknown'
                    WHEN scored.historical_score >= 85 THEN 'severe'
                    WHEN scored.historical_score >= 55 THEN 'high'
                    WHEN scored.historical_score >= 25 THEN 'medium'
                    ELSE 'low'
                END,
                confidence_level = CASE
                    WHEN scored.evidence_count = 0 THEN 'unknown'
                    WHEN scored.confidence_score >= 0.8 THEN 'high'
                    WHEN scored.confidence_score >= 0.5 THEN 'medium'
                    ELSE 'low'
                END,
                evidence_counts = evidence_counts.counts,
                top_evidence_ids = top_evidence.ids,
                latest_observed_at = scored.latest_observed_at,
                latest_occurred_at = scored.latest_occurred_at,
                latest_ingested_at = scored.latest_ingested_at,
                coverage_gaps = to_jsonb(array_remove(ARRAY[
                    CASE WHEN scored.evidence_count = 0 THEN 'no_accepted_evidence' END,
                    CASE
                        WHEN scored.evidence_count > 0 AND NOT COALESCE(scored.has_observed_history, false)
                            THEN 'historical_news_backfill_partial'
                    END
                ], NULL)),
                missing_sources = to_jsonb(array_remove(ARRAY[
                    CASE WHEN NOT COALESCE(scored.has_rainfall, false) THEN 'rainfall' END,
                    CASE WHEN NOT COALESCE(scored.has_water_level, false) THEN 'water_level' END
                ], NULL)),
                status = CASE
                    WHEN scored.evidence_count = 0 THEN 'missing'
                    ELSE 'healthy'
                END,
                computed_at = %s,
                expires_at = %s::timestamptz + interval '7 days',
                updated_at = now()
            FROM target_profile, scored, evidence_counts, top_evidence
            WHERE profile.id = target_profile.id
            RETURNING
                profile.{key_column} AS profile_key,
                scored.evidence_count,
                top_evidence.ids AS top_evidence_ids,
                profile.realtime_level,
                profile.historical_level,
                profile.confidence_level,
                profile.computed_at
        ),
        deleted_links AS (
            DELETE FROM profile_evidence_links links
            WHERE links.profile_kind = %s
                AND links.profile_key = %s
            RETURNING links.id
        ),
        inserted_links AS (
            INSERT INTO profile_evidence_links (
                profile_kind,
                profile_key,
                evidence_id,
                relevance_score,
                reason,
                created_at
            )
            SELECT
                %s,
                profile_update.profile_key,
                evidence_id,
                1.0,
                'profile_top_evidence',
                %s
            FROM profile_update
            CROSS JOIN LATERAL unnest(profile_update.top_evidence_ids) AS evidence_id
            ON CONFLICT (profile_kind, profile_key, evidence_id) DO NOTHING
            RETURNING id
        )
        SELECT *
        FROM profile_update
    """

    try:
        with _connect(database_url, connection_factory) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql,
                    (
                        profile_key,
                        resolved_now,
                        resolved_now,
                        resolved_now,
                        resolved_now,
                        profile_kind,
                        profile_key,
                        profile_kind,
                        resolved_now,
                    ),
                )
                row = cursor.fetchone()
            _commit(connection)
    except Exception as exc:
        raise ProfileRefreshJobUnavailable(str(exc)) from exc

    return _rebuild_summary(profile_kind=profile_kind, row=row) if row is not None else None


def _connect(database_url: str | None, connection_factory: ConnectionFactory | None) -> Any:
    if connection_factory is not None:
        return connection_factory()

    import psycopg
    from psycopg.rows import dict_row

    assert database_url is not None
    return psycopg.connect(database_url, connect_timeout=2, row_factory=dict_row)


def _commit(connection: Any) -> None:
    commit = getattr(connection, "commit", None)
    if callable(commit):
        commit()


def _job_from_row(row: dict[str, Any]) -> ProfileRefreshJob:
    return ProfileRefreshJob(
        id=str(row["id"]),
        profile_kind=str(row["profile_kind"]),
        profile_key=str(row["profile_key"]),
        priority=int(row["priority"]),
        reason=str(row["reason"]),
        attempts=int(row["attempts"]),
        max_attempts=int(row["max_attempts"]),
        payload=_json_dict(row.get("payload")),
        run_after=cast(datetime, row["run_after"]),
        lease_expires_at=cast(datetime | None, row.get("lease_expires_at")),
    )


def _rebuild_summary(*, profile_kind: str, row: dict[str, Any]) -> ProfileRebuildSummary:
    return ProfileRebuildSummary(
        profile_kind=profile_kind,
        profile_key=str(row["profile_key"]),
        evidence_count=int(row["evidence_count"]),
        top_evidence_ids=_string_tuple(row.get("top_evidence_ids")),
        realtime_level=str(row["realtime_level"]),
        historical_level=str(row["historical_level"]),
        confidence_level=str(row["confidence_level"]),
        computed_at=cast(datetime, row["computed_at"]),
    )


def _json_dict(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        payload = json.loads(value)
        return payload if isinstance(payload, dict) else {}
    return {}


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return tuple(str(item) for item in value)
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    if isinstance(value, str):
        payload = json.loads(value)
        if isinstance(payload, list):
            return tuple(str(item) for item in payload)
        return (value,)
    return ()
