#!/usr/bin/env bash
set -Eeuo pipefail

cd "${GDELT_BACKFILL_WORKDIR:-/app/apps/workers}"

export SOURCE_NEWS_ENABLED="${GDELT_BACKFILL_SOURCE_NEWS_ENABLED:-true}"
export SOURCE_TERMS_REVIEW_ACK="${GDELT_BACKFILL_SOURCE_TERMS_REVIEW_ACK:-true}"
export GDELT_SOURCE_ENABLED="${GDELT_BACKFILL_SOURCE_ENABLED:-true}"
export GDELT_BACKFILL_ENABLED="${GDELT_BACKFILL_ENABLED:-true}"
export GDELT_PRODUCTION_INGESTION_ENABLED="${GDELT_BACKFILL_PRODUCTION_ENABLED:-true}"
export GDELT_REQUIRE_GEOCODER_MATCH="${GDELT_BACKFILL_REQUIRE_GEOCODER_MATCH:-true}"

START="${GDELT_BACKFILL_START:-2016-05-07T00:00:00Z}"
END="${GDELT_BACKFILL_END:-2026-05-07T23:59:59Z}"
SHARD_SIZE="${GDELT_BACKFILL_SHARD_SIZE:-25}"
OFFSET="${GDELT_BACKFILL_OFFSET_START:-0}"
MAX_SHARDS="${GDELT_BACKFILL_MAX_SHARDS:-0}"
MAX_RECORDS="${GDELT_BACKFILL_MAX_RECORDS:-10}"
CADENCE_SECONDS="${GDELT_BACKFILL_CADENCE_SECONDS:-1}"
PROGRESS_INTERVAL="${GDELT_BACKFILL_PROGRESS_INTERVAL:-1}"
TERMS_PER_QUERY="${GDELT_GEOCODER_TERMS_PER_QUERY:-8}"
APPROVAL_PATH="${GDELT_PRODUCTION_APPROVAL_EVIDENCE_PATH:-/app/apps/workers/docs/gdelt-controlled-backfill-approval-2026-05-07.md}"
VILLAGE_TERMS_PATH="${GDELT_VILLAGE_TERMS_PATH:-/app/apps/api/app/data/geocoder/villages.normalized.jsonl.gz}"
ROAD_TERMS_PATH="${GDELT_ROAD_TERMS_PATH:-/app/apps/api/app/data/geocoder/roads-114.normalized.jsonl.gz}"

if [[ -z "${GDELT_BACKFILL_TOTAL_QUERIES:-}" ]]; then
  TOTAL_QUERIES="$(
    python - "$VILLAGE_TERMS_PATH" "$ROAD_TERMS_PATH" "$TERMS_PER_QUERY" <<'PY'
from pathlib import Path
import sys

from app.jobs.taiwan_news_query_plan import (
    build_taiwan_flood_news_queries,
    load_taiwan_geocoder_query_places,
)

places = load_taiwan_geocoder_query_places(
    (Path(sys.argv[1]), Path(sys.argv[2])),
    scopes=("village", "road"),
)
queries = build_taiwan_flood_news_queries(
    (place.term for place in places),
    terms_per_query=int(sys.argv[3]),
)
print(len(queries))
PY
  )"
else
  TOTAL_QUERIES="$GDELT_BACKFILL_TOTAL_QUERIES"
fi

echo "{\"event\":\"gdelt_backfill.shards.started\",\"metadata_only\":true,\"start\":\"$START\",\"end\":\"$END\",\"offset_start\":$OFFSET,\"shard_size\":$SHARD_SIZE,\"total_queries\":$TOTAL_QUERIES,\"max_shards\":$MAX_SHARDS}"

SHARD_INDEX=0
while [[ "$OFFSET" -lt "$TOTAL_QUERIES" ]]; do
  if [[ "$MAX_SHARDS" -gt 0 && "$SHARD_INDEX" -ge "$MAX_SHARDS" ]]; then
    echo "{\"event\":\"gdelt_backfill.shards.paused\",\"metadata_only\":true,\"next_offset\":$OFFSET,\"completed_shards\":$SHARD_INDEX,\"total_queries\":$TOTAL_QUERIES}"
    exit 0
  fi

  echo "{\"event\":\"gdelt_backfill.shard.started\",\"metadata_only\":true,\"offset\":$OFFSET,\"limit\":$SHARD_SIZE,\"shard_index\":$SHARD_INDEX,\"total_queries\":$TOTAL_QUERIES}"
  python -m app.main \
    --run-gdelt-news-production-candidate \
    --persist \
    --gdelt-source-enabled \
    --gdelt-backfill-enabled \
    --gdelt-production-enabled \
    --gdelt-approval-evidence-path "$APPROVAL_PATH" \
    --gdelt-approval-evidence-ack \
    --gdelt-start "$START" \
    --gdelt-end "$END" \
    --gdelt-geocoder-term-path "$VILLAGE_TERMS_PATH" \
    --gdelt-geocoder-term-path "$ROAD_TERMS_PATH" \
    --gdelt-geocoder-scopes village,road \
    --gdelt-geocoder-terms-per-query "$TERMS_PER_QUERY" \
    --gdelt-require-geocoder-match \
    --gdelt-query-offset "$OFFSET" \
    --gdelt-query-limit "$SHARD_SIZE" \
    --gdelt-max-records "$MAX_RECORDS" \
    --gdelt-cadence-seconds "$CADENCE_SECONDS" \
    --gdelt-progress-log-interval "$PROGRESS_INTERVAL"
  echo "{\"event\":\"gdelt_backfill.shard.completed\",\"metadata_only\":true,\"offset\":$OFFSET,\"limit\":$SHARD_SIZE,\"shard_index\":$SHARD_INDEX,\"next_offset\":$((OFFSET + SHARD_SIZE))}"

  OFFSET=$((OFFSET + SHARD_SIZE))
  SHARD_INDEX=$((SHARD_INDEX + 1))
done

echo "{\"event\":\"gdelt_backfill.shards.completed\",\"metadata_only\":true,\"completed_shards\":$SHARD_INDEX,\"total_queries\":$TOTAL_QUERIES}"
