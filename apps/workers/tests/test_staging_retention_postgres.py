"""PostGIS acceptance for the bounded staging_evidence retention passes.

Runs against a live PostGIS in an isolated schema so the delete can be
observed for real without touching a shared development dataset. Skips when
``EVIDENCE_TEST_DATABASE_URL`` is absent, and fails instead of skipping when
``OFFICIAL_DB_ACCEPTANCE_REQUIRED=1``.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from app.jobs import evidence_retention
from app.jobs.evidence_retention import (
    STAGING_EVIDENCE_ACCEPTED_INDEX,
    STAGING_EVIDENCE_REJECTED_INDEX,
    PostgresEvidenceRetentionJob,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from infra.scripts.apply_migrations import apply_migrations  # noqa: E402

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
AGED_REJECTED_ROWS = 20_000
RECENT_REJECTED_ROWS = 1_000
# The orphan population the accepted pass exists for: promoted realtime
# telemetry whose evidence row the 48 h realtime prune already deleted.
ORPHAN_ACCEPTED_ROWS = 20_000
REFERENCED_ACCEPTED_ROWS = 500
RECENT_ACCEPTED_ROWS = 500
HISTORICAL_ACCEPTED_ROWS = 500
UNSOURCED_ACCEPTED_ROWS = 500
# The production budget. A batch that cannot finish inside it deletes nothing.
PRODUCTION_STATEMENT_TIMEOUT_MS = 5_000

# The survivor prefix that made the first shape of this pass quadratic: rows
# an evidence row still references stay at the head of the accepted index
# forever, so an unwindowed batch re-probes all of them before it reaches a
# single new orphan. Seeded in the oldest hour, with the orphans behind it.
SURVIVOR_PREFIX_ROWS = 50_000
SWEEP_ORPHAN_ROWS = 12_000
SWEEP_ORIGIN = datetime(2026, 8, 1, tzinfo=UTC)
SWEEP_NOW = SWEEP_ORIGIN + timedelta(days=14)

REALTIME_ADAPTER_KEY = "official.cwa.rainfall"
HISTORICAL_ADAPTER_KEY = "official.nstc.flood_disaster_points"

# Everything the accepted pass must leave behind, whatever it deletes.
SURVIVING_ACCEPTED = {
    "referenced-accepted": REFERENCED_ACCEPTED_ROWS,
    "recent-accepted": RECENT_ACCEPTED_ROWS,
    "historical-accepted": HISTORICAL_ACCEPTED_ROWS,
    "unsourced-accepted": UNSOURCED_ACCEPTED_ROWS,
}


@pytest.fixture(autouse=True)
def _reset_sweep_state() -> None:
    """The watermark is module level so it can outlive a maintenance cycle."""

    evidence_retention._accepted_sweep_watermark = None
    evidence_retention._accepted_sweep_window_seconds = None
    evidence_retention._accepted_fallback_adapter_keys = None
    evidence_retention._accepted_timeout_streak = 0
    evidence_retention._staging_timeout_streak = 0


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


def _source_id(connection: psycopg.Connection, adapter_key: str) -> str:
    """Resolve a seeded catalogue row rather than inventing one.

    The adapter keys come from the real ``data_sources`` seed migrations, so
    this also proves the job's classifier agrees with the shipped catalogue.
    """

    row = connection.execute(
        "SELECT id FROM data_sources WHERE adapter_key = %s", (adapter_key,)
    ).fetchone()
    assert row is not None, f"{adapter_key} is missing from the data_sources seed"
    return str(row[0])


@pytest.fixture
def seeded_url(migrated_schema_url: str) -> Iterator[str]:
    """Reset staging_evidence, then insert the populations under test."""

    with psycopg.connect(migrated_schema_url) as connection:
        connection.execute("TRUNCATE staging_evidence CASCADE")
        connection.execute("DELETE FROM evidence WHERE properties ? 'staging_evidence_id'")
        realtime_source_id = _source_id(connection, REALTIME_ADAPTER_KEY)
        historical_source_id = _source_id(connection, HISTORICAL_ADAPTER_KEY)

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
        # (a) The orphans: promoted realtime telemetry whose evidence row the
        # 48 h realtime prune already deleted. Nothing can read these again.
        connection.execute(
            """
            INSERT INTO staging_evidence (
                data_source_id, source_id, source_type, event_type, title,
                summary, validation_status, created_at
            )
            SELECT
                %s,
                'orphan-accepted-' || generated,
                'official',
                'rainfall',
                'aged accepted staging row with no evidence left',
                'promoted, then the evidence row aged out at 48 h',
                'accepted',
                %s
            FROM generate_series(1, %s) AS generated
            """,
            (realtime_source_id, NOW - timedelta(days=8), ORPHAN_ACCEPTED_ROWS),
        )
        # (b) Aged accepted rows an evidence row still points at.
        connection.execute(
            """
            INSERT INTO staging_evidence (
                data_source_id, source_id, source_type, event_type, title,
                summary, validation_status, created_at
            )
            SELECT
                %s,
                'referenced-accepted-' || generated,
                'official',
                'flood_report',
                'aged accepted staging row still referenced',
                'its evidence row is retained, so the audit row must stay',
                'accepted',
                %s
            FROM generate_series(1, %s) AS generated
            """,
            (realtime_source_id, NOW - timedelta(days=8), REFERENCED_ACCEPTED_ROWS),
        )
        connection.execute(
            """
            INSERT INTO evidence (
                data_source_id, source_id, source_type, event_type, title,
                summary, confidence, properties
            )
            SELECT
                staging.data_source_id,
                staging.source_id,
                'official',
                'flood_report',
                'promoted evidence',
                'still inside its own retention window',
                0.8,
                jsonb_build_object('staging_evidence_id', staging.id::text)
            FROM staging_evidence staging
            WHERE staging.source_id LIKE 'referenced-accepted-%%'
            """
        )
        # (c) Accepted but inside the retention window.
        connection.execute(
            """
            INSERT INTO staging_evidence (
                data_source_id, source_id, source_type, event_type, title,
                summary, validation_status, created_at
            )
            SELECT
                %s,
                'recent-accepted-' || generated,
                'official',
                'rainfall',
                'recent accepted staging row',
                'may still be promoted',
                'accepted',
                %s
            FROM generate_series(1, %s) AS generated
            """,
            (realtime_source_id, NOW - timedelta(days=1), RECENT_ACCEPTED_ROWS),
        )
        # (d) Aged, unreferenced -- but historical_coverage.py reads these.
        connection.execute(
            """
            INSERT INTO staging_evidence (
                data_source_id, source_id, source_type, event_type, title,
                summary, validation_status, occurred_at, created_at
            )
            SELECT
                %s,
                'historical-accepted-' || generated,
                'official',
                'flood_report',
                'aged accepted historical staging row',
                'historical_coverage.py rebuilds county/year coverage from these',
                'accepted',
                %s,
                %s
            FROM generate_series(1, %s) AS generated
            """,
            (
                historical_source_id,
                NOW - timedelta(days=900),
                NOW - timedelta(days=8),
                HISTORICAL_ACCEPTED_ROWS,
            ),
        )
        # (e) Aged and unreferenced with no data_source_id at all: unclassifiable,
        # so never eligible.
        connection.execute(
            """
            INSERT INTO staging_evidence (
                source_id, source_type, event_type, title, summary,
                validation_status, created_at
            )
            SELECT
                'unsourced-accepted-' || generated,
                'official',
                'rainfall',
                'aged accepted staging row with no data source',
                'cannot be classified, so cannot be pruned',
                'accepted',
                %s
            FROM generate_series(1, %s) AS generated
            """,
            (NOW - timedelta(days=8), UNSOURCED_ACCEPTED_ROWS),
        )
        connection.commit()
        connection.execute("ANALYZE staging_evidence")
        connection.execute("ANALYZE evidence")
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


def _seeded_populations() -> dict[str, int]:
    return {
        "aged-rejected": AGED_REJECTED_ROWS,
        "recent-rejected": RECENT_REJECTED_ROWS,
        "orphan-accepted": ORPHAN_ACCEPTED_ROWS,
        **SURVIVING_ACCEPTED,
    }


def _rows_removed_by_filter(plan_text: str) -> int:
    """Total rows the index scan read and threw away -- the cost that used
    to grow without bound as the survivor prefix grew.
    """

    return sum(
        int(match)
        for match in re.findall(r"Rows Removed by Filter: (\d+)", plan_text)
    )


def _explain_accepted_candidates(
    database_url: str,
    *,
    window_start: datetime | None,
    window_end: datetime,
    batch_size: int = 5_000,
) -> str:
    """EXPLAIN the candidate select a batch issues, windowed or not.

    ``window_start=None`` reproduces the unwindowed shape this pass shipped
    with before #381, which is the regression the numbers below pin down.
    """

    window_clause = (
        "AND s.created_at >= %(window_start)s::timestamptz"
        if window_start is not None
        else ""
    )
    with psycopg.connect(database_url) as connection:
        source_id = _source_id(connection, REALTIME_ADAPTER_KEY)
        plan = connection.execute(
            f"""
            EXPLAIN (ANALYZE, BUFFERS)
            SELECT s.id
            FROM staging_evidence s
            WHERE s.validation_status = 'accepted'
                {window_clause}
                AND s.created_at < %(window_end)s::timestamptz
                AND s.data_source_id = ANY(%(source_ids)s::uuid[])
                AND NOT EXISTS (
                    SELECT 1
                    FROM evidence e
                    WHERE e.properties ? 'staging_evidence_id'
                        AND e.properties ->> 'staging_evidence_id' = s.id::text
                    OFFSET 0
                )
            ORDER BY s.created_at ASC
            LIMIT %(batch_size)s
            """,
            {
                "window_start": window_start,
                "window_end": window_end,
                "source_ids": [source_id],
                "batch_size": batch_size,
            },
        ).fetchall()
    return "\n".join(str(line[0]) for line in plan)


def _job(database_url: str) -> PostgresEvidenceRetentionJob:
    return PostgresEvidenceRetentionJob(
        connection_factory=lambda: psycopg.connect(database_url, connect_timeout=10)
    )


def _index_is_valid(database_url: str, index_name: str) -> bool:
    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            """
            SELECT idx.indisvalid
            FROM pg_class cls
            JOIN pg_index idx ON idx.indexrelid = cls.oid
            WHERE cls.relname = %s
                AND cls.relnamespace = current_schema()::regnamespace
            """,
            (index_name,),
        ).fetchone()
    return bool(row and row[0])


def test_prune_staging_evidence_clears_aged_rejected_rows_only(seeded_url: str) -> None:
    assert _populations(seeded_url) == _seeded_populations()

    # 4 batches x 5 000 rows clears the 20 000 aged rejected rows; the fifth
    # batch deletes nothing, which is how the pass learns it is done.
    summary = _job(seeded_url).prune_staging_evidence(
        retention_days=7,
        batch_size=5_000,
        max_batches=10,
        statement_timeout_ms=30_000,
        accepted_enabled=False,
        now=NOW,
    )

    assert summary.index_state == "ready"
    assert summary.deleted_rows == AGED_REJECTED_ROWS
    assert summary.batches == 5
    assert summary.stopped_reason == "exhausted"
    assert summary.accepted_stopped_reason == "disabled"
    expected = _seeded_populations()
    del expected["aged-rejected"]
    assert _populations(seeded_url) == expected


def test_prune_staging_evidence_honours_the_per_cycle_batch_ceiling(
    seeded_url: str,
) -> None:
    summary = _job(seeded_url).prune_staging_evidence(
        retention_days=7,
        batch_size=1_000,
        max_batches=3,
        statement_timeout_ms=30_000,
        accepted_enabled=False,
        now=NOW,
    )

    assert summary.deleted_rows == 3_000
    assert summary.batches == 3
    assert summary.stopped_reason == "max_batches"
    assert _populations(seeded_url) == {
        **_seeded_populations(),
        "aged-rejected": AGED_REJECTED_ROWS - 3_000,
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
        accepted_enabled=False,
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
    assert _index_is_valid(seeded_url, STAGING_EVIDENCE_REJECTED_INDEX) is False

    summary = _job(seeded_url).prune_staging_evidence(
        retention_days=7,
        batch_size=1_000,
        max_batches=1,
        accepted_enabled=False,
        now=NOW,
    )

    assert summary.index_state == "ready"
    assert _index_is_valid(seeded_url, STAGING_EVIDENCE_REJECTED_INDEX) is True
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
    assert _index_is_valid(seeded_url, STAGING_EVIDENCE_REJECTED_INDEX) is False

    summary = _job(seeded_url).prune_staging_evidence(
        retention_days=7,
        batch_size=1_000,
        max_batches=1,
        accepted_enabled=False,
        now=NOW,
    )

    assert summary.index_state == "ready"
    assert _index_is_valid(seeded_url, STAGING_EVIDENCE_REJECTED_INDEX) is True
    assert summary.deleted_rows == 1_000


# --------------------------------------------------------------------------
# The accepted-orphan pass (#372).
# --------------------------------------------------------------------------


def test_prune_staging_evidence_clears_orphaned_accepted_rows_only(
    seeded_url: str,
) -> None:
    """(a) goes; (b), (c), (d) and (e) stay."""

    summary = _job(seeded_url).prune_staging_evidence(
        retention_days=7,
        batch_size=5_000,
        max_batches=10,
        accepted_max_batches=10,
        # The whole seeded span in one window, so this test stays about which
        # rows go and which stay; window sizing has its own tests below.
        accepted_window_seconds=30 * 24 * 3_600,
        statement_timeout_ms=30_000,
        now=NOW,
    )

    assert summary.accepted_index_state == "ready"
    assert summary.accepted_deleted_rows == ORPHAN_ACCEPTED_ROWS
    assert summary.accepted_stopped_reason == "caught_up"
    assert summary.accepted_source_count > 0
    # Both passes run in one cycle, so the rejected backlog goes as well.
    assert summary.deleted_rows == AGED_REJECTED_ROWS
    assert _populations(seeded_url) == {
        "recent-rejected": RECENT_REJECTED_ROWS,
        **SURVIVING_ACCEPTED,
    }

    # Spelled out: an accepted row an evidence row still points at is the one
    # deletion that would break promotion idempotency.
    with psycopg.connect(seeded_url) as connection:
        dangling = connection.execute(
            """
            SELECT count(*)::integer
            FROM evidence e
            WHERE e.properties ? 'staging_evidence_id'
                AND NOT EXISTS (
                    SELECT 1
                    FROM staging_evidence s
                    WHERE s.id::text = e.properties ->> 'staging_evidence_id'
                )
            """
        ).fetchone()
    assert dangling is not None
    assert dangling[0] == 0


def test_prune_staging_evidence_accepted_pass_honours_its_own_batch_ceiling(
    seeded_url: str,
) -> None:
    summary = _job(seeded_url).prune_staging_evidence(
        retention_days=7,
        batch_size=1_000,
        max_batches=1,
        accepted_max_batches=3,
        statement_timeout_ms=30_000,
        now=NOW,
    )

    assert summary.deleted_rows == 1_000
    assert summary.accepted_deleted_rows == 3_000
    assert summary.accepted_batches == 3
    assert summary.accepted_stopped_reason == "max_batches"
    assert _populations(seeded_url) == {
        **_seeded_populations(),
        "aged-rejected": AGED_REJECTED_ROWS - 1_000,
        "orphan-accepted": ORPHAN_ACCEPTED_ROWS - 3_000,
    }


def test_prune_staging_evidence_accepted_pass_fits_the_production_budget(
    seeded_url: str,
) -> None:
    """The orphan batch probes evidence per row, so time it under the real budget."""

    started_at = monotonic()
    summary = _job(seeded_url).prune_staging_evidence(
        retention_days=7,
        batch_size=5_000,
        max_batches=1,
        accepted_max_batches=4,
        statement_timeout_ms=PRODUCTION_STATEMENT_TIMEOUT_MS,
        now=NOW,
    )
    elapsed_seconds = monotonic() - started_at

    assert summary.accepted_stopped_reason == "max_batches"
    assert summary.accepted_deleted_rows == ORPHAN_ACCEPTED_ROWS
    assert summary.accepted_batches == 4
    per_batch_seconds = elapsed_seconds / (summary.batches + summary.accepted_batches)
    print(
        f"staging_accepted_retention_batches elapsed_seconds={elapsed_seconds:.3f} "
        f"per_batch_seconds={per_batch_seconds:.3f}"
    )
    assert per_batch_seconds < 1.0
    assert elapsed_seconds < PRODUCTION_STATEMENT_TIMEOUT_MS / 1000


def test_prune_staging_evidence_builds_the_accepted_partial_index_concurrently(
    seeded_url: str,
) -> None:
    with psycopg.connect(seeded_url, autocommit=True) as connection:
        connection.execute(
            sql.SQL("DROP INDEX IF EXISTS {}").format(
                sql.Identifier(STAGING_EVIDENCE_ACCEPTED_INDEX)
            )
        )
    assert _index_is_valid(seeded_url, STAGING_EVIDENCE_ACCEPTED_INDEX) is False

    summary = _job(seeded_url).prune_staging_evidence(
        retention_days=7,
        batch_size=1_000,
        max_batches=1,
        accepted_max_batches=1,
        now=NOW,
    )

    assert summary.accepted_index_state == "ready"
    assert _index_is_valid(seeded_url, STAGING_EVIDENCE_ACCEPTED_INDEX) is True
    assert summary.accepted_deleted_rows == 1_000

    # Both indexes have to be in the plan: the accepted partial index to find
    # aged rows in created_at order, and 0042 to answer the NOT EXISTS probe
    # without scanning evidence.
    with psycopg.connect(seeded_url) as connection:
        source_id = _source_id(connection, REALTIME_ADAPTER_KEY)
        plan = connection.execute(
            """
            EXPLAIN (FORMAT TEXT)
            SELECT s.id
            FROM staging_evidence s
            WHERE s.validation_status = 'accepted'
                AND s.created_at < %s::timestamptz
                AND s.data_source_id = ANY(%s::uuid[])
                AND NOT EXISTS (
                    SELECT 1
                    FROM evidence e
                    WHERE e.properties ? 'staging_evidence_id'
                        AND e.properties ->> 'staging_evidence_id' = s.id::text
                    OFFSET 0
                )
            ORDER BY s.created_at ASC
            LIMIT 5000
            """,
            (NOW - timedelta(days=7), [source_id]),
        ).fetchall()
    plan_text = "\n".join(str(line[0]) for line in plan)
    assert STAGING_EVIDENCE_ACCEPTED_INDEX in plan_text, plan_text
    assert "idx_evidence_staging_evidence_id" in plan_text, plan_text
    # What the OFFSET 0 fence buys: the NOT EXISTS stays a per-row SubPlan
    # probe, so a batch costs (rows in window) x (one index probe) and the
    # window sizing in _sweep_accepted_staging can reason about it. Pulled
    # up into an anti-join it would still be correct and still use the same
    # index, but its cost would depend on the join strategy and on how many
    # parallel workers happen to be free.
    assert "SubPlan" in plan_text, plan_text


def test_prune_staging_evidence_accepted_pass_can_be_switched_off(
    seeded_url: str,
) -> None:
    summary = _job(seeded_url).prune_staging_evidence(
        retention_days=7,
        batch_size=1_000,
        max_batches=1,
        accepted_enabled=False,
        now=NOW,
    )

    assert summary.accepted_stopped_reason == "disabled"
    assert summary.accepted_deleted_rows == 0
    assert _populations(seeded_url) == {
        **_seeded_populations(),
        "aged-rejected": AGED_REJECTED_ROWS - 1_000,
    }


# --------------------------------------------------------------------------
# The watermark sweep (#381 review).
# --------------------------------------------------------------------------


@pytest.fixture
def swept_url(migrated_schema_url: str) -> Iterator[str]:
    """A survivor prefix in the oldest hour, with the orphans behind it.

    This is the shape that made the first version of the accepted pass
    quadratic: referenced rows are never deleted, so they stay at the head of
    the accepted index and every unwindowed batch re-probes all of them.
    """

    with psycopg.connect(migrated_schema_url) as connection:
        connection.execute("TRUNCATE staging_evidence CASCADE")
        connection.execute("DELETE FROM evidence WHERE properties ? 'staging_evidence_id'")
        realtime_source_id = _source_id(connection, REALTIME_ADAPTER_KEY)

        connection.execute(
            """
            INSERT INTO staging_evidence (
                data_source_id, source_id, source_type, event_type, title,
                summary, validation_status, created_at
            )
            SELECT
                %s,
                'survivor-accepted-' || generated,
                'official', 'flood_report', 'referenced accepted staging row',
                'its evidence row is retained, so this stays forever',
                'accepted',
                %s
            FROM generate_series(1, %s) AS generated
            """,
            (realtime_source_id, SWEEP_ORIGIN, SURVIVOR_PREFIX_ROWS),
        )
        connection.execute(
            """
            INSERT INTO evidence (
                data_source_id, source_id, source_type, event_type, title,
                summary, confidence, properties
            )
            SELECT
                staging.data_source_id, staging.source_id, 'official',
                'flood_report', 'promoted evidence', 'retained', 0.8,
                jsonb_build_object('staging_evidence_id', staging.id::text)
            FROM staging_evidence staging
            WHERE staging.source_id LIKE 'survivor-accepted-%%'
            """
        )
        # The orphans sit one hour later, i.e. in the window after the one the
        # survivors occupy.
        connection.execute(
            """
            INSERT INTO staging_evidence (
                data_source_id, source_id, source_type, event_type, title,
                summary, validation_status, created_at
            )
            SELECT
                %s,
                'sweep-orphan-' || generated,
                'official', 'rainfall', 'aged accepted orphan',
                'promoted, then the evidence row aged out at 48 h',
                'accepted',
                %s
            FROM generate_series(1, %s) AS generated
            """,
            (realtime_source_id, SWEEP_ORIGIN + timedelta(hours=1), SWEEP_ORPHAN_ROWS),
        )
        connection.commit()
    with psycopg.connect(migrated_schema_url, autocommit=True) as connection:
        connection.execute("VACUUM (ANALYZE) staging_evidence")
        connection.execute("VACUUM (ANALYZE) evidence")
    yield migrated_schema_url


def test_accepted_sweep_does_not_rescan_the_survivor_prefix(swept_url: str) -> None:
    """The regression that made this pass unshippable, pinned with a number.

    One batch pays for the survivor window once. After that the watermark is
    past it, and every later batch reads only its own window -- where the old
    unwindowed shape re-read all SURVIVOR_PREFIX_ROWS survivors on every batch,
    forever, with the prefix growing as the sweep advanced.
    """

    summary = _job(swept_url).prune_staging_evidence(
        retention_days=7,
        batch_size=5_000,
        max_batches=1,
        accepted_max_batches=1,
        accepted_window_seconds=3_600,
        statement_timeout_ms=30_000,
        now=SWEEP_NOW,
    )

    # The first batch swept the survivor window and deleted nothing from it.
    assert summary.accepted_deleted_rows == 0
    assert summary.accepted_watermark == SWEEP_ORIGIN + timedelta(hours=1)

    windowed = _explain_accepted_candidates(
        swept_url,
        window_start=summary.accepted_watermark,
        window_end=summary.accepted_watermark + timedelta(hours=1),
    )
    unwindowed = _explain_accepted_candidates(
        swept_url,
        window_start=None,
        window_end=SWEEP_NOW - timedelta(days=7),
    )
    windowed_discarded = _rows_removed_by_filter(windowed)
    unwindowed_discarded = _rows_removed_by_filter(unwindowed)
    print(
        "accepted_sweep_rows_removed_by_filter "
        f"windowed={windowed_discarded} unwindowed={unwindowed_discarded} "
        f"survivors={SURVIVOR_PREFIX_ROWS}"
    )

    # The unwindowed shape has to walk every survivor to reach an orphan.
    assert unwindowed_discarded >= SURVIVOR_PREFIX_ROWS
    # The windowed one reads only its own window, which holds no survivors.
    assert windowed_discarded < SURVIVOR_PREFIX_ROWS // 10
    assert STAGING_EVIDENCE_ACCEPTED_INDEX in windowed, windowed


def test_accepted_sweep_holds_the_watermark_while_a_window_still_has_orphans(
    swept_url: str,
) -> None:
    summary = _job(swept_url).prune_staging_evidence(
        retention_days=7,
        batch_size=5_000,
        max_batches=1,
        # One batch for the survivor window, two full batches of orphans.
        accepted_max_batches=3,
        accepted_window_seconds=3_600,
        statement_timeout_ms=30_000,
        now=SWEEP_NOW,
    )

    orphan_window_start = SWEEP_ORIGIN + timedelta(hours=1)
    assert summary.accepted_deleted_rows == 10_000
    assert summary.accepted_batches == 3
    # Both orphan batches were full, so the window is not finished and the
    # watermark has not moved past it.
    assert summary.accepted_watermark == orphan_window_start

    # The next cycle resumes inside the same window and finishes it.
    summary = _job(swept_url).prune_staging_evidence(
        retention_days=7,
        batch_size=5_000,
        max_batches=1,
        accepted_max_batches=1,
        accepted_window_seconds=3_600,
        statement_timeout_ms=30_000,
        now=SWEEP_NOW,
    )
    assert summary.accepted_deleted_rows == SWEEP_ORPHAN_ROWS - 10_000
    assert summary.accepted_watermark == orphan_window_start + timedelta(hours=1)
    with psycopg.connect(swept_url) as connection:
        remaining = connection.execute(
            "SELECT count(*)::integer FROM staging_evidence "
            "WHERE source_id LIKE 'sweep-orphan-%'"
        ).fetchone()
    assert remaining is not None
    assert remaining[0] == 0


def test_accepted_sweep_reports_caught_up_once_the_watermark_reaches_the_cutoff(
    swept_url: str,
) -> None:
    summary = _job(swept_url).prune_staging_evidence(
        retention_days=7,
        batch_size=5_000,
        max_batches=1,
        accepted_max_batches=100,
        # One window covers everything from the oldest row to the cutoff.
        accepted_window_seconds=30 * 24 * 3_600,
        statement_timeout_ms=30_000,
        now=SWEEP_NOW,
    )

    assert summary.accepted_stopped_reason == "caught_up"
    assert summary.accepted_deleted_rows == SWEEP_ORPHAN_ROWS
    assert summary.accepted_watermark == SWEEP_NOW - timedelta(days=7)
    # Steady state: a caught-up cycle issues no DELETE at all.
    summary = _job(swept_url).prune_staging_evidence(
        retention_days=7,
        max_batches=1,
        accepted_max_batches=100,
        accepted_window_seconds=30 * 24 * 3_600,
        now=SWEEP_NOW,
    )
    assert summary.accepted_stopped_reason == "caught_up"
    assert summary.accepted_batches == 0


def test_accepted_sweep_halves_the_window_on_a_real_statement_timeout(
    swept_url: str,
) -> None:
    """A 1 ms budget cannot finish any batch, so the window shrinks to the floor.

    Proves the retry path against a real cancelled statement rather than a
    synthetic sqlstate: the pass must roll back, shrink, retry and finally
    report the timeout instead of raising or looping.

    The 1 ms budget applies to the batch DELETEs only. The sweep's two
    setup reads carry STAGING_EVIDENCE_METADATA_STATEMENT_TIMEOUT_MS, so a
    slow runner cannot turn this into a preamble timeout and a green-looking
    but meaningless pass -- which is what it would have done when both
    shared one budget.
    """

    summary = _job(swept_url).prune_staging_evidence(
        retention_days=7,
        batch_size=5_000,
        max_batches=1,
        accepted_max_batches=10,
        accepted_window_seconds=1_200,
        accepted_min_window_seconds=300,
        statement_timeout_ms=1,
        now=SWEEP_NOW,
    )

    # 1200 -> 600 -> 300 -> give up: three attempts, and the watermark stays
    # where it was so the next cycle retries the same ground.
    assert summary.accepted_stopped_reason == "statement_timeout"
    assert summary.accepted_batches == 3
    assert summary.accepted_window_seconds == 300
    assert summary.accepted_watermark == SWEEP_ORIGIN
    assert summary.accepted_deleted_rows == 0
    # The setup reads got through on their own budget, which is how the
    # sweep reached a batch at all: source_count is only ever non-zero
    # once the data_sources read has committed.
    assert summary.accepted_source_count > 0
