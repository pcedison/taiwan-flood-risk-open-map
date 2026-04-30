from __future__ import annotations

import argparse
import time
from collections.abc import Sequence
from dataclasses import dataclass

from app.adapters.registry import enabled_adapter_keys
from app.config import WorkerSettings, load_worker_settings
from app.jobs.official_demo import build_official_demo_adapters
from app.jobs.query_heat import (
    SUPPORTED_QUERY_HEAT_PERIODS,
    PostgresQueryHeatAggregationJob,
    QueryHeatAggregationUnavailable,
)
from app.scheduler import (
    run_enabled_adapters_loop,
    run_enabled_adapters_once,
    run_scheduled_ingestion_cycle,
)
from app.jobs.runtime import work_runtime_queue_once
from app.jobs.sample import run_sample_job
from app.jobs.tile_cache import PostgresTileCacheWriter, TileCacheUnavailable, TileLayerUnsupported
from app.logging import log_event
from app.pipelines.ingestion_runs import PostgresIngestionRunWriter
from app.pipelines.postgres_writer import PostgresStagingBatchWriter
from app.pipelines.promotion import (
    PostgresEvidencePromotionWriter,
    PromotionResult,
    promote_accepted_staging,
)


@dataclass(frozen=True)
class DemoPersistenceWriters:
    staging_writer: PostgresStagingBatchWriter
    run_writer: PostgresIngestionRunWriter
    promotion_writer: PostgresEvidencePromotionWriter


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Flood Risk worker runtime")
    parser.add_argument("--once", action="store_true", help="Run one sample job and exit.")
    parser.add_argument(
        "--run-official-demo",
        action="store_true",
        help="Run enabled official demo adapters once through ingestion and freshness checks.",
    )
    parser.add_argument(
        "--run-enabled-adapters",
        action="store_true",
        help="Run configured runtime adapters once, selected by WORKER_ENABLED_ADAPTER_KEYS/config gates.",
    )
    parser.add_argument(
        "--scheduler",
        action="store_true",
        help="Run configured runtime adapters in a scheduler loop.",
    )
    parser.add_argument(
        "--work-runtime-queue",
        action="store_true",
        help="Consume durable worker_runtime_jobs. Use --once for one dequeue attempt.",
    )
    parser.add_argument(
        "--aggregate-query-heat",
        action="store_true",
        help="Materialize query heat buckets from location_queries into query_heat_buckets.",
    )
    parser.add_argument(
        "--query-heat-periods",
        default=",".join(SUPPORTED_QUERY_HEAT_PERIODS),
        help="Comma-separated periods for --aggregate-query-heat. Defaults to P1D,P7D.",
    )
    parser.add_argument(
        "--refresh-tile-features",
        action="store_true",
        help="Refresh worker-generated map_layer_features for supported tile layers.",
    )
    parser.add_argument(
        "--tile-layer-id",
        default="flood-potential",
        help="Tile layer for --refresh-tile-features. Defaults to flood-potential.",
    )
    parser.add_argument(
        "--tile-feature-limit",
        type=int,
        help="Optional positive row limit for --refresh-tile-features.",
    )
    parser.add_argument(
        "--max-ticks",
        type=int,
        help=(
            "Bound --scheduler or --work-runtime-queue ticks. "
            "Defaults to SCHEDULER_MAX_TICKS for --scheduler."
        ),
    )
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Persist --run-official-demo output to Postgres staging, ingestion runs, and evidence.",
    )
    parser.add_argument(
        "--database-url",
        help="Postgres URL for --run-official-demo --persist. Defaults to WORKER_DATABASE_URL/DATABASE_URL.",
    )
    parser.add_argument(
        "--list-adapters",
        action="store_true",
        help="Print enabled adapter keys and exit.",
    )
    args = parser.parse_args(argv)
    settings = load_worker_settings()

    if args.list_adapters:
        for adapter_key in enabled_adapter_keys(settings):
            print(adapter_key)
        return 0

    if args.work_runtime_queue:
        return _work_runtime_queue(settings=settings, once=args.once, max_ticks=args.max_ticks)

    if args.aggregate_query_heat:
        return _aggregate_query_heat(
            settings=settings,
            periods=_parse_query_heat_periods(args.query_heat_periods),
        )

    if args.refresh_tile_features:
        return _refresh_tile_features(
            settings=settings,
            layer_id=args.tile_layer_id,
            limit=args.tile_feature_limit,
        )

    if args.once:
        run_sample_job(enabled_adapters=enabled_adapter_keys(settings))
        return 0

    if args.run_enabled_adapters:
        result = run_enabled_adapters_once(settings=settings, job_key="worker.runtime.run_once")
        return 1 if result.has_alerts else 0

    if args.scheduler:
        results = run_enabled_adapters_loop(
            settings=settings,
            max_ticks=max(1, args.max_ticks) if args.max_ticks is not None else None,
        )
        return 1 if any(result.has_alerts for result in results) else 0

    if args.run_official_demo:
        adapters = build_official_demo_adapters()
        persistence = (
            _build_demo_persistence_writers(settings, database_url=args.database_url)
            if args.persist
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
            persisted=args.persist,
            promoted=promotion.promoted,
            evidence_ids=promotion.evidence_ids,
        )
        return 1 if result.has_alerts else 0

    log_event("worker.started", mode="placeholder", enabled_adapters=enabled_adapter_keys(settings))
    while True:
        run_sample_job(enabled_adapters=enabled_adapter_keys(settings))
        time.sleep(settings.worker_idle_seconds)


