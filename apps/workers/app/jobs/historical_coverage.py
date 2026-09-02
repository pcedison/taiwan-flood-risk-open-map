from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

ConnectionFactory = Callable[[], Any]

HISTORICAL_COVERAGE_START_YEAR: Final = 2018
HISTORICAL_COVERAGE_END_YEAR: Final = 2026
HISTORICAL_COVERAGE_POINT_FALLBACK_METERS: Final = 100
HISTORICAL_COVERAGE_ADAPTER_KEYS: Final[frozenset[str]] = frozenset(
    {
        "official.nstc.flood_disaster_points",
        "official.wra.historical_flood",
    }
)


class HistoricalCoverageWriteError(RuntimeError):
    pass


@dataclass(frozen=True)
class HistoricalCoverageWriteResult:
    adapter_key: str
    assessed_years: tuple[int, ...]
    source_check_count: int
    attributed_record_count: int
    boundary_adjusted_record_count: int


class PostgresHistoricalCoverageWriter:
    def __init__(
        self,
        *,
        database_url: str | None = None,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        if database_url is None and connection_factory is None:
            raise ValueError("database_url or connection_factory is required")
        self._database_url = database_url
        self._connection_factory = connection_factory

    def record_success(
        self,
        *,
        adapter_key: str,
        raw_ref: str,
        assessed_at: datetime,
    ) -> HistoricalCoverageWriteResult:
        if adapter_key not in HISTORICAL_COVERAGE_ADAPTER_KEYS:
            raise ValueError("adapter is not approved for historical coverage updates")
        if assessed_at.tzinfo is None or assessed_at.utcoffset() is None:
            raise ValueError("assessed_at must be timezone-aware")
        review_ref = (
            "worker-snapshot:v2:"
            f"point-fallback-{HISTORICAL_COVERAGE_POINT_FALLBACK_METERS}m:"
            f"{adapter_key}:"
            f"{hashlib.sha256(raw_ref.encode('utf-8')).hexdigest()}"
        )
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    _UPSERT_SOURCE_CHECKS_SQL,
                    (
                        raw_ref,
                        adapter_key,
                        HISTORICAL_COVERAGE_START_YEAR,
                        HISTORICAL_COVERAGE_END_YEAR,
                        adapter_key,
                        assessed_at,
                        assessed_at,
                        review_ref,
                    ),
                )
                row = cursor.fetchone()
                if row is None:
                    raise HistoricalCoverageWriteError(
                        "historical coverage preflight returned no row"
                    )
                accepted_count = int(row[0])
                geometry_count = int(row[1])
                attributed_count = int(row[2])
                years = tuple(int(year) for year in (row[3] or ()))
                boundary_count = int(row[4])
                boundary_adjusted_count = int(row[5])
                source_check_count = int(row[6])
                if boundary_count != 22:
                    raise HistoricalCoverageWriteError(
                        "active historical coverage boundary contract is not exactly 22 counties"
                    )
                if accepted_count != geometry_count:
                    raise HistoricalCoverageWriteError(
                        "historical snapshot contains accepted rows without valid geometry"
                    )
                if geometry_count != attributed_count:
                    raise HistoricalCoverageWriteError(
                        "historical snapshot contains geometry outside the active 22-county "
                        f"boundary contract and its bounded "
                        f"{HISTORICAL_COVERAGE_POINT_FALLBACK_METERS}-metre point fallback"
                    )
                if not years:
                    connection.commit()
                    return HistoricalCoverageWriteResult(
                        adapter_key=adapter_key,
                        assessed_years=(),
                        source_check_count=0,
                        attributed_record_count=0,
                        boundary_adjusted_record_count=0,
                    )
                cursor.execute(_REFRESH_COVERAGE_CELLS_SQL, (list(years),))
            connection.commit()
        return HistoricalCoverageWriteResult(
            adapter_key=adapter_key,
            assessed_years=years,
            source_check_count=source_check_count,
            attributed_record_count=attributed_count,
            boundary_adjusted_record_count=boundary_adjusted_count,
        )

    def _connect(self) -> Any:
        if self._connection_factory is not None:
            return self._connection_factory()
        import psycopg

        assert self._database_url is not None
        return psycopg.connect(self._database_url)


