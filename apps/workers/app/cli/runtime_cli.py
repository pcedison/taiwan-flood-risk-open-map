"""Managed runtime-adapter ingestion CLI commands and the official demo path."""

from __future__ import annotations

import os
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from types import TracebackType
from typing import Self
from uuid import uuid4

from app.adapters.registry import ADAPTER_REGISTRY, enabled_adapter_keys
from app.cli.persistence import build_demo_persistence_writers
from app.config import WorkerSettings
from app.jobs.frozen_legacy import report_frozen_legacy
from app.jobs.ingestion import record_runtime_selection
from app.jobs.official_demo import build_official_demo_adapters
from app.jobs.queue import PostgresRuntimeQueue, RuntimeQueueUnavailable
from app.jobs.runtime import build_runtime_adapters
from app.jobs.runtime_managed import (
    V1_BASELINE_ADAPTER_KEYS,
    _execute_managed_runtime_ingestion_cycle,
    run_v1_baseline_adapter_cycle,
)
from app.logging import log_event
from app.pipelines.ingestion_runs import PostgresIngestionRunWriter
from app.pipelines.promotion import PromotionResult, promote_accepted_staging
from app.scheduler import _execute_scheduled_ingestion_cycle


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

    def __enter__(self) -> Self:
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
    return report_frozen_legacy()


def _legacy_run_managed_enabled_adapters(
    *,
    settings: WorkerSettings,
    database_url: str | None,
) -> int:
    result = _execute_managed_runtime_ingestion_cycle(
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
    return report_frozen_legacy()


def _legacy_run_managed_enabled_adapters_loop(
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
                result = _execute_managed_runtime_ingestion_cycle(
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


def v1_baseline_eligible_adapter_keys(settings: WorkerSettings) -> tuple[str, ...]:
    """Return the configured adapter keys that the v1 baseline cycle accepts."""

    return tuple(
        key for key in enabled_adapter_keys(settings) if key in V1_BASELINE_ADAPTER_KEYS
    )


def _run_v1_baseline_tick(
    *,
    settings: WorkerSettings,
    database_url: str,
    job_key: str,
) -> bool:
    """Run one isolated v1 cycle per eligible source. Return True on any failure.

    `run_v1_baseline_adapter_cycle` deliberately accepts exactly one adapter and
    requires the scoped settings to name only that adapter, so a source can never
    reach another source's staging, promotion, or catalog decision. This wrapper
    honors that contract by scoping settings per key rather than widening it.
    """

    eligible = v1_baseline_eligible_adapter_keys(settings)
    if not eligible:
        log_event("worker.runtime.v1_baseline.noop", reason="no_eligible_adapter_keys")
        return False

    had_failure = False
    ran_keys: list[str] = []
    for adapter_key in eligible:
        scoped_settings = replace(settings, enabled_adapter_keys=(adapter_key,))
        adapters = build_runtime_adapters(scoped_settings)
        adapter = adapters.get(adapter_key)
        if adapter is None:
            # A gate for this source is off. That is a normal disabled state, not
            # a failure, and it must not stop the remaining sources.
            log_event(
                "worker.runtime.v1_baseline.adapter_gated_off",
                adapter_key=adapter_key,
            )
            continue
        result = run_v1_baseline_adapter_cycle(
            {adapter_key: adapter},
            settings=scoped_settings,
            database_url=database_url,
            promote=True,
            promotion_adapter_keys=(adapter_key,),
            job_key=job_key,
        )
        ran_keys.append(adapter_key)
        had_failure = had_failure or result.failed or result.has_alerts
        log_event(
            "worker.runtime.v1_baseline.source_completed",
            adapter_key=adapter_key,
            status=result.status,
            reason=result.reason,
            promoted=result.promoted,
        )

    # Each scoped cycle records the runtime selection with only its own key, and
    # `write_runtime_selection` sets `runtime_enabled = false` for every other
    # known adapter. Left alone, the last source of the tick would be the only one
    # the public API reports as enabled, and every other live source would show
    # "background worker recently reported this source as disabled". Re-record the
    # real selection for the whole tick so the reported state matches reality.
    if ran_keys:
        record_runtime_selection(
            PostgresIngestionRunWriter(database_url=database_url),
            enabled_adapter_keys=tuple(ran_keys),
            known_adapter_keys=tuple(ADAPTER_REGISTRY),
        )
    return had_failure


def run_v1_baseline_enabled_adapters(
    *,
    settings: WorkerSettings,
    database_url: str | None,
    scheduler: bool,
    once: bool,
    max_ticks: int | None,
) -> int:
    """Run the v1 baseline ingestion cycle once, or on the scheduler loop.

    This is the sanctioned v1 replacement for the frozen legacy adapter runner.
    It reuses the existing scheduler lease and heartbeat so exactly one instance
    ingests at a time.
    """

    resolved_database_url = database_url or settings.database_url
    if not resolved_database_url:
        log_event("worker.runtime.v1_baseline.noop", reason="no_database_url")
        return 0

    if not scheduler:
        return 1 if _run_v1_baseline_tick(
            settings=settings,
            database_url=resolved_database_url,
            job_key="worker.runtime.v1_baseline.run_once",
        ) else 0

    tick_limit = (
        1
        if once
        else max(1, max_ticks)
        if max_ticks is not None
        else settings.scheduler_max_ticks
    )
    if settings.scheduler_lease_ttl_seconds <= 0:
        log_event(
            "worker.runtime.v1_baseline.invalid_lease_ttl",
            reason="scheduler_lease_ttl_must_be_positive",
        )
        return 1

    lease_holder = _process_unique_lease_holder(settings.metrics_instance)
    lease_key = "scheduler.v1-baseline-adapters"
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
                "worker.runtime.v1_baseline.lease_unavailable",
                reason="runtime_queue_unavailable",
            )
            return None

    try:
        while tick_limit is None or tick < tick_limit:
            if not lease_acquired:
                lease_acquired = acquire_or_renew_lease() is True
                if not lease_acquired:
                    log_event(
                        "worker.runtime.v1_baseline.lease_waiting",
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
                    "worker.runtime.v1_baseline.lease_lost",
                    lease_key=lease_key,
                    holder_id=lease_holder,
                )
                continue

            with _SchedulerLeaseHeartbeat(
                renew=acquire_or_renew_lease,
                interval_seconds=heartbeat_interval_seconds,
            ) as heartbeat:
                tick_failed = _run_v1_baseline_tick(
                    settings=settings,
                    database_url=resolved_database_url,
                    job_key="worker.runtime.v1_baseline.scheduler",
                )
            if heartbeat.lost:
                lease_acquired = False
                log_event(
                    "worker.runtime.v1_baseline.lease_lost",
                    lease_key=lease_key,
                    holder_id=lease_holder,
                )
            had_failure = had_failure or tick_failed
            log_event("worker.runtime.v1_baseline.tick_completed", failed=tick_failed)
            tick += 1
            if tick_limit is not None and tick >= tick_limit:
                break

            if not acquire_or_renew_lease():
                lease_acquired = False
                log_event(
                    "worker.runtime.v1_baseline.lease_lost",
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
                    "worker.runtime.v1_baseline.lease_release_failed",
                    reason="runtime_queue_unavailable",
                )

    return 1 if had_failure else 0


def run_official_demo(
    *,
    settings: WorkerSettings,
    persist: bool,
    database_url: str | None,
) -> int:
    if persist:
        return report_frozen_legacy()
    return _legacy_run_official_demo(
        settings=settings,
        persist=persist,
        database_url=database_url,
    )


def _legacy_run_official_demo(
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
    result = _execute_scheduled_ingestion_cycle(
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
