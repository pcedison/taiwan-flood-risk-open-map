# Flood Risk Workers

Worker ingestion groundwork for official/L2 sources, plus scheduler/sample
smoke paths.

## Current operations status

Completed for local/runtime smoke:

- Postgres-backed `worker_runtime_jobs` and `worker_scheduler_leases` tables.
- Queue producer and consumer CLIs for enabled runtime adapter jobs.
- Row-level dequeue locking, worker leases, expired lease recovery, and retry
  to terminal `failed` status after `max_attempts`.
- Deterministic runtime queue `dedupe_key` handling for active producer jobs
  and `final_failed_at` visibility for exhausted retries.
- Bounded scheduler and queue producer paths that can acquire the DB scheduler
  lease when a database URL is configured.
- Manual query heat aggregation/retention, `flood-potential` tile feature
  refresh commands, and a bounded Query Heat/tile cache maintenance scheduler
  tick.
- Opt-in worker and scheduler heartbeat textfile metrics.

Partially complete, not production-ready:

- Active producer dedupe is scoped to runtime adapter queue/job/adapter rows.
  It is not a complete production idempotency contract for all job side effects
  or future job families.
- Exhausted jobs remain in `worker_runtime_jobs` with `status='failed'`; there
  is dead-letter-equivalent visibility through `final_failed_at`, but no
  dedicated DLQ table, replay command, or poison-job routing policy yet.
- Runtime adapter execution is still fixture-backed unless
  `WORKER_RUNTIME_FIXTURES_ENABLED=true` is set. Reviewed real source clients
  and credentials are pending.
- `python -m app.scheduler` without flags is a placeholder maintenance/sample
  loop. Production deployment cadence for ingestion, query heat, tile cache,
  freshness export, and operator ownership is still pending.
- Heartbeat metrics are written only when `WORKER_METRICS_TEXTFILE_PATH` or
  `SCHEDULER_METRICS_TEXTFILE_PATH` is set and a node exporter textfile
  collector is deployed.

## Entry points

- Single sample job: `python -m app.main --once`
- Run configured runtime adapters once:
  `WORKER_RUNTIME_FIXTURES_ENABLED=true WORKER_ENABLED_ADAPTER_KEYS=official.cwa.rainfall python -m app.main --run-enabled-adapters`
- Run configured runtime adapters on a bounded scheduler loop:
  `WORKER_RUNTIME_FIXTURES_ENABLED=true SCHEDULER_MAX_TICKS=2 python -m app.main --scheduler`
- Enqueue configured runtime adapter jobs into the durable queue:
  `WORKER_DATABASE_URL=postgresql://... WORKER_ENABLED_ADAPTER_KEYS=official.cwa.rainfall python -m app.main --enqueue-runtime-jobs`
- Enqueue configured runtime adapter jobs on a lease-guarded scheduler loop:
  `WORKER_DATABASE_URL=postgresql://... WORKER_ENABLED_ADAPTER_KEYS=official.cwa.rainfall python -m app.main --enqueue-runtime-jobs --scheduler --max-ticks 2`
- Consume one durable runtime adapter job from `worker_runtime_jobs`:
  `WORKER_RUNTIME_FIXTURES_ENABLED=true WORKER_DATABASE_URL=postgresql://... python -m app.main --work-runtime-queue --once`
- Consume durable runtime adapter jobs in a bounded worker loop:
  `WORKER_RUNTIME_FIXTURES_ENABLED=true WORKER_DATABASE_URL=postgresql://... python -m app.main --work-runtime-queue --max-ticks 2`
- Materialize Query Heat buckets:
  `WORKER_DATABASE_URL=postgresql://... python -m app.main --aggregate-query-heat --query-heat-periods P1D,P7D`
- Materialize a bounded Query Heat window and prune old buckets:
  `WORKER_DATABASE_URL=postgresql://... python -m app.main --aggregate-query-heat --query-heat-created-at-start 2026-04-23T00:00:00Z --query-heat-created-at-end 2026-04-30T00:00:00Z --query-heat-retention-days 90`
- Refresh worker-generated tile layer features:
  `WORKER_DATABASE_URL=postgresql://... python -m app.main --refresh-tile-features --tile-layer-id flood-potential`
- Run one bounded Query Heat + tile cache maintenance tick:
  `WORKER_DATABASE_URL=postgresql://... python -m app.main --scheduler --maintenance --once`
