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
from app.jobs.freshness import FreshnessCheck, check_batch_freshness
from app.jobs.ingestion import (
    AdapterBatchRunSummary,
    IngestionRunSummaryWriter,
    run_enabled_adapter_batches,
)
from app.jobs.official_demo import build_official_demo_adapters
from app.jobs.query_heat import (
    SUPPORTED_QUERY_HEAT_PERIODS,
    PostgresQueryHeatAggregationJob,
    QueryHeatAggregationSummary,
    QueryHeatAggregationUnavailable,
    QueryHeatRetentionSummary,
)
from app.jobs.queue import PostgresRuntimeQueue, RuntimeQueueUnavailable
from app.jobs.runtime import (
    RuntimeQueue,
    RuntimeQueueProducerResult,
    build_runtime_adapters,
    produce_enabled_runtime_adapter_jobs,
)
from app.jobs.sample import run_sample_job
from app.jobs.tile_cache import (
    PostgresTileCacheWriter,
    TileCachePruneResult,
    TileCacheUnavailable,
    TileFeatureRefreshResult,
    TileLayerUnsupported,
)
from app.logging import log_event
from app.metrics import (
    RunStatus,
    render_scheduler_heartbeat_metrics,
    render_worker_heartbeat_metrics,
    write_prometheus_textfile,
)
from app.pipelines.staging import StagingBatchWriter


DEFAULT_QUERY_HEAT_RETENTION_DAYS = 90
DEFAULT_TILE_LAYER_ID = "flood-potential"
DEFAULT_TILE_FEATURE_LIMIT = 1000
DEFAULT_TILE_PRUNE_LIMIT = 1000
MAINTENANCE_LEASE_KEY = "scheduler.maintenance"

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


def run_maintenance_once(
    *,
    settings: WorkerSettings | None = None,
    periods: Iterable[str] = SUPPORTED_QUERY_HEAT_PERIODS,
    retention_days: int = DEFAULT_QUERY_HEAT_RETENTION_DAYS,
    tile_layer_id: str = DEFAULT_TILE_LAYER_ID,
    tile_feature_limit: int | None = DEFAULT_TILE_FEATURE_LIMIT,
    tile_prune_limit: int = DEFAULT_TILE_PRUNE_LIMIT,
    tile_expired_before: datetime | None = None,
) -> MaintenanceCycleResult:
    resolved_settings = settings or load_worker_settings()
    resolved_periods = tuple(dict.fromkeys(periods))
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
    tile_refresh: TileFeatureRefreshResult | None = None
    tile_prune: TileCachePruneResult | None = None
    expired_before = tile_expired_before or datetime.now(UTC)

    try:
        query_heat_job = PostgresQueryHeatAggregationJob(
            database_url=resolved_settings.database_url,
        )
        query_heat_summaries = query_heat_job.aggregate(periods=resolved_periods)
        query_heat_retention = query_heat_job.prune_retention(
            periods=resolved_periods,
            retention_days=retention_days,
        )

        tile_cache_writer = PostgresTileCacheWriter(database_url=resolved_settings.database_url)
        tile_refresh = tile_cache_writer.refresh_layer_features(
            layer_id=tile_layer_id,
            limit=tile_feature_limit,
        )
        tile_prune = tile_cache_writer.prune_expired(
            layer_id=tile_layer_id,
            expired_before=expired_before,
            limit=tile_prune_limit,
        )
    except (
        QueryHeatAggregationUnavailable,
        TileCacheUnavailable,
        TileLayerUnsupported,
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
            tile_refresh=tile_refresh,
            tile_prune=tile_prune,
        )

    log_event(
        "scheduler.maintenance.completed",
        periods=tuple(summary.period for summary in query_heat_summaries),
        query_heat_buckets_upserted=sum(
            summary.buckets_upserted for summary in query_heat_summaries
        ),
        query_heat_retention_days=retention_days,
        query_heat_buckets_pruned=(
            query_heat_retention.buckets_pruned if query_heat_retention else 0
        ),
        tile_layer_id=tile_refresh.layer_id if tile_refresh else tile_layer_id,
        tile_features_refreshed=tile_refresh.refreshed if tile_refresh else 0,
        tile_cache_deleted=tile_prune.tile_cache_deleted if tile_prune else 0,
        tile_features_deleted=tile_prune.features_deleted if tile_prune else 0,
    )
    return MaintenanceCycleResult(
        status="succeeded",
        query_heat_summaries=query_heat_summaries,
        query_heat_retention=query_heat_retention,
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
    lease_holder = resolved_settings.metrics_instance
    lease_acquired = _acquire_scheduler_lease(
        settings=resolved_settings,
        holder_id=lease_holder,
        lease_key=MAINTENANCE_LEASE_KEY,
    )
    if lease_acquired is False:
        log_event(
            "scheduler.maintenance.lease_skipped",
            lease_key=MAINTENANCE_LEASE_KEY,
            holder_id=lease_holder,
        )
        return ()

    try:
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
    finally:
        if lease_acquired is True:
            _release_scheduler_lease(
                settings=resolved_settings,
                holder_id=lease_holder,
                lease_key=MAINTENANCE_LEASE_KEY,
            )

    return tuple(results)


def enqueue_enabled_adapters_once(
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
            result = enqueue_enabled_adapters_once(
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
        help="Enqueue durable runtime adapter jobs selected by WORKER_ENABLED_ADAPTER_KEYS/config gates.",
    )
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
        "--maintenance",
        action="store_true",
        help="Run Query Heat and tile cache maintenance on a bounded scheduler loop.",
    )
    parser.add_argument(
        "--query-heat-periods",
        default=",".join(SUPPORTED_QUERY_HEAT_PERIODS),
        help="Comma-separated periods for maintenance Query Heat aggregation.",
    )
    parser.add_argument(
        "--query-heat-retention-days",
        type=int,
        default=DEFAULT_QUERY_HEAT_RETENTION_DAYS,
        help="Retention age in days for maintenance Query Heat bucket pruning.",
    )
    parser.add_argument(
        "--tile-layer-id",
        default=DEFAULT_TILE_LAYER_ID,
        help="Tile layer for maintenance feature refresh and expired prune.",
    )
    parser.add_argument(
        "--tile-feature-limit",
        type=int,
        default=DEFAULT_TILE_FEATURE_LIMIT,
        help="Positive row limit for maintenance tile feature refresh.",
    )
    parser.add_argument(
        "--tile-prune-limit",
        type=int,
        default=DEFAULT_TILE_PRUNE_LIMIT,
        help="Positive per-table row limit for maintenance tile expired pruning.",
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
    if args.maintenance:
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

    if args.enqueue_runtime_jobs:
        enqueue_enabled_adapters_loop(
            settings=settings,
            max_ticks=1 if args.once else max_ticks,
        )
        return 0

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