_SOURCE_ROWS_CTE = f"""
    target_snapshot AS (
        SELECT raw.id
        FROM raw_snapshots raw
        WHERE raw.raw_ref = %s
          AND raw.adapter_key = %s
    ),
    accepted_row_candidates AS MATERIALIZED (
        SELECT
            staging.id,
            COALESCE(
                NULLIF(staging.payload->>'evidence_id', ''),
                CASE
                    WHEN staging.source_id IS NOT NULL THEN
                        staging.source_id || '|' || staging.occurred_at::text
                    ELSE NULL
                END,
                staging.id::text
            ) AS evidence_key,
            EXTRACT(YEAR FROM staging.occurred_at)::integer AS coverage_year,
            staging.payload->'location_payload'->'geometry' AS geometry_payload,
            staging.created_at
        FROM staging_evidence staging
        JOIN target_snapshot snapshot ON snapshot.id = staging.raw_snapshot_id
        WHERE staging.validation_status = 'accepted'
          AND staging.event_type = 'flood_report'
          AND staging.occurred_at IS NOT NULL
          AND EXTRACT(YEAR FROM staging.occurred_at)::integer BETWEEN %s AND %s
    ),
    accepted_rows AS MATERIALIZED (
        SELECT DISTINCT ON (candidate.evidence_key)
            candidate.id,
            candidate.coverage_year,
            candidate.geometry_payload
        FROM accepted_row_candidates candidate
        ORDER BY candidate.evidence_key, candidate.created_at DESC, candidate.id DESC
    ),
    source_rows AS MATERIALIZED (
        SELECT
            accepted.id,
            accepted.coverage_year,
            ST_SetSRID(
                ST_GeomFromGeoJSON(accepted.geometry_payload::text),
                4326
            ) AS geom
        FROM accepted_rows accepted
        WHERE jsonb_typeof(accepted.geometry_payload) = 'object'
    ),
    active_boundaries AS MATERIALIZED (
        SELECT boundary.jurisdiction_code, boundary.geom
        FROM realtime_jurisdiction_boundary_snapshots snapshot
        JOIN realtime_jurisdiction_boundaries boundary
          ON boundary.snapshot_id = snapshot.id
        WHERE snapshot.is_active
          AND snapshot.is_complete
          AND snapshot.reviewed_at IS NOT NULL
          AND snapshot.review_ref IS NOT NULL
          AND snapshot.imported_count = 22
          AND snapshot.manifest_sha256 = snapshot.approved_manifest_sha256
    ),
    active_boundary_parts AS MATERIALIZED (
        SELECT boundary.jurisdiction_code, part.geom
        FROM active_boundaries boundary
        CROSS JOIN LATERAL ST_Subdivide(boundary.geom, 256) AS part(geom)
    ),
    point_attributed_rows AS MATERIALIZED (
        SELECT DISTINCT ON (source.id)
            source.id,
            source.coverage_year,
            boundary_part.jurisdiction_code
        FROM source_rows source
        JOIN active_boundary_parts boundary_part
          ON boundary_part.geom && source.geom
         AND ST_Covers(boundary_part.geom, source.geom)
        WHERE ST_GeometryType(source.geom) = 'ST_Point'
        ORDER BY source.id, boundary_part.jurisdiction_code
    ),
    polygon_attributed_rows AS MATERIALIZED (
        SELECT DISTINCT
            source.id,
            source.coverage_year,
            boundary_part.jurisdiction_code
        FROM source_rows source
        JOIN active_boundary_parts boundary_part
          ON boundary_part.geom && source.geom
         AND ST_Intersects(boundary_part.geom, source.geom)
          AND ST_Area(
              ST_Intersection(boundary_part.geom, source.geom)::geography
          ) > 0
        WHERE ST_GeometryType(source.geom) IN ('ST_Polygon', 'ST_MultiPolygon')
    ),
    exact_attributed_rows AS MATERIALIZED (
        SELECT id, coverage_year, jurisdiction_code
        FROM point_attributed_rows
        UNION ALL
        SELECT id, coverage_year, jurisdiction_code
        FROM polygon_attributed_rows
    ),
    unattributed_point_rows AS MATERIALIZED (
        SELECT source.id, source.coverage_year, source.geom
        FROM source_rows source
        WHERE ST_GeometryType(source.geom) = 'ST_Point'
          AND NOT EXISTS (
              SELECT 1
              FROM exact_attributed_rows attributed
              WHERE attributed.id = source.id
          )
    ),
    boundary_adjusted_rows AS MATERIALIZED (
        SELECT
            source.id,
            source.coverage_year,
            nearest.jurisdiction_code
        FROM unattributed_point_rows source
        JOIN LATERAL (
            SELECT boundary.jurisdiction_code
            FROM active_boundaries boundary
            WHERE ST_DWithin(
                boundary.geom::geography,
                source.geom::geography,
                {HISTORICAL_COVERAGE_POINT_FALLBACK_METERS}
            )
            ORDER BY
                ST_Distance(boundary.geom::geography, source.geom::geography),
                boundary.jurisdiction_code
            LIMIT 1
        ) nearest ON true
    ),
    attributed_rows AS MATERIALIZED (
        SELECT id, coverage_year, jurisdiction_code
        FROM exact_attributed_rows
        UNION ALL
        SELECT id, coverage_year, jurisdiction_code
        FROM boundary_adjusted_rows
    )
"""

