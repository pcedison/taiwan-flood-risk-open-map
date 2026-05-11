from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.adapters.registry import enabled_adapter_keys
from app.config import WorkerSettings, env_flag, env_int, env_list, env_str, load_worker_settings
from app.jobs.historical_news_backfill import (
    DEFAULT_GDELT_REHEARSAL_CADENCE_SECONDS,
    DEFAULT_GDELT_REHEARSAL_MAX_RECORDS_PER_QUERY,
    DEFAULT_TAIWAN_FLOOD_NEWS_QUERIES,
    HistoricalNewsBackfillConfig,
    ensure_historical_news_backfill_production_candidate_gates,
    run_historical_news_backfill_production_candidate,
    run_historical_news_backfill_rehearsal,
)
from app.adapters.news.public_web import GdeltQueryPlace
from app.jobs.official_demo import build_official_demo_adapters
from app.jobs.profiles import (
    ProfileRefreshJobUnavailable,
    claim_profile_refresh_jobs,
    complete_profile_refresh_job,
    rebuild_risk_profile,
    seed_admin_area_profiles_from_geocoder,
    seed_grid_profiles_from_query_heat,
)
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
from app.jobs.taiwan_news_query_plan import (
    DEFAULT_TERMS_PER_QUERY,
    TaiwanQueryScope,
    build_taiwan_flood_news_queries,
    load_taiwan_geocoder_query_places,
)
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
        "--run-gdelt-news-production-candidate",
        action="store_true",
        help=(
            "Run the bounded GDELT public-news production-candidate path. "
            "Requires --persist, a database URL, source gates, "
            "GDELT_PRODUCTION_INGESTION_ENABLED, approval evidence, and "
            "an explicit approval acknowledgement."
        ),
    )
    parser.add_argument(
        "--validate-gdelt-live-acceptance",
        metavar="YAML",
        help=(
            "No-network preflight for GDELT live acceptance evidence. "
            "Prints JSON and never opens the live ingestion path."
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
        help="Open the GDELT-specific source gate for this command only.",
    )
    parser.add_argument(
        "--gdelt-backfill-enabled",
        action="store_true",
        help="Open the GDELT backfill gate for this command only.",
    )
    parser.add_argument(
        "--gdelt-production-enabled",
        action="store_true",
        help="Open GDELT_PRODUCTION_INGESTION_ENABLED for this candidate command only.",
    )
    parser.add_argument(
        "--gdelt-approval-evidence-path",
        help=(
            "Path to external GDELT production-candidate approval evidence. "
            "Can also be supplied with GDELT_PRODUCTION_APPROVAL_EVIDENCE_PATH."
        ),
    )
    parser.add_argument(
        "--gdelt-approval-evidence-ack",
        action="store_true",
        help=(
            "Acknowledge external GDELT production-candidate approval evidence for this "
            "command only. Required with the approval evidence path; does not replace "
            "legal/source approval records."
        ),
    )
    parser.add_argument(
        "--gdelt-promotion-limit",
        type=int,
        help="Optional cap for GDELT production-candidate evidence promotion.",
    )
    parser.add_argument(
        "--gdelt-start",
        type=_parse_query_heat_datetime,
        help="Inclusive ISO-8601 start timestamp for bounded GDELT run.",
    )
    parser.add_argument(
        "--gdelt-end",
        type=_parse_query_heat_datetime,
        help="Exclusive ISO-8601 end timestamp for bounded GDELT run.",
    )
    parser.add_argument(
        "--gdelt-query",
        action="append",
        help=(
            "Override default Taiwan flood-news queries. May be supplied multiple times. "
            "GDELT_REHEARSAL_QUERIES or GDELT_PRODUCTION_QUERIES can also provide "
            "comma-separated queries for their respective commands."
        ),
    )
    parser.add_argument(
        "--gdelt-geocoder-term-path",
        action="append",
        help=(
            "Load Taiwan geocoder JSONL/JSONL.GZ terms for a controlled GDELT query plan. "
            "May be supplied multiple times; env: GDELT_GEOCODER_TERM_PATHS."
        ),
    )
    parser.add_argument(
        "--gdelt-geocoder-scopes",
        help=(
            "Comma-separated geocoder scopes for query planning: village,road,town,county. "
            "Defaults to GDELT_GEOCODER_SCOPES when set."
        ),
    )
    parser.add_argument(
        "--gdelt-geocoder-term-limit",
        type=int,
        help="Optional cap on loaded geocoder terms before query chunking.",
    )
    parser.add_argument(
        "--gdelt-geocoder-terms-per-query",
        type=int,
        help="How many place terms to OR into one GDELT query. Defaults to 8.",
    )
    parser.add_argument(
        "--gdelt-query-offset",
        type=int,
        help="Skip this many generated GDELT queries for resumable shards.",
    )
    parser.add_argument(
        "--gdelt-query-limit",
        type=int,
        help="Run at most this many generated GDELT queries for resumable shards.",
    )
    parser.add_argument(
        "--gdelt-require-geocoder-match",
        action="store_true",
        help=(
            "When geocoder terms are loaded, only normalize articles whose title matches "
            "one of those controlled village/road terms."
        ),
    )
    parser.add_argument(
        "--gdelt-progress-log-interval",
        type=int,
        help="Emit metadata-only JSON progress logs every N GDELT query batches.",
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
        "--seed-risk-profiles",
        action="store_true",
        help="Seed stale precomputed admin-area and grid profile shards.",
    )
    parser.add_argument(
        "--seed-profile-kind",
        choices=("admin_area", "risk_grid", "all"),
        default="all",
        help="Profile kind for --seed-risk-profiles. Defaults to all.",
    )
    parser.add_argument(
        "--profile-seed-source-key",
        default="moi-village-boundary-twd97-geographic",
        help="Geocoder source key for admin-area profile seeding.",
    )
    parser.add_argument(
        "--profile-seed-limit",
        type=int,
        help="Optional positive limit for each profile seed source.",
    )
    parser.add_argument(
        "--profile-grid-system",
        choices=("h3", "geohash"),
        default="h3",
        help="Grid system label for query-heat profile seeding. Defaults to h3.",
    )
    parser.add_argument(
        "--profile-grid-resolution",
        default="8",
        help="Grid resolution label for query-heat profile seeding. Defaults to 8.",
    )
    parser.add_argument(
        "--profile-include-privacy-bucket-fallback",
        action="store_true",
        help="Allow location_queries.privacy_bucket to seed local grid profiles when h3_index is absent.",
    )
    parser.add_argument(
        "--profile-no-enqueue-refresh",
        action="store_true",
        help="Seed profiles without enqueuing profile_refresh_jobs.",
    )
    parser.add_argument(
        "--rebuild-risk-profile",
        action="store_true",
        help="Rebuild one precomputed profile identified by --profile-kind and --profile-key.",
    )
    parser.add_argument(
        "--profile-kind",
        choices=("admin_area", "risk_grid"),
        help="Profile kind for --rebuild-risk-profile.",
    )
    parser.add_argument(
        "--profile-key",
        help="Profile key for --rebuild-risk-profile.",
    )
    parser.add_argument(
        "--work-profile-refresh-jobs",
        action="store_true",
        help="Claim and rebuild queued profile_refresh_jobs.",
    )
    parser.add_argument(
        "--profile-refresh-limit",
        type=int,
        default=1,
        help="Maximum profile refresh jobs to claim in one worker tick. Defaults to 1.",
    )
    parser.add_argument(
        "--profile-refresh-worker-id",
        help="Worker identity for profile_refresh_jobs leases.",
    )
    parser.add_argument(
        "--profile-refresh-lease-seconds",
        type=int,
        default=300,
        help="Lease seconds for --work-profile-refresh-jobs. Defaults to 300.",
    )
    parser.add_argument(
        "--profile-refresh-statement-timeout-ms",
        type=int,
        default=15000,
        help=(
            "Per-profile rebuild statement timeout in milliseconds. "
            "Defaults to 15000 to keep hosted PostGIS responsive."
        ),
    )
    parser.add_argument(
        "--profile-refresh-cooldown-seconds",
        type=int,
        default=0,
        help="Seconds to sleep between claimed profile refresh jobs. Defaults to 0.",
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

    if args.run_gdelt_news_production_candidate:
        return _run_gdelt_news_production_candidate(args=args, settings=settings)

    if args.validate_gdelt_live_acceptance:
        from app.jobs.gdelt_live_acceptance import (
            render_gdelt_live_acceptance_json,
            validate_gdelt_live_acceptance_file,
        )

        gdelt_acceptance = validate_gdelt_live_acceptance_file(
            Path(args.validate_gdelt_live_acceptance)
        )
        print(render_gdelt_live_acceptance_json(gdelt_acceptance))
        return 1 if gdelt_acceptance.status == "failed" else 0

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

    if args.seed_risk_profiles:
        return _seed_risk_profiles(
            settings=settings,
            database_url=args.database_url,
            profile_kind=args.seed_profile_kind,
            source_key=args.profile_seed_source_key,
            limit=args.profile_seed_limit,
            grid_system=args.profile_grid_system,
            grid_resolution=args.profile_grid_resolution,
            include_privacy_bucket_fallback=args.profile_include_privacy_bucket_fallback,
            enqueue_refresh=not args.profile_no_enqueue_refresh,
        )

    if args.rebuild_risk_profile:
        return _rebuild_one_risk_profile(
            settings=settings,
            database_url=args.database_url,
            profile_kind=args.profile_kind,
            profile_key=args.profile_key,
        )

    if args.work_profile_refresh_jobs:
        return _work_profile_refresh_jobs(
            settings=settings,
            database_url=args.database_url,
            worker_id=args.profile_refresh_worker_id,
            limit=args.profile_refresh_limit,
            lease_seconds=args.profile_refresh_lease_seconds,
            statement_timeout_ms=args.profile_refresh_statement_timeout_ms,
            cooldown_seconds=args.profile_refresh_cooldown_seconds,
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


def _build_gdelt_news_backfill_config(
    *,
    args: argparse.Namespace,
    settings: WorkerSettings,
    fetched_at: datetime,
    production_database_url: str | None = None,
) -> HistoricalNewsBackfillConfig:
    is_production_candidate = bool(
        getattr(args, "run_gdelt_news_production_candidate", False)
    )
    query_env_name = (
        "GDELT_PRODUCTION_QUERIES"
        if is_production_candidate
        else "GDELT_REHEARSAL_QUERIES"
    )
    max_records_env_name = (
        "GDELT_PRODUCTION_MAX_RECORDS_PER_QUERY"
        if is_production_candidate
        else "GDELT_REHEARSAL_MAX_RECORDS_PER_QUERY"
    )
    cadence_env_name = (
        "GDELT_PRODUCTION_CADENCE_SECONDS"
        if is_production_candidate
        else "GDELT_REHEARSAL_CADENCE_SECONDS"
    )

    env_queries = env_list(os.environ, query_env_name)
    queries = tuple(args.gdelt_query or ()) or env_queries
    query_places, query_plan_metadata = _build_gdelt_geocoder_query_plan(args)
    if not queries and query_places:
        generated_queries = build_taiwan_flood_news_queries(
            (place.term for place in query_places),
            terms_per_query=_positive_int(
                args.gdelt_geocoder_terms_per_query
                or env_int(
                    os.environ,
                    "GDELT_GEOCODER_TERMS_PER_QUERY",
                    default=DEFAULT_TERMS_PER_QUERY,
                ),
                default=DEFAULT_TERMS_PER_QUERY,
            ),
        )
        queries = _slice_generated_queries(
            generated_queries,
            offset=args.gdelt_query_offset
            if args.gdelt_query_offset is not None
            else env_int(os.environ, "GDELT_QUERY_OFFSET", default=0),
            limit=args.gdelt_query_limit
            if args.gdelt_query_limit is not None
            else env_int(os.environ, "GDELT_QUERY_LIMIT", default=0),
        )
        query_plan_metadata = {
            **query_plan_metadata,
            "generated_query_count_total": len(generated_queries),
            "generated_query_offset": max(
                0,
                args.gdelt_query_offset
                if args.gdelt_query_offset is not None
                else env_int(os.environ, "GDELT_QUERY_OFFSET", default=0),
            ),
            "generated_query_limit": (
                args.gdelt_query_limit
                if args.gdelt_query_limit is not None
                else env_int(os.environ, "GDELT_QUERY_LIMIT", default=0)
            )
            or None,
        }
    max_records = (
        args.gdelt_max_records
        if args.gdelt_max_records is not None
        else env_int(
            os.environ,
            max_records_env_name,
            default=DEFAULT_GDELT_REHEARSAL_MAX_RECORDS_PER_QUERY,
        )
    )
    cadence_seconds = args.gdelt_cadence_seconds
    if cadence_seconds is None:
        cadence_seconds = env_int(
            os.environ,
            cadence_env_name,
            default=DEFAULT_GDELT_REHEARSAL_CADENCE_SECONDS,
        )

    return HistoricalNewsBackfillConfig(
        start_datetime=args.gdelt_start,
        end_datetime=args.gdelt_end,
        fetched_at=fetched_at,
        queries=queries if queries is not None else DEFAULT_TAIWAN_FLOOD_NEWS_QUERIES,
        max_records_per_query=max_records,
        request_cadence_seconds=cadence_seconds,
        gdelt_source_enabled=args.gdelt_source_enabled
        or env_flag(os.environ, "GDELT_SOURCE_ENABLED"),
        gdelt_backfill_enabled=args.gdelt_backfill_enabled
        or env_flag(os.environ, "GDELT_BACKFILL_ENABLED"),
        source_news_enabled=settings.source_news_enabled is True,
        source_terms_review_ack=settings.source_terms_review_ack,
        gdelt_production_ingestion_enabled=args.gdelt_production_enabled
        or env_flag(os.environ, "GDELT_PRODUCTION_INGESTION_ENABLED"),
        gdelt_production_approval_evidence_path=args.gdelt_approval_evidence_path
        or env_str(os.environ, "GDELT_PRODUCTION_APPROVAL_EVIDENCE_PATH"),
        gdelt_production_approval_evidence_ack=args.gdelt_approval_evidence_ack
        or env_flag(os.environ, "GDELT_PRODUCTION_APPROVAL_EVIDENCE_ACK"),
        production_persist_intent=args.persist,
        production_database_url=production_database_url,
        query_places=query_places,
        require_query_place_match=args.gdelt_require_geocoder_match
        or env_flag(os.environ, "GDELT_REQUIRE_GEOCODER_MATCH"),
        progress_log_interval=args.gdelt_progress_log_interval
        if args.gdelt_progress_log_interval is not None
        else env_int(os.environ, "GDELT_PROGRESS_LOG_INTERVAL", default=0),
        query_plan_metadata=query_plan_metadata,
    )


def _build_gdelt_geocoder_query_plan(
    args: argparse.Namespace,
) -> tuple[tuple[GdeltQueryPlace, ...], dict[str, object]]:
    raw_paths = tuple(args.gdelt_geocoder_term_path or ()) or env_list(
        os.environ,
        "GDELT_GEOCODER_TERM_PATHS",
    )
    if not raw_paths:
        return (), {}

    scopes = _parse_gdelt_geocoder_scopes(
        args.gdelt_geocoder_scopes
        or os.environ.get("GDELT_GEOCODER_SCOPES")
        or "village,road"
    )
    term_limit = (
        args.gdelt_geocoder_term_limit
        if args.gdelt_geocoder_term_limit is not None
        else env_int(os.environ, "GDELT_GEOCODER_TERM_LIMIT", default=0)
    )
    loaded_places = load_taiwan_geocoder_query_places(
        raw_paths,
        scopes=scopes,
        limit=term_limit if term_limit and term_limit > 0 else None,
    )
    query_places = tuple(
        GdeltQueryPlace(
            term=place.term,
            lat=place.lat,
            lng=place.lng,
            scope=place.scope,
            canonical_name=place.canonical_name,
            precision=place.precision,
            source_key=place.source_key,
            source_record_id=place.source_record_id,
        )
        for place in loaded_places
    )
    return query_places, {
        "geocoder_query_plan": True,
        "geocoder_term_paths": tuple(str(path) for path in raw_paths),
        "geocoder_scopes": scopes,
        "geocoder_term_limit": term_limit or None,
        "geocoder_query_place_count_total": len(query_places),
    }


def _parse_gdelt_geocoder_scopes(raw: str) -> tuple[TaiwanQueryScope, ...]:
    allowed: set[TaiwanQueryScope] = {"county", "town", "village", "road"}
    scopes: list[TaiwanQueryScope] = []
    for part in raw.replace("\n", ",").split(","):
        scope = part.strip().lower()
        if scope in allowed and scope not in scopes:
            scopes.append(scope)  # type: ignore[arg-type]
    return tuple(scopes) or ("village", "road")


def _slice_generated_queries(
    queries: tuple[str, ...],
    *,
    offset: int,
    limit: int,
) -> tuple[str, ...]:
    start = max(0, offset)
    if limit and limit > 0:
        return queries[start : start + limit]
    return queries[start:]


def _positive_int(value: int, *, default: int) -> int:
    return value if value > 0 else default


def _validate_gdelt_bounded_window(args: argparse.Namespace) -> int | None:
    if args.gdelt_start is None or args.gdelt_end is None:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "reason": "missing_bounded_window",
                    "message": "--gdelt-start and --gdelt-end are required",
                    "network_allowed": False,
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
                    "network_allowed": False,
                },
                sort_keys=True,
            )
        )
        return 1
    return None


