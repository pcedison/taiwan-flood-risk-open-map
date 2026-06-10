# Flood Risk Engineering Roadmap

Reviewed: 2026-06-10

This roadmap is the engineering execution backlog for the next production-beta push. It complements `docs/PROJECT_WORK_PLAN.md`: the work plan records the broader phase strategy, while this file lists the concrete blockers, runtime gaps, and trust/scale improvements that should be executed next.

## Current State

- The local production-beta candidate is green: Docker Compose config, API tests/mypy, worker tests, repository tests, unknown-address smoke, event public-value smokes, web audit/unit/lint/typecheck/build/E2E, OpenAPI, contract fixtures, source allowlists, migrations, monitoring assets, readiness evidence examples, basemap evidence, flood-potential import evidence, public-report evidence, risk-calibration examples, and `scripts/public-beta-local-gate.ps1` passed during the latest review.
- Latest repo-local execution audit: `docs/reviews/roadmap-execution-audit-2026-06-10.md`.
- Full runtime smoke still depends on the local Docker daemon being available.
- All repo-scoped P0/P1/P2 items currently listed below are accepted except P1-04 and P2-01, which remain `In Progress` because they require private environment-specific production evidence outside this repository.
- The project is not yet hosted production-beta-ready until real source launch evidence and production calibration replay evidence pass the `--production-complete` validators in a private ops-controlled location.

Task status values:

- `Todo`: not implemented yet.
- `In Progress`: implementation has started but is not accepted.
- `Accepted`: implementation, tests, and acceptance checks are complete.

## P0 - Release Blockers

### P0-01 Fix API mypy Failure

Status: Accepted

Problem: `apps/api/app/api/routes/public.py` contains a `max()` call over values typed as `datetime | None`, causing `cd apps/api && python -m mypy app` to fail.

Implementation:

- Normalize candidate timestamps into a `list[datetime]` before calling `max()`.
- Keep the existing response semantics for official flood-disaster summary evidence.
- Add or update a focused unit test for summary creation when records have mixed `observed_at`, `occurred_at`, and missing timestamps.

Acceptance Criteria:

- `cd apps/api && python -m mypy app` passes.
- Existing API tests still pass.
- Summary evidence still chooses the nearest representative item and latest available timestamp.

Verification:

- `python -m pytest apps/api/tests -q`
- `cd apps/api && python -m mypy app`

Dependencies: None.

### P0-02 Upgrade Next.js And Clear High-Risk Audit Findings

Status: Accepted

Problem: `apps/web/package-lock.json` currently resolves Next.js to `15.5.15`, and `npm audit --prefix apps/web` reports high-severity Next.js advisories plus a moderate transitive advisory.

Implementation:

- Upgrade Next.js to a patched compatible release using the minimal dependency update needed.
- Refresh `apps/web/package-lock.json`.
- Resolve the `brace-expansion` transitive advisory if `npm audit fix` or a targeted dependency refresh can do so without broad churn.
- Keep React and app behavior unchanged unless required by the Next.js patch.

Acceptance Criteria:

- `npm audit --prefix apps/web` reports no high-severity production dependency findings.
- Any remaining moderate dev-only finding must be documented in the PR with why it is not exploitable in runtime.
- Frontend lint, typecheck, unit tests, and build pass.

Verification:

- `npm ci --prefix apps/web`
- `npm audit --prefix apps/web`
- `npm run lint --prefix apps/web`
- `npm run typecheck --prefix apps/web`
- `npm test --prefix apps/web`
- `npm run build --prefix apps/web`

Dependencies: None.

### P0-03 Remove Production Use Of Unverified TLS For Official Realtime Data

Status: Accepted

Problem: official realtime fetching can fall back to an unverified TLS context. Public safety data must not silently accept unverifiable upstream responses in hosted environments.

Implementation:

- Remove the unverified TLS fallback, or guard it behind an explicit local-only development flag.
- In staging/production, certificate verification failure must return a degraded source status rather than unverified data.
- Add logging and metrics labels that distinguish upstream TLS failure from timeout, malformed response, and disabled source.

Acceptance Criteria:

- No staging/production code path uses `ssl._create_unverified_context()`.
- Risk assessment responses can degrade gracefully when official realtime sources fail TLS verification.
- Tests cover TLS failure behavior.

Verification:

- `python -m pytest apps/api/tests -q`
- `cd apps/api && python -m mypy app`
- Manual code search confirms no production-reachable unverified TLS path remains.

