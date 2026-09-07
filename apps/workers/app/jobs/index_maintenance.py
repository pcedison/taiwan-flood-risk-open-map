"""Online index rebuilds for the high-churn ``evidence`` table.

``evidence`` is written and deleted continuously: realtime station rows are
inserted every ingestion cycle and deleted 48 h later (see
``jobs/evidence_retention.py``), and every NSTC/WRA historical snapshot
re-imports a whole batch before the previous one is dropped. Neither VACUUM nor
autovacuum hands an index page back, so the indexes only ever grow, and an
incrementally built GiST index accumulates overlapping bounding boxes that a
search has to descend into. On the hosted node (2026-09-07) ``evidence`` is
2.27 M rows / 5.4 GB of heap under 2.26 GB of indexes, and the
``nearby_evidence`` probe read 2 875 cold shared blocks in 1.87 s to fetch 168
candidate rows whose geometry and properties add up to 0.1 MiB -- nearly all of
those blocks are index pages, not data.

``REINDEX INDEX CONCURRENTLY`` (PostgreSQL 12+) rebuilds an index without
locking out writers, and from PostgreSQL 14 a GiST build sorts entries along a
space-filling curve, so a rebuilt bbox index answers a 500 m search from a few
pages instead of walking overlapping ones.

Why this is a worker job and not a migration: migrations run inside the API
start-up transaction, so building an index there locks a large table and takes
the site down (#317). This is the same shape as
``evidence_retention._ensure_rejected_index``: an autocommit connection,
``CONCURRENTLY``, and a ``pg_index.indisvalid`` check before trusting anything.

The policy is deliberately dull, because a rebuild costs minutes of extra I/O
on a 2 GB node:

* only inside a UTC maintenance window (default 18:00-21:00 UTC, which is
  02:00-05:00 Taipei, the daily traffic trough);
* at most one index per maintenance cycle, so no cycle runs for an hour;
* at most ``max_per_window`` rebuilds per window (default 2), so the first
  night after a deploy is not 36 back-to-back rebuilds;
* at most one rebuild per index per ``interval_hours`` (default one week);
* at most one *attempt* per index per window, so a failing rebuild cannot spin;
* nothing above ``max_index_bytes``, because a concurrent rebuild needs the
  index's own size again in free disk and this job cannot see how much the
  hosted volume has left.

The "when did this last run" state lives in module-level dicts, the same
trade-off ``evidence_retention._staging_timeout_streak`` makes: the scheduler is
a single long-lived process and the sole writer. A restart forgets the history,
so the next window rebuilds one more round, and an index that failed earlier in
the current window is retried inside it; that is wasted I/O inside a
low-traffic window, never a correctness problem.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from typing import Any

from psycopg import sql

from app.logging import log_event

ConnectionFactory = Callable[[], Any]

# Ordered by how much the hosted node stands to gain. The partial GiST index
# that serves the assessment read path comes first: it is the one the
# nearby_evidence probe walks (191 scans / 317 k tuples read, 1.87 s cold).
# The two btrees are last because they are already selective -- they are here
# for bloat, not for plan shape.
EVIDENCE_REINDEX_INDEXES: tuple[str, ...] = (
    "idx_evidence_nearby_non_realtime_geom",
    "idx_evidence_official_water_level_geom",
    "idx_evidence_official_rainfall_geom",
    "idx_evidence_observed_flood_history_geom",
    "idx_evidence_geom_geography",
    "idx_evidence_staging_evidence_id",
    "evidence_source_raw_ref_unique",
)

DEFAULT_EVIDENCE_INDEX_REINDEX_WINDOW_UTC = "18:00-21:00"
DEFAULT_EVIDENCE_INDEX_REINDEX_INTERVAL_HOURS = 168
# Rebuilding a small index costs about as much as leaving it bloated, and the
# hosted numbers make 8 MiB the natural floor: every evidence index worth
# rebuilding there is 7.5 MiB or larger.
DEFAULT_EVIDENCE_INDEX_REINDEX_MIN_SIZE_BYTES = 8 * 1024 * 1024
# The old and the new index coexist for the whole of a concurrent rebuild, so
# the operation needs its own size again in free space. The hosted database is
# ~30 GB on a Zeabur volume whose free space nothing here can read, and running
# it out of space would lock the table and take the node down -- the #317
# failure mode this job exists to avoid. So a ceiling, low enough that the
# 933 MiB evidence_source_raw_ref_unique waits until an operator has looked at
# the volume and raised it deliberately.
DEFAULT_EVIDENCE_INDEX_REINDEX_MAX_INDEX_BYTES = 512 * 1024 * 1024
# One index per 300 s cycle still means up to 36 rebuilds in a three-hour
# window, so the first night after a deploy would rebuild the whole list back
# to back -- an I/O and WAL spike on a 2 GB node, all of it optional work. Two
# per night spreads the default list of seven over about three nights.
DEFAULT_EVIDENCE_INDEX_REINDEX_MAX_PER_WINDOW = 2
DEFAULT_EVIDENCE_INDEX_REINDEX_LOCK_TIMEOUT_MS = 5_000
DEFAULT_EVIDENCE_INDEX_REINDEX_STATEMENT_TIMEOUT_MS = 1_800_000
# A rebuild that starts late in the window would otherwise run its whole
# statement_timeout past the window's end, into the traffic the window exists
# to keep clear. One rebuild's budget is therefore the configured timeout or
# the time left in the window, whichever is less, and a cycle with less than
# this left does not start one at all.
DEFAULT_EVIDENCE_INDEX_REINDEX_MIN_REMAINING_SECONDS = 600
# REINDEX ... CONCURRENTLY landed in PostgreSQL 12. Below that the only
# rebuild available takes an ACCESS EXCLUSIVE lock, which is exactly what this
# job exists to avoid, so the whole pass turns itself off instead.
MINIMUM_SERVER_VERSION_NUM = 120_000

# psycopg.sql.Identifier already quotes and escapes, so this is belt and
# braces: an operator-supplied name that is not a plain lower-case identifier
# is a typo or an injection attempt, and either way the job refuses it rather
# than sending it to the server.
INDEX_NAME_PATTERN = re.compile(r"^[a-z0-9_]+$")

_WINDOW_PATTERN = re.compile(r"^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$")

# A REINDEX CONCURRENTLY that does not finish leaves a transient index behind,
# invalid and invisible to the planner but holding a full index's worth of disk
# -- 933 MiB in the worst hosted case. Which one depends on how far it got:
# "<name>_ccnew" if it died before the swap, "<name>_ccold" (the *old* index,
# now dead) if it died after, and "_ccnew1"/"_ccold1" and so on when an earlier
# corpse still occupies the plain name.
#
# The leftover does not block anything -- PostgreSQL just picks the next free
# suffix -- so this is purely about giving the disk back, which on a 2 GB node
# with a ~30 GB database is reason enough.
CC_LEFTOVER_INFIX = "_cc"

# A REINDEX CONCURRENTLY can time out *after* it has already swapped the new
# index in, while waiting for the last readers of the old one (measured on
# PostgreSQL 16: an idle-in-transaction reader holding AccessShareLock blocks
# that final wait, and lock_timeout fires with the rebuild already done). The
# statement reports failure, but the index is rebuilt and valid. Treating that
# as a failure would rebuild it again the next night, and leave another corpse
# each time, so these two SQLSTATEs get a second look before being believed.
_POST_SWAP_RECOVERABLE_SQLSTATES = frozenset({"55P03", "57014"})

REINDEXED_OUTCOMES = ("reindexed", "reindexed_after_lock_timeout")

# The scheduler builds a fresh job per maintenance cycle, so the schedule has
# to outlive the instance. The scheduler process is the single writer.
_last_reindex_at: dict[str, datetime] = {}
_last_attempt_at: dict[str, datetime] = {}
# The last line this pass actually logged, as (window, outcome, index). A cycle
# runs every 300 s and almost always has nothing to say, so it says it once per
# window per distinct answer instead of every five minutes.
_last_logged: tuple[datetime, str, str | None, tuple[str, ...]] | None = None


@dataclass(frozen=True)
class EvidenceReindexSummary:
    """What one maintenance cycle did, or why it did nothing."""

    outcome: str
    index: str | None
    window_utc: str
    before_bytes: int | None = None
    after_bytes: int | None = None
    reltuples: float | None = None
    elapsed_ms: int = 0
    skipped: Mapping[str, str] = field(default_factory=dict)
    leftovers_dropped: tuple[str, ...] = ()
    # What the rebuild was allowed: the configured statement_timeout capped by
    # the time left in the window when it started.
    budget_ms: int | None = None

    @property
    def reindexed(self) -> bool:
        return self.outcome in REINDEXED_OUTCOMES

    def log_fields(self) -> dict[str, object]:
        return {
            "index": self.index,
            "outcome": self.outcome,
            "window_utc": self.window_utc,
            "before_bytes": self.before_bytes,
            "after_bytes": self.after_bytes,
            "reltuples": self.reltuples,
            "elapsed_ms": self.elapsed_ms,
            "skipped": dict(self.skipped),
            "leftovers_dropped": list(self.leftovers_dropped),
            "budget_ms": self.budget_ms,
        }


@dataclass(frozen=True)
class _IndexState:
    size_bytes: int
    reltuples: float
    indisvalid: bool
    # Changes on every rebuild, which is the only way to tell "the swap already
    # happened" from "nothing was done" after an ambiguous timeout.
    relfilenode: int


class PostgresIndexMaintenanceJob:
    def __init__(
        self,
        *,
        database_url: str | None = None,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        if database_url is None and connection_factory is None:
            raise ValueError("database_url or connection_factory is required")
        self._database_url = database_url
        self._connection_factory = connection_factory

    def reindex_evidence_indexes(
        self,
        *,
        index_names: Sequence[str] | None = None,
        window_utc: str = DEFAULT_EVIDENCE_INDEX_REINDEX_WINDOW_UTC,
        interval_hours: int = DEFAULT_EVIDENCE_INDEX_REINDEX_INTERVAL_HOURS,
        min_size_bytes: int = DEFAULT_EVIDENCE_INDEX_REINDEX_MIN_SIZE_BYTES,
        max_index_bytes: int = DEFAULT_EVIDENCE_INDEX_REINDEX_MAX_INDEX_BYTES,
        max_per_window: int = DEFAULT_EVIDENCE_INDEX_REINDEX_MAX_PER_WINDOW,
        lock_timeout_ms: int = DEFAULT_EVIDENCE_INDEX_REINDEX_LOCK_TIMEOUT_MS,
        statement_timeout_ms: int = DEFAULT_EVIDENCE_INDEX_REINDEX_STATEMENT_TIMEOUT_MS,
        min_remaining_seconds: int = DEFAULT_EVIDENCE_INDEX_REINDEX_MIN_REMAINING_SECONDS,
        now: datetime | None = None,
    ) -> EvidenceReindexSummary:
        """Rebuild at most one bloated ``evidence`` index, concurrently.

        Never raises for a database-side failure: a refused lock, a cancelled
        statement, or an unreachable server is logged and the maintenance cycle
        carries on. A malformed configuration (an index name that is not a
        plain identifier, an unparseable window) is a caller error and does
        raise ``ValueError`` -- silently ignoring it would leave the operator
        believing rebuilds are happening.
        """

        resolved_names = _validated_index_names(
            EVIDENCE_REINDEX_INDEXES if index_names is None else index_names
        )
        window = _parse_window(window_utc)
        if interval_hours < 1:
            raise ValueError("interval_hours must be a positive integer")
        if min_size_bytes < 0:
            raise ValueError("min_size_bytes must not be negative")
        if max_index_bytes < 1:
            raise ValueError("max_index_bytes must be a positive integer")
        if max_index_bytes <= min_size_bytes:
            raise ValueError("max_index_bytes must be greater than min_size_bytes")
        if max_per_window < 1:
            raise ValueError("max_per_window must be a positive integer")
        if lock_timeout_ms < 1:
            raise ValueError("lock_timeout_ms must be a positive integer")
        if statement_timeout_ms < 1:
            raise ValueError("statement_timeout_ms must be a positive integer")
        if min_remaining_seconds < 1:
            raise ValueError("min_remaining_seconds must be a positive integer")

        resolved_now = (now or _now()).astimezone(UTC)
        window_started_at = _window_started_at(resolved_now, window)
        if window_started_at is None:
            return _log_summary(
                EvidenceReindexSummary(
                    outcome="skipped_outside_window",
                    index=None,
                    window_utc=window_utc,
                ),
                window_started_at=None,
            )

        if _rebuilds_in_window(window_started_at) >= max_per_window:
            return _log_summary(
                EvidenceReindexSummary(
                    outcome="skipped_window_budget",
                    index=None,
                    window_utc=window_utc,
                ),
                window_started_at=window_started_at,
            )

        # The window is a promise to the morning traffic, and a rebuild
        # started at 20:59 with a 30 minute timeout would break it. Whatever
        # is left of the window is the most a rebuild may take; too little
        # left and this cycle does not open a connection at all.
        remaining_seconds = int(
            (_window_ends_at(window_started_at, window) - resolved_now).total_seconds()
        )
        # Strictly more than the floor has to be left, because the cycle's own
        # preamble is charged to the budget as one whole second.
        if remaining_seconds <= min_remaining_seconds:
            return _log_summary(
                EvidenceReindexSummary(
                    outcome="skipped_window_closing",
                    index=None,
                    window_utc=window_utc,
                ),
                window_started_at=window_started_at,
            )

        try:
            summary = self._reindex_first_eligible(
                index_names=resolved_names,
                window_utc=window_utc,
                window_started_at=window_started_at,
                interval_hours=interval_hours,
                min_size_bytes=min_size_bytes,
                max_index_bytes=max_index_bytes,
                lock_timeout_ms=lock_timeout_ms,
                statement_timeout_ms=statement_timeout_ms,
                min_remaining_seconds=min_remaining_seconds,
                remaining_seconds=remaining_seconds,
                cycle_started_at=_now(),
                now=resolved_now,
            )
        except Exception as exc:
            # Connecting or probing failed before any index was chosen. There
            # is nothing to retry inside this cycle and nothing half-done to
            # clean up, so record it and let maintenance finish.
            summary = EvidenceReindexSummary(
                outcome=f"failed:{_failure_code(exc)}",
                index=None,
                window_utc=window_utc,
            )
        return _log_summary(summary, window_started_at=window_started_at)

    def _reindex_first_eligible(
        self,
        *,
        index_names: tuple[str, ...],
        window_utc: str,
        window_started_at: datetime,
        interval_hours: int,
        min_size_bytes: int,
        max_index_bytes: int,
        lock_timeout_ms: int,
        statement_timeout_ms: int,
        min_remaining_seconds: int,
        remaining_seconds: int,
        cycle_started_at: datetime,
        now: datetime,
    ) -> EvidenceReindexSummary:
        skipped: dict[str, str] = {}
        with (
            self._connect(autocommit=True) as connection,
            connection.cursor() as cursor,
        ):
            if _server_version_num(cursor) < MINIMUM_SERVER_VERSION_NUM:
                return EvidenceReindexSummary(
                    outcome="skipped_unsupported",
                    index=None,
                    window_utc=window_utc,
                )

            _apply_reindex_timeouts(
                cursor,
                lock_timeout_ms=lock_timeout_ms,
                statement_timeout_ms=statement_timeout_ms,
            )
            # Every cycle in the window, for every index on the list, not just
            # the one about to be rebuilt. A rebuild that timed out after the
            # swap leaves a full dead copy behind and is then not due again for
            # a week; sweeping here reclaims that disk at the next cycle
            # instead, as soon as whatever held the lock has finished.
            leftovers = _sweep_invalid_cc_leftovers(cursor, index_names)

            for index_name in index_names:
                state = _index_state(cursor, index_name)
                reason = _skip_reason(
                    state,
                    index_name=index_name,
                    min_size_bytes=min_size_bytes,
                    max_index_bytes=max_index_bytes,
                    interval_hours=interval_hours,
                    window_started_at=window_started_at,
                    now=now,
                )
                if reason is not None:
                    skipped[index_name] = reason
                    continue
                return self._reindex_one(
                    cursor,
                    index_name=index_name,
                    before=state,
                    window_utc=window_utc,
                    now=now,
                    skipped=skipped,
                    leftovers=leftovers,
                    statement_timeout_ms=statement_timeout_ms,
                    min_remaining_seconds=min_remaining_seconds,
                    remaining_seconds=remaining_seconds,
                    cycle_started_at=cycle_started_at,
                )

        return EvidenceReindexSummary(
            outcome="skipped_no_candidate",
            index=None,
            window_utc=window_utc,
            skipped=skipped,
            leftovers_dropped=leftovers,
        )

    def _reindex_one(
        self,
        cursor: Any,
        *,
        index_name: str,
        before: _IndexState | None,
        window_utc: str,
        now: datetime,
        skipped: Mapping[str, str],
        leftovers: tuple[str, ...],
        statement_timeout_ms: int,
        min_remaining_seconds: int,
        remaining_seconds: int,
        cycle_started_at: datetime,
    ) -> EvidenceReindexSummary:
        # The leftover sweep and the catalog probes above have used some of
        # the window; what is left, capped by the configured timeout, is the
        # rebuild's budget. Set right before the statement so the sweep's
        # time cannot be spent twice.
        budget_ms = _statement_budget_ms(
            statement_timeout_ms=statement_timeout_ms,
            remaining_seconds=remaining_seconds,
            cycle_started_at=cycle_started_at,
        )
        if budget_ms < min_remaining_seconds * 1000:
            return EvidenceReindexSummary(
                outcome="skipped_window_closing",
                index=None,
                window_utc=window_utc,
                skipped={**skipped, index_name: "skipped_window_closing"},
                leftovers_dropped=leftovers,
                budget_ms=budget_ms,
            )
        _apply_statement_budget(cursor, budget_ms)
        # Recorded before the work starts, not after: a rebuild that dies from
        # a refused lock must not be retried by the next cycle a few minutes
        # later, which is exactly when the contention is still there.
        _last_attempt_at[index_name] = now
        started_at = _now()
        try:
            cursor.execute(
                sql.SQL("REINDEX INDEX CONCURRENTLY {}").format(
                    sql.Identifier(index_name)
                )
            )
        except Exception as exc:
            recovered = self._recover_post_swap_success(
                cursor,
                exc,
                index_name=index_name,
                before=before,
                window_utc=window_utc,
                elapsed_ms=_elapsed_ms(started_at),
                now=now,
                skipped=skipped,
                leftovers=leftovers,
            )
            if recovered is not None:
                return recovered
            return EvidenceReindexSummary(
                outcome=f"failed:{_failure_code(exc)}",
                index=index_name,
                window_utc=window_utc,
                before_bytes=before.size_bytes if before else None,
                reltuples=before.reltuples if before else None,
                elapsed_ms=_elapsed_ms(started_at),
                skipped=skipped,
                leftovers_dropped=leftovers,
                budget_ms=budget_ms,
            )
        elapsed_ms = _elapsed_ms(started_at)
        _last_reindex_at[index_name] = now
        after = _index_state(cursor, index_name)
        return EvidenceReindexSummary(
            outcome="reindexed",
            index=index_name,
            window_utc=window_utc,
            before_bytes=before.size_bytes if before else None,
            after_bytes=after.size_bytes if after else None,
            reltuples=after.reltuples if after else None,
            elapsed_ms=elapsed_ms,
            skipped=skipped,
            leftovers_dropped=leftovers,
            budget_ms=budget_ms,
        )

    def _recover_post_swap_success(
        self,
        cursor: Any,
        exc: BaseException,
        *,
        index_name: str,
        before: _IndexState | None,
        window_utc: str,
        elapsed_ms: int,
        now: datetime,
        skipped: Mapping[str, str],
        leftovers: tuple[str, ...],
    ) -> EvidenceReindexSummary | None:
        """Tell "it timed out doing nothing" from "it timed out tidying up".

        ``REINDEX INDEX CONCURRENTLY`` swaps the rebuilt index in and only then
        waits for the last readers of the old one. A ``lock_timeout`` in that
        final wait reports failure over a rebuild that has already happened --
        measured on PostgreSQL 16, where one idle-in-transaction reader holding
        ``AccessShareLock`` is enough to trigger it. Believing the error would
        rebuild the index again the next night and leave another dead copy
        behind each time.

        ``relfilenode`` is the evidence: it changes only when the index is
        actually rebuilt, so a changed one on a still-valid index means the
        work is done, whatever the statement said.
        """

        if _failure_code(exc) not in _POST_SWAP_RECOVERABLE_SQLSTATES:
            return None
        if before is None:
            return None
        try:
            after = _index_state(cursor, index_name)
        except Exception:
            # The connection is probably gone too; report the original failure.
            return None
        if after is None or not after.indisvalid:
            return None
        if after.relfilenode == before.relfilenode:
            return None

        _last_reindex_at[index_name] = now
        # The swap left the old index behind as a dead copy. No attempt to drop
        # it here: whatever held the lock long enough to fail the rebuild is by
        # definition still holding it, so the drop would just burn another
        # lock_timeout. The next cycle's sweep reclaims it, five minutes later.
        return EvidenceReindexSummary(
            outcome="reindexed_after_lock_timeout",
            index=index_name,
            window_utc=window_utc,
            before_bytes=before.size_bytes,
            after_bytes=after.size_bytes,
            reltuples=after.reltuples,
            elapsed_ms=elapsed_ms,
            skipped=skipped,
            leftovers_dropped=leftovers,
        )

    def _connect(self, *, autocommit: bool = False) -> Any:
        if self._connection_factory is not None:
            connection = self._connection_factory()
            if autocommit:
                _enable_autocommit(connection)
            return connection

        import psycopg

        assert self._database_url is not None
        return psycopg.connect(self._database_url, autocommit=autocommit)


def _skip_reason(
    state: _IndexState | None,
    *,
    index_name: str,
    min_size_bytes: int,
    max_index_bytes: int,
    interval_hours: int,
    window_started_at: datetime,
    now: datetime,
) -> str | None:
    if state is None:
        return "skipped_missing"
    if not state.indisvalid:
        # An invalid index is either a build still running or the wreckage of
        # one that died. Rebuilding it concurrently would not fix it and might
        # collide with the running build, so this one wants a human.
        return "skipped_invalid"
    if state.size_bytes < min_size_bytes:
        return "skipped_small"
    if state.size_bytes > max_index_bytes:
        # Both copies exist until the swap, so the rebuild needs this much free
        # space again. Nothing here can read the hosted volume's free space, and
        # filling it locks the table -- so a big index waits for an operator to
        # check the volume and raise the ceiling. Skipping does not use up the
        # cycle's single rebuild: the loop moves on to the next index.
        return "skipped_too_large"
    last_reindex_at = _last_reindex_at.get(index_name)
    if last_reindex_at is not None and now - last_reindex_at < timedelta(
        hours=interval_hours
    ):
        return "skipped_interval"
    last_attempt_at = _last_attempt_at.get(index_name)
    if last_attempt_at is not None and last_attempt_at >= window_started_at:
        return "skipped_attempted"
    return None


def _index_state(cursor: Any, index_name: str) -> _IndexState | None:
    """Look the index up in the *current* schema only.

    Matching on ``relname`` alone would be wrong the moment two schemas hold an
    index of the same name -- which is precisely the shape of the acceptance
    test, where a throwaway schema carries the whole migrated schema alongside
    the real one.
    """

    cursor.execute(
        """
        SELECT
            pg_relation_size(cls.oid)::bigint AS size_bytes,
            cls.reltuples::double precision AS reltuples,
            idx.indisvalid AS indisvalid,
            cls.relfilenode::bigint AS relfilenode
        FROM pg_class cls
        JOIN pg_index idx ON idx.indexrelid = cls.oid
        WHERE cls.relname = %s
            AND cls.relnamespace = current_schema()::regnamespace
        """,
        (index_name,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return _IndexState(
        size_bytes=int(_row_value(row, "size_bytes", 0) or 0),
        reltuples=float(_row_value(row, "reltuples", 1) or 0.0),
        indisvalid=bool(_row_value(row, "indisvalid", 2)),
        relfilenode=int(_row_value(row, "relfilenode", 3) or 0),
    )


def _sweep_invalid_cc_leftovers(
    cursor: Any, index_names: tuple[str, ...]
) -> tuple[str, ...]:
    """Drop every dead transient index earlier attempts left behind.

    PostgreSQL names them ``<name>_ccnew`` before the swap and ``<name>_ccold``
    after it, with a numeric suffix when an older corpse still holds the plain
    name, so this matches the whole family rather than one spelling. Only
    ``indisvalid = false`` rows qualify, so a live index is never a candidate,
    and the search is scoped to the current schema like every other probe here.

    The scheduler is the only thing that rebuilds these indexes and it is a
    single process, so a ``_ccnew`` seen here belongs to a dead attempt, not to
    a build running right now.

    Never raises. A drop that cannot get its lock is not a reason to skip the
    cycle's actual work -- the next cycle sweeps again.
    """

    prefixes = [name + CC_LEFTOVER_INFIX for name in index_names]
    try:
        cursor.execute(
            """
            SELECT cls.relname AS relname
            FROM pg_class cls
            JOIN pg_index idx ON idx.indexrelid = cls.oid
            WHERE cls.relnamespace = current_schema()::regnamespace
                AND NOT idx.indisvalid
                AND cls.relname LIKE ANY (%s::text[])
            ORDER BY cls.relname
            """,
            ([_like_prefix(prefix) for prefix in prefixes],),
        )
        names = [str(_row_value(row, "relname", 0)) for row in cursor.fetchall()]
    except Exception as exc:
        log_event(
            "worker.maintenance.evidence_reindex_leftover_probe_failed",
            error=_failure_code(exc),
        )
        return ()

    dropped: list[str] = []
    for name in names:
        try:
            cursor.execute(
                sql.SQL("DROP INDEX CONCURRENTLY IF EXISTS {}").format(
                    sql.Identifier(name)
                )
            )
        except Exception as exc:
            log_event(
                "worker.maintenance.evidence_reindex_leftover_drop_failed",
                index=name,
                error=_failure_code(exc),
            )
            continue
        dropped.append(name)
    return tuple(dropped)


def _like_prefix(prefix: str) -> str:
    """A LIKE pattern matching exactly ``prefix`` followed by anything.

    Index names contain ``_``, which LIKE reads as "any single character", so
    the literal parts have to be escaped or ``idx_evidence_geom_cc`` would also
    match ``idxXevidenceXgeomXcc``.
    """

    escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return escaped + "%"


def _rebuilds_in_window(window_started_at: datetime) -> int:
    return sum(
        1 for finished_at in _last_reindex_at.values() if finished_at >= window_started_at
    )


def _apply_reindex_timeouts(
    cursor: Any,
    *,
    lock_timeout_ms: int,
    statement_timeout_ms: int,
) -> None:
    # Session-level (is_local false), because REINDEX CONCURRENTLY runs outside
    # a transaction block and a transaction-local setting would not survive to
    # cover it. set_config rather than SET: SET is a utility statement and
    # takes no bind parameters.
    #
    # Unlike the staging index build this does keep a statement_timeout. The
    # cost of a cancelled rebuild is a leftover "_ccnew", which the next
    # attempt drops, and that is cheaper than a rebuild running past the window
    # into the morning traffic.
    cursor.execute(
        """
        SELECT
            set_config('lock_timeout', %s, false),
            set_config('statement_timeout', %s, false)
        """,
        (f"{lock_timeout_ms}ms", f"{statement_timeout_ms}ms"),
    )


def _statement_budget_ms(
    *,
    statement_timeout_ms: int,
    remaining_seconds: int,
    cycle_started_at: datetime,
) -> int:
    """The most one rebuild may take, in milliseconds.

    ``remaining_seconds`` is what the window had left when the cycle began;
    the time the cycle has spent since (catalog probes, the leftover sweep)
    comes off it, rounded up to the next whole second so the answer does not
    wobble by milliseconds from one run to the next.
    """

    spent_seconds = int((_now() - cycle_started_at).total_seconds()) + 1
    left_ms = max(0, remaining_seconds - spent_seconds) * 1000
    return min(statement_timeout_ms, left_ms)


def _apply_statement_budget(cursor: Any, budget_ms: int) -> None:
    cursor.execute(
        "SELECT set_config('statement_timeout', %s, false)",
        (f"{budget_ms}ms",),
    )


def _server_version_num(cursor: Any) -> int:
    cursor.execute("SHOW server_version_num")
    row = cursor.fetchone()
    if row is None:
        return 0
    try:
        return int(_row_value(row, "server_version_num", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _validated_index_names(index_names: Sequence[str]) -> tuple[str, ...]:
    resolved = tuple(
        dict.fromkeys(name.strip() for name in index_names if name.strip())
    )
    if not resolved:
        raise ValueError("index_names must contain at least one index name")
    for name in resolved:
        if not INDEX_NAME_PATTERN.match(name):
            raise ValueError(
                f"invalid index name {name!r}: expected only [a-z0-9_] characters"
            )
    return resolved


def _parse_window(window_utc: str) -> tuple[time, time]:
    match = _WINDOW_PATTERN.match(window_utc.strip())
    if match is None:
        raise ValueError(
            f"invalid maintenance window {window_utc!r}: expected HH:MM-HH:MM in UTC"
        )
    start_hour, start_minute, end_hour, end_minute = (
        int(part) for part in match.groups()
    )
    try:
        start = time(hour=start_hour, minute=start_minute)
        end = time(hour=end_hour, minute=end_minute)
    except ValueError as exc:
        raise ValueError(f"invalid maintenance window {window_utc!r}: {exc}") from exc
    if start == end:
        raise ValueError(
            f"invalid maintenance window {window_utc!r}: start and end must differ"
        )
    return start, end


def _window_started_at(now: datetime, window: tuple[time, time]) -> datetime | None:
    """When the window occurrence containing ``now`` opened, else ``None``.

    The answer is the per-window identity used to enforce "one attempt per index
    per window", so it has to name the occurrence, not merely say whether the
    door is open. Windows that cross midnight (start > end) are supported
    because a Taipei-local trough is easy to write that way.
    """

    start, end = window
    day_start = now.replace(
        hour=start.hour, minute=start.minute, second=0, microsecond=0
    )
    current = now.time()
    if start < end:
        return day_start if start <= current < end else None
    if current >= start:
        return day_start
    if current < end:
        return day_start - timedelta(days=1)
    return None


def _window_ends_at(window_started_at: datetime, window: tuple[time, time]) -> datetime:
    """When the window occurrence that opened at ``window_started_at`` closes."""

    _start, end = window
    ends_at = window_started_at.replace(
        hour=end.hour, minute=end.minute, second=0, microsecond=0
    )
    if ends_at <= window_started_at:
        ends_at += timedelta(days=1)
    return ends_at


def _log_summary(
    summary: EvidenceReindexSummary,
    *,
    window_started_at: datetime | None,
) -> EvidenceReindexSummary:
    """Log once per window per distinct answer, and never outside the window.

    A maintenance cycle runs every 300 s, and for 21 of every 24 hours this
    pass has nothing to do: logging that would be 288 lines a day nobody reads.
    Inside the window it repeats too -- once the budget is spent every
    remaining cycle says the same thing. The current state is always visible in
    ``scheduler.maintenance.completed``'s ``evidence_reindex_outcome``; this
    event is for the transitions.
    """

    global _last_logged

    if window_started_at is None:
        return summary
    fingerprint = (
        window_started_at,
        summary.outcome,
        summary.index,
        summary.leftovers_dropped,
    )
    if fingerprint == _last_logged:
        return summary
    _last_logged = fingerprint
    log_event("worker.maintenance.evidence_reindex", **summary.log_fields())
    return summary


def _failure_code(exc: BaseException) -> str:
    sqlstate = getattr(exc, "sqlstate", None)
    if isinstance(sqlstate, str) and sqlstate:
        return sqlstate
    return type(exc).__name__


def _row_value(row: Any, key: str, position: int) -> Any:
    if isinstance(row, Mapping):
        return row.get(key)
    return row[position]


def _elapsed_ms(started_at: datetime) -> int:
    return int((_now() - started_at).total_seconds() * 1000)


def _enable_autocommit(connection: Any) -> None:
    setter = getattr(connection, "set_autocommit", None)
    if setter is None:
        return
    with suppress(Exception):
        setter(True)


def _now() -> datetime:
    return datetime.now(UTC)
