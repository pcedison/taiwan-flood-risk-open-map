from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "workers"))

from app.jobs.historical_coverage_review import (  # noqa: E402
    PostgresHistoricalCoverageGapReviewWriter,
    load_historical_coverage_gap_review,
)
from infra.scripts.apply_migrations import apply_migrations  # noqa: E402


REVIEW_MANIFEST = (
    REPO_ROOT
    / "docs"
    / "data-sources"
    / "official"
    / "historical-coverage-gap-review-2026-09-02.json"
)
REVIEW_MANIFEST_SHA256 = (
    "01ca620ee29d8a8815ff00fffb7894ef02e1acf36a01960b00e2d625b1598d3c"
)


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
    schema_name = f"history_gap_review_{uuid4().hex}"
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


def test_gap_review_updates_only_unassessed_cells_and_is_idempotent() -> None:
    database_url = _database_url()
    manifest, manifest_sha256 = load_historical_coverage_gap_review(
        REVIEW_MANIFEST,
        expected_sha256=REVIEW_MANIFEST_SHA256,
    )

    with _isolated_schema(database_url) as isolated_url:
        apply_migrations(database_url=isolated_url)
        with psycopg.connect(isolated_url) as connection:
            jurisdiction_code = connection.execute(
                """
                SELECT jurisdiction_code
                FROM realtime_jurisdictions
                ORDER BY jurisdiction_code
                LIMIT 1
                """
            ).fetchone()[0]
            connection.execute(
                """
                UPDATE historical_coverage_cells
                SET status = 'partial',
                    checked_source_count = 1,
                    successful_source_count = 1,
                    source_adapter_keys = ARRAY['official.wra.historical_flood'],
                    assessed_at = now(),
                    last_attempted_at = now(),
                    last_succeeded_at = now(),
                    review_ref = 'source-snapshot-review',
                    status_reason = 'Preserved source-derived partial result.',
                    updated_at = now()
                WHERE jurisdiction_code = %s
                  AND coverage_year = 2017
                """,
                (jurisdiction_code,),
            )
            connection.commit()

        writer = PostgresHistoricalCoverageGapReviewWriter(database_url=isolated_url)
        dry_run = writer.assess(
            manifest,
            manifest_sha256=manifest_sha256,
            persist=False,
        )
        first = writer.assess(
            manifest,
            manifest_sha256=manifest_sha256,
            persist=True,
        )
        second = writer.assess(
            manifest,
            manifest_sha256=manifest_sha256,
            persist=True,
        )

        assert dry_run.would_update_cell_count == 43
        assert dry_run.applied_cell_count == 0
        assert first.applied_cell_count == 43
        assert second.applied_cell_count == 0
        assert second.preserved_cell_count == 44

        with psycopg.connect(isolated_url) as connection:
            status_rows = connection.execute(
                """
                SELECT coverage_year, status, count(*)::integer
                FROM historical_coverage_cells
                WHERE coverage_year IN (2017, 2026)
                GROUP BY coverage_year, status
                ORDER BY coverage_year, status
                """
            ).fetchall()
            preserved = connection.execute(
                """
                SELECT status, review_ref
                FROM historical_coverage_cells
                WHERE jurisdiction_code = %s
                  AND coverage_year = 2017
                """,
                (jurisdiction_code,),
            ).fetchone()
            reviewed_metadata = connection.execute(
                """
                SELECT
                    min(checked_source_count)::integer,
                    max(successful_source_count)::integer,
                    count(*) FILTER (
                        WHERE review_ref LIKE 'coverage-gap-review:v1:%'
                    )::integer
                FROM historical_coverage_cells
                WHERE coverage_year IN (2017, 2026)
                  AND status IN ('not_published', 'failed')
                """
            ).fetchone()

        assert status_rows == [
            (2017, "not_published", 21),
            (2017, "partial", 1),
            (2026, "failed", 22),
        ]
        assert preserved == ("partial", "source-snapshot-review")
        assert reviewed_metadata == (1, 0, 43)
