from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from app.config import load_worker_settings
from app.jobs.queue import (
    NullRuntimeQueue,
    PostgresRuntimeQueue,
    RuntimeQueueJob,
    RuntimeQueueUnavailable,
)
from app.jobs.runtime import (
    dequeue_runtime_adapter_job,
    enqueue_enabled_runtime_adapter_jobs,
    mark_runtime_adapter_job_failed,
    mark_runtime_adapter_job_succeeded,
)
from app.scheduler import run_enabled_adapters_loop


def test_scheduler_lease_acquire_release_sql_supports_expired_lease() -> None:
    connection = _FakeConnection(fetch_rows=[("scheduler.enabled-adapters",), None])
    queue = PostgresRuntimeQueue(connection_factory=lambda: connection)

    acquired = queue.acquire_scheduler_lease(
        lease_key="scheduler.enabled-adapters",
        holder_id="worker-a",
        ttl_seconds=60,
    )
    queue.release_scheduler_lease(
        lease_key="scheduler.enabled-adapters",
        holder_id="worker-a",
    )

    assert acquired is True
    assert connection.commits == 2
    acquire_sql, acquire_params = connection.cursor_instance.executions[0]
    release_sql, release_params = connection.cursor_instance.executions[1]
    assert "INSERT INTO worker_scheduler_leases" in acquire_sql
    assert "lease_expires_at <= now()" in acquire_sql
    assert acquire_params == ("scheduler.enabled-adapters", "worker-a", 60)
    assert "DELETE FROM worker_scheduler_leases" in release_sql
    assert release_params == ("scheduler.enabled-adapters", "worker-a")


def test_scheduler_lease_acquire_returns_false_when_active_holder_exists() -> None:
    queue = PostgresRuntimeQueue(
        connection_factory=lambda: _FakeConnection(fetch_rows=[None])
    )

    acquired = queue.acquire_scheduler_lease(
        lease_key="scheduler.enabled-adapters",
        holder_id="worker-b",
        ttl_seconds=60,
    )

    assert acquired is False


def test_runtime_queue_enqueue_dequeue_adapter_job() -> None:
    connection = _FakeConnection(
        fetch_rows=[
            ("job-1",),
            (
                "job-1",
                "runtime-adapters",
                "runtime.adapter.ingest",
                "official.cwa.rainfall",
                {"adapter_key": "official.cwa.rainfall"},
                1,
                3,
            ),
        ]
    )
    queue = PostgresRuntimeQueue(connection_factory=lambda: connection)

    job_id = queue.enqueue_adapter_job(
        adapter_key="official.cwa.rainfall",
        payload={"adapter_key": "official.cwa.rainfall"},
    )
    job = queue.dequeue_adapter_job(
        queue_name="runtime-adapters",
        worker_id="worker-a",
        lease_seconds=300,
    )

    assert job_id == "job-1"
    assert job is not None
    assert job.id == "job-1"
    assert job.adapter_key == "official.cwa.rainfall"
    assert job.payload["adapter_key"] == "official.cwa.rainfall"
    enqueue_sql, enqueue_params = connection.cursor_instance.executions[0]
    dequeue_sql, dequeue_params = connection.cursor_instance.executions[1]
    assert "INSERT INTO worker_runtime_jobs" in enqueue_sql
    assert enqueue_params[2] == "official.cwa.rainfall"
    assert "FOR UPDATE SKIP LOCKED" in dequeue_sql
    assert "lease_expires_at <= now()" in dequeue_sql
    assert dequeue_params == ("runtime-adapters", "worker-a", 300)


def test_runtime_queue_marks_adapter_job_succeeded() -> None:
    connection = _FakeConnection(fetch_rows=[("job-1",)])
    queue = PostgresRuntimeQueue(connection_factory=lambda: connection)

    updated = queue.mark_job_succeeded(job_id="job-1", worker_id="worker-a")

    assert updated is True
    sql, params = connection.cursor_instance.executions[0]
    assert "status = 'succeeded'" in sql
    assert "lease_expires_at = NULL" in sql
    assert "finished_at = now()" in sql
    assert params == ("job-1", "worker-a")


def test_runtime_queue_marks_failed_job_retryable_until_max_attempts() -> None:
    connection = _FakeConnection(fetch_rows=[("job-1",)])
    queue = PostgresRuntimeQueue(connection_factory=lambda: connection)

    updated = queue.mark_job_failed(
        job_id="job-1",
        worker_id="worker-a",
        error="source timeout",
        retry_delay_seconds=120,
    )

    assert updated is True
    sql, params = connection.cursor_instance.executions[0]
    assert "WHEN attempts < max_attempts THEN 'queued'" in sql
    assert "ELSE 'failed'" in sql
    assert "last_error = %s" in sql
    assert params == (120, "source timeout", "job-1", "worker-a")


def test_runtime_queue_unavailable_raises_for_db_errors() -> None:
    queue = PostgresRuntimeQueue(connection_factory=lambda: _BrokenConnection())

    try:
        queue.dequeue_adapter_job(
            queue_name="runtime-adapters",
            worker_id="worker-a",
            lease_seconds=300,
        )
    except RuntimeQueueUnavailable as exc:
        assert "database unavailable" in str(exc)
    else:
        raise AssertionError("expected RuntimeQueueUnavailable")


