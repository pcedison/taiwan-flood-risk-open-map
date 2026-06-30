from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from app.adapters._helpers import optional_float, optional_str, parse_datetime
from app.adapters._helpers import stable_evidence_id, url_with_query
from app.adapters._taiwan_gov_tls import taiwan_gov_open_data_ssl_context
from app.adapters.contracts import (
    AdapterMetadata,
    AdapterRunResult,
    EventType,
    IngestionStatus,
    NormalizedEvidence,
    RawSourceItem,
    SourceFamily,
)


FetchText = Callable[[str, int], str]

KINMEN_LOCAL_TZ = timezone(timedelta(hours=8))
DEFAULT_KINMEN_KWIS_TIMEOUT_SECONDS = 8
KINMEN_KWIS_STALE_AFTER_MINUTES = 180
KINMEN_KWIS_MAX_FUTURE_SKEW_MINUTES = 15
KINMEN_KWIS_DATA_URL = "https://kwis.kinmen.gov.tw/"
KINMEN_KWIS_SERVICE_ROOT = "https://kwis.kinmen.gov.tw/KWIS_IOT_Data/KWIS_IOT_Data_Service.asmx"
KINMEN_KWIS_PUMP_STATION_API_URL = f"{KINMEN_KWIS_SERVICE_ROOT}/KWIS_Get_Pump_Basic_Unit_Data"
KINMEN_KWIS_ATTRIBUTION = "Kinmen County Government KWIS"
KINMEN_KWIS_USER_AGENT = "FloodRiskTaiwan/0.1 worker-local-kinmen-kwis"

KINMEN_KWIS_PUMP_STATION_METADATA = AdapterMetadata(
    key="local.kinmen.kwis_pump_station",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=False,
    display_name="Kinmen KWIS pump-station status adapter",
    data_gov_url=KINMEN_KWIS_DATA_URL,
    resource_url=KINMEN_KWIS_PUMP_STATION_API_URL,
    update_frequency="KWIS token-gated read API; cadence requires county authorization",
    license="Official KWIS endpoint; production license requires county authorization",
    limitations=(
        "KWIS read methods are token-gated. The adapter is disabled unless a formal "
        "KINMEN_KWIS_API_TOKEN is configured.",
        "The public ASMX/WSDL exposes the result as a string and does not publish a "
        "field-level response schema; this adapter only normalizes rows with station "
        "id, station name, observed time, pump status, and coordinates.",
        "Blank-token live smoke returns ErrMsg (7) invalid Token with Data: [].",
    ),
)


class KinmenKwisAdapterError(RuntimeError):
    """Base error for Kinmen KWIS adapters."""


class KinmenKwisAuthorizationError(KinmenKwisAdapterError):
    """Raised when KWIS read access is missing or rejected."""


class KinmenKwisFetchError(KinmenKwisAdapterError):
    """Raised when fetching KWIS payloads fails."""


class KinmenKwisPayloadError(KinmenKwisAdapterError):
    """Raised when a KWIS payload cannot be parsed."""


