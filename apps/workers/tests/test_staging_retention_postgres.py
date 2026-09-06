"""PostGIS acceptance for the bounded staging_evidence retention pass.

Runs against a live PostGIS in an isolated schema so the delete can be
observed for real without touching a shared development dataset. Skips when
``EVIDENCE_TEST_DATABASE_URL`` is absent, and fails instead of skipping when
``OFFICIAL_DB_ACCEPTANCE_REQUIRED=1``.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from app.jobs.evidence_retention import (
    STAGING_EVIDENCE_REJECTED_INDEX,
    PostgresEvidenceRetentionJob,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from infra.scripts.apply_migrations import apply_migrations  # noqa: E402

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
AGED_REJECTED_ROWS = 20_000
AGED_ACCEPTED_ROWS = 1_000
RECENT_REJECTED_ROWS = 1_000
# The production budget. A batch that cannot finish inside it deletes nothing.
PRODUCTION_STATEMENT_TIMEOUT_MS = 5_000


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


@pytest.fixture(scope="module")
def migrated_schema_url() -> Iterator[str]:
    """A throwaway schema with the full migration set applied once."""

    database_url = _database_url()
    schema_name = f"staging_retention_{uuid4().hex}"
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
    connection_info = psycopg.conninfo.conninfo_to_dict(database_url)
    existing_options = connection_info.get("options", "")
    connection_info["options"] = (
        f"{existing_options} -c search_path={schema_name},public".strip()
    )
    isolated_url = psycopg.conninfo.make_conninfo(**connection_info)
    try:
        apply_migrations(database_url=isolated_url)
        yield isolated_url
    finally:
        with psycopg.connect(database_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )


@pytest.fixture
def seeded_url(migrated_schema_url: str) -> Iterator[str]:
    """Reset staging_evidence, then insert the three populations under test."""

    with psycopg.connect(migrated_schema_url) as connection:
        connection.execute("TRUNCATE staging_evidence CASCADE")
        connection.execute(
            """
            INSERT INTO staging_evidence (
                source_id, source_type, event_type, title, summary,
                validation_status, rejection_reason, created_at
            )
            SELECT
                'aged-rejected-' || generated,
                'official',
                'rainfall',
                'aged rejected staging row',
                'promotion settled this observation as unchanged',
                'rejected',
                'idempotent_existing_observation',
                %s
            FROM generate_series(1, %s) AS generated
            """,
            (NOW - timedelta(days=8), AGED_REJECTED_ROWS),
        )
        connection.execute(
            """
            INSERT INTO staging_evidence (
                source_id, source_type, event_type, title, summary,
                validation_status, created_at
            )
            SELECT
                'aged-accepted-' || generated,
                'official',
                'flood_report',
                'aged accepted staging row',
                'still readable by promotion and historical coverage',
                'accepted',
                %s
            FROM generate_series(1, %s) AS generated
            """,
            (NOW - timedelta(days=8), AGED_ACCEPTED_ROWS),
        )
        connection.execute(
            """
            INSERT INTO staging_evidence (
                source_id, source_type, event_type, title, summary,
                validation_status, rejection_reason, created_at
            )
            SELECT
                'recent-rejected-' || generated,
                'official',
                'rainfall',
                'recent rejected staging row',
                'inside the retention window',
                'rejected',
                'idempotent_existing_observation',
                %s
            FROM generate_series(1, %s) AS generated
            """,
            (NOW - timedelta(days=1), RECENT_REJECTED_ROWS),
        )
        connection.commit()
        connection.execute("ANALYZE staging_evidence")
    yield migrated_schema_url


def _populations(database_url: str) -> dict[str, int]:
    with psycopg.connect(database_url) as connection:
        rows = connection.execute(
            """
            SELECT
                split_part(source_id, '-', 1) || '-' || split_part(source_id, '-', 2)
                    AS population,
                count(*)::integer
            FROM staging_evidence
            GROUP BY 1
            """
        ).fetchall()
    return {str(population): int(count) for population, count in rows}


def _job(database_url: str) -> PostgresEvidenceRetentionJob:
    return PostgresEvidenceRetentionJob(
        connection_factory=lambda: psycopg.connect(database_url, connect_timeout=10)
    )


def _index_is_valid(database_url: str) -> bool:
    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            """
            SELECT idx.indisvalid
            FROM pg_class cls
            JOIN pg_index idx ON idx.indexrelid = cls.oid
            WHERE cls.relname = %s
            """,
            (STAGING_EVIDENCE_REJECTED_INDEX,),
        ).fetchone()
    return bool(row and row[0])


def test_prune_staging_evidence_clears_aged_rejected_rows_only(seeded_url: str) -> None:
    assert _populations(seeded_url) == {
        "aged-rejected": AGED_REJECTED_ROWS,
        "aged-accepted": AGED_ACCEPTED_ROWS,
        "recent-rejected": RECENT_REJECTED_ROWS,
    }

    # 4 batches x 5 000 rows clears the 20 000 aged rejected rows; the fifth
    # batch deletes nothing, which is how the pass learns it is done.
    summary = _job(seeded_url).prune_staging_evidence(
        retention_days=7,
        batch_size=5_000,
        max_batches=10,
        statement_timeout_ms=30_000,
        now=NOW,
    )

    assert summary.index_state == "ready"
    assert summary.deleted_rows == AGED_REJECTED_ROWS
    assert summary.batches == 5
    assert summary.stopped_reason == "exhausted"
    assert _populations(seeded_url) == {
        "aged-accepted": AGED_ACCEPTED_ROWS,
        "recent-rejected": RECENT_REJECTED_ROWS,
    }

    # Accepted rows are the promotion and historical-coverage read set, so
    # retention must never touch one however old it is.
    with psycopg.connect(seeded_url) as connection:
        untouched = connection.execute(
            """
            SELECT count(*)::integer
            FROM staging_evidence
            WHERE validation_status = 'accepted'
                AND created_at < %s
            """,
            (NOW - timedelta(days=7),),
        ).fetchone()
    assert untouched is not None
    assert untouched[0] == AGED_ACCEPTED_ROWS


def test_prune_staging_evidence_honours_the_per_cycle_batch_ceiling(
    seeded_url: str,
) -> None:
    summary = _job(seeded_url).prune_staging_evidence(
        retention_days=7,
        batch_size=1_000,
        max_batches=3,
        statement_timeout_ms=30_000,
        now=NOW,
    )

    assert summary.deleted_rows == 3_000
    assert summary.batches == 3
    assert summary.stopped_reason == "max_batches"
    assert _populations(seeded_url) == {
        "aged-rejected": AGED_REJECTED_ROWS - 3_000,
        "aged-accepted": AGED_ACCEPTED_ROWS,
        "recent-rejected": RECENT_REJECTED_ROWS,
    }


def test_prune_staging_evidence_fits_the_production_budget(seeded_url: str) -> None:
    """A backlog batch must finish well inside the real 5 s statement_timeout.

    The first shape of this job ordered by the uuid primary key, which is
    random heap I/O: the reviewer measured ~1.31 M buffers and 2.5 s per batch
    on 1 M rows, so on the hosted table the very first batch would be cancelled
    and nothing would ever be deleted. This runs the production budget for
    real, so that regression cannot come back unnoticed.
    """

    started_at = monotonic()
    summary = _job(seeded_url).prune_staging_evidence(
        retention_days=7,
        batch_size=5_000,
        max_batches=4,
        statement_timeout_ms=PRODUCTION_STATEMENT_TIMEOUT_MS,
        now=NOW,
    )
    elapsed_seconds = monotonic() - started_at

    assert summary.stopped_reason == "max_batches"
    assert summary.deleted_rows == AGED_REJECTED_ROWS
    assert summary.batches == 4
    per_batch_seconds = elapsed_seconds / summary.batches
    print(
        f"staging_retention_batches elapsed_seconds={elapsed_seconds:.3f} "
        f"per_batch_seconds={per_batch_seconds:.3f}"
    )
    # Four batches inside one budget is already proof no single batch came near
    # it, and it leaves room for a loaded CI runner.
    assert elapsed_seconds < PRODUCTION_STATEMENT_TIMEOUT_MS / 1000


def test_prune_staging_evidence_builds_its_partial_index_concurrently(
    seeded_url: str,
) -> None:
    with psycopg.connect(seeded_url, autocommit=True) as connection:
        connection.execute(
            sql.SQL("DROP INDEX IF EXISTS {}").format(
                sql.Identifier(STAGING_EVIDENCE_REJECTED_INDEX)
            )
        )
    assert _index_is_valid(seeded_url) is False

    summary = _job(seeded_url).prune_staging_evidence(
        retention_days=7, batch_size=1_000, max_batches=1, now=NOW
    )

    assert summary.index_state == "ready"
    assert _index_is_valid(seeded_url) is True
    assert summary.deleted_rows == 1_000
    # The index is the plan the batch select depends on, so assert the planner
    # actually chooses it rather than trusting that it exists.
    with psycopg.connect(seeded_url) as connection:
        plan = connection.execute(
            """
            EXPLAIN (FORMAT TEXT)
            SELECT id
            FROM staging_evidence
            WHERE validation_status = 'rejected'
                AND created_at < %s::timestamptz
            ORDER BY created_at ASC
            LIMIT 5000
            """,
            (NOW - timedelta(days=7),),
        ).fetchall()
    plan_text = "\n".join(str(line[0]) for line in plan)
    assert STAGING_EVIDENCE_REJECTED_INDEX in plan_text, plan_text


def test_prune_staging_evidence_rebuilds_an_invalid_index_before_deleting(
    seeded_url: str,
) -> None:
    """A build killed half way leaves an index the planner ignores.

    It also blocks CREATE INDEX ... IF NOT EXISTS from replacing it, so the job
    has to drop it first or it would never delete anything again.
    """

    with psycopg.connect(seeded_url, autocommit=True) as connection:
        connection.execute(
            sql.SQL("DROP INDEX IF EXISTS {}").format(
                sql.Identifier(STAGING_EVIDENCE_REJECTED_INDEX)
            )
        )
        connection.execute(
            sql.SQL(
                "CREATE INDEX {} ON staging_evidence (created_at) "
                "WHERE validation_status = 'rejected'"
            ).format(sql.Identifier(STAGING_EVIDENCE_REJECTED_INDEX))
        )
        connection.execute(
            """
            UPDATE pg_index
            SET indisvalid = false
            WHERE indexrelid = %s::regclass
            """,
            (STAGING_EVIDENCE_REJECTED_INDEX,),
        )
    assert _index_is_valid(seeded_url) is False

    summary = _job(seeded_url).prune_staging_evidence(
        retention_days=7, batch_size=1_000, max_batches=1, now=NOW
    )

    assert summary.index_state == "ready"
    assert _index_is_valid(seeded_url) is True
    assert summary.deleted_rows == 1_000
