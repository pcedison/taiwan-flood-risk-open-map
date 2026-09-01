from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
import sys
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "workers"))

from app.jobs.historical_coverage import (  # noqa: E402
    HistoricalCoverageWriteError,
    PostgresHistoricalCoverageWriter,
)
from infra.scripts.apply_migrations import apply_migrations  # noqa: E402


def _database_url() -> str:
    database_url = os.getenv("EVIDENCE_TEST_DATABASE_URL")
    required = os.getenv("OFFICIAL_DB_ACCEPTANCE_REQUIRED") == "1"
    if not database_url:
        if required:
            pytest.fail(
                "EVIDENCE_TEST_DATABASE_URL is required when "
                "OFFICIAL_DB_ACCEPTANCE_REQUIRED=1"
            )
        pytest.skip("EVIDENCE_TEST_DATABASE_URL is not configured")
    try:
        with psycopg.connect(database_url) as connection:
            connection.execute("SELECT PostGIS_Version()")
    except (OSError, psycopg.Error) as exc:
        if required:
            pytest.fail(f"required PostGIS is unreachable: {exc}")
        pytest.skip(f"PostGIS is unreachable: {exc}")
    return database_url


@contextmanager
def _isolated_schema(database_url: str) -> Iterator[str]:
    schema_name = f"history_source_checks_{uuid4().hex}"
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
    connection_info = psycopg.conninfo.conninfo_to_dict(database_url)
    existing_options = connection_info.get("options", "")
    connection_info["options"] = (
        f"{existing_options} -c search_path={schema_name},public".strip()
    )
    try:
        yield psycopg.conninfo.make_conninfo(**connection_info)
    finally:
        with psycopg.connect(database_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )


