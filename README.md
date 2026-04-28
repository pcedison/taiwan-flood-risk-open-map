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

The repository is in Phase 0: contracts and skeleton.

See [Project Work Plan](docs/PROJECT_WORK_PLAN.md) for the current execution order,
work packages, integration rules, and subagent handoff protocol.