def test_enqueue_enabled_runtime_adapter_jobs_noops_without_database_url() -> None:
    settings = load_worker_settings(
        {"WORKER_ENABLED_ADAPTER_KEYS": "official.cwa.rainfall"}
    )

    assert enqueue_enabled_runtime_adapter_jobs(settings) == ()


def test_enqueue_enabled_runtime_adapter_jobs_uses_durable_queue_when_available() -> None:
    settings = load_worker_settings(
        {"WORKER_ENABLED_ADAPTER_KEYS": "official.cwa.rainfall,official.wra.water_level"}
    )
    queue = _CollectingQueue()

    job_ids = enqueue_enabled_runtime_adapter_jobs(settings, queue=queue)

    assert job_ids == ("job-1", "job-2")
    assert queue.adapter_keys == ["official.cwa.rainfall", "official.wra.water_level"]


def test_dequeue_runtime_adapter_job_noops_without_database_url() -> None:
    settings = load_worker_settings({})

    assert dequeue_runtime_adapter_job(settings) is None


def test_dequeue_runtime_adapter_job_uses_runtime_job_lease_seconds() -> None:
    settings = load_worker_settings(
        {
            "WORKER_INSTANCE": "worker-a",
            "WORKER_RUNTIME_JOB_LEASE_SECONDS": "120",
        }
    )
    queue = _DequeuingQueue()

    job = dequeue_runtime_adapter_job(settings, queue=queue)

    assert job is not None
    assert job.adapter_key == "official.cwa.rainfall"
    assert queue.dequeue_args == ("runtime-adapters", "worker-a", 120)


def test_runtime_adapter_job_completion_helpers_use_worker_identity() -> None:
    settings = load_worker_settings({"WORKER_INSTANCE": "worker-a"})
    queue = _CompletingQueue()

    assert mark_runtime_adapter_job_succeeded(settings, job_id="job-1", queue=queue)
    assert mark_runtime_adapter_job_failed(
        settings,
        job_id="job-2",
        error="source timeout",
        retry_delay_seconds=120,
        queue=queue,
    )
    assert queue.completed == [("succeeded", "job-1", "worker-a")]
    assert queue.failed == [("failed", "job-2", "worker-a", "source timeout", 120)]


def test_scheduler_loop_falls_back_when_database_lease_is_unavailable(monkeypatch) -> None:
    settings = load_worker_settings(
        {
            "WORKER_DATABASE_URL": "postgresql://worker:test@localhost/flood",
            "WORKER_ENABLED_ADAPTER_KEYS": "official.cwa.rainfall",
            "WORKER_RUNTIME_FIXTURES_ENABLED": "true",
        }
    )

    monkeypatch.setattr("app.scheduler.PostgresRuntimeQueue", _UnavailableQueue)

    results = run_enabled_adapters_loop(settings=settings, max_ticks=1)

    assert len(results) == 1


class _FakeConnection:
    def __init__(self, *, fetch_rows: list[tuple[Any, ...] | None]) -> None:
        self.cursor_instance = _FakeCursor(fetch_rows=fetch_rows)
        self.commits = 0

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.commits += 1


class _FakeCursor:
    def __init__(self, *, fetch_rows: list[tuple[Any, ...] | None]) -> None:
        self._fetch_rows = fetch_rows
        self.executions: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.executions.append((sql, params))

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._fetch_rows.pop(0)


class _BrokenConnection:
    def __enter__(self) -> _BrokenConnection:
        raise RuntimeError("database unavailable")

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


class _CollectingQueue(NullRuntimeQueue):
    def __init__(self) -> None:
        self.adapter_keys: list[str] = []

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
        del job_key, queue_name, payload, priority, max_attempts, run_after
        self.adapter_keys.append(adapter_key)
        return f"job-{len(self.adapter_keys)}"


class _DequeuingQueue(NullRuntimeQueue):
    def __init__(self) -> None:
        self.dequeue_args: tuple[str, str, int] | None = None

    def dequeue_adapter_job(
        self,
        *,
        queue_name: str,
        worker_id: str,
        lease_seconds: int,
    ) -> RuntimeQueueJob:
        self.dequeue_args = (queue_name, worker_id, lease_seconds)
        return RuntimeQueueJob(
            id="job-1",
            queue_name=queue_name,
            job_key="runtime.adapter.ingest",
            adapter_key="official.cwa.rainfall",
            payload={"adapter_key": "official.cwa.rainfall"},
            attempts=1,
            max_attempts=3,
        )


class _CompletingQueue(NullRuntimeQueue):
    def __init__(self) -> None:
        self.completed: list[tuple[str, str, str]] = []
        self.failed: list[tuple[str, str, str, str, int]] = []

    def mark_job_succeeded(self, *, job_id: str, worker_id: str) -> bool:
        self.completed.append(("succeeded", job_id, worker_id))
        return True

    def mark_job_failed(
        self,
        *,
        job_id: str,
        worker_id: str,
        error: str,
        retry_delay_seconds: int = 60,
    ) -> bool:
        self.failed.append(("failed", job_id, worker_id, error, retry_delay_seconds))
        return True


class _UnavailableQueue:
    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    def acquire_scheduler_lease(
        self,
        *,
        lease_key: str,
        holder_id: str,
        ttl_seconds: int,
    ) -> bool:
        del lease_key, holder_id, ttl_seconds
        raise RuntimeQueueUnavailable("database unavailable")
