from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from typing import Any, cast

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


ConnectionFactory = Callable[[], Any]


class RiskProfileRepositoryUnavailable(RuntimeError):
    """Raised when precomputed risk profile storage cannot be queried."""


@dataclass(frozen=True)
class RiskProfileRecord:
    profile_kind: str
    profile_key: str
    profile_scope: str
    profile_radius_m: int
    score_version: str
    realtime_level: str
    historical_level: str
    confidence_level: str
    evidence_counts: dict[str, Any]
    top_evidence_ids: tuple[str, ...]
    latest_observed_at: datetime | None
    latest_occurred_at: datetime | None
    latest_ingested_at: datetime | None
    coverage_gaps: tuple[str, ...]
    missing_sources: tuple[str, ...]
    computed_at: datetime
    expires_at: datetime | None
    status: str
    distance_to_query_m: float | None


def fetch_best_profile_for_point(
    *,
    database_url: str,
    lat: float,
    lng: float,
    radius_m: int,
    now: datetime | None = None,
    connection_factory: ConnectionFactory | None = None,
) -> RiskProfileRecord | None:
    reference_time = now or datetime.now(UTC)
    sql = """
        WITH query_point AS (
            SELECT
                ST_SetSRID(ST_MakePoint(%s, %s), 4326) AS geom,
                ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography AS geog
        ),
        candidate_profiles AS (
            SELECT
                'admin_area'::text AS profile_kind,
                ap.area_key AS profile_key,
                ap.scope AS profile_scope,
                ap.profile_radius_m,
                ap.score_version,
                ap.realtime_level,
                ap.historical_level,
                ap.confidence_level,
                ap.evidence_counts,
                ap.top_evidence_ids,
                ap.latest_observed_at,
                ap.latest_occurred_at,
                ap.latest_ingested_at,
                ap.coverage_gaps,
                ap.missing_sources,
                ap.computed_at,
                ap.expires_at,
                ap.status,
                ST_Distance(
                    COALESCE(ap.centroid, ST_PointOnSurface(ap.geom))::geography,
                    qp.geog
                ) AS distance_to_query_m,
                CASE ap.scope
                    WHEN 'village' THEN 1
                    WHEN 'town' THEN 2
                    WHEN 'county' THEN 3
                    ELSE 4
                END AS scope_rank
            FROM admin_area_profiles ap
            CROSS JOIN query_point qp
            WHERE ap.status = 'healthy'
                AND ap.computed_at <= %s
                AND (ap.expires_at IS NULL OR ap.expires_at > %s)
                AND (
                    ST_Covers(ap.geom, qp.geom)
                    OR ST_DWithin(
                        COALESCE(ap.centroid, ST_PointOnSurface(ap.geom))::geography,
                        qp.geog,
                        LEAST(ap.profile_radius_m, %s)
                    )
                )
            UNION ALL
            SELECT
                'risk_grid'::text AS profile_kind,
                gp.grid_key AS profile_key,
                gp.grid_system || ':' || gp.grid_resolution AS profile_scope,
                gp.profile_radius_m,
                gp.score_version,
                gp.realtime_level,
                gp.historical_level,
                gp.confidence_level,
                gp.evidence_counts,
                gp.top_evidence_ids,
                gp.latest_observed_at,
                gp.latest_occurred_at,
                gp.latest_ingested_at,
                gp.coverage_gaps,
                gp.missing_sources,
                gp.computed_at,
                gp.expires_at,
                gp.status,
                ST_Distance(
                    COALESCE(gp.centroid, ST_PointOnSurface(gp.geom))::geography,
                    qp.geog
                ) AS distance_to_query_m,
                0 AS scope_rank
            FROM risk_grid_profiles gp
            CROSS JOIN query_point qp
            WHERE gp.status = 'healthy'
                AND gp.computed_at <= %s
                AND (gp.expires_at IS NULL OR gp.expires_at > %s)
                AND (
                    ST_Covers(gp.geom, qp.geom)
                    OR ST_DWithin(
                        COALESCE(gp.centroid, ST_PointOnSurface(gp.geom))::geography,
                        qp.geog,
                        LEAST(gp.profile_radius_m, %s)
                    )
                )
        )
        SELECT *
        FROM candidate_profiles
        ORDER BY
            scope_rank ASC,
            distance_to_query_m ASC NULLS LAST,
            computed_at DESC
        LIMIT 1
    """
    params = (
        lng,
        lat,
        lng,
        lat,
        reference_time,
        reference_time,
        radius_m,
        reference_time,
        reference_time,
        radius_m,
    )
    try:
        with _connect(database_url, connection_factory) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                row = cursor.fetchone()
    except (OSError, psycopg.Error) as exc:
        raise RiskProfileRepositoryUnavailable(str(exc)) from exc

    return _profile_from_row(row) if row is not None else None


