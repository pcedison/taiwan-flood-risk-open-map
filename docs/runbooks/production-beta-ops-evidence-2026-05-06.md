# Production Beta Ops Evidence

Date: 2026-05-06
Environment: Zeabur `flood_risk`
Status: public beta candidate, not production-complete

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

Current validation result: not acceptable as production CDN yet. HTTP redirects
to HTTPS, but HTTPS validation currently sees a self-signed certificate from the
MinIO endpoint. Public browsers and PMTiles clients should not use this as the
production basemap URL until TLS is fixed or a CDN/custom domain terminates
trusted TLS.

## Secret Manager References

Use Zeabur environment variables as the secret-manager reference source. Store
only refs like these in private production evidence:

- `zeabur://flood_risk/taiwan-flood-risk-open-map/env/ADMIN_BEARER_TOKEN`
- `zeabur://flood_risk/taiwan-flood-risk-open-map/env/CWA_API_AUTHORIZATION`
- `zeabur://flood_risk/taiwan-flood-risk-open-map/env/DATABASE_URL`
- `zeabur://flood_risk/taiwan-flood-risk-open-map/env/REDIS_URL`
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

The current app service was restarted after the env update. Hosted API smoke at
`https://floodrisk.zeabur.app/v1/risk/assess` returned:

- `cwa-rainfall`: `healthy`
- `wra-water-level`: `healthy`
- `db-evidence`: `healthy`
- `explanation.missing_sources`: `[]`

Private artifact ref: `private-ops://hosted-smoke/cwa-live/2026-05-06`.

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

Backup alert route is still pending. For public beta with a single maintainer,
the backup route can be another mailbox, LINE/Discord/Slack channel, or a
trusted human escalation contact that can be tested once.

## Backup And Restore Drill

Zeabur PostGIS exposes a `Backup/Restore` page and a manual `Backup` action.
Attempting to trigger the manual backup returned a Zeabur UI message requiring
the service to be paused before backup:

```text
Please pause this service before backup.
```

Because pausing PostGIS causes production downtime, the actual backup drill is
pending an explicit maintenance window. The safe public-beta drill path is:

1. Announce a short maintenance window.
2. Pause PostGIS.
3. Trigger Zeabur backup.
4. Resume PostGIS and verify `/ready`.
5. Restore the archive only to a scratch/test database, never over production.
6. Run `/ready` or SQL checks against the scratch target.
7. Record the private drill transcript and archive ref.

No production restore was attempted.

## Rollback Drill

Application rollback has not yet been executed. Zeabur deployment history is
available on the app service page, but an actual rollback can change the hosted
service version and should be performed in a scheduled drill window. Before
public beta, record:

- current deployment SHA
- known-good rollback target
- rollback action transcript
- `/health`, `/ready`, and hosted smoke after rollback
- forward redeploy transcript if the drill returns to the latest version

## Basemap And Object Storage

Production public OSM community tile usage has been removed from hosted
production fallback behavior. A production basemap is still not complete until
operator-owned object storage/CDN contains reviewed basemap assets and evidence:

- PMTiles/style/raster URL
- required attribution
- CORS proof
- HTTP Range `206` proof for PMTiles
- cache-control proof
- desktop/mobile screenshots
- browser network log proving no `tile.openstreetmap.org` requests

MinIO is now available as the Zeabur object-storage service, but the production
basemap bucket/object upload and CDN evidence remain pending. The Zeabur object
UI opened the bucket creation dialog, but bucket creation did not complete in
the browser session. Treat bucket bootstrap as pending until the MinIO console,
Zeabur object UI, or an S3-compatible CLI confirms the bucket exists.

## Public Beta Limitation

The public UI and README must show the limitation statement:

```text
本服務為公開資料與歷史/潛勢圖資整合的淹水風險查詢 beta。結果不可視為即時災害通報或購屋安全保證；地址定位可能因開放資料覆蓋不足而退回道路或行政區精度。
```

This is an accepted launch limitation for public beta. It does not unblock
production-complete status by itself.
