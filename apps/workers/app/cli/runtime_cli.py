"""Managed runtime-adapter ingestion CLI commands and the official demo path."""

from __future__ import annotations

from collections.abc import Callable
import os
import socket
import threading
import time
from types import TracebackType
from uuid import uuid4

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


class _SchedulerLeaseHeartbeat:
    """Renew a scheduler lease while one ingestion cycle is still running."""

    def __init__(
        self,
        *,
        renew: Callable[[], bool | None],
        interval_seconds: float,
    ) -> None:
        self._renew = renew
        self._interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._lost = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="scheduler-lease-heartbeat",
            daemon=True,
        )

    @property
    def lost(self) -> bool:
        return self._lost.is_set()

    def __enter__(self) -> _SchedulerLeaseHeartbeat:
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self._stop.set()
        # Do not release the lease until any in-flight renewal has completed.
        self._thread.join()

    def _run(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            renewed = self._renew()
            if renewed is False:
                self._lost.set()
                return


def _process_unique_lease_holder(base: str) -> str:
    return f"{base}:{socket.gethostname()}:{os.getpid()}:{uuid4().hex}"


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
    if settings.scheduler_lease_ttl_seconds <= 0:
        log_event(
            "worker.runtime.managed_scheduler.invalid_lease_ttl",
            reason="scheduler_lease_ttl_must_be_positive",
        )
        return 1

    lease_holder = _process_unique_lease_holder(settings.metrics_instance)
    lease_key = "scheduler.enabled-adapters"
    lease_retry_seconds = max(1, min(30, settings.scheduler_interval_seconds))
    heartbeat_interval_seconds = max(
        0.25,
        min(30.0, settings.scheduler_lease_ttl_seconds / 3),
    )
    queue = PostgresRuntimeQueue(database_url=resolved_database_url)
    had_failure = False
    tick = 0
    lease_acquired = False

    def acquire_or_renew_lease() -> bool | None:
        try:
            return queue.acquire_scheduler_lease(
                lease_key=lease_key,
                holder_id=lease_holder,
                ttl_seconds=settings.scheduler_lease_ttl_seconds,
            )
        except RuntimeQueueUnavailable:
            log_event(
                "worker.runtime.managed_scheduler.lease_unavailable",
                reason="runtime_queue_unavailable",
            )
            return None

    try:
        while tick_limit is None or tick < tick_limit:
            if not lease_acquired:
                lease_acquired = acquire_or_renew_lease() is True
                if not lease_acquired:
                    log_event(
                        "worker.runtime.managed_scheduler.lease_waiting",
                        lease_key=lease_key,
                        holder_id=lease_holder,
                        retry_seconds=lease_retry_seconds,
                    )
                    if once:
                        return 0
                    time.sleep(lease_retry_seconds)
                    continue
            elif not acquire_or_renew_lease():
                lease_acquired = False
                log_event(
                    "worker.runtime.managed_scheduler.lease_lost",
                    lease_key=lease_key,
                    holder_id=lease_holder,
                )
                continue

            with _SchedulerLeaseHeartbeat(
                renew=acquire_or_renew_lease,
                interval_seconds=heartbeat_interval_seconds,
            ) as heartbeat:
                result = run_managed_runtime_ingestion_cycle(
                    settings=settings,
                    database_url=resolved_database_url,
                    adapter_builder=build_runtime_adapters,
                    promote=True,
                    job_key="worker.runtime.managed_scheduler",
                )
            if heartbeat.lost:
                lease_acquired = False
                log_event(
                    "worker.runtime.managed_scheduler.lease_lost",
                    lease_key=lease_key,
                    holder_id=lease_holder,
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

            if not acquire_or_renew_lease():
                lease_acquired = False
                log_event(
                    "worker.runtime.managed_scheduler.lease_lost",
                    lease_key=lease_key,
                    holder_id=lease_holder,
                )
                continue
            time.sleep(settings.scheduler_interval_seconds)
    finally:
        if lease_acquired:
            try:
                queue.release_scheduler_lease(
                    lease_key=lease_key,
                    holder_id=lease_holder,
                )
            except RuntimeQueueUnavailable:
                log_event(
                    "worker.runtime.managed_scheduler.lease_release_failed",
                    reason="runtime_queue_unavailable",
                )

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
