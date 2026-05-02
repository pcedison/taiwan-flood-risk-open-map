# Next Phase Runtime Readiness Queue - 2026-04-30

Scope: WP5 runtime smoke, ops, and phase-readiness hardening for the next
integration phase. This file is intentionally an acceptance checklist, not a
claim that all production pipelines are complete.

## Status Legend

- Done: implemented or documented in this pass and covered by an available
  smoke/check.
- In development: a safe runtime path exists, but production behavior still
  needs implementation or hardening.
- Pending: not implemented yet; only documented as a fallback or future
  acceptance gate.

## Five-Point Readiness Standard

### 1. Expanded Runtime Smoke

Status: Done for script/runbook coverage.

Acceptance standard for the next phase:

- `.\scripts\runtime-smoke.ps1 -Help` works without touching Docker.
- The default runtime smoke includes base API/Web checks plus reports,
  queue, MVT, query heat, and tile-cache readiness checks.
- Operators can opt out of the extended checks only for local debugging with
  `-SkipExtendedSmoke`, `-SkipQueueSmoke`, or `-SkipReportsEnabledSmoke`.
- The runbook states which checks write local smoke rows.

### 2. Durable Queue Smoke

Status: In development with producer/consumer CLIs and replay-audit primitives.

What exists now:

- `worker_runtime_jobs` and scheduler lease tables exist.
- Worker code can enqueue/dequeue/complete runtime adapter jobs.
- Runtime smoke exercises one durable job through a one-off worker container
  with fixture adapters enabled.
- `--enqueue-runtime-jobs`, `--work-runtime-queue --once`, and
  `--work-runtime-queue --persist` CLIs are integrated.
- `--requeue-runtime-job` requires operator identity/reason, records replay
  audit rows, and refuses active poison-quarantined jobs.

Not complete yet:

- Reviewed real source clients are not the default runtime path.
- A production singleton scheduler and durable queue operating model are not
  accepted yet.
- Replay audit/quarantine tables are primitives only; production routing,
  alerting, source idempotency review, and approval workflow are not accepted.

Acceptance standard for the next phase:

- A documented queue producer CLI or scheduler command can enqueue jobs without
  an inline Python helper.
- Exactly one scheduler instance can acquire the production lease.
- A worker can consume, succeed, retry, and fail jobs with observable status.
- Queue smoke must pass against PostGIS without relying on hidden test doubles.

### 3. Reports Default-Disabled and Enabled Smoke

Status: Done for smoke and admin moderation coverage; product launch is
pending.

What exists now:

- `/v1/reports` is default-disabled and returns `feature_disabled`.
- Runtime smoke verifies the default-disabled path over live HTTP.
- Runtime smoke verifies the enabled route/repository path in a one-off API
  container with `USER_REPORTS_ENABLED=true`.
- Admin pending-list and moderation endpoints exist, with audit logging.

Not complete yet:

- Public report UX, moderation dashboard, abuse prevention, upload handling,
  deletion/retention flow, and governance launch approval are not complete.
- Reports must remain disabled by default outside explicit smoke/testing.

Acceptance standard for the next phase:

- Default-disabled behavior remains the deployment default.
- Enabled smoke inserts minimized pending reports and audit logs only.
- No media, EXIF, e-mail, username, or private reporter fields are accepted.
- Phase 5 launch remains blocked until
  `docs/privacy/public-discussion-user-report-gates.md` is accepted.

### 4. MVT and Tile Cache Readiness

Status: In development with worker CLI smoke.

What exists now:

- `/v1/tiles/{layer_id}/{z}/{x}/{y}.mvt` serves seeded `query-heat` and
  `flood-potential` layers.
- Runtime smoke verifies HTTP 200 and MVT content type for both seeded layers.
- `map_layer_features` and `tile_cache_entries` tables exist.
- `python -m app.main --refresh-tile-features --tile-layer-id flood-potential`
  can refresh worker-generated layer features.
- Runtime smoke writes one cache row and proves the API can serve it.

Not complete yet:

- Production layer feature generation is only implemented for the current
  `flood-potential` smoke path.
- Full production tile generation, expiry, refresh cadence, and invalidation
  are not accepted yet.
- External tile hosting/cache strategy is not accepted.

Acceptance standard for the next phase:

- A tile generation or refresh command can populate `map_layer_features` and
  `tile_cache_entries`.
- MVT responses can be served from cache when cache rows exist.
- Cache expiry and regeneration behavior are documented.
- Empty tiles remain valid, but non-200 tile responses block phase acceptance.

### 5. Query Heat Materialization

Status: In development with worker CLI smoke.

What exists now:

- `/v1/risk/assess` persists query/assessment snapshots.
- API query heat reads recent persisted assessment history when the database is
  available.
- Runtime smoke fails if query heat falls back to `limited-db-unavailable`
  while `/ready` reports the database healthy.
- `python -m app.main --aggregate-query-heat --query-heat-periods P1D,P7D`
  materializes privacy-preserving buckets into `query_heat_buckets`.
- Runtime smoke verifies materialized `P1D` and `P7D` rows exist.

Not complete yet:

- Materialized heat bucket generation is accepted only as a local runtime smoke
  path, not as a production cadence.
- Privacy-preserving bucket refresh cadence and retention are not accepted.

Acceptance standard for the next phase:

- A documented job can materialize privacy-preserving query heat buckets.
- The job never stores raw user identifiers.
- Buckets are coarse enough to avoid exposing individual queries.
- Runtime smoke can distinguish API fallback history from materialized bucket
  output.

## Required Next-Phase Verification

- `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\runtime-smoke.ps1 -Help`
- PowerShell parser check for `scripts/runtime-smoke.ps1`.
- Full runtime smoke after current API/worker/report changes settle:
  `.\scripts\runtime-smoke.ps1 -StopOnExit`
- Focused queue smoke using the runbook command.
- Focused reports default-disabled and enabled-path smoke.
- Focused MVT smoke for `query-heat` and `flood-potential`.
- Query heat materialization smoke for `P1D` and `P7D`.
- Tile feature refresh plus tile cache API-read smoke.

## Non-Acceptance Notes

- Do not count the local query heat CLI smoke as a production refresh cadence.
- Do not count the local tile feature/cache smoke as full production tile
  generation, expiry, invalidation, or external hosting.
- Do not count reports enabled smoke as Phase 5 product readiness.
- Do not count fixture-backed queue smoke as production source ingestion.
