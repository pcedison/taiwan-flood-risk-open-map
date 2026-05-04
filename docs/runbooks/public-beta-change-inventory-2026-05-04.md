# Public Beta Change Inventory

Status: snapshot
Date: 2026-05-04

This is a non-destructive snapshot of the current dirty worktree. It is not a
claim that all listed work is complete or public-beta ready. Its purpose is to
separate the public-beta MVP path from accumulated parallel work.

## Summary Counts

Current changed/untracked areas:

- API: 21 files
- Web: 8 files
- Workers: 17 files
- Docs: 22 files
- Infra: 5 files
- Repo-level tests: 4 files
- Root/config/other: 5 files

The tree is too broad to treat as a single finished feature. Public-beta work
must be narrowed to the unknown-address and open-data MVP line.

## MVP-Critical Areas

These areas are directly related to the current public-beta blocker:

- `apps/api/app/api/routes/public.py`
  - Contains `/v1/geocode` and `/v1/risk/assess`.
  - Current geocoding behavior is still route-level orchestration.
- `apps/api/app/domain/geocoding/`
  - Contains Taiwan query cleanup and fallback expansion helpers.
  - Needs provider-chain ownership and precision semantics.
- `apps/api/app/domain/history/`
  - Contains limited local historical records and public-news enrichment.
  - Useful for local risk evidence, but not a substitute for real geocoding.
- `apps/web/app/page.tsx`
  - Contains the user search flow and risk request trigger.
  - Must stop automatically assessing broad/admin-only geocode results.
- `apps/web/tests/e2e/map-risk.spec.ts`
  - Exercises frontend behavior, but still relies heavily on mocked API routes.
  - Needs a stronger unfamiliar-address smoke path.
- `docs/runbooks/public-beta-mvp-open-data-plan.md`
  - Records TGOS optional status and open-data source decisions.
- `docs/runbooks/public-beta-execution-roadmap.md`
  - Defines execution order and acceptance gates.

## Parked Areas

These areas may contain useful prior work, but should not drive the next
engineering sequence:

- PTT, Dcard, forum, and social adapters.
- Direct user-report ingestion beyond disabled/governed scaffolding.
- Zeabur production deployment, DNS, secrets, and monitoring.
- TGOS integration.

They remain parked until unknown-address E2E and public-beta MVP gates pass.

## Main Risk

The current project has many legitimate-looking components, but the most
important user journey is still under-proven:

1. User enters an unfamiliar Taiwan address or location.
2. Backend returns a candidate with honest precision metadata.
3. Frontend renders the precision and limitations.
4. Risk assessment runs only when the location is precise enough.
5. Risk levels and evidence/limitations are visible.

Until that chain passes locally, additional source integrations will create the
appearance of progress without resolving the blocker.

## Next Controlled Scope

Proceed in this order:

1. Geocoding precision contract.
2. Open geocoder provider chain.
3. Unknown-address local E2E and smoke script.
4. Full local test baseline.
5. CWA/WRA disabled-or-smoked source shells.
6. Flood-potential offline import plan and validator.
7. Basemap PMTiles evidence.

No parked area should be expanded during steps 1 through 4.
