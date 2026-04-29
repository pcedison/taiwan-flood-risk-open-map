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

Commands below describe the current Phase 1 service contracts. Exact package commands may change as the app implementation grows, but changes must remain compatible with this runbook or update it in the same pull request.

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

The Zeabur matrix must use the same names as `.env.example`, `docker-compose.yml`, and the current FastAPI settings loader. Variables in this section are the Phase 1 shared contract; future production-only variables are listed separately so they are not mistaken for required skeleton configuration.

Required Phase 1 variables:

| Variable | Service | Notes |
|---|---|---|
| `APP_ENV` | api, worker, scheduler | `local`, `staging`, or `production-beta`; read by FastAPI settings as `app_env` |
| `LOG_LEVEL` | api, worker, scheduler | Use `info` by default to match `.env.example` casing |
| `NEXT_PUBLIC_API_BASE_URL` | web | Public API origin used by the web runtime |
| `NEXT_TELEMETRY_DISABLED` | web | Set to `1` to keep local/CI logs quiet and deterministic |
| `CORS_ORIGINS` | api | Comma-separated allowed web origins, for example `https://flood-risk-staging.example.com` |
| `ADMIN_BEARER_TOKEN` | api | Required before admin endpoints can be used; unset admin endpoints return 403 |
| `DATABASE_URL` | api, worker, scheduler, migration | PostgreSQL/PostGIS connection string |
| `REDIS_URL` | api, worker, scheduler | Redis connection string |
| `MINIO_ENDPOINT` | api, worker | MinIO or S3-compatible endpoint currently read by FastAPI settings |
| `MINIO_BUCKET_RAW_SNAPSHOTS` | worker | Raw source snapshot bucket name |
| `WORKER_QUEUE` | worker, scheduler | Queue name; current default is `default` |
| `WORKER_IDLE_SECONDS` | worker | Placeholder polling interval until durable jobs are implemented |
| `SCHEDULER_INTERVAL_SECONDS` | scheduler | Placeholder schedule interval; scheduler must remain a singleton |

Service-specific runtime variables:

| Variable | Service | Notes |
|---|---|---|
| `API_PORT` | api | Local/placeholder port. In Zeabur, prefer `$PORT` if the platform injects it into the start command. |
| `WEB_PORT` | web | Local/placeholder port. In Zeabur, prefer `$PORT` if the platform injects it into the start command. |
| `API_VERSION` | api | Optional release/version string exposed by `/health`; default is `0.1.0-draft`. |
| `POSTGRES_HOST` | postgres | Local compose helper when not using `DATABASE_URL` directly. |
| `POSTGRES_PORT` | postgres | Local compose helper. |
| `POSTGRES_DB` | postgres | Managed/database image initialization name. |
| `POSTGRES_USER` | postgres | Managed/database image initialization user. |
| `POSTGRES_PASSWORD` | postgres | Secret for local image initialization or managed database setup. |
| `REDIS_HOST` | redis | Local compose helper when not using `REDIS_URL` directly. |
| `REDIS_PORT` | redis | Local compose helper. |
| `MINIO_PUBLIC_ENDPOINT` | object-storage | Local compose/public console helper; not read by the current API settings loader. |
| `MINIO_CONSOLE_PORT` | object-storage | Local compose console port helper. |
| `MINIO_ROOT_USER` | object-storage | Secret for MinIO initialization. |
| `MINIO_ROOT_PASSWORD` | object-storage | Secret for MinIO initialization. |

Adapter and source variables:

| Variable | Service | Notes |
|---|---|---|
| `SOURCE_CWA_ENABLED` | worker, scheduler | Current flag name; default `false` until official adapter is implemented |
| `SOURCE_WRA_ENABLED` | worker, scheduler | Current flag name; default `false` until official adapter is implemented |
| `SOURCE_FLOOD_POTENTIAL_ENABLED` | worker, scheduler | Current flag name; default `false` until official adapter is implemented |
| `SOURCE_NEWS_ENABLED` | worker, scheduler | Current flag name; default `false` until legal/source review is complete |
| `SOURCE_PTT_ENABLED` | worker, scheduler | Current flag name; default `false` until legal/source review is complete |
| `SOURCE_DCARD_ENABLED` | worker, scheduler | Current flag name; default `false` until legal/source review is complete |

