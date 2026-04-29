from __future__ import annotations

import json
import math
import ssl
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

HealthStatus = Literal["healthy", "degraded", "failed"]
ObservationType = Literal["rainfall", "water_level"]

CWA_RAINFALL_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/O-A0002-001"
WRA_WATER_LEVEL_URL = "https://opendata.wra.gov.tw/api/v2/73c4c3de-4045-4765-abeb-89f9f9cd5ff0"
WRA_STATION_URL = "https://opendata.wra.gov.tw/api/v2/c4acc691-7416-40ca-9464-292c0c00da92"
DEFAULT_CWA_AUTHORIZATION = "rdec-key-123-45678-011121314"
USER_AGENT = "FloodRiskTaiwan/0.1 local-development"
NEARBY_STATION_LIMIT_M = 25_000.0
TAIPEI_TZ = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class OfficialRealtimeObservation:
    source_id: str
    source_name: str
    event_type: ObservationType
    title: str
    summary: str
    observed_at: datetime
    ingested_at: datetime
    lat: float
    lng: float
    distance_to_query_m: float
    confidence: float
    freshness_score: float
    source_weight: float
    risk_factor: float


@dataclass(frozen=True)
class OfficialRealtimeSourceStatus:
    source_id: str
    name: str
    health_status: HealthStatus
    observed_at: datetime | None
    ingested_at: datetime | None
    message: str | None = None


@dataclass(frozen=True)
class OfficialRealtimeBundle:
    observations: tuple[OfficialRealtimeObservation, ...]
    source_statuses: tuple[OfficialRealtimeSourceStatus, ...]


@dataclass(frozen=True)
class _RainfallStation:
    station_id: str
    station_name: str
    county: str | None
    town: str | None
    lat: float
    lng: float
    observed_at: datetime
    rainfall_10m: float | None
    rainfall_1h: float
    rainfall_24h: float | None


@dataclass(frozen=True)
class _WaterLevelStation:
    station_id: str
    station_name: str
    river_name: str | None
    lat: float
    lng: float
    observed_at: datetime
    water_level_m: float
    alert_level_1_m: float | None
    alert_level_2_m: float | None


_json_cache: dict[str, tuple[datetime, Any]] = {}


def fetch_official_realtime_bundle(
    *,
    lat: float,
    lng: float,
    radius_m: int,
    cwa_authorization: str | None = DEFAULT_CWA_AUTHORIZATION,
    enabled: bool = True,
    now: datetime | None = None,
) -> OfficialRealtimeBundle:
    checked_at = now or datetime.now(UTC)
    if not enabled:
        return OfficialRealtimeBundle(
            observations=(),
            source_statuses=(
                OfficialRealtimeSourceStatus(
                    source_id="cwa-rainfall",
                    name="中央氣象署即時雨量",
                    health_status="degraded",
                    observed_at=None,
                    ingested_at=checked_at,
                    message="即時雨量資料來源目前已停用。",
                ),
                OfficialRealtimeSourceStatus(
                    source_id="wra-water-level",
                    name="經濟部水利署即時水位",
                    health_status="degraded",
                    observed_at=None,
                    ingested_at=checked_at,
                    message="即時水位資料來源目前已停用。",
                ),
            ),
        )

    observations: list[OfficialRealtimeObservation] = []
    statuses: list[OfficialRealtimeSourceStatus] = []

    rainfall = _nearest_rainfall_observation(
        lat=lat,
        lng=lng,
        radius_m=radius_m,
        cwa_authorization=cwa_authorization,
        checked_at=checked_at,
    )
    observations.extend(rainfall[0])
    statuses.append(rainfall[1])

    water_level = _nearest_water_level_observation(
        lat=lat,
        lng=lng,
        radius_m=radius_m,
        checked_at=checked_at,
    )
    observations.extend(water_level[0])
    statuses.append(water_level[1])

    return OfficialRealtimeBundle(observations=tuple(observations), source_statuses=tuple(statuses))


