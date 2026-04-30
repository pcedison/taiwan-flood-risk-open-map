# Flood Risk Web

Next.js Phase 1 map-first web experience with evidence UI hardening.

## Entry points

- Next.js app route: `app/page.tsx`
- Docker Compose command: `npm ci && npm run dev -- --hostname 0.0.0.0 --port 3000`
- Local Next.js command after installing dependencies: `npm run dev`

Dependencies are locked in `package-lock.json`. Docker Compose mounts named
`web-node-modules` and `web-next-cache` volumes so Linux container dependencies
and Next.js build output do not overwrite Windows host files.

## Current scope

- Map-first risk query shell.
- Address/geocode query flow against the API contract.
- Risk summary and evidence/freshness rendering groundwork.
- Evidence drawer that fetches the full `/v1/evidence/{assessment_id}` list and
  falls back to risk-response previews on failure.
- Node unit tests for risk/evidence display helpers.
- Playwright smoke coverage for the core map-risk path.

## Placeholder boundary

- `server-placeholder.mjs` is a fallback artifact only. Docker Compose and
  normal local development should use the Next.js dev runtime.
- Frontend unit tests now cover data-shaping/display helpers; component-level
  unit coverage can still expand later.
- Tile/layer production UX remains pending the geo/tile pipeline.