def _build_demo_persistence_writers(
    settings: WorkerSettings,
    *,
    database_url: str | None = None,
) -> DemoPersistenceWriters:
    resolved_database_url = database_url or settings.database_url
    if not resolved_database_url:
        raise SystemExit(
            "--persist requires --database-url, WORKER_DATABASE_URL, or DATABASE_URL"
        )

    return DemoPersistenceWriters(
        staging_writer=PostgresStagingBatchWriter(database_url=resolved_database_url),
        run_writer=PostgresIngestionRunWriter(database_url=resolved_database_url),
        promotion_writer=PostgresEvidencePromotionWriter(database_url=resolved_database_url),
    )


def _work_runtime_queue(
    *,
    settings: WorkerSettings,
    once: bool,
    max_ticks: int | None,
) -> int:
    tick_limit = 1 if once else max(1, max_ticks) if max_ticks is not None else None
    had_failure = False
    tick = 0
    while tick_limit is None or tick < tick_limit:
        result = work_runtime_queue_once(settings=settings)
        had_failure = had_failure or result.status == "failed"
        tick += 1
        if tick_limit is not None and tick >= tick_limit:
            break
        time.sleep(settings.worker_idle_seconds)
    return 1 if had_failure else 0


def _aggregate_query_heat(*, settings: WorkerSettings, periods: tuple[str, ...]) -> int:
    if not settings.database_url:
        log_event("query_heat.aggregation.noop", reason="no_database_url", periods=periods)
        return 0

    try:
        summaries = PostgresQueryHeatAggregationJob(database_url=settings.database_url).aggregate(
            periods=periods
        )
    except (QueryHeatAggregationUnavailable, ValueError) as exc:
        log_event("query_heat.aggregation.failed", error=str(exc), periods=periods)
        return 1

    log_event(
        "query_heat.aggregation.cli.completed",
        periods=tuple(summary.period for summary in summaries),
        buckets_upserted=sum(summary.buckets_upserted for summary in summaries),
    )
    return 0


def _refresh_tile_features(
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


def _parse_query_heat_periods(raw: str) -> tuple[str, ...]:
    periods = tuple(dict.fromkeys(part.strip() for part in raw.split(",") if part.strip()))
    return periods or SUPPORTED_QUERY_HEAT_PERIODS


if __name__ == "__main__":
    raise SystemExit(main())