def _nearest_rainfall_observation(
    *,
    lat: float,
    lng: float,
    radius_m: int,
    cwa_authorization: str | None,
    checked_at: datetime,
) -> tuple[list[OfficialRealtimeObservation], OfficialRealtimeSourceStatus]:
    stations = _fetch_cwa_rainfall_stations(cwa_authorization)
    if not stations:
        return (
            [],
            OfficialRealtimeSourceStatus(
                source_id="cwa-rainfall",
                name="中央氣象署即時雨量",
                health_status="failed",
                observed_at=None,
                ingested_at=checked_at,
                message="即時雨量資料暫時無法取得。",
            ),
        )

    nearest = _nearest_station(stations, lat=lat, lng=lng)
    if nearest is None:
        return (
            [],
            OfficialRealtimeSourceStatus(
                source_id="cwa-rainfall",
                name="中央氣象署即時雨量",
                health_status="degraded",
                observed_at=None,
                ingested_at=checked_at,
                message="即時雨量資料已接入，但目前沒有可定位的測站。",
            ),
        )

    station, distance = nearest
    status = OfficialRealtimeSourceStatus(
        source_id="cwa-rainfall",
        name="中央氣象署即時雨量",
        health_status="healthy",
        observed_at=station.observed_at,
        ingested_at=checked_at,
        message=f"採用最近雨量站「{station.station_name}」，距查詢點約 {round(distance):,} m。",
    )

    if distance > max(radius_m, NEARBY_STATION_LIMIT_M):
        return ([], status)

    summary = f"最近雨量站「{station.station_name}」1 小時雨量 {station.rainfall_1h:.1f} mm"
    if station.rainfall_10m is not None:
        summary = f"{summary}，10 分鐘雨量 {station.rainfall_10m:.1f} mm"
    if station.rainfall_24h is not None:
        summary = f"{summary}，24 小時累積 {station.rainfall_24h:.1f} mm"

    return (
        [
            OfficialRealtimeObservation(
                source_id=f"cwa-rainfall:{station.station_id}:{station.observed_at.isoformat()}",
                source_name="中央氣象署即時雨量",
                event_type="rainfall",
                title=f"中央氣象署雨量站：{station.station_name}",
                summary=f"{summary}。",
                observed_at=station.observed_at,
                ingested_at=checked_at,
                lat=station.lat,
                lng=station.lng,
                distance_to_query_m=distance,
                confidence=0.92,
                freshness_score=_freshness_score(station.observed_at, checked_at, max_age_minutes=120),
                source_weight=1.0,
                risk_factor=_rainfall_risk_factor(station.rainfall_1h),
            )
        ],
        status,
    )


def _nearest_water_level_observation(
    *,
    lat: float,
    lng: float,
    radius_m: int,
    checked_at: datetime,
) -> tuple[list[OfficialRealtimeObservation], OfficialRealtimeSourceStatus]:
    stations = _fetch_wra_water_level_stations()
    if not stations:
        return (
            [],
            OfficialRealtimeSourceStatus(
                source_id="wra-water-level",
                name="經濟部水利署即時水位",
                health_status="failed",
                observed_at=None,
                ingested_at=checked_at,
                message="即時水位資料暫時無法取得。",
            ),
        )

    nearest = _nearest_station(stations, lat=lat, lng=lng)
    if nearest is None:
        return (
            [],
            OfficialRealtimeSourceStatus(
                source_id="wra-water-level",
                name="經濟部水利署即時水位",
                health_status="degraded",
                observed_at=None,
                ingested_at=checked_at,
                message="即時水位資料已接入，但目前沒有可定位的測站。",
            ),
        )

    station, distance = nearest
    status = OfficialRealtimeSourceStatus(
        source_id="wra-water-level",
        name="經濟部水利署即時水位",
        health_status="healthy",
        observed_at=station.observed_at,
        ingested_at=checked_at,
        message=f"採用最近水位站「{station.station_name}」，距查詢點約 {round(distance):,} m。",
    )

    if distance > max(radius_m, NEARBY_STATION_LIMIT_M):
        return ([], status)

    threshold = station.alert_level_2_m or station.alert_level_1_m
    if threshold is None:
        summary = f"最近水位站「{station.station_name}」水位 {station.water_level_m:.2f} m"
    else:
        gap = threshold - station.water_level_m
        summary = (
            f"最近水位站「{station.station_name}」水位 {station.water_level_m:.2f} m，"
            f"距警戒水位約 {gap:.2f} m"
        )
    if station.river_name:
        summary = f"{summary}（{station.river_name}）"

    return (
        [
            OfficialRealtimeObservation(
                source_id=f"wra-water-level:{station.station_id}:{station.observed_at.isoformat()}",
                source_name="經濟部水利署即時水位",
                event_type="water_level",
                title=f"水利署水位站：{station.station_name}",
                summary=f"{summary}。",
                observed_at=station.observed_at,
                ingested_at=checked_at,
                lat=station.lat,
                lng=station.lng,
                distance_to_query_m=distance,
                confidence=0.88,
                freshness_score=_freshness_score(station.observed_at, checked_at, max_age_minutes=180),
                source_weight=1.0,
                risk_factor=_water_level_risk_factor(
                    water_level_m=station.water_level_m,
                    alert_level_1_m=station.alert_level_1_m,
                    alert_level_2_m=station.alert_level_2_m,
                ),
            )
        ],
        status,
    )


