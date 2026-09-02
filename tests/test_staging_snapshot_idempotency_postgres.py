from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import os
from typing import Iterator
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from app.adapters.news import SamplePublicWebNewsAdapter
from app.pipelines.postgres_writer import PostgresStagingBatchWriter
from app.pipelines.staging import build_staging_batch
from infra.scripts.apply_migrations import apply_migrations


def _database_url() -> str:
    database_url = os.getenv("EVIDENCE_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("EVIDENCE_TEST_DATABASE_URL is not configured")
    try:
        with psycopg.connect(database_url, connect_timeout=2) as connection:
            connection.execute("SELECT 1")
    except psycopg.Error as exc:
        pytest.skip(f"PostGIS is unreachable: {exc}")
    return database_url


@contextmanager
def _isolated_schema(database_url: str) -> Iterator[str]:
    schema_name = f"staging_idempotency_{uuid4().hex}"
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name))
        )
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


def test_replaying_one_raw_revision_keeps_one_staging_decision() -> None:
    with _isolated_schema(_database_url()) as isolated_url:
        apply_migrations(database_url=isolated_url)
        batch = build_staging_batch(
            SamplePublicWebNewsAdapter(
                [
                    {
                        "id": "snapshot-idempotency-1",
                        "url": "https://example.test/news/flood-1",
                        "title": "Reviewed flood report",
                        "summary": "One deterministic staging decision.",
                        "published_at": "2026-09-02T00:00:00Z",
                        "location_text": "Taiwan",
                        "confidence": 0.72,
                    }
                ],
                fetched_at=datetime(2026, 9, 2, tzinfo=UTC),
                raw_snapshot_key="raw/test/staging-idempotency.json",
            ).run()
        )
        writer = PostgresStagingBatchWriter(database_url=isolated_url)

        writer.write_batch(batch)
        writer.write_batch(batch)

        with psycopg.connect(isolated_url) as connection:
            counts = connection.execute(
                """
                SELECT
                    count(*)::integer,
                    count(DISTINCT payload->>'evidence_id')::integer
                FROM staging_evidence
                """
            ).fetchone()
            raw_count = connection.execute(
                "SELECT count(*)::integer FROM raw_snapshots"
            ).fetchone()[0]

        assert counts == (1, 1)
        assert raw_count == 1
