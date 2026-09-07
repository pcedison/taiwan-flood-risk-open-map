"""PostGIS acceptance for the concurrent evidence index rebuild.

The unit suite proves the policy; this proves the premise. It reproduces the
hosted table's write pattern in an isolated schema -- insert a batch of
non-realtime point rows, delete most of them, repeat, never VACUUM -- and then
measures what the rebuild is supposed to buy: a smaller
``idx_evidence_nearby_non_realtime_geom`` and a bounding-box search that touches
fewer blocks.

Skips when ``EVIDENCE_TEST_DATABASE_URL`` is absent, and fails instead of
skipping when ``OFFICIAL_DB_ACCEPTANCE_REQUIRED=1``.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from app.jobs import index_maintenance
from app.jobs.index_maintenance import PostgresIndexMaintenanceJob

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from infra.scripts.apply_migrations import apply_migrations  # noqa: E402

TARGET_INDEX = "idx_evidence_nearby_non_realtime_geom"
CCNEW_INDEX = f"{TARGET_INDEX}_ccnew"

# Inside the production default window, so the acceptance runs the shipped
# policy rather than a test-only one. Time is injected, never read from the
# clock, so this is stable whenever CI happens to run.
IN_WINDOW = datetime(2026, 9, 7, 19, 0, tzinfo=UTC)
WINDOW_UTC = "18:00-21:00"
# Small enough that the fixture's index clears it; production uses 8 MiB.
TEST_MIN_SIZE_BYTES = 64 * 1024

CHURN_ROUNDS = 3
ROWS_PER_ROUND = 50_000
# Keep every tenth row: the realtime prune and the historical re-imports both
# delete the large majority of what they inserted.
KEEP_EVERY = 10  # rows whose source_id ends in "0"

# Taipei City Hall, the probe point the hosted diagnostics uses.
PROBE_LNG = 121.5645
PROBE_LAT = 25.0375
PROBE_RADIUS_M = 500
# query_nearby_evidence turns metres into degrees the same way.
DEGREES_PER_METRE = 1 / 90000.0
# Rows are scattered over a ~11 km box so a 500 m probe selects a slice
# comparable to the 168 candidate rows the hosted probe fetches.
SCATTER_DEGREES = 0.1


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
    schema_name = f"index_maintenance_{uuid4().hex}"
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name))
        )
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


@pytest.fixture(scope="module")
def churned_url(migrated_schema_url: str) -> str:
    """Bloat the partial GiST index the way live ingestion bloats it.

    Insert a batch, delete nine tenths of it, repeat. No VACUUM in between and
    none afterwards: an index page freed by a delete is never returned, and a
    GiST index grown one insert at a time ends up with heavily overlapping
    bounding boxes, which is exactly why a 500 m search on the hosted node
    reads 2 875 blocks to return 168 rows.
    """

    with psycopg.connect(migrated_schema_url) as connection:
        # Migration 0063 tunes autovacuum to run aggressively on this table.
        # Here it would be a race: an autovacuum landing mid-test clears the
        # dead index entries the measurement is about, so the before/after
        # numbers would depend on the daemon's timing rather than on the
        # rebuild. Freezing it makes the bloat reproducible; on the hosted node
        # autovacuum runs and the indexes stay large anyway, because it never
        # returns an index page.
        connection.execute("ALTER TABLE evidence SET (autovacuum_enabled = false)")
        connection.execute("TRUNCATE evidence CASCADE")
        connection.commit()
        for round_number in range(1, CHURN_ROUNDS + 1):
            connection.execute(
                """
                INSERT INTO evidence (
                    source_id, source_type, event_type, title, summary,
                    confidence, privacy_level, ingestion_status, geom,
                    observed_at
                )
                SELECT
                    'churn-' || %s || '-' || generated,
                    'official',
                    'flood_report',
                    'churn row',
                    'index bloat fixture',
                    0.5,
                    'public',
                    'accepted',
                    ST_SetSRID(
                        ST_MakePoint(
                            %s + (random() - 0.5) * %s,
                            %s + (random() - 0.5) * %s
                        ),
                        4326
                    ),
                    now()
                FROM generate_series(1, %s) AS generated
                """,
                (
                    round_number,
                    PROBE_LNG,
                    SCATTER_DEGREES,
                    PROBE_LAT,
                    SCATTER_DEGREES,
                    ROWS_PER_ROUND,
                ),
            )
            connection.commit()
            # generate_series ran 1..ROWS_PER_ROUND, so the rows whose source_id
            # ends in a zero are exactly every tenth one.
            connection.execute(
                """
                DELETE FROM evidence
                WHERE source_id LIKE %s
                    AND source_id NOT LIKE %s
                """,
                (f"churn-{round_number}-%", "%0"),
            )
            connection.commit()
        connection.execute("ANALYZE evidence")
        connection.commit()
    return migrated_schema_url


@pytest.fixture(autouse=True)
def _reset_module_schedule() -> None:
    index_maintenance._last_reindex_at.clear()
    index_maintenance._last_attempt_at.clear()


def _job(database_url: str) -> PostgresIndexMaintenanceJob:
    return PostgresIndexMaintenanceJob(
        connection_factory=lambda: psycopg.connect(database_url, connect_timeout=10)
    )


def _reindex(
    database_url: str,
    *,
    now: datetime = IN_WINDOW,
    lock_timeout_ms: int = 5_000,
) -> Any:
    return _job(database_url).reindex_evidence_indexes(
        index_names=(TARGET_INDEX,),
        window_utc=WINDOW_UTC,
        min_size_bytes=TEST_MIN_SIZE_BYTES,
        lock_timeout_ms=lock_timeout_ms,
        now=now,
    )


def _index_row(database_url: str, index_name: str) -> tuple[int, bool] | None:
    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            """
            SELECT pg_relation_size(cls.oid)::bigint, idx.indisvalid
            FROM pg_class cls
            JOIN pg_index idx ON idx.indexrelid = cls.oid
            WHERE cls.relname = %s
                AND cls.relnamespace = current_schema()::regnamespace
            """,
            (index_name,),
        ).fetchone()
    return (int(row[0]), bool(row[1])) if row is not None else None


def _bbox_scan(database_url: str) -> tuple[int, int, str]:
    """Run the nearby-evidence bounding-box probe and count the blocks it reads.

    This is the first branch of ``query_nearby_evidence`` reduced to the part
    the index answers: the partial index predicate plus the ``&&`` box. The
    join, the ``ST_DWithin`` refinement and the ordering are dropped because
    they are not what the rebuild changes.

    ``enable_seqscan`` is off so both measurements describe the same access
    path. Shared hits and reads are summed: the number of blocks the scan has
    to touch is the structural property under test, and whether one of them is
    already cached is not.
    """

    with psycopg.connect(database_url) as connection:
        connection.execute("SET enable_seqscan = off")
        plan = connection.execute(
            """
            EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
            SELECT count(*)
            FROM evidence e
            WHERE e.geom IS NOT NULL
                AND e.ingestion_status = 'accepted'
                AND e.privacy_level IN ('public', 'aggregated')
                AND NOT (
                    e.source_type = 'official'
                    AND e.event_type IN ('rainfall', 'water_level')
                )
                AND e.geom && ST_Expand(
                    ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                    %s * %s
                )
            """,
            (PROBE_LNG, PROBE_LAT, PROBE_RADIUS_M, DEGREES_PER_METRE),
        ).fetchone()
    assert plan is not None
    root = plan[0][0]["Plan"]
    return _sum_blocks(root), _rows_returned(root), _plan_text(root)


def _bbox_count(database_url: str) -> int:
    """The answer the probe returns, which a rebuild must not change."""

    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            """
            SELECT count(*)::integer
            FROM evidence e
            WHERE e.geom IS NOT NULL
                AND e.ingestion_status = 'accepted'
                AND e.privacy_level IN ('public', 'aggregated')
                AND NOT (
                    e.source_type = 'official'
                    AND e.event_type IN ('rainfall', 'water_level')
                )
                AND e.geom && ST_Expand(
                    ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                    %s * %s
                )
            """,
            (PROBE_LNG, PROBE_LAT, PROBE_RADIUS_M, DEGREES_PER_METRE),
        ).fetchone()
    assert row is not None
    return int(row[0])


def _sum_blocks(node: dict[str, Any]) -> int:
    total = int(node.get("Shared Hit Blocks", 0)) + int(
        node.get("Shared Read Blocks", 0)
    )
    for child in node.get("Plans", []):
        total += _sum_blocks(child)
    return total


def _rows_returned(node: dict[str, Any]) -> int:
    """Rows the index scan itself produced, not the rows the aggregate emits."""

    if "Index Scan" in str(node.get("Node Type", "")):
        return int(node.get("Actual Rows", 0))
    for child in node.get("Plans", []):
        rows = _rows_returned(child)
        if rows:
            return rows
    return 0


def _plan_text(node: dict[str, Any]) -> str:
    names = [str(node.get("Index Name", ""))] if node.get("Index Name") else []
    for child in node.get("Plans", []):
        names.append(_plan_text(child))
    return " ".join(name for name in names if name)


def test_reindex_shrinks_the_bloated_partial_gist_index(churned_url: str) -> None:
    before_blocks, before_rows, before_plan = _bbox_scan(churned_url)
    before_count = _bbox_count(churned_url)
    assert TARGET_INDEX in before_plan, (
        f"the probe must exercise {TARGET_INDEX}, got plan indexes: {before_plan}"
    )

    summary = _reindex(churned_url)

    after_blocks, after_rows, after_plan = _bbox_scan(churned_url)
    after_count = _bbox_count(churned_url)
    print(
        f"evidence_reindex index={TARGET_INDEX} "
        f"before_bytes={summary.before_bytes} after_bytes={summary.after_bytes} "
        f"elapsed_ms={summary.elapsed_ms} "
        f"bbox_blocks_before={before_blocks} bbox_blocks_after={after_blocks} "
        f"bbox_index_rows_before={before_rows} bbox_index_rows_after={after_rows} "
        f"bbox_matching_rows={after_count}"
    )

    assert summary.outcome == "reindexed"
    assert summary.index == TARGET_INDEX
    assert summary.before_bytes is not None and summary.after_bytes is not None
    # A margin, not a hairline: the rebuilt index holds only the surviving
    # tenth of the entries, so anything close to the old size means the
    # rebuild did not really happen.
    assert summary.after_bytes * 2 < summary.before_bytes

    rebuilt = _index_row(churned_url, TARGET_INDEX)
    assert rebuilt is not None
    rebuilt_size, rebuilt_valid = rebuilt
    # A rebuild that leaves the index invalid is worse than no rebuild: the
    # planner stops using it and the read path falls back to a seq scan.
    assert rebuilt_valid is True
    assert rebuilt_size == summary.after_bytes
    # Nothing transient survives a successful rebuild.
    assert _index_row(churned_url, CCNEW_INDEX) is None

    # The point of the exercise: the same bounding box, the same answer, from
    # fewer pages.
    assert after_plan == before_plan
    assert after_count == before_count > 0
    assert after_blocks * 2 < before_blocks
    # And the scan stops handing the heap entries that point at rows the
    # retention pass deleted long ago -- the hosted symptom, where 168 live
    # candidate rows cost 2 875 blocks.
    assert after_rows * 2 < before_rows
    # An index scan can over-return (dead entries the heap then rejects); it
    # can never under-return.
    assert after_rows >= after_count


def test_reindex_reports_a_refused_lock_and_leaves_the_index_usable(
    churned_url: str,
) -> None:
    """A rebuild must never queue behind ingestion; it gives up instead."""

    blocker = psycopg.connect(churned_url)
    try:
        # SHARE conflicts with the SHARE UPDATE EXCLUSIVE that REINDEX
        # CONCURRENTLY needs, so the rebuild cannot start.
        blocker.execute("LOCK TABLE evidence IN SHARE MODE")
        summary = _reindex(churned_url, lock_timeout_ms=500)
    finally:
        blocker.rollback()
        blocker.close()

    assert summary.outcome == "failed:55P03"
    assert summary.index == TARGET_INDEX

    still_there = _index_row(churned_url, TARGET_INDEX)
    assert still_there is not None
    assert still_there[1] is True

    # Same window, same index: no retry while the contention is still likely.
    retried = _reindex(churned_url, now=IN_WINDOW + timedelta(minutes=5))
    assert retried.outcome == "skipped_no_candidate"
    assert retried.skipped == {TARGET_INDEX: "skipped_attempted"}


def test_reindex_drops_an_invalid_ccnew_left_by_a_previous_attempt(
    churned_url: str,
) -> None:
    """A cancelled rebuild leaves ``<name>_ccnew`` behind; clear it first.

    The leftover is manufactured the deterministic way: a CREATE INDEX
    CONCURRENTLY that fails during its validation pass leaves exactly the same
    artefact a cancelled REINDEX does -- an index the planner ignores, that
    still occupies disk, and whose name blocks the next rebuild.
    """

    with psycopg.connect(churned_url, autocommit=True) as connection:
        with pytest.raises(psycopg.errors.UniqueViolation):
            connection.execute(
                sql.SQL(
                    "CREATE UNIQUE INDEX CONCURRENTLY {} ON evidence (event_type)"
                ).format(sql.Identifier(CCNEW_INDEX))
            )

    leftover = _index_row(churned_url, CCNEW_INDEX)
    assert leftover is not None
    assert leftover[1] is False

    summary = _reindex(churned_url)

    assert summary.outcome == "reindexed"
    assert _index_row(churned_url, CCNEW_INDEX) is None
    rebuilt = _index_row(churned_url, TARGET_INDEX)
    assert rebuilt is not None
    assert rebuilt[1] is True


def test_reindex_leaves_an_invalid_target_index_for_a_human(churned_url: str) -> None:
    summary = _job(churned_url).reindex_evidence_indexes(
        index_names=("idx_evidence_not_a_real_index",),
        window_utc=WINDOW_UTC,
        min_size_bytes=TEST_MIN_SIZE_BYTES,
        now=IN_WINDOW,
    )

    assert summary.outcome == "skipped_no_candidate"
    assert summary.skipped == {"idx_evidence_not_a_real_index": "skipped_missing"}