def _fetch_cwa_rainfall_stations(authorization: str | None) -> tuple[_RainfallStation, ...]:
    params = {
        "Authorization": authorization or DEFAULT_CWA_AUTHORIZATION,
        "format": "JSON",
    }
    payload = _fetch_cached_json("cwa-rainfall", f"{CWA_RAINFALL_URL}?{urlencode(params)}", ttl=300)
    stations = payload.get("records", {}).get("Station", []) if isinstance(payload, dict) else []
    if not isinstance(stations, list):
        return ()

    parsed: list[_RainfallStation] = []
    for item in stations:
        if not isinstance(item, dict):
            continue
        station = _parse_cwa_station(item)
        if station is not None:
            parsed.append(station)
    return tuple(parsed)


def _parse_cwa_station(item: dict[str, Any]) -> _RainfallStation | None:
    geo_info = item.get("GeoInfo")
    rainfall = item.get("RainfallElement")
    obs_time = item.get("ObsTime")
    if not isinstance(geo_info, dict) or not isinstance(rainfall, dict) or not isinstance(obs_time, dict):
        return None

    coordinate = _wgs84_coordinate(geo_info.get("Coordinates"))
    observed_at = _parse_datetime(obs_time.get("DateTime"))
    rainfall_1h = _precipitation_value(rainfall.get("Past1hr"))
    if coordinate is None or observed_at is None or rainfall_1h is None:
        return None

    lat, lng = coordinate
    return _RainfallStation(
        station_id=str(item.get("StationId", "")),
        station_name=str(item.get("StationName") or "未命名雨量站"),
        county=_optional_str(geo_info.get("CountyName")),
        town=_optional_str(geo_info.get("TownName")),
        lat=lat,
        lng=lng,
        observed_at=observed_at,
        rainfall_10m=_precipitation_value(rainfall.get("Past10Min")),
        rainfall_1h=rainfall_1h,
        rainfall_24h=_precipitation_value(rainfall.get("Past24hr")),
    )


def _fetch_wra_water_level_stations() -> tuple[_WaterLevelStation, ...]:
    realtime_payload = _fetch_cached_json(
        "wra-water-level",
        f"{WRA_WATER_LEVEL_URL}?{urlencode({'format': 'JSON', 'sort': '_importdate desc', 'limit': 5000})}",
        ttl=300,
    )
    metadata_payload = _fetch_cached_json(
        "wra-water-stations",
        f"{WRA_STATION_URL}?{urlencode({'format': 'JSON', 'limit': 5000})}",
        ttl=86_400,
    )
    if not isinstance(realtime_payload, list) or not isinstance(metadata_payload, list):
        return ()

    metadata_by_id = {
        str(item.get("basinidentifier")): item
        for item in metadata_payload
        if isinstance(item, dict) and item.get("observationstatus") == "現存"
    }

    parsed: list[_WaterLevelStation] = []
    for item in realtime_payload:
        if not isinstance(item, dict):
            continue
        station_id = str(item.get("stationid") or "")
        metadata = metadata_by_id.get(station_id)
        if metadata is None:
            continue
        station = _parse_wra_station(item, metadata)
        if station is not None:
            parsed.append(station)
    return tuple(parsed)


def _parse_wra_station(
    realtime: dict[str, Any],
    metadata: dict[str, Any],
) -> _WaterLevelStation | None:
    coordinate = _twd97_xy_to_wgs84(metadata.get("locationbytwd97_xy"))
    observed_at = _parse_datetime(realtime.get("datetime"), default_tz=TAIPEI_TZ)
    water_level = _float_value(realtime.get("waterlevel"))
    if coordinate is None or observed_at is None or water_level is None:
        return None
    if water_level <= -90:
        return None

    lat, lng = coordinate
    return _WaterLevelStation(
        station_id=str(realtime.get("stationid") or metadata.get("basinidentifier")),
        station_name=str(metadata.get("observatoryname") or "未命名水位站"),
        river_name=_optional_str(metadata.get("rivername")),
        lat=lat,
        lng=lng,
        observed_at=observed_at,
        water_level_m=water_level,
        alert_level_1_m=_float_value(metadata.get("alertlevel1")),
        alert_level_2_m=_float_value(metadata.get("alertlevel2")),
    )


