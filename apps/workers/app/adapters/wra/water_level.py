from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from app.adapters._helpers import optional_str, parse_datetime, stable_evidence_id
from app.adapters.contracts import (
    AdapterMetadata,
    AdapterRunResult,
    EventType,
    IngestionStatus,
    NormalizedEvidence,
    RawSourceItem,
    SourceFamily,
)


FetchJson = Callable[[str, int], Any]

WRA_WATER_LEVEL_API_URL = (
    "https://opendata.wra.gov.tw/api/v2/73c4c3de-4045-4765-abeb-89f9f9cd5ff0"
    "?format=JSON&sort=_importdate+desc&limit=5000"
)
WRA_WATER_LEVEL_ATTRIBUTION = "Water Resources Agency"
WRA_WATER_LEVEL_USER_AGENT = "FloodRiskTaiwan/0.1 worker-wra-water-level"
DEFAULT_WRA_WATER_LEVEL_TIMEOUT_SECONDS = 8

WRA_WATER_LEVEL_METADATA = AdapterMetadata(
    key="official.wra.water_level",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=True,
    display_name="WRA water level observation adapter",
)


class WraWaterLevelAdapterError(RuntimeError):
    """Base error for WRA water level adapter failures."""


class WraWaterLevelFetchError(WraWaterLevelAdapterError):
    """Raised when fetching WRA water level API payloads fails."""


class WraWaterLevelPayloadError(WraWaterLevelAdapterError):
    """Raised when the WRA water level API payload shape is not parseable."""


