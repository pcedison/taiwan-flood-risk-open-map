# Production Beta Ops Evidence

Date: 2026-05-06
Environment: Zeabur `flood_risk`
Status: controlled public beta candidate after basemap/CDN, alert-route,
hosted geocoder bundle, production PostGIS geocoder import, logical PostGIS
scratch-restore drill, and forward-only rollback evidence. Production-complete
status still needs Zeabur-managed offsite backup artifact evidence and a
reviewed long-term backup retention policy.

This note records no-secret operational evidence gathered during the public
beta readiness pass. Private addresses, tokens, secret values, screenshots that
reveal values, and drill transcripts stay outside the public repository.

## Zeabur Services

Observed services in the Zeabur project:

- `taiwan-flood-risk-open-map`
- `postgis`
- `redis`
- `minio`

The `minio` service was added from the Zeabur MinIO template and reached
`running` state. It exposes MinIO-related environment variables through Zeabur
secret-backed service configuration. No secret values were copied into this
repository.

A Zeabur subdomain was bound to the MinIO HTTP 9000 port:

```text
http://flood-risk-minio.zeabur.app
```

Current MinIO validation result: not acceptable as production CDN yet. HTTP
redirects to HTTPS, but HTTPS validation currently sees a self-signed
certificate from the MinIO endpoint. Public browsers and PMTiles clients should
not use this as the production basemap URL until TLS is fixed or a CDN/custom
domain terminates trusted TLS.

Public beta basemap delivery now uses Cloudflare R2 instead of the Zeabur MinIO
test subdomain. The current public R2 base is:

```text
https://pub-6257ee5681314ac39a2e0b5f88823e39.r2.dev
```

This uses Cloudflare's managed `r2.dev` host, not a custom project domain. That
is acceptable for a controlled public beta, but a future production-complete
review should decide whether to add a custom CDN/domain and cache policy.

## Secret Manager References

Use Zeabur environment variables as the secret-manager reference source. Store
only refs like these in private production evidence:

- `zeabur://flood_risk/taiwan-flood-risk-open-map/env/ADMIN_BEARER_TOKEN`
- `zeabur://flood_risk/taiwan-flood-risk-open-map/env/CWA_API_AUTHORIZATION`
- `zeabur://flood_risk/taiwan-flood-risk-open-map/env/DATABASE_URL`
- `zeabur://flood_risk/taiwan-flood-risk-open-map/env/REDIS_URL`
- `zeabur://flood_risk/taiwan-flood-risk-open-map/env/BASEMAP_STYLE_URL`
- `zeabur://flood_risk/taiwan-flood-risk-open-map/env/BASEMAP_PMTILES_URL`
- `zeabur://flood_risk/minio/env/MINIO_ROOT_USER`
- `zeabur://flood_risk/minio/env/MINIO_ROOT_PASSWORD`
- `zeabur://flood_risk/minio/env/MINIO_DEFAULT_BUCKET`

The Zeabur UI also shows managed PostGIS and Redis generated variables. Keep
those as Zeabur refs in private evidence; do not paste connection strings or
password previews into runbooks.

## CWA Live Smoke

CWA live feed was enabled in Zeabur by setting:

- `CWA_API_AUTHORIZATION`: stored in Zeabur env
- `SOURCE_CWA_API_ENABLED=true`
- `REALTIME_OFFICIAL_ENABLED=true`

The current app service was restarted after the env update. Hosted API smoke at
`https://floodrisk.zeabur.app/v1/risk/assess` returned:

- `cwa-rainfall`: `healthy`
- `wra-water-level`: `healthy`
- `db-evidence`: `healthy`
- `explanation.missing_sources`: `[]`

Private artifact refs:

- `private-ops://hosted-smoke/cwa-live/2026-05-06`
- `private-ops://basemap-r2/2026-05-06/risk-live.json`

## Alert Route

Primary email alert route test was sent and the operator confirmed receipt.
The route can be used for:

- API readiness
- Source freshness
- Worker heartbeat
- Scheduler heartbeat
- Queue health
- Backup/restore drill notices

Private artifact ref: `private-ops://alert-route/email-primary/2026-05-06`.
Do not commit the operator email address to this public repository.

Backup email alert route test was also sent and the operator confirmed receipt.
Use it as the backup notification path for:

- API readiness
- Source freshness
- Worker heartbeat
- Scheduler heartbeat
- Queue health
- Backup/restore drill notices
- Rollback drill notices

Private artifact ref: `private-ops://alert-route/email-backup/2026-05-06`.
Do not commit the backup email address to this public repository.

## Backup And Restore Drill

