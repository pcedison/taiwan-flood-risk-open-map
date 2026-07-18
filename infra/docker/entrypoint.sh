#!/usr/bin/env bash
# Unified production entrypoint.
#
# SERVICE_ROLE selects what this container runs, so the same image can be
# deployed either as today's single service or split into three services
# (which isolates an OOM in one runtime from taking down the others — see
# docs/architecture/realtime-storage-optimization-plan.md Phase 1):
#
#   all        (default) API + Web + optional ingestion scheduler together
#   api        FastAPI only, foreground (applies migrations first)
#   web        Next.js only, foreground (set INTERNAL_API_BASE_URL to the
#              API service URL so /v1 rewrites reach it)
#   scheduler  ingestion scheduler only, foreground (expects migrations to
#              have been applied by the api service)
set -Eeuo pipefail

truthy() {
  case "${1:-}" in
    1|true|TRUE|True|yes|YES|Yes|on|ON|On) return 0 ;;
    *) return 1 ;;
  esac
}

merge_adapter_keys() {
  local left="${1:-}"
  local right="${2:-}"
  local merged=""
  local key
  local items=()
  IFS=',' read -r -a items <<< "${left},${right}"
  for key in "${items[@]}"; do
    key="${key//[[:space:]]/}"
    if [ -z "${key}" ]; then
      continue
    fi
    case ",${merged}," in
      *",${key},"*) ;;
      *) merged="${merged:+${merged},}${key}" ;;
    esac
  done
  printf '%s' "${merged}"
}

role="${SERVICE_ROLE:-all}"
api_host="${API_HOST:-127.0.0.1}"
api_port="${API_PORT:-8000}"
web_host="${WEB_HOST:-0.0.0.0}"
web_port="${PORT:-${WEB_PORT:-8080}}"
worker_database_url="${WORKER_DATABASE_URL:-${DATABASE_URL:-}}"
ingestion_enabled="${HOSTED_INGESTION_SCHEDULER_ENABLED:-${SINGLE_SERVICE_INGESTION_SCHEDULER_ENABLED:-auto}}"
realtime_backbone_force_ingestion="${REALTIME_BACKBONE_FORCE_INGESTION_ON_START:-true}"
realtime_backbone_ingestion_disabled="${REALTIME_BACKBONE_INGESTION_DISABLED:-false}"
realtime_backbone_adapter_keys="official.cwa.rainfall,official.cwa.tide_level,official.wra.water_level,official.wra_iow.flood_depth,official.ncdr.cap,official.civil_iot.flood_sensor,official.civil_iot.sewer_water_level,official.civil_iot.pump_water_level,official.civil_iot.gate_water_level,local.tainan.flood_sensor"
# Only the loopback hop (the co-located Next.js proxy) is trusted for
# X-Forwarded-* by default; override for split topologies where the API's
# direct peer is the platform ingress instead.
uvicorn_forwarded_allow_ips="${UVICORN_FORWARDED_ALLOW_IPS:-127.0.0.1}"

# In the unified service, API and worker must not silently point at different
# databases.  Let DATABASE_URL inherit the worker URL when only the latter was
# configured, and fail closed when both are configured differently.  Never
# print either URL because it may contain credentials.
if [ "${role}" = "all" ] && [ -n "${DATABASE_URL:-}" ] && [ -n "${WORKER_DATABASE_URL:-}" ] \
  && [ "${DATABASE_URL}" != "${WORKER_DATABASE_URL}" ]; then
  echo "[start] DATABASE_URL and WORKER_DATABASE_URL must match for SERVICE_ROLE=all"
  exit 1
fi
if [ -z "${DATABASE_URL:-}" ] && [ -n "${worker_database_url}" ]; then
  export DATABASE_URL="${worker_database_url}"
fi

if [ "${ingestion_enabled}" = "auto" ]; then
  if [ -n "${worker_database_url}" ]; then
    ingestion_enabled="true"
  else
    ingestion_enabled="false"
  fi
fi
if truthy "${realtime_backbone_force_ingestion}" && [ -n "${worker_database_url}" ]; then
  ingestion_enabled="true"
fi
if truthy "${realtime_backbone_ingestion_disabled}"; then
  ingestion_enabled="false"
fi

apply_migrations() {
  if truthy "${RUN_DATABASE_MIGRATIONS_ON_START:-true}" && [ -n "${worker_database_url}" ]; then
    echo "[start] applying database migrations"
    python /app/infra/scripts/apply_migrations.py --database-url "${worker_database_url}"
  fi
}

