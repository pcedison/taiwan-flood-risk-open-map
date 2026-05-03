from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from app.adapters.registry import enabled_adapter_keys
from app.config import WorkerSettings, env_flag, env_int, env_list, load_worker_settings
from app.jobs.historical_news_backfill import (
    DEFAULT_GDELT_REHEARSAL_CADENCE_SECONDS,
    DEFAULT_GDELT_REHEARSAL_MAX_RECORDS_PER_QUERY,
    DEFAULT_TAIWAN_FLOOD_NEWS_QUERIES,
    HistoricalNewsBackfillConfig,
    run_historical_news_backfill_rehearsal,
)
from app.jobs.official_demo import build_official_demo_adapters
from app.jobs.query_heat import (
    SUPPORTED_QUERY_HEAT_PERIODS,
    PostgresQueryHeatAggregationJob,
    QueryHeatAggregationUnavailable,
)
from app.scheduler import (
    DEFAULT_QUERY_HEAT_RETENTION_DAYS,
    DEFAULT_TILE_FEATURE_LIMIT,
    DEFAULT_TILE_LAYER_ID,
    DEFAULT_TILE_PRUNE_LIMIT,
    enqueue_enabled_adapters_loop,
    enqueue_enabled_adapters_once,
    run_maintenance_loop,
    run_maintenance_once,
    run_enabled_adapters_loop,
    run_enabled_adapters_once,
    run_scheduled_ingestion_cycle,
)
from app.jobs.queue import (
    PostgresRuntimeQueue,
    RuntimeQueueDeadLetterJob,
    RuntimeQueueDeadLetterSummary,
    RuntimeQueueMetricsSnapshot,
    RuntimeQueueUnavailable,
)
from app.jobs.replay_audit import PostgresRuntimeQueueReplayAudit
from app.jobs.runtime import (
    build_runtime_adapters,
    build_runtime_persistence_writers,
    work_runtime_queue_once,
)
from app.jobs.runtime_managed import run_managed_runtime_ingestion_cycle
from app.jobs.sample import run_sample_job
from app.jobs.tile_cache import PostgresTileCacheWriter, TileCacheUnavailable, TileLayerUnsupported
from app.logging import log_event
from app.metrics import render_runtime_queue_metrics, write_prometheus_textfile
from app.jobs.ingestion import IngestionRunSummaryWriter
from app.pipelines.ingestion_runs import PostgresIngestionRunWriter
from app.pipelines.postgres_writer import PostgresStagingBatchWriter
from app.pipelines.promotion import (
    EvidencePromotionWriter,
    PostgresEvidencePromotionWriter,
    PromotionResult,
    promote_accepted_staging,
)
from app.pipelines.staging import StagingBatchWriter