Zeabur's public documentation distinguishes stateful volume backups from
database backups. For database services, Zeabur documents online offsite backup
support without pausing the database service. It also documents a GraphQL
`backups(environmentID, serviceID)` query for retrieving backup metadata and
download URLs.

Earlier Zeabur UI exploration saw a manual backup path return this message:

```text
Please pause this service before backup.
```

An accelerated 2026-05-06 14:37 Asia/Taipei drill attempted to continue this
workflow without waiting for the original 2026-05-07 window. Preflight passed:

- `/ready`: `200`, database healthy, Redis healthy
- hosted public beta smoke: passed
- Docker fallback PostgreSQL clients available:
  `pg_dump (PostgreSQL) 16.4`, `pg_restore (PostgreSQL) 16.4`

The drill could not safely execute hosted backup/restore because the current
automation session could not obtain an authenticated Zeabur operation channel:

- Browser Use Node REPL execution tool was not exposed in this session.
- Zeabur CLI was available but not logged in; `zeabur auth login` did not
  complete within the automation window.
- No production `DATABASE_URL` value was printed or copied into the repository.

The safe public-beta hosted backup drill path remains:

1. Announce a short maintenance window.
2. Pause PostGIS.
3. Trigger Zeabur backup.
4. Resume PostGIS and verify `/ready`.
5. Restore the archive only to a scratch/test database, never over production.
6. Run `/ready` or SQL checks against the scratch target.
7. Record the private drill transcript and archive ref.

No production restore was attempted during the 2026-05-06 accelerated UI drill.

A no-secret logical PostGIS scratch-restore drill was completed later in the
same accelerated window through authenticated Zeabur CLI `service exec` on the
API container. The drill used the Zeabur-injected `DATABASE_URL` inside the
container; the connection string was never printed or copied.

Logical scratch-restore result:

- started at: `2026-05-06T09:16:06Z`
- scratch schema:
  `backup_restore_drill_20260506_0913z`
- backup/restore scope:
  `geocoder_open_data_entries`
- production rows before restore: `46,457`
- scratch restored rows: `46,457`
- source counts matched:
  - `moi-national-road-names`: `32,868`
  - `nfa-evacuation-shelter-locations`: `5,878`
  - `moi-village-boundary-twd97-geographic`: `7,711`
- scratch cleanup check:
  `scratch_schema_remaining=0`
- post-drill `/ready`: `200`, database healthy, Redis healthy
- post-drill hosted public beta smoke: passed

This satisfies a beta-level application logical backup/restore drill for the
current production geocoder data. It does not replace a production-complete
Zeabur-managed offsite backup artifact drill. Before production-complete status,
capture either a Zeabur dashboard transcript or Public API evidence showing a
successful provider-managed backup artifact, download URL metadata, and restore
test to a scratch database or equivalent isolated target.

## Rollback Drill

Application rollback was exercised during the accelerated 2026-05-06 drill.

First attempt: move GitHub `main` directly back to previous known-good commit
`55c4a27ff5d5e59f99fcc2ca90a43728272ecadc`, then restore it to
`ff8f658b56d7816680ad9274d516a743e1e3dbf1`. GitHub accepted the temporary
branch movement and it was restored, but Zeabur did not deploy the backward
branch movement within the timeout. The hosted service stayed healthy and was
verified after restore.

Second attempt: forward-only rollback path using ordinary commits:

- Starting deployment: `ff8f658b56d7816680ad9274d516a743e1e3dbf1`
- Rollback commit: `37a65bdb0bd32cfd332edfc341b90557b97ef438`
- Rollback `/ready`: `200`, database healthy, Redis healthy
- Rollback hosted public beta smoke: passed
- Forward deploy commit: `fd928bbd79bf7358f6035a2befc04bcd4fe56649`
- Forward `/ready`: `200`, database healthy, Redis healthy
- Forward hosted public beta smoke: passed

Result: rollback drill passed for the forward-only GitHub/Zeabur deployment
path. Zeabur dashboard-level "select previous deployment" rollback still needs
authenticated UI/CLI access if production-complete evidence requires that exact
platform action.

Before production-complete status, record:

- current deployment SHA
- known-good rollback target
- rollback action transcript
- `/health`, `/ready`, and hosted smoke after rollback
- forward redeploy transcript if the drill returns to the latest version

## Basemap And Object Storage

Production public OSM community tile usage has been removed from hosted
production fallback behavior. The public beta basemap now uses operator-owned
Cloudflare R2 objects:

- Style URL:
  `https://pub-6257ee5681314ac39a2e0b5f88823e39.r2.dev/styles/taiwan-open/2026-05-06/style.json`
- PMTiles URL:
  `https://pub-6257ee5681314ac39a2e0b5f88823e39.r2.dev/basemaps/taiwan/2026-05-05/protomaps-taiwan-z14.pmtiles`
