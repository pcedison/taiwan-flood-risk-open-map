# Worker And Scheduler Deployment

Reviewed: 2026-06-09

This runbook defines the production-beta split-service path for Flood Risk. It
complements `deploy-zeabur.md`, which still documents the current single-service
preview path.

## Topology

Deploy these runtime units as separate services or platform-native jobs:

- `web`: Next.js public UI.
- `api`: FastAPI public/admin API.
- `worker`: durable queue consumer and one-off ingestion/maintenance runner.
- `scheduler`: singleton producer for runtime adapter jobs and maintenance
  ticks.
- `migrate`: manual or release-gated database migration job.

PostgreSQL/PostGIS, Redis, object storage, and monitoring storage are managed
dependencies. The worker and scheduler must share the same `DATABASE_URL`,
`REDIS_URL`, adapter gate variables, and source credentials as the API where
applicable.

## Required Commands

API and Web commands are platform-specific, but must expose `/health`, `/ready`,
and the public web origin.

Worker queue consumer:

```sh
python -m app.main --work-runtime-queue --persist
```

Scheduler queue producer:

```sh
python -m app.scheduler --enqueue-runtime-jobs
```

Scheduler maintenance tick:

```sh
python -m app.scheduler --maintenance
```

Migration job:

```sh
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f infra/migrations/<migration>.sql
```

Use bounded `--once` commands for smoke tests and release checks. Use platform
scheduling or exactly one scheduler replica for recurring production cadence.

## Environment Gates

Required for API, worker, scheduler:

- `APP_ENV=production-beta` or `production`
- `DATABASE_URL`
- `REDIS_URL`
- `ABUSE_HASH_SALT`

Required for hosted public API rate limits:

- `PUBLIC_RATE_LIMIT_ENABLED=true`
- `PUBLIC_RATE_LIMIT_BACKEND=redis`

Required before enabling live official worker adapters:

- `WORKER_ENABLED_ADAPTER_KEYS`
- `REALTIME_OFFICIAL_DIAGNOSTIC_FALLBACK_ENABLED=false` for hosted public API
  traffic. Production and production-beta do not use the API realtime bridge
  as readiness evidence; public risk responses must be backed by
  worker-persisted evidence.
- `SOURCE_CWA_API_ENABLED=true` plus `CWA_API_AUTHORIZATION` for CWA rainfall.
- `SOURCE_WRA_API_ENABLED=true` plus `WRA_API_TOKEN` if the WRA source requires
  it.
- `SOURCE_FLOOD_POTENTIAL_GEOJSON_ENABLED=true` plus a reviewed
  `FLOOD_POTENTIAL_GEOJSON_URL` for flood-potential imports.

Keep public discussion, forum, social, and public-report ingestion disabled
until their launch evidence is accepted.

## Health And Readiness

- API liveness: `GET /health`.
- API dependency readiness: `GET /ready`.
- Worker health: recent worker heartbeat textfile metric or platform job success.
- Scheduler health: recent scheduler heartbeat textfile metric and a singleton
  lease winner.
- Source health: source freshness metrics and latest adapter run status.
- Queue health: runtime queue metrics plus final-failed row inspection.

Set `WORKER_METRICS_TEXTFILE_PATH` and `SCHEDULER_METRICS_TEXTFILE_PATH` when
using node-exporter textfile collection. Scrape the generated files through the
monitoring profile or the hosted metrics collector.

## Smoke Checks

Local Compose validation:

```powershell
docker compose config --quiet
python -m pytest apps/workers/tests/test_worker_entrypoints.py -q
python infra/scripts/validate_monitoring_assets.py
```

Queue producer smoke:

```sh
WORKER_ENABLED_ADAPTER_KEYS=official.wra.water_level \
python -m app.scheduler --enqueue-runtime-jobs --once
```

Queue worker smoke:

```sh
WORKER_RUNTIME_FIXTURES_ENABLED=true \
WORKER_ENABLED_ADAPTER_KEYS=official.wra.water_level \
python -m app.main --work-runtime-queue --once --persist
```

Managed ingestion smoke:

```sh
WORKER_RUNTIME_FIXTURES_ENABLED=true \
WORKER_ENABLED_ADAPTER_KEYS=official.wra.water_level \
python -m app.main --run-enabled-adapters --persist
```

Before claiming hosted or production readiness, capture evidence that the
worker/scheduler path wrote `raw_snapshots`, `staging_evidence`,
`adapter_runs`, promoted `evidence`, and fresh `official_realtime_latest` rows
for each enabled official adapter. The `official_realtime_latest` rows are the
public hot path for nearby realtime coverage; do not use the API realtime
bridge as a substitute for this evidence.

## Failure Detection

Investigate before restarting workers when any of these fire:

- API `/ready` reports database or Redis failed.
- Worker heartbeat age exceeds the documented alert threshold.
- Scheduler heartbeat age exceeds the documented alert threshold.
- Source freshness marks CWA, WRA, flood-potential, public news, or historical
  evidence stale.
- Runtime queue final-failed rows increase.
- Adapter run status is `failed` or freshness checks are alerting.

Use row-level requeue only after confirming idempotency, source safety, and the
reason the previous run failed. Record the operator, reason, and evidence ref in
private ops notes.