_UPSERT_SOURCE_CHECKS_SQL = f"""
    WITH {_SOURCE_ROWS_CTE},
    source_years AS (
        SELECT DISTINCT coverage_year FROM source_rows
    ),
    record_counts AS MATERIALIZED (
        SELECT
            jurisdiction_code,
            coverage_year,
            count(DISTINCT id)::integer AS record_count
        FROM attributed_rows
        GROUP BY jurisdiction_code, coverage_year
    ),
    source_metrics AS MATERIALIZED (
        SELECT
            (SELECT count(*) FROM accepted_rows)::integer AS accepted_count,
            (SELECT count(*) FROM source_rows)::integer AS geometry_count,
            (SELECT count(DISTINCT id) FROM attributed_rows)::integer
                AS attributed_count,
            COALESCE(
                (SELECT array_agg(DISTINCT coverage_year ORDER BY coverage_year)
                 FROM source_rows),
                ARRAY[]::integer[]
            ) AS years,
            (SELECT count(*) FROM active_boundaries)::integer AS boundary_count,
            (SELECT count(DISTINCT id) FROM boundary_adjusted_rows)::integer
                AS boundary_adjusted_count
    ),
    valid_preflight AS (
        SELECT 1
        FROM source_metrics
        WHERE boundary_count = 22
          AND accepted_count = geometry_count
          AND geometry_count = attributed_count
    ),
    upserted_source_checks AS (
        INSERT INTO historical_coverage_source_checks (
            jurisdiction_code,
            coverage_year,
            adapter_key,
            status,
            record_count,
            attempted_at,
            succeeded_at,
            review_ref
        )
        SELECT
            boundary.jurisdiction_code,
            year_window.coverage_year,
            %s,
            'succeeded',
            COALESCE(counts.record_count, 0),
            %s,
            %s,
            %s
        FROM active_boundaries boundary
        CROSS JOIN source_years year_window
        CROSS JOIN valid_preflight
        LEFT JOIN record_counts counts
          ON counts.jurisdiction_code = boundary.jurisdiction_code
         AND counts.coverage_year = year_window.coverage_year
        ON CONFLICT (jurisdiction_code, coverage_year, adapter_key) DO UPDATE SET
            status = EXCLUDED.status,
            record_count = EXCLUDED.record_count,
            attempted_at = EXCLUDED.attempted_at,
            succeeded_at = EXCLUDED.succeeded_at,
            review_ref = EXCLUDED.review_ref,
            updated_at = now()
        RETURNING 1
    )
    SELECT
        metrics.accepted_count,
        metrics.geometry_count,
        metrics.attributed_count,
        metrics.years,
        metrics.boundary_count,
        metrics.boundary_adjusted_count,
        (SELECT count(*) FROM upserted_source_checks)::integer
    FROM source_metrics metrics
"""

_REFRESH_COVERAGE_CELLS_SQL = """
    WITH aggregate_checks AS (
        SELECT
            source_check.jurisdiction_code,
            source_check.coverage_year,
            COALESCE(
                sum(source_check.record_count)
                    FILTER (WHERE source_check.status = 'succeeded'),
                0
            )::integer AS record_count,
            count(*)::integer AS checked_source_count,
            count(*) FILTER (WHERE source_check.status = 'succeeded')::integer
                AS successful_source_count,
            array_agg(source_check.adapter_key ORDER BY source_check.adapter_key)
                AS source_adapter_keys,
            max(source_check.attempted_at) AS last_attempted_at,
            max(source_check.succeeded_at)
                FILTER (WHERE source_check.status = 'succeeded') AS last_succeeded_at,
            max(source_check.review_ref) AS review_ref
        FROM historical_coverage_source_checks source_check
        WHERE source_check.coverage_year = ANY(%s::integer[])
        GROUP BY source_check.jurisdiction_code, source_check.coverage_year
    )
    UPDATE historical_coverage_cells coverage
    SET
        status = CASE
            WHEN aggregate.successful_source_count > 0 THEN 'partial'
            ELSE 'failed'
        END,
        record_count = aggregate.record_count,
        checked_source_count = aggregate.checked_source_count,
        successful_source_count = aggregate.successful_source_count,
        source_adapter_keys = aggregate.source_adapter_keys,
        assessed_at = aggregate.last_attempted_at,
        last_attempted_at = aggregate.last_attempted_at,
        last_succeeded_at = aggregate.last_succeeded_at,
        review_ref = aggregate.review_ref,
        status_reason = CASE
            WHEN aggregate.successful_source_count > 0 THEN
                'Approved official source snapshots were checked; coverage remains partial until all reviewed sources are complete.'
            ELSE
                'All attempted official historical source checks failed.'
        END,
        updated_at = now()
    FROM aggregate_checks aggregate
    WHERE coverage.jurisdiction_code = aggregate.jurisdiction_code
      AND coverage.coverage_year = aggregate.coverage_year
"""
