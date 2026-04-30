from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any


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
    ) -> str | None:
        del adapter_key, job_key, queue_name, payload, priority, max_attempts, run_after
        return None

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
    ) -> str:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO worker_runtime_jobs (
                            queue_name,
                            job_key,
                            adapter_key,
                            payload,
                            priority,
                            max_attempts,
                            run_after
                        )
                        VALUES (%s, %s, %s, %s::jsonb, %s, %s, COALESCE(%s, now()))
                        RETURNING id
                        """,
                        (
                            queue_name,
                            job_key,
                            adapter_key,
                            _json(dict(payload or {})),
                            priority,
                            max_attempts,
                            run_after,
                        ),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise RuntimeError("runtime job enqueue did not return an id")
                    job_id = str(row[0])
                connection.commit()
        except Exception as exc:
            raise RuntimeQueueUnavailable(str(exc)) from exc

        return job_id

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
