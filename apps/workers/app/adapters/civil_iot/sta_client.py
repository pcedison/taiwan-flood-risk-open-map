"""Shared OGC SensorThings API (STA) client for Civil IoT Taiwan.

Civil IoT Taiwan (``ci.taiwan.gov.tw``) publishes WRA flood sensors, river water
levels, agricultural pond levels, sewer levels, pump stations, and CWA rainfall
through one OGC SensorThings API. This module fetches and flattens the standard
STA ``Things``/``Locations``/``Datastreams``/``Observations`` shape into per
station latest-observation records that adapters can normalize.

The higher level adapters (flood sensor, river water level) build on this client
so the STA parsing primitives are written once, mirroring the worker-internal
deduplication recorded in ADR-0010.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.adapters._helpers import optional_float, optional_str, parse_observed_at_utc

StaFetchJson = Callable[[str, int], Any]

# Civil IoT Taiwan water-resource SensorThings service base.
STA_WATER_RESOURCE_BASE = "https://sta.ci.taiwan.gov.tw/STA_WaterResource_v2/v1.0/"
CIVIL_IOT_HOMEPAGE = "https://ci.taiwan.gov.tw/dsp/"
CIVIL_IOT_USER_AGENT = "FloodRiskTaiwan/0.1 worker-civil-iot-sta"
DEFAULT_STA_TIMEOUT_SECONDS = 8

# Latest single observation per station, ordered newest first.
DEFAULT_THINGS_EXPAND = (
    "Locations,"
    "Datastreams($expand=Observations($orderby=phenomenonTime desc;$top=1))"
)


class CivilIotStaError(RuntimeError):
    """Base error for Civil IoT SensorThings client failures."""


class CivilIotStaFetchError(CivilIotStaError):
    """Raised when fetching a SensorThings payload fails."""


class CivilIotStaPayloadError(CivilIotStaError):
    """Raised when a SensorThings payload cannot be parsed."""


def parse_sta_things_payload(
    payload: object,
    *,
    source_url: str,
    datastream_name_contains: str | None = None,
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

    things = _things_items(payload)
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


def _parse_thing(
    thing: Mapping[str, Any],
    *,
    source_url: str,
    datastream_name_contains: str | None = None,
) -> Mapping[str, Any] | None:
    properties = thing.get("properties")
    properties = properties if isinstance(properties, Mapping) else {}

    station_id = _first_text(
        properties,
        "stationID",
        "stationId",
        "station_id",
        "stationNo",
        "ID",
        "id",
    ) or _first_text(thing, "@iot.id", "name")
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

    coordinate = _thing_coordinate(thing)
    if coordinate is not None:
        lat, lng = coordinate
        record["latitude"] = lat
        record["longitude"] = lng
        record["geometry"] = {"type": "Point", "coordinates": [lng, lat]}

    return record


def _datastreams(thing: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    raw = thing.get("Datastreams")
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in raw if isinstance(item, Mapping))


def _select_datastream(
    thing: Mapping[str, Any],
    name_contains: str | None,
) -> Mapping[str, Any] | None:
    datastreams = _datastreams(thing)
    if name_contains:
        for datastream in datastreams:
            name = optional_str(datastream.get("name")) or ""
            if name_contains in name and _latest_observation(datastream) is not None:
                return datastream
        return None
    for datastream in datastreams:
        if _latest_observation(datastream) is not None:
            return datastream
    return None


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
        url,
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
