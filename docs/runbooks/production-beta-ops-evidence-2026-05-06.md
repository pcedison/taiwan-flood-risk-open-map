# Production Beta Ops Evidence

Date: 2026-05-06
Environment: Zeabur `flood_risk`
Status: public beta candidate after basemap/CDN and alert-route evidence; not
production-complete until scheduled drills and geocoder coverage are done

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

Zeabur PostGIS exposes a `Backup/Restore` page and a manual `Backup` action.
Attempting to trigger the manual backup returned a Zeabur UI message requiring
the service to be paused before backup:

```text
Please pause this service before backup.
```

Because pausing PostGIS causes production downtime, the actual backup drill is
scheduled for `2026-05-07 23:30-23:45 Asia/Taipei`. The safe public-beta drill
path is:

1. Announce a short maintenance window.
2. Pause PostGIS.
3. Trigger Zeabur backup.
4. Resume PostGIS and verify `/ready`.
5. Restore the archive only to a scratch/test database, never over production.
6. Run `/ready` or SQL checks against the scratch target.
7. Record the private drill transcript and archive ref.

No production restore was attempted during the 2026-05-06 readiness pass.

## Rollback Drill

Application rollback has not yet been executed. Zeabur deployment history is
available on the app service page, but an actual rollback can change the hosted
service version and should be performed in a scheduled drill window. The
rollback drill is scheduled for `2026-05-07 23:45` to `2026-05-08 00:00`
Asia/Taipei. Before public beta, record:

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

Hosted public checks after Zeabur env restore:

- `GET /health`: `200`
- `GET /ready`: `200`, database healthy, Redis healthy
- `GET /basemap-config`: R2 style URL returned with no warnings
- `POST /v1/geocode`: sample query returned POI precision with limitations
- `POST /v1/risk/assess`: CWA, WRA, and database evidence healthy for the
  live-smoke radius

Current hosted deployment SHA observed in `/ready`:

```text
d995e23bd9cd6262277870abd5407929831492d0
```

## Public Beta Limitation

The public UI and README show the limitation statement:

```text
本服務為公開資料與歷史/潛勢圖資整合的淹水風險查詢 beta。結果不可視為即時災害通報或購屋安全保證；地址定位可能因開放資料覆蓋不足而退回道路或行政區精度。
```

This is an accepted launch limitation for public beta. It does not unblock
production-complete status by itself.

## Remaining Blockers

- Execute the scheduled backup/restore drill and record private evidence.
- Execute the scheduled rollback drill and record private evidence.
- Complete production PostGIS ingestion and coverage evidence for the expanded
  Taiwan geocoder data sources.
- Decide whether controlled public beta can keep the Cloudflare managed
  `r2.dev` host or should wait for a custom CDN/domain.
- Keep the single-maintainer on-call model explicit until additional humans or
  escalation routes exist.
