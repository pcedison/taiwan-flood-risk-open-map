"""Durable runtime queue CLI commands: consume, enqueue, inspect, requeue."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime

from app.cli.persistence import build_runtime_persistence_bundle
from app.config import WorkerSettings
from app.jobs.queue import (
    PostgresRuntimeQueue,
    RuntimeQueueDeadLetterJob,
    RuntimeQueueDeadLetterSummary,
    RuntimeQueueMetricsSnapshot,
    RuntimeQueueUnavailable,
)
from app.jobs.replay_audit import PostgresRuntimeQueueReplayAudit
from app.jobs.runtime import work_runtime_queue_once
from app.logging import log_event
from app.metrics import render_runtime_queue_metrics, write_prometheus_textfile
from app.scheduler import enqueue_enabled_adapters_loop, enqueue_enabled_adapters_once


def work_runtime_queue(
    *,
    settings: WorkerSettings,
    once: bool,
    max_ticks: int | None,
    persist: bool,
    database_url: str | None,
) -> int:
    tick_limit = 1 if once else max(1, max_ticks) if max_ticks is not None else None
    persistence = (
        build_runtime_persistence_bundle(settings, database_url=database_url)
        if persist
        else None
    )
    had_failure = False
    tick = 0
    while tick_limit is None or tick < tick_limit:
        result = work_runtime_queue_once(
            settings=settings,
            writer=persistence.staging_writer if persistence else None,
            run_writer=persistence.run_writer if persistence else None,
            promotion_writer=persistence.promotion_writer if persistence else None,
            promote=persistence is not None,
        )
        had_failure = had_failure or result.status == "failed"
        tick += 1
        if tick_limit is not None and tick >= tick_limit:
            break
        time.sleep(settings.worker_idle_seconds)
    return 1 if had_failure else 0


def enqueue_runtime_jobs(
    *,
    settings: WorkerSettings,
    scheduler: bool,
    once: bool,
    max_ticks: int | None,
) -> int:
    if not scheduler:
        enqueue_enabled_adapters_once(settings=settings)
        return 0

    tick_limit = 1 if once else max(1, max_ticks) if max_ticks is not None else None
    enqueue_enabled_adapters_loop(settings=settings, max_ticks=tick_limit)
    return 0


def list_runtime_dead_letter_jobs(
    *,
    settings: WorkerSettings,
    database_url: str | None,
    queue_name: str | None,
    limit: int,
) -> int:
    resolved_database_url = database_url or settings.database_url
    if not resolved_database_url:
        return 0

    try:
        jobs = PostgresRuntimeQueue(database_url=resolved_database_url).list_dead_letter_jobs(
            queue_name=queue_name,
            limit=limit,
        )
    except RuntimeQueueUnavailable as exc:
        log_event("runtime.queue.dead_letter.list.failed", error=str(exc))
        return 1

    for job in jobs:
        print(_runtime_dead_letter_job_json(job))
    return 0


def summarize_runtime_dead_letter_jobs(
    *,
    settings: WorkerSettings,
    database_url: str | None,
    queue_name: str | None,
) -> int:
    resolved_database_url = database_url or settings.database_url
    if not resolved_database_url:
        print(
            _runtime_dead_letter_summary_json(
                RuntimeQueueDeadLetterSummary(
                    queue_name=queue_name,
                    failed_terminal_count=0,
                    oldest_final_failed_at=None,
                    newest_final_failed_at=None,
                    max_attempts_observed=None,
                    max_configured_attempts=None,
                ),
                available=False,
                reason="no_database_url",
            )
        )
        return 0

    try:
        summary = PostgresRuntimeQueue(
            database_url=resolved_database_url
        ).summarize_dead_letter_jobs(queue_name=queue_name)
    except RuntimeQueueUnavailable as exc:
        print(
            _runtime_dead_letter_summary_json(
                RuntimeQueueDeadLetterSummary(
                    queue_name=queue_name,
                    failed_terminal_count=0,
                    oldest_final_failed_at=None,
                    newest_final_failed_at=None,
                    max_attempts_observed=None,
                    max_configured_attempts=None,
                ),
                available=False,
                reason="queue_unavailable",
                error=str(exc),
            )
        )
        return 1

    print(_runtime_dead_letter_summary_json(summary, available=True))
    return 0


def export_runtime_queue_metrics(
    *,
    settings: WorkerSettings,
    database_url: str | None,
    queue_name: str | None,
    output_format: str,
    metrics_path: str | None,
) -> int:
    collected_at = datetime.now(UTC)
    resolved_database_url = database_url or settings.database_url
    available = True
    reason: str | None = None
    error: str | None = None

    if not resolved_database_url:
        snapshots = _default_queue_metrics_snapshots(queue_name)
        available = False
        reason = "no_database_url"
    else:
        try:
            snapshots = PostgresRuntimeQueue(
                database_url=resolved_database_url
            ).collect_metrics(queue_name=queue_name)
        except RuntimeQueueUnavailable as exc:
            snapshots = _default_queue_metrics_snapshots(queue_name)
            available = False
            reason = "queue_unavailable"
            error = str(exc)

    if output_format == "json":
        print(
            _runtime_queue_metrics_json(
                snapshots,
                collected_at=collected_at,
                available=available,
                reason=reason,
                error=error,
            )
        )
        return 0 if available or reason == "no_database_url" else 1

    content = render_runtime_queue_metrics(
        snapshots=snapshots,
        collected_at=collected_at,
        available=available,
        reason=reason,
    )
    if metrics_path:
        write_prometheus_textfile(metrics_path, content)
    else:
        print(content, end="")
    return 0 if available or reason == "no_database_url" else 1


def _default_queue_metrics_snapshots(
    queue_name: str | None,
) -> tuple[RuntimeQueueMetricsSnapshot, ...]:
    return (
        RuntimeQueueMetricsSnapshot(
            queue_name=queue_name or "runtime-adapters",
            queued_count=0,
            running_count=0,
            final_failed_count=0,
            expired_lease_count=0,
            oldest_queued_at=None,
            oldest_final_failed_at=None,
        ),
    )


def requeue_runtime_job(
    *,
    settings: WorkerSettings,
    database_url: str | None,
    job_id: str,
    reset_attempts: bool,
    requested_by: str | None,
    reason: str | None,
) -> int:
    resolved_database_url = database_url or settings.database_url
    if not resolved_database_url:
        log_event(
            "runtime.queue.requeue.failed",
            reason="no_database_url",
            job_id=job_id,
        )
        return 1
    resolved_requested_by = (requested_by or "").strip()
    resolved_reason = (reason or "").strip()
    if not resolved_requested_by or not resolved_reason:
        log_event(
            "runtime.queue.requeue.failed",
            reason="missing_audit_context",
            job_id=job_id,
            requested_by_provided=bool(resolved_requested_by),
            requeue_reason_provided=bool(resolved_reason),
        )
        return 1

    try:
        result = PostgresRuntimeQueueReplayAudit(
            database_url=resolved_database_url
        ).requeue_failed_job_with_audit(
            job_id=job_id,
            requested_by=resolved_requested_by,
            reason=resolved_reason,
            reset_attempts=reset_attempts,
        )
    except RuntimeQueueUnavailable as exc:
        log_event("runtime.queue.requeue.failed", job_id=job_id, error=str(exc))
        return 1

    print(
        json.dumps(
            {
                "job_id": result.job_id,
                "outcome_audit_id": result.outcome_audit_id,
                "requested_audit_id": result.requested_audit_id,
                "requeued": result.requeued,
                "reset_attempts": result.reset_attempts,
                "attempts": result.attempts_after,
                "attempts_before": result.attempts_before,
                "reason": result.reason,
            },
            sort_keys=True,
        )
    )
    if not result.requeued:
        return 1

    return 0


def _runtime_dead_letter_job_json(job: RuntimeQueueDeadLetterJob) -> str:
    return json.dumps(
        {
            "id": job.id,
            "queue_name": job.queue_name,
            "job_key": job.job_key,
            "adapter_key": job.adapter_key,
            "payload": dict(job.payload),
            "attempts": job.attempts,
            "max_attempts": job.max_attempts,
            "last_error": job.last_error,
            "final_failed_at": (
                job.final_failed_at.isoformat() if job.final_failed_at is not None else None
            ),
            "dedupe_key": job.dedupe_key,
        },
        sort_keys=True,
    )


def _runtime_dead_letter_summary_json(
    summary: RuntimeQueueDeadLetterSummary,
    *,
    available: bool,
    reason: str | None = None,
    error: str | None = None,
) -> str:
    return json.dumps(
        {
            "available": available,
            "queue_name": summary.queue_name,
            "failed_terminal_count": summary.failed_terminal_count,
            "oldest_final_failed_at": (
                summary.oldest_final_failed_at.isoformat()
                if summary.oldest_final_failed_at is not None
                else None
            ),
            "newest_final_failed_at": (
                summary.newest_final_failed_at.isoformat()
                if summary.newest_final_failed_at is not None
                else None
            ),
            "max_attempts_observed": summary.max_attempts_observed,
            "max_configured_attempts": summary.max_configured_attempts,
            "reason": reason,
            "error": error,
        },
        sort_keys=True,
    )


def _runtime_queue_metrics_json(
    snapshots: tuple[RuntimeQueueMetricsSnapshot, ...],
    *,
    collected_at: datetime,
    available: bool,
    reason: str | None = None,
    error: str | None = None,
) -> str:
    return json.dumps(
        {
            "available": available,
            "collected_at": collected_at.isoformat(),
            "reason": reason,
            "error": error,
            "queues": [
                {
                    "queue_name": snapshot.queue_name,
                    "queued_count": snapshot.queued_count,
                    "running_count": snapshot.running_count,
                    "final_failed_count": snapshot.final_failed_count,
                    "expired_lease_count": snapshot.expired_lease_count,
                    "oldest_queued_at": (
                        snapshot.oldest_queued_at.isoformat()
                        if snapshot.oldest_queued_at is not None
                        else None
                    ),
                    "oldest_final_failed_at": (
                        snapshot.oldest_final_failed_at.isoformat()
                        if snapshot.oldest_final_failed_at is not None
                        else None
                    ),
                }
                for snapshot in snapshots
            ],
        },
        sort_keys=True,
    )
