#!/usr/bin/env bash
set -Eeuo pipefail

truthy() {
  case "${1:-}" in
    1|true|TRUE|True|yes|YES|Yes|on|ON|On) return 0 ;;
    *) return 1 ;;
  esac
}

api_host="${API_HOST:-127.0.0.1}"
api_port="${API_PORT:-8000}"
web_host="${WEB_HOST:-0.0.0.0}"
web_port="${PORT:-${WEB_PORT:-3000}}"
ingestion_enabled="${HOSTED_INGESTION_SCHEDULER_ENABLED:-${SINGLE_SERVICE_INGESTION_SCHEDULER_ENABLED:-false}}"

service_pids=()
all_pids=()
cleanup() {
  if [ "${#all_pids[@]}" -gt 0 ]; then
    kill "${all_pids[@]}" 2>/dev/null || true
    wait "${all_pids[@]}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

cd /app/apps/api
python -m uvicorn app.main:app --host "${api_host}" --port "${api_port}" &
service_pids+=("$!")
all_pids+=("$!")

cd /app/apps/web
node node_modules/next/dist/bin/next start --hostname "${web_host}" --port "${web_port}" &
service_pids+=("$!")
all_pids+=("$!")

if truthy "${ingestion_enabled}"; then
  export WORKER_DATABASE_URL="${WORKER_DATABASE_URL:-${DATABASE_URL:-}}"
  export WORKER_ENABLED_ADAPTER_KEYS="${WORKER_ENABLED_ADAPTER_KEYS:-official.cwa.rainfall,official.wra.water_level}"
  export SCHEDULER_INTERVAL_SECONDS="${SCHEDULER_INTERVAL_SECONDS:-300}"
  export SCHEDULER_LEASE_TTL_SECONDS="${SCHEDULER_LEASE_TTL_SECONDS:-600}"
  export WORKER_INSTANCE="${WORKER_INSTANCE:-zeabur-single-service-${HOSTNAME:-local}}"

  cd /app/apps/workers
  python -m app.main --run-enabled-adapters --persist --scheduler &
  all_pids+=("$!")
fi

set +e
wait -n "${service_pids[@]}"
exit_status=$?
cleanup
trap - EXIT INT TERM
exit "${exit_status}"
