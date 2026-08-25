from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

from app.adapters._helpers import optional_str, parse_datetime, stable_evidence_id
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

FetchJson = Callable[[str, int], object]
FetchText = Callable[[str, int], str]

WRA_HISTORICAL_FLOOD_INDEX_URL = (
    "https://opendata.wra.gov.tw/api/v2/"
    "72d7aee9-e29b-49a2-bd0b-54acc8e3b75c?format=JSON&sort=_importdate+asc"
)
WRA_HISTORICAL_FLOOD_DATA_GOV_DATASET_ID = "25770"
WRA_HISTORICAL_FLOOD_DATA_GOV_URL = "https://data.gov.tw/dataset/25770"
WRA_HISTORICAL_FLOOD_ATTRIBUTION = "Water Resources Agency historical flood KML"
WRA_HISTORICAL_FLOOD_USER_AGENT = "FloodRiskTaiwan/0.1 worker-wra-historical-flood"
DEFAULT_WRA_HISTORICAL_FLOOD_TIMEOUT_SECONDS = 8
WRA_LOCAL_TZ = timezone(timedelta(hours=8))

_TAIWAN_LONGITUDE_BOUNDS = (117.0, 123.5)
_TAIWAN_LATITUDE_BOUNDS = (20.0, 27.5)
_HISTORICAL_LIMITATIONS = (
    "Historical footprint only; it is not a realtime flood observation or warning.",
    "The source event time is taken only from a parseable KML event label or field.",
    "KML points and polygons describe source-provided historical locations and extents.",
    "The catalog landing page is retained as a historical dataset and may be withdrawn.",
)

WRA_HISTORICAL_FLOOD_METADATA = AdapterMetadata(
    key="official.wra.historical_flood",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=False,
    display_name="WRA historical flood KML adapter",
    data_gov_dataset_id=WRA_HISTORICAL_FLOOD_DATA_GOV_DATASET_ID,
    data_gov_url=WRA_HISTORICAL_FLOOD_DATA_GOV_URL,
    resource_url=WRA_HISTORICAL_FLOOD_INDEX_URL,
    update_frequency="irregular historical KML publication",
    license="Government Open Data License, version 1.0",
    limitations=_HISTORICAL_LIMITATIONS,
)


class WraHistoricalFloodAdapterError(RuntimeError):
    """Base error for the WRA historical-flood adapter."""


class WraHistoricalFloodFetchError(WraHistoricalFloodAdapterError):
    """Raised when the metadata index or resolved KML cannot be fetched."""


class WraHistoricalFloodPayloadError(WraHistoricalFloodAdapterError):
    """Raised when metadata or KML violates the reviewed source contract."""


