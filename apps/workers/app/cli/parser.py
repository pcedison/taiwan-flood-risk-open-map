"""Argument parser for the worker CLI entrypoint."""

from __future__ import annotations

import argparse
from datetime import datetime

from app.jobs.historical_news_backfill import (
    DEFAULT_GDELT_REHEARSAL_CADENCE_SECONDS,
    DEFAULT_GDELT_REHEARSAL_MAX_RECORDS_PER_QUERY,
)
from app.jobs.query_heat import SUPPORTED_QUERY_HEAT_PERIODS
from app.scheduler import DEFAULT_TILE_FEATURE_LIMIT, DEFAULT_TILE_PRUNE_LIMIT


def build_parser() -> argparse.ArgumentParser:
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
    return parser


def parse_query_heat_periods(raw: str) -> tuple[str, ...]:
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
