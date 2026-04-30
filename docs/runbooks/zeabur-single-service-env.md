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

## Required Variables

| Variable | Zeabur value |
|---|---|
| `APP_ENV` | `staging` |
| `LOG_LEVEL` | `info` |
| `NEXT_PUBLIC_API_BASE_URL` | Leave empty |
| `NEXT_TELEMETRY_DISABLED` | `1` |
| `REALTIME_OFFICIAL_ENABLED` | `true` |
| `CWA_API_AUTHORIZATION` | Paste the CWA authorization token |

## Optional Variables

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
| `SOURCE_*_ENABLED` | These are worker and scheduler flags; there is no worker or scheduler in this service. |
| `SOURCE_CWA_API_ENABLED`, `CWA_API_URL`, `CWA_API_TIMEOUT_SECONDS` | Worker live-ingestion knobs; the single-service preview only uses the API realtime bridge. |
| `S3_*` | The current runtime does not read these names. |
| `TGOS_API_KEY` | Reserved for future TGOS geocoding support; not read by the current runtime. |
| `API_HOST`, `API_PORT`, `WEB_HOST`, `WEB_PORT` | Zeabur and the Dockerfile already choose the correct runtime ports. |

## TGOS Domain

When TGOS asks for the app domain, use the public Zeabur domain exactly as users open it, for example:

```text
https://your-service.zeabur.app
```

Do not submit `localhost`, `127.0.0.1`, an internal Zeabur address, or a health-check path such as `/health`. Keep this domain stable during review.