- Run a bounded maintenance cadence with explicit limits:
  `WORKER_DATABASE_URL=postgresql://... python -m app.main --scheduler --maintenance --max-ticks 2 --query-heat-periods P1D,P7D --query-heat-retention-days 90 --tile-layer-id flood-potential --tile-feature-limit 1000 --tile-prune-limit 1000`
- Official adapter demo ingestion + freshness check: `python -m app.main --run-official-demo`
- Official adapter demo with DB persistence and evidence promotion:
  `python -m app.main --run-official-demo --persist --database-url postgresql://...`
- Scheduler loop smoke path: `python -m app.scheduler`
- Scheduler runtime adapter path:
  `WORKER_RUNTIME_FIXTURES_ENABLED=true python -m app.scheduler --run-enabled-adapters --once`
- Scheduler queue producer tick:
  `WORKER_DATABASE_URL=postgresql://... WORKER_ENABLED_ADAPTER_KEYS=official.cwa.rainfall python -m app.scheduler --enqueue-runtime-jobs --once`
- Scheduler maintenance tick:
  `WORKER_DATABASE_URL=postgresql://... python -m app.scheduler --maintenance --once`
- Scheduler official demo tick: `python -m app.scheduler --official-demo --once`
- Worker heartbeat textfile metrics:
  `WORKER_METRICS_TEXTFILE_PATH=./tmp/worker.prom python -m app.main --run-enabled-adapters`
- Scheduler heartbeat textfile metrics:
  `SCHEDULER_METRICS_TEXTFILE_PATH=./tmp/scheduler.prom python -m app.main --scheduler --max-ticks 1`

## Operator command examples

These examples assume the local Compose database has migrations applied. They
are useful for smoke and debugging; they are not a production deployment plan.

```powershell
# Apply migrations in the local Compose database.
docker compose --profile tools run --rm migrate

# Producer: enqueue one durable runtime job per enabled adapter.
docker compose run --rm `
  -e WORKER_ENABLED_ADAPTER_KEYS=official.wra.water_level `
  worker sh -c "pip install -e . && python -m app.main --enqueue-runtime-jobs"

# Worker: consume one durable runtime job with fixture-backed adapters.
docker compose run --rm `
  -e WORKER_ENABLED_ADAPTER_KEYS=official.wra.water_level `
  -e WORKER_RUNTIME_FIXTURES_ENABLED=true `
  worker sh -c "pip install -e . && python -m app.main --work-runtime-queue --once"

# Scheduler producer: run one DB-lease-guarded enqueue tick.
docker compose run --rm `
  -e WORKER_ENABLED_ADAPTER_KEYS=official.wra.water_level `
  scheduler sh -c "pip install -e . && python -m app.scheduler --enqueue-runtime-jobs --once"

# Maintenance smoke: materialize and prune query heat buckets.
docker compose run --rm worker sh -c "pip install -e . && python -m app.main --aggregate-query-heat --query-heat-periods P1D,P7D --query-heat-retention-days 90"

# Maintenance smoke: refresh worker-generated flood-potential features.
docker compose run --rm worker sh -c "pip install -e . && python -m app.main --refresh-tile-features --tile-layer-id flood-potential --tile-feature-limit 25"

# Local heartbeat files for monitoring profile validation.
docker compose run --rm `
  -e WORKER_ENABLED_ADAPTER_KEYS=official.wra.water_level `
  -e WORKER_METRICS_TEXTFILE_PATH=/var/lib/node_exporter/textfile_collector/flood-risk-worker.prom `
  -e WORKER_RUNTIME_FIXTURES_ENABLED=true `
  worker sh -c "pip install -e . && python -m app.main --run-enabled-adapters"