def _rehearse_gdelt_news_backfill(
    *,
    args: argparse.Namespace,
    settings: WorkerSettings,
) -> int:
    window_exit_code = _validate_gdelt_bounded_window(args)
    if window_exit_code is not None:
        return window_exit_code

    config = _build_gdelt_news_backfill_config(
        args=args,
        settings=settings,
        fetched_at=datetime.now(UTC),
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


def _run_gdelt_news_production_candidate(
    *,
    args: argparse.Namespace,
    settings: WorkerSettings,
) -> int:
    window_exit_code = _validate_gdelt_bounded_window(args)
    if window_exit_code is not None:
        return window_exit_code
    if args.gdelt_promotion_limit is not None and args.gdelt_promotion_limit < 1:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "reason": "invalid_promotion_limit",
                    "message": "--gdelt-promotion-limit must be greater than 0",
                    "network_allowed": False,
                },
                sort_keys=True,
            )
        )
        return 1

    resolved_database_url = args.database_url or settings.database_url
    config = _build_gdelt_news_backfill_config(
        args=args,
        settings=settings,
        fetched_at=datetime.now(UTC),
        production_database_url=resolved_database_url,
    )

    try:
        ensure_historical_news_backfill_production_candidate_gates(config)
    except RuntimeError as exc:
        print(
            json.dumps(
                {
                    "status": "skipped",
                    "mode": "production-candidate",
                    "reason": str(exc),
                    "network_allowed": False,
                },
                sort_keys=True,
            )
        )
        return 0

    persistence = _build_demo_persistence_writers(
        settings,
        database_url=args.database_url,
    )
    try:
        result = run_historical_news_backfill_production_candidate(
            config,
            staging_writer=persistence.staging_writer,
            run_writer=persistence.run_writer,
            promotion_writer=persistence.promotion_writer,
            promotion_limit=args.gdelt_promotion_limit,
        )
    except RuntimeError as exc:
        print(
            json.dumps(
                {
                    "status": "skipped",
                    "mode": "production-candidate",
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
                    "mode": "production-candidate",
                    "reason": str(exc),
                },
                sort_keys=True,
            )
        )
        return 1

    print(json.dumps(result.as_payload(), sort_keys=True))
    return 1 if result.failed else 0


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


