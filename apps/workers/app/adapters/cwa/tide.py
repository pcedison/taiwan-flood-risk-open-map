from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.adapters._helpers import (
    optional_float,
    optional_str,
    parse_datetime,
    parse_observed_at_utc,
    stable_evidence_id,
    url_with_query,
)
from app.adapters.contracts import (
    AdapterMetadata,
    AdapterRunResult,
    EventType,
    IngestionStatus,
    NormalizedEvidence,
    RawSourceItem,
    SourceFamily,
)


FetchJson = Callable[[str, int], Mapping[str, Any]]

CWA_TIDE_LEVEL_API_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/O-B0075-001"
CWA_TIDE_LEVEL_STATION_API_URL = (
    "https://opendata.cwa.gov.tw/fileapi/v1/opendataapi/O-B0076-001"
)
CWA_TIDE_LEVEL_DATASET_ID = "O-B0075-001"
CWA_TIDE_LEVEL_STATION_DATASET_ID = "O-B0076-001"
CWA_TIDE_LEVEL_DATASET_URL = "https://opendata.cwa.gov.tw/dataset/observation/O-B0075-001"
CWA_TIDE_LEVEL_STATION_DATASET_URL = (
    "https://opendata.cwa.gov.tw/dataset/forecast/O-B0076-001"
)
CWA_TIDE_LEVEL_ATTRIBUTION = "Central Weather Administration"
CWA_TIDE_LEVEL_USER_AGENT = "FloodRiskTaiwan/0.1 worker-cwa-tide-level"
DEFAULT_CWA_TIDE_LEVEL_TIMEOUT_SECONDS = 8

CWA_TIDE_LEVEL_METADATA = AdapterMetadata(
    key="official.cwa.tide_level",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=True,
    display_name="CWA tide-level observation adapter",
    data_gov_dataset_id=CWA_TIDE_LEVEL_DATASET_ID,
    data_gov_url=CWA_TIDE_LEVEL_DATASET_URL,
    resource_url=CWA_TIDE_LEVEL_API_URL,
    update_frequency="hourly observations; station metadata daily",
    license="Government Open Data License, version 1.0",
    limitations=(
        "coastal tide level is a marine hydrologic context signal, not an inland river, sewer, or pump-station water level.",
        "Offshore tide stations such as Matsu use local mean sea level and are not tied back to Taiwan island TWVD2001.",
        "Rows without joined station metadata, WGS84 coordinates, observed time, or numeric tide height are rejected.",
    ),
)


class CwaTideLevelAdapterError(RuntimeError):
    """Base error for CWA tide-level adapter failures."""


class CwaTideLevelConfigurationError(CwaTideLevelAdapterError):
    """Raised when the live CWA tide client is enabled without required config."""


class CwaTideLevelFetchError(CwaTideLevelAdapterError):
    """Raised when fetching CWA tide-level API payloads fails."""


class CwaTideLevelPayloadError(CwaTideLevelAdapterError):
    """Raised when the CWA tide-level API payload shape is not parseable."""


