#!/usr/bin/env bash
# Unified production entrypoint.
#
# SERVICE_ROLE selects what this container runs, so the same image can be
# deployed either as today's single service or split into three services
# (which isolates an OOM in one runtime from taking down the others — see
# docs/architecture/realtime-storage-optimization-plan.md Phase 1):
#
#   all        (default) API + Web + optional ingestion scheduler together
#   api        FastAPI only, foreground (never applies migrations)
#   web        Next.js only, foreground (set INTERNAL_API_BASE_URL to the
#              API service URL so /v1 rewrites reach it)
#   scheduler  ingestion scheduler only, foreground (expects migrations to
#              have been applied by the api service)
#   migrate    explicit, bounded migration release job; defaults to plan-only
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
worker_database_url="${WORKER_DATABASE_URL:-${DATABASE_URL:-${POSTGRES_CONNECTION_STRING:-${POSTGRES_URI:-}}}}"
ingestion_enabled="${HOSTED_INGESTION_SCHEDULER_ENABLED:-${SINGLE_SERVICE_INGESTION_SCHEDULER_ENABLED:-auto}}"
realtime_backbone_force_ingestion="${REALTIME_BACKBONE_FORCE_INGESTION_ON_START:-true}"
realtime_backbone_ingestion_disabled="${REALTIME_BACKBONE_INGESTION_DISABLED:-false}"
realtime_backbone_emergency_stop="${REALTIME_BACKBONE_EMERGENCY_STOP:-false}"
realtime_backbone_adapter_keys="official.cwa.rainfall,official.cwa.tide_level,official.wra.water_level,official.wra_iow.flood_depth,official.ncdr.cap,official.civil_iot.sewer_water_level,local.tainan.flood_sensor,official.wra.historical_flood,official.nstc.flood_disaster_points"
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
if truthy "${realtime_backbone_emergency_stop}"; then
  ingestion_enabled="false"
elif truthy "${realtime_backbone_ingestion_disabled}"; then
  if truthy "${realtime_backbone_force_ingestion}" && [ -n "${worker_database_url}" ]; then
    # The old integration runbook used this flag as an unbounded temporary
    # stop. Recovery force mode must be able to retire that stale state. Use
    # REALTIME_BACKBONE_EMERGENCY_STOP for an unconditional current stop.
    echo "[start] legacy ingestion stop ignored because force mode is active"
  else
    ingestion_enabled="false"
  fi
fi

reject_startup_migrations() {
  if truthy "${RUN_DATABASE_MIGRATIONS_ON_START:-false}"; then
    echo "[start] RUN_DATABASE_MIGRATIONS_ON_START is no longer supported; use SERVICE_ROLE=migrate"
    exit 1
  fi
}

run_migration_release() {
  local release_mode="${MIGRATION_RELEASE_MODE:-plan}"
  local release_environment="${APP_ENV:-}"
  local release_sha="${DEPLOYMENT_SHA:-${ZEABUR_GIT_COMMIT_SHA:-}}"
  local expected_current="${MIGRATION_RELEASE_EXPECTED_CURRENT_VERSION:-}"
  local target_version="${MIGRATION_RELEASE_TARGET_VERSION:-}"
  local release_ack="${MIGRATION_RELEASE_ACK:-}"
  local args=()

  if [ -z "${worker_database_url}" ]; then
    echo "[migration-release] no supported database URL is configured"
    exit 1
  fi
  if [ -z "${expected_current}" ] || [ -z "${target_version}" ]; then
    echo "[migration-release] expected current and target versions are required"
    exit 1
  fi
  args=(
    --database-url "${worker_database_url}"
    --expected-current-version "${expected_current}"
    --target-version "${target_version}"
    --release-environment "${release_environment}"
    --release-sha "${release_sha}"
  )
  case "${release_mode}" in
    plan)
      args+=(--plan)
      ;;
    apply)
      args+=(--release-ack "${release_ack}")
      ;;
    *)
      echo "[migration-release] MIGRATION_RELEASE_MODE must be plan or apply"
      exit 1
      ;;
  esac
  echo "[migration-release] mode=${release_mode} environment=${release_environment} expected=${expected_current} target=${target_version}"
  exec python /app/infra/scripts/apply_migrations.py "${args[@]}"
}

