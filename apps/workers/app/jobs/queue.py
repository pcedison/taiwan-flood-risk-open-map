from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any, Literal


ConnectionFactory = Callable[[], Any]


class RuntimeQueueUnavailable(RuntimeError):
    """Raised when the durable queue database cannot be reached."""


@dataclass(frozen=True)
class RuntimeQueueJob:
    id: str
    queue_name: str
    job_key: str
    adapter_key: str | None
    payload: Mapping[str, Any]
    attempts: int
    max_attempts: int


RuntimeQueueEnqueueStatus = Literal["enqueued", "deduped", "skipped"]


@dataclass(frozen=True)
class RuntimeQueueEnqueueResult:
    status: RuntimeQueueEnqueueStatus
    job_id: str | None = None
    dedupe_key: str | None = None


@dataclass(frozen=True)
class RuntimeQueueDeadLetterJob:
    id: str
    queue_name: str
    job_key: str
    adapter_key: str | None
    payload: Mapping[str, Any]
    attempts: int
    max_attempts: int
    last_error: str | None
    final_failed_at: datetime | None
    dedupe_key: str | None


@dataclass(frozen=True)
class RuntimeQueueDeadLetterSummary:
    queue_name: str | None
    failed_terminal_count: int
    oldest_final_failed_at: datetime | None
    newest_final_failed_at: datetime | None
    max_attempts_observed: int | None
    max_configured_attempts: int | None


@dataclass(frozen=True)
class RuntimeQueueMetricsSnapshot:
    queue_name: str
    queued_count: int
    running_count: int
    final_failed_count: int
    expired_lease_count: int
    oldest_final_failed_at: datetime | None


@dataclass(frozen=True)
class RuntimeQueueRequeueResult:
    job_id: str
    requeued: bool
    reset_attempts: bool
    attempts: int | None = None


class NullRuntimeQueue:
    def acquire_scheduler_lease(
        self,
        *,
        lease_key: str,
        holder_id: str,
        ttl_seconds: int,
    ) -> bool:
        del lease_key, holder_id, ttl_seconds
        return True

    def release_scheduler_lease(self, *, lease_key: str, holder_id: str) -> None:
        del lease_key, holder_id

    def enqueue_adapter_job(
        self,
        *,
        adapter_key: str,
        job_key: str = "runtime.adapter.ingest",
        queue_name: str = "runtime-adapters",
        payload: Mapping[str, Any] | None = None,
        priority: int = 0,
        max_attempts: int = 3,
        run_after: datetime | None = None,
        dedupe_key: str | None = None,
    ) -> RuntimeQueueEnqueueResult:
        del adapter_key, job_key, queue_name, payload, priority, max_attempts, run_after
        return RuntimeQueueEnqueueResult(status="skipped", dedupe_key=dedupe_key)

    def dequeue_adapter_job(
        self,
        *,
        queue_name: str,
        worker_id: str,
        lease_seconds: int,
    ) -> RuntimeQueueJob | None:
        del queue_name, worker_id, lease_seconds
        return None

    def mark_job_succeeded(self, *, job_id: str, worker_id: str) -> bool:
        del job_id, worker_id
        return False

    def mark_job_failed(
        self,
        *,
        job_id: str,
        worker_id: str,
        error: str,
        retry_delay_seconds: int = 60,
    ) -> bool:
        del job_id, worker_id, error, retry_delay_seconds
        return False

    def list_dead_letter_jobs(
        self,
        *,
        queue_name: str | None = None,
        limit: int = 100,
    ) -> tuple[RuntimeQueueDeadLetterJob, ...]:
        del queue_name, limit
        return ()

    def summarize_dead_letter_jobs(
        self,
        *,
        queue_name: str | None = None,
    ) -> RuntimeQueueDeadLetterSummary:
        return RuntimeQueueDeadLetterSummary(
            queue_name=queue_name,
            failed_terminal_count=0,
            oldest_final_failed_at=None,
            newest_final_failed_at=None,
            max_attempts_observed=None,
            max_configured_attempts=None,
        )

    def collect_metrics(
        self,
        *,
        queue_name: str | None = None,
    ) -> tuple[RuntimeQueueMetricsSnapshot, ...]:
        return (
            RuntimeQueueMetricsSnapshot(
                queue_name=queue_name or "runtime-adapters",
                queued_count=0,
                running_count=0,
                final_failed_count=0,
                expired_lease_count=0,
                oldest_final_failed_at=None,
            ),
        )

    def requeue_failed_job(
        self,
        *,
        job_id: str,
        reset_attempts: bool = True,
        run_after: datetime | None = None,
    ) -> RuntimeQueueRequeueResult:
        del run_after
        return RuntimeQueueRequeueResult(
            job_id=job_id,
            requeued=False,
            reset_attempts=reset_attempts,
        )