class WraWaterLevelApiAdapter:
    metadata = WRA_WATER_LEVEL_METADATA

    def __init__(
        self,
        *,
        api_url: str | None = None,
        api_token: str | None = None,
        timeout_seconds: int = DEFAULT_WRA_WATER_LEVEL_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_json: FetchJson | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._api_url = (api_url or WRA_WATER_LEVEL_API_URL).strip()
        self._api_token = api_token
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_json = fetch_json or _fetch_json
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        request_url = _wra_water_level_request_url(self._api_url, self._api_token)
        source_url = _wra_water_level_source_url(self._api_url)
        try:
            payload = self._fetch_json(request_url, self._timeout_seconds)
        except WraWaterLevelAdapterError:
            raise
        except Exception as exc:
            raise WraWaterLevelFetchError(f"WRA water level fetcher failed: {exc}") from exc

        records = parse_wra_water_level_api_payload(payload, source_url=source_url)
        fetched_at = self._fetched_at or datetime.now(UTC)
        return tuple(
            RawSourceItem(
                source_id=_source_id(record),
                source_url=str(record["source_url"]),
                fetched_at=fetched_at,
                payload=record,
                raw_snapshot_key=self._raw_snapshot_key,
            )
            for record in records
        )

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize_water_level_record(self.metadata, raw_item)

    def run(self) -> AdapterRunResult:
        fetched = self.fetch()
        normalized: list[NormalizedEvidence] = []
        rejected: list[str] = []

        for raw_item in fetched:
            evidence = self.normalize(raw_item)
            if evidence is None:
                rejected.append(raw_item.source_id)
            else:
                normalized.append(evidence)

        return AdapterRunResult(
            adapter_key=self.metadata.key,
            fetched=fetched,
            normalized=tuple(normalized),
            rejected=tuple(rejected),
        )


class WraWaterLevelAdapter:
    metadata = WRA_WATER_LEVEL_METADATA

    def __init__(
        self,
        records: Iterable[Mapping[str, Any]],
        *,
        fetched_at: datetime,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._records = tuple(records)
        self._fetched_at = fetched_at
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        return tuple(
            RawSourceItem(
                source_id=_source_id(record),
                source_url=str(record["source_url"]),
                fetched_at=self._fetched_at,
                payload=record,
                raw_snapshot_key=self._raw_snapshot_key,
            )
            for record in self._records
        )

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize_water_level_record(self.metadata, raw_item)

    def run(self) -> AdapterRunResult:
        fetched = self.fetch()
        normalized: list[NormalizedEvidence] = []
        rejected: list[str] = []

        for raw_item in fetched:
            evidence = self.normalize(raw_item)
            if evidence is None:
                rejected.append(raw_item.source_id)
            else:
                normalized.append(evidence)

        return AdapterRunResult(
            adapter_key=self.metadata.key,
            fetched=fetched,
            normalized=tuple(normalized),
            rejected=tuple(rejected),
        )


def parse_wra_water_level_api_payload(
    payload: object,
    *,
    source_url: str,
) -> tuple[Mapping[str, Any], ...]:
    items = _water_level_items(payload)
    parsed: list[Mapping[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        record = _parse_wra_station_record(item, source_url=source_url)
        if record is not None:
            parsed.append(record)
    return tuple(parsed)


def _normalize_water_level_record(
    metadata: AdapterMetadata,
    raw_item: RawSourceItem,
) -> NormalizedEvidence | None:
    payload = raw_item.payload
    station_name = str(payload.get("station_name", "")).strip()
    observed_at = parse_datetime(payload.get("observed_at"))
    water_level_m = _optional_float(payload.get("water_level_m"))
    warning_level_m = _optional_float(payload.get("warning_level_m"))

    if not station_name or observed_at is None or water_level_m is None:
        return None

    river_name = optional_str(payload.get("river_name"))
    location_text = " ".join(part for part in (river_name, station_name) if part)
    summary = f"Observed water level: {water_level_m:.2f} m"
    tags = ["official", "wra", "water_level"]
    if warning_level_m is not None:
        gap = warning_level_m - water_level_m
        summary = f"{summary}; {gap:.2f} m below warning level"
        if gap <= 0:
            tags.append("warning_threshold_reached")

    return NormalizedEvidence(
        evidence_id=stable_evidence_id(metadata.key, raw_item.source_id),
        adapter_key=metadata.key,
        source_family=metadata.family,
        event_type=EventType.WATER_LEVEL,
        source_id=raw_item.source_id,
        source_url=raw_item.source_url,
        source_title=f"WRA water level observation: {station_name}",
        source_timestamp=observed_at,
        fetched_at=raw_item.fetched_at,
        summary=summary,
        location_text=location_text or station_name,
        confidence=float(payload.get("confidence", 0.9)),
        status=IngestionStatus.NORMALIZED,
        attribution=optional_str(payload.get("attribution")) or WRA_WATER_LEVEL_ATTRIBUTION,
        tags=tuple(tags),
    )


def _source_id(record: Mapping[str, Any]) -> str:
    station_id = str(record["station_id"])
    observed_at = str(record["observed_at"])
    return f"{station_id}:{observed_at}"


def _water_level_items(payload: object) -> Iterable[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, Mapping):
        raise WraWaterLevelPayloadError(
            "WRA water level payload is missing a water level record list"
        )

    for key in ("responseData", "data", "Data"):
        items = payload.get(key)
        if isinstance(items, list):
            return items

    records = payload.get("records")
    if isinstance(records, list):
        return records
    if isinstance(records, Mapping):
        for key in ("WaterLevel", "waterLevel", "Station", "records"):
            items = records.get(key)
            if isinstance(items, list):
                return items

    raise WraWaterLevelPayloadError(
        "WRA water level payload is missing a water level record list"
    )


def _parse_wra_station_record(
    item: Mapping[str, Any],
    *,
    source_url: str,
) -> Mapping[str, Any] | None:
    station_id = _first_text(
        item,
        "station_id",
        "StationId",
        "StationID",
        "StationNo",
        "ST_NO",
        "ObservatoryIdentifier",
        "stationid",
        "basinidentifier",
    )
    station_name = _first_text(
        item,
        "station_name",
        "StationName",
        "StationNameEng",
        "observatoryname",
    )
    observed_at = _parse_wra_observed_at(
        _first_value(
            item,
            "observed_at",
            "Time",
            "DateTime",
            "RecordTime",
            "ObserveTime",
            "datetime",
        )
    )
    water_level_m = _optional_float(
        _first_value(
            item,
            "water_level_m",
            "WaterLevel",
            "WaterLevelM",
            "Stage",
            "waterlevel",
        )
    )
    if station_id is None or observed_at is None or water_level_m is None:
        return None
    if water_level_m <= -90:
        return None
    station_name = station_name or station_id

    record: dict[str, Any] = {
        "station_id": station_id,
        "station_name": station_name,
        "observed_at": observed_at.isoformat(),
        "water_level_m": water_level_m,
        "source_url": source_url,
        "attribution": WRA_WATER_LEVEL_ATTRIBUTION,
        "confidence": 0.92,
    }

    river_name = _first_text(item, "river_name", "RiverName", "rivername")
    warning_level_m = _optional_float(
        _first_value(
            item,
            "warning_level_m",
            "WarningLevel",
            "WarningStage",
            "alertlevel2",
            "AlertLevel2",
            "alertlevel1",
            "AlertLevel1",
        )
    )
    if river_name is not None:
        record["river_name"] = river_name
    if warning_level_m is not None:
        record["warning_level_m"] = warning_level_m

    lat = _optional_float(_first_value(item, "latitude", "Latitude", "Lat"))
    lng = _optional_float(_first_value(item, "longitude", "Longitude", "Lon", "Lng"))
    if lat is not None and lng is not None:
        record["latitude"] = lat
        record["longitude"] = lng
        record["geometry"] = {"type": "Point", "coordinates": [lng, lat]}

    return record


def _fetch_json(url: str, timeout_seconds: int) -> Any:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": WRA_WATER_LEVEL_USER_AGENT,
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload: Any = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise WraWaterLevelFetchError(f"WRA water level API returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WraWaterLevelFetchError(f"WRA water level API request failed: {exc}") from exc

    if not isinstance(payload, (Mapping, list)):
        raise WraWaterLevelPayloadError(
            "WRA water level API returned a non-object/list JSON payload"
        )
    return payload


def _wra_water_level_request_url(api_url: str, api_token: str | None) -> str:
    params = {"format": "JSON"}
    token = optional_str(api_token)
    if token is not None:
        params["api_key"] = token
    return _url_with_query(api_url, params)


def _wra_water_level_source_url(api_url: str) -> str:
    return _url_with_query(api_url, {"format": "JSON"})


def _url_with_query(api_url: str, params: Mapping[str, str]) -> str:
    parts = urlsplit(api_url)
    replacement_keys = {key.lower() for key in params}
    existing_params = tuple(
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in replacement_keys and key.lower() != "api_key"
    )
    query = urlencode((*existing_params, *params.items()))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def _first_text(item: Mapping[str, Any], *keys: str) -> str | None:
    return optional_str(_first_value(item, *keys))


def _first_value(item: Mapping[str, Any], *keys: str) -> object:
    for key in keys:
        value = item.get(key)
        if value is not None:
            return value
    return None


def _parse_wra_observed_at(value: object) -> datetime | None:
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