configure_backbone_source_gates() {
  local gate
  local gates=(
    SOURCE_CWA_ENABLED
    SOURCE_CWA_API_ENABLED
    SOURCE_WRA_ENABLED
    SOURCE_WRA_API_ENABLED
    SOURCE_WRA_HISTORICAL_FLOOD_ENABLED
    SOURCE_WRA_HISTORICAL_FLOOD_API_ENABLED
    SOURCE_NSTC_FLOOD_DISASTER_POINTS_ENABLED
    SOURCE_NSTC_FLOOD_DISASTER_POINTS_API_ENABLED
    SOURCE_WRA_IOW_FLOOD_DEPTH_ENABLED
    SOURCE_WRA_IOW_FLOOD_DEPTH_API_ENABLED
    SOURCE_NCDR_CAP_ENABLED
    SOURCE_NCDR_CAP_API_ENABLED
    SOURCE_NCDR_CAP_CONTRACT_ENABLED
    SOURCE_CIVIL_IOT_SEWER_ENABLED
    SOURCE_CIVIL_IOT_SEWER_API_ENABLED
    SOURCE_TAINAN_FLOOD_SENSOR_ENABLED
    SOURCE_TAINAN_FLOOD_SENSOR_API_ENABLED
  )

  for gate in "${gates[@]}"; do
    if truthy "${realtime_backbone_force_ingestion}"; then
      # Force mode is the production recovery contract: stale platform values
      # such as an explicit "false" must not silently disable the reviewed
      # backbone. Set REALTIME_BACKBONE_FORCE_INGESTION_ON_START=false to
      # return control to the individual source gates.
      printf -v "${gate}" "%s" "true"
    elif [ -z "${!gate:-}" ]; then
      printf -v "${gate}" "%s" "true"
    fi
    export "${gate}"
  done
}

setup_ingestion_env() {
  local configured_adapter_keys="${WORKER_ENABLED_ADAPTER_KEYS:-}"
  local required_adapter_keys
  export WORKER_DATABASE_URL="${worker_database_url}"
  if [ -z "${WORKER_DATABASE_URL}" ]; then
    echo "[start] ingestion scheduler requested but no supported database URL is configured"
    exit 1
  fi
  if truthy "${realtime_backbone_force_ingestion}"; then
    # A platform value can add reviewed adapters but must not remove a source
    # that the deployed revision declares part of its canonical backbone. This
    # repairs stale deployment values that pre-date newly required sources.
    required_adapter_keys="$(merge_adapter_keys "${realtime_backbone_adapter_keys}" "${REALTIME_BACKBONE_ADAPTER_KEYS:-}")"
    # Force mode guarantees the reviewed baseline but must preserve explicitly
    # configured local adapters instead of silently replacing them.
    export WORKER_ENABLED_ADAPTER_KEYS="$(merge_adapter_keys "${required_adapter_keys}" "${configured_adapter_keys}")"
  else
    export WORKER_ENABLED_ADAPTER_KEYS="${WORKER_ENABLED_ADAPTER_KEYS:-${realtime_backbone_adapter_keys}}"
  fi
  configure_backbone_source_gates
  export SCHEDULER_INTERVAL_SECONDS="${SCHEDULER_INTERVAL_SECONDS:-300}"
  export SCHEDULER_LEASE_TTL_SECONDS="${SCHEDULER_LEASE_TTL_SECONDS:-600}"
  export WORKER_INSTANCE="${WORKER_INSTANCE:-zeabur-single-service-${HOSTNAME:-local}}"
}

case "${role}" in
  migrate)
    run_migration_release
    ;;
  api)
    api_host="${API_HOST:-0.0.0.0}"
    api_port="${PORT:-${API_PORT:-8000}}"
    echo "[start] role=api ${api_host}:${api_port}"
    reject_startup_migrations
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
    if ! truthy "${ingestion_enabled}"; then
      echo "[start] dedicated ingestion scheduler intentionally disabled; recording state and idling"
      python -m app.main --record-runtime-sources-disabled
      exec sleep infinity
    fi
    echo "[start] launching official ingestion scheduler loop (first tick runs immediately)"
    exec python -m app.main --run-v1-baseline-adapters --scheduler
    ;;
  all)
    ;;
  *)
    echo "[start] unknown SERVICE_ROLE '${role}' (expected all|api|web|scheduler|migrate)"
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
reject_startup_migrations
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
  python -m app.main --run-v1-baseline-adapters --scheduler &
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