Dependencies: None.

### P0-04 Make Hosted Admin DB Failures Explicit

Status: Accepted

Problem: admin jobs and sources can return sample data when the repository is unavailable. That is useful for local skeleton behavior but misleading in hosted operations.

Implementation:

- Keep sample admin data only for local/test environments or behind an explicit demo flag.
- In hosted environments, return `503` when the admin repository cannot reach the database.
- Preserve the existing admin authentication requirement.

Acceptance Criteria:

- Hosted admin `/jobs` and `/sources` failures are explicit `503` responses.
- Local/demo mode can still show sample data only when explicitly allowed.
- Tests cover hosted failure and local/demo fallback behavior.

Verification:

- `python -m pytest apps/api/tests -q`
- Contract fixtures updated only if response contracts intentionally change.

Dependencies: None.

### P0-05 Add Public Rate Limiting For Geocode And Risk Assessment

Status: Accepted

Problem: user-report intake has abuse controls, but public geocode and risk-assessment endpoints do not have equivalent rate limiting.

Implementation:

- Add a reusable public endpoint rate-limit helper.
- Use Redis in hosted environments and memory fallback only for local/test.
- Hash client signals with the existing privacy-preserving pattern used by report intake.
- Return a structured `429` error payload consistent with existing API error shape.
- Apply limits to `/v1/geocode` and `/v1/risk/assess`.

Acceptance Criteria:

- Hosted deployments fail closed if required Redis-backed rate limiting is unavailable.
- Local/test runs remain easy to use without external Redis.
- Tests cover allowed requests, exceeded limits, missing backend, and error payload shape.

Verification:

- `python -m pytest apps/api/tests -q`
- OpenAPI validation still passes if response metadata changes.

Dependencies: None.

## P1 - Production Runtime

### P1-01 Split The Oversized Public API Route

Status: Accepted

Problem: `apps/api/app/api/routes/public.py` combines transport handlers, geocoding fallback, risk orchestration, evidence assembly, public-news lookup, layer fallback, caching, and persistence. This makes production changes risky.

Implementation:

- Keep public HTTP schemas and endpoint URLs stable.
- Move risk-assessment orchestration into a service module. (Complete.)
- Move evidence listing/cache lookup into an evidence service. (Complete.)
- Move layer record and TileJSON fallback logic into a layer service. (Complete.)
- Leave FastAPI route functions as thin request/response adapters. (Complete.)

Acceptance Criteria:

- No public API response shape changes.
- Route file size and responsibility are materially reduced.
- Existing API tests pass without broad fixture rewrites.
- New service-level tests cover risk orchestration branches that were previously only route-level behavior.

Verification:

- `python -m pytest apps/api/tests -q`
- `python -m ruff check apps/api/app apps/api/tests`
- `cd apps/api && python -m mypy app`
- `python infra/scripts/validate_openapi.py`
- `python infra/scripts/validate_contract_fixtures.py`

Dependencies: P0-01 should be completed first to avoid refactoring around a known type failure.

### P1-02 Enforce Official Realtime Source-Of-Truth Semantics

Status: Accepted

Problem: risk assessment currently uses on-demand official realtime calls from the API path, while the worker system is the intended place for source governance, persistence, freshness, replay, and alerting.

Implementation:

- Choose Worker-persisted official evidence as the production source of truth. (Complete.)
- Keep API on-demand official realtime only as a local/staging diagnostic fallback unless a launch document explicitly accepts the risk. (Complete.)
- Add response limitations when realtime data is stale, missing, disabled, or diagnostic-only. (Complete.)
- Ensure source freshness is visible in risk output and monitoring. (Complete for API output; monitoring assets remain covered by existing validators.)

Acceptance Criteria:

- Production risk assessment does not depend on unmanaged on-demand official calls.
- Operators can identify freshness state for CWA, WRA, flood-potential, public news, and historical evidence.
- Documentation states what users can and cannot infer when realtime sources are stale or unavailable.

Verification:

- API tests for persisted evidence, stale source, missing source, and diagnostic fallback.
- Worker tests for official adapter persistence and freshness reporting.
- Monitoring validator still passes after metric additions.

Dependencies: P0-03 should be completed first.

### P1-03 Add Production Worker And Scheduler Deployment Path

Status: Accepted

Problem: the single-service Docker path starts API and Web, but not the worker or scheduler runtime required for durable ingestion.

Implementation:

