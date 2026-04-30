# Flood Risk Workers

Worker ingestion groundwork for official/L2 sources, plus scheduler/sample
smoke paths.

## Entry points

- Single sample job: `python -m app.main --once`
- Official adapter demo ingestion + freshness check: `python -m app.main --run-official-demo`
- Official adapter demo with DB persistence and evidence promotion:
  `python -m app.main --run-official-demo --persist --database-url postgresql://...`
- Scheduler loop smoke path: `python -m app.scheduler`
- Scheduler official demo tick: `python -m app.scheduler --official-demo --once`

The current implementation keeps the sample and scheduler paths lightweight so
they can run before production queue dependencies are selected.
The official demo only writes to Postgres when `--persist` is supplied; the
database URL can come from `--database-url`, `WORKER_DATABASE_URL`, or
`DATABASE_URL`.

## Current scope

- Adapter contract and registry groundwork.
- Official CWA rainfall, WRA water-level, and flood-potential fixture parsers.
- Worker CLI/scheduler demo path for enabled official adapters.
- Lightweight freshness checks that emit alerts for stale or failed adapter runs.
- L2 news/public-web sample adapter and source allowlist validation.
- Raw snapshot, staging, validation, promotion, and PostGIS writer groundwork.
- `WORKER_ENABLED_ADAPTER_KEYS` configuration groundwork for explicit adapter
  enablement.

## Placeholder boundary

- `app.scheduler` and `app.jobs.sample` are smoke/fallback paths, not completed
  production scheduler/queue behavior.
- PTT and Dcard adapters are phase-delayed and must remain disabled until legal
  and privacy review work lands.
- User report ingestion is pending Phase 5 governance/API implementation.
