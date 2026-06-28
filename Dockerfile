FROM node:22-bookworm-slim AS web-builder

WORKDIR /app/apps/web

COPY apps/web/package.json apps/web/package-lock.json ./
# Harden against transient registry network flakes ("npm error network aborted")
# on the build host: longer npm fetch retries/timeouts plus an outer retry loop,
# and skip audit/fund to cut extra registry calls. Registry is unchanged so the
# package-lock integrity hashes still match.
RUN npm config set fetch-retries 5 \
  && npm config set fetch-retry-mintimeout 20000 \
  && npm config set fetch-retry-maxtimeout 120000 \
  && npm config set fetch-timeout 300000
RUN for attempt in 1 2 3 4 5; do \
      echo "npm ci attempt $attempt"; \
      if npm ci --no-audit --no-fund; then exit 0; fi; \
      echo "npm ci failed (attempt $attempt); retrying in 15s..." >&2; \
      sleep 15; \
    done; \
    echo "npm ci failed after 5 attempts" >&2; exit 1

COPY apps/web ./

ARG NEXT_PUBLIC_API_BASE_URL=""
ARG NEXT_PUBLIC_BASEMAP_STYLE_URL=""
ARG NEXT_PUBLIC_BASEMAP_KIND=""
ARG NEXT_PUBLIC_BASEMAP_PMTILES_URL=""
ARG NEXT_PUBLIC_BASEMAP_RASTER_TILES=""
ARG NEXT_PUBLIC_BASEMAP_ATTRIBUTION=""
ARG INTERNAL_API_BASE_URL="http://127.0.0.1:8000"
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
ENV NEXT_PUBLIC_BASEMAP_STYLE_URL=${NEXT_PUBLIC_BASEMAP_STYLE_URL}
ENV NEXT_PUBLIC_BASEMAP_KIND=${NEXT_PUBLIC_BASEMAP_KIND}
ENV NEXT_PUBLIC_BASEMAP_PMTILES_URL=${NEXT_PUBLIC_BASEMAP_PMTILES_URL}
ENV NEXT_PUBLIC_BASEMAP_RASTER_TILES=${NEXT_PUBLIC_BASEMAP_RASTER_TILES}
ENV NEXT_PUBLIC_BASEMAP_ATTRIBUTION=${NEXT_PUBLIC_BASEMAP_ATTRIBUTION}
ENV INTERNAL_API_BASE_URL=${INTERNAL_API_BASE_URL}
ENV NEXT_TELEMETRY_DISABLED=1

RUN npm run build
RUN npm prune --omit=dev --no-audit --no-fund --ignore-scripts \
  && npm cache clean --force

