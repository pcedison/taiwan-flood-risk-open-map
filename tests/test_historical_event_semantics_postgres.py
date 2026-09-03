from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
import psycopg
from psycopg import sql


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = REPO_ROOT / "infra" / "migrations" / "0060_historical_event_semantics.sql"


def _database_url() -> str:
    database_url = os.getenv("EVIDENCE_TEST_DATABASE_URL")
    required = os.getenv("OFFICIAL_DB_ACCEPTANCE_REQUIRED") == "1"
    if not database_url:
        if required:
            pytest.fail("EVIDENCE_TEST_DATABASE_URL is required for PostGIS acceptance")
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
    schema_name = f"history_semantics_{uuid4().hex}"
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
    info = psycopg.conninfo.conninfo_to_dict(database_url)
    info["options"] = f"-c search_path={schema_name},public"
    isolated_url = psycopg.conninfo.make_conninfo(**info)
    try:
        yield isolated_url
    finally:
        with psycopg.connect(database_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )


def test_migration_backfills_year_only_rows_without_synthetic_dates() -> None:
    database_url = _database_url()
    migration_sql = MIGRATION.read_text(encoding="utf-8")
    with _isolated_schema(database_url) as isolated_url:
        source_id = uuid4()
        raw_id = uuid4()
        staging_id = uuid4()
        evidence_id = uuid4()
        with psycopg.connect(isolated_url) as connection:
            connection.execute(
                """
                CREATE TABLE data_sources (
                    id uuid PRIMARY KEY,
                    adapter_key text NOT NULL
                );
                CREATE TABLE raw_snapshots (
                    id uuid PRIMARY KEY,
                    adapter_key text NOT NULL,
                    source_timestamp_min timestamptz,
                    source_timestamp_max timestamptz,
                    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
                );
                CREATE TABLE staging_evidence (
                    id uuid PRIMARY KEY,
                    data_source_id uuid NOT NULL,
                    source_id text NOT NULL,
                    occurred_at timestamptz,
                    observed_at timestamptz,
                    payload jsonb NOT NULL DEFAULT '{}'::jsonb
                );
                CREATE TABLE evidence (
                    id uuid PRIMARY KEY,
                    data_source_id uuid NOT NULL,
                    source_id text NOT NULL,
                    occurred_at timestamptz,
                    observed_at timestamptz,
                    properties jsonb NOT NULL DEFAULT '{}'::jsonb,
                    geom geometry(Geometry, 4326),
                    ingestion_status text NOT NULL DEFAULT 'accepted',
                    source_type text NOT NULL DEFAULT 'official',
                    event_type text NOT NULL DEFAULT 'flood_report'
                )
                """
            )
            connection.execute(
                """
                INSERT INTO data_sources (id, adapter_key)
                VALUES (%s, 'official.nstc.flood_disaster_points')
                """,
                (source_id,),
            )
            connection.execute(
                """
                INSERT INTO raw_snapshots (
                    id, adapter_key, source_timestamp_min, source_timestamp_max
                ) VALUES (
                    %s, 'official.nstc.flood_disaster_points',
                    '2025-12-31T04:00:00Z', '2025-12-31T04:00:00Z'
                )
                """,
                (raw_id,),
            )
            connection.execute(
                """
                INSERT INTO staging_evidence (
                    id, data_source_id, source_id, occurred_at, observed_at, payload
                ) VALUES (
                    %s, %s, 'data-gov-130016:2025:demo:1',
                    '2025-12-31T04:00:00Z', '2025-12-31T04:00:00Z',
                    '{"event_year":2025,"location_payload":{"geometry":{"type":"Point","coordinates":[120.2,23.0]}}}'::jsonb
                )
                """,
                (staging_id, source_id),
            )
            connection.execute(
                """
                INSERT INTO evidence (
                    id, data_source_id, source_id, occurred_at, observed_at,
                    properties, geom
                ) VALUES (
                    %s, %s, 'data-gov-130016:2025:demo:1',
                    '2025-12-31T04:00:00Z', '2025-12-31T04:00:00Z',
                    '{"event_year":2025}'::jsonb,
                    ST_SetSRID(ST_MakePoint(120.2, 23.0), 4326)
                )
                """,
                (evidence_id, source_id),
            )
            connection.execute(migration_sql)
            # The migration is also safe if replayed by an operator in an
            # isolated recovery transaction.
            connection.execute(migration_sql)

            staging = connection.execute(
                """
                SELECT event_year, temporal_precision, occurred_at, observed_at,
                       event_start_at, event_end_at, source_record_key
                FROM staging_evidence WHERE id = %s
                """,
                (staging_id,),
            ).fetchone()
            promoted = connection.execute(
                """
                SELECT event_year, temporal_precision, occurred_at, observed_at,
                       event_start_at, event_end_at, source_record_key
                FROM evidence WHERE id = %s
                """,
                (evidence_id,),
            ).fetchone()
            raw = connection.execute(
                """
                SELECT source_timestamp_min, source_timestamp_max,
                       metadata->>'temporal_precision',
                       metadata->>'exact_event_timestamps_available'
                FROM raw_snapshots WHERE id = %s
                """,
                (raw_id,),
            ).fetchone()

        assert staging[:6] == (2025, "year", None, None, None, None)
        assert promoted[:6] == (2025, "year", None, None, None, None)
        canonical_key = (
            "2025:"
            + sha256("2025|demo|120.200000|23.000000".encode("utf-8")).hexdigest()[:24]
        )
        assert staging[6] == canonical_key
        assert promoted[6] == canonical_key
        assert raw == (None, None, "year", "false")
