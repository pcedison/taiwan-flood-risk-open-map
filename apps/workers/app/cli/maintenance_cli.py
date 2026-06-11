"""Maintenance CLI commands: query heat aggregation and tile feature refresh."""

from __future__ import annotations

from datetime import datetime

from app.config import WorkerSettings
from app.jobs.query_heat import PostgresQueryHeatAggregationJob, QueryHeatAggregationUnavailable
from app.jobs.tile_cache import PostgresTileCacheWriter, TileCacheUnavailable, TileLayerUnsupported
from app.logging import log_event
from app.scheduler import (
    DEFAULT_QUERY_HEAT_RETENTION_DAYS,
    DEFAULT_TILE_FEATURE_LIMIT,
    DEFAULT_TILE_LAYER_ID,
    DEFAULT_TILE_PRUNE_LIMIT,
    run_maintenance_loop,
    run_maintenance_once,
)


def run_maintenance(
    *,
    settings: WorkerSettings,
    scheduler: bool,
    once: bool,
    max_ticks: int | None,
    periods: tuple[str, ...],
    retention_days: int | None,
    tile_layer_id: str,
    tile_feature_limit: int | None,
    tile_prune_limit: int | None,
) -> int:
    resolved_retention_days = (
        retention_days if retention_days is not None else DEFAULT_QUERY_HEAT_RETENTION_DAYS
    )
    resolved_tile_feature_limit = (
        tile_feature_limit if tile_feature_limit is not None else DEFAULT_TILE_FEATURE_LIMIT
    )
    resolved_tile_prune_limit = (
        tile_prune_limit if tile_prune_limit is not None else DEFAULT_TILE_PRUNE_LIMIT
    )
    resolved_tile_layer_id = tile_layer_id or DEFAULT_TILE_LAYER_ID

    if not scheduler:
        result = run_maintenance_once(
            settings=settings,
            periods=periods,
            retention_days=resolved_retention_days,
            tile_layer_id=resolved_tile_layer_id,
            tile_feature_limit=resolved_tile_feature_limit,
            tile_prune_limit=resolved_tile_prune_limit,
        )
        return 1 if result.failed else 0

    tick_limit = 1 if once else max(1, max_ticks) if max_ticks is not None else None
    results = run_maintenance_loop(
        settings=settings,
        max_ticks=tick_limit,
        periods=periods,
        retention_days=resolved_retention_days,
        tile_layer_id=resolved_tile_layer_id,
        tile_feature_limit=resolved_tile_feature_limit,
        tile_prune_limit=resolved_tile_prune_limit,
    )
    return 1 if any(result.failed for result in results) else 0


def aggregate_query_heat(
    *,
    settings: WorkerSettings,
    periods: tuple[str, ...],
    created_at_start: datetime | None = None,
    created_at_end: datetime | None = None,
    retention_days: int | None = None,
) -> int:
    if not settings.database_url:
        log_event("query_heat.aggregation.noop", reason="no_database_url", periods=periods)
        return 0

    try:
        job = PostgresQueryHeatAggregationJob(database_url=settings.database_url)
        summaries = job.aggregate(
            periods=periods,
            created_at_start=created_at_start,
            created_at_end=created_at_end,
        )
        retention_summary = (
            job.prune_retention(periods=periods, retention_days=retention_days)
            if retention_days is not None
            else None
        )
    except (QueryHeatAggregationUnavailable, ValueError) as exc:
        log_event("query_heat.aggregation.failed", error=str(exc), periods=periods)
        return 1

    log_event(
        "query_heat.aggregation.cli.completed",
        periods=tuple(summary.period for summary in summaries),
        buckets_upserted=sum(summary.buckets_upserted for summary in summaries),
        retention_days=retention_days,
        buckets_pruned=retention_summary.buckets_pruned if retention_summary else 0,
    )
    return 0


def refresh_tile_features(
    *,
    settings: WorkerSettings,
    layer_id: str,
    limit: int | None,
) -> int:
    if limit is not None and limit < 1:
        log_event("tile.features.refresh.failed", error="tile feature limit must be positive")
        return 1
    if not settings.database_url:
        log_event("tile.features.refresh.noop", reason="no_database_url", layer_id=layer_id)
        return 0

    try:
        result = PostgresTileCacheWriter(database_url=settings.database_url).refresh_layer_features(
            layer_id=layer_id,
            limit=limit,
        )
    except (TileCacheUnavailable, TileLayerUnsupported, ValueError) as exc:
        log_event("tile.features.refresh.failed", layer_id=layer_id, error=str(exc))
        return 1

    log_event(
        "tile.features.refresh.cli.completed",
        layer_id=result.layer_id,
        refreshed=result.refreshed,
    )
    return 0
