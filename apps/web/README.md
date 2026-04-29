# Flood Risk Web

Next.js Phase 1 map-first web experience.

## Entry points

- Next.js app route: `app/page.tsx`
- Docker Compose command: `npm ci && npm run dev -- --hostname 0.0.0.0 --port 3000`
- Local Next.js command after installing dependencies: `npm run dev`

Dependencies are locked in `package-lock.json`. Docker Compose mounts named
`web-node-modules` and `web-next-cache` volumes so Linux container dependencies
and Next.js build output do not overwrite Windows host files.
