"""Retention pruning for high-volume realtime official station evidence.

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
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

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

    def _connect(self) -> Any:
        if self._connection_factory is not None:
            return self._connection_factory()

        import psycopg

        assert self._database_url is not None
        return psycopg.connect(self._database_url)


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


def _row_count(row: Any) -> int:
    if row is None:
        return 0
    if isinstance(row, dict):
        return int(row.get("rows_deleted", 0) or 0)
    return int(row[0] or 0)


def _now() -> datetime:
    return datetime.now(UTC)
