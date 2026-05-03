from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.adapters.news.public_web import FetchJson, GdeltPublicNewsBackfillAdapter
from app.pipelines.staging import AdapterStagingBatch, build_staging_batch


DEFAULT_TAIWAN_FLOOD_NEWS_QUERIES = (
    '(淹水 OR 積淹水 OR 積水 OR 豪雨) (台灣 OR 台北 OR 新北 OR 桃園 OR 新竹 OR 苗栗 OR 台中 OR 彰化 OR 雲林 OR 嘉義 OR 台南 OR 高雄 OR 屏東 OR 宜蘭 OR 花蓮 OR 台東)',
    '(道路淹水 OR 地下道淹水 OR 排水不及 OR 側溝排水不及) sourcecountry:TW',
)


@dataclass(frozen=True)
class HistoricalNewsBackfillConfig:
    start_datetime: datetime
    end_datetime: datetime
    fetched_at: datetime
    queries: tuple[str, ...] = DEFAULT_TAIWAN_FLOOD_NEWS_QUERIES
    max_records_per_query: int = 250
    gdelt_backfill_enabled: bool = False
    source_news_enabled: bool = False
    source_terms_review_ack: bool = False
    fetch_json: FetchJson | None = None


def build_historical_news_backfill_batch(
    config: HistoricalNewsBackfillConfig,
) -> AdapterStagingBatch:
    _ensure_historical_news_backfill_gates(config)
    adapter = GdeltPublicNewsBackfillAdapter(
        config.queries,
        fetched_at=config.fetched_at,
        start_datetime=config.start_datetime,
        end_datetime=config.end_datetime,
        max_records_per_query=config.max_records_per_query,
        fetch_json=config.fetch_json,
    )
    return build_staging_batch(adapter.run())


def _ensure_historical_news_backfill_gates(config: HistoricalNewsBackfillConfig) -> None:
    if not config.gdelt_backfill_enabled:
        raise RuntimeError("GDELT backfill is disabled by default")
    if not config.source_news_enabled:
        raise RuntimeError("GDELT backfill requires SOURCE_NEWS_ENABLED=true")
    if not config.source_terms_review_ack:
        raise RuntimeError("GDELT backfill requires SOURCE_TERMS_REVIEW_ACK=true")
