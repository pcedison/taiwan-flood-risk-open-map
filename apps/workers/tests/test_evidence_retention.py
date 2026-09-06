from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.config import load_worker_settings
from app.jobs import evidence_retention
from app.jobs.evidence_retention import (
    DEFAULT_EVIDENCE_REALTIME_RETENTION_HOURS,
    DEFAULT_LOCATION_QUERY_RETENTION_HOURS,
    DEFAULT_STAGING_EVIDENCE_BATCH_SIZE,
    DEFAULT_STAGING_EVIDENCE_MAX_BATCHES,
    DEFAULT_STAGING_EVIDENCE_RETENTION_DAYS,
    DEFAULT_STAGING_EVIDENCE_STATEMENT_TIMEOUT_MS,
    STAGING_EVIDENCE_REJECTED_INDEX,
    STAGING_RETENTION_TIMEOUT_WARNING_STREAK,
    EvidenceRetentionUnavailable,
    PostgresEvidenceRetentionJob,
)


class _FakeCursor:
    def __init__(self, fetch_result: object) -> None:
        self._fetch_result = fetch_result
        self.executions: list[tuple[str, tuple]] = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple) -> None:
        self.executions.append((sql, params))

    def fetchone(self) -> object:
        return self._fetch_result


class _FakeConnection:
    def __init__(self, fetch_result: object) -> None:
        self.cursor_instance = _FakeCursor(fetch_result)
        self.commits = 0

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.commits += 1


def test_prune_realtime_deletes_official_station_evidence_past_cutoff() -> None:
    connection = _FakeConnection((7,))
    now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    summary = job.prune_realtime(retention_hours=48, now=now)

    assert summary.rows_deleted == 7
    assert summary.event_types == (
        "rainfall",
        "water_level",
        "flood_warning",
    )
    assert summary.cutoff == now - timedelta(hours=48)
    assert connection.commits == 1

    sql, params = connection.cursor_instance.executions[0]
    assert "DELETE FROM evidence" in sql
    assert "source_type = 'official'" in sql
    assert "event_type = ANY(%s::text[])" in sql
    assert params == (
        ["rainfall", "water_level", "flood_warning"],
        now - timedelta(hours=48),
        50_000,
    )


def test_prune_realtime_excludes_flood_report_to_protect_observed_history() -> None:
    """flood_report must not be in the default prunable set.

    profiles.py counts every flood_report (including official ones) as
    observed history for historical_score, so pruning aged official flood
    reports would erase real observed flood events. flood_warning is safe
    (scoring treats it only as a realtime signal).
    """
    from app.jobs.evidence_retention import PRUNABLE_REALTIME_EVENT_TYPES

    assert "flood_report" not in PRUNABLE_REALTIME_EVENT_TYPES
    assert "flood_warning" in PRUNABLE_REALTIME_EVENT_TYPES


def test_prune_realtime_scoped_to_official_source() -> None:
    """The prune query filters source_type='official' as a hardcoded literal.

    Even if a caller passes an event_type shared with non-official evidence,
    the 'official' filter is baked into the SQL text (not a bind parameter),
    so non-official rows can never be deleted.
    """
    connection = _FakeConnection((3,))
    now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    job.prune_realtime(
        retention_hours=48,
        event_types=("flood_warning",),
        now=now,
    )

    sql, params = connection.cursor_instance.executions[0]
    # 'official' is a literal baked into the SQL text, not a bind parameter --
    # there is no way for a caller to widen the query to non-official rows.
    assert "source_type = 'official'" in sql
    assert params == (["flood_warning"], now - timedelta(hours=48), 50_000)


def test_prune_realtime_skips_when_no_event_types() -> None:
    connection = _FakeConnection((0,))
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    summary = job.prune_realtime(retention_hours=24, event_types=())

    assert summary.rows_deleted == 0
    assert connection.commits == 0
    assert connection.cursor_instance.executions == []


def test_prune_realtime_rejects_non_positive_retention() -> None:
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: _FakeConnection((0,)))

    with pytest.raises(ValueError):
        job.prune_realtime(retention_hours=0)


