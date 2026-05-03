from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from app.adapters.news.public_web import (
    GDELT_MAX_RECORDS_PER_QUERY,
    FetchJson,
    GdeltPublicNewsBackfillAdapter,
    Sleep,
)
from app.adapters.contracts import AdapterRunResult
from app.pipelines.staging import AdapterStagingBatch, build_staging_batch


DEFAULT_TAIWAN_FLOOD_NEWS_QUERIES = (
    '(淹水 OR 積淹水 OR 積水 OR 豪雨) (台灣 OR 台北 OR 新北 OR 桃園 OR 新竹 OR 苗栗 OR 台中 OR 彰化 OR 雲林 OR 嘉義 OR 台南 OR 高雄 OR 屏東 OR 宜蘭 OR 花蓮 OR 台東)',
    '(道路淹水 OR 地下道淹水 OR 排水不及 OR 側溝排水不及) sourcecountry:TW',
)
DEFAULT_GDELT_REHEARSAL_MAX_RECORDS_PER_QUERY = 10
DEFAULT_GDELT_REHEARSAL_CADENCE_SECONDS = 60

GdeltRehearsalMode = Literal["dry-run", "staging-batch"]


@dataclass(frozen=True)
class HistoricalNewsBackfillConfig:
    start_datetime: datetime
    end_datetime: datetime
    fetched_at: datetime
    queries: tuple[str, ...] = DEFAULT_TAIWAN_FLOOD_NEWS_QUERIES
    max_records_per_query: int = DEFAULT_GDELT_REHEARSAL_MAX_RECORDS_PER_QUERY
    request_cadence_seconds: int = DEFAULT_GDELT_REHEARSAL_CADENCE_SECONDS
    gdelt_source_enabled: bool = False
    gdelt_backfill_enabled: bool = False
    source_news_enabled: bool = False
    source_terms_review_ack: bool = False
    fetch_json: FetchJson | None = None
    sleep: Sleep | None = None


@dataclass(frozen=True)
class HistoricalNewsBackfillRehearsalResult:
    mode: GdeltRehearsalMode
    adapter_key: str
    fetched_count: int
    normalized_count: int
    rejected_count: int
    metadata: dict[str, Any]
    batch: AdapterStagingBatch | None = None

    @property
    def status(self) -> str:
        return "succeeded"

    def as_payload(self) -> dict[str, Any]:
        payload = {
            "status": self.status,
            "mode": self.mode,
            "adapter_key": self.adapter_key,
            "fetched_count": self.fetched_count,
            "normalized_count": self.normalized_count,
            "rejected_count": self.rejected_count,
            "metadata": self.metadata,
        }
        if self.batch is not None:
            payload["raw_ref"] = self.batch.raw_snapshot.raw_ref
            payload["accepted_count"] = len(self.batch.accepted)
            payload["staging_rejected_count"] = len(self.batch.rejected)
        return payload


def build_historical_news_backfill_batch(
    config: HistoricalNewsBackfillConfig,
) -> AdapterStagingBatch:
    _ensure_historical_news_backfill_gates(config)
    return build_staging_batch(_run_historical_news_backfill_adapter(config))


def run_historical_news_backfill_rehearsal(
    config: HistoricalNewsBackfillConfig,
    *,
    mode: GdeltRehearsalMode = "dry-run",
) -> HistoricalNewsBackfillRehearsalResult:
    if mode not in ("dry-run", "staging-batch"):
        raise ValueError("GDELT rehearsal mode must be dry-run or staging-batch")

    _ensure_historical_news_backfill_gates(config)
    result = _run_historical_news_backfill_adapter(config)
    batch = build_staging_batch(result) if mode == "staging-batch" else None
    return HistoricalNewsBackfillRehearsalResult(
        mode=mode,
        adapter_key=result.adapter_key,
        fetched_count=len(result.fetched),
        normalized_count=len(result.normalized),
        rejected_count=len(result.rejected),
        metadata=_rehearsal_contract_metadata(config),
        batch=batch,
    )


def _ensure_historical_news_backfill_gates(config: HistoricalNewsBackfillConfig) -> None:
    if not config.gdelt_source_enabled:
        raise RuntimeError("GDELT backfill requires GDELT_SOURCE_ENABLED=true")
    if not config.gdelt_backfill_enabled:
        raise RuntimeError("GDELT backfill is disabled by default")
    if not config.source_news_enabled:
        raise RuntimeError("GDELT backfill requires SOURCE_NEWS_ENABLED=true")
    if not config.source_terms_review_ack:
        raise RuntimeError("GDELT backfill requires SOURCE_TERMS_REVIEW_ACK=true")


def _run_historical_news_backfill_adapter(
    config: HistoricalNewsBackfillConfig,
) -> AdapterRunResult:
    adapter = GdeltPublicNewsBackfillAdapter(
        config.queries,
        fetched_at=config.fetched_at,
        start_datetime=config.start_datetime,
        end_datetime=config.end_datetime,
        max_records_per_query=config.max_records_per_query,
        request_cadence_seconds=config.request_cadence_seconds,
        fetch_json=config.fetch_json,
        sleep=config.sleep,
    )
    return adapter.run()


def _rehearsal_contract_metadata(config: HistoricalNewsBackfillConfig) -> dict[str, Any]:
    return {
        "network_allowed": True,
        "source_gate": "GDELT_SOURCE_ENABLED",
        "news_gate": "SOURCE_NEWS_ENABLED",
        "terms_gate": "SOURCE_TERMS_REVIEW_ACK",
        "backfill_gate": "GDELT_BACKFILL_ENABLED",
        "metadata_only": True,
        "rate_limit_contract": "one bounded GDELT DOC request per query",
        "cadence_seconds": max(0, config.request_cadence_seconds),
        "max_records_per_query": max(
            1,
            min(config.max_records_per_query, GDELT_MAX_RECORDS_PER_QUERY),
        ),
        "query_count": len(tuple(query for query in config.queries if query.strip())),
        "start_datetime": config.start_datetime.isoformat(),
        "end_datetime": config.end_datetime.isoformat(),
    }
