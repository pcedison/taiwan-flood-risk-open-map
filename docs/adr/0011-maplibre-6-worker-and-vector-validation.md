# ADR-0011: MapLibre 6 Worker Packaging and Vector Validation

## Title

Serve the locked MapLibre 6 ESM worker and shared module together

## Status

Proposed

## Date

2026-10-01

## Context

GHSA-jrc7-96c5-q579 affects MapLibre through 6.4.0; the patched floor is
6.4.1. PR #272 upgraded 5.24.0 to 6.6.0, passed raster-based E2E checks, and
was reverted by #273 after production PMTiles remained in the loading state.
The large leaf/grid shown during that failure is the app's loading fallback.

A local production build with 6.4.1 reproduced the failure using the current
public production style and real archive. The emitted hashed worker retained
its relative import of `./maplibre-gl-shared.mjs`, while Turbopack emitted
hashed shared filenames. The archive header returned HTTP 206, but the map
never loaded vector features or reached the ready UI. MapLibre's versioned
Next.js guidance documents this worker packaging requirement.

## Decision

Pin MapLibre to the reviewed 6.4.1 security release. Copy its worker and shared
module unchanged from the installed, locked npm package into
`apps/web/public/maplibre/` before both development and production builds.
Call `setWorkerUrl()` with the same-origin public worker path before creating
a map. Include `public/` in the Docker runtime image. Keep the existing CSP;
its `worker-src 'self' blob:` already permits these assets.

Retain the PMTiles ownership-aware registration cleanup and validate it with
a unit test. Add an explicit online vector suite separate from fixture raster
E2E. The vector suite builds the local app, reads real public PMTiles Range
responses and glyphs, and verifies desktop/mobile ready state, actual rendered
roads and Chinese labels, search zoom/center/marker, risk circle presentation
below labels, attribution sanitation, and teardown/remount. Visually review
the overview and street-level screenshots. Risk responses remain fixtures;
the suite neither calls production risk APIs nor connects to a database.

## Consequences

- Browser compatibility now requires WebGL2, as required by MapLibre 6.
- Generated vendor assets are ignored by Git and ESLint. They are regenerated
  from the lockfile on each build, rather than checked in or hand-modified.
- Docker packaging is part of the migration. A build that omits `public/`
  would reintroduce the worker failure even if local browser checks pass.
- The vector suite depends on external basemap/glyph availability. Its
  loopback-only relay preserves the archive's actual bytes, status and ranges
  while supplying test CORS headers; no production permissions change.
- Map-ref inspection lives only in test code and relies on React hook internals;
  review that helper when changing React. Raster tests do not prove vector
  compatibility, and a skipped online check is not a successful migration.

## References

