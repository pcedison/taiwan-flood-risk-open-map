from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from functools import lru_cache
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from typing import Literal

from app.domain.history.flood_records import HistoricalFloodRecord


DATA_GOV_DATASET_ID = "130016"
DATA_GOV_URL = "https://data.gov.tw/dataset/130016"
RESOURCE_URL = "https://mas.nstc.gov.tw/OPENDATA/GetFile?fileodr=1&format=csv&serialno=455"
SOURCE_ID = "official-flood-disaster-points"
SOURCE_NAME = "官方資料：近5年淹水災點"
_TAIWAN_TZ = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class OfficialFloodDisasterLookup:
    attempted: bool
    source_id: str
    name: str
    health_status: Literal["healthy", "degraded", "failed", "disabled", "unknown"]
    message: str
    records: tuple[tuple[HistoricalFloodRecord, float], ...] = ()
    observed_at: datetime | None = None
    ingested_at: datetime | None = None


def lookup_official_flood_disaster_points(
    *,
    lat: float,
    lng: float,
    radius_m: int,
    csv_path: str | None,
    enabled: bool,
    now: datetime,
    limit: int = 25,
) -> OfficialFloodDisasterLookup:
    if not enabled:
        return OfficialFloodDisasterLookup(
            attempted=False,
            source_id=SOURCE_ID,
            name=SOURCE_NAME,
            health_status="disabled",
            message="官方淹水災點資料來源未啟用。",
            ingested_at=now,
        )
    if not csv_path:
        return OfficialFloodDisasterLookup(
            attempted=True,
            source_id=SOURCE_ID,
            name=SOURCE_NAME,
            health_status="failed",
            message="官方淹水災點資料未設定本地快照路徑。",
            ingested_at=now,
        )

    try:
        records = load_official_flood_disaster_records(csv_path)
    except OSError:
        return OfficialFloodDisasterLookup(
            attempted=True,
            source_id=SOURCE_ID,
            name=SOURCE_NAME,
            health_status="failed",
            message="官方淹水災點資料本地快照暫時無法讀取。",
            ingested_at=now,
        )
    except ValueError as exc:
        return OfficialFloodDisasterLookup(
            attempted=True,
            source_id=SOURCE_ID,
            name=SOURCE_NAME,
            health_status="failed",
            message=f"官方淹水災點資料格式無法解析：{exc}",
            ingested_at=now,
        )

    matches: list[tuple[HistoricalFloodRecord, float]] = []
    for record in records:
        distance_m = _haversine_m(lat, lng, record.lat, record.lng)
        if distance_m <= radius_m:
            matches.append((record, distance_m))

    ordered = tuple(sorted(matches, key=lambda item: item[1])[: max(1, limit)])
    latest_observed = max((record.occurred_at for record, _ in ordered), default=None)
    if ordered:
        return OfficialFloodDisasterLookup(
            attempted=True,
            source_id=SOURCE_ID,
            name=SOURCE_NAME,
            health_status="healthy",
            message=(
                f"官方近5年淹水災點資料命中 {len(ordered)} 筆；"
                "此資料提供年度與點位，作為官方歷史淹水事件佐證。"
            ),
            records=ordered,
            observed_at=latest_observed,
            ingested_at=now,
        )
    return OfficialFloodDisasterLookup(
        attempted=True,
        source_id=SOURCE_ID,
        name=SOURCE_NAME,
        health_status="healthy",
        message=(
            "官方近5年淹水災點資料已查詢，半徑內未命中；"
            "這不代表該地點沒有淹水紀錄。"
        ),
        observed_at=None,
        ingested_at=now,
    )


def load_official_flood_disaster_records(csv_path: str) -> tuple[HistoricalFloodRecord, ...]:
    path = Path(csv_path)
    return _load_official_flood_disaster_records(str(path), path.stat().st_mtime_ns)


@lru_cache(maxsize=4)
def _load_official_flood_disaster_records(
    csv_path: str,
    mtime_ns: int,
) -> tuple[HistoricalFloodRecord, ...]:
    del mtime_ns
    text = _read_csv_text(Path(csv_path))
    return parse_official_flood_disaster_csv(text)


