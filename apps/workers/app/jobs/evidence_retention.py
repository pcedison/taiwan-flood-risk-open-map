"""Retention pruning for raw snapshots and high-volume realtime evidence.

Live ingestion of CWA rainfall (~570 stations), WRA/Civil IoT water levels,
and NCDR CAP alerts (``flood_warning``) each write a new ``evidence`` row per
station/alert per cycle, so the ``evidence`` table grows fast. Those event
types feed only the realtime scoring window (6 h) and the freshness panel, so
official-sourced rows for them are pruned past a short retention window.

``flood_report`` is deliberately NOT pruned even for official sources: the
profile-rebuild scoring in ``jobs/profiles.py`` counts every ``flood_report``
(including official ones such as WRA IoW flood depth) as observed history for
``historical_score``/``has_observed_history``, so deleting aged official
flood reports would erase real observed flood events from historical risk.
Bounding ``flood_report`` growth needs a way to distinguish a live per-cycle
snapshot from a retained observed event (a follow-up), which the schema does
not yet express. ``flood_warning`` is safe because scoring only ever treats
it as a realtime signal (``has_realtime``), never as observed history.

Non-official rows are never touched regardless: the prune query always
restricts to ``source_type = 'official'``.

This keeps the table bounded so a 2-4 GB hosted node can run live ingestion
without PostGIS bloat. All evidence foreign keys are ``ON DELETE CASCADE``, so a
prune cleans up any profile/embedding/assessment links automatically.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from app.logging import log_event

ConnectionFactory = Callable[[], Any]

# Realtime telemetry safe to prune past the retention window (see the module
# docstring for why flood_report is excluded). The prune query below always
# restricts to source_type = 'official', so non-official rows are never touched
# even when they share an event_type with this tuple.
PRUNABLE_REALTIME_EVENT_TYPES: tuple[str, ...] = (
    "rainfall",
    "water_level",
    "flood_warning",
)
DEFAULT_EVIDENCE_REALTIME_RETENTION_HOURS = 48
DEFAULT_EVIDENCE_PRUNE_BATCH_LIMIT = 50_000
# ADR-0006: location_queries rows hold only coarse (~1 km) buckets, but even
# coarse query history must not accumulate forever. 30 days comfortably covers
# the live query-heat window (P7D) and materialization cadence.
DEFAULT_LOCATION_QUERY_RETENTION_HOURS = 720
# staging_evidence keeps one audit row per normalized item per ingestion cycle
# and has never been pruned, so it is by far the largest table on the hosted
# node (14.0 M live rows / 20.8 GB on 2026-09-06, see #367). Only rows whose
# validation_status is terminal are pruned:
#
# * ``rejected`` is written by promotion.py (``_terminally_reject_staging`` and
#   the batched ``idempotent_existing_observation`` settle) and is never read
#   again -- ``fetch_accepted_staging`` and ``jobs/historical_coverage.py``
#   both select ``validation_status = 'accepted'`` only.
# * ``accepted`` is deliberately NOT pruned. The schema has no ``promoted``
#   state (``0002_phase1_core_domain.sql`` allows pending/accepted/rejected/
#   quarantined and ``pipelines/staging.py`` only ever writes accepted or
#   rejected), so a promoted row stays ``accepted``; telling a promoted row
#   from one still awaiting promotion needs a per-row probe into ``evidence``,
#   and ``jobs/historical_coverage.py`` still reads aged accepted rows.
# * ``pending``/``quarantined`` are schema-allowed but never written by the
#   pipeline; they are left alone for human review.
#
# Promotion idempotency is unaffected either way: it compares
# ``evidence.properties ->> 'staging_evidence_id'`` on the evidence side.
# ``staging_evidence.raw_snapshot_id`` is ``ON DELETE SET NULL`` so pruning a
# staging row never touches a raw snapshot, while
# ``evidence_embeddings.staging_evidence_id`` is ``ON DELETE CASCADE``
# (migration 0015), so the embedding rows of a deleted staging row -- which
# only ever described that staging row -- go with it.
DEFAULT_STAGING_EVIDENCE_RETENTION_DAYS = 7
DEFAULT_STAGING_EVIDENCE_BATCH_SIZE = 5_000
# 10 batches x 5 000 rows = 50 000 rows per maintenance cycle. With the partial
# index below a batch costs a few buffers and finishes in well under a second,
# so a cycle spends about a second on this and the 300 s scheduler interval,
# not the batch cost, is what paces the backlog: ~14.4 M rows/day.
DEFAULT_STAGING_EVIDENCE_MAX_BATCHES = 10
DEFAULT_STAGING_EVIDENCE_STATEMENT_TIMEOUT_MS = 5_000
DEFAULT_STAGING_EVIDENCE_LOCK_TIMEOUT_MS = 2_000

# Without this index the batch select has to walk the table to find 5 000 aged
# rejected rows: measured on 1 M local rows that is ~1.31 M buffers and 2.5 s
# per batch, which both blows the 5 s budget during the backlog and, once the
# backlog is gone, re-scans the whole table every cycle and evicts the page
# cache of a 2 GB node. With it, a steady-state batch touches 3 buffers.
#
# It cannot be created by a migration: migrations run inside the API start-up
# transaction, and a plain CREATE INDEX on a 14 M row table locks out writes
# until it finishes (#317). So the job builds it itself, CONCURRENTLY, on an
# autocommit connection, and refuses to delete anything until it is valid.
STAGING_EVIDENCE_REJECTED_INDEX = "idx_staging_evidence_rejected_created_at"
CREATE_STAGING_EVIDENCE_REJECTED_INDEX_SQL = f"""
    CREATE INDEX CONCURRENTLY IF NOT EXISTS {STAGING_EVIDENCE_REJECTED_INDEX}
        ON staging_evidence (created_at)
        WHERE validation_status = 'rejected'
