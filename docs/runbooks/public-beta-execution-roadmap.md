# Public Beta Execution Roadmap

Status: active execution plan
Date: 2026-05-04

Change inventory: `docs/runbooks/public-beta-change-inventory-2026-05-04.md`
Readiness note: `docs/runbooks/public-beta-readiness-2026-05-04.md`
Open-data geocoder import: `docs/runbooks/open-data-geocoder-import.md`

This roadmap defines the work that can move forward without new manual input
from the project owner. It exists to stop scope drift and to turn the current
prototype into a locally verifiable public-beta candidate.

The controlling goal is simple:

> A user can enter an unfamiliar Taiwan location, the app shows how precisely it
> was located, runs a risk query only when the location is acceptable, and
> displays risk level, evidence, and limitations without pretending the data is
> stronger than it is.

## Current Stage

The project is in the public-beta MVP hardening stage. The local MVP gate for
unknown Taiwan address lookup is now green, but the project is not public-beta
deployment ready yet because production data/assets/secrets still need source
evidence and environment setup.

Completed:

- API contracts exist for geocoding, risk assessment, evidence, admin sources,
  user reports, and readiness.
- Geocoding has explicit precision semantics and frontend confirmation behavior.
- `/v1/geocode` delegates to an open-data-first provider chain.
- Reviewed CSV/JSONL geocoder rows can be mounted through
  `GEOCODER_OPEN_DATA_PATHS` without changing code.
- Local unfamiliar-address fixtures prove exact-address, road/lane, admin-area,
  and no-match behavior without network access.
- Frontend E2E now includes realistic local API behavior, not only hand-written
  happy-path mocks.
- Risk scoring can combine official realtime signals, historical evidence, DB
  evidence, and non-blocking public-news enrichment.
- CWA/WRA source gates are explicit and can be disabled honestly for local MVP.
- Flood-potential import metadata has a manifest schema, validator, and dry-run
  import command planner.
- Basemap smoke coverage proves production-like open raster basemap behavior
  without OSM or TGOS tiles.
- Production readiness, user-report governance, and source approval docs/checks
  have substantial scaffolding.

Not complete:

- The local geocoder still uses a small project-controlled fixture/gazetteer set;
  production needs a larger reviewed open-data import.
- CWA and WRA live integrations are intentionally disabled until a live source
  smoke is recorded.
- Flood-potential SHP packages still need actual retrieval, checksum evidence,
  and processed output; the manifest validator is ready, not the production
  layer itself.
- Production PMTiles/style assets still need deployed URL, attribution, CORS,
  range-request, and cache evidence before public testing.
- Public beta readiness needs a final go/no-go note tied to the checklist.

## Non-Negotiable MVP Line

Do not expand PTT, Dcard, social crawling, direct user reports, or TGOS work
until the following gate passes locally:

1. Unknown Taiwan address lookup returns candidate precision and limitations.
2. Exact address, road/lane fallback, POI fallback, admin fallback, and no-match
   cases are tested.
3. Risk assessment runs for acceptable precision only.
4. The UI visibly distinguishes exact, road/lane, POI, admin-area, map-click,
   and no-match states.
5. API, worker, repo-level, frontend unit, frontend typecheck/lint, and E2E
   checks pass.

## Execution Principles

- Open-source/open-data first. TGOS remains optional and future-only.
- Disabled live sources must be honest: they return clear limitations and do not
  silently downgrade user trust.
- Public Nominatim is development fallback only. Production should use
  project-controlled local/open-data geocoding.
- Public beta can launch without live CWA/WRA credentials if the UI states those
  sources are disabled and the smoke evidence records that fact.
- Every work package ends with tests and a short status note.

## Work Package 0: Stabilize The Baseline

Goal: stop losing progress in a large dirty worktree.

Status: completed 2026-05-04.

Tasks:

- Produce a change inventory grouped by API, web, workers, infra, docs, and
  tests.
- Identify changes that are unrelated to public-beta MVP and leave them
  untouched.
- Keep the current branch and avoid reverting user or prior work.
- Establish the baseline command set:
  - `python -m pytest apps\api\tests -q`
  - `python -m pytest apps\workers\tests -q`
  - `python -m pytest tests -q`
  - `npm test` in `apps\web`
  - `npm run typecheck` in `apps\web`
  - `npm run lint` in `apps\web`
  - `npm run e2e` in `apps\web`

Definition of done:

- The current status is documented.
- The test command list is confirmed.
- No unrelated files are reverted or reformatted.

## Work Package 1: Geocoding Precision Contract

Goal: make geocoding truthfulness machine-readable.