setup_ingestion_env() {
  local configured_adapter_keys="${WORKER_ENABLED_ADAPTER_KEYS:-}"
  local required_adapter_keys
  export WORKER_DATABASE_URL="${worker_database_url}"
  if [ -z "${WORKER_DATABASE_URL}" ]; then
    echo "[start] ingestion scheduler requested but WORKER_DATABASE_URL/DATABASE_URL is empty"
    exit 1
  fi
  if truthy "${realtime_backbone_force_ingestion}"; then
    required_adapter_keys="${REALTIME_BACKBONE_ADAPTER_KEYS:-${realtime_backbone_adapter_keys}}"
    # Force mode guarantees the reviewed baseline but must preserve explicitly
    # configured local adapters instead of silently replacing them.
    export WORKER_ENABLED_ADAPTER_KEYS="$(merge_adapter_keys "${required_adapter_keys}" "${configured_adapter_keys}")"
  else
    export WORKER_ENABLED_ADAPTER_KEYS="${WORKER_ENABLED_ADAPTER_KEYS:-${realtime_backbone_adapter_keys}}"
  fi
  export SOURCE_CWA_ENABLED="${SOURCE_CWA_ENABLED:-true}"
  export SOURCE_CWA_API_ENABLED="${SOURCE_CWA_API_ENABLED:-true}"
  export SOURCE_WRA_ENABLED="${SOURCE_WRA_ENABLED:-true}"
  export SOURCE_WRA_API_ENABLED="${SOURCE_WRA_API_ENABLED:-true}"
  export SOURCE_WRA_IOW_FLOOD_DEPTH_ENABLED="${SOURCE_WRA_IOW_FLOOD_DEPTH_ENABLED:-true}"
  export SOURCE_WRA_IOW_FLOOD_DEPTH_API_ENABLED="${SOURCE_WRA_IOW_FLOOD_DEPTH_API_ENABLED:-true}"
  export SOURCE_NCDR_CAP_ENABLED="${SOURCE_NCDR_CAP_ENABLED:-true}"
  export SOURCE_NCDR_CAP_API_ENABLED="${SOURCE_NCDR_CAP_API_ENABLED:-true}"
  export SOURCE_FLOOD_SENSOR_ENABLED="${SOURCE_FLOOD_SENSOR_ENABLED:-true}"
  export SOURCE_FLOOD_SENSOR_API_ENABLED="${SOURCE_FLOOD_SENSOR_API_ENABLED:-true}"
  export SOURCE_FLOOD_SENSOR_USE_LIVE="${SOURCE_FLOOD_SENSOR_USE_LIVE:-true}"
  export SOURCE_CIVIL_IOT_SEWER_ENABLED="${SOURCE_CIVIL_IOT_SEWER_ENABLED:-true}"
  export SOURCE_CIVIL_IOT_SEWER_API_ENABLED="${SOURCE_CIVIL_IOT_SEWER_API_ENABLED:-true}"
  export SOURCE_CIVIL_IOT_PUMP_ENABLED="${SOURCE_CIVIL_IOT_PUMP_ENABLED:-true}"
  export SOURCE_CIVIL_IOT_PUMP_API_ENABLED="${SOURCE_CIVIL_IOT_PUMP_API_ENABLED:-true}"
  export SOURCE_CIVIL_IOT_GATE_ENABLED="${SOURCE_CIVIL_IOT_GATE_ENABLED:-true}"
  export SOURCE_CIVIL_IOT_GATE_API_ENABLED="${SOURCE_CIVIL_IOT_GATE_API_ENABLED:-true}"
  export SOURCE_TAINAN_FLOOD_SENSOR_ENABLED="${SOURCE_TAINAN_FLOOD_SENSOR_ENABLED:-true}"
  export SOURCE_TAINAN_FLOOD_SENSOR_API_ENABLED="${SOURCE_TAINAN_FLOOD_SENSOR_API_ENABLED:-true}"
  export SCHEDULER_INTERVAL_SECONDS="${SCHEDULER_INTERVAL_SECONDS:-300}"
  export SCHEDULER_LEASE_TTL_SECONDS="${SCHEDULER_LEASE_TTL_SECONDS:-600}"
  export WORKER_INSTANCE="${WORKER_INSTANCE:-zeabur-single-service-${HOSTNAME:-local}}"
}

