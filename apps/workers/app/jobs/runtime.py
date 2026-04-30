from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from app.adapters.contracts import DataSourceAdapter
from app.adapters.registry import enabled_adapter_keys
from app.config import WorkerSettings
from app.jobs.official_demo import build_official_demo_adapters
from app.jobs.queue import (
    NullRuntimeQueue,
    PostgresRuntimeQueue,
    RuntimeQueueJob,
    RuntimeQueueUnavailable,
)
from app.logging import log_event


def build_runtime_adapters(
    settings: WorkerSettings,
    *,
    fetched_at: datetime | None = None,
) -> Mapping[str, DataSourceAdapter]:
    if not settings.runtime_fixtures_enabled:
        log_event(
            "runtime.adapters.noop",
            reason="fixture_runtime_disabled",
            enabled_adapter_keys=settings.enabled_adapter_keys,
        )
        return {}

    adapters = build_official_demo_adapters(fetched_at=fetched_at or datetime.now(UTC))
    log_event(
        "runtime.adapters.fixture_mode.enabled",
        available_adapter_keys=tuple(adapters),
    )
    return adapters


def enqueue_enabled_runtime_adapter_jobs(
    settings: WorkerSettings,
    *,
    queue: PostgresRuntimeQueue | NullRuntimeQueue | None = None,
    job_key: str = "runtime.adapter.ingest",
) -> tuple[str, ...]:
    adapter_keys = enabled_adapter_keys(settings)
    if not adapter_keys:
        log_event("runtime.queue.enqueue.noop", reason="no_enabled_adapters")
        return ()

    runtime_queue = queue or (
        PostgresRuntimeQueue(database_url=settings.database_url)
        if settings.database_url
        else NullRuntimeQueue()
    )
    job_ids: list[str] = []
    try:
        for adapter_key in adapter_keys:
            job_id = runtime_queue.enqueue_adapter_job(
                adapter_key=adapter_key,
                job_key=job_key,
                payload={"adapter_key": adapter_key},
            )
            if job_id is not None:
                job_ids.append(job_id)
    except RuntimeQueueUnavailable as exc:
        log_event("runtime.queue.enqueue.unavailable", error=str(exc))
        return ()

    log_event(
        "runtime.queue.enqueue.completed",
        adapter_count=len(adapter_keys),
        durable_job_count=len(job_ids),
    )
    return tuple(job_ids)


def dequeue_runtime_adapter_job(
    settings: WorkerSettings,
    *,
    queue: PostgresRuntimeQueue | NullRuntimeQueue | None = None,
    queue_name: str = "runtime-adapters",
    worker_id: str | None = None,
) -> RuntimeQueueJob | None:
    runtime_queue = queue or (
        PostgresRuntimeQueue(database_url=settings.database_url)
        if settings.database_url
        else NullRuntimeQueue()
    )
    try:
        return runtime_queue.dequeue_adapter_job(
            queue_name=queue_name,
            worker_id=worker_id or settings.metrics_instance,
            lease_seconds=settings.runtime_job_lease_seconds,
        )
    except RuntimeQueueUnavailable as exc:
        log_event("runtime.queue.dequeue.unavailable", error=str(exc))
        return None


def mark_runtime_adapter_job_succeeded(
    settings: WorkerSettings,
    *,
    job_id: str,
    queue: PostgresRuntimeQueue | NullRuntimeQueue | None = None,
    worker_id: str | None = None,
) -> bool:
    runtime_queue = queue or (
        PostgresRuntimeQueue(database_url=settings.database_url)
        if settings.database_url
        else NullRuntimeQueue()
    )
    try:
        updated = runtime_queue.mark_job_succeeded(
            job_id=job_id,
            worker_id=worker_id or settings.metrics_instance,
        )
    except RuntimeQueueUnavailable as exc:
        log_event("runtime.queue.complete.unavailable", error=str(exc), status="succeeded")
        return False

    log_event("runtime.queue.complete", job_id=job_id, status="succeeded", updated=updated)
    return updated


def mark_runtime_adapter_job_failed(
    settings: WorkerSettings,
    *,
    job_id: str,
    error: str,
    retry_delay_seconds: int = 60,
    queue: PostgresRuntimeQueue | NullRuntimeQueue | None = None,
    worker_id: str | None = None,
) -> bool:
    runtime_queue = queue or (
        PostgresRuntimeQueue(database_url=settings.database_url)
        if settings.database_url
        else NullRuntimeQueue()
    )
    try:
        updated = runtime_queue.mark_job_failed(
            job_id=job_id,
            worker_id=worker_id or settings.metrics_instance,
            error=error,
            retry_delay_seconds=retry_delay_seconds,
        )
    except RuntimeQueueUnavailable as exc:
        log_event("runtime.queue.complete.unavailable", error=str(exc), status="failed")
        return False

    log_event("runtime.queue.complete", job_id=job_id, status="failed", updated=updated)
    return updated
