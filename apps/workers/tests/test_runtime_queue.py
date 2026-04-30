from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.adapters.contracts import (
    AdapterMetadata,
    AdapterRunResult,
    NormalizedEvidence,
    RawSourceItem,
    SourceFamily,
)
from app.adapters.cwa import CwaRainfallConfigurationError
from app.config import load_worker_settings
from app.jobs.queue import (
    NullRuntimeQueue,
    PostgresRuntimeQueue,
    RuntimeQueueEnqueueResult,
    RuntimeQueueJob,
    RuntimeQueueRequeueResult,
    RuntimeQueueUnavailable,
)
from app.jobs.runtime import (
    build_runtime_adapters,
    dequeue_runtime_adapter_job,
    enqueue_enabled_runtime_adapter_jobs,
    mark_runtime_adapter_job_failed,
    mark_runtime_adapter_job_succeeded,
    produce_enabled_runtime_adapter_jobs,
    work_runtime_queue_once,
)
from app.scheduler import enqueue_enabled_adapters_loop, run_enabled_adapters_loop


FIXTURES = Path(__file__).parent / "fixtures"


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
            ("job-1", True),
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

    enqueue_result = queue.enqueue_adapter_job(
        adapter_key="official.cwa.rainfall",
        payload={"adapter_key": "official.cwa.rainfall"},
        dedupe_key="runtime-adapters:runtime.adapter.ingest:official.cwa.rainfall",
    )
    job = queue.dequeue_adapter_job(
        queue_name="runtime-adapters",
        worker_id="worker-a",
        lease_seconds=300,
    )

    assert enqueue_result.status == "enqueued"
    assert enqueue_result.job_id == "job-1"
    assert (
        enqueue_result.dedupe_key
        == "runtime-adapters:runtime.adapter.ingest:official.cwa.rainfall"
    )
    assert job is not None
    assert job.id == "job-1"
    assert job.adapter_key == "official.cwa.rainfall"
    assert job.payload["adapter_key"] == "official.cwa.rainfall"
    enqueue_sql, enqueue_params = connection.cursor_instance.executions[0]
    dequeue_sql, dequeue_params = connection.cursor_instance.executions[1]
    assert "INSERT INTO worker_runtime_jobs" in enqueue_sql
    assert "dedupe_key" in enqueue_sql
    assert "ON CONFLICT" in enqueue_sql
    assert "existing_active_job" in enqueue_sql
    assert "adapter_key IS NOT DISTINCT FROM %s" in enqueue_sql
    assert "dedupe_key IS NOT DISTINCT FROM %s" in enqueue_sql
    assert "dedupe_key IS NOT NULL" in enqueue_sql
    assert "status IN ('queued', 'running')" in enqueue_sql
    assert enqueue_params[2] == "official.cwa.rainfall"
    assert (
        enqueue_params[3]
        == "runtime-adapters:runtime.adapter.ingest:official.cwa.rainfall"
    )
    assert (
        enqueue_params[-1]
        == "runtime-adapters:runtime.adapter.ingest:official.cwa.rainfall"
    )
    assert "FOR UPDATE SKIP LOCKED" in dequeue_sql
    assert "lease_expires_at <= now()" in dequeue_sql
    assert dequeue_params == ("runtime-adapters", "worker-a", 300)


def test_runtime_queue_enqueue_reports_existing_active_dedupe_job() -> None:
    connection = _FakeConnection(fetch_rows=[("job-existing", False)])
    queue = PostgresRuntimeQueue(connection_factory=lambda: connection)

    result = queue.enqueue_adapter_job(
        adapter_key="official.cwa.rainfall",
        job_key="scheduler.enqueue.enabled_adapters",
        payload={"adapter_key": "official.cwa.rainfall"},
        dedupe_key="runtime-adapters:scheduler.enqueue.enabled_adapters:official.cwa.rainfall",
    )

    assert result.status == "deduped"
    assert result.job_id == "job-existing"
    assert (
        result.dedupe_key
        == "runtime-adapters:scheduler.enqueue.enabled_adapters:official.cwa.rainfall"
    )
    sql, params = connection.cursor_instance.executions[0]
    assert "ON CONFLICT" in sql
    assert "WHERE NOT EXISTS (SELECT 1 FROM existing_active_job)" in sql
    assert "DO UPDATE SET" in sql
    assert "RETURNING id, (xmax = 0) AS inserted" in sql
    assert params[1] == "scheduler.enqueue.enabled_adapters"
    assert params[-1] == result.dedupe_key