Status: completed 2026-05-04.

API changes:

- Extend `PlaceCandidate` with precision metadata:
  - `precision`: `exact_address`, `road_or_lane`, `poi`, `admin_area`,
    `map_click`, or `unknown`.
  - `matched_query`: the normalized/fallback query that produced the candidate.
  - `requires_confirmation`: true when the result is too broad for automatic
    risk assessment.
  - `limitations`: short user-facing strings explaining the fallback.
- Keep backward-compatible fields where practical: `name`, `type`, `point`,
  `source`, `confidence`, and `admin_code`.

Backend behavior:

- Exact address and high-confidence road/lane candidates can trigger risk.
- POI candidates can trigger risk only when confidence is high enough and the UI
  clearly labels the result as a POI.
- Admin-area candidates must not silently trigger precise risk. They should ask
  for confirmation or map click.
- No-match cases must clear stale risk results.

Tests:

- Add API tests for exact address, road/lane fallback, POI fallback, admin-area
  fallback, and no-match.
- Add OpenAPI schema expectations for the new fields.
- Add frontend unit/E2E assertions that risk is not called for
  `requires_confirmation=true`.

Definition of done:

- Unknown-address behavior is explicit in the API contract.
- Frontend no longer has to infer precision from source string hacks.

## Work Package 2: Open Geocoder Provider Chain

Goal: replace route-level fallback logic with a provider chain that can grow
without becoming fragile.

Status: completed 2026-05-04 for local MVP. Production still needs a larger
reviewed open-data import, but public TGOS is not an MVP blocker.

Provider order for MVP:

1. `LocalTaiwanAddressProvider`: project-controlled fixtures and imported
   open-data address/road/POI rows.
2. `OpenStreetMapProvider`: project-controlled OSM/Nominatim/Photon-compatible
   lookup when available.
3. `NominatimDevelopmentFallbackProvider`: public Nominatim for local
   diagnostics only, with cache and attribution.
4. `WikimediaPoiFallbackProvider`: POI-only fallback, never treated as exact
   address geocoding.

Implementation targets:

- Move provider orchestration into `apps/api/app/domain/geocoding/`.
- Keep external HTTP calls behind provider interfaces for testability.
- Add a small local fixture dataset for unfamiliar Taiwan locations that are not
  hardcoded landmarks.
- Attach source, precision, matched query, confidence cap, and limitation text
  in one place.

Definition of done:

- `/v1/geocode` delegates to the provider chain.
- Tests can prove provider order and fallback behavior without network access.
- Public Nominatim is not required for the local MVP test suite.

## Work Package 3: Unknown Address Local E2E

Goal: prove the user-facing workflow, not just isolated API functions.

Status: completed 2026-05-04.

Required scenarios:

- New exact/near-exact address fixture returns a candidate and risk assessment.
- Road/lane fallback returns a candidate, labels fallback precision, and still
  assesses when acceptable.
- Admin-area-only fallback shows confirmation/map-click requirement and does not
  call risk automatically.
- Missing address clears previous risk results.

Implementation targets:

- API-level integration tests using real provider fixtures.
- Frontend E2E with realistic API behavior, not only hand-written happy-path
  mocks.
- A local smoke script that runs the representative unknown-address probes and
  prints pass/fail results.

Definition of done:

- A single local command can demonstrate unfamiliar-address lookup, risk call,
  risk labels, and limitations.
- The smoke output includes the searched text, selected candidate, precision,
  confidence, risk levels, and missing-source messages.

## Work Package 4: Official Data Source Shells

Goal: make CWA/WRA non-blocking but honest.

Status: completed 2026-05-04 for disabled/local MVP behavior. Live source
smokes remain a production-readiness task.

CWA:

- Add or tighten adapter configuration for `CWA_API_AUTHORIZATION`.
- Keep `SOURCE_CWA_API_ENABLED=false` by default.
- Fixture-backed tests must show disabled, failed, stale, and healthy states.
- Cache/persist observations; never call CWA once per user search.

WRA:

- Prefer the public government open-data realtime water-level path.
- Keep `SOURCE_WRA_API_ENABLED=false` until a live smoke is recorded.
- If a token endpoint is selected later, keep it behind `WRA_API_TOKEN`.
- UI limitation must say realtime water-level data is raw and may be delayed,
  interrupted, abnormal, or unverified.

Definition of done:

- Local MVP passes with CWA/WRA disabled.
- Enabling CWA/WRA later is an environment/config change plus smoke evidence,
  not a rewrite.

## Work Package 5: Flood-Potential Offline Layer

Goal: use flood-potential data as a planning layer without creating a fake live
warning product.

