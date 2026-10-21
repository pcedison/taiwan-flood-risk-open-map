# Flood Risk Web

Next.js Phase 1 map-first web experience with evidence UI hardening.

## Entry points

- Next.js app route: `app/page.tsx`
- Docker Compose command: `npm ci && npm run dev -- --hostname 0.0.0.0 --port 3000`
- Local Next.js command after installing dependencies: `npm run dev`

Dependencies are locked in `package-lock.json`. Docker Compose mounts named
`web-node-modules` and `web-next-cache` volumes so Linux container dependencies
and Next.js build output do not overwrite Windows host files.

MapLibre is pinned to the reviewed security release 6.4.1. Its ESM worker and
shared module are copied together from the installed package to
`public/maplibre/` by `predev`/`prebuild`; the Docker runtime includes these
assets. Do not replace this with Turbopack's hashed default worker URL. MapLibre
6 requires WebGL2. See [ADR-0011](../../docs/adr/0011-maplibre-6-worker-and-vector-validation.md).

## Basemap configuration

Production should use an open-source basemap hosted as a MapLibre style JSON,
or a PMTiles archive behind low-cost object storage/CDN.

- `NEXT_PUBLIC_BASEMAP_STYLE_URL`: preferred production path. MapLibre receives
  this style JSON URL directly, so R2/CDN can host the complete style.
- `NEXT_PUBLIC_BASEMAP_KIND=pmtiles` with `NEXT_PUBLIC_BASEMAP_PMTILES_URL`:
  builds a minimal vector style around a `pmtiles://` source.
- `NEXT_PUBLIC_BASEMAP_KIND=raster` with `NEXT_PUBLIC_BASEMAP_RASTER_TILES`:
  development or temporary raster fallback. Multiple templates can be comma
  separated.

If no basemap env is set, local development falls back to the public
OpenStreetMap raster tile endpoint. That fallback is only for local/dev use and
must not be treated as the production basemap path.

## Current scope

- Map-first risk query shell.
- Address/geocode query flow against the API contract.
- Risk summary and evidence/freshness rendering groundwork.
- Evidence drawer that fetches the full `/v1/evidence/{assessment_id}` list and
  falls back to risk-response previews on failure.
- Node unit tests for risk/evidence display helpers.
- Playwright smoke coverage for the core map-risk path.

## Test commands

- `npm run e2e`: runs the Playwright desktop and mobile projects. The
  Playwright dev server injects a production-like open raster basemap pointed at
  `https://basemap.example.test/{z}/{x}/{y}.png`; e2e tests mock that tile host
  and must not depend on real external tile providers.
- `npx playwright test tests/e2e/open-basemap-smoke.spec.ts`: runs only the open
  basemap browser smoke.
- `npm run e2e:vector`: separately builds and tests the local app on desktop and
  Pixel 7 against the reviewed public production style and real PMTiles archive.
  This suite requires network access to the basemap and Protomaps glyph hosts.
  Only risk API responses are fixtures. A test-only relay forwards unchanged
  HTTP Range bytes because the CDN permits its production origin rather than
  loopback; it does not change CDN CORS settings. The suite checks real rendered
  roads and Chinese labels, map-ready, search zoom/center/marker, overlay order
  and opacity, paired worker responses, attribution sanitation, and remount.
  Inspect both map screenshots under `test-results/` before approving a major
  map dependency upgrade; passing the raster suite alone is insufficient.
  `VECTOR_BASEMAP_STYLE_URL` and `E2E_VECTOR_WEB_PORT` can override its style
  and local port. Map-ref diagnostics use existing React hooks only inside the
  test and may need review after a React update.

## Placeholder boundary

- `server-placeholder.mjs` is a fallback artifact only. Docker Compose and
  normal local development should use the Next.js dev runtime.
- Frontend unit tests now cover data-shaping/display helpers; component-level
  unit coverage can still expand later.
- Tile/layer production UX remains pending the geo/tile pipeline.


### Scoped lint dependency replacement

The security lockfile replaces fast-glob only inside the Next ESLint plugin
with tinyglobby 0.2.17 to remove the unpatched braces dependency. This preserves
the locked plugin's directory-glob use; it is not a full fast-glob replacement.
Re-review `get-root-dirs` and run `next-root-dirs.test.ts` when updating the
plugin. Do not replace this with audit suppression or an older Next lint config.

For the same vector regression against a prebuilt local Docker web server, set
`E2E_VECTOR_BASE_URL=http://127.0.0.1:<port>` and run `npm run e2e:vector`.
This skips building/starting a second local web server. The Docker process must
run only Next with the application entrypoint overridden; no API/DB is needed.
