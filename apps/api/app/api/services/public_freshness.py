"""Data-freshness blocks, source-limitation messages, and lookup predicates.

Pure helpers shared by the public risk assessment flow. They never perform
I/O; the route layer supplies observations, records, and lookup results.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.api.schemas import DataFreshness, Evidence
from app.domain.history import HistoricalFloodRecord, OfficialFloodDisasterLookup
from app.domain.history.news_enrichment import OnDemandNewsSearchResult
from app.domain.realtime import OfficialRealtimeBundle, OfficialRealtimeSourceStatus

OBSERVED_HISTORICAL_EVENT_TYPES = {"flood_report", "road_closure"}


def persisted_official_realtime_data_freshness(
    evidence_items: tuple[Evidence, ...],
    *,
    now: datetime,
) -> list[DataFreshness]:
    freshness_items: list[DataFreshness] = []
    for event_type, source_id, name in (
        ("rainfall", "cwa-rainfall", "中央氣象署即時雨量"),
        ("water_level", "wra-water-level", "水利署即時水位"),
    ):
        source_items = [
            item
            for item in evidence_items
            if item.source_type == "official" and item.event_type == event_type
        ]
        if not source_items:
            continue
        observed_values: list[datetime] = []
        for item in source_items:
            observed_value = item.observed_at or item.occurred_at
            if observed_value is not None:
                observed_values.append(observed_value)
        latest_observed = max(observed_values) if observed_values else None
        latest_ingested = max(item.ingested_at for item in source_items)
        is_fresh = (
            latest_observed is not None
            and is_recent_official_realtime_observation(latest_observed, now)
        )
        freshness_items.append(
            DataFreshness(
                source_id=source_id,
                name=name,
                health_status="healthy" if is_fresh else "degraded",
                observed_at=latest_observed,
                ingested_at=latest_ingested,
                feature_count=len(source_items),
                message=(
                    f"已使用 {len(source_items)} 筆系統定期保存的{name}，"
                    "作為正式站可信來源。"
                    if is_fresh
                    else (
                        f"系統定期保存的{name}已過期或缺少觀測時間；"
                        "正式站不使用未受監控的即時 API 備援查詢，因此暫不判定此即時來源風險。"
                    )
                ),
            )
        )
    return freshness_items


def is_recent_official_realtime_observation(observed_at: datetime, now: datetime) -> bool:
    comparable_observed_at = observed_at
    if comparable_observed_at.tzinfo is None and now.tzinfo is not None:
        comparable_observed_at = comparable_observed_at.replace(tzinfo=now.tzinfo)
    comparable_now = now
    if comparable_now.tzinfo is None and comparable_observed_at.tzinfo is not None:
        comparable_now = comparable_now.replace(tzinfo=comparable_observed_at.tzinfo)
    return comparable_now - timedelta(hours=6) <= comparable_observed_at <= (
        comparable_now + timedelta(minutes=5)
    )


def use_on_demand_public_news(settings: object) -> bool:
    if not getattr(settings, "historical_news_on_demand_enabled", False):
        return False
    # On-demand lookup stores and displays citation metadata only. Full historical
    # news backfill and writeback still remain behind their own source/terms gates.
    return True


def needs_historical_event_lookup(
    *,
    historical_records: tuple[tuple[HistoricalFloodRecord, float], ...],
    db_evidence_items: tuple[Evidence, ...] | None,
) -> bool:
    return (
        not historical_records
        and not has_observed_historical_event(db_evidence_items or ())
    )


def should_attempt_public_news_lookup(
    *,
    historical_records: tuple[tuple[HistoricalFloodRecord, float], ...],
    db_evidence_items: tuple[Evidence, ...] | None,
) -> bool:
    return not has_public_news_evidence(
        historical_records=historical_records,
        db_evidence_items=db_evidence_items,
    )


def has_public_news_evidence(
    *,
    historical_records: tuple[tuple[HistoricalFloodRecord, float], ...],
    db_evidence_items: tuple[Evidence, ...] | None,
) -> bool:
    return any(
        record.source_type == "news" and record.event_type in OBSERVED_HISTORICAL_EVENT_TYPES
        for record, _distance_m in historical_records
    ) or any(
        item.source_type == "news" and item.event_type in OBSERVED_HISTORICAL_EVENT_TYPES
        for item in (db_evidence_items or ())
    )


def has_observed_historical_event(evidence_items: tuple[Evidence, ...]) -> bool:
    return any(
        item.event_type in OBSERVED_HISTORICAL_EVENT_TYPES
        for item in evidence_items
    )


def on_demand_data_freshness(
    result: OnDemandNewsSearchResult,
    *,
    now: datetime,
) -> list[DataFreshness]:
    if not result.attempted:
        return []
    return [
        DataFreshness(
            source_id=result.source_id,
            name="公開新聞／Wiki 即時補查",
            health_status=result.health_status if not result.records else "healthy",
            observed_at=max(
                (record.observed_at for record in result.records if record.observed_at is not None),
                default=None,
            ),
            ingested_at=now,
            feature_count=len(result.records),
            message=result.message,
        )
    ]


def official_flood_disaster_data_freshness(
    lookup: OfficialFloodDisasterLookup,
) -> list[DataFreshness]:
    if not lookup.attempted:
        return []
    return [
        DataFreshness(
            source_id=lookup.source_id,
            name=lookup.name,
            health_status=lookup.health_status,
            observed_at=lookup.observed_at,
            ingested_at=lookup.ingested_at,
            feature_count=len(lookup.records),
            message=lookup.message,
        )
    ]


def historical_freshness_message(
    historical_records: tuple[tuple[HistoricalFloodRecord, float], ...],
) -> str:
    if not historical_records:
        return "查詢半徑內尚未有已匯入的歷史淹水紀錄；目前屬於資料不足，不能判定為低風險。"
    return (
        f"查詢半徑內找到 {len(historical_records)} 筆已匯入歷史淹水公開紀錄；"
        "目前完整新聞回填仍在 Phase 2 管線建置中。"
    )


def historical_data_freshness(
    *,
    historical_records: tuple[tuple[HistoricalFloodRecord, float], ...],
    db_evidence_items: tuple[Evidence, ...] | None,
    now: datetime,
) -> DataFreshness:
    if db_evidence_items is None:
        return DataFreshness(
            source_id="historical-flood-records",
            name="Historical flood fallback records",
            health_status="healthy" if historical_records else "unknown",
            observed_at=max((record.occurred_at for record, _ in historical_records), default=None),
            ingested_at=now,
            feature_count=len(historical_records),
            message=historical_freshness_message(historical_records),
        )

    observed_values = [
        observed_at
        for item in db_evidence_items
        for observed_at in (item.observed_at or item.occurred_at,)
        if observed_at is not None
    ]
    latest_observed = max(observed_values, default=None)
    latest_ingested = max((item.ingested_at for item in db_evidence_items), default=None)
    only_flood_potential = bool(db_evidence_items) and all(
        item.event_type == "flood_potential" for item in db_evidence_items
    )
    return DataFreshness(
        source_id="db-evidence",
        name="淹水潛勢與歷史資料庫" if only_flood_potential else "歷史淹水紀錄與公開新聞",
        health_status=(
            "degraded"
            if only_flood_potential
            else "healthy"
            if db_evidence_items
            else "unknown"
        ),
        observed_at=latest_observed,
        ingested_at=latest_ingested or now,
        feature_count=len(db_evidence_items),
        message=(
            f"查詢半徑內與 {len(db_evidence_items)} 筆淹水潛勢規劃圖資相交；"
            "這是情境參考，不是實際歷史淹水事件；仍需公開新聞或災情紀錄佐證。"
            if only_flood_potential
            else f"查詢半徑內找到 {len(db_evidence_items)} 筆已審核歷史資料。"
            if db_evidence_items
            else "查詢半徑內目前沒有已審核歷史資料；這是資料不足，不代表沒有淹水風險。"
        ),
    )


def freshness_from_status(status: OfficialRealtimeSourceStatus) -> DataFreshness:
    return DataFreshness(
        source_id=status.source_id,
        name=status.name,
        health_status=status.health_status,
        observed_at=status.observed_at,
        ingested_at=status.ingested_at,
        message=status.message,
    )


def visible_source_limitations(
    bundle: OfficialRealtimeBundle,
    historical_records: tuple[tuple[HistoricalFloodRecord, float], ...],
    db_evidence_items: tuple[Evidence, ...] | None,
    on_demand_news: OnDemandNewsSearchResult,
) -> list[str]:
    limitations: list[str] = []
    observation_types = {observation.event_type for observation in bundle.observations}
    persisted_types = persisted_official_observation_types(db_evidence_items or ())
    statuses = {status.source_id: status for status in bundle.source_statuses}

    if "rainfall" not in observation_types and "rainfall" not in persisted_types:
        rainfall = statuses.get("cwa-rainfall")
        if rainfall is not None:
            limitations.append(rainfall.message or "即時雨量資料目前沒有可用測站。")
    if "water_level" not in observation_types and "water_level" not in persisted_types:
        water_level = statuses.get("wra-water-level")
        if water_level is not None:
            limitations.append(water_level.message or "即時水位資料目前沒有可用測站。")
    has_historical_event = (
        bool(historical_records)
        or has_observed_historical_event(db_evidence_items or ())
        or bool(on_demand_news.records)
    )
    if not has_historical_event:
        limitations.append(
            "查詢半徑內尚未匯入實際歷史淹水事件或公開新聞紀錄；"
            "目前資料不足，淹水潛勢圖資只能作為情境參考，不能標記為低風險或購屋安全。"
        )
    if on_demand_news.attempted and not on_demand_news.records and on_demand_news.message and not has_historical_event:
        news_message = on_demand_news.message.rstrip()
        separator = "" if news_message.endswith(("。", ".", "！", "!", "？", "?")) else "。"
        if on_demand_news.health_status == "disabled":
            limitations.append(news_message)
        else:
            limitations.append(
                f"公開新聞補查未取得可用事件：{news_message}{separator}"
                "這代表資料仍不足，不代表該地點沒有淹水紀錄。"
            )
    return limitations


def persisted_official_observation_types(evidence_items: tuple[Evidence, ...]) -> set[str]:
    return {
        item.event_type
        for item in evidence_items
        if item.source_type == "official" and item.event_type in {"rainfall", "water_level"}
    }