def _read_csv_text(path: Path) -> str:
    payload = path.read_bytes()
    for encoding in ("utf-8-sig", "cp950"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8-sig", errors="replace")


def parse_official_flood_disaster_csv(text: str) -> tuple[HistoricalFloodRecord, ...]:
    reader = csv.DictReader(text.splitlines())
    required_fields = {"FID", "year", "X_97", "Y_97", "source"}
    missing = required_fields.difference(reader.fieldnames or ())
    if missing:
        raise ValueError(f"missing required field(s): {', '.join(sorted(missing))}")

    records: list[HistoricalFloodRecord] = []
    for row in reader:
        fid = _text(row.get("FID"))
        year = _int_value(row.get("year"))
        x = _float_value(row.get("X_97"))
        y = _float_value(row.get("Y_97"))
        source = _text(row.get("source")) or "unknown"
        if not fid or year is None or x is None or y is None:
            continue
        coordinate = _twd97_tm2_121_to_wgs84(x, y)
        if coordinate is None:
            continue
        lat, lng = coordinate
        if not _within_taiwan_bounds(lat, lng):
            continue
        occurred_at = datetime(year, 12, 31, 12, 0, tzinfo=_TAIWAN_TZ)
        source_id = f"data-gov-130016:{year}:{source}:{fid}"
        records.append(
            HistoricalFloodRecord(
                source_id=source_id,
                source_name=SOURCE_NAME,
                source_type="official",
                event_type="flood_report",
                title=f"{year} 官方淹水災害情資點位（{source} #{fid}）",
                summary=(
                    "data.gov.tw dataset 130016 彙整防救災部會署淹水災害情資點位；"
                    "此筆資料提供年度與座標點，未提供完整事件時間、淹水深度或地址。"
                ),
                url=DATA_GOV_URL,
                occurred_at=occurred_at,
                ingested_at=datetime(2026, 5, 13, 0, 0, tzinfo=UTC),
                lat=lat,
                lng=lng,
                confidence=0.82,
                freshness_score=_freshness_score(year),
                source_weight=1.0,
                risk_factor=1.0,
            )
        )
    return tuple(records)


def _twd97_tm2_121_to_wgs84(x: float, y: float) -> tuple[float, float] | None:
    # TWD97 / TM2 zone 121, used by the dataset's X_97/Y_97 fields.
    import math

    a = 6378137.0
    b = 6356752.314245
    lng0 = math.radians(121)
    k0 = 0.9999
    dx = 250000.0
    e = math.sqrt(1 - (b * b) / (a * a))

    x -= dx
    m = y / k0
    mu = m / (a * (1 - e**2 / 4 - 3 * e**4 / 64 - 5 * e**6 / 256))
    e1 = (1 - math.sqrt(1 - e**2)) / (1 + math.sqrt(1 - e**2))

    fp = (
        mu
        + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu)
        + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
        + (151 * e1**3 / 96) * math.sin(6 * mu)
        + (1097 * e1**4 / 512) * math.sin(8 * mu)
    )

    e2 = e**2 / (1 - e**2)
    c1 = e2 * math.cos(fp) ** 2
    t1 = math.tan(fp) ** 2
    r1 = a * (1 - e**2) / ((1 - e**2 * math.sin(fp) ** 2) ** 1.5)
    n1 = a / math.sqrt(1 - e**2 * math.sin(fp) ** 2)
    d = x / (n1 * k0)

    lat = fp - (n1 * math.tan(fp) / r1) * (
        d**2 / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1**2 - 9 * e2) * d**4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1**2 - 252 * e2 - 3 * c1**2) * d**6 / 720
    )
    lng = lng0 + (
        d
        - (1 + 2 * t1 + c1) * d**3 / 6
        + (5 - 2 * c1 + 28 * t1 - 3 * c1**2 + 8 * e2 + 24 * t1**2) * d**5 / 120
    ) / math.cos(fp)
    return (math.degrees(lat), math.degrees(lng))


def _freshness_score(year: int) -> float:
    if year >= 2022:
        return 0.9
    if year >= 2020:
        return 0.82
    return 0.74


def _haversine_m(lat_a: float, lng_a: float, lat_b: float, lng_b: float) -> float:
    earth_radius_m = 6371008.8
    lat_a_rad = radians(lat_a)
    lat_b_rad = radians(lat_b)
    d_lat = radians(lat_b - lat_a)
    d_lng = radians(lng_b - lng_a)
    haversine = sin(d_lat / 2) ** 2 + cos(lat_a_rad) * cos(lat_b_rad) * sin(d_lng / 2) ** 2
    return 2 * earth_radius_m * asin(sqrt(haversine))


def _within_taiwan_bounds(lat: float, lng: float) -> bool:
    return 21.7 <= lat <= 25.5 and 119.0 <= lng <= 122.5


def _float_value(value: object) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _int_value(value: object) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _text(value: object) -> str:
    return str(value or "").strip()
