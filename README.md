# Taiwan Flood Risk Open Map

Taiwan Flood Risk Open Map is a public-interest, open-source-first platform for
querying realtime and historical flood risk in Taiwan.

The project follows a spec-first SDD workflow. The source of truth is:

- [Project SDD](docs/PROJECT_SDD.md)
- [Project Work Plan](docs/PROJECT_WORK_PLAN.md)

## Core Decisions

- License: Apache-2.0 for software.
- Data exports: layered licensing.
- Deployment path: GitHub repository connected to Zeabur VPS.
- Basemap launch path: MapLibre GL JS with PMTiles/Protomaps-compatible
  OpenStreetMap-derived data served from object storage/CDN.
- TGOS: future optional Taiwan-local provider, not an MVP or public launch
  blocker.
- Language: Traditional Chinese first.
- Risk labels: `低`, `中`, `高`, `極高`, `未知`.
- AI/NLP v1: rules plus small open-source NLP models; model output is never the only source of truth.

## Planned Runtime

- Frontend: Next.js and MapLibre GL JS.
- Open basemap: PMTiles/Protomaps-compatible OSM-derived data through
  Cloudflare R2 or another S3-compatible object storage/CDN path.
- Backend: FastAPI.
- Spatial database: PostgreSQL with PostGIS.
- Workers: Python worker service with explicit scheduler.
- Cache: Redis.
- Durable worker queue groundwork: PostgreSQL `worker_runtime_jobs`; Redis is
  not the accepted production queue backend yet.
- Object storage: MinIO locally; Cloudflare R2 or compatible S3 for low-cost
  public basemap assets, snapshots, and backups.
- Local orchestration: Docker Compose.

## Development Status

The repository has moved beyond the Phase 0 skeleton. Phase 1 map-first query
groundwork is in place, Phase 2 ingestion/adapters have tested groundwork, and
Phase 3 risk scoring v0 has golden-fixture coverage. The current sprint is a
hardening pass across docs/status, Web evidence UX, runtime smoke, and
worker/API ingestion wiring. Runtime smoke now covers the base API/Web path,
query heat, durable queue smoke with active-job dedupe, replay-audited requeue,
and final-failed row visibility, default-disabled and enabled-path report smoke,
seeded MVT endpoints, query heat materialization, and a tile feature/cache smoke
path. The worker official-adapter path is partial but no longer demo-only:
`--run-official-demo --persist`, `--run-enabled-adapters --persist`, and
`--work-runtime-queue --persist` can write staging, ingestion-run, and evidence
rows, and CWA rainfall, WRA water level, and flood-potential GeoJSON all have
explicit live-client gates. Reviewed credentials, production cadence, replay
operations, tile cache hosting/expiry, and governance remain next-phase work.

Current placeholder boundaries:

- API and Web placeholder servers remain only as fallback files; Docker Compose
  now points at the FastAPI and Next.js development runtimes. Keep these files
  only for last-resort diagnostics unless a follow-up explicitly removes them.
- Worker scheduler and sample jobs are safe local runtime paths, not a
  completed production queue/scheduler. Durable queue smoke exists for local
  fixture jobs, active-job dedupe, final-failed row visibility, and audited
  manual requeue. Replay audit/quarantine DB primitives exist, but a production
  replay policy, poison-job routing/escalation, and deployed singleton
  scheduling are still pending.
- Official data currently has two different paths that should not be conflated:
  the API realtime bridge can fetch CWA/WRA observations for risk responses,
  while the worker official-adapter path has demo persistence plus managed
  persistence for gated CWA rainfall, WRA water-level, and flood-potential
  GeoJSON clients. Flood-potential still needs reviewed upstream URL/license,
  credential, cadence, and egress approval before production use.
- PTT, Dcard, and user report adapters are phase-delayed/pending
  implementation and must remain disabled until the required legal, privacy, and
  governance work lands.
- `packages/geo`, `packages/shared`, and `infra/monitoring` are still
  placeholder or baseline areas, not completed tile, shared-rule, or monitoring
  systems. DB-backed MVT serving and worker-side feature/cache smoke exist, but
  tile cache generation, expiry, and hosting are not production-ready.
- The basemap launch path is now PMTiles/object-storage/CDN first. A full
  OpenMapTiles/Tegola/PostGIS tile server is a future higher-operations option,
  and TGOS remains optional rather than a launch dependency.

Ops runbooks and dry-run checks:

- [Open Basemap PMTiles Runbook](docs/runbooks/open-basemap-pmtiles.md) for
  MapLibre, PMTiles/Protomaps, object-storage/CDN delivery, OSM/ODbL
  attribution, range request smoke, cache behavior, and rollback.
- [Runtime Smoke Runbook](docs/runbooks/runtime-smoke.md) for local Compose
  runtime acceptance, including queue, reports, MVT, and query heat/cache
  job smoke.
- [Monitoring Freshness Alerts](docs/runbooks/monitoring-freshness-alerts.md)
  and `scripts/ops-source-freshness-check.ps1` for admin source-health
  freshness checks.
