from __future__ import annotations

import argparse
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from app.adapters.contracts import DataSourceAdapter
from app.adapters.registry import enabled_adapter_keys
from app.config import WorkerSettings, load_worker_settings
from app.jobs.freshness import FreshnessCheck, check_batch_freshness
from app.jobs.ingestion import (
    AdapterBatchRunSummary,
    IngestionRunSummaryWriter,
    run_enabled_adapter_batches,
)
from app.jobs.official_demo import build_official_demo_adapters
from app.jobs.queue import PostgresRuntimeQueue, RuntimeQueueUnavailable
from app.jobs.runtime import build_runtime_adapters
from app.jobs.sample import run_sample_job
from app.logging import log_event
from app.metrics import (
    RunStatus,
    render_scheduler_heartbeat_metrics,
    render_worker_heartbeat_metrics,
    write_prometheus_textfile,
)
from app.pipelines.staging import StagingBatchWriter


@dataclass(frozen=True)
class ScheduledIngestionCycleResult:
    summaries: tuple[AdapterBatchRunSummary, ...]
    freshness_checks: tuple[FreshnessCheck, ...]

    @property
    def has_alerts(self) -> bool:
        return any(check.is_alert() for check in self.freshness_checks)


def run_scheduled_ingestion_cycle(
    adapter_by_key: Mapping[str, DataSourceAdapter],
    *,
    settings=None,
    job_key: str = "scheduler.ingest.enabled_adapters",
    writer: StagingBatchWriter | None = None,
    run_writer: IngestionRunSummaryWriter | None = None,
) -> ScheduledIngestionCycleResult:
    resolved_settings = settings or load_worker_settings()
    summaries = run_enabled_adapter_batches(
        adapter_by_key,
        settings=resolved_settings,
        writer=writer,
        run_writer=run_writer,
        job_key=job_key,
    )
    freshness_checks = check_batch_freshness(
        summaries,
        max_age_seconds=resolved_settings.freshness_max_age_seconds,
    )
    log_event(
        "scheduler.ingestion_cycle.completed",
        job_key=job_key,
        adapter_count=len(summaries),
        alert_count=sum(1 for check in freshness_checks if check.is_alert()),
    )
    return ScheduledIngestionCycleResult(
        summaries=summaries,
        freshness_checks=freshness_checks,
    )


def run_enabled_adapters_once(
    *,
    settings: WorkerSettings | None = None,
    adapter_by_key: Mapping[str, DataSourceAdapter] | None = None,
    job_key: str = "scheduler.ingest.enabled_adapters",
    writer: StagingBatchWriter | None = None,
    run_writer: IngestionRunSummaryWriter | None = None,
) -> ScheduledIngestionCycleResult:
    resolved_settings = settings or load_worker_settings()
    enabled_keys = enabled_adapter_keys(resolved_settings)
    adapters = adapter_by_key if adapter_by_key is not None else build_runtime_adapters(resolved_settings)
    missing_keys = tuple(key for key in enabled_keys if key not in adapters)
    if not enabled_keys:
        log_event("scheduler.enabled_adapters.noop", reason="no_enabled_adapters")
    elif missing_keys:
        log_event(
            "scheduler.enabled_adapters.partial_runtime",
            missing_adapter_keys=missing_keys,
            available_adapter_keys=tuple(adapters),
        )

    result = run_scheduled_ingestion_cycle(
        adapters,
        settings=resolved_settings,
        job_key=job_key,
        writer=writer,
        run_writer=run_writer,
    )
    _write_worker_heartbeat(
        settings=resolved_settings,
        result=result,
        job_key=job_key,
    )
    return result


def run_enabled_adapters_loop(
    *,
    settings: WorkerSettings | None = None,
    max_ticks: int | None = None,
    sleep: Callable[[int], object] = time.sleep,
) -> tuple[ScheduledIngestionCycleResult, ...]:
    resolved_settings = settings or load_worker_settings()
    tick_limit = max_ticks if max_ticks is not None else resolved_settings.scheduler_max_ticks
    results: list[ScheduledIngestionCycleResult] = []
    tick = 0
    lease_holder = resolved_settings.metrics_instance
    lease_acquired = _acquire_scheduler_lease(settings=resolved_settings, holder_id=lease_holder)
    if lease_acquired is False:
        log_event(
            "scheduler.lease.skipped",
            lease_key="scheduler.enabled-adapters",
            holder_id=lease_holder,
        )
        return ()

    try:
        while tick_limit is None or tick < tick_limit:
            result = run_enabled_adapters_once(settings=resolved_settings)
            results.append(result)
            _write_scheduler_heartbeat(settings=resolved_settings, result=result)
            tick += 1
            if tick_limit is not None and tick >= tick_limit:
                break
            sleep(resolved_settings.scheduler_interval_seconds)
    finally:
        if lease_acquired is True:
            _release_scheduler_lease(settings=resolved_settings, holder_id=lease_holder)

    return tuple(results)