def test_runtime_queue_marks_adapter_job_succeeded() -> None:
    connection = _FakeConnection(fetch_rows=[("job-1",)])
    queue = PostgresRuntimeQueue(connection_factory=lambda: connection)

    updated = queue.mark_job_succeeded(job_id="job-1", worker_id="worker-a")

    assert updated is True
    sql, params = connection.cursor_instance.executions[0]
    assert "status = 'succeeded'" in sql
    assert "lease_expires_at = NULL" in sql
    assert "final_failed_at = NULL" in sql
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
    assert "final_failed_at = CASE" in sql
    assert "ELSE now()" in sql
    assert "last_error = %s" in sql
    assert params == (120, "source timeout", "job-1", "worker-a")


def test_runtime_queue_lists_final_failed_jobs_for_dead_letter_visibility() -> None:
    final_failed_at = datetime(2026, 4, 30, 8, 0, tzinfo=UTC)
    connection = _FakeConnection(
        fetch_rows=[
            (
                "job-1",
                "runtime-adapters",
                "runtime.adapter.ingest",
                "official.cwa.rainfall",
                {"adapter_key": "official.cwa.rainfall"},
                3,
                3,
                "source timeout",
                final_failed_at,
                "runtime-adapters:runtime.adapter.ingest:official.cwa.rainfall",
            )
        ]
    )
    queue = PostgresRuntimeQueue(connection_factory=lambda: connection)

    jobs = queue.list_dead_letter_jobs(queue_name="runtime-adapters", limit=25)

    assert len(jobs) == 1
    assert jobs[0].id == "job-1"
    assert jobs[0].attempts == 3
    assert jobs[0].max_attempts == 3
    assert jobs[0].last_error == "source timeout"
    assert jobs[0].final_failed_at == final_failed_at
    assert (
        jobs[0].dedupe_key
        == "runtime-adapters:runtime.adapter.ingest:official.cwa.rainfall"
    )
    sql, params = connection.cursor_instance.executions[0]
    assert "status = 'failed'" in sql
    assert "attempts >= max_attempts" in sql
    assert "%s::text IS NULL" in sql
    assert "COALESCE(final_failed_at, finished_at, updated_at)" in sql
    assert params == ("runtime-adapters", "runtime-adapters", 25)


def test_runtime_queue_requeues_failed_job_resetting_attempts_by_default() -> None:
    connection = _FakeConnection(fetch_rows=[("job-1", 0)])
    queue = PostgresRuntimeQueue(connection_factory=lambda: connection)

    result = queue.requeue_failed_job(job_id="job-1")

    assert result == RuntimeQueueRequeueResult(
        job_id="job-1",
        requeued=True,
        reset_attempts=True,
        attempts=0,
    )
    sql, params = connection.cursor_instance.executions[0]
    assert "UPDATE worker_runtime_jobs" in sql
    assert "status = 'queued'" in sql
    assert "attempts = CASE" in sql
    assert "WHEN %s THEN 0" in sql
    assert "run_after = COALESCE(%s::timestamptz, now())" in sql
    assert "leased_by = NULL" in sql
    assert "lease_expires_at = NULL" in sql
    assert "final_failed_at = NULL" in sql
    assert "finished_at = NULL" in sql
    assert "last_error = NULL" in sql
    assert "AND status = 'failed'" in sql
    assert params == (True, None, "job-1")


def test_runtime_queue_requeues_failed_job_can_keep_attempts() -> None:
    run_after = datetime(2026, 4, 30, 9, 0, tzinfo=UTC)
    connection = _FakeConnection(fetch_rows=[("job-1", 3)])
    queue = PostgresRuntimeQueue(connection_factory=lambda: connection)

    result = queue.requeue_failed_job(
        job_id="job-1",
        reset_attempts=False,
        run_after=run_after,
    )

    assert result == RuntimeQueueRequeueResult(
        job_id="job-1",
        requeued=True,
        reset_attempts=False,
        attempts=3,
    )
    _, params = connection.cursor_instance.executions[0]
    assert params == (False, run_after, "job-1")


