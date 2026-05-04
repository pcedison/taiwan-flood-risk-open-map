from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from typing import Any, Literal

from app.jobs.queue import ConnectionFactory, RuntimeQueueUnavailable


ReplayAuditAction = Literal["replay", "poison_quarantine", "poison_release"]
ReplayAuditStatus = Literal["requested", "completed", "failed"]
PoisonQuarantineStatus = Literal["active", "released"]


@dataclass(frozen=True)
class RuntimeQueueReplayAuditRecord:
    id: str
    job_id: str
    action: ReplayAuditAction
    status: ReplayAuditStatus
    attempts_before: int | None
    attempts_after: int | None


@dataclass(frozen=True)
class RuntimeQueuePoisonQuarantineRecord:
    id: str
    job_id: str
    status: PoisonQuarantineStatus
    quarantined_by: str
    reason: str
    attempts_at_quarantine: int | None


@dataclass(frozen=True)
class AuditedRuntimeQueueRequeueResult:
    job_id: str
    requeued: bool
    reset_attempts: bool
    requested_audit_id: str | None = None
    outcome_audit_id: str | None = None
    attempts_before: int | None = None
    attempts_after: int | None = None
    reason: str | None = None


class PostgresRuntimeQueueReplayAudit:
    """DB primitives for replay audit and poison boundaries.

    The record/quarantine helpers intentionally only write audit/quarantine tables.
    The audited requeue helper is the explicit transactional boundary for manual
    replay: it locks the queue row, checks active quarantine, updates the job, and
    writes request/outcome audit rows in one commit.
    """

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

    def record_requested(
        self,
        *,
        job_id: str,
        requested_by: str,
        reason: str,
        attempts_before: int | None,
        attempts_after: int | None = None,
        metadata: Mapping[str, Any] | None = None,
        action: ReplayAuditAction = "replay",
    ) -> RuntimeQueueReplayAuditRecord:
        return self._insert_replay_audit(
            job_id=job_id,
            action=action,
            requested_by=requested_by,
            reason=reason,
            status="requested",
            attempts_before=attempts_before,
            attempts_after=attempts_after,
            metadata=metadata,
        )

    def record_completed(
        self,
        *,
        job_id: str,
        requested_by: str,
        attempts_before: int | None,
        attempts_after: int | None,
        reason: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        action: ReplayAuditAction = "replay",
    ) -> RuntimeQueueReplayAuditRecord:
        return self._insert_replay_audit(
            job_id=job_id,
            action=action,
            requested_by=requested_by,
            reason=reason,
            status="completed",
            attempts_before=attempts_before,
            attempts_after=attempts_after,
            metadata=metadata,
        )

    def record_failed(
        self,
        *,
        job_id: str,
        requested_by: str,
        reason: str,
        attempts_before: int | None,
        attempts_after: int | None,
        metadata: Mapping[str, Any] | None = None,
        action: ReplayAuditAction = "replay",
    ) -> RuntimeQueueReplayAuditRecord:
        return self._insert_replay_audit(
            job_id=job_id,
            action=action,
            requested_by=requested_by,
            reason=reason,
            status="failed",
            attempts_before=attempts_before,
            attempts_after=attempts_after,
            metadata=metadata,
        )

    def quarantine_poison_job(
        self,
        *,
        job_id: str,
        quarantined_by: str,
        reason: str,
        attempts_at_quarantine: int | None,
        metadata: Mapping[str, Any] | None = None,
    ) -> RuntimeQueuePoisonQuarantineRecord:
        _validate_attempts("attempts_at_quarantine", attempts_at_quarantine)
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO worker_runtime_queue_poison_quarantine (
                            job_id,
                            status,
                            quarantined_by,
                            reason,
                            attempts_at_quarantine,
                            metadata
                        )
                        VALUES (%s, 'active', %s, %s, %s, %s::jsonb)
                        ON CONFLICT (job_id)
                        WHERE status = 'active'
                            AND released_at IS NULL
                        DO UPDATE SET
                            reason = EXCLUDED.reason,
                            attempts_at_quarantine = EXCLUDED.attempts_at_quarantine,
                            metadata = (
                                worker_runtime_queue_poison_quarantine.metadata
                                || EXCLUDED.metadata
                            ),
                            updated_at = now()
                        RETURNING
                            id,
                            job_id,
                            status,
                            quarantined_by,
                            reason,
                            attempts_at_quarantine
                        """,
                        (
                            job_id,
                            quarantined_by,
                            reason,
                            attempts_at_quarantine,
                            _json(metadata or {}),
                        ),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise RuntimeError("poison quarantine insert did not return a row")
                connection.commit()
        except Exception as exc:
            raise RuntimeQueueUnavailable(str(exc)) from exc

        return _poison_quarantine_record(row)

    def release_poison_quarantine(
        self,
        *,
        job_id: str,
        released_by: str,
        reason: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> bool:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE worker_runtime_queue_poison_quarantine
                        SET
                            status = 'released',
                            released_by = %s,
                            released_reason = %s,
                            released_at = now(),
                            metadata = metadata || %s::jsonb,
                            updated_at = now()
                        WHERE
                            job_id = %s
                            AND status = 'active'
                            AND released_at IS NULL
                        RETURNING id
                        """,
                        (released_by, reason, _json(metadata or {}), job_id),
                    )
                    released = cursor.fetchone() is not None
                connection.commit()
        except Exception as exc:
            raise RuntimeQueueUnavailable(str(exc)) from exc

        return released

    def has_active_poison_quarantine(self, *, job_id: str) -> bool:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT 1
                        FROM worker_runtime_queue_poison_quarantine
                        WHERE
                            job_id = %s
                            AND status = 'active'
                            AND released_at IS NULL
                        LIMIT 1
                        """,
                        (job_id,),
                    )
                    active = cursor.fetchone() is not None
                connection.commit()
        except Exception as exc:
            raise RuntimeQueueUnavailable(str(exc)) from exc

        return active

    def requeue_failed_job_with_audit(
        self,
        *,
        job_id: str,
        requested_by: str,
        reason: str,
        reset_attempts: bool = True,
    ) -> AuditedRuntimeQueueRequeueResult:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT id, status, attempts
                        FROM worker_runtime_jobs
                        WHERE id = %s
                        FOR UPDATE
                        """,
                        (job_id,),
                    )
                    job_row = cursor.fetchone()
                    if job_row is None:
                        connection.commit()
                        return AuditedRuntimeQueueRequeueResult(
                            job_id=job_id,
                            requeued=False,
                            reset_attempts=reset_attempts,
                            reason="queue_row_not_found",
                        )

                    locked_job_id = str(job_row[0])
                    job_status = str(job_row[1])
                    attempts_before = _optional_int(job_row[2])
                    requested_record = self._insert_replay_audit_cursor(
                        cursor,
                        job_id=locked_job_id,
                        action="replay",
                        requested_by=requested_by,
                        reason=reason,
                        status="requested",
                        attempts_before=attempts_before,
                        attempts_after=None,
                        metadata={"reset_attempts": reset_attempts},
                    )
                    cursor.execute(
                        """
                        SELECT id
                        FROM worker_runtime_queue_poison_quarantine
                        WHERE
                            job_id = %s
                            AND status = 'active'
                            AND released_at IS NULL
                        FOR UPDATE
                        LIMIT 1
                        """,
                        (locked_job_id,),
                    )
                    active_quarantine = cursor.fetchone() is not None
                    if active_quarantine:
                        outcome_record = self._insert_replay_audit_cursor(
                            cursor,
                            job_id=locked_job_id,
                            action="replay",
                            requested_by=requested_by,
                            reason="poison_quarantine_active",
                            status="failed",
                            attempts_before=attempts_before,
                            attempts_after=attempts_before,
                            metadata={
                                "requested_reason": reason,
                                "requested_audit_id": requested_record.id,
                                "reset_attempts": reset_attempts,
                            },
                        )
                        connection.commit()
                        return AuditedRuntimeQueueRequeueResult(
                            job_id=locked_job_id,
                            requeued=False,
                            reset_attempts=reset_attempts,
                            requested_audit_id=requested_record.id,
                            outcome_audit_id=outcome_record.id,
                            attempts_before=attempts_before,
                            attempts_after=attempts_before,
                            reason="poison_quarantine_active",
                        )

                    if job_status != "failed":
                        outcome_record = self._insert_replay_audit_cursor(
                            cursor,
                            job_id=locked_job_id,
                            action="replay",
                            requested_by=requested_by,
                            reason="queue_row_not_failed",
                            status="failed",
                            attempts_before=attempts_before,
                            attempts_after=attempts_before,
                            metadata={
                                "requested_reason": reason,
                                "requested_audit_id": requested_record.id,
                                "reset_attempts": reset_attempts,
                                "status": job_status,
                            },
                        )
                        connection.commit()
                        return AuditedRuntimeQueueRequeueResult(
                            job_id=locked_job_id,
                            requeued=False,
                            reset_attempts=reset_attempts,
                            requested_audit_id=requested_record.id,
                            outcome_audit_id=outcome_record.id,
                            attempts_before=attempts_before,
                            attempts_after=attempts_before,
                            reason="queue_row_not_failed",
                        )

                    cursor.execute(
                        """
                        UPDATE worker_runtime_jobs
                        SET
                            status = 'queued',
                            attempts = CASE
                                WHEN %s THEN 0
                                ELSE attempts
                            END,
                            run_after = now(),
                            leased_by = NULL,
                            lease_expires_at = NULL,
                            final_failed_at = NULL,
                            finished_at = NULL,
                            last_error = NULL,
                            updated_at = now()
                        WHERE id = %s
                        RETURNING id, attempts
                        """,
                        (reset_attempts, locked_job_id),
                    )
                    updated_row = cursor.fetchone()
                    if updated_row is None:
                        outcome_record = self._insert_replay_audit_cursor(
                            cursor,
                            job_id=locked_job_id,
                            action="replay",
                            requested_by=requested_by,
                            reason="queue_row_not_updated",
                            status="failed",
                            attempts_before=attempts_before,
                            attempts_after=attempts_before,
                            metadata={
                                "requested_reason": reason,
                                "requested_audit_id": requested_record.id,
                                "reset_attempts": reset_attempts,
                            },
                        )
                        connection.commit()
                        return AuditedRuntimeQueueRequeueResult(
                            job_id=locked_job_id,
                            requeued=False,
                            reset_attempts=reset_attempts,
                            requested_audit_id=requested_record.id,
                            outcome_audit_id=outcome_record.id,
                            attempts_before=attempts_before,
                            attempts_after=attempts_before,
                            reason="queue_row_not_updated",
                        )

                    attempts_after = _optional_int(updated_row[1])
                    outcome_record = self._insert_replay_audit_cursor(
                        cursor,
                        job_id=locked_job_id,
                        action="replay",
                        requested_by=requested_by,
                        reason=reason,
                        status="completed",
                        attempts_before=attempts_before,
                        attempts_after=attempts_after,
                        metadata={"requested_audit_id": requested_record.id},
                    )
                connection.commit()
        except Exception as exc:
            raise RuntimeQueueUnavailable(str(exc)) from exc

        return AuditedRuntimeQueueRequeueResult(
            job_id=locked_job_id,
            requeued=True,
            reset_attempts=reset_attempts,
            requested_audit_id=requested_record.id,
            outcome_audit_id=outcome_record.id,
            attempts_before=attempts_before,
            attempts_after=attempts_after,
        )

    def _insert_replay_audit(
        self,
        *,
        job_id: str,
        action: ReplayAuditAction,
        requested_by: str,
        reason: str | None,
        status: ReplayAuditStatus,
        attempts_before: int | None,
        attempts_after: int | None,
        metadata: Mapping[str, Any] | None,
    ) -> RuntimeQueueReplayAuditRecord:
        _validate_attempts("attempts_before", attempts_before)
        _validate_attempts("attempts_after", attempts_after)
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    record = self._insert_replay_audit_cursor(
                        cursor,
                        job_id=job_id,
                        action=action,
                        requested_by=requested_by,
                        reason=reason,
                        status=status,
                        attempts_before=attempts_before,
                        attempts_after=attempts_after,
                        metadata=metadata,
                    )
                connection.commit()
        except Exception as exc:
            raise RuntimeQueueUnavailable(str(exc)) from exc

        return record

    def _insert_replay_audit_cursor(
        self,
        cursor: Any,
        *,
        job_id: str,
        action: ReplayAuditAction,
        requested_by: str,
        reason: str | None,
        status: ReplayAuditStatus,
        attempts_before: int | None,
        attempts_after: int | None,
        metadata: Mapping[str, Any] | None,
    ) -> RuntimeQueueReplayAuditRecord:
        cursor.execute(
            """
            INSERT INTO worker_runtime_queue_replay_audit (
                job_id,
                action,
                requested_by,
                reason,
                status,
                attempts_before,
                attempts_after,
                metadata,
                requested_at,
                completed_at,
                failed_at
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s::jsonb,
                CASE WHEN %s = 'requested' THEN now() ELSE NULL END,
                CASE WHEN %s = 'completed' THEN now() ELSE NULL END,
                CASE WHEN %s = 'failed' THEN now() ELSE NULL END
            )
            RETURNING
                id,
                job_id,
                action,
                status,
                attempts_before,
                attempts_after
            """,
            (
                job_id,
                action,
                requested_by,
                reason,
                status,
                attempts_before,
                attempts_after,
                _json(metadata or {}),
                status,
                status,
                status,
            ),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("replay audit insert did not return a row")
        return _replay_audit_record(row)

    def _connect(self) -> Any:
        if self._connection_factory is not None:
            return self._connection_factory()

        import psycopg

        assert self._database_url is not None
        return psycopg.connect(self._database_url)


def _replay_audit_record(row: tuple[Any, ...]) -> RuntimeQueueReplayAuditRecord:
    return RuntimeQueueReplayAuditRecord(
        id=str(row[0]),
        job_id=str(row[1]),
        action=row[2],
        status=row[3],
        attempts_before=_optional_int(row[4]),
        attempts_after=_optional_int(row[5]),
    )


def _poison_quarantine_record(row: tuple[Any, ...]) -> RuntimeQueuePoisonQuarantineRecord:
    return RuntimeQueuePoisonQuarantineRecord(
        id=str(row[0]),
        job_id=str(row[1]),
        status=row[2],
        quarantined_by=str(row[3]),
        reason=str(row[4]),
        attempts_at_quarantine=_optional_int(row[5]),
    )


def _json(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), sort_keys=True, separators=(",", ":"), default=str)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(str(value))


def _validate_attempts(name: str, value: int | None) -> None:
    if value is not None and value < 0:
        raise ValueError(f"{name} must be greater than or equal to 0")
