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
- Language: Traditional Chinese first.
- Risk labels: `低`, `中`, `高`, `極高`, `未知`.
- AI/NLP v1: rules plus small open-source NLP models; model output is never the only source of truth.

## Planned Runtime

- Frontend: Next.js and MapLibre/Leaflet.
- Backend: FastAPI.
- Spatial database: PostgreSQL with PostGIS.
- Workers: Python worker service with explicit scheduler.
- Cache/queue: Redis.
- Object storage: MinIO.
- Local orchestration: Docker Compose.

## Development Status

The repository has moved beyond the Phase 0 skeleton. Phase 1 map-first query
groundwork is in place, Phase 2 ingestion/adapters have tested groundwork, and
Phase 3 risk scoring v0 has golden-fixture coverage. The current sprint is a
hardening pass across docs/status, Web evidence UX, runtime smoke, and
worker/API ingestion wiring. Runtime smoke now covers the base API/Web path,
query heat, durable queue smoke, default-disabled and enabled-path report
smoke, seeded MVT endpoints, query heat materialization, and a tile
feature/cache smoke path. Public report product UX, production source-client
rollout, singleton queue/scheduler behavior, tile cache hosting/expiry, and
governance remain next-phase work.

Current placeholder boundaries:

- API and Web placeholder servers remain only as fallback files; Docker Compose
  now points at the FastAPI and Next.js development runtimes. Keep these files
  only for last-resort diagnostics unless a follow-up explicitly removes them.
- Worker scheduler and sample jobs are safe local runtime paths, not a
  completed production queue/scheduler. Durable queue smoke exists for one
  local fixture job, but production source clients and singleton scheduling are
  still pending.
- PTT, Dcard, and user report adapters are phase-delayed/pending
  implementation and must remain disabled until the required legal, privacy, and
  governance work lands.
- `packages/geo`, `packages/shared`, and `infra/monitoring` are still
  placeholder or baseline areas, not completed tile, shared-rule, or monitoring
  systems. DB-backed MVT serving and worker-side feature/cache smoke exist, but
  tile cache generation, expiry, and hosting are not production-ready.

Ops runbooks and dry-run checks:

- [Runtime Smoke Runbook](docs/runbooks/runtime-smoke.md) for local Compose
  runtime acceptance, including queue, reports, MVT, and query heat/cache
  job smoke.
- [Monitoring Freshness Alerts](docs/runbooks/monitoring-freshness-alerts.md)
  and `scripts/ops-source-freshness-check.ps1` for admin source-health
  freshness checks.
- [Backup and Restore Drill](docs/runbooks/backup-restore-drill.md) and
  `scripts/backup-restore-drill.ps1` for non-destructive drill planning,
  backup creation, and explicit scratch restore verification.
- [Next Phase Runtime Readiness Queue](docs/reviews/phase-next-runtime-queue-heat-tiles-reports-2026-04-30.md)
  for the five acceptance standards around queue, reports, MVT, query heat, and
  tile cache readiness.

See [Project Work Plan](docs/PROJECT_WORK_PLAN.md) for the current execution order,
work packages, integration rules, and subagent handoff protocol.
