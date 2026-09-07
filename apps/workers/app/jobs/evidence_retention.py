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
from functools import partial
from typing import Any, Literal, TypeVar

from app.jobs.freshness import FreshnessCadence, cadence_for_adapter
from app.jobs.historical_coverage import HISTORICAL_COVERAGE_ADAPTER_KEYS
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
# * ``accepted`` is pruned only for the narrow orphan case described below.
#   The schema has no ``promoted`` state (``0002_phase1_core_domain.sql``
#   allows pending/accepted/rejected/quarantined and ``pipelines/staging.py``
#   only ever writes accepted or rejected), so a promoted row stays
#   ``accepted`` and telling it from one still awaiting promotion needs a
#   per-row probe into ``evidence``.
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
#
# The accepted pass (#372) is the per-row probe the paragraph above called
# too expensive to guess at, run for real against the partial index from
# migration 0042. On the hosted node 12.6 M of the 14.35 M staging rows are
# ``accepted`` but only ~2.25 M are still referenced by an evidence row, so
# ~10.4 M are orphans: realtime telemetry that was promoted, whose evidence
# row the 48 h ``prune_realtime`` pass above then deleted. Nothing can ever
# read them again -- ``fetch_accepted_staging`` only promotes rows no
# evidence points at, and a week-old realtime observation is long past its
# scoring window -- so past the retention window they are deleted, subject
# to two guards:
#
# * the row's adapter must be realtime-cadence (see
#   ``is_orphan_prunable_adapter``): ``jobs/historical_coverage.py`` reads
#   aged accepted rows for the NSTC / WRA historical-flood adapters, and the
#   static and warning-event adapters publish too rarely for "older than a
#   week" to mean "already superseded";
# * no evidence row may reference it (``NOT EXISTS`` against
#   ``idx_evidence_staging_evidence_id``), so a row still awaiting promotion,
#   or one whose evidence is retained, is never touched.
DEFAULT_STAGING_EVIDENCE_RETENTION_DAYS = 7
DEFAULT_STAGING_EVIDENCE_BATCH_SIZE = 5_000
# 10 batches x 5 000 rows = 50 000 rows per maintenance cycle. With the partial
# index below a batch costs a few buffers and finishes in well under a second,
# so a cycle spends about a second on this and the 300 s scheduler interval,
# not the batch cost, is what paces the backlog: ~14.4 M rows/day.
DEFAULT_STAGING_EVIDENCE_MAX_BATCHES = 10
# The accepted pass gets its own batch budget so it can be throttled -- or
# turned off -- without touching the rejected backlog it runs after.
DEFAULT_STAGING_EVIDENCE_ACCEPTED_MAX_BATCHES = 10
# The accepted pass sweeps a created_at *window* per batch rather than
# "the next 5 000 orphans", because the rows it keeps stay in the index
# forever: on the hosted node ~2.25 M accepted rows are still referenced by
# an evidence row, and an unwindowed batch has to re-probe that whole
# surviving prefix before it reaches a single new orphan. Measured by the
# #381 reviewer with a 400 k-row survivor prefix: 405 k NOT EXISTS probes,
# 1.6 M buffers and 1.43 s for one batch on a warm SSD -- and the prefix
# grows with every cycle, so on the 2 GB IO-bound node every batch would
# soon hit the 5 s statement_timeout and roll back, forever.
#
# With a window the work per statement is set by the window's row count
# instead. An hour of hosted ingestion is ~48 k staging rows, so a 1 h
# window costs ~48 k probes whatever the survivor prefix has grown to.
DEFAULT_STAGING_EVIDENCE_ACCEPTED_WINDOW_SECONDS = 3_600
# A window that still times out is halved down to this floor before the
# pass gives up for the cycle; below five minutes the per-statement
# overhead stops being worth the smaller scan.
DEFAULT_STAGING_EVIDENCE_ACCEPTED_MIN_WINDOW_SECONDS = 300
# A window that deleted *nothing* may grow past the normal ceiling, up to
# this one. Empty windows are what a restart costs: the watermark lives in
# memory, so the next sweep re-walks ground that is already clear, and at a
# fixed 1 h ceiling that is 10 h of history per cycle -- 38 cycles, ~3.2 h,
# to re-cross 16 days. Doubling through empty history instead crosses the
# same span in about four cycles. Any window that actually finds rows drops
# straight back to the normal ceiling, and the halving path collects the
# overshoot, so this only ever buys speed over ground with nothing in it.
DEFAULT_STAGING_EVIDENCE_ACCEPTED_MAX_WINDOW_SECONDS = 86_400
DEFAULT_STAGING_EVIDENCE_STATEMENT_TIMEOUT_MS = 5_000
# The sweep's two setup reads -- the data_sources catalogue and min(created_at)
# over the accepted partial index -- are bounded lookups, not scans, and they
# are not what the per-batch budget is sizing. Giving them their own fixed
# budget means lowering the batch budget to protect ingestion cannot starve
# the sweep of the setup it needs to run at all.
STAGING_EVIDENCE_METADATA_STATEMENT_TIMEOUT_MS = 5_000
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
# The accepted pass needs the same shape over the other half of the table,
# and for the same reason: without it the batch select walks 12.6 M rows to
# find 5 000 aged accepted ones. It is built the same way, and the accepted
# deletes likewise refuse to run until it is valid.
STAGING_EVIDENCE_ACCEPTED_INDEX = "idx_staging_evidence_accepted_created_at"
CREATE_STAGING_EVIDENCE_ACCEPTED_INDEX_SQL = f"""
    CREATE INDEX CONCURRENTLY IF NOT EXISTS {STAGING_EVIDENCE_ACCEPTED_INDEX}
        ON staging_evidence (created_at)
        WHERE validation_status = 'accepted'
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
    # Accepted pass only: the operator turned it off, or data_sources named
    # no adapter whose accepted rows may be pruned. Both mean "ran no DELETE".
    "disabled",
    "no_adapter_sources",
    # Accepted pass only: the sweep watermark reached the retention cutoff,
    # so every aged row has already been visited once. The steady state.
    "caught_up",
]
# "ready" is the only state that deletes. "skipped" means the job was told
# not to build the index (ENSURE_INDEX=false) and the operator-managed index
# is absent or invalid -- the earlier behaviour of deleting anyway on that
# flag bought the pathological scan one cancelled batch per cycle, forever.
StagingIndexState = Literal["ready", "building", "skipped", "unavailable"]

# The scheduler builds one job per maintenance cycle, so a streak has to
# outlive the instance. The scheduler process is the single writer.
_staging_timeout_streak = 0
# The accepted pass keeps its own streak: the two passes have different
# indexes, budgets and query shapes, so one timing out says nothing about
# the other and a shared counter would hide whichever is healthy.
_accepted_timeout_streak = 0
# Where the accepted sweep has got to, and the window size it is currently
# using. Module level for the same reason as the streak: the scheduler is
# one long-lived process building a fresh job per cycle.
#
# Sweeping once from oldest to newest is enough, and never re-scanning is
# the whole point. A row's orphan status is settled well before it reaches
# the 7-day cutoff: a row that was never promoted is an orphan from birth,
# and a promoted row loses its evidence within
# EVIDENCE_REALTIME_RETENTION_HOURS (48 h). Losing the watermark on restart
# just costs one sweep from the oldest row, which is why it is not
# persisted.
_accepted_sweep_watermark: datetime | None = None
_accepted_sweep_window_seconds: int | None = None
# The adapters admitted only by the legacy fallback, as of the last cycle
# that logged them. 34 keys every 300 s is noise nobody reads; the same 34
# keys the one time they change is the thing worth seeing.
_accepted_fallback_adapter_keys: tuple[str, ...] | None = None


# Cadences whose accepted staging rows are one-cycle telemetry. A realtime
# adapter republishes every station every few minutes, so a week-old accepted
# row has been superseded hundreds of times over; "legacy" is the fallback
# ``cadence_for_adapter`` returns for everything that is neither a slow static
# snapshot nor a warning event, which is the same per-cycle shape. The static
# and event cadences are excluded: they publish rarely enough that a week-old
# accepted row can still be the current one.
ORPHAN_PRUNABLE_CADENCES: tuple[FreshnessCadence, ...] = ("realtime", "legacy")


def is_orphan_prunable_adapter(adapter_key: str) -> bool:
    """True when this adapter's aged, unreferenced accepted rows are dead.

    Deliberately derived from ``jobs/freshness.cadence_for_adapter`` rather
    than a hand-kept list, so a new adapter cannot be realtime for freshness
    and something else for retention. ``HISTORICAL_COVERAGE_ADAPTER_KEYS`` is
    excluded on top of the cadence rule -- ``jobs/historical_coverage.py``
    re-reads those accepted staging rows years after ingestion -- even though
    both of its keys are already static-cadence today; the belt is cheap and
    the braces would otherwise depend on freshness never reclassifying them.
    """

    if adapter_key in HISTORICAL_COVERAGE_ADAPTER_KEYS:
        return False
    return cadence_for_adapter(adapter_key) in ORPHAN_PRUNABLE_CADENCES


def orphan_prunable_source_ids(sources: Iterable[tuple[Any, Any]]) -> tuple[str, ...]:
    """Filter ``(data_sources.id, adapter_key)`` rows down to prunable ids.

    ``staging_evidence`` carries ``data_source_id``, not ``adapter_key``
    (migration 0002), so the classification happens here -- in Python, over the
    few dozen rows of ``data_sources`` -- and the batch SQL only ever sees a
    resolved id list.
    """

    resolved: list[str] = []
    for source_id, adapter_key in sources:
        if source_id is None or adapter_key is None:
            continue
        if not is_orphan_prunable_adapter(str(adapter_key)):
            continue
        resolved.append(str(source_id))
    return tuple(dict.fromkeys(resolved))


def legacy_fallback_adapter_keys(
    sources: Iterable[tuple[Any, Any]],
) -> tuple[str, ...]:
    """Adapters admitted only because the cadence rule is fail-open.

    ``cadence_for_adapter`` returns ``legacy`` for anything none of the
    three freshness sets names, and ``legacy`` is prunable. That is
    deliberate -- an adapter nobody classified still writes one accepted
    audit row per item per cycle, and the ``NOT EXISTS`` guard already
    protects everything that was promoted -- but it means a *new* adapter
    is opted in by omission rather than by decision. 33 of the 58 seeded
    adapters arrive this way today. Naming them once per cycle in the log
    is what makes that visible instead of implicit.
    """

    fallback: list[str] = []
    for _source_id, adapter_key in sources:
        if adapter_key is None:
            continue
        key = str(adapter_key)
        if cadence_for_adapter(key) != "legacy":
            continue
        if not is_orphan_prunable_adapter(key):
            continue
        fallback.append(key)
    return tuple(sorted(dict.fromkeys(fallback)))


_BatchResult = TypeVar("_BatchResult")


@dataclass(frozen=True)
class _AcceptedSweepResult:
    """What one cycle of the accepted sweep did, and where it left off."""

    deleted_rows: int
    batches: int
    stopped_reason: StagingRetentionStopReason
    source_count: int
    watermark: datetime | None
    window_seconds: int


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
    """One maintenance cycle's two staging passes.

    The unprefixed fields are the rejected pass, unchanged from #370 so the
    log queries and dashboards built on it keep working; ``accepted_*``
    mirrors them for the orphan pass added in #372.
    """

    retention_days: int
    cutoff: datetime
    deleted_rows: int
    batches: int
    index_state: StagingIndexState
    stopped_reason: StagingRetentionStopReason
    accepted_deleted_rows: int
    accepted_batches: int
    accepted_index_state: StagingIndexState
    accepted_stopped_reason: StagingRetentionStopReason
    accepted_source_count: int
    accepted_watermark: datetime | None
    accepted_window_seconds: int
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

    def accepted_log_fields(self) -> dict[str, object]:
        """The accepted pass in the same shape, under its own event name."""

        return {
            "retention_days": self.retention_days,
            "cutoff": self.cutoff,
            "deleted_rows": self.accepted_deleted_rows,
            "batches": self.accepted_batches,
            "index_state": self.accepted_index_state,
            "stopped_reason": self.accepted_stopped_reason,
            "source_count": self.accepted_source_count,
            "watermark": self.accepted_watermark,
            "window_seconds": self.accepted_window_seconds,
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
        accepted_enabled: bool = True,
        accepted_max_batches: int = (
            DEFAULT_STAGING_EVIDENCE_ACCEPTED_MAX_BATCHES
        ),
        accepted_window_seconds: int = (
            DEFAULT_STAGING_EVIDENCE_ACCEPTED_WINDOW_SECONDS
        ),
        accepted_min_window_seconds: int = (
            DEFAULT_STAGING_EVIDENCE_ACCEPTED_MIN_WINDOW_SECONDS
        ),
        accepted_max_window_seconds: int | None = None,
        now: datetime | None = None,
    ) -> StagingEvidenceRetentionSummary:
        """Delete dead staging rows past the retention window, in two passes.

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

        The rejected pass runs first and the accepted-orphan pass second,
        each with its own index, its own batch budget, its own timeout
        streak and its own ``stopped_reason``, so a stalled orphan pass can
        never eat the budget of -- or mask the health of -- the backlog
        pass that is already proven in production.

        The two passes bound a batch differently. The rejected pass deletes
        the rows it selects, so nothing it skips accumulates and "the
        oldest 5 000 eligible rows" stays cheap forever. The accepted pass
        keeps every referenced row, so it sweeps a ``created_at`` window at
        a time behind a watermark instead; see
        ``_sweep_accepted_staging``.
        """

        if retention_days < 1:
            raise ValueError("retention_days must be a positive integer")
        if batch_size < 1:
            raise ValueError("batch_size must be a positive integer")
        if max_batches < 1:
            raise ValueError("max_batches must be a positive integer")
        if accepted_max_batches < 1:
            raise ValueError(
                "accepted_max_batches must be a positive integer"
            )
        if accepted_min_window_seconds < 1:
            raise ValueError(
                "accepted_min_window_seconds must be a positive integer"
            )
        if accepted_window_seconds < accepted_min_window_seconds:
            raise ValueError(
                "accepted_window_seconds must not be below accepted_min_window_seconds"
            )
        # Defaults to the constant, but never below the normal ceiling: raising
        # only the window must not fail on a limit the caller never set.
        resolved_max_window_seconds = (
            max(
                DEFAULT_STAGING_EVIDENCE_ACCEPTED_MAX_WINDOW_SECONDS,
                accepted_window_seconds,
            )
            if accepted_max_window_seconds is None
            else accepted_max_window_seconds
        )
        if resolved_max_window_seconds < accepted_window_seconds:
            raise ValueError(
                "accepted_max_window_seconds must not be below accepted_window_seconds"
            )
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
        accepted_deleted_rows = 0
        accepted_batches = 0
        accepted_index_state: StagingIndexState = "skipped"
        accepted_stopped_reason: StagingRetentionStopReason = "disabled"
        accepted_source_count = 0
        accepted_watermark = _accepted_sweep_watermark
        accepted_window = accepted_window_seconds

        try:
            index_state = self._ensure_partial_index(
                index_name=STAGING_EVIDENCE_REJECTED_INDEX,
                create_sql=CREATE_STAGING_EVIDENCE_REJECTED_INDEX_SQL,
                enabled=ensure_index,
                lock_timeout_ms=lock_timeout_ms,
            )
            # Deleting without the index is the pathological case the reviewer
            # measured: ~1.31 M buffers and 2.5 s per batch on 1 M rows. Wait
            # for the build instead, however many cycles that takes.
            if index_state == "ready":
                deleted_rows, batches, stopped_reason = self._delete_staging_batches(
                    cutoff=cutoff,
                    batch_size=batch_size,
                    max_batches=max_batches,
                    statement_timeout_ms=statement_timeout_ms,
                    lock_timeout_ms=lock_timeout_ms,
                )
            else:
                stopped_reason = "index_not_ready"

            if accepted_enabled:
                accepted_index_state = self._ensure_partial_index(
                    index_name=STAGING_EVIDENCE_ACCEPTED_INDEX,
                    create_sql=CREATE_STAGING_EVIDENCE_ACCEPTED_INDEX_SQL,
                    enabled=ensure_index,
                    lock_timeout_ms=lock_timeout_ms,
                )
                if accepted_index_state == "ready":
                    sweep = self._sweep_accepted_staging(
                        cutoff=cutoff,
                        batch_size=batch_size,
                        max_batches=accepted_max_batches,
                        statement_timeout_ms=statement_timeout_ms,
                        lock_timeout_ms=lock_timeout_ms,
                        window_seconds=accepted_window_seconds,
                        min_window_seconds=accepted_min_window_seconds,
                        max_window_seconds=resolved_max_window_seconds,
                    )
                    accepted_deleted_rows = sweep.deleted_rows
                    accepted_batches = sweep.batches
                    accepted_stopped_reason = sweep.stopped_reason
                    accepted_source_count = sweep.source_count
                    accepted_watermark = sweep.watermark
                    accepted_window = sweep.window_seconds
                else:
                    accepted_stopped_reason = "index_not_ready"
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
            accepted_deleted_rows=accepted_deleted_rows,
            accepted_batches=accepted_batches,
            accepted_index_state=accepted_index_state,
            accepted_stopped_reason=accepted_stopped_reason,
            accepted_source_count=accepted_source_count,
            accepted_watermark=accepted_watermark,
            accepted_window_seconds=accepted_window,
            started_at=started_at,
            finished_at=_now(),
        )
        log_event("worker.maintenance.staging_retention", **summary.log_fields())
        log_event(
            "worker.maintenance.staging_accepted_retention",
            **summary.accepted_log_fields(),
        )
        _record_staging_timeout_streak(stopped_reason)
        _record_accepted_timeout_streak(accepted_stopped_reason)
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
                    batch_rows = _committed_batch(
                        connection,
                        statement_timeout_ms=statement_timeout_ms,
                        lock_timeout_ms=lock_timeout_ms,
                        work=partial(
                            _delete_staging_evidence_batch,
                            cutoff=cutoff,
                            batch_size=batch_size,
                        ),
                    )
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

    def _sweep_accepted_staging(
        self,
        *,
        cutoff: datetime,
        batch_size: int,
        max_batches: int,
        statement_timeout_ms: int,
        lock_timeout_ms: int,
        window_seconds: int,
        min_window_seconds: int,
        max_window_seconds: int,
    ) -> _AcceptedSweepResult:
        """Sweep aged accepted rows no evidence row points at any more.

        Unlike the rejected pass this one cannot ask for "the oldest
        batch_size eligible rows": the rows it must keep -- ~2.25 M on the
        hosted node -- stay at the head of the index forever, so every
        batch would re-probe that whole surviving prefix before reaching a
        new orphan, and the prefix grows with every cycle. Measured by the
        #381 reviewer at a 400 k-row prefix: 405 k probes, 1.6 M buffers,
        1.43 s for one batch, heading straight for a permanent timeout.

        So it sweeps instead. A watermark walks ``created_at`` from the
        oldest accepted row towards the cutoff, one window at a time, and
        each DELETE is bounded to ``[watermark, window_end)``. The work per
        statement is then set by how many rows that window holds (~48 k an
        hour of hosted ingestion) and not by how far into the table the
        orphans have receded.

        A window is done when a batch deletes fewer rows than it asked for:
        the DELETE wanted ``batch_size`` matches and found fewer, so none
        are left in it, and the watermark moves to its end. A full batch
        leaves the watermark alone and takes the next batch out of the same
        window.

        A ``statement_timeout`` halves the window and retries -- each
        attempt costs a batch from the budget -- down to
        ``min_window_seconds``, below which the cycle gives up and reports
        the timeout. A ``lock_timeout`` is contention rather than a sizing
        problem, so it ends the cycle without shrinking anything. Each
        swept window doubles the size back towards the configured maximum,
        so one slow patch of history does not throttle the sweep forever.

        A window that deleted nothing at all may double past
        ``window_seconds`` up to ``max_window_seconds``, because empty
        history is exactly what a restart makes the sweep re-cross and
        there is nothing there to cost anything. The moment a window
        yields rows the size drops back to ``window_seconds``.
        """

        global _accepted_sweep_watermark, _accepted_sweep_window_seconds

        deleted_rows = 0
        batches = 0
        stopped_reason: StagingRetentionStopReason = "max_batches"
        window = min(
            max_window_seconds,
            max(
                min_window_seconds,
                _accepted_sweep_window_seconds or window_seconds,
            ),
        )
        watermark = _accepted_sweep_watermark

        with self._connect() as connection:
            try:
                source_ids = _committed_batch(
                    connection,
                    statement_timeout_ms=(
                        STAGING_EVIDENCE_METADATA_STATEMENT_TIMEOUT_MS
                    ),
                    lock_timeout_ms=lock_timeout_ms,
                    work=_fetch_orphan_prunable_source_ids,
                )
                if watermark is None:
                    watermark = _committed_batch(
                        connection,
                        statement_timeout_ms=(
                            STAGING_EVIDENCE_METADATA_STATEMENT_TIMEOUT_MS
                        ),
                        lock_timeout_ms=lock_timeout_ms,
                        work=_fetch_oldest_accepted_created_at,
                    )
            except Exception as exc:
                timeout_reason = _timeout_stop_reason(exc)
                if timeout_reason is None:
                    raise
                _rollback_quietly(connection)
                return _AcceptedSweepResult(
                    deleted_rows=0,
                    batches=0,
                    stopped_reason=timeout_reason,
                    source_count=0,
                    watermark=watermark,
                    window_seconds=window,
                )

            if not source_ids:
                return _AcceptedSweepResult(
                    deleted_rows=0,
                    batches=0,
                    stopped_reason="no_adapter_sources",
                    source_count=0,
                    watermark=watermark,
                    window_seconds=window,
                )
            if watermark is None:
                # No accepted row exists at all, so there is nothing to
                # sweep and nowhere to start one from next cycle either.
                return _AcceptedSweepResult(
                    deleted_rows=0,
                    batches=0,
                    stopped_reason="caught_up",
                    source_count=len(source_ids),
                    watermark=None,
                    window_seconds=window,
                )

            while batches < max_batches:
                if watermark >= cutoff:
                    stopped_reason = "caught_up"
                    break
                window_end = min(watermark + timedelta(seconds=window), cutoff)
                try:
                    batch_rows = _committed_batch(
                        connection,
                        statement_timeout_ms=statement_timeout_ms,
                        lock_timeout_ms=lock_timeout_ms,
                        work=partial(
                            _delete_accepted_staging_evidence_batch,
                            window_start=watermark,
                            window_end=window_end,
                            batch_size=batch_size,
                            source_ids=source_ids,
                        ),
                    )
                except Exception as exc:
                    timeout_reason = _timeout_stop_reason(exc)
                    if timeout_reason is None:
                        raise
                    _rollback_quietly(connection)
                    batches += 1
                    if (
                        timeout_reason != "statement_timeout"
                        or window <= min_window_seconds
                    ):
                        stopped_reason = timeout_reason
                        break
                    window = max(min_window_seconds, window // 2)
                    log_event(
                        "worker.maintenance.staging_accepted_retention_window_shrunk",
                        window_seconds=window,
                        watermark=watermark,
                    )
                    continue
                batches += 1
                deleted_rows += batch_rows
                if batch_rows >= batch_size:
                    # Dense enough to fill a batch. A window grown wide over
                    # empty history has done its job, so hand it back now
                    # rather than pay a run of timeouts to discover the same.
                    window = min(window, window_seconds)
                    continue
                watermark = window_end
                ceiling = max_window_seconds if batch_rows == 0 else window_seconds
                window = min(ceiling, window * 2)

        _accepted_sweep_watermark = watermark
        _accepted_sweep_window_seconds = window
        return _AcceptedSweepResult(
            deleted_rows=deleted_rows,
            batches=batches,
            stopped_reason=stopped_reason,
            source_count=len(source_ids),
            watermark=watermark,
            window_seconds=window,
        )

    def _ensure_partial_index(
        self,
        *,
        index_name: str,
        create_sql: str,
        enabled: bool,
        lock_timeout_ms: int,
    ) -> StagingIndexState:
        """Build the partial index a batch select needs, concurrently.

        ``CREATE INDEX CONCURRENTLY`` cannot run inside a transaction block, so
        this uses an autocommit connection, and it carries no
        ``statement_timeout``: on 14 M rows the build takes minutes, and a
        timeout would only leave an invalid index behind. ``lock_timeout`` is
        kept, because the brief locks the build does take must never queue
        behind ingestion.

        A previous build that died half way leaves an ``indisvalid = false``
        index that the planner ignores and that blocks a rebuild, so it is
        dropped concurrently first.

        ``enabled=False`` (``ENSURE_INDEX=false``) means an operator builds
        the index by hand in a window of their choosing. The validity probe
        still runs: taking the operator's word for it and deleting anyway
        bought nothing but the pathological scan, one cancelled batch per
        cycle, silently, for as long as the index stayed missing.
        """

        try:
            with (
                self._connect(autocommit=True) as connection,
                connection.cursor() as cursor,
            ):
                if _index_is_valid(cursor, index_name):
                    return "ready"
                if not enabled:
                    log_event(
                        "worker.maintenance.staging_retention_index_missing",
                        level="warning",
                        index_name=index_name,
                    )
                    return "skipped"
                _apply_index_build_timeouts(cursor, lock_timeout_ms=lock_timeout_ms)
                cursor.execute("DROP INDEX CONCURRENTLY IF EXISTS " + index_name)
                cursor.execute(create_sql)
                state: StagingIndexState = (
                    "ready" if _index_is_valid(cursor, index_name) else "building"
                )
                log_event(
                    "worker.maintenance.staging_retention_index_built",
                    index_name=index_name,
                    index_state=state,
                )
                return state
        except Exception as exc:
            # A failed build is not a failed maintenance cycle: the next cycle
            # retries, and until then the job simply does not delete.
            log_event(
                "worker.maintenance.staging_retention_index_failed",
                index_name=index_name,
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


def _committed_batch(
    connection: Any,
    *,
    statement_timeout_ms: int,
    lock_timeout_ms: int,
    work: Callable[[Any], _BatchResult],
) -> _BatchResult:
    """Run one statement in its own transaction under the batch timeouts.

    Every statement of every staging pass goes through here, so the
    transaction-local timeouts are applied exactly once per transaction and
    no pass can drift into forgetting either of them or the commit. The
    caller keeps the ``except`` clause, because what a timeout *means*
    differs per pass.
    """

    with connection.cursor() as cursor:
        _apply_staging_retention_timeouts(
            cursor,
            statement_timeout_ms=statement_timeout_ms,
            lock_timeout_ms=lock_timeout_ms,
        )
        result = work(cursor)
    connection.commit()
    return result


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


def _index_is_valid(cursor: Any, index_name: str) -> bool:
    """True only when the index exists here and the planner will use it.

    Scoped to ``current_schema()``: ``pg_class.relname`` is not unique
    across schemas, so without it a same-named index in another schema on
    the search_path reads as ready and the job deletes against a table that
    has no index at all.
    """

    cursor.execute(
        """
        SELECT idx.indisvalid
        FROM pg_class cls
        JOIN pg_index idx ON idx.indexrelid = cls.oid
        WHERE cls.relname = %s
            AND cls.relnamespace = current_schema()::regnamespace
        """,
        (index_name,),
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


def _fetch_orphan_prunable_source_ids(cursor: Any) -> tuple[str, ...]:
    """Resolve the allowed adapter keys into data_sources ids.

    ``data_sources`` is a few dozen rows, so this reads it whole once per
    cycle and classifies in Python; that keeps the adapter rule a pure,
    directly testable function instead of a second copy of it in SQL.
    """

    cursor.execute(
        """
        SELECT id, adapter_key
        FROM data_sources
        """
    )
    pairs = tuple(
        (
            (row["id"], row["adapter_key"])
            if isinstance(row, dict)
            else (row[0], row[1])
        )
        for row in (cursor.fetchall() or ())
    )
    source_ids = orphan_prunable_source_ids(pairs)
    _log_orphan_prunable_adapters(
        source_ids=source_ids,
        fallback_keys=legacy_fallback_adapter_keys(pairs),
    )
    return source_ids


def _log_orphan_prunable_adapters(
    *,
    source_ids: tuple[str, ...],
    fallback_keys: tuple[str, ...],
) -> None:
    """Report the allow-list, naming the fallback adapters only on a change.

    The counts go out every cycle so a dashboard can watch them; the key
    list only when the set actually moves, which is when a deploy added or
    reclassified an adapter and somebody should look.
    """

    global _accepted_fallback_adapter_keys

    changed = fallback_keys != _accepted_fallback_adapter_keys
    _accepted_fallback_adapter_keys = fallback_keys
    fields: dict[str, object] = {
        "source_count": len(source_ids),
        "legacy_fallback_count": len(fallback_keys),
        "legacy_fallback_changed": changed,
    }
    if changed:
        fields["legacy_fallback_adapter_keys"] = list(fallback_keys)
    log_event(
        "worker.maintenance.staging_accepted_retention_adapters", **fields
    )


def _fetch_oldest_accepted_created_at(cursor: Any) -> datetime | None:
    """Where a fresh sweep starts.

    ``min()`` over a partial index is a single descent of the btree, so
    this costs a few buffers even on the 12.6 M row accepted half.
    """

    cursor.execute(
        """
        SELECT min(created_at) AS oldest
        FROM staging_evidence
        WHERE validation_status = 'accepted'
        """
    )
    row = cursor.fetchone()
    if row is None:
        return None
    value = row["oldest"] if isinstance(row, dict) else row[0]
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _delete_accepted_staging_evidence_batch(
    cursor: Any,
    *,
    window_start: datetime,
    window_end: datetime,
    batch_size: int,
    source_ids: tuple[str, ...],
) -> int:
    # Like the rejected batch above, 'accepted' is a literal baked into the
    # SQL text rather than a bind parameter. The NOT EXISTS is what makes
    # deleting an accepted row safe at all: it is an index probe into
    # idx_evidence_staging_evidence_id (migration 0042), whose partial
    # predicate is repeated here so the planner can use it, and the
    # evidence side stores str(UUID(...)) -- the same canonical lowercase
    # text s.id::text produces.
    #
    # The half-open [window_start, window_end) bound is what keeps the cost
    # of a batch flat as the sweep advances; see _sweep_accepted_staging.
    # window_end is always capped at the retention cutoff by the caller, so
    # this needs no separate cutoff predicate.
    #
    # OFFSET 0 is an optimizer fence, not dead syntax: simplify_EXISTS_query
    # refuses to pull up a sublink carrying limitOffset, so the NOT EXISTS
    # stays a per-row SubPlan probe into 0042's index rather than becoming
    # an anti-join. Both shapes are correct and both use that index; the
    # fence is here because the SubPlan's cost is simply (rows in window) x
    # (one index probe), which is exactly what the window sizing reasons
    # about. The anti-join's cost instead depends on the join strategy and
    # on how many parallel workers happen to be available, which turns a
    # budget the sweep is supposed to control into something it cannot
    # predict.
    cursor.execute(
        """
        /* staging-retention-accepted */
        DELETE FROM staging_evidence
        WHERE id IN (
            SELECT s.id
            FROM staging_evidence s
            WHERE s.validation_status = 'accepted'
                AND s.created_at >= %s::timestamptz
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
            LIMIT %s
        )
        """,
        (window_start, window_end, list(source_ids), batch_size),
    )
    return int(cursor.rowcount or 0)


def _record_accepted_timeout_streak(
    stopped_reason: StagingRetentionStopReason,
) -> None:
    """The accepted pass's own streak.

    Separate from the rejected one on purpose: the passes have different
    indexes, query shapes and budgets, so a shared counter would let a
    healthy rejected cycle keep resetting an accepted pass that is timing
    out every five minutes.
    """

    global _accepted_timeout_streak

    if stopped_reason not in ("statement_timeout", "lock_timeout"):
        _accepted_timeout_streak = 0
        return
    _accepted_timeout_streak += 1
    if _accepted_timeout_streak < STAGING_RETENTION_TIMEOUT_WARNING_STREAK:
        return
    log_event(
        "worker.maintenance.staging_accepted_retention_timeout_streak",
        level="warning",
        streak=_accepted_timeout_streak,
        stopped_reason=stopped_reason,
        threshold=STAGING_RETENTION_TIMEOUT_WARNING_STREAK,
    )


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