class CwaTideLevelApiAdapter:
    metadata = CWA_TIDE_LEVEL_METADATA

    def __init__(
        self,
        *,
        authorization: str | None,
        api_url: str | None = None,
        station_api_url: str | None = None,
        timeout_seconds: int = DEFAULT_CWA_TIDE_LEVEL_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_json: FetchJson | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._authorization = authorization
        self._api_url = (api_url or CWA_TIDE_LEVEL_API_URL).strip()
        self._station_api_url = (station_api_url or CWA_TIDE_LEVEL_STATION_API_URL).strip()
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_json = fetch_json or _fetch_json
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        authorization = optional_str(self._authorization)
        if authorization is None:
            raise CwaTideLevelConfigurationError(
                "CWA_API_AUTHORIZATION is required when official.cwa.tide_level is enabled"
            )

        tide_request_url = _cwa_tide_level_request_url(self._api_url, authorization)
        tide_resource_url = _cwa_tide_level_source_url(self._api_url)
        station_request_url = _cwa_tide_station_request_url(
            self._station_api_url,
            authorization,
        )
        station_resource_url = _cwa_tide_station_source_url(self._station_api_url)
        try:
            tide_payload = self._fetch_json(tide_request_url, self._timeout_seconds)
            station_payload = self._fetch_json(station_request_url, self._timeout_seconds)
        except CwaTideLevelAdapterError:
            raise
        except Exception as exc:
            raise CwaTideLevelFetchError(f"CWA tide-level fetcher failed: {exc}") from exc

        station_metadata = parse_cwa_tide_station_metadata_payload(
            station_payload,
            station_metadata_url=station_resource_url,
        )
        records = parse_cwa_tide_level_api_payload(
            tide_payload,
            source_url=CWA_TIDE_LEVEL_DATASET_URL,
            resource_url=tide_resource_url,
            station_metadata=station_metadata,
            station_metadata_url=station_resource_url,
        )
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
        return _normalize_tide_level_record(self.metadata, raw_item)

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


class CwaTideLevelAdapter:
    metadata = CWA_TIDE_LEVEL_METADATA

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
        return _normalize_tide_level_record(self.metadata, raw_item)

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


def parse_cwa_tide_level_api_payload(
    payload: Mapping[str, Any],
    *,
    source_url: str,
    station_metadata: Mapping[str, Mapping[str, Any]],
    resource_url: str | None = None,
    station_metadata_url: str | None = None,
) -> tuple[Mapping[str, Any], ...]:
    locations = _tide_locations(payload)
    parsed: list[Mapping[str, Any]] = []
    for item in locations:
        if not isinstance(item, Mapping):
            continue
        record = _parse_tide_location(
            item,
            source_url=source_url,
            resource_url=resource_url,
            station_metadata=station_metadata,
            station_metadata_url=station_metadata_url,
        )
        if record is not None:
            parsed.append(record)
    return tuple(parsed)


def parse_cwa_tide_station_metadata_payload(
    payload: Mapping[str, Any],
    *,
    station_metadata_url: str | None = None,
) -> Mapping[str, Mapping[str, Any]]:
    locations = _station_locations(payload)
    station_by_id: dict[str, Mapping[str, Any]] = {}
    for item in locations:
        if not isinstance(item, Mapping):
            continue
        station = item.get("Station")
        if not isinstance(station, Mapping):
            continue
        parsed = _parse_station_metadata(station, station_metadata_url=station_metadata_url)
        if parsed is not None:
            station_by_id[str(parsed["station_id"])] = parsed
    return station_by_id


def _normalize_tide_level_record(
    metadata: AdapterMetadata,
    raw_item: RawSourceItem,
) -> NormalizedEvidence | None:
    payload = raw_item.payload
    station_name = optional_str(payload.get("station_name"))
    observed_at = parse_datetime(payload.get("observed_at"))
    water_level_m = optional_float(payload.get("water_level_m"))
    if station_name is None or observed_at is None or water_level_m is None:
        return None

    county = optional_str(payload.get("county"))
    town = optional_str(payload.get("town"))
    location_text = " ".join(part for part in (county, town, station_name) if part)
    summary = (
        f"CWA coastal tide level: {water_level_m:.2f} m at {station_name}; "
        "use as coastal hydrologic context, not inland drainage depth."
    )

    return NormalizedEvidence(
        evidence_id=stable_evidence_id(metadata.key, raw_item.source_id),
        adapter_key=metadata.key,
        source_family=metadata.family,
        event_type=EventType.WATER_LEVEL,
        source_id=raw_item.source_id,
        source_url=raw_item.source_url,
        source_title=f"CWA tide level observation: {station_name}",
        source_timestamp=observed_at,
        fetched_at=raw_item.fetched_at,
        summary=summary,
        location_text=location_text or station_name,
        confidence=float(payload.get("confidence", 0.9)),
        status=IngestionStatus.NORMALIZED,
        attribution=optional_str(payload.get("attribution")) or CWA_TIDE_LEVEL_ATTRIBUTION,
        tags=("official", "cwa", "marine", "tide_level", "water_level"),
    )


def _parse_tide_location(
    item: Mapping[str, Any],
    *,
    source_url: str,
    resource_url: str | None,
    station_metadata: Mapping[str, Mapping[str, Any]],
    station_metadata_url: str | None,
) -> Mapping[str, Any] | None:
    station = item.get("Station")
    obs_times = item.get("StationObsTimes")
    if not isinstance(station, Mapping) or not isinstance(obs_times, Mapping):
        return None

    station_id = optional_str(station.get("StationID"))
    times = obs_times.get("StationObsTime")
    if station_id is None or not isinstance(times, list) or not times:
        return None

    station_record = station_metadata.get(station_id)
    if station_record is None:
        return None

    latest = times[0]
    if not isinstance(latest, Mapping):
        return None
    elements = latest.get("WeatherElements")
    if not isinstance(elements, Mapping):
        return None

    observed_at = parse_observed_at_utc(latest.get("DateTime"))
    tide_height_m = optional_float(elements.get("TideHeight"))
    if observed_at is None or tide_height_m is None:
        return None

    record: dict[str, Any] = {
        **dict(station_record),
        "observed_at": observed_at.isoformat(),
        "water_level_m": tide_height_m,
        "source_url": source_url,
        "attribution": CWA_TIDE_LEVEL_ATTRIBUTION,
        "confidence": 0.9,
        "source_weight": 0.65,
        "station_type": "tide_level",
        "quality_flags": {
            "coastal_context_only": True,
            "datum_note": "offshore stations may use local mean sea level",
        },
    }
    tide_level = optional_str(elements.get("TideLevel"))
    if tide_level not in {None, "-", "None"}:
        record["tide_level_label"] = tide_level
    if resource_url is not None:
        record["resource_url"] = resource_url
    if station_metadata_url is not None:
        record["station_metadata_url"] = station_metadata_url
    return record


def _parse_station_metadata(
    station: Mapping[str, Any],
    *,
    station_metadata_url: str | None,
) -> Mapping[str, Any] | None:
    station_id = optional_str(station.get("StationID"))
    station_name = optional_str(station.get("StationName"))
    lat = optional_float(station.get("StationLatitude"))
    lng = optional_float(station.get("StationLongitude"))
    if station_id is None or station_name is None or lat is None or lng is None:
        return None

    county = _nested_text(station.get("County"), "CountyName")
    town = _nested_text(station.get("Town"), "TownName")
    area = _nested_text(station.get("Area"), "AreaName")
    record: dict[str, Any] = {
        "station_id": station_id,
        "station_name": station_name,
        "latitude": lat,
        "longitude": lng,
        "geometry": {"type": "Point", "coordinates": [lng, lat]},
    }
    _assign_text(record, "station_name_en", station.get("StationNameEN"))
    _assign_text(record, "station_attribute", station.get("StationAttribute"))
    _assign_text(record, "station_address", station.get("StationAddress"))
    _assign_text(record, "authority", station.get("StationChargeIns"))
    _assign_text(record, "county", county)
    _assign_text(record, "town", town)
    _assign_text(record, "area", area)
    if station_metadata_url is not None:
        record["station_metadata_url"] = station_metadata_url
    return record


def _tide_locations(payload: Mapping[str, Any]) -> list[Any]:
    records = payload.get("Records") or payload.get("records")
    if not isinstance(records, Mapping):
        raise CwaTideLevelPayloadError("CWA tide-level payload is missing Records object")
    sea_surface = records.get("SeaSurfaceObs")
    if not isinstance(sea_surface, Mapping):
        raise CwaTideLevelPayloadError("CWA tide-level payload is missing SeaSurfaceObs object")
    locations = sea_surface.get("Location")
    if not isinstance(locations, list):
        raise CwaTideLevelPayloadError("CWA tide-level payload is missing Location list")
    return locations


def _station_locations(payload: Mapping[str, Any]) -> list[Any]:
    cwa_open_data = payload.get("cwaopendata")
    if not isinstance(cwa_open_data, Mapping):
        raise CwaTideLevelPayloadError("CWA tide station metadata is missing cwaopendata")
    resource = (
        _mapping(cwa_open_data.get("Resources"))
        and _mapping(cwa_open_data["Resources"]).get("Resource")
    )
    if not isinstance(resource, Mapping):
        raise CwaTideLevelPayloadError("CWA tide station metadata is missing Resource")
    data = resource.get("Data")
    if not isinstance(data, Mapping):
        raise CwaTideLevelPayloadError("CWA tide station metadata is missing Data")
    sea_surface = data.get("SeaSurfaceObs")
    if not isinstance(sea_surface, Mapping):
        raise CwaTideLevelPayloadError("CWA tide station metadata is missing SeaSurfaceObs")
    locations = sea_surface.get("Location")
    if not isinstance(locations, list):
        raise CwaTideLevelPayloadError("CWA tide station metadata is missing Location list")
    return locations


def _source_id(record: Mapping[str, Any]) -> str:
    station_id = str(record["station_id"])
    observed_at = str(record["observed_at"])
    return f"{station_id}:{observed_at}"


def _fetch_json(url: str, timeout_seconds: int) -> Mapping[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": CWA_TIDE_LEVEL_USER_AGENT,
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload: Any = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise CwaTideLevelFetchError(f"CWA tide-level API returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CwaTideLevelFetchError(f"CWA tide-level API request failed: {exc}") from exc

    if not isinstance(payload, Mapping):
        raise CwaTideLevelPayloadError("CWA tide-level API returned a non-object JSON payload")
    return payload


def _cwa_tide_level_request_url(api_url: str, authorization: str) -> str:
    return url_with_query(
        api_url,
        {
            "Authorization": authorization,
            "format": "JSON",
        },
        drop_keys=("authorization",),
    )


def _cwa_tide_level_source_url(api_url: str) -> str:
    return url_with_query(api_url, {"format": "JSON"}, drop_keys=("authorization",))


def _cwa_tide_station_request_url(api_url: str, authorization: str) -> str:
    return url_with_query(
        api_url,
        {
            "Authorization": authorization,
            "downloadType": "WEB",
            "format": "JSON",
        },
        drop_keys=("authorization",),
    )


def _cwa_tide_station_source_url(api_url: str) -> str:
    return url_with_query(
        api_url,
        {
            "downloadType": "WEB",
            "format": "JSON",
        },
        drop_keys=("authorization",),
    )


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _nested_text(value: object, key: str) -> str | None:
    if not isinstance(value, Mapping):
        return None
    return optional_str(value.get(key))


def _assign_text(target: dict[str, Any], key: str, value: object) -> None:
    text = optional_str(value)
    if text is not None:
        target[key] = text