FROM python:3.12-slim AS runtime

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends bash ca-certificates \
  && rm -rf /var/lib/apt/lists/*

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV NEXT_PUBLIC_API_BASE_URL=""
ENV NEXT_PUBLIC_BASEMAP_STYLE_URL=""
ENV NEXT_PUBLIC_BASEMAP_KIND=""
ENV NEXT_PUBLIC_BASEMAP_PMTILES_URL=""
ENV NEXT_PUBLIC_BASEMAP_RASTER_TILES=""
ENV NEXT_PUBLIC_BASEMAP_ATTRIBUTION=""
ENV INTERNAL_API_BASE_URL="http://127.0.0.1:8000"
ENV APP_ENV=staging
ENV REALTIME_OFFICIAL_ENABLED=true

COPY --from=web-builder /usr/local/bin/node /usr/local/bin/node

RUN python -m venv "${VIRTUAL_ENV}" \
  && pip install --no-cache-dir --upgrade pip

COPY apps/api/pyproject.toml apps/api/README.md /app/apps/api/
COPY apps/api/app /app/apps/api/app
RUN pip install --no-cache-dir -e /app/apps/api

COPY apps/workers /app/apps/workers
RUN pip install --no-cache-dir "PyYAML>=6.0"

COPY infra/migrations /app/infra/migrations
COPY infra/scripts/apply_migrations.py /app/infra/scripts/apply_migrations.py

COPY --from=web-builder /app/apps/web/package.json /app/apps/web/package-lock.json /app/apps/web/
COPY --from=web-builder /app/apps/web/node_modules /app/apps/web/node_modules
COPY --from=web-builder /app/apps/web/.next /app/apps/web/.next
COPY apps/web/next.config.mjs /app/apps/web/next.config.mjs

RUN printf '%s\n' \
  '#!/usr/bin/env bash' \
  'set -Eeuo pipefail' \
  'truthy() {' \
  '  case "${1:-}" in' \
  '    1|true|TRUE|True|yes|YES|Yes|on|ON|On) return 0 ;;' \
  '    *) return 1 ;;' \
  '  esac' \
  '}' \
  'api_host="${API_HOST:-127.0.0.1}"' \
  'api_port="${API_PORT:-8000}"' \
  'web_host="${WEB_HOST:-0.0.0.0}"' \
  'web_port="${PORT:-${WEB_PORT:-8080}}"' \
  'worker_database_url="${WORKER_DATABASE_URL:-${DATABASE_URL:-}}"' \
  'ingestion_enabled="${HOSTED_INGESTION_SCHEDULER_ENABLED:-${SINGLE_SERVICE_INGESTION_SCHEDULER_ENABLED:-auto}}"' \
  'realtime_backbone_force_ingestion="${REALTIME_BACKBONE_FORCE_INGESTION_ON_START:-true}"' \
  'realtime_backbone_ingestion_disabled="${REALTIME_BACKBONE_INGESTION_DISABLED:-false}"' \
  'realtime_backbone_adapter_keys="official.cwa.rainfall,official.wra.water_level,official.wra_iow.flood_depth,official.ncdr.cap,official.civil_iot.flood_sensor,official.civil_iot.sewer_water_level,official.civil_iot.pump_water_level,official.civil_iot.gate_water_level"' \
  'if [ "${ingestion_enabled}" = "auto" ]; then' \
  '  if [ -n "${worker_database_url}" ]; then' \
  '    ingestion_enabled="true"' \
  '  else' \
  '    ingestion_enabled="false"' \
  '  fi' \
  'fi' \
  'if truthy "${realtime_backbone_force_ingestion}" && [ -n "${worker_database_url}" ]; then' \
  '  ingestion_enabled="true"' \
  'fi' \
  'if truthy "${realtime_backbone_ingestion_disabled}"; then' \
  '  ingestion_enabled="false"' \
  'fi' \
  'scheduler_pid=""' \
  'echo "[start] api=${api_host}:${api_port} web=${web_host}:${web_port} ingestion=${ingestion_enabled}"' \
  'if truthy "${RUN_DATABASE_MIGRATIONS_ON_START:-true}" && [ -n "${worker_database_url}" ]; then' \
  '  echo "[start] applying database migrations"' \
  '  python /app/infra/scripts/apply_migrations.py --database-url "${worker_database_url}"' \
  'fi' \
  'cd /app/apps/api' \
  'echo "[start] launching api"' \
  'python -m uvicorn app.main:app --host "${api_host}" --port "${api_port}" &' \
  'api_pid=$!' \
  'cleanup() {' \
  '  local pid' \
  '  for pid in "${api_pid:-}" "${web_pid:-}" "${scheduler_pid:-}"; do' \
  '    if [ -n "${pid}" ]; then' \
  '      kill "${pid}" 2>/dev/null || true' \
  '    fi' \
  '  done' \
  '  for pid in "${api_pid:-}" "${web_pid:-}" "${scheduler_pid:-}"; do' \
  '    if [ -n "${pid}" ]; then' \
  '      wait "${pid}" 2>/dev/null || true' \
  '    fi' \
  '  done' \
  '}' \
  'trap cleanup EXIT INT TERM' \
  'api_ready=""' \
  'echo "[start] waiting for api health"' \
  'for attempt in $(seq 1 60); do' \
  '  if python -c "import urllib.request; urllib.request.urlopen('"'"'http://${api_host}:${api_port}/health'"'"', timeout=1)" >/dev/null 2>&1; then' \
  '    api_ready="1"' \
  '    break' \
  '  fi' \
  '  sleep 1' \
  'done' \
  'if [ -z "${api_ready}" ]; then' \
  '  echo "[start] api health did not become ready"' \
  '  exit 1' \
  'fi' \
  'echo "[start] api health ready"' \
  'cd /app/apps/web' \
  'echo "[start] launching web"' \
  'node node_modules/next/dist/bin/next start --hostname "${web_host}" --port "${web_port}" &' \
  'web_pid=$!' \
  'if truthy "${ingestion_enabled}"; then' \
  '  echo "[start] launching official ingestion scheduler"' \
  '  export WORKER_DATABASE_URL="${worker_database_url}"' \
  '  if [ -z "${WORKER_DATABASE_URL}" ]; then' \
  '    echo "[start] ingestion scheduler requested but WORKER_DATABASE_URL/DATABASE_URL is empty"' \
  '    exit 1' \
  '  fi' \
  '  if truthy "${realtime_backbone_force_ingestion}"; then' \
  '    export WORKER_ENABLED_ADAPTER_KEYS="${REALTIME_BACKBONE_ADAPTER_KEYS:-${realtime_backbone_adapter_keys}}"' \
  '  else' \
  '    export WORKER_ENABLED_ADAPTER_KEYS="${WORKER_ENABLED_ADAPTER_KEYS:-${realtime_backbone_adapter_keys}}"' \
  '  fi' \
  '  export SOURCE_CWA_ENABLED="${SOURCE_CWA_ENABLED:-true}"' \
  '  export SOURCE_CWA_API_ENABLED="${SOURCE_CWA_API_ENABLED:-true}"' \
  '  export SOURCE_WRA_ENABLED="${SOURCE_WRA_ENABLED:-true}"' \
  '  export SOURCE_WRA_API_ENABLED="${SOURCE_WRA_API_ENABLED:-true}"' \
  '  export SOURCE_WRA_IOW_FLOOD_DEPTH_ENABLED="${SOURCE_WRA_IOW_FLOOD_DEPTH_ENABLED:-true}"' \
  '  export SOURCE_WRA_IOW_FLOOD_DEPTH_API_ENABLED="${SOURCE_WRA_IOW_FLOOD_DEPTH_API_ENABLED:-true}"' \
  '  export SOURCE_NCDR_CAP_ENABLED="${SOURCE_NCDR_CAP_ENABLED:-true}"' \
  '  export SOURCE_NCDR_CAP_API_ENABLED="${SOURCE_NCDR_CAP_API_ENABLED:-true}"' \
  '  export SOURCE_FLOOD_SENSOR_ENABLED="${SOURCE_FLOOD_SENSOR_ENABLED:-true}"' \
  '  export SOURCE_FLOOD_SENSOR_API_ENABLED="${SOURCE_FLOOD_SENSOR_API_ENABLED:-true}"' \
  '  export SOURCE_FLOOD_SENSOR_USE_LIVE="${SOURCE_FLOOD_SENSOR_USE_LIVE:-true}"' \
  '  export SOURCE_CIVIL_IOT_SEWER_ENABLED="${SOURCE_CIVIL_IOT_SEWER_ENABLED:-true}"' \
  '  export SOURCE_CIVIL_IOT_SEWER_API_ENABLED="${SOURCE_CIVIL_IOT_SEWER_API_ENABLED:-true}"' \
  '  export SOURCE_CIVIL_IOT_PUMP_ENABLED="${SOURCE_CIVIL_IOT_PUMP_ENABLED:-true}"' \
  '  export SOURCE_CIVIL_IOT_PUMP_API_ENABLED="${SOURCE_CIVIL_IOT_PUMP_API_ENABLED:-true}"' \
  '  export SOURCE_CIVIL_IOT_GATE_ENABLED="${SOURCE_CIVIL_IOT_GATE_ENABLED:-true}"' \
  '  export SOURCE_CIVIL_IOT_GATE_API_ENABLED="${SOURCE_CIVIL_IOT_GATE_API_ENABLED:-true}"' \
  '  export SCHEDULER_INTERVAL_SECONDS="${SCHEDULER_INTERVAL_SECONDS:-300}"' \
  '  export SCHEDULER_LEASE_TTL_SECONDS="${SCHEDULER_LEASE_TTL_SECONDS:-600}"' \
  '  export WORKER_INSTANCE="${WORKER_INSTANCE:-zeabur-single-service-${HOSTNAME:-local}}"' \
  '  cd /app/apps/workers' \
  '  echo "[start] running initial official ingestion tick"' \
  '  python -m app.main --run-enabled-adapters --persist || echo "[start] initial official ingestion tick failed; scheduler will retry"' \
  '  echo "[start] launching official ingestion scheduler loop"' \
  '  python -m app.main --run-enabled-adapters --persist --scheduler &' \
  '  scheduler_pid=$!' \
  'else' \
  '  echo "[start] official ingestion scheduler disabled"' \
  'fi' \
  'set +e' \
  'wait -n "${api_pid}" "${web_pid}"' \
  'exit_status=$?' \
  'cleanup' \
  'trap - EXIT INT TERM' \
  'exit "${exit_status}"' \
  > /app/start-zeabur-single.sh \
  && chmod +x /app/start-zeabur-single.sh

EXPOSE 8080

CMD ["/app/start-zeabur-single.sh"]