"""
# Consecutive cycles ending in a timeout before the job says so out loud. One
# timeout is a busy node; a run of them means the bound is wrong for this
# database and an operator has to look.
STAGING_RETENTION_TIMEOUT_WARNING_STREAK = 3

_STATEMENT_TIMEOUT_SQLSTATE = "57014"  # query_canceled
_LOCK_TIMEOUT_SQLSTATE = "55P03"  # lock_not_available

StagingRetentionStopReason = Literal[
    "exhausted",
    "max_batches",
    "statement_timeout",
    "lock_timeout",
    "index_not_ready",
]
StagingIndexState = Literal["ready", "building", "skipped", "unavailable"]

# The scheduler builds one job per maintenance cycle, so a streak has to
# outlive the instance. The scheduler process is the single writer.
_staging_timeout_streak = 0


class EvidenceRetentionUnavailable(RuntimeError):
    """Raised when stale evidence cannot be pruned from the database."""


@dataclass(frozen=True)
class EvidenceRetentionSummary:
    event_types: tuple[str, ...]
    retention_hours: int
    cutoff: datetime
    rows_deleted: int
    started_at: datetime
    finished_at: datetime

    def log_fields(self) -> dict[str, object]:
        return {
            "event_types": self.event_types,
            "retention_hours": self.retention_hours,
            "cutoff": self.cutoff,
            "rows_deleted": self.rows_deleted,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass(frozen=True)
class LocationQueryRetentionSummary:
    retention_hours: int
    cutoff: datetime
    rows_deleted: int
    started_at: datetime
    finished_at: datetime

    def log_fields(self) -> dict[str, object]:
        return {
            "retention_hours": self.retention_hours,
            "cutoff": self.cutoff,
            "rows_deleted": self.rows_deleted,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass(frozen=True)
class RawSnapshotRetentionSummary:
    rows_deleted: int
    started_at: datetime
    finished_at: datetime

    def log_fields(self) -> dict[str, object]:
        return {
            "rows_deleted": self.rows_deleted,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass(frozen=True)
class StagingEvidenceRetentionSummary:
    retention_days: int
    cutoff: datetime
    deleted_rows: int
    batches: int
    index_state: StagingIndexState
    stopped_reason: StagingRetentionStopReason
    started_at: datetime
    finished_at: datetime

    def log_fields(self) -> dict[str, object]:
        return {
            "retention_days": self.retention_days,
            "cutoff": self.cutoff,
            "deleted_rows": self.deleted_rows,
            "batches": self.batches,
            "index_state": self.index_state,
            "stopped_reason": self.stopped_reason,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class PostgresEvidenceRetentionJob:
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

    def prune_realtime(
        self,
        *,
        retention_hours: int,
        event_types: Iterable[str] = PRUNABLE_REALTIME_EVENT_TYPES,
        batch_limit: int = DEFAULT_EVIDENCE_PRUNE_BATCH_LIMIT,
        now: datetime | None = None,
    ) -> EvidenceRetentionSummary:
        resolved_event_types = tuple(dict.fromkeys(event_types))
        if retention_hours < 1:
            raise ValueError("retention_hours must be a positive integer")
        if batch_limit < 1:
            raise ValueError("batch_limit must be a positive integer")
        resolved_now = (now or _now()).astimezone(UTC)
        cutoff = resolved_now - timedelta(hours=retention_hours)
        started_at = _now()

        if not resolved_event_types:
            summary = EvidenceRetentionSummary(
                event_types=(),
                retention_hours=retention_hours,
                cutoff=cutoff,
                rows_deleted=0,
                started_at=started_at,
                finished_at=_now(),
            )
            log_event("evidence.retention.completed", **summary.log_fields())
            return summary

        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    rows_deleted = _prune_realtime_evidence(
                        cursor,
                        event_types=resolved_event_types,
                        cutoff=cutoff,
                        batch_limit=batch_limit,
                    )
                connection.commit()
        except Exception as exc:
            raise EvidenceRetentionUnavailable(str(exc)) from exc

        summary = EvidenceRetentionSummary(
            event_types=resolved_event_types,
            retention_hours=retention_hours,
            cutoff=cutoff,
            rows_deleted=rows_deleted,
            started_at=started_at,
            finished_at=_now(),
        )
        log_event("evidence.retention.completed", **summary.log_fields())
        return summary

    def prune_location_queries(
        self,
        *,
        retention_hours: int = DEFAULT_LOCATION_QUERY_RETENTION_HOURS,
        batch_limit: int = DEFAULT_EVIDENCE_PRUNE_BATCH_LIMIT,
        now: datetime | None = None,
    ) -> LocationQueryRetentionSummary:
        if retention_hours < 1:
            raise ValueError("retention_hours must be a positive integer")
        if batch_limit < 1:
            raise ValueError("batch_limit must be a positive integer")
        resolved_now = (now or _now()).astimezone(UTC)
        cutoff = resolved_now - timedelta(hours=retention_hours)
        started_at = _now()

        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    rows_deleted = _prune_location_queries(
                        cursor,
                        cutoff=cutoff,
                        batch_limit=batch_limit,
                    )
                connection.commit()
        except Exception as exc:
            raise EvidenceRetentionUnavailable(str(exc)) from exc

        summary = LocationQueryRetentionSummary(
            retention_hours=retention_hours,
            cutoff=cutoff,
            rows_deleted=rows_deleted,
            started_at=started_at,
            finished_at=_now(),
        )
        log_event("location_queries.retention.completed", **summary.log_fields())
        return summary

    def prune_expired_raw_snapshots(
        self,
        *,
        batch_limit: int = DEFAULT_EVIDENCE_PRUNE_BATCH_LIMIT,
        now: datetime | None = None,
    ) -> RawSnapshotRetentionSummary:
        """Delete one bounded batch whose per-source-family policy has expired.

        ``staging_evidence.raw_snapshot_id`` uses ``ON DELETE SET NULL`` so the
        normalized validation audit remains available after the raw payload's
        retention window ends.
        """

        if batch_limit < 1:
            raise ValueError("batch_limit must be a positive integer")
        resolved_now = (now or _now()).astimezone(UTC)
        started_at = _now()

        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    rows_deleted = _prune_expired_raw_snapshots(
                        cursor,
                        expired_before=resolved_now,
                        batch_limit=batch_limit,
                    )
                connection.commit()
        except Exception as exc:
            raise EvidenceRetentionUnavailable(str(exc)) from exc

        summary = RawSnapshotRetentionSummary(
            rows_deleted=rows_deleted,
            started_at=started_at,
            finished_at=_now(),
        )
        log_event("raw_snapshots.retention.completed", **summary.log_fields())
        return summary

    def prune_staging_evidence(
        self,
        *,
        retention_days: int = DEFAULT_STAGING_EVIDENCE_RETENTION_DAYS,
        batch_size: int = DEFAULT_STAGING_EVIDENCE_BATCH_SIZE,
        max_batches: int = DEFAULT_STAGING_EVIDENCE_MAX_BATCHES,
        statement_timeout_ms: int = DEFAULT_STAGING_EVIDENCE_STATEMENT_TIMEOUT_MS,
        lock_timeout_ms: int = DEFAULT_STAGING_EVIDENCE_LOCK_TIMEOUT_MS,
        ensure_index: bool = True,
        now: datetime | None = None,
    ) -> StagingEvidenceRetentionSummary:
        """Delete terminal (rejected) staging rows past the retention window.

        The delete is bounded three ways so it can never hold the table long
        enough to stall ingestion on a small node (#317): a fixed row count per
        batch, one committed transaction per batch, and a ``max_batches`` cap
        per maintenance cycle. Each batch first sets a transaction-local
        ``statement_timeout``/``lock_timeout``; when either fires the cycle
        stops and reports why instead of retrying.

        Batches need no cursor. Every batch deletes the rows it selected, so
        the next one necessarily sees different rows, and ordering by
        ``created_at`` means each batch takes the oldest rows still eligible --
        which is also the order the supporting partial index stores them in.
        """

        if retention_days < 1:
            raise ValueError("retention_days must be a positive integer")
        if batch_size < 1:
            raise ValueError("batch_size must be a positive integer")
        if max_batches < 1:
            raise ValueError("max_batches must be a positive integer")
        if statement_timeout_ms < 1:
            raise ValueError("statement_timeout_ms must be a positive integer")
        if lock_timeout_ms < 1:
            raise ValueError("lock_timeout_ms must be a positive integer")

        resolved_now = (now or _now()).astimezone(UTC)
        cutoff = resolved_now - timedelta(days=retention_days)
        started_at = _now()

        deleted_rows = 0
        batches = 0
        stopped_reason: StagingRetentionStopReason = "max_batches"

        try:
            index_state = self._ensure_rejected_index(
                enabled=ensure_index, lock_timeout_ms=lock_timeout_ms
            )
            # Deleting without the index is the pathological case the reviewer
            # measured: ~1.31 M buffers and 2.5 s per batch on 1 M rows. Wait
            # for the build instead, however many cycles that takes.
            # "skipped" means an operator took the index on themselves, so the
            # deletes still run; if the index is in fact missing, the per-batch
            # statement_timeout bounds the damage to one refused batch.
            if index_state in ("ready", "skipped"):
                deleted_rows, batches, stopped_reason = self._delete_staging_batches(
                    cutoff=cutoff,
                    batch_size=batch_size,
                    max_batches=max_batches,
                    statement_timeout_ms=statement_timeout_ms,
                    lock_timeout_ms=lock_timeout_ms,
                )
            else:
                stopped_reason = "index_not_ready"
        except EvidenceRetentionUnavailable:
            raise
        except Exception as exc:
            raise EvidenceRetentionUnavailable(str(exc)) from exc

        summary = StagingEvidenceRetentionSummary(
            retention_days=retention_days,
            cutoff=cutoff,
            deleted_rows=deleted_rows,
            batches=batches,
            index_state=index_state,
            stopped_reason=stopped_reason,
            started_at=started_at,
            finished_at=_now(),
        )
        log_event("worker.maintenance.staging_retention", **summary.log_fields())
        _record_staging_timeout_streak(stopped_reason)
        return summary

    def _delete_staging_batches(
        self,
        *,
        cutoff: datetime,
        batch_size: int,
        max_batches: int,
        statement_timeout_ms: int,
        lock_timeout_ms: int,
    ) -> tuple[int, int, StagingRetentionStopReason]:
        deleted_rows = 0
        batches = 0
        stopped_reason: StagingRetentionStopReason = "max_batches"

        with self._connect() as connection:
            while batches < max_batches:
                try:
                    with connection.cursor() as cursor:
                        _apply_staging_retention_timeouts(
                            cursor,
                            statement_timeout_ms=statement_timeout_ms,
                            lock_timeout_ms=lock_timeout_ms,
                        )
                        batch_rows = _delete_staging_evidence_batch(
                            cursor, cutoff=cutoff, batch_size=batch_size
                        )
                    connection.commit()
                except Exception as exc:
                    timeout_reason = _timeout_stop_reason(exc)
                    if timeout_reason is None:
                        raise
                    _rollback_quietly(connection)
                    stopped_reason = timeout_reason
                    break
                batches += 1
                if not batch_rows:
                    stopped_reason = "exhausted"
                    break
                deleted_rows += batch_rows
        return deleted_rows, batches, stopped_reason

    def _ensure_rejected_index(
        self, *, enabled: bool, lock_timeout_ms: int
    ) -> StagingIndexState:
        """Build the partial index the batch select needs, concurrently.

        ``CREATE INDEX CONCURRENTLY`` cannot run inside a transaction block, so
        this uses an autocommit connection, and it carries no
        ``statement_timeout``: on 14 M rows the build takes minutes, and a
        timeout would only leave an invalid index behind. ``lock_timeout`` is
        kept, because the brief locks the build does take must never queue
        behind ingestion.

        A previous build that died half way leaves an ``indisvalid = false``
        index that the planner ignores and that blocks a rebuild, so it is
        dropped concurrently first.
        """

        if not enabled:
            return "skipped"
        try:
            with (
                self._connect(autocommit=True) as connection,
                connection.cursor() as cursor,
            ):
                if _index_is_valid(cursor):
                    return "ready"
                _apply_index_build_timeouts(cursor, lock_timeout_ms=lock_timeout_ms)
                cursor.execute(
                    "DROP INDEX CONCURRENTLY IF EXISTS "
                    + STAGING_EVIDENCE_REJECTED_INDEX
                )
                cursor.execute(CREATE_STAGING_EVIDENCE_REJECTED_INDEX_SQL)
                state: StagingIndexState = (
                    "ready" if _index_is_valid(cursor) else "building"
                )
                log_event(
                    "worker.maintenance.staging_retention_index_built",
                    index_name=STAGING_EVIDENCE_REJECTED_INDEX,
                    index_state=state,
                )
                return state
        except Exception as exc:
            # A failed build is not a failed maintenance cycle: the next cycle
            # retries, and until then the job simply does not delete.
            log_event(
                "worker.maintenance.staging_retention_index_failed",
                index_name=STAGING_EVIDENCE_REJECTED_INDEX,
                error=type(exc).__name__,
            )
            return "unavailable"

    def _connect(self, *, autocommit: bool = False) -> Any:
        if self._connection_factory is not None:
            connection = self._connection_factory()
            if autocommit:
                _enable_autocommit(connection)
            return connection

        import psycopg

        assert self._database_url is not None
        return psycopg.connect(self._database_url, autocommit=autocommit)


def _prune_realtime_evidence(
    cursor: Any,
    *,
    event_types: tuple[str, ...],
    cutoff: datetime,
    batch_limit: int,
) -> int:
    cursor.execute(
        """
        WITH stale AS (
            SELECT id
            FROM evidence
            WHERE source_type = 'official'
                AND event_type = ANY(%s::text[])
                AND COALESCE(observed_at, ingested_at, created_at) < %s::timestamptz
            ORDER BY COALESCE(observed_at, ingested_at, created_at) ASC
            LIMIT %s
        ),
        deleted AS (
            DELETE FROM evidence
            WHERE id IN (SELECT id FROM stale)
            RETURNING id
        )
        SELECT COUNT(*)::integer AS rows_deleted
        FROM deleted
        """,
        (
            list(event_types),
            cutoff,
            batch_limit,
        ),
    )
    return _row_count(cursor.fetchone())


def _prune_location_queries(
    cursor: Any,
    *,
    cutoff: datetime,
    batch_limit: int,
) -> int:
    # risk_assessments.query_id and risk_assessment_evidence cascade on
    # delete, so pruning a query row cleans up its assessment links too.
    cursor.execute(
        """
        WITH stale AS (
            SELECT id
            FROM location_queries
            WHERE created_at < %s::timestamptz
            ORDER BY created_at ASC
            LIMIT %s
        ),
        deleted AS (
            DELETE FROM location_queries
            WHERE id IN (SELECT id FROM stale)
            RETURNING id
        )
        SELECT COUNT(*)::integer AS rows_deleted
        FROM deleted
        """,
        (cutoff, batch_limit),
    )
    return _row_count(cursor.fetchone())


def _prune_expired_raw_snapshots(
    cursor: Any,
    *,
    expired_before: datetime,
    batch_limit: int,
) -> int:
    cursor.execute(
        """
        WITH stale AS (
            SELECT id
            FROM raw_snapshots
            WHERE retention_expires_at IS NOT NULL
                AND retention_expires_at < %s::timestamptz
            ORDER BY retention_expires_at ASC
            LIMIT %s
        ),
        deleted AS (
            DELETE FROM raw_snapshots
            WHERE id IN (SELECT id FROM stale)
            RETURNING id
        )
        SELECT COUNT(*)::integer AS rows_deleted
        FROM deleted
        """,
        (expired_before, batch_limit),
    )
    return _row_count(cursor.fetchone())


def _apply_staging_retention_timeouts(
    cursor: Any,
    *,
    statement_timeout_ms: int,
    lock_timeout_ms: int,
) -> None:
    # Transaction-local (third argument true), so every batch re-applies them
    # and no setting leaks into a pooled session.
    cursor.execute(
        """
        SELECT
            set_config('lock_timeout', %s, true),
            set_config('statement_timeout', %s, true)
        """,
        (f"{lock_timeout_ms}ms", f"{statement_timeout_ms}ms"),
    )


def _apply_index_build_timeouts(cursor: Any, *, lock_timeout_ms: int) -> None:
    # Session-level, because CREATE INDEX CONCURRENTLY runs outside a
    # transaction block and a transaction-local setting would not survive to
    # cover it. statement_timeout is disabled on purpose: a 14 M row build
    # takes minutes and cancelling it only leaves an invalid index behind.
    # set_config with is_local false rather than SET: SET is a utility
    # statement and takes no bind parameters.
    cursor.execute(
        """
        SELECT
            set_config('lock_timeout', %s, false),
            set_config('statement_timeout', '0', false)
        """,
        (f"{lock_timeout_ms}ms",),
    )


def _index_is_valid(cursor: Any) -> bool:
    """True only when the index exists and the planner will actually use it."""

    cursor.execute(
        """
        SELECT idx.indisvalid
        FROM pg_class cls
        JOIN pg_index idx ON idx.indexrelid = cls.oid
        WHERE cls.relname = %s
        """,
        (STAGING_EVIDENCE_REJECTED_INDEX,),
    )
    row = cursor.fetchone()
    if row is None:
        return False
    value = row["indisvalid"] if isinstance(row, dict) else row[0]
    return bool(value)


def _delete_staging_evidence_batch(
    cursor: Any,
    *,
    cutoff: datetime,
    batch_size: int,
) -> int:
    # 'rejected' is a literal baked into the SQL text, not a bind parameter, so
    # no caller can widen this to the accepted rows promotion still reads.
    #
    # No cursor: the batch deletes exactly the rows it selected, so the next
    # batch cannot see them again. Ordering by created_at takes the oldest
    # eligible rows first and matches idx_staging_evidence_rejected_created_at,
    # so the select reads a handful of buffers instead of walking the table.
    cursor.execute(
        """
        /* staging-retention */
        DELETE FROM staging_evidence
        WHERE id IN (
            SELECT id
            FROM staging_evidence
            WHERE validation_status = 'rejected'
                AND created_at < %s::timestamptz
            ORDER BY created_at ASC
            LIMIT %s
        )
        """,
        (cutoff, batch_size),
    )
    return int(cursor.rowcount or 0)


def _record_staging_timeout_streak(stopped_reason: StagingRetentionStopReason) -> None:
    global _staging_timeout_streak

    if stopped_reason not in ("statement_timeout", "lock_timeout"):
        _staging_timeout_streak = 0
        return
    _staging_timeout_streak += 1
    if _staging_timeout_streak < STAGING_RETENTION_TIMEOUT_WARNING_STREAK:
        return
    log_event(
        "worker.maintenance.staging_retention_timeout_streak",
        level="warning",
        streak=_staging_timeout_streak,
        stopped_reason=stopped_reason,
        threshold=STAGING_RETENTION_TIMEOUT_WARNING_STREAK,
    )


def _enable_autocommit(connection: Any) -> None:
    setter = getattr(connection, "set_autocommit", None)
    if setter is None:
        return
    with suppress(Exception):
        setter(True)


def _timeout_stop_reason(exc: BaseException) -> StagingRetentionStopReason | None:
    sqlstate = getattr(exc, "sqlstate", None)
    if sqlstate == _STATEMENT_TIMEOUT_SQLSTATE:
        return "statement_timeout"
    if sqlstate == _LOCK_TIMEOUT_SQLSTATE:
        return "lock_timeout"
    return None


def _rollback_quietly(connection: Any) -> None:
    rollback = getattr(connection, "rollback", None)
    if rollback is None:
        return
    with suppress(Exception):
        rollback()


def _row_count(row: Any) -> int:
    if row is None:
        return 0
    if isinstance(row, dict):
        return int(row.get("rows_deleted", 0) or 0)
    return int(row[0] or 0)


def _now() -> datetime:
    return datetime.now(UTC)
