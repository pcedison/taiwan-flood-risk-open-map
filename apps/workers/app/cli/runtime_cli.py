"""Managed runtime-adapter ingestion CLI commands and the official demo path."""

from __future__ import annotations

import time

from app.adapters.registry import ADAPTER_REGISTRY
from app.cli.persistence import build_demo_persistence_writers
from app.config import WorkerSettings
from app.jobs.official_demo import build_official_demo_adapters
from app.jobs.queue import PostgresRuntimeQueue, RuntimeQueueUnavailable
from app.jobs.runtime import build_runtime_adapters
from app.jobs.runtime_managed import run_managed_runtime_ingestion_cycle
from app.logging import log_event
from app.pipelines.ingestion_runs import PostgresIngestionRunWriter
from app.pipelines.promotion import PromotionResult, promote_accepted_staging
from app.scheduler import run_scheduled_ingestion_cycle


def record_runtime_sources_disabled(
    *,
    settings: WorkerSettings,
    database_url: str | None,
) -> int:
    resolved_database_url = database_url or settings.database_url
    if not resolved_database_url:
        log_event("worker.runtime.selection.disabled.failed", reason="no_database_url")
        return 1
    PostgresIngestionRunWriter(database_url=resolved_database_url).write_runtime_selection(
        enabled_adapter_keys=(),
        known_adapter_keys=tuple(ADAPTER_REGISTRY),
    )
    log_event(
        "worker.runtime.selection.disabled.recorded",
        source_count=len(ADAPTER_REGISTRY),
    )
    return 0


def run_managed_enabled_adapters(
    *,
    settings: WorkerSettings,
    database_url: str | None,
) -> int:
    result = run_managed_runtime_ingestion_cycle(
        settings=settings,
        database_url=database_url,
        adapter_builder=build_runtime_adapters,
        promote=True,
        job_key="worker.runtime.managed_run_once",
    )
    log_event(
        "worker.runtime.managed_run_once.completed",
        status=result.status,
        reason=result.reason,
        promoted=result.promoted,
        evidence_ids=result.evidence_ids,
    )
    return 1 if result.failed or result.has_alerts else 0


def run_managed_enabled_adapters_loop(
    *,
    settings: WorkerSettings,
    database_url: str | None,
    once: bool,
    max_ticks: int | None,
) -> int:
    resolved_database_url = database_url or settings.database_url
    if not resolved_database_url:
        log_event("worker.runtime.managed_scheduler.noop", reason="no_database_url")
        return 0

    tick_limit = (
        1
        if once
        else max(1, max_ticks)
        if max_ticks is not None
        else settings.scheduler_max_ticks
    )
    lease_holder = settings.metrics_instance
    lease_key = "scheduler.enabled-adapters"
    queue = PostgresRuntimeQueue(database_url=resolved_database_url)
    try:
        lease_acquired = queue.acquire_scheduler_lease(
            lease_key=lease_key,
            holder_id=lease_holder,
            ttl_seconds=settings.scheduler_lease_ttl_seconds,
        )
    except RuntimeQueueUnavailable as exc:
        log_event("worker.runtime.managed_scheduler.lease_unavailable", error=str(exc))
        lease_acquired = True

    if not lease_acquired:
        log_event(
            "worker.runtime.managed_scheduler.lease_skipped",
            lease_key=lease_key,
            holder_id=lease_holder,
        )
        return 0

    had_failure = False
    tick = 0
    try:
        while tick_limit is None or tick < tick_limit:
            result = run_managed_runtime_ingestion_cycle(
                settings=settings,
                database_url=resolved_database_url,
                adapter_builder=build_runtime_adapters,
                promote=True,
                job_key="worker.runtime.managed_scheduler",
            )
            had_failure = had_failure or result.failed or result.has_alerts
            log_event(
                "worker.runtime.managed_scheduler.tick_completed",
                status=result.status,
                reason=result.reason,
                promoted=result.promoted,
                evidence_ids=result.evidence_ids,
            )
            tick += 1
            if tick_limit is not None and tick >= tick_limit:
                break
            time.sleep(settings.scheduler_interval_seconds)
    finally:
        try:
            queue.release_scheduler_lease(
                lease_key=lease_key,
                holder_id=lease_holder,
            )
        except RuntimeQueueUnavailable as exc:
            log_event("worker.runtime.managed_scheduler.lease_release_failed", error=str(exc))

    return 1 if had_failure else 0


def run_official_demo(
    *,
    settings: WorkerSettings,
    persist: bool,
    database_url: str | None,
) -> int:
    adapters = build_official_demo_adapters()
    persistence = (
        build_demo_persistence_writers(settings, database_url=database_url)
        if persist
        else None
    )
    result = run_scheduled_ingestion_cycle(
        adapters,
        settings=settings,
        job_key="worker.official_demo",
        writer=persistence.staging_writer if persistence else None,
        run_writer=persistence.run_writer if persistence else None,
    )
    promotion = (
        promote_accepted_staging(
            persistence.promotion_writer,
            adapter_keys=tuple(adapters),
        )
        if persistence is not None
        else PromotionResult(promoted=0, evidence_ids=())
    )
    log_event(
        "worker.official_demo.completed",
        persisted=persist,
        promoted=promotion.promoted,
        evidence_ids=promotion.evidence_ids,
    )
    return 1 if result.has_alerts else 0
