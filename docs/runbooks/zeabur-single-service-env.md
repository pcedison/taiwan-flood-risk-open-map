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

This checklist is for the deployable single-service public beta. The container
always starts API and Web. When `DATABASE_URL` or `WORKER_DATABASE_URL` is
attached, `HOSTED_INGESTION_SCHEDULER_ENABLED=auto` starts the beta ingestion
scheduler in the same container by default. That scheduler uses the existing
worker managed-ingestion path, persists official snapshots to Postgres,
promotes them to evidence, and guards repeated runs with the Postgres scheduler
lease. The production beta start script forces the realtime backbone on when a
database URL is present, so legacy `HOSTED_INGESTION_SCHEDULER_ENABLED=false`
does not keep the backbone disabled. Set
`REALTIME_BACKBONE_INGESTION_DISABLED=true` as the explicit kill switch. A
separate worker/scheduler topology is still the preferred production operating
model once alerting, scaling, and incident ownership are accepted.

When a database URL is attached, the start script also applies any unrecorded
`infra/migrations/*.sql` files before launching API/Web. Migrations are tracked
in `schema_migrations` and can be disabled only with
`RUN_DATABASE_MIGRATIONS_ON_START=false`.

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

## Single-Service Official Ingestion

Use this after PostgreSQL migrations have been applied. The scheduler runs
inside the same Zeabur service as API/Web so the public beta can receive
official CWA/WRA, WRA IoW, NCDR CAP, and Civil IoT backbone snapshots before a
dedicated worker service exists. Source gates default to `true` in the
single-service scheduler, but each gate can still be set to `false` in Zeabur to
disable that source.

| Variable | Zeabur value |
|---|---|
| `HOSTED_INGESTION_SCHEDULER_ENABLED` | Leave unset or set `auto`; legacy `false` is overridden by `REALTIME_BACKBONE_FORCE_INGESTION_ON_START=true` |
| `DATABASE_URL` | Zeabur Postgres connection URL |
| `WORKER_DATABASE_URL` | Leave blank to reuse `DATABASE_URL`, or set the same Postgres URL |
| `REALTIME_BACKBONE_FORCE_INGESTION_ON_START` | Leave unset or `true`; forces the realtime backbone on when DB is attached |
| `REALTIME_BACKBONE_INGESTION_DISABLED` | Leave unset or `false`; set `true` only as the explicit kill switch |
| `REALTIME_BACKBONE_ADAPTER_KEYS` | Leave unset for the full backbone, or set the same full list below to override an old `WORKER_ENABLED_ADAPTER_KEYS` |
| `RUN_DATABASE_MIGRATIONS_ON_START` | Leave unset or `true`; use `false` only for an operator-managed migration window |
| `WORKER_ENABLED_ADAPTER_KEYS` | `official.cwa.rainfall,official.cwa.tide_level,official.wra.water_level,official.wra_iow.flood_depth,official.ncdr.cap,official.civil_iot.flood_sensor,official.civil_iot.sewer_water_level,official.civil_iot.pump_water_level,official.civil_iot.gate_water_level,local.tainan.flood_sensor` |
| `SOURCE_CWA_ENABLED` | Leave unset or `true`; `false` disables CWA ingestion |
| `SOURCE_CWA_API_ENABLED` | `true` |
| `CWA_API_AUTHORIZATION` | Your CWA API authorization token |
| `SOURCE_WRA_ENABLED` | Leave unset or `true`; `false` disables WRA ingestion |
| `SOURCE_WRA_API_ENABLED` | `true` |
| `SOURCE_WRA_IOW_FLOOD_DEPTH_ENABLED` | `true` |
| `SOURCE_WRA_IOW_FLOOD_DEPTH_API_ENABLED` | `true` |
| `SOURCE_NCDR_CAP_ENABLED` | `true` |
| `SOURCE_NCDR_CAP_API_ENABLED` | `true` |
| `SOURCE_FLOOD_SENSOR_ENABLED` | `true` |
| `SOURCE_FLOOD_SENSOR_API_ENABLED` | `true` |
| `SOURCE_FLOOD_SENSOR_USE_LIVE` | `true` |
| `SOURCE_CIVIL_IOT_SEWER_ENABLED` | `true` |
| `SOURCE_CIVIL_IOT_SEWER_API_ENABLED` | `true` |
| `SOURCE_CIVIL_IOT_PUMP_ENABLED` | `true` |
| `SOURCE_CIVIL_IOT_PUMP_API_ENABLED` | `true` |
| `SOURCE_CIVIL_IOT_GATE_ENABLED` | `true` |
| `SOURCE_CIVIL_IOT_GATE_API_ENABLED` | `true` |
| `SOURCE_TAINAN_FLOOD_SENSOR_ENABLED` | `true` |
| `SOURCE_TAINAN_FLOOD_SENSOR_API_ENABLED` | `true` |
| `WRA_STATION_API_URL` | Leave blank unless overriding the WRA station metadata endpoint |
| `SCHEDULER_INTERVAL_SECONDS` | `300` for a 5-minute beta cadence |
| `SCHEDULER_LEASE_TTL_SECONDS` | `600` |

## Leave Blank For First Preview

Do not add these variables for the first single-service preview unless an engineer specifically tells you the related service is ready:

| Variable or group | Reason |
|---|---|
| `DATABASE_URL`, `POSTGRES_*` | PostgreSQL is not part of the first preview. |
| `REDIS_URL`, `REDIS_HOST`, `REDIS_PORT` | Redis is not part of the first preview. |
| `MINIO_*` | Object storage is not part of the first preview. |
| `CWA_API_URL`, `CWA_API_TIMEOUT_SECONDS` | Optional worker live-ingestion knobs; leave blank/default unless CWA endpoint review requires an override. |
| `WRA_API_URL`, `WRA_STATION_API_URL`, `WRA_API_TOKEN`, `WRA_API_TIMEOUT_SECONDS` | Optional worker live-ingestion knobs; leave blank/default unless WRA endpoint review requires an override. |
| `WORKER_METRICS_TEXTFILE_PATH`, `SCHEDULER_METRICS_TEXTFILE_PATH` | Queue/heartbeat metric files require a collector; leave blank in this single-service beta unless monitoring is attached. |
| `S3_*` | The current runtime does not read these names. |
| `TGOS_API_KEY` | Reserved for future optional TGOS support; not read by the current runtime. |
| `API_HOST`, `API_PORT`, `WEB_HOST`, `WEB_PORT` | Zeabur and the Dockerfile already choose the correct runtime ports. |

## TGOS Optional Provider

TGOS is not required for the single-service preview. Keep `TGOS_API_KEY` unset
until the runtime supports it and the IP/domain constraints have a reviewed
solution. The current preview should prove the MapLibre open basemap path through
`NEXT_PUBLIC_BASEMAP_*` instead.
