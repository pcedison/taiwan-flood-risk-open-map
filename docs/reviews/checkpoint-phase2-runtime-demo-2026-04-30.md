# Phase 2 Runtime Demo Checkpoint - 2026-04-30

Branch: `codex/phase2-runtime-demo`

This checkpoint records the integrated Phase 1-3 hardening pass after the
second subagent wave and main-agent verification. The branch has not been
staged, committed, pushed, or opened as a PR at the time this document is
written.

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
- API query heat and evidence realism: evidence repository helpers use DB-first
  nearby evidence and safe geometry centroids for polygon evidence; limited
  fallback behavior remains explicit when DB access is unavailable.
- API layers: `/v1/layers` now reads seeded `map_layers` metadata from PostGIS
  through a layer repository, with a deterministic fallback if DB data is
  unavailable.
- Worker demo persistence: `python -m app.main --run-official-demo --persist
  --database-url ...` writes official demo evidence through raw snapshot,
  staging, promotion, and PostGIS geometry paths.
- Monitoring and ops: Prometheus scrape config and alert rules cover API
  availability and source freshness; backup/restore and source freshness
  scripts have dry-run and Docker-client paths.

## Verification Completed

- API: `python -m pytest` passed, 45 tests.
- API: `python -m ruff check .` passed.
- API: `python -m mypy .` passed.
- Workers: `python -m pytest` passed, 57 tests.
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

## Known Risks

- Query heat is still partial: DB-first read helpers exist, but
  `/v1/risk/assess` does not yet persist `location_queries` /
  `risk_assessments`, and materialized heat buckets are still pending.
- Worker production execution is still partial: the official demo has a runtime
  command, but durable production scheduler/queue behavior remains pending.
- Tile/layer production pipeline is still partial: layer metadata is now real,
  but real tile generation/hosting is not implemented.
- Monitoring is alert-rule ready, but real worker/scheduler heartbeat metrics
  are future placeholders until production worker runtime is implemented.
- Placeholder servers and sample scheduler paths still exist as fallback/smoke
  tools and must not be counted as product runtime acceptance.
- PTT, Dcard, and user report adapters remain phase-delayed and disabled until
  legal/source/privacy gates are complete.

## Suggested Commit Message

```text
feat: checkpoint phase 2 runtime demo hardening

- document Phase 1-3 hardening status and placeholder boundaries
- add runtime smoke, backup/restore, freshness checks, and Prometheus alerts
- wire API layers, DB-first evidence queries, and worker official demo persistence
- harden web evidence display and expand API/web/worker verification coverage
```

## PR Body Draft

```markdown
## Summary

This checkpoint moves `codex/phase2-runtime-demo` from skeleton hardening into a
verified runtime-demo state. It keeps the remaining product risks explicit while
proving the local API/Web/PostGIS path, worker official demo persistence, and
ops smoke scripts.

## Scope

- Align project status docs and placeholder boundaries.
- Add local runtime smoke, source freshness, backup/restore, and monitoring
  alert-rule entrypoints.
- Harden Web evidence display and frontend tests.
- Add DB-first evidence/layer API behavior with seeded `map_layers` metadata.
- Add worker official demo persistence through raw snapshot, staging,
  promotion, and PostGIS geometry paths.

## Verification

- API pytest/ruff/mypy passed.
- Worker pytest/ruff/mypy passed.
- Web test/lint/typecheck/e2e passed.
- OpenAPI, migration, contract fixture, and source allowlist validators passed.
- Runtime smoke passed with `scripts/runtime-smoke.ps1 -StopOnExit`.
- Worker DB demo persisted official flood-potential evidence and API risk
  assessment returned that evidence.
- Backup/restore Docker client path and non-scratch restore guard were checked.

## Remaining Risks

- Persisted query heat and heat bucket materialization remain pending.
- Production worker scheduler/queue remains pending.
- Tile generation/hosting remains pending beyond real layer metadata.
- Worker/scheduler heartbeat alerts need real production metrics.
- Forum/user-report adapters remain disabled pending legal/source/privacy gates.
```