def enqueue_profile_refresh_job(
    *,
    database_url: str,
    profile_kind: str,
    profile_key: str,
    priority: int = 0,
    reason: str = "scheduled_refresh",
    run_after: datetime | None = None,
    payload: dict[str, Any] | None = None,
    connection_factory: ConnectionFactory | None = None,
) -> str | None:
    sql = """
        INSERT INTO profile_refresh_jobs (
            profile_kind,
            profile_key,
            priority,
            reason,
            run_after,
            payload,
            created_at,
            updated_at
        )
        VALUES (
            %s,
            %s,
            %s,
            %s,
            COALESCE(%s::timestamptz, now()),
            %s::jsonb,
            now(),
            now()
        )
        ON CONFLICT DO NOTHING
        RETURNING id::text AS id
    """
    try:
        with _connect(database_url, connection_factory) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql,
                    (
                        profile_kind,
                        profile_key,
                        priority,
                        reason,
                        run_after,
                        Jsonb(payload or {}),
                    ),
                )
                row = cursor.fetchone()
            _commit(connection)
    except (OSError, psycopg.Error) as exc:
        raise RiskProfileRepositoryUnavailable(str(exc)) from exc

    if row is None:
        return None
    if isinstance(row, dict):
        return str(row["id"])
    return str(cast(Any, row)[0])


def _connect(database_url: str, connection_factory: ConnectionFactory | None) -> Any:
    if connection_factory is not None:
        return connection_factory()
    return psycopg.connect(database_url, connect_timeout=2, row_factory=dict_row)


def _commit(connection: Any) -> None:
    commit = getattr(connection, "commit", None)
    if callable(commit):
        commit()


def _profile_from_row(row: dict[str, Any]) -> RiskProfileRecord:
    return RiskProfileRecord(
        profile_kind=str(row["profile_kind"]),
        profile_key=str(row["profile_key"]),
        profile_scope=str(row["profile_scope"]),
        profile_radius_m=int(row["profile_radius_m"]),
        score_version=str(row["score_version"]),
        realtime_level=str(row["realtime_level"]),
        historical_level=str(row["historical_level"]),
        confidence_level=str(row["confidence_level"]),
        evidence_counts=_json_dict(row.get("evidence_counts")),
        top_evidence_ids=_string_tuple(row.get("top_evidence_ids")),
        latest_observed_at=cast(datetime | None, row.get("latest_observed_at")),
        latest_occurred_at=cast(datetime | None, row.get("latest_occurred_at")),
        latest_ingested_at=cast(datetime | None, row.get("latest_ingested_at")),
        coverage_gaps=_string_tuple(row.get("coverage_gaps")),
        missing_sources=_string_tuple(row.get("missing_sources")),
        computed_at=cast(datetime, row["computed_at"]),
        expires_at=cast(datetime | None, row.get("expires_at")),
        status=str(row["status"]),
        distance_to_query_m=_optional_float(row.get("distance_to_query_m")),
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


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(cast(Any, value))