def test_successful_snapshot_updates_22_county_year_checks_idempotently() -> None:
    database_url = _database_url()
    adapter_key = "official.nstc.flood_disaster_points"
    raw_ref = "raw/official/nstc/flood-disaster-points/test.json"
    assessed_at = datetime(2026, 9, 1, 2, 30, tzinfo=UTC)

    with _isolated_schema(database_url) as isolated_url:
        apply_migrations(database_url=isolated_url)
        with psycopg.connect(isolated_url) as connection:
            snapshot_id = connection.execute(
                """
                INSERT INTO realtime_jurisdiction_boundary_snapshots (
                    source_name, source_url, source_revision
                )
                VALUES ('test boundaries', 'https://example.test/boundaries', 'test-v1')
                RETURNING id
                """
            ).fetchone()[0]
            jurisdictions = connection.execute(
                """
                SELECT jurisdiction_code
                FROM realtime_jurisdictions
                ORDER BY jurisdiction_code
                """
            ).fetchall()
            for index, (jurisdiction_code,) in enumerate(jurisdictions):
                min_lng = 118.0 + index * 0.2
                max_lng = min_lng + 0.19
                connection.execute(
                    """
                    INSERT INTO realtime_jurisdiction_boundaries (
                        snapshot_id, jurisdiction_code, geom, geom_sha256
                    )
                    SELECT
                        %s,
                        %s,
                        candidate.geom,
                        encode(digest(ST_AsEWKB(candidate.geom), 'sha256'), 'hex')
                    FROM (
                        SELECT ST_Multi(ST_MakeEnvelope(%s, 23.0, %s, 23.2, 4326))
                            AS geom
                    ) candidate
                    """,
                    (snapshot_id, jurisdiction_code, min_lng, max_lng),
                )
            connection.execute(
                """
                UPDATE realtime_jurisdiction_boundary_snapshots
                SET imported_count = 22,
                    manifest_sha256 = repeat('a', 64),
                    approved_manifest_sha256 = repeat('a', 64),
                    is_complete = true,
                    reviewed_at = now(),
                    review_ref = 'test://history-source-checks',
                    is_active = true
                WHERE id = %s
                """,
                (snapshot_id,),
            )
            raw_snapshot_id = connection.execute(
                """
                INSERT INTO raw_snapshots (data_source_id, adapter_key, raw_ref, fetched_at)
                SELECT id, adapter_key, %s, %s
                FROM data_sources
                WHERE adapter_key = %s
                RETURNING id
                """,
                (raw_ref, assessed_at, adapter_key),
            ).fetchone()[0]
            first_lng = 118.05
            second_lng = 118.25
            for source_id, year, lng in (
                ("point-a", 2024, first_lng),
                ("point-b", 2024, first_lng),
                ("point-c", 2025, second_lng),
                # Roughly 51 metres beyond the first synthetic county. Reviewed
                # official points this close to a coastline may use the bounded
                # nearest-county fallback instead of invalidating the snapshot.
                ("point-near-boundary", 2024, 118.1905),
            ):
                connection.execute(
                    """
                    INSERT INTO staging_evidence (
                        raw_snapshot_id,
                        data_source_id,
                        source_id,
                        source_type,
                        event_type,
                        title,
                        summary,
                        occurred_at,
                        observed_at,
                        confidence,
                        validation_status,
                        payload
                    )
                    SELECT
                        %s,
                        id,
                        %s,
                        'official',
                        'flood_report',
                        %s,
                        'year-only official point',
                        make_timestamptz(%s, 12, 31, 12, 0, 0, 'Asia/Taipei'),
                        make_timestamptz(%s, 12, 31, 12, 0, 0, 'Asia/Taipei'),
                        0.82,
                        'accepted',
                        jsonb_build_object(
                            'adapter_key', %s::text,
                            'raw_ref', %s::text,
                            'location_payload', jsonb_build_object(
                                'geometry', jsonb_build_object(
                                    'type', 'Point',
                                    'coordinates', jsonb_build_array(%s::double precision, 23.1)
                                )
                            )
                        )
                    FROM data_sources
                    WHERE adapter_key = %s
                    """,
                    (
                        raw_snapshot_id,
                        source_id,
                        source_id,
                        year,
                        year,
                        adapter_key,
                        raw_ref,
                        lng,
                        adapter_key,
                    ),
                )
            connection.execute(
                """
                INSERT INTO staging_evidence (
                    raw_snapshot_id,
                    data_source_id,
                    source_id,
                    source_type,
                    event_type,
                    title,
                    summary,
                    occurred_at,
                    observed_at,
                    confidence,
                    validation_status,
                    payload
                )
                SELECT
                    %s,
                    id,
                    'footprint-cross-county',
                    'official',
                    'flood_report',
                    'cross-county flood footprint',
                    'one source footprint must contribute to every intersected county',
                    make_timestamptz(2024, 12, 31, 12, 0, 0, 'Asia/Taipei'),
                    make_timestamptz(2024, 12, 31, 12, 0, 0, 'Asia/Taipei'),
                    0.82,
                    'accepted',
                    jsonb_build_object(
                        'adapter_key', %s::text,
                        'raw_ref', %s::text,
                        'location_payload', jsonb_build_object(
                            'geometry', ST_AsGeoJSON(
                                ST_MakeEnvelope(118.1, 23.05, 118.3, 23.15, 4326)
                            )::jsonb
                        )
                    )
                FROM data_sources
                WHERE adapter_key = %s
                """,
                (raw_snapshot_id, adapter_key, raw_ref, adapter_key),
            )
            connection.commit()

        writer = PostgresHistoricalCoverageWriter(database_url=isolated_url)
        first = writer.record_success(
            adapter_key=adapter_key,
            raw_ref=raw_ref,
            assessed_at=assessed_at,
        )
        second = writer.record_success(
            adapter_key=adapter_key,
            raw_ref=raw_ref,
            assessed_at=assessed_at,
        )

        assert first.assessed_years == (2024, 2025)
        assert first.source_check_count == 44
        assert first.attributed_record_count == 5
        assert first.boundary_adjusted_record_count == 1
        assert second.source_check_count == 44
        assert second.boundary_adjusted_record_count == 1
        with psycopg.connect(isolated_url) as connection:
            summary = connection.execute(
                """
                SELECT
                    count(*)::integer,
                    count(*) FILTER (WHERE status = 'partial')::integer,
                    sum(record_count)::integer,
                    min(checked_source_count)::integer,
                    max(checked_source_count)::integer
                FROM historical_coverage_cells
                WHERE coverage_year IN (2024, 2025)
                """
            ).fetchone()
            check_count = connection.execute(
                "SELECT count(*)::integer FROM historical_coverage_source_checks"
            ).fetchone()[0]

        assert summary == (44, 44, 6, 1, 1)
        assert check_count == 44

        with psycopg.connect(isolated_url) as connection:
            connection.execute(
                """
                INSERT INTO staging_evidence (
                    raw_snapshot_id,
                    data_source_id,
                    source_id,
                    source_type,
                    event_type,
                    title,
                    summary,
                    occurred_at,
                    observed_at,
                    confidence,
                    validation_status,
                    payload
                )
                SELECT
                    %s,
                    id,
                    'point-far-outside-boundaries',
                    'official',
                    'flood_report',
                    'invalid distant point',
                    'coverage writer must fail outside the bounded fallback',
                    make_timestamptz(2025, 12, 31, 12, 0, 0, 'Asia/Taipei'),
                    make_timestamptz(2025, 12, 31, 12, 0, 0, 'Asia/Taipei'),
                    0.82,
                    'accepted',
                    jsonb_build_object(
                        'adapter_key', %s::text,
                        'raw_ref', %s::text,
                        'location_payload', jsonb_build_object(
                            'geometry', jsonb_build_object(
                                'type', 'Point',
                                'coordinates', jsonb_build_array(117.0, 23.1)
                            )
                        )
                    )
                FROM data_sources
                WHERE adapter_key = %s
                """,
                (raw_snapshot_id, adapter_key, raw_ref, adapter_key),
            )
            connection.commit()

        with pytest.raises(HistoricalCoverageWriteError, match="outside the active"):
            writer.record_success(
                adapter_key=adapter_key,
                raw_ref=raw_ref,
                assessed_at=assessed_at,
            )

        with psycopg.connect(isolated_url) as connection:
            connection.execute(
                "DELETE FROM staging_evidence WHERE source_id = %s",
                ("point-far-outside-boundaries",),
            )
            connection.execute(
                """
                INSERT INTO staging_evidence (
                    raw_snapshot_id,
                    data_source_id,
                    source_id,
                    source_type,
                    event_type,
                    title,
                    summary,
                    occurred_at,
                    observed_at,
                    confidence,
                    validation_status,
                    payload
                )
                SELECT
                    %s,
                    id,
                    'point-without-geometry',
                    'official',
                    'flood_report',
                    'invalid accepted row',
                    'coverage writer must fail closed',
                    make_timestamptz(2025, 12, 31, 12, 0, 0, 'Asia/Taipei'),
                    make_timestamptz(2025, 12, 31, 12, 0, 0, 'Asia/Taipei'),
                    0.82,
                    'accepted',
                    jsonb_build_object(
                        'adapter_key', %s::text,
                        'raw_ref', %s::text
                    )
                FROM data_sources
                WHERE adapter_key = %s
                """,
                (raw_snapshot_id, adapter_key, raw_ref, adapter_key),
            )
            connection.commit()

        with pytest.raises(HistoricalCoverageWriteError, match="without valid geometry"):
            writer.record_success(
                adapter_key=adapter_key,
                raw_ref=raw_ref,
                assessed_at=assessed_at,
            )