Status: completed 2026-05-04 for manifest schema, validation, and import command
planning. Actual SHP retrieval/import/output remains pending.

Tasks:

- Define a manifest schema for source URL, retrieval date, license notes,
  rainfall scenario, file checksums, and processing output.
- Add an import script target for SHP to PostGIS or PMTiles/MVT.
- Add tests for manifest validation and risk-layer metadata.
- Ensure UI text says this is a historical/planning potential layer, not live
  flood detection.

Definition of done:

- A reviewed SHP package can be imported repeatably.
- The layer appears with scenario notes, attribution, and limitations.

## Work Package 6: Basemap Static Assets

Goal: remove public OSM tile dependency before public testing.

Status: partially complete. Production-like E2E smoke passes; deployed PMTiles
or open raster asset evidence still needs to be recorded before public beta.

Tasks:

- Keep MapLibre plus PMTiles/Protomaps-compatible style configuration.
- Validate PMTiles/style URL, attribution, CORS, range requests, and cache
  headers through an evidence file.
- Keep public OSM community tiles as local-development fallback only.

Definition of done:

- Basemap smoke passes with project-controlled static assets or explicitly
  reports that public-beta map assets are not ready.

## Work Package 7: Public Beta Gate

Goal: turn readiness into an objective go/no-go.

Status: completed 2026-05-04 as a blocked hosted public-beta decision. The
local MVP gate passes; hosted public beta remains blocked on production
evidence and environment setup.

Gate checklist:

- Unknown-address local E2E passes.
- API, workers, repo tests, web unit, typecheck, lint, and E2E pass.
- CWA/WRA are either live-smoked or visibly disabled with limitations.
- Flood-potential layer has source/attribution/scenario metadata.
- Basemap has project-controlled PMTiles/style evidence or remains blocked.
- PTT/Dcard/user reports remain disabled.
- Zeabur/env/secrets are not started until the local MVP gate is green.

Definition of done:

- One public-beta readiness note says `ready`, `blocked`, or `not ready`, with
  reasons tied to the checklist above.

## Immediate Next Engineering Sequence

1. Work Package 1: precision metadata in the geocode contract. Completed on
   2026-05-04.
2. Work Package 2: provider chain with fixture-backed open geocoder. Completed
   on 2026-05-04.
3. Work Package 3: unknown-address local E2E and smoke script. Completed on
   2026-05-04.
4. Work Package 4: CWA/WRA disabled source shells. Completed on 2026-05-04 for
   local MVP.
5. Work Package 5: flood-potential manifest and validator. Completed on
   2026-05-04 for metadata validation.
6. Public-beta readiness note. Completed on 2026-05-04.
7. No-secret local public-beta gate command. Completed on 2026-05-04.

This ordering is intentional: if unknown-address geocoding is not trustworthy,
additional data sources only make the product look more complete than it is.

## Progress Notes

2026-05-04:

- Added geocode precision metadata to `PlaceCandidate`: `precision`,
  `matched_query`, `requires_confirmation`, and `limitations`.
- Added backend metadata for local gazetteer, local admin-area centroids,
  Nominatim fallback, and Wikimedia POI candidates.
- Added frontend behavior that stops automatic risk assessment when a geocode
  candidate requires confirmation, such as admin-area-only matches.
- Added E2E coverage proving admin-area geocoding clears stale risk results and
  does not call `/v1/risk/assess`.
- Verified baseline:
  - `python -m pytest apps\api\tests -q`: 131 passed
  - `python -m pytest apps\workers\tests -q`: 247 passed
  - `python -m pytest tests -q`: 64 passed
  - `npm test`: 20 passed
  - `npm run typecheck`: passed
  - `npm run lint`: passed
  - `npm run e2e`: 10 passed
- Added `scripts/unknown_address_smoke.py`; verified:
  - exact unfamiliar address geocodes and returns historical high risk.
  - road/lane fallback geocodes and can assess with lower precision.
  - admin-area fallback requires confirmation and does not run risk.
  - no-match returns no candidate and clears stale risk.
- Added CWA/WRA per-source gates so local MVP can explicitly run with official
  realtime sources disabled.
- Added flood-potential import manifest template, validator tests, and
  `infra/scripts/import_flood_potential_layer.py` dry-run/import command planner.
- Added `docs/runbooks/public-beta-readiness-2026-05-04.md` to separate the
  green local MVP gate from blocked hosted public-beta evidence.
- Added `scripts/public-beta-local-gate.ps1` as the no-secret local gate command.
- Added the file-backed open-data geocoder path and
  `docs/runbooks/open-data-geocoder-import.md`.
