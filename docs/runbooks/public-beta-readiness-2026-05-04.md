# Public Beta Readiness Note

Date: 2026-05-04
Status: blocked for hosted public beta
Local MVP gate: passed

This note records the public-beta gate after the open-data-first geocoding
work. It separates what is locally complete from what still needs production
evidence, credentials, or deployed assets.

## Local MVP Gate

Passed.

Verified behavior:

- Unknown exact Taiwan address geocodes from local open-data fixtures and runs a
  risk assessment.
- Road/lane fallback geocodes with lower precision and can still run risk when
  acceptable.
- Admin-area-only fallback asks for confirmation or map click and does not call
  risk automatically.
- No-match lookup returns no candidate and clears stale risk.
- The frontend shows geocode precision and limitation text.
- TGOS is not required for MVP.
- CWA/WRA can remain disabled while returning honest limitation messages.
- PTT, Dcard, forums, and public user reports remain disabled/frozen.

Verification run:

```text
python -m pytest apps\api\tests -q       -> 131 passed
python -m pytest apps\workers\tests -q   -> 247 passed
python -m pytest tests -q                -> 64 passed
npm test                                 -> 20 passed
npm run typecheck                        -> passed
npm run lint                             -> passed
npm run e2e                              -> 10 passed
python scripts\unknown_address_smoke.py  -> UNKNOWN_ADDRESS_SMOKE passed
python -m ruff check <changed python>    -> passed
```

Repeat the local gate with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\public-beta-local-gate.ps1
```

Repeat the hosted no-secret smoke after each Zeabur deployment with:

```powershell
python scripts\hosted_public_beta_smoke.py --base-url https://floodrisk.zeabur.app
```

## Hosted Public Beta Decision

Blocked.

The blocker is not TGOS or local address search anymore. The remaining blockers
are production evidence and environment setup that should not be faked in the
repository.

Required before hosted public beta:

- Zeabur production-beta environment exists, with reviewed `APP_ENV`,
  `DATABASE_URL`, `REDIS_URL`, admin token, and alert routes.
- `/health` exposes `deployment_sha`, either from `DEPLOYMENT_SHA` or a
  provider-supplied commit env var.
- Production CWA/WRA decision is recorded. They may stay disabled for public
  beta, but the deployed UI/API must show that limitation.
- Flood-potential SHP package is actually retrieved, checksummed, processed,
  and recorded in a production-complete manifest.
- Basemap PMTiles/style or open raster assets are deployed to operator-owned
  static storage/CDN with attribution, CORS, range request, cache, screenshot,
  and browser-network evidence.
- Production readiness evidence and basemap CDN evidence pass their
  `--production-complete` validators in a private ops-controlled location.
- On-call, rollback, runtime smoke, Playwright, alert route, and backup restore
  evidence are recorded for staging or production beta.

## Engineering Completed In This Stage

- Added geocode precision metadata to the public API contract.
- Moved geocoding into an open-data-first provider chain.
- Added local unfamiliar Taiwan address fixtures.
- Added `GEOCODER_OPEN_DATA_PATHS` so reviewed CSV/JSONL geocoding rows can be
  mounted without changing code.
- Added provider-chain tests without network dependency.
- Added frontend confirmation behavior for broad geocodes.
- Added live local E2E coverage for unknown-address behavior.
- Added `scripts/unknown_address_smoke.py`.
- Added `EVIDENCE_REPOSITORY_ENABLED=false` support so local smoke/E2E can run
  without a production database.
- Added per-source CWA/WRA gates.
- Added flood-potential manifest template, validator, and dry-run import command
  planner.
- Updated the public-beta execution roadmap with completed work packages.
- Added `scripts/public-beta-local-gate.ps1` as the no-secret repeatable local
  gate.
- Added `scripts/hosted_public_beta_smoke.py` for deployed Zeabur public-endpoint
  checks.

## Next Non-Manual Work

The remaining work that can continue without private production credentials is:

1. Populate `GEOCODER_OPEN_DATA_PATHS` with reviewed address/road/POI rows
   beyond the checked-in sample.
2. Run `infra/scripts/import_flood_potential_layer.py` with a reviewed local
   SHP/zip package once the source URL/checksum is accepted.
3. Run `scripts/public-beta-local-gate.ps1` before every public-beta candidate
   handoff.
4. Deploy the current branch to Zeabur and run
   `scripts/hosted_public_beta_smoke.py`.

## Manual Or Production Inputs Still Needed

- Zeabur project, domain, secrets, alert route, and backup/restore evidence.
- CWA authorization only if live CWA is enabled.
- WRA token only if the selected WRA endpoint requires it.
- Operator-owned basemap storage/CDN URL and evidence.
- Reviewed flood-potential package URL/checksum/output evidence.
- Named owners for source, platform, observability, worker, and governance
  decisions.
