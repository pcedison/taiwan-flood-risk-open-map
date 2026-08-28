from __future__ import annotations

import argparse
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.adapters.contracts import DataSourceAdapter
from app.adapters.registry import enabled_adapter_keys
from app.config import WorkerSettings, load_worker_settings
from app.jobs.evidence_retention import (
    EvidenceRetentionSummary,
    EvidenceRetentionUnavailable,
    LocationQueryRetentionSummary,
    PostgresEvidenceRetentionJob,
)
from app.jobs.freshness import FreshnessCheck, check_batch_freshness
from app.jobs.frozen_legacy import report_frozen_legacy
from app.jobs.ingestion import (
    AdapterBatchRunSummary,
    IngestionRunSummaryWriter,
    run_enabled_adapter_batches,
)
from app.jobs.query_heat import (
    SUPPORTED_QUERY_HEAT_PERIODS,
    PostgresQueryHeatAggregationJob,  # noqa: F401 - compatibility seam for freeze tests
    QueryHeatAggregationSummary,
    QueryHeatRetentionSummary,
)
from app.jobs.queue import PostgresRuntimeQueue, RuntimeQueueUnavailable
from app.jobs.runtime import (
    RuntimeQueue,
    RuntimeQueueProducerResult,
    build_runtime_adapters,
    produce_enabled_runtime_adapter_jobs,
)
from app.jobs.tile_cache import (
    PostgresTileCacheWriter,  # noqa: F401 - compatibility seam for freeze tests
    TileCachePruneResult,
    TileFeatureRefreshResult,
)
from app.logging import log_event
from app.metrics import (
    RunStatus,
    render_scheduler_heartbeat_metrics,
    render_source_freshness_metrics,
    render_worker_heartbeat_metrics,
    write_prometheus_textfile,
)
from app.pipelines.staging import StagingBatchWriter

DEFAULT_QUERY_HEAT_RETENTION_DAYS = 90
DEFAULT_TILE_LAYER_ID = "flood-potential"
DEFAULT_TILE_FEATURE_LIMIT = 1000
DEFAULT_TILE_PRUNE_LIMIT = 1000

MaintenanceStatus = Literal["succeeded", "skipped", "failed"]


@dataclass(frozen=True)
class ScheduledIngestionCycleResult:
    summaries: tuple[AdapterBatchRunSummary, ...]
    freshness_checks: tuple[FreshnessCheck, ...]

    @property
    def has_alerts(self) -> bool:
        return any(check.is_alert() for check in self.freshness_checks)


@dataclass(frozen=True)
class MaintenanceCycleResult:
    status: MaintenanceStatus
    reason: str | None = None
    query_heat_summaries: tuple[QueryHeatAggregationSummary, ...] = ()
    query_heat_retention: QueryHeatRetentionSummary | None = None
    evidence_retention: EvidenceRetentionSummary | None = None
    location_query_retention: LocationQueryRetentionSummary | None = None
    tile_refresh: TileFeatureRefreshResult | None = None
    tile_prune: TileCachePruneResult | None = None

    @property
    def failed(self) -> bool:
        return self.status == "failed"


def run_scheduled_ingestion_cycle(
    adapter_by_key: Mapping[str, DataSourceAdapter],
    *,
    settings=None,
    job_key: str = "scheduler.ingest.enabled_adapters",
    writer: StagingBatchWriter | None = None,
    run_writer: IngestionRunSummaryWriter | None = None,
    pipeline_run_at: datetime | None = None,
) -> int:
    del adapter_by_key, settings, job_key, writer, run_writer, pipeline_run_at
    return report_frozen_legacy()


def _execute_scheduled_ingestion_cycle(
    adapter_by_key: Mapping[str, DataSourceAdapter],
    *,
    settings=None,
    runtime_selection_adapter_keys: tuple[str, ...] | None = None,
    write_runtime_selection_revision: bool = True,
    job_key: str = "scheduler.ingest.enabled_adapters",
    writer: StagingBatchWriter | None = None,
    run_writer: IngestionRunSummaryWriter | None = None,
    pipeline_run_at: datetime | None = None,
) -> ScheduledIngestionCycleResult:
    resolved_settings = settings or load_worker_settings()
    summaries = run_enabled_adapter_batches(
        adapter_by_key,
        settings=resolved_settings,
        runtime_selection_adapter_keys=runtime_selection_adapter_keys,
        write_runtime_selection_revision=write_runtime_selection_revision,
        writer=writer,
        run_writer=run_writer,
        job_key=job_key,
        pipeline_run_at=pipeline_run_at,
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
) -> int:
    del settings, adapter_by_key, job_key, writer, run_writer
    return report_frozen_legacy()