def test_prune_realtime_wraps_database_errors() -> None:
    def boom() -> object:
        raise RuntimeError("connection refused")

    job = PostgresEvidenceRetentionJob(connection_factory=boom)

    with pytest.raises(EvidenceRetentionUnavailable):
        job.prune_realtime(retention_hours=48)


def test_prune_location_queries_deletes_rows_past_cutoff() -> None:
    connection = _FakeConnection((11,))
    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    summary = job.prune_location_queries(retention_hours=720, now=now)

    assert summary.rows_deleted == 11
    assert summary.retention_hours == 720
    assert summary.cutoff == now - timedelta(hours=720)
    assert connection.commits == 1

    sql, params = connection.cursor_instance.executions[0]
    assert "DELETE FROM location_queries" in sql
    assert "created_at < %s::timestamptz" in sql
    assert params == (now - timedelta(hours=720), 50_000)


def test_prune_location_queries_rejects_non_positive_retention() -> None:
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: _FakeConnection((0,)))

    with pytest.raises(ValueError):
        job.prune_location_queries(retention_hours=0)


def test_prune_location_queries_wraps_database_errors() -> None:
    def boom() -> object:
        raise RuntimeError("connection refused")

    job = PostgresEvidenceRetentionJob(connection_factory=boom)

    with pytest.raises(EvidenceRetentionUnavailable):
        job.prune_location_queries(retention_hours=720)


def test_prune_expired_raw_snapshots_uses_persisted_policy_deadline() -> None:
    connection = _FakeConnection((13,))
    now = datetime(2026, 8, 29, 1, 0, tzinfo=UTC)
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    summary = job.prune_expired_raw_snapshots(batch_limit=2_000, now=now)

    assert summary.rows_deleted == 13
    assert connection.commits == 1
    sql, params = connection.cursor_instance.executions[0]
    assert "DELETE FROM raw_snapshots" in sql
    assert "retention_expires_at IS NOT NULL" in sql
    assert "retention_expires_at < %s::timestamptz" in sql
    assert params == (now, 2_000)


def test_prune_expired_raw_snapshots_rejects_non_positive_limit() -> None:
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: _FakeConnection((0,)))

    with pytest.raises(ValueError):
        job.prune_expired_raw_snapshots(batch_limit=0)


def test_prune_expired_raw_snapshots_wraps_database_errors() -> None:
    def boom() -> object:
        raise RuntimeError("connection refused")

    job = PostgresEvidenceRetentionJob(connection_factory=boom)

    with pytest.raises(EvidenceRetentionUnavailable):
        job.prune_expired_raw_snapshots()


def test_location_queries_retention_hours_config_default_and_env() -> None:
    assert load_worker_settings({}).location_queries_retention_hours == (
        DEFAULT_LOCATION_QUERY_RETENTION_HOURS
    )
    assert (
        load_worker_settings(
            {"LOCATION_QUERIES_RETENTION_HOURS": "240"}
        ).location_queries_retention_hours
        == 240
    )


def test_evidence_retention_hours_config_default_and_env() -> None:
    assert load_worker_settings({}).evidence_realtime_retention_hours == (
        DEFAULT_EVIDENCE_REALTIME_RETENTION_HOURS
    )
    assert (
        load_worker_settings(
            {"EVIDENCE_REALTIME_RETENTION_HOURS": "12"}
        ).evidence_realtime_retention_hours
        == 12
    )


class _StagingFakeCursor:
    """Cursor scripted with the per-batch delete counts, plus index answers."""

    def __init__(
        self,
        batches: list[int] | Exception,
        *,
        index_valid: list[bool] | None = None,
    ) -> None:
        self._batches = batches
        self._index_valid = list(index_valid if index_valid is not None else [True])
        self._index_answer: bool = True
        self.rowcount = 0
        self.executions: list[tuple[str, tuple | None]] = []

    def __enter__(self) -> "_StagingFakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple | None = None) -> None:
        self.executions.append((sql, params))
        if "pg_index" in sql:
            self._index_answer = (
                self._index_valid.pop(0) if self._index_valid else False
            )
            return
        if "DELETE FROM staging_evidence" not in sql:
            return
        if isinstance(self._batches, Exception):
            raise self._batches
        self.rowcount = self._batches.pop(0) if self._batches else 0

    def fetchone(self) -> object:
        return {"indisvalid": self._index_answer}

    def fetchall(self) -> list[object]:
        return []