def main(argv: tuple[str, ...] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Flood Risk worker scheduler")
    parser.add_argument("--once", action="store_true", help="Run one scheduler tick and exit.")
    parser.add_argument(
        "--run-enabled-adapters",
        action="store_true",
        help="Run enabled runtime adapters selected by WORKER_ENABLED_ADAPTER_KEYS/config gates.",
    )
    parser.add_argument(
        "--official-demo",
        action="store_true",
        help="Run enabled official demo adapters through the scheduler cycle.",
    )
    parser.add_argument(
        "--max-ticks",
        type=int,
        help="Bound the scheduler loop. Defaults to SCHEDULER_MAX_TICKS when set.",
    )
    args = parser.parse_args(argv)
    settings = load_worker_settings()
    max_ticks = max(1, args.max_ticks) if args.max_ticks is not None else settings.scheduler_max_ticks
    log_event(
        "scheduler.started",
        interval_seconds=settings.scheduler_interval_seconds,
        enabled_adapters=enabled_adapter_keys(settings),
        max_ticks=max_ticks,
    )
    tick = 0
    while True:
        if args.run_enabled_adapters:
            run_enabled_adapters_once(settings=settings)
        elif args.official_demo:
            run_scheduled_ingestion_cycle(
                build_official_demo_adapters(),
                settings=settings,
                job_key="scheduler.official_demo",
            )
        else:
            run_sample_job(
                job_key="maintenance.placeholder",
                enabled_adapters=enabled_adapter_keys(settings),
            )
        tick += 1
        if args.once or (max_ticks is not None and tick >= max_ticks):
            return 0
        time.sleep(settings.scheduler_interval_seconds)


def _write_worker_heartbeat(
    *,
    settings: WorkerSettings,
    result: ScheduledIngestionCycleResult,
    job_key: str,
) -> None:
    if settings.worker_metrics_textfile_path is None:
        return

    content = render_worker_heartbeat_metrics(
        instance=settings.metrics_instance,
        queue=_queue_label(settings),
        heartbeat_at=datetime.now(UTC),
        last_run_status=_run_status(result),
        job=job_key,
    )
    _write_metrics_textfile(settings.worker_metrics_textfile_path, content)


def _write_scheduler_heartbeat(
    *,
    settings: WorkerSettings,
    result: ScheduledIngestionCycleResult,
) -> None:
    if settings.scheduler_metrics_textfile_path is None:
        return

    content = render_scheduler_heartbeat_metrics(
        instance=settings.metrics_instance,
        scheduler="enabled-adapters",
        heartbeat_at=datetime.now(UTC),
        last_run_status=_run_status(result),
    )
    _write_metrics_textfile(settings.scheduler_metrics_textfile_path, content)


def _write_metrics_textfile(path: str, content: str) -> None:
    try:
        write_prometheus_textfile(path, content)
    except OSError as exc:
        log_event("scheduler.metrics_textfile.write_failed", path=path, error=str(exc))


def _run_status(result: ScheduledIngestionCycleResult) -> RunStatus:
    if result.has_alerts:
        return "failed"
    if not result.summaries:
        return "skipped"
    return "succeeded"


def _queue_label(settings: WorkerSettings) -> str:
    keys = enabled_adapter_keys(settings)
    return ",".join(keys) if keys else "none"


def _acquire_scheduler_lease(*, settings: WorkerSettings, holder_id: str) -> bool | None:
    if not settings.database_url:
        return None

    try:
        acquired = PostgresRuntimeQueue(database_url=settings.database_url).acquire_scheduler_lease(
            lease_key="scheduler.enabled-adapters",
            holder_id=holder_id,
            ttl_seconds=settings.scheduler_lease_ttl_seconds,
        )
    except RuntimeQueueUnavailable as exc:
        log_event("scheduler.lease.unavailable", error=str(exc), fallback="local")
        return None

    if acquired:
        log_event(
            "scheduler.lease.acquired",
            lease_key="scheduler.enabled-adapters",
            holder_id=holder_id,
            ttl_seconds=settings.scheduler_lease_ttl_seconds,
        )
    return acquired


def _release_scheduler_lease(*, settings: WorkerSettings, holder_id: str) -> None:
    if not settings.database_url:
        return

    try:
        PostgresRuntimeQueue(database_url=settings.database_url).release_scheduler_lease(
            lease_key="scheduler.enabled-adapters",
            holder_id=holder_id,
        )
    except RuntimeQueueUnavailable as exc:
        log_event("scheduler.lease.release_failed", error=str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
