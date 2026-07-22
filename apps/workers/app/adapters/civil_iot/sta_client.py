"""Shared OGC SensorThings API (STA) client for Civil IoT Taiwan.

Civil IoT Taiwan publishes WRA flood sensors, river water levels, agricultural
pond levels, sewer levels, pump stations, and CWA rainfall through OGC
SensorThings APIs. This module fetches and flattens the standard STA
``Things``/``Locations``/``Datastreams``/``Observations`` shape into per station
latest-observation records that adapters can normalize.

The higher level adapters (flood sensor, river water level) build on this client
so the STA parsing primitives are written once, mirroring the worker-internal
deduplication recorded in ADR-0010.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, urlsplit
from urllib.request import Request, urlopen

from app.adapters._helpers import optional_float, optional_str, parse_observed_at_utc
from app.adapters.contracts import StationInventoryProof

StaFetchJson = Callable[[str, int], Any]

# Civil IoT Taiwan SensorThings service bases.
STA_WATER_RESOURCE_BASE = "https://sta.colife.org.tw/STA_WaterResource_v2/v1.0/"
STA_RAIN_SEWER_BASE = "https://sta.colife.org.tw/STA_RainSewer/v1.0/"
CIVIL_IOT_HOMEPAGE = "https://ci.taiwan.gov.tw/dsp/"
CIVIL_IOT_USER_AGENT = "FloodRiskTaiwan/0.1 worker-civil-iot-sta"
DEFAULT_STA_TIMEOUT_SECONDS = 8

# Latest single observation per station, ordered newest first.
DEFAULT_THINGS_EXPAND = (
    "Locations,"
    "Datastreams($expand=Observations($orderby=phenomenonTime desc;$top=1))"
)

TAIWAN_COUNTY_ALIASES: tuple[tuple[str, str], ...] = (
    ("臺北市", "臺北市"),
    ("台北市", "臺北市"),
    ("新北市", "新北市"),
    ("桃園市", "桃園市"),
    ("臺中市", "臺中市"),
    ("台中市", "臺中市"),
    ("臺南市", "臺南市"),
    ("台南市", "臺南市"),
    ("高雄市", "高雄市"),
    ("基隆市", "基隆市"),
    ("新竹市", "新竹市"),
    ("嘉義市", "嘉義市"),
    ("新竹縣", "新竹縣"),
    ("苗栗縣", "苗栗縣"),
    ("彰化縣", "彰化縣"),
    ("南投縣", "南投縣"),
    ("雲林縣", "雲林縣"),
    ("嘉義縣", "嘉義縣"),
    ("屏東縣", "屏東縣"),
    ("宜蘭縣", "宜蘭縣"),
    ("花蓮縣", "花蓮縣"),
    ("臺東縣", "臺東縣"),
    ("台東縣", "臺東縣"),
    ("澎湖縣", "澎湖縣"),
    ("金門縣", "金門縣"),
    ("連江縣", "連江縣"),
)


class CivilIotStaError(RuntimeError):
    """Base error for Civil IoT SensorThings client failures."""


class CivilIotStaFetchError(CivilIotStaError):
    """Raised when fetching a SensorThings payload fails."""


class CivilIotStaPayloadError(CivilIotStaError):
    """Raised when a SensorThings payload cannot be parsed."""


@dataclass(frozen=True)
class StaThingsFetchResult:
    records: tuple[Mapping[str, Any], ...]
    station_inventory_proof: StationInventoryProof


def parse_sta_things_payload(
    payload: object,
    *,
    source_url: str,
    datastream_name_contains: str | tuple[str, ...] | None = None,
) -> tuple[Mapping[str, Any], ...]:
    """Flatten an STA ``Things`` collection into latest-observation records.

    Each record carries ``station_id``, ``station_name``, ``observed_at`` (ISO
    UTC), ``value`` (float), ``unit``, optional ``latitude``/``longitude``/
    ``geometry`` (WGS84), ``authority``, ``location_text``, ``datastream_name``,
    and ``source_url``. Stations without a usable latest observation are skipped.

    When ``datastream_name_contains`` is set, the observation is read from the
    first datastream whose name contains that substring (e.g. ``外水位`` for pump
    stations that expose several datastreams); otherwise the first datastream with
    a usable observation is used.
    """

    things = tuple(_things_items(payload))
    return _parse_sta_things_items(
        things,
        source_url=source_url,
        datastream_name_contains=datastream_name_contains,
    )


def _parse_sta_things_items(
    things: tuple[Any, ...],
    *,
    source_url: str,
    datastream_name_contains: str | tuple[str, ...] | None,
) -> tuple[Mapping[str, Any], ...]:
    records: list[Mapping[str, Any]] = []
    for thing in things:
        if not isinstance(thing, Mapping):
            continue
        record = _parse_thing(
            thing,
            source_url=source_url,
            datastream_name_contains=datastream_name_contains,
        )
        if record is not None:
            records.append(record)
    return tuple(records)


def fetch_paginated_sta_things(
    start_url: str,
    *,
    timeout_seconds: int,
    fetch_json: StaFetchJson,
    source_url: str,
    datastream_name_contains: str | tuple[str, ...] | None = None,
) -> StaThingsFetchResult:
    """Fetch all STA Things pages plus a fail-closed station manifest proof."""

    next_url: str | None = _with_count_query(start_url)
    seen_urls: set[str] = set()
    records: list[Mapping[str, Any]] = []
    station_ids: set[str] = set()
    source_items_seen = 0
    missing_station_id_count = 0
    duplicate_station_id_count = 0
    pages_fetched = 0
    pagination_complete = False
    upstream_totals: set[int] = set()
    upstream_count_invalid = False

    while next_url is not None:
        pagination_key = _with_count_query(next_url)
        if pagination_key in seen_urls:
            raise CivilIotStaPayloadError(
                f"Civil IoT SensorThings payload repeated @iot.nextLink: {next_url}"
            )
        seen_urls.add(pagination_key)
        payload = fetch_json(next_url, timeout_seconds)
        pages_fetched += 1

        count_present, upstream_total = _sta_upstream_total(payload)
        if count_present:
            if upstream_total is None:
                upstream_count_invalid = True
            else:
                upstream_totals.add(upstream_total)

        things = tuple(_things_items(payload))
        for thing in things:
            source_items_seen += 1
            station_id = _thing_station_id(thing) if isinstance(thing, Mapping) else None
            if station_id is None:
                missing_station_id_count += 1
            elif station_id in station_ids:
                duplicate_station_id_count += 1
            else:
                station_ids.add(station_id)

        records.extend(
            _parse_sta_things_items(
                things,
                source_url=source_url,
                datastream_name_contains=datastream_name_contains,
            )
        )
        next_url = _sta_next_link(payload)
        if next_url is None:
            pagination_complete = True

    resolved_upstream_total = (
        next(iter(upstream_totals))
        if not upstream_count_invalid and len(upstream_totals) == 1
        else None
    )
    proof = StationInventoryProof(
        upstream_total=resolved_upstream_total,
        pages_fetched=pages_fetched,
        pagination_complete=pagination_complete,
        source_items_seen=source_items_seen,
        missing_station_id_count=missing_station_id_count,
        duplicate_station_id_count=duplicate_station_id_count,
        station_ids=tuple(sorted(station_ids)),
    )
    return StaThingsFetchResult(
        records=tuple(records),
        station_inventory_proof=proof,
    )


def fetch_paginated_sta_things_records(
    start_url: str,
    *,
    timeout_seconds: int,
    fetch_json: StaFetchJson,
    source_url: str,
    datastream_name_contains: str | tuple[str, ...] | None = None,
) -> tuple[Mapping[str, Any], ...]:
    """Compatibility wrapper returning only flattened observation records."""

    return fetch_paginated_sta_things(
        start_url,
        timeout_seconds=timeout_seconds,
        fetch_json=fetch_json,
        source_url=source_url,
        datastream_name_contains=datastream_name_contains,
    ).records


def _things_items(payload: object) -> Iterable[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, Mapping):
        for key in ("value", "Things", "things"):
            items = payload.get(key)
            if isinstance(items, list):
                return items
    raise CivilIotStaPayloadError(
        "Civil IoT SensorThings payload is missing a Things value list"
    )


def _sta_next_link(payload: object) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    next_link = optional_str(payload.get("@iot.nextLink"))
    return next_link or None


def _sta_upstream_total(payload: object) -> tuple[bool, int | None]:
    if not isinstance(payload, Mapping) or "@iot.count" not in payload:
        return False, None
    value = payload.get("@iot.count")
    if isinstance(value, bool):
        return True, None
    if isinstance(value, int):
        return True, value if value >= 0 else None
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return True, int(stripped)
    return True, None


def _with_count_query(url: str) -> str:
    query_keys = {key.lower() for key, _value in parse_qsl(urlsplit(url).query)}
    if "$count" in query_keys:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}$count=true"


def _parse_thing(
    thing: Mapping[str, Any],
    *,
    source_url: str,
    datastream_name_contains: str | tuple[str, ...] | None = None,
) -> Mapping[str, Any] | None:
    properties = thing.get("properties")
    properties = properties if isinstance(properties, Mapping) else {}

    station_id = _thing_station_id(thing) or _first_text(thing, "name")
    if station_id is None:
        return None

    station_name = _first_text(thing, "name", "description") or station_id

    datastream = _select_datastream(thing, datastream_name_contains)
    if datastream is None:
        return None
    observation = _latest_observation(datastream)
    if observation is None:
        return None
    observed_at = parse_observed_at_utc(
        _first_value(observation, "phenomenonTime", "resultTime")
    )
    value = optional_float(observation.get("result"))
    if observed_at is None or value is None:
        return None

    record: dict[str, Any] = {
        "station_id": station_id,
        "station_name": station_name,
        "observed_at": observed_at.isoformat(),
        "value": value,
        "source_url": source_url,
    }

    unit = _datastream_unit(datastream)
    if unit is not None:
        record["unit"] = unit
    datastream_name = optional_str(datastream.get("name"))
    if datastream_name is not None:
        record["datastream_name"] = datastream_name

    authority = _first_text(properties, "authority", "Authority", "owner")
    if authority is not None:
        record["authority"] = authority

    location_text = _location_text(properties)
    if location_text is not None:
        record["location_text"] = location_text

    county = _first_text(
        properties,
        "county",
        "County",
        "city",
        "City",
        "countyName",
        "CountyName",
        "COUNTYNAME",
        "cityName",
        "CityName",
        "CITYNAME",
    ) or _infer_county(properties, station_name)
    if county is not None:
        record["county"] = county

    _add_first_text(
        record,
        "town",
        properties,
        "town",
        "Town",
        "district",
        "District",
        "townName",
        "TownName",
        "TOWNNAME",
        "districtName",
        "DistrictName",
        "DISTRICTNAME",
        "areaName",
        "AreaName",
        "AREANAME",
    )
    _add_first_text(
        record,
        "county_code",
        properties,
        "countyCode",
        "CountyCode",
        "COUNTYCODE",
        "county_code",
        "COUNTY_CODE",
        "cityCode",
        "CityCode",
        "CITYCODE",
    )
    _add_first_text(
        record,
        "area_code",
        properties,
        "areaCode",
        "AreaCode",
        "AREACODE",
        "area_code",
        "AREA_CODE",
        "townCode",
        "TownCode",
        "TOWNCODE",
        "districtCode",
        "DistrictCode",
        "DISTRICTCODE",
    )

    coordinate = _thing_coordinate(thing)
    if coordinate is not None:
        lat, lng = coordinate
        record["latitude"] = lat
        record["longitude"] = lng
        record["geometry"] = {"type": "Point", "coordinates": [lng, lat]}

    return record


def _thing_station_id(thing: Mapping[str, Any]) -> str | None:
    properties = thing.get("properties")
    properties = properties if isinstance(properties, Mapping) else {}
    return _first_text(
        properties,
        "stationID",
        "stationId",
        "station_id",
        "stationNo",
        "ID",
        "id",
    ) or _first_text(thing, "@iot.id")


def _datastreams(thing: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    raw = thing.get("Datastreams")
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in raw if isinstance(item, Mapping))


def _select_datastream(
    thing: Mapping[str, Any],
    name_contains: str | tuple[str, ...] | None,
) -> Mapping[str, Any] | None:
    datastreams = _datastreams(thing)
    name_tokens = _datastream_name_tokens(name_contains)
    if name_tokens:
        for token in name_tokens:
            for datastream in datastreams:
                name = optional_str(datastream.get("name")) or ""
                if token in name and _latest_observation(datastream) is not None:
                    return datastream
        return None
    for datastream in datastreams:
        if _latest_observation(datastream) is not None:
            return datastream
    return None


def _datastream_name_tokens(name_contains: str | tuple[str, ...] | None) -> tuple[str, ...]:
    if name_contains is None:
        return ()
    if isinstance(name_contains, str):
        return (name_contains,)
    return tuple(token for token in name_contains if token)


def _latest_observation(datastream: Mapping[str, Any]) -> Mapping[str, Any] | None:
    observations = datastream.get("Observations")
    if not isinstance(observations, list):
        return None
    for observation in observations:
        if isinstance(observation, Mapping) and observation.get("result") is not None:
            return observation
    return None


def _datastream_unit(datastream: Mapping[str, Any]) -> str | None:
    unit = datastream.get("unitOfMeasurement")
    if isinstance(unit, Mapping):
        return _first_text(unit, "symbol", "name")
    return None


def _location_text(properties: Mapping[str, Any]) -> str | None:
    parts = [
        _first_text(properties, "city", "City", "county", "County"),
        _first_text(properties, "town", "Town", "district", "District"),
        _first_text(properties, "address", "Address"),
    ]
    joined = " ".join(part for part in parts if part)
    return joined or None


def _add_first_text(
    target: dict[str, Any],
    target_key: str,
    item: Mapping[str, Any],
    *source_keys: str,
) -> None:
    value = _first_text(item, *source_keys)
    if value is not None:
        target[target_key] = value


def _infer_county(properties: Mapping[str, Any], station_name: str) -> str | None:
    texts = (
        _first_text(properties, "authority", "Authority", "owner"),
        _first_text(properties, "stationName", "StationName", "STATIONNAME"),
        station_name,
    )
    for text in texts:
        if text is None:
            continue
        for alias, canonical in TAIWAN_COUNTY_ALIASES:
            if alias in text:
                return canonical
    return None


def _thing_coordinate(thing: Mapping[str, Any]) -> tuple[float, float] | None:
    locations = thing.get("Locations")
    if not isinstance(locations, list):
        return None
    for location in locations:
        if not isinstance(location, Mapping):
            continue
        geometry = location.get("location")
        coordinate = _geojson_point(geometry)
        if coordinate is not None:
            return coordinate
    return None


def _geojson_point(geometry: object) -> tuple[float, float] | None:
    if not isinstance(geometry, Mapping):
        return None
    coordinates = geometry.get("coordinates")
    if isinstance(geometry.get("geometry"), Mapping):
        # SensorThings may wrap a GeoJSON Feature.
        return _geojson_point(geometry["geometry"])
    if not isinstance(coordinates, (list, tuple)) or len(coordinates) < 2:
        return None
    lng = optional_float(coordinates[0])
    lat = optional_float(coordinates[1])
    if lat is None or lng is None:
        return None
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lng <= 180.0):
        return None
    return (lat, lng)


def _first_text(item: Mapping[str, Any], *keys: str) -> str | None:
    return optional_str(_first_value(item, *keys))


def _first_value(item: Mapping[str, Any], *keys: str) -> object:
    for key in keys:
        value = item.get(key)
        if value is not None:
            return value
    return None


def fetch_sta_json(url: str, timeout_seconds: int) -> Any:
    request = Request(
        _request_url(url),
        headers={
            "Accept": "application/json",
            "User-Agent": CIVIL_IOT_USER_AGENT,
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload: Any = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise CivilIotStaFetchError(
            f"Civil IoT SensorThings API returned HTTP {exc.code}"
        ) from exc
    except (URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CivilIotStaFetchError(
            f"Civil IoT SensorThings API request failed: {exc}"
        ) from exc

    if not isinstance(payload, (Mapping, list)):
        raise CivilIotStaPayloadError(
            "Civil IoT SensorThings API returned a non-object/list JSON payload"
        )
    return payload


def _request_url(url: str) -> str:
    return quote(url, safe=":/?&=$,();'@%+")