def test_runtime_queue_requeue_reports_not_updated_for_non_failed_job() -> None:
    queue = PostgresRuntimeQueue(connection_factory=lambda: _FakeConnection(fetch_rows=[None]))

    result = queue.requeue_failed_job(job_id="job-running")

    assert result == RuntimeQueueRequeueResult(
        job_id="job-running",
        requeued=False,
        reset_attempts=True,
    )


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


def test_build_runtime_adapters_noops_without_fixture_or_cwa_api_gate() -> None:
    settings = load_worker_settings(
        {"WORKER_ENABLED_ADAPTER_KEYS": "official.cwa.rainfall"}
    )

    assert build_runtime_adapters(settings) == {}


def test_build_runtime_adapters_respects_cwa_source_gate_even_with_api_gate() -> None:
    settings = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": "official.cwa.rainfall",
            "SOURCE_CWA_ENABLED": "false",
            "SOURCE_CWA_API_ENABLED": "true",
            "CWA_API_AUTHORIZATION": "test-token",
        }
    )

    assert build_runtime_adapters(settings) == {}


def test_build_runtime_adapters_constructs_cwa_api_adapter_with_configured_client() -> None:
    captured: dict[str, object] = {}

    def fetch_json(url: str, timeout_seconds: int) -> dict[str, Any]:
        captured["url"] = url
        captured["timeout_seconds"] = timeout_seconds
        return _load_cwa_api_payload()

    settings = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": "official.cwa.rainfall",
            "SOURCE_CWA_API_ENABLED": "true",
            "CWA_API_AUTHORIZATION": "test-token",
            "CWA_API_URL": "https://example.test/cwa/rainfall",
            "CWA_API_TIMEOUT_SECONDS": "4",
        }
    )

    adapters = build_runtime_adapters(
        settings,
        fetched_at=datetime(2026, 4, 28, 8, 10, tzinfo=UTC),
        cwa_fetch_json=fetch_json,
    )
    result = adapters["official.cwa.rainfall"].run()

    assert tuple(adapters) == ("official.cwa.rainfall",)
    assert captured["timeout_seconds"] == 4
    assert "Authorization=test-token" in str(captured["url"])
    assert len(result.fetched) == 1
    assert len(result.normalized) == 1


def test_build_runtime_adapters_missing_cwa_auth_fails_without_fetch_call() -> None:
    called = False

    def fetch_json(url: str, timeout_seconds: int) -> dict[str, Any]:
        nonlocal called
        del url, timeout_seconds
        called = True
        return _load_cwa_api_payload()

    settings = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": "official.cwa.rainfall",
            "SOURCE_CWA_API_ENABLED": "true",
        }
    )

    adapters = build_runtime_adapters(settings, cwa_fetch_json=fetch_json)

    with pytest.raises(CwaRainfallConfigurationError, match="CWA_API_AUTHORIZATION"):
        adapters["official.cwa.rainfall"].run()
    assert called is False


def test_produce_enabled_runtime_adapter_jobs_reports_no_database_url() -> None:
    settings = load_worker_settings(
        {"WORKER_ENABLED_ADAPTER_KEYS": "official.cwa.rainfall"}
    )

    result = produce_enabled_runtime_adapter_jobs(settings)

    assert result.status == "skipped"
    assert result.reason == "no_database_url"
    assert result.adapter_keys == ("official.cwa.rainfall",)
    assert result.job_ids == ()


def test_produce_enabled_runtime_adapter_jobs_reports_no_enabled_adapters() -> None:
    settings = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": "official.cwa.rainfall",
            "SOURCE_CWA_ENABLED": "false",
        }
    )
    queue = _RecordingProducerQueue()

    result = produce_enabled_runtime_adapter_jobs(settings, queue=queue)

    assert result.status == "skipped"
    assert result.reason == "no_enabled_adapters"
    assert result.adapter_keys == ()
    assert result.job_ids == ()
    assert queue.enqueued == []


