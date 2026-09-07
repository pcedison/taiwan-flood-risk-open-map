from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.config import load_worker_settings
from app.jobs import evidence_retention
from app.jobs.evidence_retention import (
    DEFAULT_EVIDENCE_REALTIME_RETENTION_HOURS,
    DEFAULT_LOCATION_QUERY_RETENTION_HOURS,
    DEFAULT_STAGING_EVIDENCE_ACCEPTED_MAX_BATCHES,
    DEFAULT_STAGING_EVIDENCE_ACCEPTED_MIN_WINDOW_SECONDS,
    DEFAULT_STAGING_EVIDENCE_ACCEPTED_WINDOW_SECONDS,
    DEFAULT_STAGING_EVIDENCE_BATCH_SIZE,
    DEFAULT_STAGING_EVIDENCE_MAX_BATCHES,
    DEFAULT_STAGING_EVIDENCE_RETENTION_DAYS,
    DEFAULT_STAGING_EVIDENCE_STATEMENT_TIMEOUT_MS,
    STAGING_EVIDENCE_ACCEPTED_INDEX,
    STAGING_EVIDENCE_REJECTED_INDEX,
    STAGING_RETENTION_TIMEOUT_WARNING_STREAK,
    EvidenceRetentionUnavailable,
    PostgresEvidenceRetentionJob,
    is_orphan_prunable_adapter,
    legacy_fallback_adapter_keys,
    orphan_prunable_source_ids,
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


REALTIME_SOURCE_ID = "11111111-1111-4111-8111-111111111111"
HISTORICAL_SOURCE_ID = "22222222-2222-4222-8222-222222222222"
DEFAULT_DATA_SOURCES = (
    (REALTIME_SOURCE_ID, "official.cwa.rainfall"),
    (HISTORICAL_SOURCE_ID, "official.nstc.flood_disaster_points"),
)


class _StagingFakeCursor:
    """Cursor scripted with the per-batch delete counts, plus index answers.

    The two passes are scripted independently: ``batches`` drives the
    rejected delete and ``accepted_batches`` the orphan delete, so a test
    about one pass is not perturbed by the other running after it.
    """

    def __init__(
        self,
        batches: list[int] | Exception,
        *,
        index_valid: list[bool] | None = None,
        accepted_batches: list[object] | Exception | None = None,
        accepted_index_valid: list[bool] | None = None,
        data_sources: list[tuple[str, str]] | None = None,
        oldest_accepted: datetime | None = None,
    ) -> None:
        self._batches = batches
        # None means the table holds no accepted row at all, so the sweep
        # reports caught_up without issuing a DELETE. That keeps the
        # rejected-pass tests below about the rejected pass.
        self._oldest_accepted = oldest_accepted
        # Either every accepted batch fails, or the list is a script whose
        # entries are row counts and, where a single batch must fail, the
        # exception to raise for it.
        self._accepted_batches: list[object] | Exception = (
            accepted_batches
            if isinstance(accepted_batches, Exception)
            else list(accepted_batches or [])
        )
        self._index_valid = list(index_valid if index_valid is not None else [True])
        self._accepted_index_valid = list(
            accepted_index_valid if accepted_index_valid is not None else [True]
        )
        self._data_sources = list(
            data_sources if data_sources is not None else DEFAULT_DATA_SOURCES
        )
        self._index_answer: bool = True
        self._rows: list[object] = []
        self._fetchone_result: object = None
        self.rowcount = 0
        self.executions: list[tuple[str, tuple | None]] = []

    def __enter__(self) -> "_StagingFakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple | None = None) -> None:
        self.executions.append((sql, params))
        if "pg_index" in sql:
            queue = (
                self._accepted_index_valid
                if params and params[0] == STAGING_EVIDENCE_ACCEPTED_INDEX
                else self._index_valid
            )
            self._index_answer = queue.pop(0) if queue else False
            self._fetchone_result = {"indisvalid": self._index_answer}
            return
        if "min(created_at)" in sql:
            self._fetchone_result = {"oldest": self._oldest_accepted}
            return
        if "FROM data_sources" in sql:
            self._rows = list(self._data_sources)
            return
        if "DELETE FROM staging_evidence" not in sql:
            return
        if ACCEPTED_MARKER in sql:
            if isinstance(self._accepted_batches, Exception):
                raise self._accepted_batches
            if isinstance(self._batches, Exception):
                raise self._batches
            queued_row = (
                self._accepted_batches.pop(0) if self._accepted_batches else 0
            )
            if isinstance(queued_row, Exception):
                raise queued_row
            self.rowcount = int(queued_row)  # type: ignore[call-overload]
            return
        if isinstance(self._batches, Exception):
            raise self._batches
        self.rowcount = self._batches.pop(0) if self._batches else 0

    def fetchone(self) -> object:
        return self._fetchone_result

    def fetchall(self) -> list[object]:
        return list(self._rows)


class _StagingFakeConnection:
    def __init__(
        self,
        batches: list[int] | Exception,
        *,
        index_valid: list[bool] | None = None,
        accepted_batches: list[object] | Exception | None = None,
        accepted_index_valid: list[bool] | None = None,
        data_sources: list[tuple[str, str]] | None = None,
        oldest_accepted: datetime | None = None,
    ) -> None:
        self.cursor_instance = _StagingFakeCursor(
            batches,
            index_valid=index_valid,
            accepted_batches=accepted_batches,
            accepted_index_valid=accepted_index_valid,
            data_sources=data_sources,
            oldest_accepted=oldest_accepted,
        )
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


ACCEPTED_MARKER = "/* staging-retention-accepted */"


# A window wide enough that one batch always covers the whole span from the
# fake watermark to the cutoff, so tests that are not about window sizing
# see exactly one window.
WHOLE_SPAN_WINDOW_SECONDS = 10**9
AGED = datetime(2026, 8, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _reset_sweep_state() -> None:
    """The streaks and the sweep watermark outlive a single job by design."""

    evidence_retention._staging_timeout_streak = 0
    evidence_retention._accepted_timeout_streak = 0
    evidence_retention._accepted_sweep_watermark = None
    evidence_retention._accepted_sweep_window_seconds = None


def _statements(connection: _StagingFakeConnection, needle: str) -> list[tuple[str, tuple | None]]:
    return [
        execution
        for execution in connection.cursor_instance.executions
        if needle in execution[0]
    ]


def _deletes(connection: _StagingFakeConnection) -> list[tuple[str, tuple | None]]:
    """Rejected-pass deletes only, told apart by their SQL comment marker."""

    return [
        execution
        for execution in _statements(connection, "DELETE FROM staging_evidence")
        if ACCEPTED_MARKER not in execution[0]
    ]


def _accepted_deletes(
    connection: _StagingFakeConnection,
) -> list[tuple[str, tuple | None]]:
    return _statements(connection, ACCEPTED_MARKER)


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
    # Three for the rejected pass (two deleting batches plus the empty terminal
    # one), then two for the accepted pass: the one-off data_sources lookup and
    # its own terminal batch.
    assert timeout_calls == [("2000ms", "5000ms")] * 5
    assert all(
        "true" in sql for sql, _params in _statements(connection, "set_config")
    )
    # Each batch commits on its own; nothing spans the whole cycle.
    assert connection.commits == 5


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
    connection = _StagingFakeConnection(
        _FakeDatabaseError(sqlstate), oldest_accepted=AGED
    )
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    # Window pinned at the floor, so the accepted pass has nothing left to
    # shrink and reports the timeout on its first refused batch. The shrinking
    # path has its own test below.
    summary = job.prune_staging_evidence(
        accepted_window_seconds=DEFAULT_STAGING_EVIDENCE_ACCEPTED_MIN_WINDOW_SECONDS,
        accepted_min_window_seconds=(
            DEFAULT_STAGING_EVIDENCE_ACCEPTED_MIN_WINDOW_SECONDS
        ),
    )

    assert summary.stopped_reason == expected_reason
    assert summary.deleted_rows == 0
    assert summary.batches == 0
    # No retry: the cycle ends after the first refused batch.
    assert len(_deletes(connection)) == 1
    # The accepted pass is independent, so it makes its own attempt and reports
    # its own reason rather than inheriting the rejected pass's.
    assert summary.accepted_stopped_reason == expected_reason
    assert summary.accepted_deleted_rows == 0
    assert summary.accepted_batches == 1
    assert len(_accepted_deletes(connection)) == 1
    assert connection.rollbacks == 2


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

    # An operator who built the index in a maintenance window still gets the
    # deletes; only the build step is skipped.
    assert summary.index_state == "ready"
    assert _statements(connection, "CREATE INDEX CONCURRENTLY") == []
    assert summary.deleted_rows == 2


def test_prune_staging_evidence_still_probes_the_index_when_told_not_to_build(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """ENSURE_INDEX=false skips the build, not the safety check.

    Taking the operator's word for it and deleting anyway bought nothing but
    the pathological scan -- one cancelled batch per cycle, silently, for as
    long as the index stayed missing.
    """

    connection = _StagingFakeConnection(
        [2, 0], index_valid=[False], accepted_index_valid=[False]
    )
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    summary = job.prune_staging_evidence(batch_size=2, ensure_index=False)
    warned = capsys.readouterr().out

    assert summary.index_state == "skipped"
    assert summary.stopped_reason == "index_not_ready"
    assert summary.deleted_rows == 0
    assert _deletes(connection) == []
    assert summary.accepted_index_state == "skipped"
    assert summary.accepted_stopped_reason == "index_not_ready"
    assert _accepted_deletes(connection) == []
    assert _statements(connection, "CREATE INDEX CONCURRENTLY") == []
    assert "worker.maintenance.staging_retention_index_missing" in warned


def test_index_validity_probe_is_scoped_to_the_current_schema() -> None:
    """relname is not unique across schemas.

    Without the namespace filter a same-named index on another schema of the
    search_path reads as ready and the job deletes with no index at all.
    """

    connection = _StagingFakeConnection([0])
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    job.prune_staging_evidence()

    probes = _statements(connection, "pg_index")
    assert probes
    for sql, params in probes:
        assert "cls.relnamespace = current_schema()::regnamespace" in sql
        assert params in (
            (STAGING_EVIDENCE_REJECTED_INDEX,),
            (STAGING_EVIDENCE_ACCEPTED_INDEX,),
        )


# --------------------------------------------------------------------------
# The accepted-orphan pass (#372).
#
# ~10.4 M of the hosted node's 12.6 M accepted staging rows are realtime
# telemetry that was promoted and whose evidence row the 48 h realtime prune
# then deleted, so nothing can read them again. Two guards keep the delete
# narrow: the adapter must be realtime-cadence, and no evidence row may still
# point at the staging row.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "adapter_key",
    [
        "official.cwa.rainfall",
        "official.cwa.tide_level",
        "official.wra.water_level",
        "official.wra_iow.flood_depth",
        "official.civil_iot.sewer_water_level",
        "official.civil_iot.pump_water_level",
        "official.civil_iot.gate_water_level",
        "local.taipei.sewer_water_level",
        "local.tainan.flood_sensor",
    ],
)
def test_is_orphan_prunable_adapter_accepts_realtime_telemetry(
    adapter_key: str,
) -> None:
    assert is_orphan_prunable_adapter(adapter_key) is True


@pytest.mark.parametrize(
    "adapter_key",
    [
        # historical_coverage.py re-reads these accepted staging rows years
        # after ingestion to build the county/year coverage grid.
        "official.nstc.flood_disaster_points",
        "official.wra.historical_flood",
        # A static snapshot's accepted row is still the current one at 8 days.
        "official.flood_potential.geojson",
        # Warning events publish only when there is an event to publish.
        "official.ncdr.cap",
        "official.cwa.heavy_rain_warning",
    ],
)
def test_is_orphan_prunable_adapter_excludes_historical_static_and_event_sources(
    adapter_key: str,
) -> None:
    assert is_orphan_prunable_adapter(adapter_key) is False


def test_orphan_prunable_source_ids_resolves_only_allowed_adapters() -> None:
    resolved = orphan_prunable_source_ids(
        [
            (REALTIME_SOURCE_ID, "official.cwa.rainfall"),
            (HISTORICAL_SOURCE_ID, "official.nstc.flood_disaster_points"),
            ("33333333-3333-4333-8333-333333333333", "official.ncdr.cap"),
            ("44444444-4444-4444-8444-444444444444", "official.flood_potential.geojson"),
            # Rows with a missing id or adapter key can never be matched safely.
            (None, "official.cwa.rainfall"),
            (REALTIME_SOURCE_ID, None),
            # A duplicate must not widen the array the batch SQL binds.
            (REALTIME_SOURCE_ID, "official.cwa.rainfall"),
        ]
    )

    assert resolved == (REALTIME_SOURCE_ID,)


def test_prune_staging_evidence_accepted_pass_deletes_only_unreferenced_aged_rows() -> None:
    connection = _StagingFakeConnection(
        [0], accepted_batches=[4], oldest_accepted=AGED
    )
    now = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    summary = job.prune_staging_evidence(
        retention_days=7,
        batch_size=4,
        accepted_window_seconds=WHOLE_SPAN_WINDOW_SECONDS,
        now=now,
    )

    cutoff = now - timedelta(days=7)
    assert summary.accepted_deleted_rows == 4
    assert summary.accepted_stopped_reason == "caught_up"
    assert summary.accepted_source_count == 1
    assert summary.accepted_watermark == cutoff

    sql, params = _accepted_deletes(connection)[0]
    # 'accepted' is a SQL literal like 'rejected' is, never a bind parameter.
    assert "s.validation_status = 'accepted'" in sql
    # The half-open window is what bounds a batch's scan; window_end is capped
    # at the cutoff by the caller, so no separate cutoff predicate is needed.
    assert "s.created_at >= %s::timestamptz" in sql
    assert "s.created_at < %s::timestamptz" in sql
    # The adapter allow-list is an id array resolved from data_sources, and the
    # NOT EXISTS is what makes deleting an accepted row safe at all.
    assert "s.data_source_id = ANY(%s::uuid[])" in sql
    assert "NOT EXISTS (" in sql
    assert "e.properties ->> 'staging_evidence_id' = s.id::text" in sql
    # Repeating 0042's partial predicate is what lets the planner use it.
    assert "e.properties ? 'staging_evidence_id'" in sql
    assert "ORDER BY s.created_at ASC" in sql
    assert "LIMIT %s" in sql
    assert params == (AGED, cutoff, [REALTIME_SOURCE_ID], 4)


def test_prune_staging_evidence_runs_the_rejected_pass_first() -> None:
    """Order matters: the accepted pass must not delay the proven backlog pass."""

    connection = _StagingFakeConnection(
        [2, 0], accepted_batches=[2, 1], oldest_accepted=AGED
    )
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    job.prune_staging_evidence(
        batch_size=2, accepted_window_seconds=WHOLE_SPAN_WINDOW_SECONDS
    )

    order = [
        ACCEPTED_MARKER in sql
        for sql, _params in _statements(connection, "DELETE FROM staging_evidence")
    ]
    assert order == [False, False, True, True]


def test_prune_staging_evidence_accepted_pass_runs_no_delete_without_source_ids() -> None:
    """An empty allow-list must mean "delete nothing", not "delete anything"."""

    connection = _StagingFakeConnection([0], accepted_batches=[5], data_sources=[])
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    summary = job.prune_staging_evidence()

    assert summary.accepted_stopped_reason == "no_adapter_sources"
    assert summary.accepted_deleted_rows == 0
    assert summary.accepted_batches == 0
    assert summary.accepted_source_count == 0
    assert _accepted_deletes(connection) == []


def test_prune_staging_evidence_accepted_pass_runs_no_delete_for_excluded_adapters() -> None:
    connection = _StagingFakeConnection(
        [0],
        accepted_batches=[5],
        data_sources=[(HISTORICAL_SOURCE_ID, "official.nstc.flood_disaster_points")],
    )
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    summary = job.prune_staging_evidence()

    assert summary.accepted_stopped_reason == "no_adapter_sources"
    assert _accepted_deletes(connection) == []


def test_prune_staging_evidence_accepted_pass_can_be_disabled() -> None:
    connection = _StagingFakeConnection([2, 0], accepted_batches=[5])
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    summary = job.prune_staging_evidence(batch_size=2, accepted_enabled=False)

    assert summary.accepted_stopped_reason == "disabled"
    assert summary.accepted_index_state == "skipped"
    assert summary.accepted_deleted_rows == 0
    assert _accepted_deletes(connection) == []
    assert _statements(connection, "FROM data_sources") == []
    # The rejected pass is untouched by the switch.
    assert summary.deleted_rows == 2


def test_prune_staging_evidence_accepted_pass_has_its_own_batch_budget() -> None:
    connection = _StagingFakeConnection(
        [2] * 4, accepted_batches=[2] * 10, oldest_accepted=AGED
    )
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    summary = job.prune_staging_evidence(
        batch_size=2,
        max_batches=2,
        accepted_max_batches=3,
        accepted_window_seconds=WHOLE_SPAN_WINDOW_SECONDS,
    )

    assert summary.batches == 2
    assert summary.deleted_rows == 4
    assert summary.accepted_batches == 3
    assert summary.accepted_deleted_rows == 6
    assert summary.accepted_stopped_reason == "max_batches"


def test_prune_staging_evidence_rejects_a_non_positive_accepted_batch_ceiling() -> None:
    job = PostgresEvidenceRetentionJob(
        connection_factory=lambda: _StagingFakeConnection([0])
    )

    with pytest.raises(ValueError):
        job.prune_staging_evidence(accepted_max_batches=0)


def test_prune_staging_evidence_builds_the_accepted_partial_index_concurrently() -> None:
    connection = _StagingFakeConnection(
        [0], accepted_batches=[0], accepted_index_valid=[False, True]
    )
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    summary = job.prune_staging_evidence()

    assert summary.accepted_index_state == "ready"
    create_sql = [
        sql
        for sql, _params in _statements(connection, "CREATE INDEX CONCURRENTLY")
        if STAGING_EVIDENCE_ACCEPTED_INDEX in sql
    ]
    assert create_sql
    assert "ON staging_evidence (created_at)" in create_sql[0]
    assert "WHERE validation_status = 'accepted'" in create_sql[0]


def test_prune_staging_evidence_holds_accepted_deletes_until_its_index_is_valid() -> None:
    connection = _StagingFakeConnection(
        [0], accepted_batches=[5_000], accepted_index_valid=[False, False]
    )
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    summary = job.prune_staging_evidence()

    assert summary.accepted_index_state == "building"
    assert summary.accepted_stopped_reason == "index_not_ready"
    assert summary.accepted_deleted_rows == 0
    assert _accepted_deletes(connection) == []
    # The rejected pass has its own index and is not held up by this one.
    assert summary.index_state == "ready"


def test_prune_staging_evidence_logs_each_pass_under_its_own_event(
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = _StagingFakeConnection(
        [3, 0], accepted_batches=[4, 1], oldest_accepted=AGED
    )
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    job.prune_staging_evidence(
        batch_size=4, accepted_window_seconds=WHOLE_SPAN_WINDOW_SECONDS
    )
    logged = capsys.readouterr().out

    assert "worker.maintenance.staging_retention" in logged
    assert "worker.maintenance.staging_accepted_retention" in logged
    accepted_line = next(
        line
        for line in logged.splitlines()
        if "worker.maintenance.staging_accepted_retention" in line
    )
    assert '"deleted_rows": 5' in accepted_line
    assert '"source_count": 1' in accepted_line
    assert '"window_seconds": ' in accepted_line
    assert '"watermark": ' in accepted_line


# --------------------------------------------------------------------------
# The sweep. The accepted pass cannot ask for "the oldest batch_size eligible
# rows" the way the rejected pass does, because the rows it keeps stay at the
# head of the index forever: on the hosted node ~2.25 M accepted rows are
# still referenced, and an unwindowed batch re-probes that whole surviving
# prefix before reaching a new orphan -- 405 k probes and 1.43 s at a 400 k
# prefix, growing every cycle. A created_at window behind a watermark makes
# the cost of a batch depend on the window instead.
# --------------------------------------------------------------------------


def _accepted_windows(
    connection: _StagingFakeConnection,
) -> list[tuple[datetime, datetime]]:
    """The [window_start, window_end) each accepted batch actually asked for."""

    return [
        (params[0], params[1])
        for _sql, params in _accepted_deletes(connection)
        if params is not None
    ]


def test_accepted_sweep_starts_at_the_oldest_accepted_row() -> None:
    connection = _StagingFakeConnection(
        [0], accepted_batches=[0], oldest_accepted=AGED
    )
    now = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    job.prune_staging_evidence(
        retention_days=7, accepted_window_seconds=3_600, max_batches=1, now=now
    )

    # min() over the accepted partial index is one btree descent, so seeding
    # the watermark costs a few buffers however large the table is.
    assert _statements(connection, "min(created_at)")
    assert _accepted_windows(connection)[0] == (AGED, AGED + timedelta(hours=1))


def test_accepted_sweep_advances_the_watermark_only_when_a_window_is_finished() -> None:
    """A full batch means the window may still hold orphans; a short one cannot.

    The DELETE asked for batch_size matches and got fewer, so the window is
    swept and the watermark can move past it.
    """

    connection = _StagingFakeConnection(
        # Two full batches in the first window, then a short one that finishes
        # it, then a short one that finishes the second window.
        [0],
        accepted_batches=[2, 2, 1, 0],
        oldest_accepted=AGED,
    )
    now = AGED + timedelta(days=10)
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    summary = job.prune_staging_evidence(
        retention_days=7,
        batch_size=2,
        accepted_max_batches=4,
        accepted_window_seconds=3_600,
        now=now,
    )

    first = (AGED, AGED + timedelta(hours=1))
    second = (AGED + timedelta(hours=1), AGED + timedelta(hours=2))
    assert _accepted_windows(connection) == [first, first, first, second]
    assert summary.accepted_deleted_rows == 5
    assert summary.accepted_batches == 4
    # Two windows swept, so the watermark sits at the end of the second.
    assert summary.accepted_watermark == second[1]


def test_accepted_sweep_reports_caught_up_at_the_cutoff() -> None:
    connection = _StagingFakeConnection(
        [0], accepted_batches=[0, 0, 0], oldest_accepted=AGED
    )
    # Exactly two windows between the oldest row and the cutoff.
    now = AGED + timedelta(days=7, hours=2)
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    summary = job.prune_staging_evidence(
        retention_days=7,
        accepted_max_batches=10,
        accepted_window_seconds=3_600,
        now=now,
    )

    assert summary.accepted_stopped_reason == "caught_up"
    assert summary.accepted_batches == 2
    assert summary.accepted_watermark == AGED + timedelta(hours=2)
    # Nothing beyond the cutoff is ever swept: those rows are inside the
    # retention window and may still be promoted.
    assert all(end <= AGED + timedelta(hours=2) for _start, end in _accepted_windows(connection))


def test_accepted_sweep_resumes_from_the_watermark_on_the_next_cycle() -> None:
    """The watermark outlives the job instance; the scheduler builds a new one
    every cycle, and re-sweeping from the oldest row each time is exactly the
    cost this design exists to avoid."""

    now = AGED + timedelta(days=30)
    first_connection = _StagingFakeConnection(
        [0], accepted_batches=[0], oldest_accepted=AGED
    )
    PostgresEvidenceRetentionJob(
        connection_factory=lambda: first_connection
    ).prune_staging_evidence(
        retention_days=7,
        accepted_max_batches=1,
        accepted_window_seconds=3_600,
        now=now,
    )

    second_connection = _StagingFakeConnection(
        [0], accepted_batches=[0], oldest_accepted=AGED
    )
    PostgresEvidenceRetentionJob(
        connection_factory=lambda: second_connection
    ).prune_staging_evidence(
        retention_days=7,
        accepted_max_batches=1,
        accepted_window_seconds=3_600,
        now=now,
    )

    assert _accepted_windows(second_connection) == [
        (AGED + timedelta(hours=1), AGED + timedelta(hours=2))
    ]
    # The second cycle does not re-seed the watermark either.
    assert _statements(second_connection, "min(created_at)") == []


def test_accepted_sweep_halves_the_window_on_a_statement_timeout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = _StagingFakeConnection(
        [0], accepted_batches=_FakeDatabaseError("57014"), oldest_accepted=AGED
    )
    now = AGED + timedelta(days=30)
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    summary = job.prune_staging_evidence(
        retention_days=7,
        accepted_max_batches=10,
        accepted_window_seconds=1_200,
        accepted_min_window_seconds=300,
        now=now,
    )
    logged = capsys.readouterr().out

    # 1200 -> 600 -> 300, then the floor: three attempts, each its own batch.
    assert [end - start for start, end in _accepted_windows(connection)] == [
        timedelta(seconds=1_200),
        timedelta(seconds=600),
        timedelta(seconds=300),
    ]
    assert summary.accepted_batches == 3
    assert summary.accepted_stopped_reason == "statement_timeout"
    assert summary.accepted_window_seconds == 300
    assert summary.accepted_watermark == AGED
    assert connection.rollbacks == 3
    assert "worker.maintenance.staging_accepted_retention_window_shrunk" in logged


def test_accepted_sweep_does_not_shrink_the_window_on_a_lock_timeout() -> None:
    """A refused lock is contention, not a scan that is too big."""

    connection = _StagingFakeConnection(
        [0], accepted_batches=_FakeDatabaseError("55P03"), oldest_accepted=AGED
    )
    now = AGED + timedelta(days=30)
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    summary = job.prune_staging_evidence(
        retention_days=7,
        accepted_max_batches=10,
        accepted_window_seconds=1_200,
        accepted_min_window_seconds=300,
        now=now,
    )

    assert summary.accepted_stopped_reason == "lock_timeout"
    assert summary.accepted_batches == 1
    assert len(_accepted_deletes(connection)) == 1


def test_accepted_sweep_grows_the_window_back_after_a_swept_window() -> None:
    """One slow patch of history must not throttle the whole sweep forever."""

    connection = _StagingFakeConnection(
        [0], accepted_batches=[_FakeDatabaseError("57014"), 0, 0], oldest_accepted=AGED
    )
    now = AGED + timedelta(days=30)
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    summary = job.prune_staging_evidence(
        retention_days=7,
        accepted_max_batches=3,
        accepted_window_seconds=1_200,
        accepted_min_window_seconds=300,
        now=now,
    )

    assert [end - start for start, end in _accepted_windows(connection)] == [
        timedelta(seconds=1_200),
        timedelta(seconds=600),
        timedelta(seconds=1_200),
    ]
    assert summary.accepted_window_seconds == 1_200


def test_accepted_sweep_is_caught_up_when_no_accepted_row_exists() -> None:
    connection = _StagingFakeConnection([0], accepted_batches=[5])
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    summary = job.prune_staging_evidence()

    assert summary.accepted_stopped_reason == "caught_up"
    assert summary.accepted_watermark is None
    assert _accepted_deletes(connection) == []


def test_prune_staging_evidence_rejects_a_window_below_its_own_floor() -> None:
    job = PostgresEvidenceRetentionJob(
        connection_factory=lambda: _StagingFakeConnection([0])
    )

    with pytest.raises(ValueError):
        job.prune_staging_evidence(
            accepted_window_seconds=60, accepted_min_window_seconds=300
        )
    with pytest.raises(ValueError):
        job.prune_staging_evidence(accepted_min_window_seconds=0)


def test_accepted_pass_warns_after_its_own_streak_of_timeouts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A healthy rejected pass must not keep resetting the accepted streak."""

    def _job() -> PostgresEvidenceRetentionJob:
        return PostgresEvidenceRetentionJob(
            connection_factory=lambda: _StagingFakeConnection(
                [0],
                accepted_batches=_FakeDatabaseError("57014"),
                oldest_accepted=AGED,
            )
        )

    for _cycle in range(STAGING_RETENTION_TIMEOUT_WARNING_STREAK - 1):
        _job().prune_staging_evidence(
            accepted_window_seconds=(
                DEFAULT_STAGING_EVIDENCE_ACCEPTED_MIN_WINDOW_SECONDS
            ),
            accepted_min_window_seconds=(
                DEFAULT_STAGING_EVIDENCE_ACCEPTED_MIN_WINDOW_SECONDS
            ),
        )
    capsys.readouterr()
    _job().prune_staging_evidence(
        accepted_window_seconds=DEFAULT_STAGING_EVIDENCE_ACCEPTED_MIN_WINDOW_SECONDS,
        accepted_min_window_seconds=(
            DEFAULT_STAGING_EVIDENCE_ACCEPTED_MIN_WINDOW_SECONDS
        ),
    )
    warned = capsys.readouterr().out

    assert "worker.maintenance.staging_accepted_retention_timeout_streak" in warned
    assert '"level": "warning"' in warned
    # The rejected pass finished cleanly all along, so its streak stayed at 0.
    assert evidence_retention._staging_timeout_streak == 0


def test_legacy_fallback_adapter_keys_names_the_fail_open_admissions() -> None:
    """The cadence rule is fail-open, so say out loud who got in by omission."""

    sources = [
        (REALTIME_SOURCE_ID, "official.cwa.rainfall"),
        (HISTORICAL_SOURCE_ID, "official.nstc.flood_disaster_points"),
        ("33333333-3333-4333-8333-333333333333", "news.public_web.gdelt_backfill"),
        ("44444444-4444-4444-8444-444444444444", "official.wra.flood_warning"),
    ]

    # Classified as realtime, and classified-and-excluded, are not fallbacks.
    assert legacy_fallback_adapter_keys(sources) == (
        "news.public_web.gdelt_backfill",
        "official.wra.flood_warning",
    )
    # They really are pruned -- this is a visibility test, not a filter test.
    assert is_orphan_prunable_adapter("news.public_web.gdelt_backfill") is True


def test_accepted_pass_logs_the_adapters_admitted_by_fallback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = _StagingFakeConnection(
        [0],
        accepted_batches=[0],
        data_sources=[
            (REALTIME_SOURCE_ID, "official.cwa.rainfall"),
            ("55555555-5555-4555-8555-555555555555", "official.wra.flood_incident"),
        ],
        oldest_accepted=AGED,
    )
    job = PostgresEvidenceRetentionJob(connection_factory=lambda: connection)

    job.prune_staging_evidence(accepted_window_seconds=WHOLE_SPAN_WINDOW_SECONDS)
    logged = capsys.readouterr().out

    assert "worker.maintenance.staging_accepted_retention_adapters" in logged
    assert "official.wra.flood_incident" in logged


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
    assert defaults.staging_evidence_accepted_retention_enabled is True
    assert defaults.staging_evidence_accepted_retention_max_batches == (
        DEFAULT_STAGING_EVIDENCE_ACCEPTED_MAX_BATCHES
    )
    assert defaults.staging_evidence_accepted_retention_window_seconds == (
        DEFAULT_STAGING_EVIDENCE_ACCEPTED_WINDOW_SECONDS
    )
    assert defaults.staging_evidence_accepted_retention_min_window_seconds == (
        DEFAULT_STAGING_EVIDENCE_ACCEPTED_MIN_WINDOW_SECONDS
    )

    overridden = load_worker_settings(
        {
            "STAGING_EVIDENCE_RETENTION_ENABLED": "false",
            "STAGING_EVIDENCE_RETENTION_ENSURE_INDEX": "false",
            "STAGING_EVIDENCE_RETENTION_DAYS": "14",
            "STAGING_EVIDENCE_RETENTION_MAX_BATCHES": "2",
            "STAGING_EVIDENCE_RETENTION_BATCH_SIZE": "1000",
            "STAGING_EVIDENCE_RETENTION_STATEMENT_TIMEOUT_MS": "9000",
            "STAGING_EVIDENCE_ACCEPTED_RETENTION_ENABLED": "false",
            "STAGING_EVIDENCE_ACCEPTED_RETENTION_MAX_BATCHES": "3",
            "STAGING_EVIDENCE_ACCEPTED_WINDOW_SECONDS": "1800",
            "STAGING_EVIDENCE_ACCEPTED_MIN_WINDOW_SECONDS": "120",
        }
    )
    assert overridden.staging_evidence_retention_enabled is False
    assert overridden.staging_evidence_retention_ensure_index is False
    assert overridden.staging_evidence_retention_days == 14
    assert overridden.staging_evidence_retention_max_batches == 2
    assert overridden.staging_evidence_retention_batch_size == 1000
    assert overridden.staging_evidence_retention_statement_timeout_ms == 9000
    assert overridden.staging_evidence_accepted_retention_enabled is False
    assert overridden.staging_evidence_accepted_retention_max_batches == 3
    assert overridden.staging_evidence_accepted_retention_window_seconds == 1800
    assert overridden.staging_evidence_accepted_retention_min_window_seconds == 120