- [Monitoring Dashboard Runbook](docs/runbooks/monitoring-dashboard.md) for the
  optional local Compose `monitoring` profile, Prometheus/Grafana wiring,
  dashboard import validation, source freshness panels, and worker queue
  heartbeat panel expectations.
- [Backup and Restore Drill](docs/runbooks/backup-restore-drill.md) and
  `scripts/backup-restore-drill.ps1` for non-destructive drill planning,
  backup creation, and explicit scratch restore verification.
- [Production Readiness and On-Call Drill](docs/runbooks/production-readiness.md),
  `docs/runbooks/production-readiness-evidence.example.yaml`, and
  `infra/scripts/validate_production_readiness_evidence.py` for validating the
  evidence record shape. This is a schema/tooling check, not proof that real
  Zeabur production env, secrets, alert routing, or on-call drill are complete.
- [Next Phase Runtime Readiness Queue](docs/reviews/phase-next-runtime-queue-heat-tiles-reports-2026-04-30.md)
  for the five acceptance standards around queue, reports, MVT, query heat, and
  tile cache readiness.

See [Project Work Plan](docs/PROJECT_WORK_PLAN.md) for the current execution order,
work packages, integration rules, and subagent handoff protocol.

## Phase 2.5/3 Operations Status

This status is current for the `codex/phase2-runtime-demo` branch as of
2026-05-02. It is intentionally conservative: local smoke and groundwork are
not production readiness.

| Area | Current status | Production boundary |
|---|---|---|
| Runtime smoke | Completed for local Compose API/Web, `/metrics`, risk query, reports gates, seeded MVT, query heat, queue smoke, and tile feature/cache smoke. | Passing local smoke does not prove real credential review, hosted source credentials, scheduler cadence, alert routing, TLS, persistent storage, WRA/CWA production egress, or public abuse controls. |
| Worker queue | Partially complete. Postgres queue tables, enqueue/dequeue CLIs, row leases, active-job `dedupe_key`, retry-to-`failed`, `final_failed_at`, list/requeue commands, replay audit/quarantine tables, and local fixture-backed smoke exist. | Dedupe is scoped to active queue/job/adapter rows. Row-level list/requeue is operational visibility, not a complete DLQ. Replay audit primitives exist, but a dedicated DLQ table, poison-job routing policy, alert ownership, and accepted production replay procedure are still pending; exhausted jobs remain `failed` in `worker_runtime_jobs` until explicitly requeued. Real source success/retry/failure must still be proven. |
| Official ingestion paths | Partially complete. The API has a realtime official bridge for CWA/WRA risk evidence; the worker has fixture parsers, `--run-official-demo --persist`, managed `--run-enabled-adapters --persist`, queue-worker `--work-runtime-queue --persist`, and gated CWA rainfall/WRA water-level/flood-potential GeoJSON live clients. | The API bridge is not auditable worker ingestion. Worker live mode is explicit opt-in; reviewed credentials, raw snapshot storage policy, hosted cadence, real upstream URL/license review, and production egress verification are pending. These deployable gates are not production beta readiness by themselves. |
| Scheduler and maintenance cadence | Partially complete. Bounded scheduler, queue producer, and maintenance commands exist, and queue/maintenance loops can acquire DB-backed leases. | Production scheduler deployment, hosted singleton operating model, per-source cadence, maintenance windows, and ownership/runbook for retries are pending. |
| Monitoring | Partially complete. Local `monitoring` profile, Prometheus rules, Grafana dashboard JSON, API scrape, freshness script, and opt-in worker/scheduler textfile metrics exist. | Hosted Prometheus/Grafana or equivalent still needs real service DNS, credentials, TLS/auth, persistent storage, Alertmanager/pager routing, scheduled freshness jobs, and production alert routing ownership. |
| Public reports and public discussion sources | Groundwork only. Reports are default-disabled; Phase 4/5 gates are documented. | Abuse governance, moderation UX, deletion/retention flows, upload handling, legal/source review, and forum/public source launch approval are pending. |

Next-phase acceptance boundary:

- Queue metrics acceptance is local/deployable only when the worker/scheduler
  heartbeat textfiles are explicitly enabled, mounted into a collector, scraped,
  and visible in the local or target preview dashboard. It does not prove hosted
  alert routing, replay ownership, or a production incident workflow.
- Flood-potential acceptance now includes a gated GeoJSON runtime client and
  worker-generated feature/cache smoke, but remains blocked for production
  until a reviewed upstream URL, license, credential, cadence, and egress path
  are approved.
- Pending items that must remain visible in release notes and handoffs: real
  upstream URL/license review, credential review, hosted cadence, alert
  routing, accepted replay policy around the new audit/quarantine primitives,
  and production egress verification.

Operator commands:

