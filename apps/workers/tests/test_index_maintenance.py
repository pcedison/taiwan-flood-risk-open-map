"""Unit coverage for the concurrent evidence index rebuild policy.

Everything here runs against fake cursors, the same way
``tests/test_evidence_retention.py`` covers the staging prune: what matters is
which statements the job decides to send and when, not what PostgreSQL does
with them. ``tests/test_index_maintenance_postgres.py`` covers the real
rebuild.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.config import load_worker_settings
from app.jobs import index_maintenance
from app.jobs.index_maintenance import (
    DEFAULT_EVIDENCE_INDEX_REINDEX_MAX_INDEX_BYTES,
    DEFAULT_EVIDENCE_INDEX_REINDEX_MIN_SIZE_BYTES,
    EVIDENCE_REINDEX_INDEXES,
    MINIMUM_SERVER_VERSION_NUM,
    PostgresIndexMaintenanceJob,
)

# Inside the default 18:00-21:00 UTC window.
IN_WINDOW = datetime(2026, 9, 7, 19, 0, tzinfo=UTC)
# Taipei mid-morning: the traffic the window exists to stay away from.
OUT_OF_WINDOW = datetime(2026, 9, 7, 2, 0, tzinfo=UTC)

PRIMARY_INDEX = "idx_evidence_nearby_non_realtime_geom"
SECOND_INDEX = "idx_evidence_official_water_level_geom"
BLOATED = 200 * 1024 * 1024
REBUILT = 40 * 1024 * 1024


class _FakeDatabaseError(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(f"sqlstate {sqlstate}")
        self.sqlstate = sqlstate


class _FakeCursor:
    """Answers the questions the job asks, and records every statement.

    ``states`` maps an index name to the
    ``(size_bytes, reltuples, indisvalid, relfilenode)`` tuple the pg_class
    probe returns, or to ``None`` for an index that is not in the current
    schema. A rebuild swaps in ``after_sizes`` and a fresh relfilenode.

    ``leftovers`` are the dead ``_cc*`` indexes the leftover probe finds.
    ``swap_before_error`` reproduces the PostgreSQL 16 behaviour the reviewer
    measured: the rebuild is swapped in and *then* the statement fails while
    waiting for the last readers of the old index, leaving a ``_ccold``.
    """

    def __init__(
        self,
        *,
        states: dict[str, tuple[int, float, bool, int] | None],
        server_version_num: int = 160_004,
        reindex_error: Exception | None = None,
        after_sizes: dict[str, int] | None = None,
        leftovers: tuple[str, ...] = (),
        swap_before_error: bool = False,
    ) -> None:
        self.states = dict(states)
        self.server_version_num = server_version_num
        self.reindex_error = reindex_error
        self.after_sizes = dict(after_sizes or {})
        self.leftovers = list(leftovers)
        self.swap_before_error = swap_before_error
        self.statements: list[tuple[str, tuple[Any, ...] | None]] = []
        self._result: object = None
        self._rows: list[tuple[Any, ...]] = []
        self._next_relfilenode = 900_000

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def _swap(self, name: str) -> None:
        state = self.states.get(name)
        if state is None:
            return
        self._next_relfilenode += 1
        self.states[name] = (
            self.after_sizes.get(name, state[0]),
            state[1],
            True,
            self._next_relfilenode,
        )

    def execute(self, statement: Any, params: tuple[Any, ...] | None = None) -> None:
        text = (
            statement.as_string()
            if hasattr(statement, "as_string")
            else str(statement)
        )
        self.statements.append((text, params))
        self._result = None
        self._rows = []
        if "server_version_num" in text:
            self._result = (self.server_version_num,)
            return
        if "LIKE ANY" in text:
            assert params is not None
            prefixes = tuple(
                pattern.rstrip("%").replace("\\", "") for pattern in params[0]
            )
            self._rows = [
                (name,) for name in self.leftovers if name.startswith(prefixes)
            ]
            return
        if "pg_class" in text:
            assert params is not None
            self._result = self.states.get(str(params[0]))
            return
        if text.startswith("DROP INDEX CONCURRENTLY"):
            name = text.split('"')[1]
            if name in self.leftovers:
                self.leftovers.remove(name)
            return
        if text.startswith("REINDEX INDEX CONCURRENTLY"):
            name = text.split('"')[1]
            if self.reindex_error is not None:
                if self.swap_before_error:
                    self._swap(name)
                    self.leftovers.append(f"{name}_ccold")
                raise self.reindex_error
            self._swap(name)

    def fetchone(self) -> object:
        return self._result

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self.cursor_instance = cursor
        self.autocommit = False

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return self.cursor_instance

    def set_autocommit(self, value: bool) -> None:
        self.autocommit = value


@pytest.fixture(autouse=True)
def _reset_module_schedule() -> None:
    index_maintenance._last_reindex_at.clear()
    index_maintenance._last_attempt_at.clear()
    index_maintenance._last_logged = None


def _job(connection: _FakeConnection) -> PostgresIndexMaintenanceJob:
    return PostgresIndexMaintenanceJob(connection_factory=lambda: connection)


def _bloated(*names: str) -> dict[str, tuple[int, float, bool, int] | None]:
    return {
        name: (BLOATED, 2_270_000.0, True, 100_000 + position)
        for position, name in enumerate(names)
    }


def _drops(cursor: _FakeCursor) -> list[str]:
    return [
        text.split('"')[1]
        for text, _ in cursor.statements
        if text.startswith("DROP INDEX CONCURRENTLY")
    ]


def _reindex_log_lines(captured: str) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in captured.splitlines()
        if '"worker.maintenance.evidence_reindex"' in line
    ]


def _reindexes(cursor: _FakeCursor) -> list[str]:
    return [
        text
        for text, _ in cursor.statements
        if text.startswith("REINDEX INDEX CONCURRENTLY")
    ]


def test_reindex_rebuilds_the_first_eligible_index_and_reports_both_sizes() -> None:
    cursor = _FakeCursor(
        states=_bloated(PRIMARY_INDEX),
        after_sizes={PRIMARY_INDEX: REBUILT},
    )
    connection = _FakeConnection(cursor)

    summary = _job(connection).reindex_evidence_indexes(
        index_names=(PRIMARY_INDEX,), now=IN_WINDOW
    )

    assert summary.outcome == "reindexed"
    assert summary.index == PRIMARY_INDEX
    assert summary.before_bytes == BLOATED
    assert summary.after_bytes == REBUILT
    assert summary.reltuples == pytest.approx(2_270_000.0)
    # CONCURRENTLY cannot run inside a transaction block.
    assert connection.autocommit is True


def test_reindex_quotes_the_index_name_as_an_identifier() -> None:
    cursor = _FakeCursor(states=_bloated(PRIMARY_INDEX))
    _job(_FakeConnection(cursor)).reindex_evidence_indexes(
        index_names=(PRIMARY_INDEX,), now=IN_WINDOW
    )

    assert _reindexes(cursor) == [f'REINDEX INDEX CONCURRENTLY "{PRIMARY_INDEX}"']


def test_reindex_drops_every_dead_cc_leftover_before_rebuilding() -> None:
    """Reclaim the disk an unfinished attempt is still holding.

    The leftover blocks nothing -- PostgreSQL just takes the next free suffix --
    but it is a whole index's worth of disk, up to 933 MiB on the hosted node,
    and it appears as ``_ccnew`` before the swap and ``_ccold`` after it.
    """

    cursor = _FakeCursor(
        states=_bloated(PRIMARY_INDEX),
        leftovers=(
            f"{PRIMARY_INDEX}_ccnew",
            f"{PRIMARY_INDEX}_ccnew1",
            f"{PRIMARY_INDEX}_ccold",
            # A different index's corpse, and a real index that merely starts
            # the same way: neither is this rebuild's business.
            f"{SECOND_INDEX}_ccnew",
        ),
    )

    summary = _job(_FakeConnection(cursor)).reindex_evidence_indexes(
        index_names=(PRIMARY_INDEX,), now=IN_WINDOW
    )

    assert summary.leftovers_dropped == (
        f"{PRIMARY_INDEX}_ccnew",
        f"{PRIMARY_INDEX}_ccnew1",
        f"{PRIMARY_INDEX}_ccold",
    )
    assert _drops(cursor) == list(summary.leftovers_dropped)
    assert cursor.leftovers == [f"{SECOND_INDEX}_ccnew"]

    texts = [text for text, _ in cursor.statements]
    reindex_at = texts.index(f'REINDEX INDEX CONCURRENTLY "{PRIMARY_INDEX}"')
    last_drop = max(
        position
        for position, text in enumerate(texts)
        if text.startswith("DROP INDEX CONCURRENTLY")
    )
    assert last_drop < reindex_at


def test_reindex_only_drops_leftovers_the_planner_already_ignores() -> None:
    """Never a valid index: the probe filters on indisvalid, in this schema."""

    cursor = _FakeCursor(states=_bloated(PRIMARY_INDEX))
    _job(_FakeConnection(cursor)).reindex_evidence_indexes(
        index_names=(PRIMARY_INDEX,), now=IN_WINDOW
    )

    probe = next(text for text, _ in cursor.statements if "LIKE ANY" in text)
    assert "NOT idx.indisvalid" in probe
    assert "current_schema()::regnamespace" in probe


def test_reindex_treats_a_timeout_after_the_swap_as_success() -> None:
    """PostgreSQL 16 reports 55P03 over a rebuild that already happened.

    REINDEX CONCURRENTLY swaps the new index in and only then waits for the
    last readers of the old one; one idle-in-transaction reader holding
    AccessShareLock is enough to make that wait hit lock_timeout. Believing the
    error would rebuild the index again the next night and leave another dead
    copy behind every time.
    """

    cursor = _FakeCursor(
        states=_bloated(PRIMARY_INDEX),
        after_sizes={PRIMARY_INDEX: REBUILT},
        reindex_error=_FakeDatabaseError("55P03"),
        swap_before_error=True,
    )
    job = _job(_FakeConnection(cursor))

    summary = job.reindex_evidence_indexes(
        index_names=(PRIMARY_INDEX,), now=IN_WINDOW
    )

    assert summary.outcome == "reindexed_after_lock_timeout"
    assert summary.reindexed is True
    assert summary.before_bytes == BLOATED
    assert summary.after_bytes == REBUILT
    # Nothing is dropped in this cycle: whatever held the lock long enough to
    # fail the rebuild is still holding it, so a drop would only burn another
    # lock_timeout.
    assert summary.leftovers_dropped == ()
    assert cursor.leftovers == [f"{PRIMARY_INDEX}_ccold"]

    # The next cycle sweeps the dead copy up -- five minutes, not a week.
    next_cycle = job.reindex_evidence_indexes(
        index_names=(PRIMARY_INDEX,), now=IN_WINDOW + timedelta(minutes=5)
    )
    assert next_cycle.leftovers_dropped == (f"{PRIMARY_INDEX}_ccold",)
    assert cursor.leftovers == []

    # And the rebuild counts as done: the interval applies, so neither that
    # cycle nor the next night rebuilds it a second time.
    assert next_cycle.outcome == "skipped_no_candidate"
    assert next_cycle.skipped == {PRIMARY_INDEX: "skipped_interval"}
    assert len(_reindexes(cursor)) == 1


def test_reindex_still_fails_when_a_timeout_changed_nothing() -> None:
    """The relfilenode is the evidence, not the SQLSTATE."""

    cursor = _FakeCursor(
        states=_bloated(PRIMARY_INDEX),
        reindex_error=_FakeDatabaseError("55P03"),
        swap_before_error=False,
    )

    summary = _job(_FakeConnection(cursor)).reindex_evidence_indexes(
        index_names=(PRIMARY_INDEX,), now=IN_WINDOW
    )

    assert summary.outcome == "failed:55P03"


def test_reindex_does_not_second_guess_an_unrelated_failure() -> None:
    cursor = _FakeCursor(
        states=_bloated(PRIMARY_INDEX),
        reindex_error=_FakeDatabaseError("53100"),  # disk full
        swap_before_error=True,
    )

    summary = _job(_FakeConnection(cursor)).reindex_evidence_indexes(
        index_names=(PRIMARY_INDEX,), now=IN_WINDOW
    )

    assert summary.outcome == "failed:53100"


def test_reindex_sets_lock_and_statement_timeouts_at_session_level() -> None:
    cursor = _FakeCursor(states=_bloated(PRIMARY_INDEX))
    _job(_FakeConnection(cursor)).reindex_evidence_indexes(
        index_names=(PRIMARY_INDEX,),
        lock_timeout_ms=5_000,
        statement_timeout_ms=1_800_000,
        now=IN_WINDOW,
    )

    timeouts = [
        (text, params) for text, params in cursor.statements if "set_config" in text
    ]
    assert len(timeouts) == 1
    text, params = timeouts[0]
    # is_local false: REINDEX CONCURRENTLY runs outside a transaction block, so
    # a transaction-local setting would not cover it.
    assert "'lock_timeout', %s, false" in text
    assert "'statement_timeout', %s, false" in text
    assert params == ("5000ms", "1800000ms")


def test_reindex_rebuilds_at_most_one_index_per_maintenance_cycle() -> None:
    """A cycle is 300 s; a rebuild is minutes. Never queue two in one cycle."""

    cursor = _FakeCursor(states=_bloated(PRIMARY_INDEX, SECOND_INDEX))
    summary = _job(_FakeConnection(cursor)).reindex_evidence_indexes(
        index_names=(PRIMARY_INDEX, SECOND_INDEX), now=IN_WINDOW
    )

    assert summary.index == PRIMARY_INDEX
    assert _reindexes(cursor) == [f'REINDEX INDEX CONCURRENTLY "{PRIMARY_INDEX}"']
    # The second index was never even probed: the loop stops at the first one
    # it can act on.
    assert summary.skipped == {}


def test_reindex_stops_after_the_per_window_budget_is_spent() -> None:
    """A three-hour window is 36 cycles; do not rebuild the whole list at once.

    Back-to-back rebuilds are an I/O and WAL spike on a 2 GB node, and all of
    the work is optional. Two a night spreads the default seven over three.
    """

    third = "idx_evidence_official_rainfall_geom"
    names = (PRIMARY_INDEX, SECOND_INDEX, third)
    cursor = _FakeCursor(states=_bloated(*names))
    job = _job(_FakeConnection(cursor))

    first = job.reindex_evidence_indexes(index_names=names, now=IN_WINDOW)
    second = job.reindex_evidence_indexes(
        index_names=names, now=IN_WINDOW + timedelta(minutes=5)
    )
    third_cycle = job.reindex_evidence_indexes(
        index_names=names, now=IN_WINDOW + timedelta(minutes=10)
    )

    assert (first.index, second.index) == (PRIMARY_INDEX, SECOND_INDEX)
    assert third_cycle.outcome == "skipped_window_budget"
    assert third_cycle.index is None
    # The budget is checked before anything is opened, so the third cycle costs
    # nothing at all.
    assert len(_reindexes(cursor)) == 2

    # The next night starts a fresh budget.
    tomorrow = job.reindex_evidence_indexes(
        index_names=names, now=IN_WINDOW + timedelta(days=1)
    )
    assert tomorrow.outcome == "reindexed"
    assert tomorrow.index == third


def test_reindex_per_window_budget_is_configurable() -> None:
    names = (PRIMARY_INDEX, SECOND_INDEX)
    cursor = _FakeCursor(states=_bloated(*names))
    job = _job(_FakeConnection(cursor))

    job.reindex_evidence_indexes(
        index_names=names, max_per_window=1, now=IN_WINDOW
    )
    second = job.reindex_evidence_indexes(
        index_names=names, max_per_window=1, now=IN_WINDOW + timedelta(minutes=5)
    )

    assert second.outcome == "skipped_window_budget"
    assert len(_reindexes(cursor)) == 1


def test_reindex_rejects_a_zero_per_window_budget() -> None:
    cursor = _FakeCursor(states=_bloated(PRIMARY_INDEX))

    with pytest.raises(ValueError, match="max_per_window"):
        _job(_FakeConnection(cursor)).reindex_evidence_indexes(
            index_names=(PRIMARY_INDEX,), max_per_window=0, now=IN_WINDOW
        )


def test_reindex_says_nothing_at_all_outside_the_window(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """21 hours a day x one cycle per 300 s would be 288 lines nobody reads."""

    cursor = _FakeCursor(states=_bloated(PRIMARY_INDEX))
    job = _job(_FakeConnection(cursor))

    for minute in range(0, 30, 5):
        job.reindex_evidence_indexes(
            index_names=(PRIMARY_INDEX,), now=OUT_OF_WINDOW + timedelta(minutes=minute)
        )

    assert _reindex_log_lines(capsys.readouterr().out) == []


def test_reindex_logs_each_distinct_answer_once_per_window(
    capsys: pytest.CaptureFixture[str],
) -> None:
    cursor = _FakeCursor(states=_bloated(PRIMARY_INDEX))
    job = _job(_FakeConnection(cursor))

    # Cycle 1 rebuilds; cycles 2-4 have nothing left to do and say so once.
    for minute in (0, 5, 10, 15):
        job.reindex_evidence_indexes(
            index_names=(PRIMARY_INDEX,), now=IN_WINDOW + timedelta(minutes=minute)
        )

    lines = _reindex_log_lines(capsys.readouterr().out)
    assert [line["outcome"] for line in lines] == [
        "reindexed",
        "skipped_no_candidate",
    ]
    assert lines[0]["index"] == PRIMARY_INDEX
    assert lines[0]["leftovers_dropped"] == []
    assert lines[1]["skipped"] == {PRIMARY_INDEX: "skipped_interval"}


def test_reindex_logs_again_in_the_next_window(
    capsys: pytest.CaptureFixture[str],
) -> None:
    cursor = _FakeCursor(states={PRIMARY_INDEX: None})
    job = _job(_FakeConnection(cursor))

    job.reindex_evidence_indexes(index_names=(PRIMARY_INDEX,), now=IN_WINDOW)
    job.reindex_evidence_indexes(
        index_names=(PRIMARY_INDEX,), now=IN_WINDOW + timedelta(minutes=5)
    )
    job.reindex_evidence_indexes(
        index_names=(PRIMARY_INDEX,), now=IN_WINDOW + timedelta(days=1)
    )

    outcomes = [line["outcome"] for line in _reindex_log_lines(capsys.readouterr().out)]
    assert outcomes == ["skipped_no_candidate", "skipped_no_candidate"]


def test_reindex_skips_entirely_outside_the_maintenance_window() -> None:
    cursor = _FakeCursor(states=_bloated(PRIMARY_INDEX))
    summary = _job(_FakeConnection(cursor)).reindex_evidence_indexes(
        index_names=(PRIMARY_INDEX,), now=OUT_OF_WINDOW
    )

    assert summary.outcome == "skipped_outside_window"
    assert summary.index is None
    # Not one statement, so no connection is even opened outside the window.
    assert cursor.statements == []


def test_reindex_window_may_cross_midnight() -> None:
    cursor = _FakeCursor(states=_bloated(PRIMARY_INDEX))
    summary = _job(_FakeConnection(cursor)).reindex_evidence_indexes(
        index_names=(PRIMARY_INDEX,),
        window_utc="22:00-02:00",
        now=datetime(2026, 9, 7, 0, 30, tzinfo=UTC),
    )

    assert summary.outcome == "reindexed"


def test_reindex_honours_the_per_index_interval() -> None:
    cursor = _FakeCursor(states=_bloated(PRIMARY_INDEX))
    job = _job(_FakeConnection(cursor))

    first = job.reindex_evidence_indexes(index_names=(PRIMARY_INDEX,), now=IN_WINDOW)
    second = job.reindex_evidence_indexes(
        index_names=(PRIMARY_INDEX,), now=IN_WINDOW + timedelta(days=1)
    )

    assert first.outcome == "reindexed"
    assert second.outcome == "skipped_no_candidate"
    assert second.skipped == {PRIMARY_INDEX: "skipped_interval"}
    assert len(_reindexes(cursor)) == 1


def test_reindex_moves_to_the_next_index_once_the_first_is_recent() -> None:
    cursor = _FakeCursor(states=_bloated(PRIMARY_INDEX, SECOND_INDEX))
    job = _job(_FakeConnection(cursor))
    names = (PRIMARY_INDEX, SECOND_INDEX)

    job.reindex_evidence_indexes(index_names=names, now=IN_WINDOW)
    second = job.reindex_evidence_indexes(
        index_names=names, now=IN_WINDOW + timedelta(days=1)
    )

    assert second.outcome == "reindexed"
    assert second.index == SECOND_INDEX
    assert second.skipped == {PRIMARY_INDEX: "skipped_interval"}


def test_reindex_after_the_interval_elapses_rebuilds_again() -> None:
    cursor = _FakeCursor(states=_bloated(PRIMARY_INDEX))
    job = _job(_FakeConnection(cursor))

    job.reindex_evidence_indexes(index_names=(PRIMARY_INDEX,), now=IN_WINDOW)
    later = job.reindex_evidence_indexes(
        index_names=(PRIMARY_INDEX,), now=IN_WINDOW + timedelta(hours=169)
    )

    assert later.outcome == "reindexed"


def test_reindex_failure_is_logged_and_not_retried_in_the_same_window() -> None:
    cursor = _FakeCursor(
        states=_bloated(PRIMARY_INDEX),
        reindex_error=_FakeDatabaseError("55P03"),
    )
    job = _job(_FakeConnection(cursor))

    failed = job.reindex_evidence_indexes(index_names=(PRIMARY_INDEX,), now=IN_WINDOW)
    same_window = job.reindex_evidence_indexes(
        index_names=(PRIMARY_INDEX,), now=IN_WINDOW + timedelta(minutes=30)
    )

    # A refused lock is reported by SQLSTATE, not by exception class, so the
    # log says which bound was hit.
    assert failed.outcome == "failed:55P03"
    assert failed.index == PRIMARY_INDEX
    assert failed.before_bytes == BLOATED
    assert same_window.outcome == "skipped_no_candidate"
    assert same_window.skipped == {PRIMARY_INDEX: "skipped_attempted"}
    assert len(_reindexes(cursor)) == 1


def test_reindex_retries_a_failed_index_in_the_next_window() -> None:
    cursor = _FakeCursor(
        states=_bloated(PRIMARY_INDEX),
        reindex_error=_FakeDatabaseError("57014"),
    )
    job = _job(_FakeConnection(cursor))

    job.reindex_evidence_indexes(index_names=(PRIMARY_INDEX,), now=IN_WINDOW)
    next_window = job.reindex_evidence_indexes(
        index_names=(PRIMARY_INDEX,), now=IN_WINDOW + timedelta(days=1)
    )

    assert next_window.outcome == "failed:57014"
    assert len(_reindexes(cursor)) == 2


def test_reindex_failure_without_a_sqlstate_reports_the_exception_class() -> None:
    cursor = _FakeCursor(
        states=_bloated(PRIMARY_INDEX), reindex_error=RuntimeError("boom")
    )
    summary = _job(_FakeConnection(cursor)).reindex_evidence_indexes(
        index_names=(PRIMARY_INDEX,), now=IN_WINDOW
    )

    assert summary.outcome == "failed:RuntimeError"


def test_reindex_never_raises_when_the_connection_cannot_be_opened() -> None:
    def explode() -> Any:
        raise _FakeDatabaseError("08006")

    job = PostgresIndexMaintenanceJob(connection_factory=explode)

    summary = job.reindex_evidence_indexes(
        index_names=(PRIMARY_INDEX,), now=IN_WINDOW
    )

    assert summary.outcome == "failed:08006"
    assert summary.index is None


def test_reindex_skips_an_index_that_is_not_in_the_current_schema() -> None:
    cursor = _FakeCursor(states={PRIMARY_INDEX: None})
    summary = _job(_FakeConnection(cursor)).reindex_evidence_indexes(
        index_names=(PRIMARY_INDEX,), now=IN_WINDOW
    )

    assert summary.skipped == {PRIMARY_INDEX: "skipped_missing"}
    assert _reindexes(cursor) == []


def test_reindex_probe_is_scoped_to_the_current_schema() -> None:
    """Two schemas can hold the same index name; the acceptance test is one."""

    cursor = _FakeCursor(states=_bloated(PRIMARY_INDEX))
    _job(_FakeConnection(cursor)).reindex_evidence_indexes(
        index_names=(PRIMARY_INDEX,), now=IN_WINDOW
    )

    probe = next(text for text, _ in cursor.statements if "pg_class" in text)
    assert "current_schema()::regnamespace" in probe


def test_reindex_leaves_an_invalid_index_for_a_human() -> None:
    cursor = _FakeCursor(states={PRIMARY_INDEX: (BLOATED, 10.0, False, 100_000)})
    summary = _job(_FakeConnection(cursor)).reindex_evidence_indexes(
        index_names=(PRIMARY_INDEX,), now=IN_WINDOW
    )

    assert summary.skipped == {PRIMARY_INDEX: "skipped_invalid"}
    assert _reindexes(cursor) == []


def test_reindex_skips_an_index_below_the_size_floor() -> None:
    cursor = _FakeCursor(
        states={
            PRIMARY_INDEX: (
                DEFAULT_EVIDENCE_INDEX_REINDEX_MIN_SIZE_BYTES - 1,
                5.0,
                True,
                100_000,
            )
        }
    )
    summary = _job(_FakeConnection(cursor)).reindex_evidence_indexes(
        index_names=(PRIMARY_INDEX,), now=IN_WINDOW
    )

    assert summary.skipped == {PRIMARY_INDEX: "skipped_small"}
    assert _reindexes(cursor) == []


def test_reindex_skips_an_index_too_large_to_duplicate_safely() -> None:
    """A concurrent rebuild needs the index's own size again in free disk.

    The hosted database is ~30 GB on a Zeabur volume whose free space nothing
    here can read, and filling it locks the table -- the #317 failure mode this
    job exists to avoid. So the 933 MiB evidence_source_raw_ref_unique waits
    until an operator has checked the volume and raised the ceiling.
    """

    huge = "evidence_source_raw_ref_unique"
    cursor = _FakeCursor(
        states={
            huge: (978 * 1024 * 1024, 2_270_000.0, True, 100_100),
            **_bloated(PRIMARY_INDEX),
        }
    )

    summary = _job(_FakeConnection(cursor)).reindex_evidence_indexes(
        index_names=(huge, PRIMARY_INDEX), now=IN_WINDOW
    )

    # And skipping it does not use up the cycle's single rebuild: the next
    # index on the list still gets its turn.
    assert summary.outcome == "reindexed"
    assert summary.index == PRIMARY_INDEX
    assert summary.skipped == {huge: "skipped_too_large"}
    assert _reindexes(cursor) == [f'REINDEX INDEX CONCURRENTLY "{PRIMARY_INDEX}"']


def test_reindex_rebuilds_a_large_index_once_the_ceiling_is_raised() -> None:
    huge = "evidence_source_raw_ref_unique"
    cursor = _FakeCursor(states={huge: (978 * 1024 * 1024, 2_270_000.0, True, 100_100)})

    summary = _job(_FakeConnection(cursor)).reindex_evidence_indexes(
        index_names=(huge,),
        max_index_bytes=2 * 1024 * 1024 * 1024,
        now=IN_WINDOW,
    )

    assert summary.outcome == "reindexed"
    assert summary.index == huge


def test_reindex_rejects_a_ceiling_at_or_below_the_size_floor() -> None:
    cursor = _FakeCursor(states=_bloated(PRIMARY_INDEX))

    with pytest.raises(ValueError, match="greater than min_size_bytes"):
        _job(_FakeConnection(cursor)).reindex_evidence_indexes(
            index_names=(PRIMARY_INDEX,),
            min_size_bytes=8 * 1024 * 1024,
            max_index_bytes=8 * 1024 * 1024,
            now=IN_WINDOW,
        )


def test_default_ceiling_holds_back_the_largest_hosted_evidence_index() -> None:
    """933 MiB (evidence_source_raw_ref_unique on 2026-09-07) is over it."""

    assert DEFAULT_EVIDENCE_INDEX_REINDEX_MAX_INDEX_BYTES == 512 * 1024 * 1024
    assert 933 * 1024 * 1024 > DEFAULT_EVIDENCE_INDEX_REINDEX_MAX_INDEX_BYTES
    # ...and the partial GiST index the read path scans (52 MiB) is well under.
    assert 52 * 1024 * 1024 < DEFAULT_EVIDENCE_INDEX_REINDEX_MAX_INDEX_BYTES


def test_reindex_disables_itself_below_postgresql_12() -> None:
    """REINDEX CONCURRENTLY is 12+; the fallback takes ACCESS EXCLUSIVE."""

    cursor = _FakeCursor(
        states=_bloated(PRIMARY_INDEX),
        server_version_num=MINIMUM_SERVER_VERSION_NUM - 1,
    )
    summary = _job(_FakeConnection(cursor)).reindex_evidence_indexes(
        index_names=(PRIMARY_INDEX,), now=IN_WINDOW
    )

    assert summary.outcome == "skipped_unsupported"
    assert _reindexes(cursor) == []
    # The version gate runs before any index is even looked up.
    assert not any("pg_class" in text for text, _ in cursor.statements)


@pytest.mark.parametrize(
    "name",
    [
        'evidence"; DROP TABLE evidence; --',
        "public.idx_evidence_geom",
        "IDX_EVIDENCE_GEOM",
        "idx evidence geom",
    ],
)
def test_reindex_rejects_index_names_that_are_not_plain_identifiers(name: str) -> None:
    cursor = _FakeCursor(states=_bloated(PRIMARY_INDEX))

    with pytest.raises(ValueError, match="invalid index name"):
        _job(_FakeConnection(cursor)).reindex_evidence_indexes(
            index_names=(name,), now=IN_WINDOW
        )

    assert cursor.statements == []


def test_reindex_rejects_an_empty_index_list() -> None:
    cursor = _FakeCursor(states={})

    with pytest.raises(ValueError, match="at least one index name"):
        _job(_FakeConnection(cursor)).reindex_evidence_indexes(
            index_names=(), now=IN_WINDOW
        )


@pytest.mark.parametrize("window", ["18:00", "18:00-18:00", "25:00-26:00", "later"])
def test_reindex_rejects_a_malformed_window(window: str) -> None:
    cursor = _FakeCursor(states=_bloated(PRIMARY_INDEX))

    with pytest.raises(ValueError, match="maintenance window"):
        _job(_FakeConnection(cursor)).reindex_evidence_indexes(
            index_names=(PRIMARY_INDEX,), window_utc=window, now=IN_WINDOW
        )


def test_default_index_list_targets_the_evidence_indexes_that_bloat() -> None:
    """Order is the policy: the assessment read path is rebuilt first."""

    assert EVIDENCE_REINDEX_INDEXES == (
        "idx_evidence_nearby_non_realtime_geom",
        "idx_evidence_official_water_level_geom",
        "idx_evidence_official_rainfall_geom",
        "idx_evidence_observed_flood_history_geom",
        "idx_evidence_geom_geography",
        "idx_evidence_staging_evidence_id",
        "evidence_source_raw_ref_unique",
    )


def test_settings_default_to_the_low_traffic_taipei_window() -> None:
    settings = load_worker_settings({})

    assert settings.evidence_index_reindex_enabled is True
    # 18:00-21:00 UTC is 02:00-05:00 in Taipei.
    assert settings.evidence_index_reindex_window_utc == "18:00-21:00"
    assert settings.evidence_index_reindex_interval_hours == 168
    assert settings.evidence_index_reindex_min_size_bytes == 8 * 1024 * 1024
    assert settings.evidence_index_reindex_max_index_bytes == 512 * 1024 * 1024
    assert settings.evidence_index_reindex_max_per_window == 2
    assert settings.evidence_index_reindex_lock_timeout_ms == 5_000
    assert settings.evidence_index_reindex_statement_timeout_ms == 1_800_000
    # None means "whatever the job's own list says".
    assert settings.evidence_index_reindex_indexes is None


def test_settings_can_override_the_index_list_and_the_window() -> None:
    settings = load_worker_settings(
        {
            "EVIDENCE_INDEX_REINDEX_ENABLED": "false",
            "EVIDENCE_INDEX_REINDEX_INDEXES": f"{PRIMARY_INDEX}, {SECOND_INDEX}",
            "EVIDENCE_INDEX_REINDEX_WINDOW_UTC": "22:00-02:00",
            "EVIDENCE_INDEX_REINDEX_INTERVAL_HOURS": "24",
            "EVIDENCE_INDEX_REINDEX_MIN_SIZE_BYTES": "1048576",
            "EVIDENCE_INDEX_REINDEX_MAX_INDEX_BYTES": "2147483648",
        }
    )

    assert settings.evidence_index_reindex_enabled is False
    assert settings.evidence_index_reindex_indexes == (PRIMARY_INDEX, SECOND_INDEX)
    assert settings.evidence_index_reindex_window_utc == "22:00-02:00"
    assert settings.evidence_index_reindex_interval_hours == 24
    assert settings.evidence_index_reindex_min_size_bytes == 1_048_576
    assert settings.evidence_index_reindex_max_index_bytes == 2_147_483_648
