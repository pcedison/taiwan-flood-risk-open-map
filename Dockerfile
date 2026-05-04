FROM node:22-bookworm-slim AS web-builder

WORKDIR /app/apps/web

COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci

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

RUN npm run build && npm prune --omit=dev

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

COPY --from=web-builder /app/apps/web/package.json /app/apps/web/package-lock.json /app/apps/web/
COPY --from=web-builder /app/apps/web/node_modules /app/apps/web/node_modules
COPY --from=web-builder /app/apps/web/.next /app/apps/web/.next
COPY apps/web/next.config.mjs /app/apps/web/next.config.mjs

RUN printf '%s\n' \
  '#!/usr/bin/env bash' \
  'set -Eeuo pipefail' \
  'api_host="${API_HOST:-127.0.0.1}"' \
  'api_port="${API_PORT:-8000}"' \
  'web_host="${WEB_HOST:-0.0.0.0}"' \
  'web_port="${PORT:-${WEB_PORT:-3000}}"' \
  'cd /app/apps/api' \
  'python -m uvicorn app.main:app --host "${api_host}" --port "${api_port}" &' \
  'api_pid=$!' \
  'cleanup() {' \
  '  kill "${api_pid}" "${web_pid:-0}" 2>/dev/null || true' \
  '  wait "${api_pid}" "${web_pid:-0}" 2>/dev/null || true' \
  '}' \
  'trap cleanup EXIT INT TERM' \
  'cd /app/apps/web' \
  'node node_modules/next/dist/bin/next start --hostname "${web_host}" --port "${web_port}" &' \
  'web_pid=$!' \
  'set +e' \
  'wait -n "${api_pid}" "${web_pid}"' \
  'exit_status=$?' \
  'cleanup' \
  'trap - EXIT INT TERM' \
  'exit "${exit_status}"' \
  > /app/start-zeabur-single.sh \
  && chmod +x /app/start-zeabur-single.sh

EXPOSE 3000

CMD ["/app/start-zeabur-single.sh"]