class WraHistoricalFloodAdapter:
    metadata = WRA_HISTORICAL_FLOOD_METADATA

    def __init__(
        self,
        *,
        index_url: str | None = None,
        timeout_seconds: int = DEFAULT_WRA_HISTORICAL_FLOOD_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_json: FetchJson | None = None,
        fetch_text: FetchText | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._index_url = (index_url or WRA_HISTORICAL_FLOOD_INDEX_URL).strip()
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_json = fetch_json or fetch_wra_historical_json
        self._fetch_text = fetch_text or fetch_wra_historical_text
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        try:
            index_payload = self._fetch_json(self._index_url, self._timeout_seconds)
            metadata_record = _select_current_kml_record(index_payload)
            resolved_kml_url = _approved_kml_url(metadata_record.get("sourceurl"))
            kml_text = self._fetch_text(resolved_kml_url, self._timeout_seconds)
        except WraHistoricalFloodAdapterError:
            raise
        except Exception as exc:
            raise WraHistoricalFloodFetchError(
                f"WRA historical flood fetcher failed: {exc}"
            ) from exc

        dataset_revision = _dataset_revision(metadata_record)
        records = parse_wra_historical_flood_kml(kml_text)
        fetched_at = self._fetched_at or datetime.now(UTC)
        seen: set[str] = set()
        rows: list[RawSourceItem] = []
        for record in records:
            source_id = _historical_source_id(record)
            if source_id in seen:
                continue
            seen.add(source_id)
            payload: dict[str, Any] = {
                **record,
                "evidence_scope": "historical",
                "source_url": self._index_url,
                "resource_url": resolved_kml_url,
                "metadata_url": self._index_url,
                "resolved_kml_url": resolved_kml_url,
                "dataset_revision": dataset_revision,
                "limitations": list(_HISTORICAL_LIMITATIONS),
                "attribution": WRA_HISTORICAL_FLOOD_ATTRIBUTION,
            }
            rows.append(
                RawSourceItem(
                    source_id=source_id,
                    source_url=WRA_HISTORICAL_FLOOD_DATA_GOV_URL,
                    fetched_at=fetched_at,
                    payload=payload,
                    raw_snapshot_key=self._raw_snapshot_key,
                )
            )
        return tuple(rows)

    def normalize(self, raw: RawSourceItem) -> NormalizedEvidence | None:
        source_timestamp = parse_datetime(raw.payload.get("source_timestamp"))
        geometry = raw.payload.get("geometry")
        title = optional_str(raw.payload.get("placemark_name"))
        event_name = optional_str(raw.payload.get("event_name"))
        if (
            source_timestamp is None
            or source_timestamp.tzinfo is None
            or source_timestamp.utcoffset() is None
            or not isinstance(geometry, Mapping)
            or title is None
        ):
            return None

        geometry_type = geometry.get("type")
        if geometry_type not in {"Point", "Polygon", "MultiPolygon"}:
            return None
        location_precision = raw.payload.get("location_precision")
        if location_precision not in {"point", "polygon"}:
            return None

        description = f"WRA historical flood record: {title}"
        if event_name and event_name != title:
            description = f"{description} ({event_name})"
        return NormalizedEvidence(
            evidence_id=stable_evidence_id(self.metadata.key, raw.source_id),
            adapter_key=self.metadata.key,
            source_family=self.metadata.family,
            event_type=EventType.FLOOD_REPORT,
            source_id=raw.source_id,
            source_url=raw.source_url,
            source_title=f"WRA historical flood: {title}",
            source_timestamp=source_timestamp.astimezone(UTC),
            fetched_at=raw.fetched_at,
            summary=description,
            location_text=title,
            confidence=0.86 if location_precision == "polygon" else 0.82,
            status=IngestionStatus.NORMALIZED,
            attribution=WRA_HISTORICAL_FLOOD_ATTRIBUTION,
            tags=("official", "wra", "historical", "flood_report"),
        )

    def run(self) -> AdapterRunResult:
        fetched = self.fetch()
        normalized: list[NormalizedEvidence] = []
        rejected: list[str] = []
        for raw in fetched:
            evidence = self.normalize(raw)
            if evidence is None:
                rejected.append(raw.source_id)
            else:
                normalized.append(evidence)
        return AdapterRunResult(
            adapter_key=self.metadata.key,
            fetched=fetched,
            normalized=tuple(normalized),
            rejected=tuple(rejected),
        )


def fetch_wra_historical_json(url: str, timeout_seconds: int) -> object:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": WRA_HISTORICAL_FLOOD_USER_AGENT,
        },
    )
    try:
        with urlopen(
            request,
            timeout=timeout_seconds,
            context=taiwan_gov_open_data_ssl_context(),
        ) as response:
            return json.loads(response.read().decode("utf-8-sig"))
    except (
        HTTPError,
        URLError,
        TimeoutError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise WraHistoricalFloodFetchError(
            f"Failed to fetch WRA historical metadata {url}: {exc}"
        ) from exc


def fetch_wra_historical_text(url: str, timeout_seconds: int) -> str:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.google-earth.kml+xml,application/xml,text/xml",
            "User-Agent": WRA_HISTORICAL_FLOOD_USER_AGENT,
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
        raise WraHistoricalFloodFetchError(
            f"Failed to fetch WRA historical KML {url}: {exc}"
        ) from exc


def parse_wra_historical_flood_kml(text: str) -> tuple[Mapping[str, Any], ...]:
    normalized_text = _inject_missing_official_xsi_namespace(text)
    try:
        root = ET.fromstring(normalized_text.lstrip("\ufeff").strip())
    except (ET.ParseError, DefusedXmlException) as exc:
        raise WraHistoricalFloodPayloadError(
            f"WRA historical KML is not parseable: {exc}"
        ) from exc

    if not any(_local_name(element.tag) == "Placemark" for element in root.iter()):
        raise WraHistoricalFloodPayloadError(
            "WRA historical KML does not contain a Placemark"
        )

    records: list[Mapping[str, Any]] = []
    _walk_kml(root, inherited_event_name=None, inherited_timestamp=None, records=records)
    if not records:
        raise WraHistoricalFloodPayloadError(
            "WRA historical KML does not contain a valid Placemark geometry in Taiwan"
        )
    return tuple(records)


def _walk_kml(
    element: Element,
    *,
    inherited_event_name: str | None,
    inherited_timestamp: datetime | None,
    records: list[Mapping[str, Any]],
) -> None:
    tag = _local_name(element.tag)
    event_name = inherited_event_name
    timestamp = inherited_timestamp
    if tag in {"Document", "Folder"}:
        container_name = _direct_child_text(element, "name")
        container_timestamp = _event_timestamp(container_name)
        if container_timestamp is not None:
            event_name = container_name
            timestamp = container_timestamp

    if tag == "Placemark":
        record = _placemark_record(
            element,
            inherited_event_name=event_name,
            inherited_timestamp=timestamp,
        )
        if record is not None:
            records.append(record)
        return

    for child in element:
        _walk_kml(
            child,
            inherited_event_name=event_name,
            inherited_timestamp=timestamp,
            records=records,
        )


def _placemark_record(
    placemark: Element,
    *,
    inherited_event_name: str | None,
    inherited_timestamp: datetime | None,
) -> Mapping[str, Any] | None:
    geometry = _placemark_geometry(placemark)
    if geometry is None:
        return None
    placemark_name = _direct_child_text(placemark, "name") or "historical flood area"
    source_timestamp = _placemark_timestamp(placemark)
    if source_timestamp is None:
        source_timestamp = _event_timestamp(placemark_name) or inherited_timestamp
    record: dict[str, Any] = {
        "placemark_id": optional_str(placemark.attrib.get("id")) or "",
        "placemark_name": placemark_name,
        "event_name": inherited_event_name or placemark_name,
        "geometry": geometry,
        "location_precision": "point" if geometry["type"] == "Point" else "polygon",
    }
    if source_timestamp is not None:
        record["source_timestamp"] = source_timestamp.astimezone(UTC).isoformat()
    return record


def _placemark_timestamp(placemark: Element) -> datetime | None:
    for element in placemark.iter():
        if _local_name(element.tag) == "when":
            parsed = _event_timestamp(optional_str(element.text))
            if parsed is not None:
                return parsed

    timestamp_keys = {
        "date",
        "datetime",
        "eventdate",
        "eventdatetime",
        "eventtimestamp",
        "occurredat",
        "timestamp",
        "事件日期",
        "發生時間",
        "日期",
        "時間",
    }
    for element in placemark.iter():
        tag = _local_name(element.tag)
        if tag not in {"Data", "SimpleData"}:
            continue
        key = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", element.attrib.get("name", "").lower())
        if key not in timestamp_keys:
            continue
        value = optional_str(element.text)
        if tag == "Data":
            value = _direct_child_text(element, "value") or value
        parsed = _event_timestamp(value)
        if parsed is not None:
            return parsed
    return None


def _event_timestamp(value: str | None) -> datetime | None:
    text = optional_str(value)
    if text is None:
        return None

    iso_match = re.search(
        r"(?<!\d)((?:19|20)\d{2}-\d{1,2}-\d{1,2}"
        r"(?:[T\s]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?)",
        text,
    )
    if iso_match:
        candidate = iso_match.group(1).replace(" ", "T", 1).replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            parsed = None
        if parsed is not None:
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                parsed = parsed.replace(tzinfo=WRA_LOCAL_TZ)
            return parsed.astimezone(UTC)

    roc_match = re.search(
        r"(?<!\d)(\d{2,3})\s*(?:[-/.]|年)\s*(\d{1,2})\s*"
        r"(?:[-/.]|月)\s*(\d{1,2})(?:\s*日)?",
        text,
    )
    if roc_match:
        year = int(roc_match.group(1)) + 1911
        try:
            parsed = datetime(
                year,
                int(roc_match.group(2)),
                int(roc_match.group(3)),
                tzinfo=WRA_LOCAL_TZ,
            )
        except ValueError:
            return None
        return parsed.astimezone(UTC)
    return None


def _placemark_geometry(placemark: Element) -> dict[str, Any] | None:
    point_elements = [
        element for element in placemark.iter() if _local_name(element.tag) == "Point"
    ]
    polygon_elements = [
        element for element in placemark.iter() if _local_name(element.tag) == "Polygon"
    ]
    parsed_points = [_point_geometry(element) for element in point_elements]
    parsed_polygons = [_polygon_coordinates(element) for element in polygon_elements]
    if any(point is None for point in parsed_points) or any(
        polygon is None for polygon in parsed_polygons
    ):
        return None
    points = [point for point in parsed_points if point is not None]
    polygons = [polygon for polygon in parsed_polygons if polygon is not None]
    has_geometry_element = any(
        _local_name(element.tag) in {"Point", "Polygon", "MultiGeometry"}
        for element in placemark.iter()
    )
    if not has_geometry_element or (points and polygons) or len(points) > 1:
        return None
    if len(points) == 1:
        return {"type": "Point", "coordinates": points[0]}
    if len(polygons) == 1:
        return {"type": "Polygon", "coordinates": polygons[0]}
    if len(polygons) > 1:
        return {"type": "MultiPolygon", "coordinates": polygons}
    return None


def _point_geometry(point: Element) -> list[float] | None:
    coordinates = _first_descendant_text(point, "coordinates")
    parsed = _coordinate_sequence(coordinates)
    if parsed is None or len(parsed) != 1:
        return None
    return parsed[0]


def _polygon_coordinates(polygon: Element) -> list[list[list[float]]] | None:
    outer: list[list[float]] | None = None
    holes: list[list[list[float]]] = []
    for child in polygon:
        tag = _local_name(child.tag)
        if tag not in {"outerBoundaryIs", "innerBoundaryIs"}:
            continue
        coordinates = _first_descendant_text(child, "coordinates")
        ring = _coordinate_sequence(coordinates)
        if not _valid_linear_ring(ring):
            return None
        if tag == "outerBoundaryIs":
            if outer is not None:
                return None
            outer = ring
        else:
            assert ring is not None
            holes.append(ring)
    if outer is None:
        return None
    return [outer, *holes]


def _coordinate_sequence(value: str | None) -> list[list[float]] | None:
    text = optional_str(value)
    if text is None:
        return None
    coordinates: list[list[float]] = []
    for token in text.split():
        parts = token.split(",")
        if len(parts) < 2:
            return None
        try:
            longitude = float(parts[0])
            latitude = float(parts[1])
        except ValueError:
            return None
        if not _coordinate_in_taiwan(longitude, latitude):
            return None
        coordinates.append([longitude, latitude])
    return coordinates or None


def _coordinate_in_taiwan(longitude: float, latitude: float) -> bool:
    return (
        math.isfinite(longitude)
        and math.isfinite(latitude)
        and _TAIWAN_LONGITUDE_BOUNDS[0] <= longitude <= _TAIWAN_LONGITUDE_BOUNDS[1]
        and _TAIWAN_LATITUDE_BOUNDS[0] <= latitude <= _TAIWAN_LATITUDE_BOUNDS[1]
    )


def _valid_linear_ring(ring: list[list[float]] | None) -> bool:
    if ring is None or len(ring) < 4 or ring[0] != ring[-1]:
        return False
    return len({(coordinate[0], coordinate[1]) for coordinate in ring[:-1]}) >= 3


def _historical_source_id(record: Mapping[str, Any]) -> str:
    identity = {
        "event_name": record.get("event_name"),
        "geometry": record.get("geometry"),
        "placemark_id": record.get("placemark_id"),
        "placemark_name": record.get("placemark_name"),
        "source_timestamp": record.get("source_timestamp"),
    }
    canonical = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
    return f"wra-historical:{digest}"


def _select_current_kml_record(payload: object) -> Mapping[str, Any]:
    records = tuple(_index_records(payload))
    candidates = [record for record in records if _is_kml_record(record)]
    if not candidates:
        raise WraHistoricalFloodPayloadError(
            "WRA historical metadata does not contain a KML record"
        )
    return max(
        enumerate(candidates),
        key=lambda item: (_revision_sort_key(item[1]), item[0]),
    )[1]


def _index_records(payload: object) -> Iterable[Mapping[str, Any]]:
    if isinstance(payload, list):
        return tuple(item for item in payload if isinstance(item, Mapping))
    if not isinstance(payload, Mapping):
        return ()
    for key in ("responseData", "data", "records", "Data"):
        items = payload.get(key)
        if isinstance(items, list):
            return tuple(item for item in items if isinstance(item, Mapping))
    if "sourceurl" in payload:
        return (payload,)
    return ()


def _is_kml_record(record: Mapping[str, Any]) -> bool:
    extension = optional_str(
        record.get("fileex") or record.get("file_extension") or record.get("format")
    )
    sourceurl = optional_str(record.get("sourceurl"))
    if sourceurl is None:
        return False
    if extension is not None:
        return extension.lower().lstrip(".") == "kml"
    return urlsplit(sourceurl).path.lower().endswith(".kml")


def _approved_kml_url(value: object) -> str:
    url = optional_str(value)
    if url is None:
        raise WraHistoricalFloodPayloadError(
            "WRA historical KML record is missing an approved HTTPS sourceurl"
        )
    parsed = urlsplit(url)
    if (
        parsed.scheme.lower() != "https"
        or parsed.hostname is None
        or parsed.hostname.lower() != "opendata.wra.gov.tw"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
    ):
        raise WraHistoricalFloodPayloadError(
            "WRA historical KML sourceurl must use the approved HTTPS opendata.wra.gov.tw host"
        )
    return url


def _dataset_revision(record: Mapping[str, Any]) -> str:
    for key in ("createdatatime", "_importdate", "updated_at", "builddate"):
        value = optional_str(record.get(key))
        if value is not None:
            return value[:256]
    return "metadata-record-without-revision"


def _revision_sort_key(record: Mapping[str, Any]) -> tuple[int, str]:
    imported_at = optional_str(record.get("_importdate"))
    revision = imported_at or _dataset_revision(record)
    parsed = parse_datetime(revision)
    if parsed is None:
        return (0, revision)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=WRA_LOCAL_TZ)
    return (1, parsed.astimezone(UTC).isoformat())


def _direct_child_text(element: Element, child_name: str) -> str | None:
    for child in element:
        if _local_name(child.tag) == child_name:
            return optional_str(child.text)
    return None


def _first_descendant_text(element: Element, descendant_name: str) -> str | None:
    for descendant in element.iter():
        if _local_name(descendant.tag) == descendant_name:
            return optional_str(descendant.text)
    return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _inject_missing_official_xsi_namespace(text: str) -> str:
    """Repair the one known WRA producer defect without broad XML recovery."""

    if (
        "xsi:schemaLocation" not in text
        or re.search(r"\bxmlns:xsi\s*=", text) is not None
    ):
        return text
    root_match = re.search(r"<kml\b[^>]*", text, flags=re.IGNORECASE)
    if root_match is None:
        return text
    declaration = ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
    return f"{text[: root_match.end()]}{declaration}{text[root_match.end() :]}"
