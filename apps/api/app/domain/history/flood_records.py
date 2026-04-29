from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from math import asin, cos, radians, sin, sqrt
import re
from typing import Literal


@dataclass(frozen=True)
class HistoricalFloodRecord:
    source_id: str
    source_name: str
    source_type: Literal["official", "news", "forum", "social", "user_report", "derived"]
    event_type: Literal["flood_report", "road_closure", "flood_potential"]
    title: str
    summary: str
    url: str
    occurred_at: datetime
    ingested_at: datetime
    lat: float
    lng: float
    confidence: float
    freshness_score: float
    source_weight: float
    risk_factor: float


_TAIWAN_TZ = timezone(timedelta(hours=8))
_ROAD_PATTERN = re.compile(r"[\u4e00-\u9fff]{1,12}(?:路|街|大道)(?:[一二三四五六七八九十]+段)?(?:\d+巷)?")
_HISTORICAL_FLOOD_RECORDS = (
    HistoricalFloodRecord(
        source_id="history-news:tainan-annan-2025-08-02:pei-an-yi-an",
        source_name="公開新聞：台南安南區積淹水",
        source_type="news",
        event_type="flood_report",
        title="2025-08-02 台南安南區怡安路、培安路一帶積淹水",
        summary="公開新聞紀錄指出，2025 年 8 月颱風外圍環流與豪雨期間，安南區怡安路、培安路一帶出現局部積淹水。",
        url="https://udn.com/news/story/7326/8913573",
        occurred_at=datetime(2025, 8, 2, 8, 0, tzinfo=_TAIWAN_TZ),
        ingested_at=datetime(2026, 4, 29, 9, 0, tzinfo=UTC),
        lat=23.038818,
        lng=120.213493,
        confidence=0.86,
        freshness_score=0.95,
        source_weight=1.0,
        risk_factor=1.0,
    ),
    HistoricalFloodRecord(
        source_id="history-news:tainan-annan-2025-08-02:liukuailiao",
        source_name="公開新聞：六塊寮排水周邊積淹水",
        source_type="news",
        event_type="flood_report",
        title="2025-08-02 六塊寮排水負荷不足造成周邊道路積淹水",
        summary="公開報導提及六塊寮排水水位暴漲、周邊側溝排水不及，安南區多處道路出現積淹水。",
        url="https://udn.com/news/story/6656/8913429",
        occurred_at=datetime(2025, 8, 2, 8, 0, tzinfo=_TAIWAN_TZ),
        ingested_at=datetime(2026, 4, 29, 9, 0, tzinfo=UTC),
        lat=23.038506,
        lng=120.213051,
        confidence=0.82,
        freshness_score=0.95,
        source_weight=1.0,
        risk_factor=1.0,
    ),
    HistoricalFloodRecord(
        source_id="history-news:tainan-annan-2025-08-02:an-feng",
        source_name="公開影音新聞：安南區抽排水紀錄",
        source_type="news",
        event_type="flood_report",
        title="2025-08-02 安南區培安路、安豐六街周邊抽排水紀錄",
        summary="公開影音新聞紀錄台南安南區局部積淹水與抽水機運轉情形，可作為附近路段歷史淹水佐證。",
        url="https://video.ltn.com.tw/article/MpiXTulCRbM/PLI7xntdRxhw1UWsgraa6LMK0szgn9mLbn",
        occurred_at=datetime(2025, 8, 2, 8, 0, tzinfo=_TAIWAN_TZ),
        ingested_at=datetime(2026, 4, 29, 9, 0, tzinfo=UTC),
        lat=23.04653,
        lng=120.21495,
        confidence=0.78,
        freshness_score=0.95,
        source_weight=0.9,
        risk_factor=1.0,
    ),
    HistoricalFloodRecord(
        source_id="history-news:tainan-annan-2025-08-02:changxi-section-2-yahoo",
        source_name="公開新聞：台南安南區長溪路二段積淹水",
        source_type="news",
        event_type="flood_report",
        title="2025-08-02 台南安南區長溪路二段多處淹水",
        summary="公開新聞紀錄指出，2025 年 8 月台南清晨大雷雨造成安南區安中路一段、長溪路二段、公學路等處積淹水。",
        url="https://tw.news.yahoo.com/%E5%8F%B0%E5%8D%97%E5%8F%88%E6%B7%B9-%E6%B8%85%E6%99%A8%E9%9B%B7%E8%81%B2-%E8%BD%9F%E9%86%92-%E5%B0%8F%E6%9D%B1%E5%9C%B0%E4%B8%8B%E9%81%93-%E6%B0%B8%E5%BA%B7%E5%A4%9A%E8%99%95%E6%B7%B9%E6%B0%B4-012800130.html",
        occurred_at=datetime(2025, 8, 2, 8, 0, tzinfo=_TAIWAN_TZ),
        ingested_at=datetime(2026, 4, 29, 9, 0, tzinfo=UTC),
        lat=23.04697,
        lng=120.20344,
        confidence=0.84,
        freshness_score=0.95,
        source_weight=1.0,
        risk_factor=1.0,
    ),
    HistoricalFloodRecord(
        source_id="history-news:tainan-annan-2025-08-02:changxi-section-2-ebc",
        source_name="公開新聞：長溪路二段淹水通行風險",
        source_type="news",
        event_type="flood_report",
        title="2025-08-02 長溪路二段傳出淹水仍有機車通行",
        summary="公開新聞紀錄安南區長溪路二段亦傳出淹水情形，仍有機車騎士冒險通行，作為該路段歷史淹水佐證。",
        url="https://news.ebc.net.tw/news/living/504875",
        occurred_at=datetime(2025, 8, 2, 8, 0, tzinfo=_TAIWAN_TZ),
        ingested_at=datetime(2026, 4, 29, 9, 0, tzinfo=UTC),
        lat=23.04697,
        lng=120.20344,
        confidence=0.82,
        freshness_score=0.95,
        source_weight=1.0,
        risk_factor=1.0,
    ),
    HistoricalFloodRecord(
        source_id="history-news:tainan-annan-2021-08-02:changxi-section-2-lane-410",
        source_name="公開新聞：長溪路二段410巷積淹水",
        source_type="news",
        event_type="flood_report",
        title="2021-08-02 長溪路二段410巷積淹水與交通管制",
        summary="公開新聞紀錄長溪路二段410巷等多處路段積淹水，警方拉起封鎖線管制交通，可作為多年歷史佐證。",
        url="https://stage.cdns.com.tw/articles/436878",
        occurred_at=datetime(2021, 8, 2, 8, 0, tzinfo=_TAIWAN_TZ),
        ingested_at=datetime(2026, 4, 29, 9, 0, tzinfo=UTC),
        lat=23.04697,
        lng=120.20344,
        confidence=0.76,
        freshness_score=0.85,
        source_weight=0.85,
        risk_factor=1.0,
    ),
)