@dataclass(frozen=True)
class DemoPersistenceWriters:
    staging_writer: StagingBatchWriter
    run_writer: IngestionRunSummaryWriter
    promotion_writer: EvidencePromotionWriter


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
        "--rehearse-gdelt-news-backfill",
        action="store_true",
        help=(
            "Run the explicit GDELT public-news egress rehearsal. "
            "Requires GDELT_SOURCE_ENABLED, GDELT_BACKFILL_ENABLED, "
            "SOURCE_NEWS_ENABLED, and SOURCE_TERMS_REVIEW_ACK gates."
        ),
    )
    parser.add_argument(
        "--gdelt-rehearsal-mode",
        choices=("dry-run", "staging-batch"),
        default="dry-run",
        help="GDELT rehearsal output mode. Defaults to fetch/normalize dry-run.",
    )
    parser.add_argument(
        "--gdelt-source-enabled",
        action="store_true",
        help="Open the GDELT-specific source rehearsal gate for this command only.",
    )
    parser.add_argument(
        "--gdelt-backfill-enabled",
        action="store_true",
        help="Open the GDELT backfill rehearsal gate for this command only.",
    )
    parser.add_argument(
        "--gdelt-start",
        type=_parse_query_heat_datetime,
        help="Inclusive ISO-8601 start timestamp for bounded GDELT rehearsal.",
    )
    parser.add_argument(
        "--gdelt-end",
        type=_parse_query_heat_datetime,
        help="Exclusive ISO-8601 end timestamp for bounded GDELT rehearsal.",
    )
    parser.add_argument(
        "--gdelt-query",
        action="append",
        help=(
            "Override default Taiwan flood-news queries. May be supplied multiple times. "
            "GDELT_REHEARSAL_QUERIES can also provide comma-separated queries."
        ),
    )
    parser.add_argument(
        "--gdelt-max-records",
        type=int,
        help=(
            "Per-query GDELT maxrecords for rehearsal. "
            f"Default: {DEFAULT_GDELT_REHEARSAL_MAX_RECORDS_PER_QUERY}; adapter clamps at 250."
        ),
    )
    parser.add_argument(
        "--gdelt-cadence-seconds",
        type=int,
        help=(
            "Minimum seconds between GDELT query requests during rehearsal. "
            f"Default: {DEFAULT_GDELT_REHEARSAL_CADENCE_SECONDS}."
        ),
    )
    parser.add_argument(
        "--scheduler",
        action="store_true",
        help="Run configured runtime adapters in a scheduler loop.",
    )
    parser.add_argument(
        "--maintenance",
        action="store_true",
        help="Run Query Heat and tile cache maintenance. Combine with --scheduler for a loop.",
    )
    parser.add_argument(
        "--work-runtime-queue",
        action="store_true",
        help="Consume durable worker_runtime_jobs. Use --once for one dequeue attempt.",
    )
    parser.add_argument(
        "--enqueue-runtime-jobs",
        action="store_true",
        help=(
            "Producer path: enqueue durable worker_runtime_jobs for configured runtime adapters. "
            "Combine with --scheduler for a lease-guarded loop."
        ),
    )
    parser.add_argument(
        "--list-runtime-dead-letter-jobs",
        action="store_true",
        help="Print dead-letter-equivalent failed worker_runtime_jobs as JSON lines.",
    )
    parser.add_argument(
        "--summarize-runtime-dead-letter-jobs",
        action="store_true",
        help="Print a JSON summary of dead-letter-equivalent failed worker_runtime_jobs.",
    )
    parser.add_argument(
        "--export-runtime-queue-metrics",
        action="store_true",
        help="Print or write runtime queue final-failed row visibility metrics.",
    )
    parser.add_argument(
        "--runtime-queue-metrics-format",
        choices=("prometheus", "json"),
        default="prometheus",
        help="Output format for --export-runtime-queue-metrics. Defaults to prometheus.",
    )
    parser.add_argument(
        "--runtime-queue-metrics-path",
        help="Optional textfile path for Prometheus output from --export-runtime-queue-metrics.",
    )
    parser.add_argument(
        "--dead-letter-queue-name",
        help="Optional queue_name filter for --list-runtime-dead-letter-jobs.",
    )
    parser.add_argument(
        "--dead-letter-limit",
        type=int,
        default=100,
        help="Maximum dead-letter-equivalent jobs to print. Defaults to 100.",
    )
    parser.add_argument(
        "--requeue-runtime-job",
        metavar="JOB_ID",
        help="Requeue a failed worker_runtime_jobs row by id, resetting attempts by default.",
    )
    parser.add_argument(
        "--requeue-keep-attempts",
        action="store_true",
        help="Keep the existing attempts value for --requeue-runtime-job instead of resetting to 0.",
    )
    parser.add_argument(
        "--requeue-requested-by",
        help="Operator or automation identity required for --requeue-runtime-job audit.",
    )
    parser.add_argument(
        "--requeue-reason",
        help="Short operator reason required for --requeue-runtime-job audit.",
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
        "--query-heat-created-at-start",
        type=_parse_query_heat_datetime,
        help="Inclusive ISO-8601 created_at lower bound for --aggregate-query-heat.",
    )
    parser.add_argument(
        "--query-heat-created-at-end",
        type=_parse_query_heat_datetime,
        help="Exclusive ISO-8601 created_at upper bound for --aggregate-query-heat.",
    )
    parser.add_argument(
        "--query-heat-retention-days",
        type=int,
        help="Prune query_heat_buckets older than this many days after aggregation.",
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
        help=(
            "Optional positive row limit for --refresh-tile-features. "
            f"Maintenance default: {DEFAULT_TILE_FEATURE_LIMIT}."
        ),
    )
    parser.add_argument(
        "--tile-prune-limit",
        type=int,
        help=f"Positive per-table row limit for maintenance tile expired pruning. "
        f"Default: {DEFAULT_TILE_PRUNE_LIMIT}.",
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
        help=(
            "Persist supported worker output to Postgres staging, ingestion runs, "
            "and evidence."
        ),
    )
    parser.add_argument(
        "--database-url",
        help=(
            "Postgres URL for DB-backed commands. Defaults to "
            "WORKER_DATABASE_URL/DATABASE_URL."
        ),
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

    if args.rehearse_gdelt_news_backfill:
        return _rehearse_gdelt_news_backfill(args=args, settings=settings)

    if args.list_runtime_dead_letter_jobs:
        return _list_runtime_dead_letter_jobs(
            settings=settings,
            database_url=args.database_url,
            queue_name=args.dead_letter_queue_name,
            limit=args.dead_letter_limit,
        )

    if args.summarize_runtime_dead_letter_jobs:
        return _summarize_runtime_dead_letter_jobs(
            settings=settings,
            database_url=args.database_url,
            queue_name=args.dead_letter_queue_name,
        )

    if args.export_runtime_queue_metrics:
        return _export_runtime_queue_metrics(
            settings=settings,
            database_url=args.database_url,
            queue_name=args.dead_letter_queue_name,
            output_format=args.runtime_queue_metrics_format,
            metrics_path=args.runtime_queue_metrics_path,
        )

    if args.requeue_runtime_job:
        return _requeue_runtime_job(
            settings=settings,
            database_url=args.database_url,
            job_id=args.requeue_runtime_job,
            reset_attempts=not args.requeue_keep_attempts,
            requested_by=args.requeue_requested_by,
            reason=args.requeue_reason,
        )

    if args.work_runtime_queue:
        return _work_runtime_queue(
            settings=settings,
            once=args.once,
            max_ticks=args.max_ticks,
            persist=args.persist,
            database_url=args.database_url,
        )

    if args.enqueue_runtime_jobs:
        return _enqueue_runtime_jobs(
            settings=settings,
            scheduler=args.scheduler,
            once=args.once,
            max_ticks=args.max_ticks,
        )

    if args.maintenance:
        return _run_maintenance(
            settings=settings,
            scheduler=args.scheduler,
            once=args.once,
            max_ticks=args.max_ticks,
            periods=_parse_query_heat_periods(args.query_heat_periods),
            retention_days=args.query_heat_retention_days,
            tile_layer_id=args.tile_layer_id,
            tile_feature_limit=args.tile_feature_limit,
            tile_prune_limit=args.tile_prune_limit,
        )

    if args.aggregate_query_heat:
        return _aggregate_query_heat(
            settings=settings,
            periods=_parse_query_heat_periods(args.query_heat_periods),
            created_at_start=args.query_heat_created_at_start,
            created_at_end=args.query_heat_created_at_end,
            retention_days=args.query_heat_retention_days,
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
        if args.persist:
            return _run_managed_enabled_adapters(
                settings=settings,
                database_url=args.database_url,
            )
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


def _rehearse_gdelt_news_backfill(
    *,
    args: argparse.Namespace,
    settings: WorkerSettings,
) -> int:
    if args.gdelt_start is None or args.gdelt_end is None:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "reason": "missing_bounded_window",
                    "message": "--gdelt-start and --gdelt-end are required",
                },
                sort_keys=True,
            )
        )
        return 1
    if args.gdelt_start >= args.gdelt_end:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "reason": "invalid_bounded_window",
                    "message": "--gdelt-start must be earlier than --gdelt-end",
                },
                sort_keys=True,
            )
        )
        return 1

    env_queries = env_list(os.environ, "GDELT_REHEARSAL_QUERIES")
    queries = tuple(args.gdelt_query or ()) or env_queries
    max_records = (
        args.gdelt_max_records
        if args.gdelt_max_records is not None
        else env_int(
            os.environ,
            "GDELT_REHEARSAL_MAX_RECORDS_PER_QUERY",
            default=DEFAULT_GDELT_REHEARSAL_MAX_RECORDS_PER_QUERY,
        )
    )
    cadence_seconds = args.gdelt_cadence_seconds
    if cadence_seconds is None:
        cadence_seconds = env_int(
            os.environ,
            "GDELT_REHEARSAL_CADENCE_SECONDS",
            default=DEFAULT_GDELT_REHEARSAL_CADENCE_SECONDS,
        )

    config = HistoricalNewsBackfillConfig(
        start_datetime=args.gdelt_start,
        end_datetime=args.gdelt_end,
        fetched_at=datetime.now(UTC),
        queries=queries if queries is not None else DEFAULT_TAIWAN_FLOOD_NEWS_QUERIES,
        max_records_per_query=max_records,
        request_cadence_seconds=cadence_seconds,
        gdelt_source_enabled=args.gdelt_source_enabled
        or env_flag(os.environ, "GDELT_SOURCE_ENABLED"),
        gdelt_backfill_enabled=args.gdelt_backfill_enabled
        or env_flag(os.environ, "GDELT_BACKFILL_ENABLED"),
        source_news_enabled=settings.source_news_enabled is True,
        source_terms_review_ack=settings.source_terms_review_ack,
    )

    try:
        result = run_historical_news_backfill_rehearsal(
            config,
            mode=args.gdelt_rehearsal_mode,
        )
    except RuntimeError as exc:
        print(
            json.dumps(
                {
                    "status": "skipped",
                    "reason": str(exc),
                    "network_allowed": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except ValueError as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "reason": str(exc),
                },
                sort_keys=True,
            )
        )
        return 1

    print(json.dumps(result.as_payload(), sort_keys=True))
    return 0