- Current manifest:
  `https://pub-6257ee5681314ac39a2e0b5f88823e39.r2.dev/basemaps/current.json`
- Attribution:
  `OpenStreetMap contributors, Protomaps`

The PMTiles object was generated from Protomaps global build
`20260505.pmtiles`, extracted for Taiwan bounds `118.0,21.7,122.5,26.5` at
max zoom 14, verified with `go-pmtiles verify`, and uploaded to versioned R2
paths.

Basemap evidence collected:

- PMTiles/style URLs recorded
- required attribution visible in desktop/mobile smoke
- CORS proof for `https://floodrisk.zeabur.app`
- HTTP Range `206` proof for PMTiles
- immutable cache-control proof for versioned objects
- desktop/mobile screenshots captured
- browser network log showed R2 style/PMTiles requests and no
  `tile.openstreetmap.org` requests

Private artifact ref:
`private-ops://basemap-r2/2026-05-06`. Local working evidence was collected
under `tmp/evidence/basemap-r2-20260506/` and is intentionally not committed.

Temporary Cloudflare R2 upload credentials were deleted after upload. Do not
store upload tokens in this repository.

## Runtime Smoke

Hosted public checks after Zeabur env restore and production PostGIS geocoder
bootstrap:

- `GET /health`: `200`
- `GET /ready`: `200`, database healthy, Redis healthy
- `GET /basemap-config`: R2 style URL returned with no warnings
- `GET /v1/geocoder/open-data/status`: `healthy`, `46,457` production
  PostGIS rows
- `POST /v1/geocode`: road, POI, and admin samples returned
  `postgis-open-data:*` sources
- `POST /v1/risk/assess`: CWA, WRA, and database evidence healthy for the
  live-smoke radius

Verification deployment SHA observed in `/ready` after the production geocoder
bootstrap:

```text
4996acb5bc3855e5c08e7d8803c95b2112db3760
```

## Production PostGIS Geocoder Import

Production PostGIS geocoder import is complete for the beta road / POI /
village bundle.

Runtime bootstrap behavior:

- Hosted app uses Zeabur-injected `DATABASE_URL`; no connection string or
  password was printed, copied, or committed.
- `GEOCODER_POSTGIS_ENABLED=true` and
  `GEOCODER_POSTGIS_BOOTSTRAP_ENABLED=true` are active by hosted default.
- On startup, the API creates/updates `geocoder_open_data_entries` and
  `geocoder_open_data_import_runs`, then imports the bundled open-data files.
- The bootstrap avoids extra extension privileges by using stable app-generated
  UUIDs.

Hosted no-secret status at `2026-05-06T08:51:50Z`:

- status: `healthy`
- bundled path count: `3`
- production PostGIS rows: `46,457`
- source counts:
  - `moi-national-road-names`: `32,868`
  - `nfa-evacuation-shelter-locations`: `5,878`
  - `moi-village-boundary-twd97-geographic`: `7,711`

The raw bundled coverage input contains `46,463` rows. Production unique-key
import collapses six duplicate road `source_record_id` rows, resulting in
`46,457` stored rows.

Hosted smoke after the import:

- road sample: `precision=road_or_lane`,
  `source=postgis-open-data:moi-national-road-names`,
  `requires_confirmation=true`
- POI sample: `precision=poi`,
  `source=postgis-open-data:nfa-evacuation-shelter-locations`,
  `requires_confirmation=false`
- admin sample: `precision=admin_area`,
  `source=postgis-open-data:moi-village-boundary-twd97-geographic`,
  `requires_confirmation=true`

This closes the previous public-beta blocker for "production PostGIS geocoder
import and coverage evidence." It does not mean the service has complete
Taiwan doorplate coverage; exact national address/doorplate coverage remains a
post-beta data-expansion track.

## Public Beta Limitation

The public UI and README show the limitation statement:

```text
本服務為公開資料與歷史/潛勢圖資整合的淹水風險查詢 beta。結果不可視為即時災害通報或購屋安全保證；地址定位可能因開放資料覆蓋不足而退回道路或行政區精度。
```

This is an accepted launch limitation for public beta. It does not unblock
production-complete status by itself.

## Remaining Blockers

- For production-complete status, capture a Zeabur-managed offsite PostGIS
  backup artifact and restore evidence through the dashboard or Public API.
  The beta-level logical scratch-restore drill has passed.
- Decide whether controlled public beta can keep the Cloudflare managed
  `r2.dev` host or should wait for a custom CDN/domain.
- Keep the single-maintainer on-call model explicit until additional humans or
  escalation routes exist.