def _seed_risk_profiles(
    *,
    settings: WorkerSettings,
    database_url: str | None,
    profile_kind: str,
    source_key: str,
    limit: int | None,
    grid_system: str,
    grid_resolution: str,
    include_privacy_bucket_fallback: bool,
    enqueue_refresh: bool,
) -> int:
    resolved_database_url = database_url or settings.database_url
    if limit is not None and limit < 1:
        log_event("profiles.seed.failed", error="profile seed limit must be positive")
        return 1
    if not resolved_database_url:
        log_event("profiles.seed.noop", reason="no_database_url")
        return 0

    summaries = []
    try:
        if profile_kind in {"admin_area", "all"}:
            summaries.append(
                seed_admin_area_profiles_from_geocoder(
                    database_url=resolved_database_url,
                    source_key=source_key,
                    limit=limit,
                    enqueue_refresh=enqueue_refresh,
                )
            )
        if profile_kind in {"risk_grid", "all"}:
            summaries.append(
                seed_grid_profiles_from_query_heat(
                    database_url=resolved_database_url,
                    grid_system=grid_system,
                    grid_resolution=grid_resolution,
                    limit=limit,
                    include_privacy_bucket_fallback=include_privacy_bucket_fallback,
                    enqueue_refresh=enqueue_refresh,
                )
            )
    except (ProfileRefreshJobUnavailable, ValueError) as exc:
        log_event("profiles.seed.failed", error=str(exc))
        return 1

    payload = {
        "profile_seed": [
            {
                "profile_kind": summary.profile_kind,
                "seeded": summary.seeded,
                "refresh_jobs_enqueued": summary.refresh_jobs_enqueued,
                "source": summary.source,
            }
            for summary in summaries
        ]
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    log_event("profiles.seed.completed", summaries=payload["profile_seed"])
    return 0


def _rebuild_one_risk_profile(
    *,
    settings: WorkerSettings,
    database_url: str | None,
    profile_kind: str | None,
    profile_key: str | None,
) -> int:
    resolved_database_url = database_url or settings.database_url
    if not resolved_database_url:
        log_event("profiles.rebuild.noop", reason="no_database_url")
        return 0
    if not profile_kind or not profile_key:
        log_event("profiles.rebuild.failed", error="--profile-kind and --profile-key are required")
        return 1

    try:
        summary = rebuild_risk_profile(
            database_url=resolved_database_url,
            profile_kind=profile_kind,
            profile_key=profile_key,
        )
    except (ProfileRefreshJobUnavailable, ValueError) as exc:
        log_event("profiles.rebuild.failed", error=str(exc))
        return 1

    if summary is None:
        print(
            json.dumps(
                {
                    "profile_rebuild": {
                        "profile_kind": profile_kind,
                        "profile_key": profile_key,
                        "status": "missing",
                    }
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1

    print(
        json.dumps(
            {
                "profile_rebuild": {
                    "profile_kind": summary.profile_kind,
                    "profile_key": summary.profile_key,
                    "evidence_count": summary.evidence_count,
                    "top_evidence_ids": summary.top_evidence_ids,
                    "realtime_level": summary.realtime_level,
                    "historical_level": summary.historical_level,
                    "confidence_level": summary.confidence_level,
                    "computed_at": summary.computed_at.isoformat(),
                    "status": "succeeded",
                }
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _work_profile_refresh_jobs(
    *,
    settings: WorkerSettings,
    database_url: str | None,
    worker_id: str | None,
    limit: int,
    lease_seconds: int,
    statement_timeout_ms: int,
    cooldown_seconds: int,
) -> int:
    resolved_database_url = database_url or settings.database_url
    if limit < 1:
        log_event("profiles.refresh.failed", error="profile refresh limit must be positive")
        return 1
    if lease_seconds < 1:
        log_event("profiles.refresh.failed", error="profile refresh lease seconds must be positive")
        return 1
    if statement_timeout_ms < 1:
        log_event("profiles.refresh.failed", error="profile refresh statement timeout must be positive")
        return 1
    if cooldown_seconds < 0:
        log_event("profiles.refresh.failed", error="profile refresh cooldown cannot be negative")
        return 1
    if not resolved_database_url:
        log_event("profiles.refresh.noop", reason="no_database_url")
        return 0

    resolved_worker_id = worker_id or f"profile-worker:{settings.metrics_instance}"
    try:
        jobs = claim_profile_refresh_jobs(
            database_url=resolved_database_url,
            worker_id=resolved_worker_id,
            limit=limit,
            lease_seconds=lease_seconds,
        )
    except ProfileRefreshJobUnavailable as exc:
        log_event("profiles.refresh.claim_failed", error=str(exc))
        return 1

    results: list[dict[str, object]] = []
    for index, job in enumerate(jobs):
        if index > 0 and cooldown_seconds > 0:
            time.sleep(cooldown_seconds)
        try:
            summary = rebuild_risk_profile(
                database_url=resolved_database_url,
                profile_kind=job.profile_kind,
                profile_key=job.profile_key,
                statement_timeout_ms=statement_timeout_ms,
            )
            if summary is None:
                complete_profile_refresh_job(
                    database_url=resolved_database_url,
                    job_id=job.id,
                    status="skipped",
                    error_message=None,
                )
                results.append(
                    {
                        "job_id": job.id,
                        "profile_kind": job.profile_kind,
                        "profile_key": job.profile_key,
                        "status": "skipped",
                        "reason": "profile_missing",
                    }
                )
                continue
            complete_profile_refresh_job(
                database_url=resolved_database_url,
                job_id=job.id,
                status="succeeded",
                error_message=None,
            )
            results.append(
                {
                    "job_id": job.id,
                    "profile_kind": summary.profile_kind,
                    "profile_key": summary.profile_key,
                    "status": "succeeded",
                    "evidence_count": summary.evidence_count,
                    "historical_level": summary.historical_level,
                    "realtime_level": summary.realtime_level,
                }
            )
        except (ProfileRefreshJobUnavailable, ValueError) as exc:
            try:
                complete_profile_refresh_job(
                    database_url=resolved_database_url,
                    job_id=job.id,
                    status="failed",
                    error_message=str(exc),
                )
            except ProfileRefreshJobUnavailable:
                pass
            results.append(
                {
                    "job_id": job.id,
                    "profile_kind": job.profile_kind,
                    "profile_key": job.profile_key,
                    "status": "failed",
                    "error": str(exc),
                }
            )

    print(json.dumps({"profile_refresh_jobs": results}, ensure_ascii=False, sort_keys=True))
    return 1 if any(result["status"] == "failed" for result in results) else 0


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