Future or phase-specific variables:

| Variable | Service | Notes |
|---|---|---|
| `SECRET_KEY` | api | Future auth/session secret; not loaded by the current skeleton FastAPI settings |
| `SCORE_VERSION` | api, worker | Future risk scoring release variable; initial intended value `risk-v0` |
| `CWA_API_KEY` | worker | Future official adapter credential, required only when that adapter reads it |
| `WRA_SOURCE_MODE` | worker | Future WRA adapter mode selector, required only when the adapter supports multiple modes |
| `TGOS_API_KEY` | api, worker | Future geocoding fallback credential |
| `TILE_BASE_URL` | web, api | Future self-hosted tile endpoint variable; add to web/API config when map runtime consumes it |
| `ADMIN_BOOTSTRAP_EMAIL` | api | Future admin bootstrap workflow |
| `QUERY_HEAT_MIN_COUNT` | api | Future privacy aggregation threshold |
| `ABUSE_HASH_SALT` | api | Future abuse-prevention secret |
| `RAW_SNAPSHOT_RETENTION_DAYS` | worker | Future retention policy once raw snapshot cleanup exists |
| `S3_ENDPOINT`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_BUCKET_RAW`, `S3_BUCKET_PROCESSED` | api, worker | Do not use these names in Phase 1. Current config uses `MINIO_ENDPOINT` and `MINIO_BUCKET_RAW_SNAPSHOTS`; introduce S3 aliases only with matching runtime support and `.env.example` updates. |

## Service Split

Use separate Zeabur services so each runtime can scale and restart independently.

| Service | Root | Public | Purpose | Current command | Next target |
|---|---|---|---|---|---|
| `web` | `apps/web` | yes | Web UI | Local compose: `npm ci && npm run dev -- --hostname 0.0.0.0 --port 3000` | Zeabur: `npm run build` during build, then `npm run start -- --hostname 0.0.0.0 --port $PORT` |
| `api` | `apps/api` | yes | FastAPI HTTP API | Local compose: `pip install -e . && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000` | Zeabur: install package during build, then `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| `worker` | `apps/workers` | no | Background ingestion and processing jobs | `python -m app.main` | Keep until a dedicated queue runner module exists; update this row if it moves. |
| `scheduler` | `apps/workers` | no | Periodic job enqueueing | `python -m app.scheduler` | Keep; replace sample job loop with durable enqueueing in implementation. |
| `migration` | repo root | no | One-off database migrations | `docker compose --profile tools run --rm migrate` applies numbered SQL files with `psql` | Zeabur one-off job should run the same migration loop before app restart; replace with Alembic only after it is introduced. |
| `postgres` | managed or image | no | PostgreSQL/PostGIS | Zeabur managed service or `postgis/postgis` image default | Same unless database ownership changes. |
| `redis` | managed or image | no | Cache and job coordination | Zeabur managed service or Redis image default | Same unless queue backend changes. |
| `object-storage` | managed or image | no | Raw snapshots and artifacts | MinIO-compatible service default | Same until object storage implementation requires explicit bucket bootstrap. |
| `tiles` | tile service root | yes | Self-hosted OSM vector tiles | Not present in Phase 1 compose | Add tile server command when the tile implementation lands. |

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
3. Run the `migration` one-off command:

   ```bash
   docker compose --profile tools run --rm migrate
   ```

4. Verify migration status and core table count:

   ```bash
   docker compose exec -T postgres psql -U flood_risk -d flood_risk -tAc \
     "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';"
   ```

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
curl -fsS "https://<api-domain>/health"
curl -fsS "https://<api-domain>/ready"
```

Smoke checks after deploy:

1. Web page loads from the configured Zeabur web domain.
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