```

The runtime adapter path is config-driven and safe by default: it selects
adapters with `WORKER_ENABLED_ADAPTER_KEYS` plus source gates, but no runtime
adapter is constructed unless `WORKER_RUNTIME_FIXTURES_ENABLED=true` opts into
local fixture-backed adapters. That makes disabled or unavailable adapters a
graceful no-op and avoids accidental calls to external APIs.
The official demo only writes to Postgres when `--persist` is supplied; the
database URL can come from `--database-url`, `WORKER_DATABASE_URL`, or
`DATABASE_URL`.
Heartbeat textfile metrics are opt-in. They are only written when
`WORKER_METRICS_TEXTFILE_PATH` or `SCHEDULER_METRICS_TEXTFILE_PATH` is set.
When `WORKER_DATABASE_URL` or `DATABASE_URL` is present, the bounded scheduler
attempts to acquire a DB-backed singleton lease before running
`--scheduler`. If the lease is held by another worker, the loop exits without
running a duplicate tick; if the DB is unavailable, it logs the failure and
falls back to the existing local safe loop. Runtime adapter jobs can also be
enqueued/dequeued through the durable `worker_runtime_jobs` table, including
expired lease recovery and succeeded/failed completion updates. The
`--enqueue-runtime-jobs` producer path selects adapters from
`WORKER_ENABLED_ADAPTER_KEYS` plus source gates, skips safely when no database
URL or no adapters are configured, and writes one durable
`runtime.adapter.ingest` job per configured adapter with the adapter key in the
payload. Producer enqueues use deterministic `dedupe_key` values, so an active
`queued` or `running` job for the same queue/job/adapter returns the existing
job id as `deduped` instead of inserting a duplicate every tick. The
`--work-runtime-queue` path safely no-ops when no database URL is configured,
when the database is unavailable, or when there is no ready job.
When a job is claimed, the worker resolves the job's `adapter_key`, runs that
single adapter through the fixture-gated ingestion/freshness path, marks the
job succeeded on success, and marks it failed with the error for unknown
adapters or failed adapter runs. Final failures are visible when a job reaches
`max_attempts` via `final_failed_at` and the dead-letter query:
`SELECT id, queue_name, job_key, adapter_key, attempts, max_attempts, last_error, final_failed_at FROM worker_runtime_jobs WHERE status = 'failed' AND attempts >= max_attempts ORDER BY COALESCE(final_failed_at, finished_at, updated_at) DESC;`
Adapter construction still remains fixture-gated by
`WORKER_RUNTIME_FIXTURES_ENABLED=true`, so no external API calls are made by
default.
The maintenance scheduler path is bounded by `--once`, `--max-ticks`, or
`SCHEDULER_MAX_TICKS`, and defaults to a single tick when no bound is supplied.
Each tick runs Query Heat aggregation, Query Heat retention pruning, tile
feature refresh, and expired tile cache/feature pruning in that order. It
skips safely when no database URL is configured. Defaults are `P1D,P7D`
periods, 90 retention days, `flood-potential`, 1000 refreshed features, and
1000 expired rows per prune table.

## Current scope

- Adapter contract and registry groundwork.
- Official CWA rainfall, WRA water-level, and flood-potential fixture parsers.
- Worker CLI/scheduler demo path for enabled official adapters.
- Configurable run-once and bounded scheduler path for enabled runtime adapters.
- DB-backed runtime job queue producer/consumer and singleton scheduler lease
  groundwork.
- DB-backed Query Heat aggregation job materializes `P1D` and `P7D` buckets
  from `location_queries` into `query_heat_buckets`, supports explicit
  `created_at` bounds for cadence/backfill windows, and can prune old
  aggregate buckets by retention age.
- Lightweight freshness checks that emit alerts for stale or failed adapter runs.
- L2 news/public-web sample adapter and source allowlist validation.
- Raw snapshot, staging, validation, promotion, and PostGIS writer groundwork.
- DB-backed `flood-potential` tile feature refresh and tile cache upsert
  helpers for production layer/cache tables.
- `WORKER_ENABLED_ADAPTER_KEYS` configuration groundwork for explicit adapter
  enablement.

## Placeholder boundary

- Runtime scheduling has durable queue/lease primitives, but adapter execution
  is still fixture-backed until production source clients are selected.
- Queue jobs have retry, active-job enqueue idempotency, and terminal
  `failed`/`final_failed_at` visibility, but a dedicated DLQ/replay policy and
  poison-job alerting are pending.
- Maintenance jobs have manual CLIs, local smoke coverage, and a bounded
  scheduler command path, but production deployment and operator ownership are
  pending.
- Tile production can now refresh feature/cache tables from worker code, but it
  does not yet generate full production MVT tiles or manage cache invalidation.
- PTT and Dcard adapters are phase-delayed and must remain disabled until legal
  and privacy review work lands. Future PRs must satisfy
  `docs/privacy/public-discussion-user-report-gates.md` before enabling them.
- User report ingestion is pending Phase 5 governance/API implementation and
  must satisfy `docs/privacy/public-discussion-user-report-gates.md` before any
  public intake path is enabled.
