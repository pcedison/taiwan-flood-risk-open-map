from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from infra.scripts.apply_migrations import apply_migrations


TARGET_MIGRATION = "0059_historical_coverage_15y_retention.sql"


def _database_url() -> str:
    database_url = os.getenv("EVIDENCE_TEST_DATABASE_URL")
    required = os.getenv("OFFICIAL_DB_ACCEPTANCE_REQUIRED") == "1"
    if not database_url:
        if required:
            pytest.fail(
                "EVIDENCE_TEST_DATABASE_URL is required when OFFICIAL_DB_ACCEPTANCE_REQUIRED=1"
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
    schema_name = f"historical_coverage_{uuid4().hex}"
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


def test_migration_seeds_exact_fail_closed_matrix_and_is_idempotent() -> None:
    database_url = _database_url()

    with _isolated_schema(database_url) as isolated_url:
        summary = apply_migrations(database_url=isolated_url)
        assert TARGET_MIGRATION in summary.applied

        with psycopg.connect(isolated_url) as connection:
            row = connection.execute(
                """
                SELECT
                    count(*)::integer AS cell_count,
                    count(DISTINCT jurisdiction_code)::integer AS county_count,
                    count(DISTINCT coverage_year)::integer AS year_count,
                    min(coverage_year)::integer AS start_year,
                    max(coverage_year)::integer AS end_year,
                    count(*) FILTER (WHERE status = 'unassessed')::integer
                        AS unassessed_count
                FROM historical_coverage_cells
                """
            ).fetchone()

        assert row == (330, 22, 15, 2012, 2026, 330)

        repeated = apply_migrations(database_url=isolated_url)
        assert TARGET_MIGRATION in repeated.skipped
        with psycopg.connect(isolated_url) as connection:
            assert connection.execute(
                "SELECT count(*) FROM historical_coverage_cells"
            ).fetchone() == (330,)


def test_ledger_rejects_false_empty_and_accepts_reviewed_empty() -> None:
    database_url = _database_url()

    with _isolated_schema(database_url) as isolated_url:
        apply_migrations(database_url=isolated_url)

        with psycopg.connect(isolated_url) as connection:
            with pytest.raises(psycopg.errors.CheckViolation):
                connection.execute(
                    """
                    UPDATE historical_coverage_cells
                    SET status = 'official_checked_empty',
                        status_reason = 'No rows returned.'
                    WHERE jurisdiction_code = '67000000'
                      AND coverage_year = 2026
                    """
                )
            connection.rollback()

            with pytest.raises(psycopg.errors.CheckViolation):
                connection.execute(
                    """
                    UPDATE historical_coverage_cells
                    SET status = 'not_published',
                        assessed_at = now(),
                        review_ref = 'review://historical-coverage/tainan/2026',
                        status_reason = 'No official publication was found.',
                        updated_at = now()
                    WHERE jurisdiction_code = '67000000'
                      AND coverage_year = 2026
                    """
                )
            connection.rollback()

            connection.execute(
                """
                UPDATE historical_coverage_cells
                SET status = 'official_checked_empty',
                    checked_source_count = 1,
                    successful_source_count = 1,
                    source_adapter_keys = ARRAY['official.wra.flood_incident'],
                    assessed_at = now(),
                    last_attempted_at = now(),
                    last_succeeded_at = now(),
                    review_ref = 'review://historical-coverage/tainan/2026',
                    status_reason = 'Reviewed source completed with zero event rows.',
                    updated_at = now()
                WHERE jurisdiction_code = '67000000'
                  AND coverage_year = 2026
                """
            )
            connection.commit()
            assert connection.execute(
                """
                SELECT status, record_count, checked_source_count,
                       successful_source_count
                FROM historical_coverage_cells
                WHERE jurisdiction_code = '67000000'
                  AND coverage_year = 2026
                """
            ).fetchone() == ("official_checked_empty", 0, 1, 1)