- [MapLibre 6.4.1 Next.js installation guidance](https://github.com/maplibre/maplibre-gl-js/blob/v6.4.1/docs/index.md#installation)
- [MapLibre v5 to v6 migration](https://github.com/maplibre/maplibre-gl-js/blob/v6.4.1/docs/guides/v5-to-v6-migration-guide.md)
- [MapLibre advisory](https://github.com/advisories/GHSA-jrc7-96c5-q579)
- [Original upgrade #272](https://github.com/pcedison/taiwan-flood-risk-open-map/pull/272)
- [Original rollback #273](https://github.com/pcedison/taiwan-flood-risk-open-map/pull/273)


## Security integration update (2026-10-21)

Retain the reviewed MapLibre 6.4.1 pin and worker pair. Raise minimum Next and
eslint-config-next to 16.3.8, sharp to 0.35.5; keep brace-expansion 5.0.12 and
js-yaml 5.4.1, and override source-map-js to 1.2.2.

The latest stable/canary Next ESLint plugin metadata still uses fast-glob 3.3.1;
its micromatch/braces chain includes GHSA-vfj7-8cjw-p6xm with no patched braces
release. Scope an npm alias from fast-glob to tinyglobby 0.2.17 only under
@next/eslint-plugin-next. The locked plugin calls only
`globSync(string, { onlyDirectories: true })`; its sole consumer joins paths and
checks directories with fs. Tinyglobby's relative results/trailing separators
resolve to equivalent directories. This is not a complete fast-glob API
replacement. Re-review the installed plugin's call sites on upgrades. Tests
exercise directory discovery (including braces, arrays, Windows paths) and the
actual Next internal-link lint rule. Keep all existing lint configurations;
do not suppress audit or downgrade Next ESLint to 14.

The vector suite can also target an already-running local Docker web process via
`E2E_VECTOR_BASE_URL=http://127.0.0.1:<port>`, retaining the same assertions.
The container must run only Next, overriding the application entrypoint so no
API, worker, migrations, or database is started. Confirm both public ESM assets
match the installed package and run the suite against the actual image.


Docker vector validation must set the existing public style build argument:
`--build-arg NEXT_PUBLIC_BASEMAP_STYLE_URL=https://basemap.floodrisk.cc/styles/taiwan-open/2026-05-11/style.json`.
Next bakes CSP headers during build. Setting only runtime BASEMAP_STYLE_URL or
CSP_EXTRA_ORIGINS cannot add that origin to already-built headers. An initial
local image without this argument correctly blocked its PMTiles requests;
retain that failure evidence rather than disabling CSP. No policy code changes
are needed for the configured build.


## Fresh local validation (2026-10-21)

- Clean npm ci; npm audit: 0 vulnerabilities. No audit suppression.
- Lint and TypeScript checks passed; 79 unit tests passed.
- Next plugin alias compatibility: 2 tests passed on Linux Node 22 using a
  read-only mount and network-disabled container, in addition to Windows checks.
- Existing desktop/mobile E2E: 18 passed, including production build.
- Initial local real-vector suite: 2 passed. Final strengthened suite against
  the configured Docker image: 2 passed, including source/tiles/roads and browser
  errors after document unload/reload. The ownership unit test covers protocol
  cleanup separately; document reload alone does not prove React-only unmount.
- Full Docker image built successfully; public worker/shared module bytes match
  installed MapLibre. Only Next was started for browser validation, then stopped.
- Four desktop/mobile overview/search screenshots inspected. Existing dense
  street-label overlap remains visible; the basemap style was not redesigned.
- Independent read-only review found no remaining blockers after strengthening
  remount checks and documenting alias/build-configuration limits.

At the local-validation checkpoint, no commit, push, new security PR, CI rerun,
merge, or deployment had been performed. Original 13 security files remain hash-identical to the
preserved snapshot; PR #422 is separate and unchanged.

## Security CI follow-up (2026-10-24, PR #429)

The existing frontend audit gate reported the published Next.js advisories
GHSA-2464-fhr4-w9xw, GHSA-p3m5-59mp-jv5r and GHSA-673q-mjm6-r5xr, plus Zod
GHSA-mrhx-c7xc-m3w5. Pin Next and its ESLint config to the minimum patched
16.x release, 16.4.1. Pin the transitive React Hooks lint dependency Zod to
4.6.6 via an override; do not add a runtime Zod dependency or relax audit.
React, MapLibre, PMTiles and existing security overrides remain unchanged.

The installed Next ESLint 16.4.1 call site still uses only globSync with
onlyDirectories for root discovery. The scoped tinyglobby 0.2.17 alias is
retained and rechecked by the installed-plugin directory/link-rule tests,
included in all 79 passing unit tests. This is compatibility with this locked
plugin, not a general fast-glob substitute. Re-review future plugin upgrades.

Clean npm ci and npm audit reported zero vulnerabilities. Lint, typecheck,
production build and all 18 existing local desktop/mobile E2E tests passed.
Detailed real-vector and final-head CI results belong to PR #429 and its
security verification record. Docker image validation was not run in this
follow-up: the local Docker daemon pipe was unavailable. Do not reuse the
2026-10-21 Docker results as proof of this new Next version's image.
