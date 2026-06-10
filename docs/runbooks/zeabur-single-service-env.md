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

This checklist is for the deployable single-service public beta. By default it
starts API and Web only. It can also start a beta ingestion scheduler in the
same container when `HOSTED_INGESTION_SCHEDULER_ENABLED=true`; that scheduler
uses the existing worker managed-ingestion path, persists official snapshots to
Postgres, promotes them to evidence, and guards repeated runs with the
Postgres scheduler lease. A separate worker/scheduler topology is still the
preferred production operating model once alerting, scaling, and incident
ownership are accepted.

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
| `REALTIME_OFFICIAL_ENABLED` | `true` when official evidence snapshots are enabled; `false` only for no-secret smoke |
| `EVIDENCE_REPOSITORY_ENABLED` | `true` when PostgreSQL is attached and migrated |
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

## Optional Single-Service Official Ingestion

Use this only after PostgreSQL migrations have been applied and the source
credentials are intentionally enabled. The scheduler runs inside the same
Zeabur service as API/Web so the public beta can receive official CWA/WRA
snapshots before a dedicated worker service exists.

| Variable | Zeabur value |
|---|---|
| `HOSTED_INGESTION_SCHEDULER_ENABLED` | `true` |
| `DATABASE_URL` | Zeabur Postgres connection URL |
| `WORKER_DATABASE_URL` | Leave blank to reuse `DATABASE_URL`, or set the same Postgres URL |
| `WORKER_ENABLED_ADAPTER_KEYS` | `official.cwa.rainfall,official.wra.water_level` |
| `SOURCE_CWA_API_ENABLED` | `true` |
| `CWA_API_AUTHORIZATION` | Your CWA API authorization token |
| `SOURCE_WRA_API_ENABLED` | `true` |
| `SCHEDULER_INTERVAL_SECONDS` | `300` for a 5-minute beta cadence |
| `SCHEDULER_LEASE_TTL_SECONDS` | `600` |

Leave `SOURCE_CWA_ENABLED` and `SOURCE_WRA_ENABLED` unset unless you need an
explicit override. Setting either to `false` disables that source even when it
is listed in `WORKER_ENABLED_ADAPTER_KEYS`.

## Leave Blank For First Preview

Do not add these variables for the first single-service preview unless an engineer specifically tells you the related service is ready:

| Variable or group | Reason |
|---|---|
| `DATABASE_URL`, `POSTGRES_*` | PostgreSQL is not part of the first preview. |
| `REDIS_URL`, `REDIS_HOST`, `REDIS_PORT` | Redis is not part of the first preview. |
| `MINIO_*` | Object storage is not part of the first preview. |
| `CWA_API_URL`, `CWA_API_TIMEOUT_SECONDS` | Optional worker live-ingestion knobs; leave blank/default unless CWA endpoint review requires an override. |
| `WRA_API_URL`, `WRA_API_TOKEN`, `WRA_API_TIMEOUT_SECONDS` | Optional worker live-ingestion knobs; leave blank/default unless WRA endpoint review requires an override. |
| `WORKER_METRICS_TEXTFILE_PATH`, `SCHEDULER_METRICS_TEXTFILE_PATH` | Queue/heartbeat metric files require a collector; leave blank in this single-service beta unless monitoring is attached. |
| `S3_*` | The current runtime does not read these names. |
| `TGOS_API_KEY` | Reserved for future optional TGOS support; not read by the current runtime. |
| `API_HOST`, `API_PORT`, `WEB_HOST`, `WEB_PORT` | Zeabur and the Dockerfile already choose the correct runtime ports. |

## TGOS Optional Provider

TGOS is not required for the single-service preview. Keep `TGOS_API_KEY` unset
until the runtime supports it and the IP/domain constraints have a reviewed
solution. The current preview should prove the MapLibre open basemap path through
`NEXT_PUBLIC_BASEMAP_*` instead.
