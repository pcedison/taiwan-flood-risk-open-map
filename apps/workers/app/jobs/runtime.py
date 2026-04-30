from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.adapters.contracts import DataSourceAdapter
from app.adapters.registry import enabled_adapter_keys
from app.config import WorkerSettings, load_worker_settings
from app.jobs.freshness import FreshnessCheck, check_batch_freshness
from app.jobs.ingestion import AdapterBatchRunSummary, run_adapter_batch
from app.jobs.official_demo import build_official_demo_adapters
from app.jobs.queue import (
    NullRuntimeQueue,
    PostgresRuntimeQueue,
    RuntimeQueueJob,
    RuntimeQueueUnavailable,
)
from app.logging import log_event


RuntimeQueueWorkerStatus = Literal["succeeded", "failed", "skipped"]
RuntimeQueueProducerStatus = Literal["succeeded", "skipped", "deduped"]
RuntimeQueue = PostgresRuntimeQueue | NullRuntimeQueue


@dataclass(frozen=True)
class RuntimeQueueWorkerResult:
    status: RuntimeQueueWorkerStatus
    job_id: str | None = None
    adapter_key: str | None = None
    reason: str | None = None
    summary: AdapterBatchRunSummary | None = None
    freshness_checks: tuple[FreshnessCheck, ...] = ()


@dataclass(frozen=True)
class RuntimeQueueProducerResult:
    status: RuntimeQueueProducerStatus
    adapter_keys: tuple[str, ...] = ()
    job_ids: tuple[str, ...] = ()
    enqueued_job_ids: tuple[str, ...] = ()
    deduped_job_ids: tuple[str, ...] = ()
    dedupe_keys: tuple[str, ...] = ()
    reason: str | None = None

    @property
    def durable_job_count(self) -> int:
        return len(self.job_ids)

    @property
    def enqueued_job_count(self) -> int:
        return len(self.enqueued_job_ids)

    @property
    def deduped_job_count(self) -> int:
        return len(self.deduped_job_ids)


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
    queue: RuntimeQueue | None = None,
    job_key: str = "runtime.adapter.ingest",
) -> tuple[str, ...]:
    return produce_enabled_runtime_adapter_jobs(
        settings,
        queue=queue,
        job_key=job_key,
    ).job_ids


def produce_enabled_runtime_adapter_jobs(
    settings: WorkerSettings,
    *,
    queue: RuntimeQueue | None = None,
    job_key: str = "runtime.adapter.ingest",
    queue_name: str = "runtime-adapters",
) -> RuntimeQueueProducerResult:
    adapter_keys = enabled_adapter_keys(settings)
    if not adapter_keys:
        log_event("runtime.queue.enqueue.noop", reason="no_enabled_adapters")
        return RuntimeQueueProducerResult(status="skipped", reason="no_enabled_adapters")

    if queue is None and not settings.database_url:
        log_event(
            "runtime.queue.enqueue.noop",
            reason="no_database_url",
            adapter_count=len(adapter_keys),
        )
        return RuntimeQueueProducerResult(
            status="skipped",
            adapter_keys=adapter_keys,
            reason="no_database_url",
        )

    runtime_queue = queue or (
        PostgresRuntimeQueue(database_url=settings.database_url)
        if settings.database_url
        else NullRuntimeQueue()
    )
    job_ids: list[str] = []
    enqueued_job_ids: list[str] = []
    deduped_job_ids: list[str] = []
    dedupe_keys: list[str] = []
    try:
        for adapter_key in adapter_keys:
            dedupe_key = _runtime_adapter_dedupe_key(
                queue_name=queue_name,
                job_key=job_key,
                adapter_key=adapter_key,
            )
            enqueue_result = runtime_queue.enqueue_adapter_job(
                adapter_key=adapter_key,
                job_key=job_key,
                queue_name=queue_name,
                payload={"adapter_key": adapter_key},
                dedupe_key=dedupe_key,
            )
            dedupe_keys.append(dedupe_key)
            if enqueue_result.job_id is not None:
                job_ids.append(enqueue_result.job_id)
                if enqueue_result.status == "enqueued":
                    enqueued_job_ids.append(enqueue_result.job_id)
                elif enqueue_result.status == "deduped":
                    deduped_job_ids.append(enqueue_result.job_id)
    except RuntimeQueueUnavailable as exc:
        log_event("runtime.queue.enqueue.unavailable", error=str(exc))
        return RuntimeQueueProducerResult(
            status="skipped",
            adapter_keys=adapter_keys,
            job_ids=tuple(job_ids),
            enqueued_job_ids=tuple(enqueued_job_ids),
            deduped_job_ids=tuple(deduped_job_ids),
            dedupe_keys=tuple(dedupe_keys),
            reason="queue_unavailable",
        )

    log_event(
        "runtime.queue.enqueue.completed",
        adapter_count=len(adapter_keys),
        durable_job_count=len(job_ids),
        enqueued_job_count=len(enqueued_job_ids),
        deduped_job_count=len(deduped_job_ids),
    )
    if not job_ids:
        return RuntimeQueueProducerResult(
            status="skipped",
            adapter_keys=adapter_keys,
            dedupe_keys=tuple(dedupe_keys),
            reason="no_durable_jobs",
        )
    if not enqueued_job_ids and deduped_job_ids:
        return RuntimeQueueProducerResult(
            status="deduped",
            adapter_keys=adapter_keys,
            job_ids=tuple(job_ids),
            enqueued_job_ids=tuple(enqueued_job_ids),
            deduped_job_ids=tuple(deduped_job_ids),
            dedupe_keys=tuple(dedupe_keys),
            reason="active_jobs_already_exist",
        )
    return RuntimeQueueProducerResult(
        status="succeeded",
        adapter_keys=adapter_keys,
        job_ids=tuple(job_ids),
        enqueued_job_ids=tuple(enqueued_job_ids),
        deduped_job_ids=tuple(deduped_job_ids),
        dedupe_keys=tuple(dedupe_keys),
    )