- Define production commands and environment requirements for API, Web, worker, and scheduler. (Complete.)
- Document whether production uses one multi-process service, multiple services, or platform-native scheduled jobs. (Complete.)
- Add health/readiness checks for worker and scheduler operation. (Complete.)
- Ensure worker/scheduler logs, crashes, and source freshness can be observed. (Complete.)

Acceptance Criteria:

- Production deployment docs include API/Web plus worker/scheduler.
- A fresh operator can deploy the full runtime without reading internal phase notes.
- Worker/scheduler failure is detectable through metrics or documented operational checks.

Verification:

- `docker compose config --quiet`
- Worker runtime smoke test with a safe adapter.
- Monitoring assets validator passes after any dashboard/alert updates.

Dependencies: P1-02 should define source-of-truth expectations first.

### P1-04 Convert Source Readiness Docs Into Hard Launch Gates

Status: In Progress

Problem: source readiness, license review, credential review, egress verification, cadence, and ownership are documented as pending or examples. Production beta needs real accepted evidence.

Implementation:

- Add `source_launch_gates` to production-readiness evidence for every production source category. (Complete.)
- Require explicit approval for each production source category when a private `--production-complete` readiness record is validated. (Complete.)
- Keep public discussion/forum/report ingestion disabled until legal/privacy gates are accepted. (Complete in checked-in defaults and validator.)
- Record cadence, source-health expectations, alert routing, and rollback steps. (Complete in evidence schema.)
- Document the private production evidence handoff sequence for source launch gates, basemap, public reports, and calibration dependencies. (Complete in `docs/runbooks/private-production-evidence-handoff.md`.)
- Replace example readiness evidence with environment-specific launch evidence. (Pending private production evidence.)

Acceptance Criteria:

- Every enabled production source has reviewed license, credential, cadence, egress, and alert ownership evidence.
- Disabled/deferred sources are explicitly documented and cannot be accidentally enabled by defaults.
- Production readiness validation checks real launch evidence, not only example files.
- Remaining: private environment-specific source launch evidence must be filled outside the repository and pass `--production-complete` before this item can be Accepted.

Verification:

- `python infra/scripts/validate_source_allowlist.py`
- `python infra/scripts/validate_production_readiness_evidence.py`
- Any new source-specific readiness validator passes.

Dependencies: P1-02 and P1-03 should inform the required evidence.

### P1-05 Add Source Freshness To Readiness And Monitoring

Status: Accepted

Problem: `/ready` checks database and Redis, but production trust also depends on data source freshness, queue lag, and ingestion success.

Implementation:

- Add metrics for last successful adapter run, queue lag, stale source count, and failed runtime jobs. (Complete.)
- Keep `/ready` focused on service readiness unless product requirements explicitly demand freshness-gated readiness. (Complete.)
- Add dashboard panels and alerts for stale official sources and failed ingestion. (Complete.)

Acceptance Criteria:

- Operators can detect stale CWA/WRA/flood-potential/public-news paths. (Complete.)
- Alert thresholds are documented and testable. (Complete.)
- Monitoring assets validate successfully. (Complete.)

Verification:

- `python infra/scripts/validate_monitoring_assets.py`
- Worker tests for metric/freshness summaries.
- API tests if readiness or metrics output changes.

Dependencies: P1-02 and P1-03.

## P2 - Product Trust And Scale

### P2-01 Calibrate Risk Scoring

Status: In Progress

Problem: risk scoring is explainable and deterministic, but the weights and thresholds are heuristic rather than calibrated against replay or ground-truth fixtures.

Implementation:

- Add a calibration manifest and validator that distinguish baseline golden fixtures from production-calibrated replay evidence. (Complete.)
- Add stale official realtime golden fixture coverage. (Complete.)
- Add a 2026-06-08/09 Taiwan Meiyu heavy-rain public-value smoke that samples 100 deterministic user-search locations across all 22 counties/cities, checks no-network honesty, and verifies simulated recent CWA/WRA heavy-rain signal propagation. (Complete.)
- Build a calibration fixture set from accepted historical events, flood-potential data, official reports, and known no-event cases. (Pending accepted production source evidence.)
- Add replay tests for representative Taiwan regions and data-sparse areas. (Pending accepted replay fixture set.)
- Document model version, known bias, missing-source behavior, threshold rationale, event public-value smoke, and private evidence handoff path. (Complete for repo-local boundary in `docs/scoring/README.md` and `docs/runbooks/private-production-evidence-handoff.md`.)
- Preserve current public labels unless a product decision changes them. (Complete for this slice.)

