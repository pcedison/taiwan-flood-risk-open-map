# Docker Infrastructure

Placeholder for service-specific Dockerfiles and deployment helpers.

The root `docker-compose.yml` currently uses upstream runtime images to keep
the local skeleton lightweight. Treat it as a local runtime and ops smoke
harness, not a production topology.

## Phase 2.5/3 Runtime Truth

Completed for local Compose:

- API, Web, Postgres/PostGIS, Redis, MinIO, worker, scheduler, migration tool,
  and optional monitoring services are defined.
- Runtime smoke can validate API/Web, `/metrics`, reports gates, queue smoke,
  seeded MVT, query heat, and tile feature/cache helper paths.
- Worker queue producer/consumer and scheduler producer commands can run inside
  one-off Compose containers.
- Prometheus, Grafana, and node exporter can be started with the
  `monitoring` profile.

Partially complete:

- Worker queue persistence uses Postgres, row locks, leases, active-job
  `dedupe_key`, retries, `final_failed_at` visibility, and row-level
  list/requeue commands, but that is not a complete DLQ. There is no dedicated
  DLQ table, poison-job quarantine/routing policy, alert ownership, or
  accepted production replay procedure.
- The scheduler service defaults to `python -m app.scheduler`, which is still a
  placeholder/sample loop unless flags such as `--enqueue-runtime-jobs` or
  `--run-enabled-adapters` or `--maintenance` are supplied.
- The worker container can run `--run-official-demo --persist` against the
  Compose database, and can run CWA rainfall or WRA water-level live adapters
  when their explicit `SOURCE_*_API_ENABLED=true` gates are supplied.
  Flood-potential worker live clients are not deployed yet. WRA/CWA production
  egress verification and real credential review are still pending.
- Maintenance jobs such as query heat materialization and tile feature/cache
  cleanup have manual and bounded scheduler commands, not a deployed production
  cadence.
- Monitoring profile services use local defaults and named volumes. They do
  not establish hosted TLS/auth, durable retention, hosted cadence, or alert
  routing.

Deployable/local acceptance boundary:

- Queue metrics are accepted only for local or preview smoke when
  worker/scheduler textfiles are explicitly mounted, scraped, and visible in
  the chosen dashboard. Hosted alert routing and incident ownership remain
  pending.
- Flood-potential is accepted only as fixture/demo parsing plus worker
  feature/cache smoke. A real flood-potential source client still needs real
  upstream URL/license review, credential review, hosted cadence, alert
  routing, and production egress verification.
- Row-level final-failed visibility and requeue commands are queue operations
  tooling, not a complete DLQ.

Pending before production:

- Harden the gated CWA rainfall and WRA water-level source-client paths and
  add a reviewed flood-potential worker source client.
- Complete real credential review and WRA/CWA production egress verification
  before classifying official-source workers as production beta ready.
- A decision on how the API realtime official bridge is replaced or reconciled
  with persisted worker-ingested official evidence.
- Singleton scheduler deployment and documented hosted ingestion/maintenance
  cadence.
- Alertmanager or equivalent routing, TLS/auth, persistent monitoring storage,
  and backup/retention policy.
- Production policy for queue idempotency scope, replay audit, retry/backoff,
  poison-job quarantine/routing, alert routing, and worker scaling.
- Abuse governance, moderation, retention/deletion, and legal/privacy gates for
  public reports and public discussion sources.

## Operator Commands

```powershell
# Validate and start the local runtime services.
docker compose config --quiet
docker compose up -d postgres redis minio api web
docker compose --profile tools run --rm migrate

# Local acceptance smoke.
.\scripts\runtime-smoke.ps1 -StopOnExit

# Queue producer and worker smoke.
docker compose run --rm `
  -e WORKER_ENABLED_ADAPTER_KEYS=official.wra.water_level `
  worker sh -c "pip install -e . && python -m app.main --enqueue-runtime-jobs"

docker compose run --rm `
  -e WORKER_ENABLED_ADAPTER_KEYS=official.wra.water_level `
  -e WORKER_RUNTIME_FIXTURES_ENABLED=true `
  worker sh -c "pip install -e . && python -m app.main --work-runtime-queue --once"

# Official demo persistence path.
docker compose run --rm worker sh -c "pip install -e . && python -m app.main --run-official-demo --persist"

# Explicit CWA rainfall live adapter path.
docker compose run --rm `
  -e WORKER_ENABLED_ADAPTER_KEYS=official.cwa.rainfall `
  -e SOURCE_CWA_ENABLED=true `
  -e SOURCE_CWA_API_ENABLED=true `
  worker sh -c "pip install -e . && python -m app.main --run-enabled-adapters"

# Explicit WRA water-level live adapter path.
docker compose run --rm `
  -e WORKER_ENABLED_ADAPTER_KEYS=official.wra.water_level `
  -e SOURCE_WRA_ENABLED=true `
  -e SOURCE_WRA_API_ENABLED=true `
  worker sh -c "pip install -e . && python -m app.main --run-enabled-adapters"

# Inspect final-failed queue rows and requeue one by id after review.
# This is row-level queue visibility, not a complete DLQ.
docker compose run --rm worker sh -c "pip install -e . && python -m app.main --list-runtime-dead-letter-jobs --dead-letter-limit 20"
docker compose run --rm worker sh -c "pip install -e . && python -m app.main --requeue-runtime-job <job-id>"

# Lease-guarded scheduler producer tick.
docker compose run --rm `
  -e WORKER_ENABLED_ADAPTER_KEYS=official.wra.water_level `
  scheduler sh -c "pip install -e . && python -m app.scheduler --enqueue-runtime-jobs --once"

# Manual maintenance smoke.
docker compose run --rm worker sh -c "pip install -e . && python -m app.main --aggregate-query-heat --query-heat-periods P1D,P7D --query-heat-retention-days 90"
docker compose run --rm worker sh -c "pip install -e . && python -m app.main --refresh-tile-features --tile-layer-id flood-potential --tile-feature-limit 25"
docker compose run --rm worker sh -c "pip install -e . && python -m app.scheduler --maintenance --once"
```

## Monitoring Profile

Local monitoring deployment wiring lives in the root Compose file under the
`monitoring` profile:

```powershell
docker compose --profile monitoring config
docker compose --profile monitoring up
```

This starts Prometheus, Grafana, and node exporter using assets from
`infra/monitoring`. It is intended for local validation and reviewer demos.
Hosted deployments should adapt DNS names, credentials, persistent storage,
TLS, scheduler wiring, and alert routing for the target environment.
