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
does not keep the backbone disabled. Force mode also retires a legacy
`REALTIME_BACKBONE_INGESTION_DISABLED=true` maintenance stop. Set
`REALTIME_BACKBONE_EMERGENCY_STOP=true` for an unconditional current emergency
stop and remove it after the incident. A
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
| `REALTIME_OFFICIAL_DIAGNOSTIC_FALLBACK_ENABLED` | `false`; hosted responses must use worker-persisted official evidence, not request-time CWA/WRA fetches |
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
dedicated worker service exists. When
`REALTIME_BACKBONE_FORCE_INGESTION_ON_START=true`, the start script sets every
reviewed backbone source gate to `true` even if Zeabur still contains a legacy
explicit `false`. To control individual gates, first set force mode to `false`;
the legacy `REALTIME_BACKBONE_INGESTION_DISABLED=true` value is also ignored
while force mode is active. `REALTIME_BACKBONE_EMERGENCY_STOP=true` is the
unconditional all-source emergency stop and always overrides force mode.
The same resolved stop state is honored by a dedicated `SERVICE_ROLE=scheduler`
service: it records the intentional disable and stays idle until redeployed with
the stop removed.

| Variable | Zeabur value |
|---|---|
| `HOSTED_INGESTION_SCHEDULER_ENABLED` | Leave unset or set `auto`; legacy `false` is overridden by `REALTIME_BACKBONE_FORCE_INGESTION_ON_START=true` |
| `DATABASE_URL` | Zeabur Postgres connection URL |
| `WORKER_DATABASE_URL` | Leave blank to reuse `DATABASE_URL`, or set the same Postgres URL |
| `REALTIME_BACKBONE_FORCE_INGESTION_ON_START` | Leave unset or `true`; forces the adapter list and every reviewed source gate on when DB is attached, overriding legacy explicit `false` gate values |
| `REALTIME_BACKBONE_INGESTION_DISABLED` | Leave unset or `false`; this legacy maintenance stop is ignored while force mode is active |
| `REALTIME_BACKBONE_EMERGENCY_STOP` | Leave unset or `false`; set `true` only for a current unconditional emergency stop, then remove it after the incident |
| `REALTIME_BACKBONE_ADAPTER_KEYS` | Leave unset for the full backbone, or set the same full list below to override an old `WORKER_ENABLED_ADAPTER_KEYS` |
| `RUN_DATABASE_MIGRATIONS_ON_START` | Leave unset or `true`; use `false` only for an operator-managed migration window |
| `MIGRATION_LOCK_TIMEOUT_MS` | Leave unset for the conservative `10000` ms PostgreSQL lock-wait limit |
| `MIGRATION_STATEMENT_TIMEOUT_MS` | Leave unset for the conservative `300000` ms per-migration statement limit |
| `WORKER_ENABLED_ADAPTER_KEYS` | `official.cwa.rainfall,official.cwa.tide_level,official.wra.water_level,official.wra_iow.flood_depth,official.ncdr.cap,official.civil_iot.flood_sensor,official.civil_iot.sewer_water_level,official.civil_iot.pump_water_level,official.civil_iot.gate_water_level,local.tainan.flood_sensor` |
| `SOURCE_CWA_ENABLED` | Leave unset or `true`; `false` takes effect only when force mode is disabled |
| `SOURCE_CWA_API_ENABLED` | `true` |
| `CWA_API_AUTHORIZATION` | Your CWA API authorization token |
| `SOURCE_WRA_ENABLED` | Leave unset or `true`; `false` takes effect only when force mode is disabled |
| `SOURCE_WRA_API_ENABLED` | `true` |
| `SOURCE_WRA_IOW_FLOOD_DEPTH_ENABLED` | `true` |
| `SOURCE_WRA_IOW_FLOOD_DEPTH_API_ENABLED` | `true` |
| `SOURCE_NCDR_CAP_ENABLED` | `true` |
| `SOURCE_NCDR_CAP_API_ENABLED` | `true` |
| `SOURCE_NCDR_CAP_CONTRACT_ENABLED` | Leave unset or `true`; force mode sets this reviewed contract gate to `true` so NCDR cannot be silently omitted |
| `NCDR_ALERTS_API_KEY` | NCDR alert API key; required for the reviewed NCDR CAP adapter to fetch upstream data |
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
| `SOURCE_TAINAN_FLOOD_SENSOR_TIMEOUT_SECONDS` | Leave unset or `45`; the adapter clamps lower stale overrides to 45 seconds because production hosted egress has exceeded 20 seconds |
| `WRA_STATION_API_URL` | Leave blank unless overriding the WRA station metadata endpoint |
| `SCHEDULER_INTERVAL_SECONDS` | `300` for a 5-minute beta cadence |
| `SCHEDULER_LEASE_TTL_SECONDS` | `600` |
| `SCHEDULER_MAX_TICKS` | Leave unset; any finite value stops the long-running hosted scheduler after that many cycles |

## Stalled Realtime Pipeline Recovery

Use this sequence when the public response reports `pipeline_stalled`, or when
the hosted public-risk evidence smoke lists failed required worker sources.

1. Confirm the service topology. A single-service deployment must leave
   `SERVICE_ROLE` unset (defaults to `all`). If `SERVICE_ROLE=api`, a separate
   private `SERVICE_ROLE=scheduler` service with exactly one replica must exist.
2. Confirm `DATABASE_URL` is attached and that `WORKER_DATABASE_URL` is either
   blank or exactly the same database. Never copy either value into logs or an
   incident ticket.
3. Set `REALTIME_BACKBONE_FORCE_INGESTION_ON_START=true`,
   `REALTIME_BACKBONE_EMERGENCY_STOP=false`, and leave
   `HOSTED_INGESTION_SCHEDULER_ENABLED` unset or `auto`.
4. Remove `SCHEDULER_MAX_TICKS`, set `SCHEDULER_INTERVAL_SECONDS=300`, and set
   `SCHEDULER_LEASE_TTL_SECONDS=600`.
5. Set `REALTIME_OFFICIAL_DIAGNOSTIC_FALLBACK_ENABLED=false`. A diagnostic
   request-time observation is useful during an incident but is not proof that
   the background persistence path recovered.
6. Confirm force mode is active and that the CWA credential exists without
   printing its value. The entrypoint must override stale `false` values for the
   reviewed source gates. Keep public-news enrichment disabled until its
   separate source/terms review is accepted.
7. Redeploy and verify the service logs contain both
   `launching official ingestion scheduler loop (first tick runs immediately)`
   and repeated `worker.runtime.managed_scheduler.tick_completed` events.
8. Configure the GitHub repository secret `ADMIN_BEARER_TOKEN` and run Hosted
   Monitoring. The run must pass both `hosted_source_freshness_smoke.py` and
   `hosted_public_risk_evidence_smoke.py`; do not accept `/health` alone as
   recovery evidence.

Expected public behavior after recovery: `nearby_realtime_coverage` contains
fresh or degraded-but-usable rows, `source_health_checked=true`, and no required
source reports `pipeline_stalled`. If a fresh diagnostic observation is present
while background health is still failed, the UI may show the observation as a
partial clue, but monitoring must remain red.

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