Acceptance Criteria:

- Risk-score changes are versioned and reproducible.
- Calibration fixtures cover high-risk, low-risk, stale-source, and missing-data scenarios.
- Public explanation text remains clear about uncertainty.
- Remaining: private production calibration manifest must pass `--production-complete` with accepted source/replay evidence before this item can be Accepted.

Verification:

- Risk scoring unit tests.
- Golden fixture replay tests.
- `python scripts/event_public_value_smoke.py --sample-size 100 --mode no-network`
- `python scripts/event_public_value_smoke.py --sample-size 100 --mode simulated-heavy-rain`
- Documentation review for model-version notes.

Latest Event Smoke Results:

- `no-network`: 100/100 geocode and risk calls succeeded across 22 counties/cities; 0 failures; 145 warnings. High-concern event areas were not presented as confident low risk without evidence, but 61 locations lacked location-specific evidence, confirming the production source/replay evidence gap.
- `simulated-heavy-rain`: 100/100 geocode and risk calls succeeded across 22 counties/cities; 0 failures; 84 warnings. Injected recent CWA/WRA heavy-rain and water-level signals produced `高` realtime risk and visible official evidence for all 100 sampled locations.
- Reports: `docs/reviews/taiwan-meiyu-heavy-rain-2026-06-08-09-no-network-public-value-smoke.md` and `docs/reviews/taiwan-meiyu-heavy-rain-2026-06-08-09-simulated-heavy-rain-public-value-smoke.md`.

Dependencies: P1-04 should identify trusted calibration data sources.

### P2-02 Redesign Web UX For Public Risk Understanding

Status: Accepted

Problem: the web app is functionally complete but dense and operator-oriented. Public users need a clearer risk narrative, while diagnostics should remain available without overwhelming the first view.

Implementation:

- Keep the map-first experience. (Complete.)
- Make the primary result hierarchy: risk level, confidence, why, evidence, limitations. (Complete.)
- Replace the ambiguous realtime/historical slash heading with a combined risk label plus explicit source basis such as `即時：未知；歷史參考：高`. (Complete.)
- Apply the combined risk level to the searched radius map mask with green/yellow/red risk colors at 85% opacity when a risk assessment is available. (Complete.)
- Move source diagnostics, query details, layer contract details, and freshness details into a secondary diagnostics area. (Complete.)
- Preserve beta limitation copy and user-report disabled/enabled gates. (Complete.)

Acceptance Criteria:

- First-time users can understand the result without reading operator diagnostics. (Complete.)
- Search results or map-selected results show a visible risk-color mask tied to the displayed combined risk. (Complete.)
- Evidence and limitations remain visible and honest. (Complete.)
- Existing API client behavior remains compatible. (Complete.)
- Responsive layout works on desktop and mobile. (Complete.)

Verification:

- `npm run lint --prefix apps/web`
- `npm run typecheck --prefix apps/web`
- `npm test --prefix apps/web`
- `npm run build --prefix apps/web`
- `npm run e2e --prefix apps/web`
- Playwright visual smoke for desktop, expanded diagnostics, and mobile screenshots.

Latest Follow-up Verification:

- `npm test --prefix apps/web` passed, 43 tests.
- `npm run lint --prefix apps/web` passed.
- `npm run typecheck --prefix apps/web` passed.
- `E2E_API_PORT=8011 E2E_WEB_PORT=3111 npm run e2e --prefix apps/web` passed, 16 tests.
- Local live check at `http://127.0.0.1:3000` rendered combined risk, source-basis text, and the risk-color map mask with no form or console errors.

Dependencies: P1-01 and P1-02 should stabilize API behavior first.

### P2-03 Replace Placeholder And Fallback Tile Behavior

Status: Accepted

Problem: layer fallback can expose placeholder tile URLs, and dynamic fallback MVT generation still needs production cache, CDN, expiry, and rollback strategy.

Implementation:

- Replace placeholder tile URLs with explicit disabled/unavailable layer states. (Complete.)
- Use dedicated production layer tables for project overlays. (Complete; hosted tiles now prefer `map_layer_features`/`tile_cache_entries`, with source-table dynamic fallback gated off by default.)
- Define cache-control, tile expiry, CDN/object-storage path, and rollback behavior. (Complete in `docs/runbooks/project-overlay-tiles.md`.)
- Keep local fallback behavior useful for development without implying production readiness. (Complete; `TILE_DYNAMIC_FALLBACK_ENABLED` defaults to local/test only.)

