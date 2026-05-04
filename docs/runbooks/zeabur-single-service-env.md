# Zeabur Single-Service Environment Checklist

Use this checklist when filling Zeabur environment variables for the current single Dockerfile service.

## Zeabur Service Settings

| Setting | What to choose |
|---|---|
| Service type | `Dockerfile` |
| Root Directory | Repository root |
| Build Command | Leave blank |
| Start Command | Leave blank |
| HTTP Health Check | `/health` |

Do not use `/ready` as the first health check. `/ready` checks PostgreSQL and Redis, so it can fail before those services exist.

This checklist is for a deployable single-service preview only. It does not
accept worker ingestion, queue replay, queue metrics, hosted scheduler cadence,
or flood-potential live ingestion. Real upstream URL/license review,
credential review, hosted cadence, alert routing, poison-job
quarantine/replay audit, and production egress verification remain pending
unless a separate environment handoff says otherwise.

## Required Variables

| Variable | Zeabur value |
|---|---|
| `APP_ENV` | `staging` |
| `DEPLOYMENT_SHA` | `${ZEABUR_GIT_COMMIT_SHA}` |
| `API_VERSION` | `public-beta-mvp-2026-05-04` or another release label |
| `LOG_LEVEL` | `info` |
| `NEXT_PUBLIC_API_BASE_URL` | Leave empty |
| `NEXT_PUBLIC_BASEMAP_STYLE_URL` | Reviewed open basemap style URL, or blank for local/dev fallback only |
| `NEXT_PUBLIC_BASEMAP_KIND` | `pmtiles`, `raster`, or blank |
| `NEXT_PUBLIC_BASEMAP_PMTILES_URL` | Reviewed PMTiles URL when `NEXT_PUBLIC_BASEMAP_KIND=pmtiles` |
| `NEXT_PUBLIC_BASEMAP_RASTER_TILES` | Reviewed raster tile template only for temporary fallback |
| `NEXT_PUBLIC_BASEMAP_ATTRIBUTION` | Reviewed attribution text for the selected basemap |
| `NEXT_TELEMETRY_DISABLED` | `1` |
| `REALTIME_OFFICIAL_ENABLED` | `false` for the no-secret public beta smoke |
| `SOURCE_CWA_API_ENABLED` | `false` until CWA is explicitly enabled |
| `SOURCE_WRA_API_ENABLED` | `false` until WRA is explicitly enabled |
| `CWA_API_AUTHORIZATION` | Leave empty until CWA is explicitly enabled |
| `EVIDENCE_REPOSITORY_ENABLED` | `false` until PostgreSQL is attached and migrated |
| `HISTORICAL_NEWS_ON_DEMAND_ENABLED` | `false` until source terms are reviewed |
| `HISTORICAL_NEWS_ON_DEMAND_WRITEBACK_ENABLED` | `false` until database writeback is enabled |
| `SOURCE_NEWS_ENABLED` | `false` until source terms are reviewed |
| `SOURCE_TERMS_REVIEW_ACK` | `false` until source terms are reviewed |
| `USER_REPORTS_ENABLED` | `false` until abuse controls and moderation owner are ready |

## Optional Variables

`NEXT_PUBLIC_BASEMAP_*` values are client build-time inputs for the Dockerfile
image. Set them before Zeabur builds, and rebuild the service after changing the
public basemap.

| Variable | Zeabur value | Use when |
|---|---|---|
| `ADMIN_BEARER_TOKEN` | Random long secret | Someone will test admin endpoints. |
| `API_VERSION` | Release label, for example `preview-2026-04-29` | You want `/health` to show a recognizable version. |
| `CORS_ORIGINS` | The Zeabur origin, for example `https://your-service.zeabur.app` | A separate site will call the API directly. Usually unnecessary for same-origin preview. |

## Leave Blank For First Preview

Do not add these variables for the first single-service preview unless an engineer specifically tells you the related service is ready:

| Variable or group | Reason |
|---|---|
| `DATABASE_URL`, `POSTGRES_*` | PostgreSQL is not part of the first preview. |
| `REDIS_URL`, `REDIS_HOST`, `REDIS_PORT` | Redis is not part of the first preview. |
| `MINIO_*` | Object storage is not part of the first preview. |
| `SOURCE_*_ENABLED` not listed above | These are worker and scheduler flags; there is no worker or scheduler in this service. |
| `CWA_API_URL`, `CWA_API_TIMEOUT_SECONDS` | Worker live-ingestion knobs; the single-service preview only uses the API realtime bridge. |
| `WRA_API_URL`, `WRA_API_TOKEN`, `WRA_API_TIMEOUT_SECONDS` | Worker live-ingestion knobs; the single-service preview only uses the API realtime bridge. |
| `WORKER_METRICS_TEXTFILE_PATH`, `SCHEDULER_METRICS_TEXTFILE_PATH` | Queue/heartbeat metric knobs for worker or scheduler services; this single-service preview has neither. |
| `S3_*` | The current runtime does not read these names. |
| `TGOS_API_KEY` | Reserved for future optional TGOS support; not read by the current runtime. |
| `API_HOST`, `API_PORT`, `WEB_HOST`, `WEB_PORT` | Zeabur and the Dockerfile already choose the correct runtime ports. |

## TGOS Optional Provider

TGOS is not required for the single-service preview. Keep `TGOS_API_KEY` unset
until the runtime supports it and the IP/domain constraints have a reviewed
solution. The current preview should prove the MapLibre open basemap path through
`NEXT_PUBLIC_BASEMAP_*` instead.