def nearby_historical_flood_records(
    *,
    lat: float,
    lng: float,
    radius_m: int,
    location_text: str | None = None,
) -> tuple[tuple[HistoricalFloodRecord, float], ...]:
    matches: list[tuple[HistoricalFloodRecord, float]] = []
    normalized_location_text = _normalize_text(location_text or "")
    for record in _HISTORICAL_FLOOD_RECORDS:
        distance_m = _haversine_m(lat, lng, record.lat, record.lng)
        if distance_m <= radius_m or (
            normalized_location_text
            and distance_m <= max(radius_m, 2000)
            and _record_matches_location_text(record, normalized_location_text)
        ):
            matches.append((record, distance_m))
    return tuple(sorted(matches, key=lambda item: item[1]))


def _record_matches_location_text(record: HistoricalFloodRecord, normalized_text: str) -> bool:
    searchable = _normalize_text(" ".join((record.title, record.summary, record.source_name)))
    if normalized_text in searchable:
        return True
    return any(term and term in normalized_text for term in _road_terms(searchable))


def historical_record_matches_location_text(
    record: HistoricalFloodRecord,
    location_text: str | None,
) -> bool:
    normalized_text = _normalize_text(location_text or "")
    return bool(normalized_text) and _record_matches_location_text(record, normalized_text)


def _road_terms(text: str) -> tuple[str, ...]:
    terms: list[str] = []
    for match in _ROAD_PATTERN.finditer(text):
        term = _trim_admin_prefix(match.group(0))
        if term and term not in terms:
            terms.append(term)
    return tuple(terms)


def _trim_admin_prefix(value: str) -> str:
    for marker in ("區", "鄉", "鎮", "市", "縣"):
        if marker in value:
            value = value.rsplit(marker, 1)[-1]
    return value


def _normalize_text(text: str) -> str:
    return text.replace("臺", "台").replace(" ", "").strip()


def _haversine_m(lat_a: float, lng_a: float, lat_b: float, lng_b: float) -> float:
    earth_radius_m = 6371008.8
    lat_a_rad = radians(lat_a)
    lat_b_rad = radians(lat_b)
    d_lat = radians(lat_b - lat_a)
    d_lng = radians(lng_b - lng_a)
    haversine = sin(d_lat / 2) ** 2 + cos(lat_a_rad) * cos(lat_b_rad) * sin(d_lng / 2) ** 2
    return 2 * earth_radius_m * asin(sqrt(haversine))
