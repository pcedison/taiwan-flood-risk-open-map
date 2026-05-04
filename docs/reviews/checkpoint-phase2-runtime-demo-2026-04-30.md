# Phase 2 Runtime Demo Checkpoint - 2026-04-30

Branch: `codex/phase2-runtime-demo`

This checkpoint records the integrated Phase 1-3 hardening pass and the
follow-up five-point implementation wave on PR #1.

## Functional Scope

- Docs/status alignment: README, app READMEs, work plan, and progress notes now
  describe the project as Phase 1-3 groundwork in hardening, not a completed
  MVP.
- Placeholder boundary cleanup: API/Web placeholder servers remain
  fallback-only; worker sample/scheduler paths remain smoke/fallback-only; PTT,
  Dcard, and user reports remain phase-delayed.
- Runtime smoke: `scripts/runtime-smoke.ps1` and its runbook start Compose
  services, run migrations, check API readiness, run a risk query, check the Web
  HTTP surface, and stop services with `-StopOnExit`.
- Frontend evidence UX and tests: the map-first UI has richer evidence display,
  desktop/mobile Playwright smoke coverage, and Node unit tests for display
  helpers.
- API query heat and evidence realism: `/v1/risk/assess` persists
  query/assessment snapshots, evidence repository helpers use DB-first nearby
  evidence and safe geometry centroids for polygon evidence, and limited
  fallback behavior remains explicit when DB access is unavailable.
- API layers: `/v1/layers` now reads seeded `map_layers` metadata from PostGIS
  through a layer repository, with a deterministic fallback if DB data is
  unavailable.
- API tiles: `/v1/tiles/{layer_id}/{z}/{x}/{y}.mvt` serves DB-backed Mapbox
  Vector Tiles for seeded `flood-potential` and `query-heat` layers.
- Worker demo persistence: `python -m app.main --run-official-demo --persist
  --database-url ...` writes official demo evidence through raw snapshot,
  staging, promotion, and PostGIS geometry paths.
- Worker runtime scheduler: config-driven run-once and bounded-loop worker
  commands exist and remain safe by default because fixture adapters require
  explicit opt-in.
- Monitoring and ops: Prometheus scrape config and alert rules cover API
  availability, source freshness, and worker/scheduler heartbeats;
  backup/restore and source freshness scripts have dry-run and Docker-client
  paths.
- Phase 4/5 gates: public discussion/forum/user-report legal and privacy gates
  are documented and must be accepted before those sources are enabled.

## Verification Completed

- API: `python -m pytest` passed, 51 tests.
- API: `python -m ruff check .` passed.
- API: `python -m mypy .` passed.
- Workers: `python -m pytest` passed, 70 tests.
- Workers: `python -m ruff check .` passed.
- Workers: `python -m mypy .` passed.
- Web: `npm test` passed, 8 tests.
- Web: `npm run lint` passed.
- Web: `npm run typecheck` passed.
- Web: `npm run e2e` passed, 4 Playwright tests.
- Contracts/fixtures: OpenAPI, contract fixtures, migrations, and source
  allowlist validators passed.
- Ops scripts: PowerShell parser checks passed for runtime smoke, freshness
  check, and backup/restore drill.
- Freshness metrics: `scripts/ops-source-freshness-check.ps1 -DryRun` produced
  Prometheus-format metrics.
- Backup/restore: Docker client verification passed; non-scratch restore target
  rejection was verified.
- Runtime smoke: `scripts/runtime-smoke.ps1 -StopOnExit` completed against the
  local Compose stack.
- Worker DB demo: official demo persistence completed against PostGIS, and API
  risk assessment returned persisted flood-potential evidence near the demo
  polygon.
- Runtime follow-up smoke: migration `0005_query_heat_persistence.sql` applied
  on PostGIS, persisted query/assessment snapshots were counted, the query-heat
  MVT endpoint returned HTTP 200, and worker/scheduler heartbeat textfiles were
  written.

## Known Risks

- Query heat is still partial: persisted history exists, but materialized heat
  buckets remain pending.
- Worker production execution is still partial: safe run-once and bounded-loop
  commands exist, but durable queue/singleton scheduler behavior remains
  pending.
- Tile/layer production pipeline is still partial: real MVT serving exists, but
  dedicated production layer tables, cache, and hosting remain pending.
- Monitoring is heartbeat-ready, but production dashboards and scrape
  deployment remain pending.
- Placeholder servers and sample scheduler paths still exist as fallback/smoke
  tools and must not be counted as product runtime acceptance.
- PTT, Dcard, and user report adapters remain phase-delayed and disabled until
  legal/source/privacy gates are complete.

## Suggested Commit Message

```text
feat: advance phase 2 runtime demo hardening

- document Phase 1-3 hardening status and placeholder boundaries
- persist query heat history and serve DB-backed MVT tiles
- add safe worker runtime scheduler paths and heartbeat metrics
- document Phase 4/5 governance gates and expand verification
```

## PR Body Draft

```markdown
## Summary

This update advances `codex/phase2-runtime-demo` from a verified runtime-demo
checkpoint into a stronger Phase 2 demo: query heat persists, MVT tiles are
served from DB-backed SQL, worker runtime commands are configurable, heartbeat
metrics are real textfile outputs, and Phase 4/5 gates are explicit.

## Scope

- Align project status docs and placeholder boundaries.
- Add local runtime smoke, source freshness, backup/restore, and monitoring
  alert-rule entrypoints.
- Harden Web evidence display and frontend tests.
- Add DB-first evidence/layer API behavior with seeded `map_layers` metadata.
- Add persisted query/assessment snapshots and DB-backed query heat history.
- Add DB-backed MVT endpoint for seeded flood-potential and query-heat layers.
- Add worker official demo persistence through raw snapshot, staging,
  promotion, and PostGIS geometry paths.
- Add safe worker run-once / bounded scheduler commands and heartbeat textfile
  metrics.
- Add public discussion / user report governance gates.

## Verification

- API pytest/ruff/mypy passed: 51 tests.
- Worker pytest/ruff/mypy passed: 70 tests.
- Web test/lint/typecheck/e2e passed.
- OpenAPI, migration, contract fixture, and source allowlist validators passed.
- Runtime smoke passed with `scripts/runtime-smoke.ps1 -StopOnExit`.
- Worker DB demo persisted official flood-potential evidence and API risk
  assessment returned that evidence.
- Follow-up runtime smoke confirmed migration 0005, MVT tile HTTP 200,
  persisted query/assessment snapshots, and heartbeat textfile output.
- Backup/restore Docker client path and non-scratch restore guard were checked.

## Remaining Risks

- Materialized query heat buckets remain pending.
- Durable production queue/singleton scheduler remains pending.
- Production tile tables/cache/hosting remain pending beyond the DB-backed MVT
  smoke path.
- Production monitoring dashboards remain pending.
- Forum/user-report adapters remain disabled pending legal/source/privacy gates.
```