def dequeue_runtime_adapter_job(
    settings: WorkerSettings,
    *,
    queue: RuntimeQueue | None = None,
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
    queue: RuntimeQueue | None = None,
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
    queue: RuntimeQueue | None = None,
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


def work_runtime_queue_once(
    *,
    settings: WorkerSettings | None = None,
    queue: RuntimeQueue | None = None,
    adapter_by_key: Mapping[str, DataSourceAdapter] | None = None,
    queue_name: str = "runtime-adapters",
    worker_id: str | None = None,
    retry_delay_seconds: int = 60,
) -> RuntimeQueueWorkerResult:
    resolved_settings = settings or load_worker_settings()
    resolved_worker_id = worker_id or resolved_settings.metrics_instance
    if queue is None and not resolved_settings.database_url:
        log_event(
            "runtime.queue.worker.noop",
            reason="no_database_url",
            queue_name=queue_name,
            worker_id=resolved_worker_id,
        )
        return RuntimeQueueWorkerResult(status="skipped", reason="no_database_url")

    if queue is not None:
        runtime_queue = queue
    else:
        assert resolved_settings.database_url is not None
        runtime_queue = PostgresRuntimeQueue(database_url=resolved_settings.database_url)
    try:
        job = runtime_queue.dequeue_adapter_job(
            queue_name=queue_name,
            worker_id=resolved_worker_id,
            lease_seconds=resolved_settings.runtime_job_lease_seconds,
        )
    except RuntimeQueueUnavailable as exc:
        log_event(
            "runtime.queue.worker.noop",
            reason="queue_unavailable",
            queue_name=queue_name,
            worker_id=resolved_worker_id,
            error=str(exc),
        )
        return RuntimeQueueWorkerResult(status="skipped", reason="queue_unavailable")

    if job is None:
        log_event(
            "runtime.queue.worker.noop",
            reason="no_job",
            queue_name=queue_name,
            worker_id=resolved_worker_id,
        )
        return RuntimeQueueWorkerResult(status="skipped", reason="no_job")

    adapter_key = _job_adapter_key(job)
    if adapter_key is None:
        return _fail_runtime_queue_job(
            resolved_settings,
            queue=runtime_queue,
            job=job,
            worker_id=resolved_worker_id,
            adapter_key=None,
            error="runtime queue job is missing adapter_key",
            retry_delay_seconds=retry_delay_seconds,
        )

    try:
        adapters = (
            adapter_by_key
            if adapter_by_key is not None
            else build_runtime_adapters(resolved_settings)
        )
        adapter = adapters.get(adapter_key)
        if adapter is None:
            return _fail_runtime_queue_job(
                resolved_settings,
                queue=runtime_queue,
                job=job,
                worker_id=resolved_worker_id,
                adapter_key=adapter_key,
                error=f"unknown runtime adapter_key: {adapter_key}",
                retry_delay_seconds=retry_delay_seconds,
            )

        summary = run_adapter_batch(
            adapter,
            job_key=job.job_key,
            parameters={
                "runtime_queue_job_id": job.id,
                "runtime_queue_name": job.queue_name,
                "payload": dict(job.payload),
            },
        )
        freshness_checks = check_batch_freshness(
            (summary,),
            max_age_seconds=resolved_settings.freshness_max_age_seconds,
        )
        failure_reason = _runtime_cycle_failure_reason(summary, freshness_checks)
        if failure_reason is not None:
            return _fail_runtime_queue_job(
                resolved_settings,
                queue=runtime_queue,
                job=job,
                worker_id=resolved_worker_id,
                adapter_key=adapter_key,
                error=failure_reason,
                retry_delay_seconds=retry_delay_seconds,
                summary=summary,
                freshness_checks=freshness_checks,
            )
    except Exception as exc:
        return _fail_runtime_queue_job(
            resolved_settings,
            queue=runtime_queue,
            job=job,
            worker_id=resolved_worker_id,
            adapter_key=adapter_key,
            error=f"{exc.__class__.__name__}: {exc}",
            retry_delay_seconds=retry_delay_seconds,
        )

    updated = mark_runtime_adapter_job_succeeded(
        resolved_settings,
        job_id=job.id,
        queue=runtime_queue,
        worker_id=resolved_worker_id,
    )
    if not updated:
        log_event(
            "runtime.queue.worker.completion_not_updated",
            job_id=job.id,
            adapter_key=adapter_key,
            status="failed",
            updated=updated,
        )
        return RuntimeQueueWorkerResult(
            status="failed",
            job_id=job.id,
            adapter_key=adapter_key,
            reason="queue_completion_not_updated",
            summary=summary,
            freshness_checks=freshness_checks,
        )
    log_event(
        "runtime.queue.worker.completed",
        job_id=job.id,
        adapter_key=adapter_key,
        status="succeeded",
        updated=updated,
    )
    return RuntimeQueueWorkerResult(
        status="succeeded",
        job_id=job.id,
        adapter_key=adapter_key,
        summary=summary,
        freshness_checks=freshness_checks,
    )


def _job_adapter_key(job: RuntimeQueueJob) -> str | None:
    if job.adapter_key:
        return job.adapter_key
    payload_adapter_key = job.payload.get("adapter_key")
    if isinstance(payload_adapter_key, str) and payload_adapter_key.strip():
        return payload_adapter_key.strip()
    return None


def _runtime_adapter_dedupe_key(
    *,
    queue_name: str,
    job_key: str,
    adapter_key: str,
) -> str:
    return f"{queue_name}:{job_key}:{adapter_key}"


def _runtime_cycle_failure_reason(
    summary: AdapterBatchRunSummary,
    freshness_checks: tuple[FreshnessCheck, ...],
) -> str | None:
    if summary.status == "failed":
        return summary.error_message or summary.error_code or "adapter batch failed"

    alert = next((check for check in freshness_checks if check.is_alert()), None)
    if alert is not None:
        return alert.reason or f"freshness check {alert.status}"
    return None


def _fail_runtime_queue_job(
    settings: WorkerSettings,
    *,
    queue: RuntimeQueue,
    job: RuntimeQueueJob,
    worker_id: str,
    adapter_key: str | None,
    error: str,
    retry_delay_seconds: int,
    summary: AdapterBatchRunSummary | None = None,
    freshness_checks: tuple[FreshnessCheck, ...] = (),
) -> RuntimeQueueWorkerResult:
    updated = mark_runtime_adapter_job_failed(
        settings,
        job_id=job.id,
        error=error,
        retry_delay_seconds=retry_delay_seconds,
        queue=queue,
        worker_id=worker_id,
    )
    log_event(
        "runtime.queue.worker.completed",
        job_id=job.id,
        adapter_key=adapter_key,
        status="failed",
        error=error[:1000],
        updated=updated,
    )
    return RuntimeQueueWorkerResult(
        status="failed",
        job_id=job.id,
        adapter_key=adapter_key,
        reason=error,
        summary=summary,
        freshness_checks=freshness_checks,
    )