class PostgresRuntimeQueue:
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

    def acquire_scheduler_lease(
        self,
        *,
        lease_key: str,
        holder_id: str,
        ttl_seconds: int,
    ) -> bool:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO worker_scheduler_leases (
                            lease_key,
                            holder_id,
                            lease_expires_at
                        )
                        VALUES (%s, %s, now() + make_interval(secs => %s))
                        ON CONFLICT (lease_key) DO UPDATE SET
                            holder_id = EXCLUDED.holder_id,
                            lease_expires_at = EXCLUDED.lease_expires_at,
                            updated_at = now()
                        WHERE worker_scheduler_leases.lease_expires_at <= now()
                            OR worker_scheduler_leases.holder_id = EXCLUDED.holder_id
                        RETURNING lease_key
                        """,
                        (lease_key, holder_id, ttl_seconds),
                    )
                    acquired = cursor.fetchone() is not None
                connection.commit()
        except Exception as exc:  # pragma: no cover - covered with fake connection failures
            raise RuntimeQueueUnavailable(str(exc)) from exc

        return acquired

    def release_scheduler_lease(self, *, lease_key: str, holder_id: str) -> None:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        DELETE FROM worker_scheduler_leases
                        WHERE lease_key = %s AND holder_id = %s
                        """,
                        (lease_key, holder_id),
                    )
                connection.commit()
        except Exception as exc:  # pragma: no cover - covered with fake connection failures
            raise RuntimeQueueUnavailable(str(exc)) from exc

    def enqueue_adapter_job(
        self,
        *,
        adapter_key: str,
        job_key: str = "runtime.adapter.ingest",
        queue_name: str = "runtime-adapters",
        payload: Mapping[str, Any] | None = None,
        priority: int = 0,
        max_attempts: int = 3,
        run_after: datetime | None = None,
        dedupe_key: str | None = None,
    ) -> RuntimeQueueEnqueueResult:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        WITH existing_active_job AS (
                            SELECT id
                            FROM worker_runtime_jobs
                            WHERE
                                queue_name = %s
                                AND job_key = %s
                                AND adapter_key IS NOT DISTINCT FROM %s
                                AND dedupe_key IS NOT DISTINCT FROM %s
                                AND dedupe_key IS NOT NULL
                                AND status IN ('queued', 'running')
                            ORDER BY created_at ASC
                            LIMIT 1
                        ),
                        inserted_job AS (
                            INSERT INTO worker_runtime_jobs (
                                queue_name,
                                job_key,
                                adapter_key,
                                payload,
                                priority,
                                max_attempts,
                                run_after,
                                dedupe_key
                            )
                            SELECT %s, %s, %s, %s::jsonb, %s, %s, COALESCE(%s, now()), %s
                            WHERE NOT EXISTS (SELECT 1 FROM existing_active_job)
                            ON CONFLICT (
                                queue_name,
                                job_key,
                                (COALESCE(adapter_key, ''::text)),
                                dedupe_key
                            )
                            WHERE status IN ('queued', 'running')
                                AND dedupe_key IS NOT NULL
                            DO UPDATE SET
                                dedupe_key = worker_runtime_jobs.dedupe_key
                            RETURNING id, (xmax = 0) AS inserted
                        )
                        SELECT id, false AS inserted FROM existing_active_job
                        UNION ALL
                        SELECT id, inserted FROM inserted_job
                        LIMIT 1
                        """,
                        (
                            queue_name,
                            job_key,
                            adapter_key,
                            dedupe_key,
                            queue_name,
                            job_key,
                            adapter_key,
                            _json(dict(payload or {})),
                            priority,
                            max_attempts,
                            run_after,
                            dedupe_key,
                        ),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise RuntimeError("runtime job enqueue did not return an id")
                    job_id = str(row[0])
                    inserted = _bool(row[1])
                connection.commit()
        except Exception as exc:
            raise RuntimeQueueUnavailable(str(exc)) from exc

        return RuntimeQueueEnqueueResult(
            status="enqueued" if inserted else "deduped",
            job_id=job_id,
            dedupe_key=dedupe_key,
        )

    def dequeue_adapter_job(
        self,
        *,
        queue_name: str,
        worker_id: str,
        lease_seconds: int,
    ) -> RuntimeQueueJob | None:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        WITH next_job AS (
                            SELECT id
                            FROM worker_runtime_jobs
                            WHERE queue_name = %s
                                AND (
                                    (
                                        status = 'queued'
                                        AND run_after <= now()
                                    )
                                    OR (
                                        status = 'running'
                                        AND lease_expires_at <= now()
                                        AND attempts < max_attempts
                                    )
                                )
                            ORDER BY priority DESC, run_after ASC, created_at ASC
                            FOR UPDATE SKIP LOCKED
                            LIMIT 1
                        )
                        UPDATE worker_runtime_jobs
                        SET
                            status = 'running',
                            attempts = attempts + 1,
                            leased_by = %s,
                            lease_expires_at = now() + make_interval(secs => %s),
                            started_at = COALESCE(started_at, now()),
                            updated_at = now()
                        WHERE id = (SELECT id FROM next_job)
                        RETURNING
                            id,
                            queue_name,
                            job_key,
                            adapter_key,
                            payload,
                            attempts,
                            max_attempts
                        """,
                        (queue_name, worker_id, lease_seconds),
                    )
                    row = cursor.fetchone()
                connection.commit()
        except Exception as exc:
            raise RuntimeQueueUnavailable(str(exc)) from exc

        if row is None:
            return None

        return RuntimeQueueJob(
            id=str(row[0]),
            queue_name=str(row[1]),
            job_key=str(row[2]),
            adapter_key=str(row[3]) if row[3] is not None else None,
            payload=_payload(row[4]),
            attempts=int(row[5]),
            max_attempts=int(row[6]),
        )

    def mark_job_succeeded(self, *, job_id: str, worker_id: str) -> bool:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE worker_runtime_jobs
                        SET
                            status = 'succeeded',
                            leased_by = NULL,
                            lease_expires_at = NULL,
                            final_failed_at = NULL,
                            finished_at = now(),
                            updated_at = now()
                        WHERE
                            id = %s
                            AND leased_by = %s
                            AND status = 'running'
                        RETURNING id
                        """,
                        (job_id, worker_id),
                    )
                    updated = cursor.fetchone() is not None
                connection.commit()
        except Exception as exc:
            raise RuntimeQueueUnavailable(str(exc)) from exc

        return updated

    def mark_job_failed(
        self,
        *,
        job_id: str,
        worker_id: str,
        error: str,
        retry_delay_seconds: int = 60,
    ) -> bool:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE worker_runtime_jobs
                        SET
                            status = CASE
                                WHEN attempts < max_attempts THEN 'queued'
                                ELSE 'failed'
                            END,
                            run_after = CASE
                                WHEN attempts < max_attempts
                                    THEN now() + make_interval(secs => %s)
                                ELSE run_after
                            END,
                            leased_by = NULL,
                            lease_expires_at = NULL,
                            final_failed_at = CASE
                                WHEN attempts < max_attempts THEN NULL
                                ELSE now()
                            END,
                            finished_at = CASE
                                WHEN attempts < max_attempts THEN finished_at
                                ELSE now()
                            END,
                            last_error = %s,
                            updated_at = now()
                        WHERE
                            id = %s
                            AND leased_by = %s
                            AND status = 'running'
                        RETURNING id
                        """,
                        (retry_delay_seconds, error[:1000], job_id, worker_id),
                    )
                    updated = cursor.fetchone() is not None
                connection.commit()
        except Exception as exc:
            raise RuntimeQueueUnavailable(str(exc)) from exc

        return updated

    def list_dead_letter_jobs(
        self,
        *,
        queue_name: str | None = None,
        limit: int = 100,
    ) -> tuple[RuntimeQueueDeadLetterJob, ...]:
        capped_limit = max(1, min(limit, 500))
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT
                            id,
                            queue_name,
                            job_key,
                            adapter_key,
                            payload,
                            attempts,
                            max_attempts,
                            last_error,
                            final_failed_at,
                            dedupe_key
                        FROM worker_runtime_jobs
                        WHERE
                            status = 'failed'
                            AND attempts >= max_attempts
                            AND (%s::text IS NULL OR queue_name = %s)
                        ORDER BY
                            COALESCE(final_failed_at, finished_at, updated_at) DESC,
                            created_at DESC
                        LIMIT %s
                        """,
                        (queue_name, queue_name, capped_limit),
                    )
                    rows = cursor.fetchall()
                connection.commit()
        except Exception as exc:
            raise RuntimeQueueUnavailable(str(exc)) from exc

        return tuple(
            RuntimeQueueDeadLetterJob(
                id=str(row[0]),
                queue_name=str(row[1]),
                job_key=str(row[2]),
                adapter_key=str(row[3]) if row[3] is not None else None,
                payload=_payload(row[4]),
                attempts=int(row[5]),
                max_attempts=int(row[6]),
                last_error=str(row[7]) if row[7] is not None else None,
                final_failed_at=row[8] if isinstance(row[8], datetime) else None,
                dedupe_key=str(row[9]) if row[9] is not None else None,
            )
            for row in rows
        )

    def summarize_dead_letter_jobs(
        self,
        *,
        queue_name: str | None = None,
    ) -> RuntimeQueueDeadLetterSummary:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT
                            count(*)::bigint AS failed_terminal_count,
                            min(COALESCE(final_failed_at, finished_at, updated_at))
                                AS oldest_final_failed_at,
                            max(COALESCE(final_failed_at, finished_at, updated_at))
                                AS newest_final_failed_at,
                            max(attempts) AS max_attempts_observed,
                            max(max_attempts) AS max_configured_attempts
                        FROM worker_runtime_jobs
                        WHERE
                            status = 'failed'
                            AND attempts >= max_attempts
                            AND (%s::text IS NULL OR queue_name = %s)
                        """,
                        (queue_name, queue_name),
                    )
                    row = cursor.fetchone()
                connection.commit()
        except Exception as exc:
            raise RuntimeQueueUnavailable(str(exc)) from exc

        if row is None:
            return RuntimeQueueDeadLetterSummary(
                queue_name=queue_name,
                failed_terminal_count=0,
                oldest_final_failed_at=None,
                newest_final_failed_at=None,
                max_attempts_observed=None,
                max_configured_attempts=None,
            )

        return RuntimeQueueDeadLetterSummary(
            queue_name=queue_name,
            failed_terminal_count=int(row[0] or 0),
            oldest_final_failed_at=row[1] if isinstance(row[1], datetime) else None,
            newest_final_failed_at=row[2] if isinstance(row[2], datetime) else None,
            max_attempts_observed=int(row[3]) if row[3] is not None else None,
            max_configured_attempts=int(row[4]) if row[4] is not None else None,
        )

    def collect_metrics(
        self,
        *,
        queue_name: str | None = None,
    ) -> tuple[RuntimeQueueMetricsSnapshot, ...]:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT
                            queue_name,
                            count(*) FILTER (WHERE status = 'queued')::bigint
                                AS queued_count,
                            count(*) FILTER (WHERE status = 'running')::bigint
                                AS running_count,
                            count(*) FILTER (
                                WHERE status = 'failed' AND attempts >= max_attempts
                            )::bigint AS final_failed_count,
                            count(*) FILTER (
                                WHERE
                                    status = 'running'
                                    AND lease_expires_at <= now()
                            )::bigint AS expired_lease_count,
                            min(COALESCE(final_failed_at, finished_at, updated_at)) FILTER (
                                WHERE status = 'failed' AND attempts >= max_attempts
                            ) AS oldest_final_failed_at
                        FROM worker_runtime_jobs
                        WHERE (%s::text IS NULL OR queue_name = %s)
                        GROUP BY queue_name
                        ORDER BY queue_name ASC
                        """,
                        (queue_name, queue_name),
                    )
                    rows = cursor.fetchall()
                connection.commit()
        except Exception as exc:
            raise RuntimeQueueUnavailable(str(exc)) from exc

        if not rows:
            return (
                RuntimeQueueMetricsSnapshot(
                    queue_name=queue_name or "runtime-adapters",
                    queued_count=0,
                    running_count=0,
                    final_failed_count=0,
                    expired_lease_count=0,
                    oldest_final_failed_at=None,
                ),
            )

        return tuple(
            RuntimeQueueMetricsSnapshot(
                queue_name=str(row[0]),
                queued_count=int(row[1] or 0),
                running_count=int(row[2] or 0),
                final_failed_count=int(row[3] or 0),
                expired_lease_count=int(row[4] or 0),
                oldest_final_failed_at=row[5] if isinstance(row[5], datetime) else None,
            )
            for row in rows
        )

    def requeue_failed_job(
        self,
        *,
        job_id: str,
        reset_attempts: bool = True,
        run_after: datetime | None = None,
    ) -> RuntimeQueueRequeueResult:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE worker_runtime_jobs
                        SET
                            status = 'queued',
                            attempts = CASE
                                WHEN %s THEN 0
                                ELSE attempts
                            END,
                            run_after = COALESCE(%s::timestamptz, now()),
                            leased_by = NULL,
                            lease_expires_at = NULL,
                            final_failed_at = NULL,
                            finished_at = NULL,
                            last_error = NULL,
                            updated_at = now()
                        WHERE
                            id = %s
                            AND status = 'failed'
                        RETURNING id, attempts
                        """,
                        (reset_attempts, run_after, job_id),
                    )
                    row = cursor.fetchone()
                connection.commit()
        except Exception as exc:
            raise RuntimeQueueUnavailable(str(exc)) from exc

        if row is None:
            return RuntimeQueueRequeueResult(
                job_id=job_id,
                requeued=False,
                reset_attempts=reset_attempts,
            )

        return RuntimeQueueRequeueResult(
            job_id=str(row[0]),
            requeued=True,
            reset_attempts=reset_attempts,
            attempts=int(row[1]),
        )

    def _connect(self) -> Any:
        if self._connection_factory is not None:
            return self._connection_factory()

        import psycopg

        assert self._database_url is not None
        return psycopg.connect(self._database_url)


def _json(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), sort_keys=True, separators=(",", ":"), default=str)


def _payload(value: object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str):
        decoded = json.loads(value)
        if isinstance(decoded, Mapping):
            return decoded
    return {}


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return value.lower() in {"1", "t", "true", "yes"}
    return False