```powershell
# Local runtime acceptance smoke.
.\scripts\runtime-smoke.ps1 -StopOnExit

# Enqueue one durable runtime adapter job per enabled adapter.
docker compose run --rm `
  -e WORKER_ENABLED_ADAPTER_KEYS=official.wra.water_level `
  worker sh -c "pip install -e . && python -m app.main --enqueue-runtime-jobs"

# Consume one queued runtime adapter job using fixture-backed local adapters.
docker compose run --rm `
  -e WORKER_ENABLED_ADAPTER_KEYS=official.wra.water_level `
  -e WORKER_RUNTIME_FIXTURES_ENABLED=true `
  worker sh -c "pip install -e . && python -m app.main --work-runtime-queue --once"

# Consume and persist one queued runtime adapter job.
docker compose run --rm `
  -e WORKER_ENABLED_ADAPTER_KEYS=official.wra.water_level `
  -e WORKER_RUNTIME_FIXTURES_ENABLED=true `
  worker sh -c "pip install -e . && python -m app.main --work-runtime-queue --once --persist"

# Persist the official demo path to staging, ingestion runs, and evidence.
docker compose run --rm worker sh -c "pip install -e . && python -m app.main --run-official-demo --persist"

# Persist configured runtime adapters through the managed runtime path.
docker compose run --rm `
  -e WORKER_ENABLED_ADAPTER_KEYS=official.wra.water_level `
  -e WORKER_RUNTIME_FIXTURES_ENABLED=true `
  worker sh -c "pip install -e . && python -m app.main --run-enabled-adapters --persist"

# Run the gated CWA rainfall live adapter once.
docker compose run --rm `
  -e WORKER_ENABLED_ADAPTER_KEYS=official.cwa.rainfall `
  -e SOURCE_CWA_ENABLED=true `
  -e SOURCE_CWA_API_ENABLED=true `
  worker sh -c "pip install -e . && python -m app.main --run-enabled-adapters"

# Run the gated WRA water-level live adapter once.
docker compose run --rm `
  -e WORKER_ENABLED_ADAPTER_KEYS=official.wra.water_level `
  -e SOURCE_WRA_ENABLED=true `
  -e SOURCE_WRA_API_ENABLED=true `
  worker sh -c "pip install -e . && python -m app.main --run-enabled-adapters"

# Inspect exhausted final-failed job rows. This is not a complete DLQ.
docker compose run --rm worker sh -c "pip install -e . && python -m app.main --list-runtime-dead-letter-jobs --dead-letter-limit 20"

# Requeue one failed job by id; use only after confirming payload/idempotency.
docker compose run --rm worker sh -c "pip install -e . && python -m app.main --requeue-runtime-job <job-id> --requeue-requested-by <operator> --requeue-reason '<why-safe-to-retry>'"

# Run one lease-guarded scheduler producer tick.
docker compose run --rm `
  -e WORKER_ENABLED_ADAPTER_KEYS=official.wra.water_level `
  scheduler sh -c "pip install -e . && python -m app.scheduler --enqueue-runtime-jobs --once"

# Manual maintenance smoke for materialized query heat.
docker compose run --rm worker sh -c "pip install -e . && python -m app.main --aggregate-query-heat --query-heat-periods P1D,P7D --query-heat-retention-days 90"

# One bounded maintenance scheduler tick for query heat and tile cache cleanup.
docker compose run --rm worker sh -c "pip install -e . && python -m app.scheduler --maintenance --once"

# Local monitoring profile.
docker compose --profile monitoring up prometheus grafana node-exporter
python infra/scripts/validate_monitoring_assets.py
python infra/scripts/validate_production_readiness_evidence.py
```

Production pending checklist:

- Wire the web runtime to a project-controlled or explicitly licensed
  MapLibre style backed by PMTiles/Protomaps-compatible OSM-derived data from
  object storage/CDN.
- Add release evidence for OSM/ODbL attribution, PMTiles range requests, CDN
  cache headers, and basemap rollback. Runtime smoke must pass with TGOS unset
  or disabled.
- Harden the gated CWA rainfall, WRA water-level, and flood-potential GeoJSON
  worker clients after real upstream URL/license review, credential review,
  hosted cadence, alert routing, and production egress verification are
  accepted.
- Complete real credential review and WRA/CWA/flood-potential production
  egress verification before calling any official-source path production beta
  ready.
- Decide whether the current API realtime official bridge remains a temporary
  direct-fetch bridge or is replaced by persisted worker-ingested evidence for
  public risk responses.
- Deploy a singleton scheduler and documented maintenance cadence for
  ingestion, query heat materialization, tile refresh, and retention.
- Harden the current queue active-job dedupe, final-failed visibility,
  replay-audited row-level requeue command, and quarantine primitives into an
  accepted replay model with alerting and operational ownership before scaling
  workers. Do not describe the current row-level visibility as a complete DLQ.
- Add hosted alert routing, TLS/auth, durable Prometheus/Grafana storage, and
  scheduled freshness checks.
- Finish project overlay tile cache generation, expiry, invalidation, and
  hosting strategy. Keep the basemap on the lower-ops PMTiles path until a tile
  server upgrade is explicitly accepted.
- Keep public reports, forum sources, and public discussion ingestion disabled
  until abuse governance, moderation, retention/deletion, and legal/privacy
  gates are accepted.