class _StagingFakeConnection:
    def __init__(
        self,
        batches: list[int] | Exception,
        *,
        index_valid: list[bool] | None = None,
    ) -> None:
        self.cursor_instance = _StagingFakeCursor(batches, index_valid=index_valid)
        self.commits = 0
        self.rollbacks = 0
        self.autocommit = False

    def __enter__(self) -> "_StagingFakeConnection":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def cursor(self) -> _StagingFakeCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def set_autocommit(self, value: bool) -> None:
        self.autocommit = value


class _FakeDatabaseError(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(f"sqlstate {sqlstate}")
        self.sqlstate = sqlstate


@pytest.fixture(autouse=True)
def _reset_timeout_streak() -> None:
    evidence_retention._staging_timeout_streak = 0


def _statements(connection: _StagingFakeConnection, needle: str) -> list[tuple[str, tuple | None]]:
    return [
        execution
        for execution in connection.cursor_instance.executions
        if needle in execution[0]
    ]


def _deletes(connection: _StagingFakeConnection) -> list[tuple[str, tuple | None]]:
    return _statements(connection, "DELETE FROM staging_evidence")


def test_prune_staging_evidence_only_deletes_terminal_rejected_rows_past_cutoff() -> None:
    connection = _StagingFakeConnection([3, 0])
    now = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    summary = job.prune_staging_evidence(retention_days=7, batch_size=3, now=now)

    assert summary.deleted_rows == 3
    assert summary.cutoff == now - timedelta(days=7)
    assert summary.index_state == "ready"

    sql, params = _deletes(connection)[0]
    # The status is a SQL literal, never a bind parameter, so no caller can
    # widen the delete to the accepted rows promotion still reads.
    assert "validation_status = 'rejected'" in sql
    assert "'accepted'" not in sql
    assert "created_at < %s::timestamptz" in sql
    assert "LIMIT %s" in sql
    assert params == (now - timedelta(days=7), 3)


def test_prune_staging_evidence_orders_by_created_at_and_keeps_no_cursor() -> None:
    """Ordering by created_at is what makes the partial index usable.

    The first shape of this job walked the uuid primary key, which is random
    heap I/O: ~1.31 M buffers and 2.5 s per batch on 1 M rows, so the very
    first batch of a backlog exceeded the 5 s budget and nothing was ever
    deleted. A cursor is unnecessary anyway -- each batch deletes the rows it
    selected, so the next batch cannot see them again.
    """

    connection = _StagingFakeConnection([2, 2, 0])
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    job.prune_staging_evidence(batch_size=2)

    for sql, params in _deletes(connection):
        assert "ORDER BY created_at ASC" in sql
        assert "ORDER BY id" not in sql
        assert "id > " not in sql
        # cutoff and limit only: no cursor is threaded between batches.
        assert params is not None
        assert len(params) == 2


def test_prune_staging_evidence_sets_transaction_local_timeouts_before_each_batch() -> None:
    connection = _StagingFakeConnection([2, 2, 0])
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    job.prune_staging_evidence(
        batch_size=2, statement_timeout_ms=5_000, lock_timeout_ms=2_000
    )

    timeout_calls = [
        params
        for sql, params in _statements(connection, "set_config('statement_timeout'")
    ]
    # One per executed batch (two deleting batches plus the empty terminal one).
    assert timeout_calls == [("2000ms", "5000ms")] * 3
    assert all(
        "true" in sql for sql, _params in _statements(connection, "set_config")
    )
    # Each batch commits on its own; nothing spans the whole cycle.
    assert connection.commits == 3


def test_prune_staging_evidence_stops_at_max_batches() -> None:
    connection = _StagingFakeConnection([2] * 10)
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    summary = job.prune_staging_evidence(batch_size=2, max_batches=3)

    assert summary.batches == 3
    assert summary.deleted_rows == 6
    assert summary.stopped_reason == "max_batches"
    assert len(_deletes(connection)) == 3


def test_prune_staging_evidence_stops_when_a_batch_deletes_nothing() -> None:
    connection = _StagingFakeConnection([0])
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    summary = job.prune_staging_evidence(max_batches=10)

    assert summary.deleted_rows == 0
    assert summary.batches == 1
    assert summary.stopped_reason == "exhausted"
    assert len(_deletes(connection)) == 1


@pytest.mark.parametrize(
    ("sqlstate", "expected_reason"),
    [("57014", "statement_timeout"), ("55P03", "lock_timeout")],
)
def test_prune_staging_evidence_reports_timeouts_instead_of_raising(
    sqlstate: str, expected_reason: str
) -> None:
    connection = _StagingFakeConnection(_FakeDatabaseError(sqlstate))
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    summary = job.prune_staging_evidence()

    assert summary.stopped_reason == expected_reason
    assert summary.deleted_rows == 0
    assert summary.batches == 0
    assert connection.rollbacks == 1
    # No retry: the cycle ends after the first refused batch.
    assert len(_deletes(connection)) == 1


def test_prune_staging_evidence_warns_after_a_streak_of_timeouts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """One timeout is a busy node; a run of them needs an operator."""

    job = PostgresEvidenceRetentionJob(
        connection_factory=lambda: _StagingFakeConnection(_FakeDatabaseError("57014"))
    )

    for _cycle in range(STAGING_RETENTION_TIMEOUT_WARNING_STREAK - 1):
        job.prune_staging_evidence()
    capsys.readouterr()
    job.prune_staging_evidence()
    warned = capsys.readouterr().out

    assert "worker.maintenance.staging_retention_timeout_streak" in warned
    assert '"level": "warning"' in warned

    # A cycle that finishes clears the streak.
    PostgresEvidenceRetentionJob(
        connection_factory=lambda: _StagingFakeConnection([0])
    ).prune_staging_evidence()
    assert evidence_retention._staging_timeout_streak == 0


def test_prune_staging_evidence_wraps_non_timeout_database_errors() -> None:
    connection = _StagingFakeConnection(_FakeDatabaseError("42P01"))
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    with pytest.raises(EvidenceRetentionUnavailable):
        job.prune_staging_evidence()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"retention_days": 0},
        {"batch_size": 0},
        {"max_batches": 0},
        {"statement_timeout_ms": 0},
        {"lock_timeout_ms": 0},
    ],
)
def test_prune_staging_evidence_rejects_non_positive_bounds(
    kwargs: dict[str, int],
) -> None:
    job = PostgresEvidenceRetentionJob(
        connection_factory=lambda: _StagingFakeConnection([0])
    )

    with pytest.raises(ValueError):
        job.prune_staging_evidence(**kwargs)