class KinmenKwisPumpStationApiAdapter:
    metadata = KINMEN_KWIS_PUMP_STATION_METADATA

    def __init__(
        self,
        *,
        api_token: str | None,
        api_url: str | None = None,
        timeout_seconds: int = DEFAULT_KINMEN_KWIS_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_text: FetchText | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._api_token = optional_str(api_token)
        self._api_url = (api_url or KINMEN_KWIS_PUMP_STATION_API_URL).strip()
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_text = fetch_kinmen_kwis_text if fetch_text is None else fetch_text
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        if self._api_token is None:
            raise KinmenKwisAuthorizationError(
                "KINMEN_KWIS_API_TOKEN is required for Kinmen KWIS read API access"
            )
        request_url = url_with_query(self._api_url, {"Token": self._api_token})
        try:
            text = self._fetch_text(request_url, self._timeout_seconds)
        except KinmenKwisAdapterError:
            raise
        except Exception as exc:
            raise KinmenKwisFetchError(
                f"{self.metadata.display_name} fetcher failed: {exc}"
            ) from exc

        fetched_at = self._fetched_at or datetime.now(UTC)
        records = parse_kinmen_kwis_pump_payload(
            text,
            source_url=KINMEN_KWIS_DATA_URL,
            resource_url=self._api_url,
            fetched_at=fetched_at,
        )
        return _raw_items(records, fetched_at=fetched_at, raw_snapshot_key=self._raw_snapshot_key)

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize_pump_station_record(self.metadata, raw_item)

    def run(self) -> AdapterRunResult:
        return _run(self)


def fetch_kinmen_kwis_text(url: str, timeout_seconds: int) -> str:
    request = Request(
        url,
        headers={
            "Accept": "text/xml,application/xml,text/plain,*/*",
            "User-Agent": KINMEN_KWIS_USER_AGENT,
        },
    )
    try:
        with urlopen(
            request,
            timeout=timeout_seconds,
            context=taiwan_gov_open_data_ssl_context(),
        ) as response:
            return response.read().decode("utf-8-sig")
    except (HTTPError, URLError, TimeoutError, UnicodeDecodeError) as exc:
        raise KinmenKwisFetchError(
            f"Failed to fetch Kinmen KWIS API {_redact_token_url(url)}: {exc}"
        ) from exc


def parse_kinmen_kwis_pump_payload(
    payload: object,
    *,
    source_url: str,
    resource_url: str | None = None,
    fetched_at: datetime | None = None,
) -> tuple[Mapping[str, Any], ...]:
    envelope = _kwis_envelope(payload)
    err_msg = optional_str(_first_value(envelope, "ErrMsg", "err_msg", "message"))
    if err_msg is not None:
        if "Token" in err_msg or "token" in err_msg:
            raise KinmenKwisAuthorizationError(err_msg)
        raise KinmenKwisPayloadError(err_msg)

    records: list[Mapping[str, Any]] = []
    for item in _data_items(envelope):
        if not isinstance(item, Mapping):
            continue
        record = _parse_pump_station_record(
            item,
            source_url=source_url,
            resource_url=resource_url,
            fetched_at=fetched_at,
        )
        if record is not None:
            records.append(record)
    return tuple(records)


def _parse_pump_station_record(
    item: Mapping[str, Any],
    *,
    source_url: str,
    resource_url: str | None,
    fetched_at: datetime | None,
) -> Mapping[str, Any] | None:
    station_id = _first_text(
        item,
        "station_id",
        "StationID",
        "stationId",
        "PumpID",
        "Pump_ID",
        "PumpNo",
        "Pump_NO",
        "PumpingStationID",
        "Monitoring_station_serial_number",
        "ID",
    )
    station_name = _first_text(
        item,
        "station_name",
        "StationName",
        "stationName",
        "PumpName",
        "Pump_Name",
        "PumpingStationName",
        "Name",
    )
    observed_at = _parse_observed_at(
        _first_value(
            item,
            "observed_at",
            "ObservedAt",
            "UpdateTime",
            "update_time",
            "DataTime",
            "datatime",
            "DateTime",
            "LastUpdateTime",
            "Time",
        )
    )
    pump_status = _first_text(
        item,
        "pump_status",
        "PumpStatus",
        "Pump_Status",
        "Status",
        "status",
        "PumpState",
        "State",
    )
    coordinate = _coordinate(
        _first_value(item, "longitude", "Longitude", "Lon", "LON", "X", "x"),
        _first_value(item, "latitude", "Latitude", "Lat", "LAT", "Y", "y"),
    )
    if (
        station_id is None
        or station_name is None
        or observed_at is None
        or pump_status is None
        or coordinate is None
    ):
        return None

    longitude, latitude = coordinate
    record: dict[str, Any] = {
        "station_id": station_id,
        "station_name": station_name,
        "observed_at": observed_at.isoformat(),
        "pump_status": pump_status,
        "source_url": source_url,
        "resource_url": resource_url,
        "location_text": _location_text(station_name),
        "authority": "Kinmen County Government / KWIS",
        "longitude": longitude,
        "latitude": latitude,
        "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
        "attribution": KINMEN_KWIS_ATTRIBUTION,
        "confidence": 0.78,
        "quality_flags": _quality_flags(observed_at, fetched_at=fetched_at),
    }
    _assign_text(record, "town", _first_text(item, "town", "Town", "Township"))
    _assign_text(record, "address", _first_text(item, "address", "Address", "Addr"))
    _assign_float(record, "water_level_m", _first_value(item, "water_level_m", "WaterLevel"))
    return record


def _normalize_pump_station_record(
    metadata: AdapterMetadata,
    raw_item: RawSourceItem,
) -> NormalizedEvidence | None:
    payload = raw_item.payload
    station_name = optional_str(payload.get("station_name"))
    observed_at = parse_datetime(payload.get("observed_at"))
    pump_status = optional_str(payload.get("pump_status"))
    if station_name is None or observed_at is None or pump_status is None:
        return None
    if _has_blocking_quality_flag(payload):
        return None

    summary = f"{metadata.display_name} status {pump_status}: {station_name}"
    tags = [
        "official",
        "local_kinmen",
        "kwis",
        "pump_station",
        "pump_or_gate_status",
        "status_only",
    ]
    return NormalizedEvidence(
        evidence_id=stable_evidence_id(metadata.key, raw_item.source_id),
        adapter_key=metadata.key,
        source_family=metadata.family,
        event_type=EventType.STATUS_ONLY,
        source_id=raw_item.source_id,
        source_url=raw_item.source_url,
        source_title=f"{metadata.display_name}: {station_name}",
        source_timestamp=observed_at,
        fetched_at=raw_item.fetched_at,
        summary=summary,
        location_text=optional_str(payload.get("location_text")) or station_name,
        confidence=float(payload.get("confidence", 0.78)),
        status=IngestionStatus.NORMALIZED,
        attribution=optional_str(payload.get("attribution")) or KINMEN_KWIS_ATTRIBUTION,
        tags=tuple(dict.fromkeys(tags)),
    )


def _run(adapter: Any) -> AdapterRunResult:
    fetched = tuple(adapter.fetch())
    normalized: list[NormalizedEvidence] = []
    rejected: list[str] = []
    for raw_item in fetched:
        evidence = adapter.normalize(raw_item)
        if evidence is None:
            rejected.append(raw_item.source_id)
        else:
            normalized.append(evidence)
    return AdapterRunResult(
        adapter_key=adapter.metadata.key,
        fetched=fetched,
        normalized=tuple(normalized),
        rejected=tuple(rejected),
    )


def _raw_items(
    records: Iterable[Mapping[str, Any]],
    *,
    fetched_at: datetime,
    raw_snapshot_key: str | None,
) -> tuple[RawSourceItem, ...]:
    return tuple(
        RawSourceItem(
            source_id=f"{record['station_id']}:{record['observed_at']}",
            source_url=str(record["source_url"]),
            fetched_at=fetched_at,
            payload=record,
            raw_snapshot_key=raw_snapshot_key,
        )
        for record in records
    )


def _kwis_envelope(payload: object) -> Mapping[str, Any]:
    if isinstance(payload, Mapping):
        return payload
    text = optional_str(payload)
    if text is None:
        raise KinmenKwisPayloadError("Kinmen KWIS payload is empty")
    result_text = _xml_string_text(text) if text.lstrip().startswith("<") else text
    try:
        parsed = json.loads(result_text)
    except json.JSONDecodeError as exc:
        raise KinmenKwisPayloadError("Kinmen KWIS result string is not JSON") from exc
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except json.JSONDecodeError:
            raise KinmenKwisPayloadError("Kinmen KWIS nested result string is not JSON")
    if not isinstance(parsed, Mapping):
        raise KinmenKwisPayloadError("Kinmen KWIS result JSON is not an object")
    return parsed


def _xml_string_text(text: str) -> str:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise KinmenKwisPayloadError("Kinmen KWIS XML response cannot be parsed") from exc
    result = optional_str(root.text)
    if result is None:
        raise KinmenKwisPayloadError("Kinmen KWIS XML string response is empty")
    return result


def _data_items(envelope: Mapping[str, Any]) -> tuple[Any, ...]:
    data = _first_value(envelope, "Data", "data", "records", "items")
    if isinstance(data, list):
        return tuple(data)
    return ()


def _parse_observed_at(value: object) -> datetime | None:
    text = optional_str(value)
    if text is None:
        return None
    parsed = parse_datetime(text)
    if parsed is None:
        for fmt in ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y%m%d%H%M%S", "%Y%m%d%H%M"):
            try:
                parsed = datetime.strptime(text, fmt)
            except ValueError:
                continue
            break
    if parsed is None:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=KINMEN_LOCAL_TZ)
    return parsed.astimezone(UTC)