case "${role}" in
  api)
    api_host="${API_HOST:-0.0.0.0}"
    api_port="${PORT:-${API_PORT:-8000}}"
    echo "[start] role=api ${api_host}:${api_port}"
    apply_migrations
    cd /app/apps/api
    exec python -m uvicorn app.main:app --host "${api_host}" --port "${api_port}" --proxy-headers --forwarded-allow-ips "${uvicorn_forwarded_allow_ips}"
    ;;
  web)
    echo "[start] role=web ${web_host}:${web_port} api=${INTERNAL_API_BASE_URL:-unset}"
    if [ "${INTERNAL_API_BASE_URL:-http://127.0.0.1:8000}" = "http://127.0.0.1:8000" ]; then
      echo "[start] warning: INTERNAL_API_BASE_URL points at loopback; set it to the API service URL in split deployments"
    fi
    cd /app/apps/web
    exec node node_modules/next/dist/bin/next start --hostname "${web_host}" --port "${web_port}"
    ;;
  scheduler)
    echo "[start] role=scheduler (expects migrations applied by the api service)"
    setup_ingestion_env
    cd /app/apps/workers
    echo "[start] launching official ingestion scheduler loop (first tick runs immediately)"
    exec python -m app.main --run-enabled-adapters --persist --scheduler
    ;;
  all)
    ;;
  *)
    echo "[start] unknown SERVICE_ROLE '${role}' (expected all|api|web|scheduler)"
    exit 1
    ;;
esac

scheduler_pid=""
echo "[start] api=${api_host}:${api_port} web=${web_host}:${web_port} ingestion=${ingestion_enabled}"
if truthy "${ingestion_enabled}"; then
  # Export the shared source gates before forking the API so public/admin
  # diagnostics describe the same adapters the scheduler actually runs.
  setup_ingestion_env
fi
apply_migrations
if ! truthy "${ingestion_enabled}" && [ -n "${worker_database_url}" ]; then
  echo "[start] recording intentionally disabled ingestion sources"
  cd /app/apps/workers
  python -m app.main --record-runtime-sources-disabled
fi
cd /app/apps/api
echo "[start] launching api"
python -m uvicorn app.main:app --host "${api_host}" --port "${api_port}" --proxy-headers --forwarded-allow-ips "${uvicorn_forwarded_allow_ips}" &
api_pid=$!
cleanup() {
  local pid
  for pid in "${api_pid:-}" "${web_pid:-}" "${scheduler_pid:-}"; do
    if [ -n "${pid}" ]; then
      kill "${pid}" 2>/dev/null || true
    fi
  done
  for pid in "${api_pid:-}" "${web_pid:-}" "${scheduler_pid:-}"; do
    if [ -n "${pid}" ]; then
      wait "${pid}" 2>/dev/null || true
    fi
  done
}
trap cleanup EXIT INT TERM
api_ready=""
echo "[start] waiting for api health"
for attempt in $(seq 1 60); do
  if python -c "import urllib.request; urllib.request.urlopen('http://${api_host}:${api_port}/health', timeout=1)" >/dev/null 2>&1; then
    api_ready="1"
    break
  fi
  sleep 1
done
if [ -z "${api_ready}" ]; then
  echo "[start] api health did not become ready"
  exit 1
fi
echo "[start] api health ready"
cd /app/apps/web
echo "[start] launching web"
node node_modules/next/dist/bin/next start --hostname "${web_host}" --port "${web_port}" &
web_pid=$!
if truthy "${ingestion_enabled}"; then
  echo "[start] launching official ingestion scheduler"
  cd /app/apps/workers
  echo "[start] launching official ingestion scheduler loop (first tick runs immediately)"
  python -m app.main --run-enabled-adapters --persist --scheduler &
  scheduler_pid=$!
else
  echo "[start] official ingestion scheduler disabled"
fi
set +e
if [ -n "${scheduler_pid}" ]; then
  # The public service must not remain green while ingestion has silently
  # stopped.  Let the platform restart the container if any required runtime
  # exits, including the co-located scheduler.
  wait -n "${api_pid}" "${web_pid}" "${scheduler_pid}"
else
  wait -n "${api_pid}" "${web_pid}"
fi
exit_status=$?
cleanup
trap - EXIT INT TERM
exit "${exit_status}"
