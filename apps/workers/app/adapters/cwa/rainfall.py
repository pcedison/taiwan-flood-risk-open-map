from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Any
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


FetchJson = Callable[[str, int], Mapping[str, Any]]

CWA_RAINFALL_API_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/O-A0002-001"
CWA_RAINFALL_ATTRIBUTION = "Central Weather Administration"
CWA_RAINFALL_USER_AGENT = "FloodRiskTaiwan/0.1 worker-cwa-rainfall"
DEFAULT_CWA_RAINFALL_TIMEOUT_SECONDS = 8

CWA_RAINFALL_METADATA = AdapterMetadata(
    key="official.cwa.rainfall",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=True,
    display_name="CWA rainfall observation adapter",
)


class CwaRainfallAdapterError(RuntimeError):
    """Base error for CWA rainfall adapter failures."""


class CwaRainfallConfigurationError(CwaRainfallAdapterError):
    """Raised when the live CWA client is enabled without required config."""


class CwaRainfallFetchError(CwaRainfallAdapterError):
    """Raised when fetching CWA rainfall API payloads fails."""


class CwaRainfallPayloadError(CwaRainfallAdapterError):
    """Raised when the CWA rainfall API payload shape is not parseable."""


class CwaRainfallApiAdapter:
    metadata = CWA_RAINFALL_METADATA

    def __init__(
        self,
        *,
        authorization: str | None,
        api_url: str | None = None,
        timeout_seconds: int = DEFAULT_CWA_RAINFALL_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_json: FetchJson | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._authorization = authorization
        self._api_url = (api_url or CWA_RAINFALL_API_URL).strip()
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_json = fetch_json or _fetch_json
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        authorization = optional_str(self._authorization)
        if authorization is None:
            raise CwaRainfallConfigurationError(
                "CWA_API_AUTHORIZATION is required when SOURCE_CWA_API_ENABLED=true"
            )

        request_url = _cwa_rainfall_request_url(self._api_url, authorization)
        source_url = _cwa_rainfall_source_url(self._api_url)
        try:
            payload = self._fetch_json(request_url, self._timeout_seconds)
        except CwaRainfallAdapterError:
            raise
        except Exception as exc:
            raise CwaRainfallFetchError(f"CWA rainfall fetcher failed: {exc}") from exc

        records = parse_cwa_rainfall_api_payload(payload, source_url=source_url)
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
        return _normalize_rainfall_record(self.metadata, raw_item)

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


class CwaRainfallAdapter:
    metadata = CWA_RAINFALL_METADATA

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
        return _normalize_rainfall_record(self.metadata, raw_item)

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


def parse_cwa_rainfall_api_payload(
    payload: Mapping[str, Any],
    *,
    source_url: str,
) -> tuple[Mapping[str, Any], ...]:
    records = payload.get("records")
    if not isinstance(records, Mapping):
        raise CwaRainfallPayloadError("CWA rainfall payload is missing records object")

    stations = records.get("Station")
    if not isinstance(stations, list):
        raise CwaRainfallPayloadError("CWA rainfall payload is missing records.Station list")

    parsed: list[Mapping[str, Any]] = []
    for item in stations:
        if not isinstance(item, Mapping):
            continue
        record = _parse_cwa_station_record(item, source_url=source_url)
        if record is not None:
            parsed.append(record)
    return tuple(parsed)


def _normalize_rainfall_record(
    metadata: AdapterMetadata,
    raw_item: RawSourceItem,
) -> NormalizedEvidence | None:
    payload = raw_item.payload
    station_name = str(payload.get("station_name", "")).strip()
    observed_at = parse_datetime(payload.get("observed_at"))
    rainfall_1h = _optional_float(payload.get("rainfall_mm_1h"))
    rainfall_24h = _optional_float(payload.get("rainfall_mm_24h"))

    if not station_name or observed_at is None or rainfall_1h is None:
        return None

    county = optional_str(payload.get("county"))
    town = optional_str(payload.get("town"))
    location_text = " ".join(part for part in (county, town, station_name) if part)
    summary = f"Observed rainfall: {rainfall_1h:.1f} mm in 1 hour"
    if rainfall_24h is not None:
        summary = f"{summary}; {rainfall_24h:.1f} mm in 24 hours"

    return NormalizedEvidence(
        evidence_id=stable_evidence_id(metadata.key, raw_item.source_id),
        adapter_key=metadata.key,
        source_family=metadata.family,
        event_type=EventType.RAINFALL,
        source_id=raw_item.source_id,
        source_url=raw_item.source_url,
        source_title=f"CWA rainfall observation: {station_name}",
        source_timestamp=observed_at,
        fetched_at=raw_item.fetched_at,
        summary=summary,
        location_text=location_text or station_name,
        confidence=float(payload.get("confidence", 0.9)),
        status=IngestionStatus.NORMALIZED,
        attribution=optional_str(payload.get("attribution")) or CWA_RAINFALL_ATTRIBUTION,
        tags=("official", "cwa", "rainfall"),
    )


def _source_id(record: Mapping[str, Any]) -> str:
    station_id = str(record["station_id"])
    observed_at = str(record["observed_at"])
    return f"{station_id}:{observed_at}"


def _parse_cwa_station_record(
    item: Mapping[str, Any],
    *,
    source_url: str,
) -> Mapping[str, Any] | None:
    geo_info = item.get("GeoInfo")
    rainfall = item.get("RainfallElement")
    obs_time = item.get("ObsTime")
    if (
        not isinstance(geo_info, Mapping)
        or not isinstance(rainfall, Mapping)
        or not isinstance(obs_time, Mapping)
    ):
        return None

    station_id = optional_str(item.get("StationId"))
    station_name = optional_str(item.get("StationName"))
    observed_at = _parse_cwa_observed_at(obs_time.get("DateTime"))
    rainfall_1h = _precipitation_value(rainfall.get("Past1hr"))
    if station_id is None or station_name is None or observed_at is None or rainfall_1h is None:
        return None

    record: dict[str, Any] = {
        "station_id": station_id,
        "station_name": station_name,
        "observed_at": observed_at.isoformat(),
        "rainfall_mm_1h": rainfall_1h,
        "source_url": source_url,
        "attribution": CWA_RAINFALL_ATTRIBUTION,
        "confidence": 0.93,
    }

    rainfall_10m = _precipitation_value(rainfall.get("Past10Min"))
    rainfall_24h = _precipitation_value(rainfall.get("Past24hr"))
    if rainfall_10m is not None:
        record["rainfall_mm_10m"] = rainfall_10m
    if rainfall_24h is not None:
        record["rainfall_mm_24h"] = rainfall_24h

    county = optional_str(geo_info.get("CountyName"))
    town = optional_str(geo_info.get("TownName"))
    if county is not None:
        record["county"] = county
    if town is not None:
        record["town"] = town

    coordinate = _wgs84_coordinate(geo_info.get("Coordinates"))
    if coordinate is not None:
        lat, lng = coordinate
        record["latitude"] = lat
        record["longitude"] = lng
        record["geometry"] = {"type": "Point", "coordinates": [lng, lat]}

    return record


def _fetch_json(url: str, timeout_seconds: int) -> Mapping[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": CWA_RAINFALL_USER_AGENT,
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload: Any = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise CwaRainfallFetchError(f"CWA rainfall API returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CwaRainfallFetchError(f"CWA rainfall API request failed: {exc}") from exc

    if not isinstance(payload, Mapping):
        raise CwaRainfallPayloadError("CWA rainfall API returned a non-object JSON payload")
    return payload


def _cwa_rainfall_request_url(api_url: str, authorization: str) -> str:
    return _url_with_query(
        api_url,
        {
            "Authorization": authorization,
            "format": "JSON",
        },
    )


def _cwa_rainfall_source_url(api_url: str) -> str:
    return _url_with_query(api_url, {"format": "JSON"})


def _url_with_query(api_url: str, params: Mapping[str, str]) -> str:
    parts = urlsplit(api_url)
    replacement_keys = {key.lower() for key in params}
    existing_params = tuple(
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in replacement_keys and key.lower() != "authorization"
    )
    query = urlencode((*existing_params, *params.items()))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def _parse_cwa_observed_at(value: object) -> datetime | None:
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _wgs84_coordinate(coordinates: object) -> tuple[float, float] | None:
    if not isinstance(coordinates, list):
        return None

    fallback: tuple[float, float] | None = None
    for coordinate in coordinates:
        if not isinstance(coordinate, Mapping):
            continue
        lat = _optional_float(coordinate.get("StationLatitude"))
        lng = _optional_float(coordinate.get("StationLongitude"))
        if lat is None or lng is None:
            continue
        value = (lat, lng)
        if coordinate.get("CoordinateName") == "WGS84":
            return value
        fallback = value
    return fallback


def _precipitation_value(value: object) -> float | None:
    if isinstance(value, Mapping):
        value = value.get("Precipitation")
    precipitation = _optional_float(value)
    if precipitation is None or precipitation < 0:
        return None
    return precipitation


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