def _fetch_cached_json(cache_key: str, url: str, *, ttl: int) -> Any:
    now = datetime.now(UTC)
    cached = _json_cache.get(cache_key)
    if cached is not None:
        cached_at, payload = cached
        if now - cached_at < timedelta(seconds=ttl):
            return payload

    payload = _fetch_json(url)
    _json_cache[cache_key] = (now, payload)
    return payload


def _fetch_json(url: str) -> Any:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=8) as response:
            return json.loads(response.read().decode("utf-8"))
    except ssl.SSLError:
        return _fetch_json_without_certificate_verification(request)
    except HTTPError:
        return None
    except URLError as exc:
        if isinstance(exc.reason, ssl.SSLError):
            return _fetch_json_without_certificate_verification(request)
        return None
    except (TimeoutError, json.JSONDecodeError):
        return None


def _fetch_json_without_certificate_verification(request: Request) -> Any:
    try:
        with urlopen(request, timeout=8, context=ssl._create_unverified_context()) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return None


def _nearest_station[T](
    stations: tuple[T, ...],
    *,
    lat: float,
    lng: float,
) -> tuple[T, float] | None:
    nearest: tuple[T, float] | None = None
    for station in stations:
        distance = _distance_m(lat, lng, getattr(station, "lat"), getattr(station, "lng"))
        if nearest is None or distance < nearest[1]:
            nearest = (station, distance)
    return nearest


def _wgs84_coordinate(coordinates: object) -> tuple[float, float] | None:
    if not isinstance(coordinates, list):
        return None
    fallback: tuple[float, float] | None = None
    for coordinate in coordinates:
        if not isinstance(coordinate, dict):
            continue
        lat = _float_value(coordinate.get("StationLatitude"))
        lng = _float_value(coordinate.get("StationLongitude"))
        if lat is None or lng is None:
            continue
        value = (lat, lng)
        if coordinate.get("CoordinateName") == "WGS84":
            return value
        fallback = value
    return fallback


def _twd97_xy_to_wgs84(value: object) -> tuple[float, float] | None:
    if not isinstance(value, str):
        return None
    parts = value.split()
    if len(parts) != 2:
        return None
    x = _float_value(parts[0])
    y = _float_value(parts[1])
    if x is None or y is None:
        return None

    a = 6378137.0
    b = 6356752.314245
    lng0 = math.radians(121)
    k0 = 0.9999
    dx = 250000.0
    dy = 0.0
    e = math.sqrt(1 - (b * b) / (a * a))

    x -= dx
    y -= dy
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


def _precipitation_value(value: object) -> float | None:
    if not isinstance(value, dict):
        return None
    precipitation = _float_value(value.get("Precipitation"))
    if precipitation is None or precipitation < 0:
        return None
    return precipitation


def _float_value(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value))
    except ValueError:
        return None


def _parse_datetime(value: object, *, default_tz=UTC) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=default_tz).astimezone(UTC)
    return parsed.astimezone(UTC)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _rainfall_risk_factor(rainfall_1h: float) -> float:
    if rainfall_1h >= 80:
        return 1.0
    if rainfall_1h >= 40:
        return 0.7
    if rainfall_1h >= 20:
        return 0.35
    if rainfall_1h >= 10:
        return 0.15
    return 0.0


def _water_level_risk_factor(
    *,
    water_level_m: float,
    alert_level_1_m: float | None,
    alert_level_2_m: float | None,
) -> float:
    threshold = alert_level_2_m or alert_level_1_m
    if threshold is None:
        return 0.0
    gap = threshold - water_level_m
    if gap <= 0:
        return 1.0
    if gap <= 0.5:
        return 0.75
    if gap <= 1.0:
        return 0.45
    if gap <= 2.0:
        return 0.2
    return 0.0


def _freshness_score(observed_at: datetime, checked_at: datetime, *, max_age_minutes: int) -> float:
    age_minutes = max((checked_at - observed_at).total_seconds() / 60, 0.0)
    if age_minutes >= max_age_minutes:
        return 0.25
    return max(0.25, 1 - (age_minutes / max_age_minutes))


def _distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371008.8
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(
        delta_lambda / 2
    ) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