Acceptance Criteria:

- Production never returns placeholder tile hosts. (Complete.)
- TileJSON accurately reports availability, attribution, freshness, and cache expectations. (Complete.)
- Operators can refresh or roll back overlay tiles. (Complete.)

Verification:

- API tests for available, unavailable, and disabled layer states.
- Tile repository tests for status gating and dynamic fallback control.
- OpenAPI and migration validators pass.

Dependencies: P1-04 for source readiness and P1-05 for freshness metrics.

### P2-04 Improve API Error Propagation In Web Client

Status: Accepted

Problem: the frontend API client collapses many backend failures into generic `Request failed: <status>` messages, which weakens user guidance and operator debugging.

Implementation:

- Parse structured API error payloads when present.
- Map common errors to localized user-facing messages.
- Preserve timeout and abort behavior.
- Avoid leaking internal details to public users.

Acceptance Criteria:

- Users see actionable messages for rate limit, disabled reports, geocode miss, stale/unavailable data, and server failure.
- Tests cover structured error payloads, non-JSON errors, timeout, and abort.
- Existing request cancellation semantics remain unchanged.

Verification:

- `npm test --prefix apps/web`
- `npm run typecheck --prefix apps/web`
- Playwright smoke for at least one API failure path.

Completed:

- Added typed frontend API request errors with structured payload parsing for `error`, `detail.error`, `detail`, and direct `{code,message}` responses.
- Mapped public-safe localized messages for rate limits, disabled features, not found/geocode miss, unavailable data, bad requests, and server failures without rendering backend messages.
- Preserved timeout and abort handling; superseded searches still suppress user-visible errors.
- Added user-report `rate_limited` handling alongside existing disabled and repository-unavailable states.
- Added unit tests for structured errors, nested/direct payloads, non-JSON server failures, timeout, abort, report gates, and report display states.
- Added Playwright smoke coverage for a structured `503 repository_unavailable` risk-assessment failure.

Verification Results:

- `npm test --prefix apps/web` passed, 42 tests.
- `npm run lint --prefix apps/web` passed.
- `npm run typecheck --prefix apps/web` passed.
- `npm run e2e --prefix apps/web` passed, 16 tests.
- `npm audit --prefix apps/web` passed, 0 vulnerabilities.
- `npm run build --prefix apps/web` passed.
- `python -m pytest apps/api/tests -q` passed, 235 tests.
- `cd apps/api && python -m mypy app --no-incremental` passed.
- `python infra/scripts/validate_openapi.py` passed.
- `python infra/scripts/validate_contract_fixtures.py` passed.
- `python infra/scripts/validate_source_allowlist.py` passed.
- `python infra/scripts/validate_migrations.py` passed.
- `python infra/scripts/validate_monitoring_assets.py` passed.
- `python infra/scripts/validate_production_readiness_evidence.py` passed.
- `python infra/scripts/validate_basemap_cdn_evidence.py` passed.
- `python infra/scripts/validate_public_reports_launch_evidence.py` passed.
- `python infra/scripts/validate_risk_calibration_manifest.py` passed.
- `python infra/scripts/validate_flood_potential_import.py` passed.
- `docker compose config --quiet` passed.
- `python scripts/event_public_value_smoke.py --sample-size 100 --mode no-network` passed, 0 failures.
- `python scripts/event_public_value_smoke.py --sample-size 100 --mode simulated-heavy-rain` passed, 0 failures.
- `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\public-beta-local-gate.ps1` passed.

Dependencies: P0-05 if `429` handling is added.

## Execution Order

1. Complete all P0 items before claiming production-beta readiness.
2. Execute P1-01 after P0-01 to reduce refactor risk.
3. Execute P1-02 before P1-03/P1-05 so deployment and monitoring match the chosen source-of-truth path.
4. Execute P1-04 before enabling any new production data source.
5. Start P2 UX and scoring work only after the runtime/source semantics are stable enough to avoid redesign churn.

## Acceptance Definition

The roadmap is considered accepted when:

- All P0 items are `Accepted`.
- Production deployment includes API, Web, worker, and scheduler or explicitly documented platform-native equivalents.
- Enabled production sources have reviewed readiness evidence.
- Monitoring can detect stale source data and ingestion failures.
- Public risk output remains explainable, evidence-backed, and honest about uncertainty.
