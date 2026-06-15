"""Retention pruning for high-volume realtime official station evidence.

Live ingestion of CWA rainfall (~570 stations) plus WRA/Civil IoT water levels
writes a new evidence row per station per cycle, so the ``evidence`` table grows
fast. Those ``rainfall``/``water_level`` rows are only used inside the realtime
scoring window (6 h) and the freshness panel, so they are pruned past a short
retention window. Historical evidence (flood potential, news, observed flood
reports) is intentionally NOT pruned here.

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

# Realtime station telemetry that is safe to prune past the retention window.
PRUNABLE_REALTIME_EVENT_TYPES: tuple[str, ...] = ("rainfall", "water_level")
DEFAULT_EVIDENCE_REALTIME_RETENTION_HOURS = 48
DEFAULT_EVIDENCE_PRUNE_BATCH_LIMIT = 50_000


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


def _row_count(row: Any) -> int:
    if row is None:
        return 0
    if isinstance(row, dict):
        return int(row.get("rows_deleted", 0) or 0)
    return int(row[0] or 0)


def _now() -> datetime:
    return datetime.now(UTC)