def test_prune_staging_evidence_builds_the_partial_index_concurrently() -> None:
    # First probe says absent, the probe after the build says valid.
    connection = _StagingFakeConnection([0], index_valid=[False, True])
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    summary = job.prune_staging_evidence()

    assert summary.index_state == "ready"
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction block.
    assert connection.autocommit is True
    create_sql = _statements(connection, "CREATE INDEX CONCURRENTLY")[0][0]
    assert f"IF NOT EXISTS {STAGING_EVIDENCE_REJECTED_INDEX}" in create_sql
    assert "ON staging_evidence (created_at)" in create_sql
    assert "WHERE validation_status = 'rejected'" in create_sql
    # A half-built index from a previous crash is invalid, unusable and blocks
    # a rebuild, so it is always dropped concurrently first.
    assert _statements(connection, "DROP INDEX CONCURRENTLY IF EXISTS")
    # The build carries no statement_timeout: a 14 M row build takes minutes
    # and cancelling it only leaves another invalid index behind.
    build_timeouts = _statements(connection, "set_config('statement_timeout', '0'")
    assert build_timeouts[0][1] == ("2000ms",)
    # Session-level (is_local false), because CREATE INDEX CONCURRENTLY runs
    # outside a transaction block and a local setting would not reach it.
    assert "set_config('lock_timeout', %s, false)" in build_timeouts[0][0]


