# Zeabur Deployment Runbook

## Purpose

This runbook defines the expected Zeabur deployment path for Flood Risk staging and production beta. The SDD decision is GitHub repo to Zeabur VPS auto deploy, while preserving Docker Compose portability for future migration.

## Scope

This runbook covers:

- GitHub connection
- Environment variables
- Service split
- Database migration
- Worker and scheduler operations
- Rollback
- Health checks

Commands below describe the intended service contracts. Exact package commands may change once the app skeleton is implemented, but changes must remain compatible with this runbook or update it.

## GitHub Connection

1. Confirm the main branch is clean and all required work is committed.
2. Create or select the GitHub repository for the project.
3. In Zeabur, create a project for the target environment:
   - `flood-risk-staging`
   - `flood-risk-production-beta`
4. Connect the Zeabur project to the GitHub repository.
5. Select the deployment branch:
   - Staging: `codex/integration-sdd-mvp` or another integration branch.
   - Production beta: `main`.
6. Enable automatic redeploy on push.
7. Configure each Zeabur service with the correct root directory, build command, start command, and environment variables.
8. Do not commit secrets. Store secrets only in Zeabur environment variable settings or the selected secret manager.

## Environment Variables

Required shared variables:

| Variable | Service | Notes |
|---|---|---|
| `ENVIRONMENT` | all | `staging` or `production-beta` |
| `APP_BASE_URL` | web, api | Public web origin |
| `API_BASE_URL` | web | Public API origin |
| `DATABASE_URL` | api, worker, scheduler, migration | PostgreSQL/PostGIS connection string |
| `REDIS_URL` | api, worker, scheduler | Redis connection string |
| `SECRET_KEY` | api | Application secret, generated per environment |
| `SCORE_VERSION` | api, worker | Initial value: `risk-v0` |
| `LOG_LEVEL` | all | Use `INFO` by default |

Object storage variables:

| Variable | Service | Notes |
|---|---|---|
| `S3_ENDPOINT` | api, worker | MinIO or S3-compatible endpoint |
| `S3_ACCESS_KEY_ID` | api, worker | Secret |
| `S3_SECRET_ACCESS_KEY` | api, worker | Secret |
| `S3_BUCKET_RAW` | worker | Raw snapshots |
| `S3_BUCKET_PROCESSED` | worker | Processed artifacts |

Adapter and source variables:

| Variable | Service | Notes |
|---|---|---|
| `CWA_API_KEY` | worker | Optional until official adapter requires it |
| `WRA_SOURCE_MODE` | worker | API, KML, CSV, SHP, or configured mode |
| `TGOS_API_KEY` | api, worker | Optional geocoding fallback |
| `ENABLE_NEWS_ADAPTER` | worker, scheduler | Default `false` until reviewed |
| `ENABLE_PTT_ADAPTER` | worker, scheduler | Default `false` until reviewed |
| `ENABLE_DCARD_ADAPTER` | worker, scheduler | Default `false` until reviewed |
| `TILE_BASE_URL` | web, api | Self-hosted tile endpoint for public environments |

Operational variables:

| Variable | Service | Notes |
|---|---|---|
| `ADMIN_BOOTSTRAP_EMAIL` | api | First admin account or invite target |
| `QUERY_HEAT_MIN_COUNT` | api | Minimum public aggregation threshold |
| `ABUSE_HASH_SALT` | api | Secret salt for short-lived abuse prevention hashes |
| `RAW_SNAPSHOT_RETENTION_DAYS` | worker | Retention policy for raw source snapshots |

## Service Split

Use separate Zeabur services so each runtime can scale and restart independently.

| Service | Root | Public | Purpose | Expected start command |
|---|---|---|---|---|
| `web` | `apps/web` | yes | Next.js web UI | `npm run start -- --host 0.0.0.0 --port $PORT` |
| `api` | `apps/api` | yes | FastAPI HTTP API | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| `worker` | `apps/workers` | no | Background ingestion and processing jobs | `python -m app.jobs.worker` |
| `scheduler` | `apps/workers` | no | Periodic job enqueueing | `python -m app.jobs.scheduler` |
| `migration` | `apps/api` or `infra/migrations` | no | One-off database migrations | `alembic upgrade head` |
| `postgres` | managed or image | no | PostgreSQL/PostGIS | Zeabur managed service or `postgis/postgis` |
| `redis` | managed or image | no | Cache and job coordination | Zeabur managed service or Redis image |
| `object-storage` | managed or image | no | Raw snapshots and artifacts | MinIO-compatible service |
| `tiles` | tile service root | yes | Self-hosted OSM vector tiles | Tile server command defined by tile implementation |

