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
# Rate limiting must see the real client, not the Next.js proxy hop.
# The app takes the right-most non-proxy entry of this header (spoof-safe);
# see apps/api/app/api/services/client_signal.py.
ENV PUBLIC_RATE_LIMIT_CLIENT_HEADER=X-Forwarded-For
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

COPY infra/docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Run as a non-root user; only Next.js needs a writable .next cache.
RUN useradd --create-home --uid 10001 app   && chown -R app:app /app/apps/web/.next
ENV HOME=/home/app
USER app

EXPOSE 8080

CMD ["/app/entrypoint.sh"]