def test_enqueue_enabled_runtime_adapter_jobs_uses_durable_queue_when_available() -> None:
    settings = load_worker_settings(
        {"WORKER_ENABLED_ADAPTER_KEYS": "official.cwa.rainfall,official.wra.water_level"}
    )
    queue = _CollectingQueue()

    job_ids = enqueue_enabled_runtime_adapter_jobs(settings, queue=queue)

    assert job_ids == ("job-1", "job-2")
    assert queue.adapter_keys == ["official.cwa.rainfall", "official.wra.water_level"]


def test_produce_enabled_runtime_adapter_jobs_records_payloads_and_job_key() -> None:
    settings = load_worker_settings(
        {"WORKER_ENABLED_ADAPTER_KEYS": "official.cwa.rainfall,official.wra.water_level"}
    )
    queue = _RecordingProducerQueue()

    result = produce_enabled_runtime_adapter_jobs(
        settings,
        queue=queue,
        job_key="test.enqueue.runtime",
    )

    assert result.status == "succeeded"
    assert result.reason is None
    assert result.adapter_keys == ("official.cwa.rainfall", "official.wra.water_level")
    assert result.job_ids == ("job-1", "job-2")
    assert result.enqueued_job_ids == ("job-1", "job-2")
    assert result.deduped_job_ids == ()
    assert result.dedupe_keys == (
        "runtime-adapters:test.enqueue.runtime:official.cwa.rainfall",
        "runtime-adapters:test.enqueue.runtime:official.wra.water_level",
    )
    assert queue.enqueued == [
        (
            "official.cwa.rainfall",
            "test.enqueue.runtime",
            "runtime-adapters",
            {"adapter_key": "official.cwa.rainfall"},
            "runtime-adapters:test.enqueue.runtime:official.cwa.rainfall",
        ),
        (
            "official.wra.water_level",
            "test.enqueue.runtime",
            "runtime-adapters",
            {"adapter_key": "official.wra.water_level"},
            "runtime-adapters:test.enqueue.runtime:official.wra.water_level",
        ),
    ]


def test_produce_enabled_runtime_adapter_jobs_reports_deduped_existing_jobs() -> None:
    settings = load_worker_settings(
        {"WORKER_ENABLED_ADAPTER_KEYS": "official.cwa.rainfall,official.wra.water_level"}
    )
    queue = _RecordingProducerQueue(
        results=[
            RuntimeQueueEnqueueResult(
                status="deduped",
                job_id="existing-rainfall",
                dedupe_key="runtime-adapters:test.enqueue.runtime:official.cwa.rainfall",
            ),
            RuntimeQueueEnqueueResult(
                status="deduped",
                job_id="existing-water-level",
                dedupe_key="runtime-adapters:test.enqueue.runtime:official.wra.water_level",
            ),
        ]
    )

    result = produce_enabled_runtime_adapter_jobs(
        settings,
        queue=queue,
        job_key="test.enqueue.runtime",
    )

    assert result.status == "deduped"
    assert result.reason == "active_jobs_already_exist"
    assert result.job_ids == ("existing-rainfall", "existing-water-level")
    assert result.enqueued_job_ids == ()
    assert result.deduped_job_ids == ("existing-rainfall", "existing-water-level")
    assert result.durable_job_count == 2
    assert result.enqueued_job_count == 0
    assert result.deduped_job_count == 2
    assert queue.enqueued == [
        (
            "official.cwa.rainfall",
            "test.enqueue.runtime",
            "runtime-adapters",
            {"adapter_key": "official.cwa.rainfall"},
            "runtime-adapters:test.enqueue.runtime:official.cwa.rainfall",
        ),
        (
            "official.wra.water_level",
            "test.enqueue.runtime",
            "runtime-adapters",
            {"adapter_key": "official.wra.water_level"},
            "runtime-adapters:test.enqueue.runtime:official.wra.water_level",
        ),
    ]


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


def test_work_runtime_queue_once_noops_without_database_url() -> None:
    result = work_runtime_queue_once(settings=load_worker_settings({}))

    assert result.status == "skipped"
    assert result.reason == "no_database_url"