def test_prune_staging_evidence_skips_the_probe_when_the_index_already_exists() -> None:
    connection = _StagingFakeConnection([0], index_valid=[True])
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    summary = job.prune_staging_evidence()

    assert summary.index_state == "ready"
    assert _statements(connection, "CREATE INDEX CONCURRENTLY") == []


def test_prune_staging_evidence_deletes_nothing_until_the_index_is_valid() -> None:
    """Deleting without the index is the pathological scan, so wait instead."""

    connection = _StagingFakeConnection([5_000], index_valid=[False, False])
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    summary = job.prune_staging_evidence()

    assert summary.index_state == "building"
    assert summary.stopped_reason == "index_not_ready"
    assert summary.deleted_rows == 0
    assert summary.batches == 0
    assert _deletes(connection) == []


def test_prune_staging_evidence_reports_an_unavailable_index_without_deleting() -> None:
    class _FailingConnection(_StagingFakeConnection):
        def cursor(self) -> _StagingFakeCursor:
            raise _FakeDatabaseError("53100")

    connection = _FailingConnection([5_000])
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    summary = job.prune_staging_evidence()

    assert summary.index_state == "unavailable"
    assert summary.stopped_reason == "index_not_ready"
    assert summary.deleted_rows == 0


def test_prune_staging_evidence_can_be_told_the_index_is_managed_by_hand() -> None:
    connection = _StagingFakeConnection([2, 0])
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    summary = job.prune_staging_evidence(batch_size=2, ensure_index=False)

    assert summary.index_state == "skipped"
    assert _statements(connection, "CREATE INDEX CONCURRENTLY") == []
    # An operator who built the index in a maintenance window still gets the
    # deletes; only the build step is skipped.
    assert summary.deleted_rows == 2


def test_staging_evidence_retention_config_defaults_and_env() -> None:
    defaults = load_worker_settings({})
    assert defaults.staging_evidence_retention_enabled is True
    assert defaults.staging_evidence_retention_ensure_index is True
    assert defaults.staging_evidence_retention_days == (
        DEFAULT_STAGING_EVIDENCE_RETENTION_DAYS
    )
    assert defaults.staging_evidence_retention_max_batches == (
        DEFAULT_STAGING_EVIDENCE_MAX_BATCHES
    )
    assert defaults.staging_evidence_retention_batch_size == (
        DEFAULT_STAGING_EVIDENCE_BATCH_SIZE
    )
    assert defaults.staging_evidence_retention_statement_timeout_ms == (
        DEFAULT_STAGING_EVIDENCE_STATEMENT_TIMEOUT_MS
    )

    overridden = load_worker_settings(
        {
            "STAGING_EVIDENCE_RETENTION_ENABLED": "false",
            "STAGING_EVIDENCE_RETENTION_ENSURE_INDEX": "false",
            "STAGING_EVIDENCE_RETENTION_DAYS": "14",
            "STAGING_EVIDENCE_RETENTION_MAX_BATCHES": "2",
            "STAGING_EVIDENCE_RETENTION_BATCH_SIZE": "1000",
            "STAGING_EVIDENCE_RETENTION_STATEMENT_TIMEOUT_MS": "9000",
        }
    )
    assert overridden.staging_evidence_retention_enabled is False
    assert overridden.staging_evidence_retention_ensure_index is False
    assert overridden.staging_evidence_retention_days == 14
    assert overridden.staging_evidence_retention_max_batches == 2
    assert overridden.staging_evidence_retention_batch_size == 1000
    assert overridden.staging_evidence_retention_statement_timeout_ms == 9000