def _build_runtime_persistence_writers(
    settings: WorkerSettings,
    *,
    database_url: str | None = None,
) -> DemoPersistenceWriters:
    resolved_database_url = database_url or settings.database_url
    if not resolved_database_url:
        raise SystemExit(
            "--persist requires --database-url, WORKER_DATABASE_URL, or DATABASE_URL"
        )

    staging_writer, run_writer, promotion_writer = build_runtime_persistence_writers(
        resolved_database_url
    )
    return DemoPersistenceWriters(
        staging_writer=staging_writer,
        run_writer=run_writer,
        promotion_writer=promotion_writer,
    )


def _work_runtime_queue(
    *,
    settings: WorkerSettings,
    once: bool,
    max_ticks: int | None,
    persist: bool,
    database_url: str | None,
) -> int:
    tick_limit = 1 if once else max(1, max_ticks) if max_ticks is not None else None
    persistence = (
        _build_runtime_persistence_writers(settings, database_url=database_url)
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


def _run_managed_enabled_adapters(
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


def _enqueue_runtime_jobs(
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


def _list_runtime_dead_letter_jobs(
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


def _summarize_runtime_dead_letter_jobs(
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


def _export_runtime_queue_metrics(
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
            oldest_final_failed_at=None,
        ),
    )


def _requeue_runtime_job(
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


def _run_maintenance(
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


def _aggregate_query_heat(
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


def _parse_query_heat_periods(raw: str) -> tuple[str, ...]:
    periods = tuple(dict.fromkeys(part.strip() for part in raw.split(",") if part.strip()))
    return periods or SUPPORTED_QUERY_HEAT_PERIODS


def _parse_query_heat_datetime(raw: str) -> datetime:
    normalized = f"{raw[:-1]}+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "query heat timestamps must be valid ISO-8601 datetimes"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("query heat timestamps must include a timezone")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