def test_work_runtime_queue_once_noops_when_no_job() -> None:
    settings = load_worker_settings({"WORKER_INSTANCE": "worker-a"})
    queue = _RuntimeWorkerQueue(job=None)

    result = work_runtime_queue_once(settings=settings, queue=queue)

    assert result.status == "skipped"
    assert result.reason == "no_job"
    assert queue.completed == []
    assert queue.failed == []


def test_work_runtime_queue_once_runs_adapter_and_marks_succeeded() -> None:
    settings = load_worker_settings(
        {
            "WORKER_INSTANCE": "worker-a",
            "WORKER_RUNTIME_FIXTURES_ENABLED": "true",
            "FRESHNESS_MAX_AGE_SECONDS": "21600",
        }
    )
    queue = _RuntimeWorkerQueue(
        job=_runtime_job(adapter_key="official.cwa.rainfall"),
    )

    result = work_runtime_queue_once(settings=settings, queue=queue)

    assert result.status == "succeeded"
    assert result.adapter_key == "official.cwa.rainfall"
    assert result.summary is not None
    assert result.summary.status == "succeeded"
    assert queue.completed == [("succeeded", "job-1", "worker-a")]
    assert queue.failed == []


def test_work_runtime_queue_once_fails_when_completion_row_is_not_updated() -> None:
    settings = load_worker_settings(
        {
            "WORKER_INSTANCE": "worker-a",
            "WORKER_RUNTIME_FIXTURES_ENABLED": "true",
            "FRESHNESS_MAX_AGE_SECONDS": "21600",
        }
    )
    queue = _LostCompletionQueue(job=_runtime_job(adapter_key="official.cwa.rainfall"))

    result = work_runtime_queue_once(settings=settings, queue=queue)

    assert result.status == "failed"
    assert result.adapter_key == "official.cwa.rainfall"
    assert result.reason == "queue_completion_not_updated"
    assert result.summary is not None
    assert result.summary.status == "succeeded"
    assert queue.completed == [("succeeded", "job-1", "worker-a")]
    assert queue.failed == []


def test_work_runtime_queue_once_marks_unknown_adapter_failed() -> None:
    settings = load_worker_settings(
        {
            "WORKER_INSTANCE": "worker-a",
            "WORKER_RUNTIME_FIXTURES_ENABLED": "true",
        }
    )
    queue = _RuntimeWorkerQueue(job=_runtime_job(adapter_key="unknown.adapter"))

    result = work_runtime_queue_once(settings=settings, queue=queue)

    assert result.status == "failed"
    assert result.adapter_key == "unknown.adapter"
    assert result.reason == "unknown runtime adapter_key: unknown.adapter"
    assert queue.completed == []
    assert queue.failed == [
        (
            "failed",
            "job-1",
            "worker-a",
            "unknown runtime adapter_key: unknown.adapter",
            60,
        )
    ]


def test_work_runtime_queue_once_marks_adapter_exception_failed() -> None:
    settings = load_worker_settings({"WORKER_INSTANCE": "worker-a"})
    queue = _RuntimeWorkerQueue(job=_runtime_job(adapter_key="official.cwa.rainfall"))

    result = work_runtime_queue_once(
        settings=settings,
        queue=queue,
        adapter_by_key={"official.cwa.rainfall": _FailingAdapter()},
    )

    assert result.status == "failed"
    assert result.adapter_key == "official.cwa.rainfall"
    assert result.summary is not None
    assert result.summary.status == "failed"
    assert result.reason == "source timeout"
    assert queue.completed == []
    assert queue.failed == [("failed", "job-1", "worker-a", "source timeout", 60)]


def test_work_runtime_queue_once_noops_when_database_unavailable() -> None:
    settings = load_worker_settings(
        {
            "WORKER_DATABASE_URL": "postgresql://worker:test@localhost/flood",
            "WORKER_INSTANCE": "worker-a",
        }
    )
    queue = _UnavailableDequeueQueue()

    result = work_runtime_queue_once(settings=settings, queue=queue)

    assert result.status == "skipped"
    assert result.reason == "queue_unavailable"


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