def _quality_flags(
    observed_at: datetime,
    *,
    fetched_at: datetime | None,
) -> dict[str, bool]:
    if fetched_at is None:
        return {"future_observation": False, "stale_observation": False}
    return {
        "future_observation": observed_at
        > fetched_at + timedelta(minutes=KINMEN_KWIS_MAX_FUTURE_SKEW_MINUTES),
        "stale_observation": observed_at
        < fetched_at - timedelta(minutes=KINMEN_KWIS_STALE_AFTER_MINUTES),
    }


def _has_blocking_quality_flag(payload: Mapping[str, Any]) -> bool:
    quality_flags = payload.get("quality_flags")
    if not isinstance(quality_flags, Mapping):
        return False
    return (
        quality_flags.get("future_observation") is True
        or quality_flags.get("stale_observation") is True
    )


def _coordinate(lon: object, lat: object) -> tuple[float, float] | None:
    longitude = optional_float(lon)
    latitude = optional_float(lat)
    if longitude is None or latitude is None:
        return None
    if not (118.0 <= longitude <= 123.5 and 21.0 <= latitude <= 26.5):
        return None
    return longitude, latitude


def _location_text(station_name: str) -> str:
    return f"Kinmen County {station_name}"


def _first_value(row: Mapping[str, Any], *keys: str) -> Any:
    lowered = {str(key).lower(): value for key, value in row.items()}
    for key in keys:
        if key in row:
            return row[key]
        lowered_value = lowered.get(key.lower())
        if lowered_value is not None:
            return lowered_value
    return None


def _first_text(row: Mapping[str, Any], *keys: str) -> str | None:
    return optional_str(_first_value(row, *keys))


def _assign_text(record: dict[str, Any], key: str, value: str | None) -> None:
    if value is not None:
        record[key] = value


def _assign_float(record: dict[str, Any], key: str, value: object) -> None:
    parsed = optional_float(value)
    if parsed is not None:
        record[key] = parsed


def _redact_token_url(url: str) -> str:
    parts = urlsplit(url)
    query = urlencode(
        tuple(
            (key, "***" if key.lower() == "token" else value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
        )
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))
