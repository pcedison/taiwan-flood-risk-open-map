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
worker/API ingestion wiring. The code/test hardening pieces are in place; the
full Docker runtime smoke still requires a running Docker daemon.

Current placeholder boundaries:

- API and Web placeholder servers remain only as fallback files; Docker Compose
  now points at the FastAPI and Next.js development runtimes. Keep these files
  only for last-resort diagnostics unless a follow-up explicitly removes them.
- Worker scheduler and sample jobs are skeleton smoke paths, not a completed
  production queue/scheduler.
- PTT, Dcard, and user report adapters are phase-delayed/pending
  implementation and must remain disabled until the required legal, privacy, and
  governance work lands.
- `packages/geo`, `packages/shared`, and `infra/monitoring` are still
  placeholder or baseline areas, not completed tile, shared-rule, or monitoring
  systems.

Ops runbooks and dry-run checks:

- [Runtime Smoke Runbook](docs/runbooks/runtime-smoke.md) for local Compose
  runtime acceptance.
- [Monitoring Freshness Alerts](docs/runbooks/monitoring-freshness-alerts.md)
  and `scripts/ops-source-freshness-check.ps1` for admin source-health
  freshness checks.
- [Backup and Restore Drill](docs/runbooks/backup-restore-drill.md) and
  `scripts/backup-restore-drill.ps1` for non-destructive drill planning,
  backup creation, and explicit scratch restore verification.

See [Project Work Plan](docs/PROJECT_WORK_PLAN.md) for the current execution order,
work packages, integration rules, and subagent handoff protocol.