def test_scheduler_enqueue_loop_skips_when_database_lease_is_held(monkeypatch) -> None:
    settings = load_worker_settings(
        {
            "WORKER_DATABASE_URL": "postgresql://worker:test@localhost/flood",
            "WORKER_ENABLED_ADAPTER_KEYS": "official.cwa.rainfall",
            "WORKER_INSTANCE": "worker-a",
        }
    )
    queue = _RecordingProducerQueue()

    monkeypatch.setattr("app.scheduler.PostgresRuntimeQueue", _LeaseHeldQueue)

    results = enqueue_enabled_adapters_loop(settings=settings, queue=queue, max_ticks=1)

    assert results == ()
    assert queue.enqueued == []


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

    def fetchall(self) -> list[tuple[Any, ...]]:
        rows = [row for row in self._fetch_rows if row is not None]
        self._fetch_rows = []
        return rows


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
        dedupe_key: str | None = None,
    ) -> RuntimeQueueEnqueueResult:
        del job_key, queue_name, payload, priority, max_attempts, run_after
        self.adapter_keys.append(adapter_key)
        return RuntimeQueueEnqueueResult(
            status="enqueued",
            job_id=f"job-{len(self.adapter_keys)}",
            dedupe_key=dedupe_key,
        )


class _RecordingProducerQueue(NullRuntimeQueue):
    def __init__(self, *, results: list[RuntimeQueueEnqueueResult] | None = None) -> None:
        self.enqueued: list[tuple[str, str, str, Mapping[str, Any] | None, str | None]] = []
        self._results = list(results or [])

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
        del priority, max_attempts, run_after
        self.enqueued.append((adapter_key, job_key, queue_name, payload, dedupe_key))
        if self._results:
            return self._results.pop(0)
        return RuntimeQueueEnqueueResult(
            status="enqueued",
            job_id=f"job-{len(self.enqueued)}",
            dedupe_key=dedupe_key,
        )


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


class _RuntimeWorkerQueue(NullRuntimeQueue):
    def __init__(self, *, job: RuntimeQueueJob | None) -> None:
        self.job = job
        self.dequeue_args: tuple[str, str, int] | None = None
        self.completed: list[tuple[str, str, str]] = []
        self.failed: list[tuple[str, str, str, str, int]] = []

    def dequeue_adapter_job(
        self,
        *,
        queue_name: str,
        worker_id: str,
        lease_seconds: int,
    ) -> RuntimeQueueJob | None:
        self.dequeue_args = (queue_name, worker_id, lease_seconds)
        job = self.job
        self.job = None
        return job

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


class _LostCompletionQueue(_RuntimeWorkerQueue):
    def mark_job_succeeded(self, *, job_id: str, worker_id: str) -> bool:
        self.completed.append(("succeeded", job_id, worker_id))
        return False


class _UnavailableDequeueQueue(NullRuntimeQueue):
    def dequeue_adapter_job(
        self,
        *,
        queue_name: str,
        worker_id: str,
        lease_seconds: int,
    ) -> RuntimeQueueJob | None:
        del queue_name, worker_id, lease_seconds
        raise RuntimeQueueUnavailable("database unavailable")


class _FailingAdapter:
    metadata = AdapterMetadata(
        key="official.cwa.rainfall",
        family=SourceFamily.OFFICIAL,
        enabled_by_default=True,
        display_name="Failing rainfall adapter",
    )

    def fetch(self) -> Iterable[RawSourceItem]:
        return ()

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        del raw_item
        return None

    def run(self) -> AdapterRunResult:
        raise RuntimeError("source timeout")


def _runtime_job(*, adapter_key: str | None) -> RuntimeQueueJob:
    return RuntimeQueueJob(
        id="job-1",
        queue_name="runtime-adapters",
        job_key="runtime.adapter.ingest",
        adapter_key=adapter_key,
        payload={"adapter_key": adapter_key} if adapter_key is not None else {},
        attempts=1,
        max_attempts=3,
    )


def _load_cwa_api_payload() -> dict[str, Any]:
    return json.loads((FIXTURES / "cwa_rainfall_api_sample.json").read_text(encoding="utf-8"))


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


class _LeaseHeldQueue:
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
        return False