Deployment notes:

- `api` and `web` should have HTTP domains and health checks.
- `worker`, `scheduler`, and `migration` must not be publicly exposed.
- `scheduler` should run with exactly one replica per environment.
- `worker` may scale horizontally after jobs are idempotent.
- `migration` should run as a one-off job, not as a permanently running service.

## Migration

Pre-deploy checklist:

1. Confirm the target branch and commit SHA.
2. Confirm `DATABASE_URL` points to the intended Zeabur environment.
3. Confirm a fresh database backup or snapshot exists.
4. Confirm migration files are ordered and reviewed.
5. Confirm migrations are backward compatible with the currently running API whenever possible.

Deploy sequence:

1. Pause or scale down `scheduler` to zero replicas.
2. Let active `worker` jobs finish, then scale `worker` down if the migration changes tables used by ingestion.
3. Run the `migration` one-off command.
4. Verify migration status.
5. Deploy or restart `api`.
6. Deploy or restart `web`.
7. Restart `worker`.
8. Restart `scheduler` with one replica.
9. Run health checks and a smoke risk query.

PostGIS requirements:

- Ensure the database has the PostGIS extension enabled before spatial migrations run.
- Spatial indexes must be created through migrations, not manual console changes.
- Migration rollback must be tested locally before a destructive migration is used in Zeabur.

## Worker and Scheduler

Worker responsibilities:

- Ingest official data adapters.
- Ingest reviewed public evidence adapters.
- Normalize evidence.
- Store raw snapshots when configured.
- Promote validated staging records.
- Publish source freshness and ingestion health.

Scheduler responsibilities:

- Enqueue recurring ingestion jobs.
- Avoid duplicate schedule ownership by running as a singleton.
- Respect adapter enable flags.
- Use conservative retry and backoff behavior.

Operational rules:

- Adapter failures must not make the API unavailable.
- Optional forum and public discussion adapters must remain disabled until legal/source review is complete.
- Raw snapshots are retained according to `RAW_SNAPSHOT_RETENTION_DAYS`.
- Job handlers should be idempotent before scaling workers above one replica.

## Rollback

Application rollback:

1. In Zeabur, select the previous successful deployment for `api`, `web`, `worker`, and `scheduler`.
2. Roll back `scheduler` last so it does not enqueue jobs against a mismatched API or schema.
3. Confirm `/health` and `/ready` after rollback.

Database rollback:

1. Prefer forward-compatible migrations and forward fixes.
2. If rollback is required, stop `scheduler` and `worker` first.
3. Run the reviewed downgrade migration if one exists and was tested.
4. If data loss or destructive schema changes occurred, restore from the latest verified backup or snapshot.
5. Record the rollback reason and update the ADR or runbook if the failure exposed a contract gap.

Data rollback:

- Do not mutate raw snapshots during rollback.
- Re-run promote jobs from validated staging data when possible.
- If corrupted evidence was promoted, mark affected records with ingestion status and reprocess from raw snapshots.

## Health Check

Zeabur HTTP health check:

- `api`: `GET /health`
- `web`: root route or framework health route when available

Recommended API endpoints:

- `GET /health`: process is alive.
- `GET /ready`: database, Redis, migration state, and required dependencies are ready.
- `GET /metrics`: Prometheus metrics when enabled.
- `GET /v1/admin/source-health`: source freshness and adapter status, admin protected.

Manual checks:

```bash
curl -fsS "$API_BASE_URL/health"
curl -fsS "$API_BASE_URL/ready"
```

Smoke checks after deploy:

1. Web page loads from `APP_BASE_URL`.
2. API health returns success.
3. Readiness confirms database and Redis connectivity.
4. A mock or real risk query returns a valid risk level and `score_version`.
5. Source health is visible for configured adapters.
6. Scheduler has exactly one running replica.
7. Worker logs show no repeated startup or migration errors.

## Post-Deploy Checklist

- Confirm GitHub commit SHA matches the Zeabur deployment.
- Confirm required environment variables are set.
- Confirm migration completed once.
- Confirm health checks pass.
- Confirm worker and scheduler service definitions are present.
- Confirm rollback target is known.
- Confirm monitoring or manual source freshness checks are available.