def _execute_enabled_adapters_once(
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

    result = _execute_scheduled_ingestion_cycle(
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
) -> int:
    del settings, max_ticks, sleep
    return report_frozen_legacy()


def _execute_enabled_adapters_loop(
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
            result = _execute_enabled_adapters_once(settings=resolved_settings)
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


def run_maintenance_once(
    *,
    settings: WorkerSettings | None = None,
    periods: Iterable[str] = SUPPORTED_QUERY_HEAT_PERIODS,
    retention_days: int = DEFAULT_QUERY_HEAT_RETENTION_DAYS,
    tile_layer_id: str = DEFAULT_TILE_LAYER_ID,
    tile_feature_limit: int | None = DEFAULT_TILE_FEATURE_LIMIT,
    tile_prune_limit: int = DEFAULT_TILE_PRUNE_LIMIT,
    tile_expired_before: datetime | None = None,
    evidence_retention_hours: int | None = None,
    location_query_retention_hours: int | None = None,
) -> MaintenanceCycleResult:
    resolved_settings = settings or load_worker_settings()
    resolved_periods = tuple(dict.fromkeys(periods))
    resolved_retention_hours = (
        evidence_retention_hours
        if evidence_retention_hours is not None
        else resolved_settings.evidence_realtime_retention_hours
    )
    resolved_location_query_retention_hours = (
        location_query_retention_hours
        if location_query_retention_hours is not None
        else resolved_settings.location_queries_retention_hours
    )
    if not resolved_settings.database_url:
        log_event(
            "scheduler.maintenance.noop",
            reason="no_database_url",
            periods=resolved_periods,
            tile_layer_id=tile_layer_id,
        )
        return MaintenanceCycleResult(status="skipped", reason="no_database_url")

    query_heat_summaries: tuple[QueryHeatAggregationSummary, ...] = ()
    query_heat_retention: QueryHeatRetentionSummary | None = None
    evidence_retention: EvidenceRetentionSummary | None = None
    location_query_retention: LocationQueryRetentionSummary | None = None
    tile_refresh: TileFeatureRefreshResult | None = None
    tile_prune: TileCachePruneResult | None = None
    del retention_days, tile_feature_limit, tile_prune_limit, tile_expired_before

    try:
        retention_job = PostgresEvidenceRetentionJob(
            database_url=resolved_settings.database_url,
        )
        evidence_retention = retention_job.prune_realtime(
            retention_hours=resolved_retention_hours
        )
        location_query_retention = retention_job.prune_location_queries(
            retention_hours=resolved_location_query_retention_hours
        )

    except (
        EvidenceRetentionUnavailable,
        ValueError,
    ) as exc:
        log_event(
            "scheduler.maintenance.failed",
            error=str(exc),
            periods=resolved_periods,
            tile_layer_id=tile_layer_id,
        )
        return MaintenanceCycleResult(
            status="failed",
            reason=str(exc),
            query_heat_summaries=query_heat_summaries,
            query_heat_retention=query_heat_retention,
            evidence_retention=evidence_retention,
            location_query_retention=location_query_retention,
            tile_refresh=tile_refresh,
            tile_prune=tile_prune,
        )

    log_event(
        "scheduler.maintenance.completed",
        evidence_retention_hours=resolved_retention_hours,
        evidence_rows_pruned=(
            evidence_retention.rows_deleted if evidence_retention else 0
        ),
        location_query_retention_hours=resolved_location_query_retention_hours,
        location_query_rows_pruned=(
            location_query_retention.rows_deleted if location_query_retention else 0
        ),
        frozen_query_heat=True,
        frozen_local_tiles=True,
    )
    return MaintenanceCycleResult(
        status="succeeded",
        query_heat_summaries=query_heat_summaries,
        query_heat_retention=query_heat_retention,
        evidence_retention=evidence_retention,
        location_query_retention=location_query_retention,
        tile_refresh=tile_refresh,
        tile_prune=tile_prune,
    )


def run_maintenance_loop(
    *,
    settings: WorkerSettings | None = None,
    max_ticks: int | None = None,
    sleep: Callable[[int], object] = time.sleep,
    periods: Iterable[str] = SUPPORTED_QUERY_HEAT_PERIODS,
    retention_days: int = DEFAULT_QUERY_HEAT_RETENTION_DAYS,
    tile_layer_id: str = DEFAULT_TILE_LAYER_ID,
    tile_feature_limit: int | None = DEFAULT_TILE_FEATURE_LIMIT,
    tile_prune_limit: int = DEFAULT_TILE_PRUNE_LIMIT,
) -> tuple[MaintenanceCycleResult, ...]:
    resolved_settings = settings or load_worker_settings()
    tick_limit = max_ticks if max_ticks is not None else resolved_settings.scheduler_max_ticks
    tick_limit = max(1, tick_limit or 1)
    resolved_periods = tuple(dict.fromkeys(periods))
    results: list[MaintenanceCycleResult] = []
    tick = 0
    while tick < tick_limit:
        result = run_maintenance_once(
            settings=resolved_settings,
            periods=resolved_periods,
            retention_days=retention_days,
            tile_layer_id=tile_layer_id,
            tile_feature_limit=tile_feature_limit,
            tile_prune_limit=tile_prune_limit,
        )
        results.append(result)
        tick += 1
        if tick >= tick_limit:
            break
        sleep(resolved_settings.scheduler_interval_seconds)

    return tuple(results)


def enqueue_enabled_adapters_once(
    *,
    settings: WorkerSettings | None = None,
    queue: RuntimeQueue | None = None,
    job_key: str = "scheduler.enqueue.enabled_adapters",
) -> int:
    del settings, queue, job_key
    return report_frozen_legacy()


def _execute_enqueue_enabled_adapters_once(
    *,
    settings: WorkerSettings | None = None,
    queue: RuntimeQueue | None = None,
    job_key: str = "scheduler.enqueue.enabled_adapters",
) -> RuntimeQueueProducerResult:
    resolved_settings = settings or load_worker_settings()
    result = produce_enabled_runtime_adapter_jobs(
        resolved_settings,
        queue=queue,
        job_key=job_key,
    )
    log_event(
        "scheduler.queue_producer.tick_completed",
        status=result.status,
        reason=result.reason,
        adapter_count=len(result.adapter_keys),
        durable_job_count=result.durable_job_count,
    )
    return result


def enqueue_enabled_adapters_loop(
    *,
    settings: WorkerSettings | None = None,
    queue: RuntimeQueue | None = None,
    max_ticks: int | None = None,
    sleep: Callable[[int], object] = time.sleep,
) -> int:
    del settings, queue, max_ticks, sleep
    return report_frozen_legacy()


def _execute_enqueue_enabled_adapters_loop(
    *,
    settings: WorkerSettings | None = None,
    queue: RuntimeQueue | None = None,
    max_ticks: int | None = None,
    sleep: Callable[[int], object] = time.sleep,
) -> tuple[RuntimeQueueProducerResult, ...]:
    resolved_settings = settings or load_worker_settings()
    tick_limit = max_ticks if max_ticks is not None else resolved_settings.scheduler_max_ticks
    results: list[RuntimeQueueProducerResult] = []
    tick = 0
    lease_holder = resolved_settings.metrics_instance
    lease_acquired = _acquire_scheduler_lease(settings=resolved_settings, holder_id=lease_holder)
    if lease_acquired is False:
        log_event(
            "scheduler.queue_producer.lease_skipped",
            lease_key="scheduler.enabled-adapters",
            holder_id=lease_holder,
        )
        return ()

    try:
        while tick_limit is None or tick < tick_limit:
            result = _execute_enqueue_enabled_adapters_once(
                settings=resolved_settings,
                queue=queue,
            )
            results.append(result)
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
        "--enqueue-runtime-jobs",
        action="store_true",
        help="Frozen legacy runtime queue producer in v1; accepted and exits 2.",
    )
    parser.add_argument(
        "--run-enabled-adapters",
        action="store_true",
        help="Frozen legacy generic runtime in v1; accepted and exits 2.",
    )
    parser.add_argument(
        "--official-demo",
        action="store_true",
        help="Frozen legacy official-demo scheduler in v1; accepted and exits 2.",
    )
    parser.add_argument(
        "--maintenance",
        action="store_true",
        help="Run evidence realtime and location-query privacy retention only.",
    )
    parser.add_argument(
        "--query-heat-periods",
        default=",".join(SUPPORTED_QUERY_HEAT_PERIODS),
        help="Frozen Query Heat aggregation compatibility value; parsed and ignored in v1.",
    )
    parser.add_argument(
        "--query-heat-retention-days",
        type=int,
        default=DEFAULT_QUERY_HEAT_RETENTION_DAYS,
        help="Frozen Query Heat retention compatibility value; parsed and ignored in v1.",
    )
    parser.add_argument(
        "--tile-layer-id",
        default=DEFAULT_TILE_LAYER_ID,
        help="Frozen local-tile layer compatibility value; parsed and ignored in v1.",
    )
    parser.add_argument(
        "--tile-feature-limit",
        type=int,
        default=DEFAULT_TILE_FEATURE_LIMIT,
        help="Frozen local-tile refresh compatibility value; parsed and ignored in v1.",
    )
    parser.add_argument(
        "--tile-prune-limit",
        type=int,
        default=DEFAULT_TILE_PRUNE_LIMIT,
        help="Frozen local-tile prune compatibility value; parsed and ignored in v1.",
    )
    parser.add_argument(
        "--max-ticks",
        type=int,
        help="Bound the scheduler loop. Defaults to SCHEDULER_MAX_TICKS when set.",
    )
    args = parser.parse_args(argv)
    # Task 14's reviewed --v1-baseline branch is intentionally added before this guard.
    if (
        not args.maintenance
        or args.enqueue_runtime_jobs
        or args.run_enabled_adapters
        or args.official_demo
    ):
        return report_frozen_legacy()

    settings = load_worker_settings()
    max_ticks = max(1, args.max_ticks) if args.max_ticks is not None else settings.scheduler_max_ticks
    log_event(
        "scheduler.started",
        interval_seconds=settings.scheduler_interval_seconds,
        enabled_adapters=enabled_adapter_keys(settings),
        max_ticks=max_ticks,
    )
    results = run_maintenance_loop(
        settings=settings,
        max_ticks=1 if args.once else max_ticks,
        periods=_parse_query_heat_periods(args.query_heat_periods),
        retention_days=args.query_heat_retention_days,
        tile_layer_id=args.tile_layer_id,
        tile_feature_limit=args.tile_feature_limit,
        tile_prune_limit=args.tile_prune_limit,
    )
    return 1 if any(result.failed for result in results) else 0


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
    content += render_source_freshness_metrics(
        summaries=result.summaries,
        freshness_checks=result.freshness_checks,
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


def _parse_query_heat_periods(raw: str) -> tuple[str, ...]:
    periods = tuple(dict.fromkeys(part.strip() for part in raw.split(",") if part.strip()))
    return periods or SUPPORTED_QUERY_HEAT_PERIODS


def _acquire_scheduler_lease(
    *,
    settings: WorkerSettings,
    holder_id: str,
    lease_key: str = "scheduler.enabled-adapters",
) -> bool | None:
    if not settings.database_url:
        return None

    try:
        acquired = PostgresRuntimeQueue(database_url=settings.database_url).acquire_scheduler_lease(
            lease_key=lease_key,
            holder_id=holder_id,
            ttl_seconds=settings.scheduler_lease_ttl_seconds,
        )
    except RuntimeQueueUnavailable as exc:
        log_event("scheduler.lease.unavailable", error=str(exc), fallback="local")
        return None

    if acquired:
        log_event(
            "scheduler.lease.acquired",
            lease_key=lease_key,
            holder_id=holder_id,
            ttl_seconds=settings.scheduler_lease_ttl_seconds,
        )
    return acquired


def _release_scheduler_lease(
    *,
    settings: WorkerSettings,
    holder_id: str,
    lease_key: str = "scheduler.enabled-adapters",
) -> None:
    if not settings.database_url:
        return

    try:
        PostgresRuntimeQueue(database_url=settings.database_url).release_scheduler_lease(
            lease_key=lease_key,
            holder_id=holder_id,
        )
    except RuntimeQueueUnavailable as exc:
        log_event("scheduler.lease.release_failed", error=str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
