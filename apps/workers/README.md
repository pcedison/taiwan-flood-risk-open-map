# Flood Risk Workers

Worker ingestion groundwork for official/L2 sources, plus scheduler/sample
smoke paths.

## Entry points

- Single sample job: `python -m app.main --once`
- Run configured runtime adapters once:
  `WORKER_RUNTIME_FIXTURES_ENABLED=true WORKER_ENABLED_ADAPTER_KEYS=official.cwa.rainfall python -m app.main --run-enabled-adapters`
- Run configured runtime adapters on a bounded scheduler loop:
  `WORKER_RUNTIME_FIXTURES_ENABLED=true SCHEDULER_MAX_TICKS=2 python -m app.main --scheduler`
- Consume one durable runtime adapter job from `worker_runtime_jobs`:
  `WORKER_RUNTIME_FIXTURES_ENABLED=true WORKER_DATABASE_URL=postgresql://... python -m app.main --work-runtime-queue --once`
- Consume durable runtime adapter jobs in a bounded worker loop:
  `WORKER_RUNTIME_FIXTURES_ENABLED=true WORKER_DATABASE_URL=postgresql://... python -m app.main --work-runtime-queue --max-ticks 2`
- Materialize Query Heat buckets:
  `WORKER_DATABASE_URL=postgresql://... python -m app.main --aggregate-query-heat --query-heat-periods P1D,P7D`
- Refresh worker-generated tile layer features:
  `WORKER_DATABASE_URL=postgresql://... python -m app.main --refresh-tile-features --tile-layer-id flood-potential`
- Official adapter demo ingestion + freshness check: `python -m app.main --run-official-demo`
- Official adapter demo with DB persistence and evidence promotion:
  `python -m app.main --run-official-demo --persist --database-url postgresql://...`
- Scheduler loop smoke path: `python -m app.scheduler`
- Scheduler runtime adapter path:
  `WORKER_RUNTIME_FIXTURES_ENABLED=true python -m app.scheduler --run-enabled-adapters --once`
- Scheduler official demo tick: `python -m app.scheduler --official-demo --once`
- Worker heartbeat textfile metrics:
  `WORKER_METRICS_TEXTFILE_PATH=./tmp/worker.prom python -m app.main --run-enabled-adapters`
- Scheduler heartbeat textfile metrics:
  `SCHEDULER_METRICS_TEXTFILE_PATH=./tmp/scheduler.prom python -m app.main --scheduler --max-ticks 1`

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
`--work-runtime-queue` path safely no-ops when no database URL is configured,
when the database is unavailable, or when there is no ready job. When a job is
claimed, the worker resolves the job's `adapter_key`, runs that single adapter
through the fixture-gated ingestion/freshness path, marks the job succeeded on
success, and marks it failed with the error for unknown adapters or failed
adapter runs. Adapter construction still remains fixture-gated by
`WORKER_RUNTIME_FIXTURES_ENABLED=true`, so no external API calls are made by
default.

## Current scope

- Adapter contract and registry groundwork.
- Official CWA rainfall, WRA water-level, and flood-potential fixture parsers.
- Worker CLI/scheduler demo path for enabled official adapters.
- Configurable run-once and bounded scheduler path for enabled runtime adapters.
- DB-backed runtime job queue and singleton scheduler lease groundwork.
- DB-backed Query Heat aggregation job materializes `P1D` and `P7D` buckets
  from `location_queries` into `query_heat_buckets`.
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
- Tile production can now refresh feature/cache tables from worker code, but it
  does not yet generate full production MVT tiles or manage cache invalidation.
- PTT and Dcard adapters are phase-delayed and must remain disabled until legal
  and privacy review work lands. Future PRs must satisfy
  `docs/privacy/public-discussion-user-report-gates.md` before enabling them.
- User report ingestion is pending Phase 5 governance/API implementation and
  must satisfy `docs/privacy/public-discussion-user-report-gates.md` before any
  public intake path is enabled.
