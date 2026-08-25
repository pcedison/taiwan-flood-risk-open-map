from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta, timezone
from http.client import HTTPMessage
from itertools import pairwise
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    HTTPSHandler,
    Request,
    build_opener,
)
from xml.etree.ElementTree import Element, tostring

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
MAX_WRA_HISTORICAL_METADATA_BYTES = 256 * 1024
MAX_WRA_HISTORICAL_KML_BYTES = 8 * 1024 * 1024
MAX_WRA_HISTORICAL_XML_DEPTH = 64
MAX_WRA_HISTORICAL_XML_ELEMENTS = 100_000
MAX_WRA_HISTORICAL_PLACEMARKS = 10_000
MAX_WRA_HISTORICAL_COORDINATES_PER_RING = 2_048
MAX_WRA_HISTORICAL_TOTAL_COORDINATES = 250_000
MAX_WRA_HISTORICAL_GEOMETRY_PARTS = 256
# The 2026-08-26 official artifact measured 1,123,600 maximum and
# 3,458,657 cumulative conservative topology-work units.  Ten million leaves
# about 2.8x whole-artifact headroom while bounding all later O(n^2) checks.
MAX_WRA_HISTORICAL_TOPOLOGY_WORK = 10_000_000
WRA_LOCAL_TZ = timezone(timedelta(hours=8))

_TAIWAN_LONGITUDE_BOUNDS = (117.0, 123.5)
_TAIWAN_LATITUDE_BOUNDS = (20.0, 27.5)
_KML_22_NAMESPACE = "http://www.opengis.net/kml/2.2"
_KML_22_ROOT = f"{{{_KML_22_NAMESPACE}}}kml"
_KML_DOCUMENT = f"{{{_KML_22_NAMESPACE}}}Document"
_KML_FOLDER = f"{{{_KML_22_NAMESPACE}}}Folder"
_KML_PLACEMARK = f"{{{_KML_22_NAMESPACE}}}Placemark"
_KML_NAME = f"{{{_KML_22_NAMESPACE}}}name"
_KML_POINT = f"{{{_KML_22_NAMESPACE}}}Point"
_KML_POLYGON = f"{{{_KML_22_NAMESPACE}}}Polygon"
_KML_MULTI_GEOMETRY = f"{{{_KML_22_NAMESPACE}}}MultiGeometry"
_KML_OUTER_BOUNDARY = f"{{{_KML_22_NAMESPACE}}}outerBoundaryIs"
_KML_INNER_BOUNDARY = f"{{{_KML_22_NAMESPACE}}}innerBoundaryIs"
_KML_LINEAR_RING = f"{{{_KML_22_NAMESPACE}}}LinearRing"
_KML_COORDINATES = f"{{{_KML_22_NAMESPACE}}}coordinates"
_KML_WHEN = f"{{{_KML_22_NAMESPACE}}}when"
_KML_DATA = f"{{{_KML_22_NAMESPACE}}}Data"
_KML_SIMPLE_DATA = f"{{{_KML_22_NAMESPACE}}}SimpleData"
_KML_VALUE = f"{{{_KML_22_NAMESPACE}}}value"
_KML_CONTAINER_TAGS = {_KML_DOCUMENT, _KML_FOLDER}
_KML_SUPPORTED_GEOMETRY_TAGS = {_KML_POINT, _KML_POLYGON, _KML_MULTI_GEOMETRY}
_KML_STRUCTURAL_TAGS = {
    _KML_22_ROOT,
    _KML_DOCUMENT,
    _KML_FOLDER,
    _KML_PLACEMARK,
    _KML_POINT,
    _KML_POLYGON,
    _KML_MULTI_GEOMETRY,
    _KML_OUTER_BOUNDARY,
    _KML_INNER_BOUNDARY,
    _KML_LINEAR_RING,
    _KML_COORDINATES,
}
_KML_STRUCTURAL_LOCAL_NAMES = {
    "kml",
    "Document",
    "Folder",
    "Placemark",
    "Point",
    "Polygon",
    "MultiGeometry",
    "outerBoundaryIs",
    "innerBoundaryIs",
    "LinearRing",
    "coordinates",
}
_KML_ALLOWED_STRUCTURAL_PARENTS = {
    _KML_POINT: {_KML_PLACEMARK},
    _KML_POLYGON: {_KML_PLACEMARK, _KML_MULTI_GEOMETRY},
    _KML_MULTI_GEOMETRY: {_KML_PLACEMARK},
    _KML_OUTER_BOUNDARY: {_KML_POLYGON},
    _KML_INNER_BOUNDARY: {_KML_POLYGON},
    _KML_LINEAR_RING: {_KML_OUTER_BOUNDARY, _KML_INNER_BOUNDARY},
    _KML_COORDINATES: {_KML_POINT, _KML_LINEAR_RING},
}
_GEOMETRY_LOCAL_NAMES = {
    "LineString",
    "LinearRing",
    "Model",
    "MultiGeometry",
    "MultiTrack",
    "Point",
    "Polygon",
    "Track",
}
_XSI_NAMESPACE = "http://www.w3.org/2001/XMLSchema-instance"
_CANONICAL_WRA_SCHEMA_LOCATION = (
    "http://www.opengis.net/kml/2.2 "
    "http://schemas.opengis.net/kml/2.2.0/ogckml22.xsd "
    "http://www.google.com/kml/ext/2.2 "
    "http://code.google.com/apis/kml/schema/kml22gx.xsd"
)
_GEOMETRY_EPSILON = 1e-12
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
    snapshot_generation_mode="complete_replace",
)


class WraHistoricalFloodAdapterError(RuntimeError):
    """Base error for the WRA historical-flood adapter."""


class WraHistoricalFloodFetchError(WraHistoricalFloodAdapterError):
    """Raised when the metadata index or resolved KML cannot be fetched."""


class WraHistoricalFloodPayloadError(WraHistoricalFloodAdapterError):
    """Raised when metadata or KML violates the reviewed source contract."""


class _WraHistoricalRedirectHandler(HTTPRedirectHandler):
    """Fail closed before urllib follows any WRA historical KML redirect."""

    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> Request | None:
        resolved_url = urljoin(req.full_url, newurl)
        approved_url = _approved_kml_url(resolved_url)
        return super().redirect_request(
            req,
            fp,
            code,
            msg,
            headers,
            approved_url,
        )


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
        rows, _invalid_geometry_rejections = self._fetch_with_rejections()
        return rows

    def _fetch_with_rejections(
        self,
    ) -> tuple[tuple[RawSourceItem, ...], tuple[str, ...]]:
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
        records, invalid_geometry_rejections = (
            _parse_wra_historical_flood_kml_with_rejections(kml_text)
        )
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
        return tuple(rows), invalid_geometry_rejections

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
        fetched, invalid_geometry_rejections = self._fetch_with_rejections()
        normalized: list[NormalizedEvidence] = []
        rejected = list(invalid_geometry_rejections)
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
    approved_url = _approved_metadata_url(url)
    request = Request(
        approved_url,
        headers={
            "Accept": "application/json",
            "User-Agent": WRA_HISTORICAL_FLOOD_USER_AGENT,
        },
    )
    try:
        opener = _wra_historical_opener()
        with opener.open(request, timeout=timeout_seconds) as response:
            _approved_metadata_url(response.geturl())
            payload = _read_bounded_response(
                response,
                limit=MAX_WRA_HISTORICAL_METADATA_BYTES,
                label="metadata",
            )
            return json.loads(payload.decode("utf-8-sig"))
    except (
        HTTPError,
        URLError,
        TimeoutError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise WraHistoricalFloodFetchError(
            f"Failed to fetch WRA historical metadata {approved_url}: {exc}"
        ) from exc


def fetch_wra_historical_text(url: str, timeout_seconds: int) -> str:
    approved_url = _approved_kml_url(url)
    request = Request(
        approved_url,
        headers={
            "Accept": "application/vnd.google-earth.kml+xml,application/xml,text/xml",
            "User-Agent": WRA_HISTORICAL_FLOOD_USER_AGENT,
        },
    )
    try:
        opener = _wra_historical_opener()
        with opener.open(request, timeout=timeout_seconds) as response:
            _approved_kml_url(response.geturl())
            payload = _read_bounded_response(
                response,
                limit=MAX_WRA_HISTORICAL_KML_BYTES,
                label="KML",
            )
            return payload.decode("utf-8-sig")
    except (HTTPError, URLError, TimeoutError, UnicodeDecodeError) as exc:
        raise WraHistoricalFloodFetchError(
            f"Failed to fetch WRA historical KML {url}: {exc}"
        ) from exc


def _wra_historical_opener() -> Any:
    return build_opener(
        HTTPSHandler(context=taiwan_gov_open_data_ssl_context()),
        _WraHistoricalRedirectHandler(),
    )


def _read_bounded_response(response: Any, *, limit: int, label: str) -> bytes:
    payload = response.read(limit + 1)
    if len(payload) > limit:
        raise WraHistoricalFloodPayloadError(
            f"WRA historical {label} exceeds the {limit} bytes safety limit"
        )
    return payload


def parse_wra_historical_flood_kml(text: str) -> tuple[Mapping[str, Any], ...]:
    records, _invalid_geometry_rejections = (
        _parse_wra_historical_flood_kml_with_rejections(text)
    )
    return records


def _parse_wra_historical_flood_kml_with_rejections(
    text: str,
) -> tuple[tuple[Mapping[str, Any], ...], tuple[str, ...]]:
    _validate_text_size(
        text,
        limit=MAX_WRA_HISTORICAL_KML_BYTES,
        label="KML",
    )
    normalized_text = _inject_missing_official_xsi_namespace(text)
    try:
        root = ET.fromstring(normalized_text.lstrip("\ufeff").strip())
    except (ET.ParseError, DefusedXmlException) as exc:
        raise WraHistoricalFloodPayloadError(
            f"WRA historical KML is not parseable: {exc}"
        ) from exc

    if root.tag != _KML_22_ROOT:
        raise WraHistoricalFloodPayloadError(
            "WRA historical XML must use the exact KML 2.2 root"
        )

    _validate_kml_complexity(root)

    if not any(element.tag == _KML_PLACEMARK for element in root.iter()):
        raise WraHistoricalFloodPayloadError(
            "WRA historical KML does not contain a Placemark"
        )

    records: list[Mapping[str, Any]] = []
    invalid_geometry_rejections: list[str] = []
    _walk_kml(
        root,
        inherited_event_name=None,
        inherited_timestamp=None,
        records=records,
        invalid_geometry_rejections=invalid_geometry_rejections,
    )
    if not records:
        raise WraHistoricalFloodPayloadError(
            "WRA historical KML does not contain a valid Placemark geometry in Taiwan"
        )
    return tuple(records), tuple(invalid_geometry_rejections)


def _validate_text_size(text: str, *, limit: int, label: str) -> None:
    if len(text.encode("utf-8")) > limit:
        raise WraHistoricalFloodPayloadError(
            f"WRA historical {label} exceeds the {limit} bytes safety limit"
        )


def _validate_kml_complexity(root: Element) -> None:
    element_count = 0
    placemark_count = 0
    total_coordinate_count = 0
    geometry_parts_by_placemark: dict[int, int] = {}
    topology_segments_by_placemark: dict[int, int] = {}
    total_topology_work = 0
    stack: list[tuple[Element, int, str | None, int | None]] = [
        (root, 1, None, None)
    ]
    while stack:
        element, depth, parent_tag, placemark_identity = stack.pop()
        element_count += 1
        if element_count > MAX_WRA_HISTORICAL_XML_ELEMENTS:
            raise WraHistoricalFloodPayloadError(
                "WRA historical KML exceeds the elements safety limit "
                f"{MAX_WRA_HISTORICAL_XML_ELEMENTS}"
            )
        if depth > MAX_WRA_HISTORICAL_XML_DEPTH:
            raise WraHistoricalFloodPayloadError(
                "WRA historical KML exceeds the depth safety limit "
                f"{MAX_WRA_HISTORICAL_XML_DEPTH}"
            )

        if element.tag == _KML_PLACEMARK:
            placemark_count += 1
            if placemark_count > MAX_WRA_HISTORICAL_PLACEMARKS:
                raise WraHistoricalFloodPayloadError(
                    "WRA historical KML exceeds the Placemark safety limit "
                    f"{MAX_WRA_HISTORICAL_PLACEMARKS}"
                )
            placemark_identity = id(element)
            geometry_parts_by_placemark[placemark_identity] = 0
            topology_segments_by_placemark[placemark_identity] = 0

        if element.tag in {_KML_POLYGON, _KML_LINEAR_RING} and (
            placemark_identity is not None
        ):
            part_count = geometry_parts_by_placemark[placemark_identity] + 1
            if part_count > MAX_WRA_HISTORICAL_GEOMETRY_PARTS:
                raise WraHistoricalFloodPayloadError(
                    "WRA historical Placemark exceeds the geometry parts safety limit "
                    f"{MAX_WRA_HISTORICAL_GEOMETRY_PARTS}"
                )
            geometry_parts_by_placemark[placemark_identity] = part_count

        if element.tag == _KML_COORDINATES:
            coordinate_count = len((element.text or "").split())
            total_coordinate_count += coordinate_count
            if (
                parent_tag == _KML_LINEAR_RING
                and coordinate_count > MAX_WRA_HISTORICAL_COORDINATES_PER_RING
            ):
                raise WraHistoricalFloodPayloadError(
                    "WRA historical coordinate ring exceeds the "
                    f"{MAX_WRA_HISTORICAL_COORDINATES_PER_RING} coordinates safety limit"
                )
            if total_coordinate_count > MAX_WRA_HISTORICAL_TOTAL_COORDINATES:
                raise WraHistoricalFloodPayloadError(
                    "WRA historical KML exceeds the total coordinate safety limit "
                    f"{MAX_WRA_HISTORICAL_TOTAL_COORDINATES}"
                )
            if parent_tag == _KML_LINEAR_RING and placemark_identity is not None:
                previous_segments = topology_segments_by_placemark[placemark_identity]
                next_segments = previous_segments + max(0, coordinate_count - 1)
                total_topology_work += (
                    next_segments * next_segments
                    - previous_segments * previous_segments
                )
                if total_topology_work > MAX_WRA_HISTORICAL_TOPOLOGY_WORK:
                    raise WraHistoricalFloodPayloadError(
                        "WRA historical KML exceeds the topology work safety limit "
                        f"{MAX_WRA_HISTORICAL_TOPOLOGY_WORK}"
                    )
                topology_segments_by_placemark[placemark_identity] = next_segments

        stack.extend(
            (child, depth + 1, element.tag, placemark_identity)
            for child in reversed(element)
        )


def _walk_kml(
    element: Element,
    *,
    inherited_event_name: str | None,
    inherited_timestamp: datetime | None,
    records: list[Mapping[str, Any]],
    invalid_geometry_rejections: list[str],
) -> None:
    event_name = inherited_event_name
    timestamp = inherited_timestamp
    if element.tag in _KML_CONTAINER_TAGS:
        container_name = _direct_kml_child_text(element, _KML_NAME)
        container_timestamp = _event_timestamp(container_name)
        if container_timestamp is not None:
            event_name = container_name
            timestamp = container_timestamp

    if element.tag == _KML_PLACEMARK:
        record = _placemark_record(
            element,
            inherited_event_name=event_name,
            inherited_timestamp=timestamp,
        )
        if record is not None:
            records.append(record)
        else:
            invalid_geometry_rejections.append(
                _invalid_geometry_rejection_id(element)
            )
        return

    for child in element:
        if child.tag not in {*_KML_CONTAINER_TAGS, _KML_PLACEMARK}:
            continue
        _walk_kml(
            child,
            inherited_event_name=event_name,
            inherited_timestamp=timestamp,
            records=records,
            invalid_geometry_rejections=invalid_geometry_rejections,
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
    placemark_name = (
        _direct_kml_child_text(placemark, _KML_NAME) or "historical flood area"
    )
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
        if element.tag == _KML_WHEN:
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
        if element.tag not in {_KML_DATA, _KML_SIMPLE_DATA}:
            continue
        key = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", element.attrib.get("name", "").lower())
        if key not in timestamp_keys:
            continue
        value = optional_str(element.text)
        if element.tag == _KML_DATA:
            value = _direct_kml_child_text(element, _KML_VALUE) or value
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
    if (
        not _valid_placemark_geometry_graph(placemark)
        or _contains_foreign_or_unsupported_geometry(placemark)
    ):
        return None
    direct_geometries = [
        child for child in placemark if child.tag in _KML_SUPPORTED_GEOMETRY_TAGS
    ]
    if len(direct_geometries) != 1:
        return None

    geometry = direct_geometries[0]
    top_level_descendants = [
        element
        for element in placemark.iter()
        if element.tag in _KML_SUPPORTED_GEOMETRY_TAGS
    ]
    if geometry.tag == _KML_POINT:
        if top_level_descendants != [geometry]:
            return None
        point = _point_geometry(geometry)
        if point is None:
            return None
        return {"type": "Point", "coordinates": point}

    if geometry.tag == _KML_POLYGON:
        if top_level_descendants != [geometry]:
            return None
        polygon = _polygon_coordinates(geometry)
        if polygon is None:
            return None
        return {"type": "Polygon", "coordinates": polygon}

    polygon_elements = [
        child for child in geometry if child.tag == _KML_POLYGON
    ]
    if not polygon_elements or top_level_descendants != [geometry, *polygon_elements]:
        return None
    polygons = [_polygon_coordinates(element) for element in polygon_elements]
    if any(polygon is None for polygon in polygons):
        return None
    valid_polygons = [polygon for polygon in polygons if polygon is not None]
    if len(valid_polygons) == 1:
        return {"type": "Polygon", "coordinates": valid_polygons[0]}
    if not _valid_multipolygon_topology(valid_polygons):
        return None
    return {"type": "MultiPolygon", "coordinates": valid_polygons}


def _valid_placemark_geometry_graph(placemark: Element) -> bool:
    stack = [(child, placemark.tag) for child in reversed(placemark)]
    while stack:
        element, parent_tag = stack.pop()
        local_name = _local_name(element.tag)
        if (
            local_name in _KML_STRUCTURAL_LOCAL_NAMES
            and element.tag not in _KML_STRUCTURAL_TAGS
        ):
            return False
        if element.tag in {
            _KML_22_ROOT,
            _KML_DOCUMENT,
            _KML_FOLDER,
            _KML_PLACEMARK,
        }:
            return False
        allowed_parents = _KML_ALLOWED_STRUCTURAL_PARENTS.get(element.tag)
        if allowed_parents is not None and parent_tag not in allowed_parents:
            return False
        stack.extend((child, element.tag) for child in reversed(element))
    return True


def _contains_foreign_or_unsupported_geometry(placemark: Element) -> bool:
    for element in placemark.iter():
        local_name = _local_name(element.tag)
        if local_name not in _GEOMETRY_LOCAL_NAMES:
            continue
        if not element.tag.startswith(f"{{{_KML_22_NAMESPACE}}}"):
            return True
        if local_name in {"LineString", "Model", "MultiTrack", "Track"}:
            return True
    return False


def _point_geometry(point: Element) -> list[float] | None:
    if any(
        element is not point and _local_name(element.tag) in _GEOMETRY_LOCAL_NAMES
        for element in point.iter()
    ):
        return None
    coordinate_elements = [
        element for element in point.iter() if element.tag == _KML_COORDINATES
    ]
    direct_coordinate_elements = [
        child for child in point if child.tag == _KML_COORDINATES
    ]
    if (
        len(coordinate_elements) != 1
        or direct_coordinate_elements != coordinate_elements
    ):
        return None
    parsed = _coordinate_sequence(optional_str(coordinate_elements[0].text))
    if parsed is None or len(parsed) != 1:
        return None
    return parsed[0]


def _polygon_coordinates(polygon: Element) -> list[list[list[float]]] | None:
    outer: list[list[float]] | None = None
    holes: list[list[list[float]]] = []
    for child in polygon:
        local_name = _local_name(child.tag)
        if local_name in {"outerBoundaryIs", "innerBoundaryIs"} and child.tag not in {
            _KML_OUTER_BOUNDARY,
            _KML_INNER_BOUNDARY,
        }:
            return None
        if child.tag not in {_KML_OUTER_BOUNDARY, _KML_INNER_BOUNDARY}:
            continue
        ring = _boundary_ring(child)
        if not _valid_linear_ring(ring):
            return None
        if child.tag == _KML_OUTER_BOUNDARY:
            if outer is not None:
                return None
            outer = ring
        else:
            assert ring is not None
            holes.append(ring)
    if outer is None:
        return None
    if not _valid_polygon_topology(outer, holes):
        return None
    return [outer, *holes]


def _boundary_ring(boundary: Element) -> list[list[float]] | None:
    ring_elements = [
        element for element in boundary.iter() if element.tag == _KML_LINEAR_RING
    ]
    direct_ring_elements = [
        child for child in boundary if child.tag == _KML_LINEAR_RING
    ]
    if len(ring_elements) != 1 or direct_ring_elements != ring_elements:
        return None
    ring = ring_elements[0]
    coordinate_elements = [
        element for element in ring.iter() if element.tag == _KML_COORDINATES
    ]
    direct_coordinate_elements = [
        child for child in ring if child.tag == _KML_COORDINATES
    ]
    if (
        len(coordinate_elements) != 1
        or direct_coordinate_elements != coordinate_elements
    ):
        return None
    return _coordinate_sequence(optional_str(coordinate_elements[0].text))


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
    topology_ring = _topology_ring(ring)
    if topology_ring is None or abs(_signed_ring_area(topology_ring)) <= _GEOMETRY_EPSILON:
        return False
    if _has_adjacent_segment_overlap(topology_ring):
        return False
    segments = _ring_segments(topology_ring)
    last_index = len(segments) - 1
    for first_index, first_segment in enumerate(segments):
        for second_index in range(first_index + 1, len(segments)):
            if second_index == first_index + 1 or (
                first_index == 0 and second_index == last_index
            ):
                continue
            if _segments_interact(first_segment, segments[second_index]):
                return False
    return True


def _valid_polygon_topology(
    shell: list[list[float]],
    holes: list[list[list[float]]],
) -> bool:
    shell_ring = _topology_ring(shell)
    hole_rings = [_topology_ring(hole) for hole in holes]
    if shell_ring is None or any(hole is None for hole in hole_rings):
        return False
    valid_holes = [hole for hole in hole_rings if hole is not None]
    for hole in valid_holes:
        if _rings_interact(shell_ring, hole):
            return False
        if not all(_point_in_ring_strict(point, shell_ring) for point in hole[:-1]):
            return False
    for first_index, first_hole in enumerate(valid_holes):
        for second_hole in valid_holes[first_index + 1 :]:
            if _rings_interact(first_hole, second_hole):
                return False
            if _point_in_ring_strict(first_hole[0], second_hole) or _point_in_ring_strict(
                second_hole[0], first_hole
            ):
                return False
    return True


def _valid_multipolygon_topology(
    polygons: list[list[list[list[float]]]],
) -> bool:
    topology_polygons: list[list[list[tuple[float, float]]]] = []
    for polygon in polygons:
        rings = [_topology_ring(ring) for ring in polygon]
        if any(ring is None for ring in rings):
            return False
        topology_polygons.append([ring for ring in rings if ring is not None])

    for first_index, first_polygon in enumerate(topology_polygons):
        for second_polygon in topology_polygons[first_index + 1 :]:
            if any(
                _rings_interact(first_ring, second_ring)
                for first_ring in first_polygon
                for second_ring in second_polygon
            ):
                return False
            if _point_in_polygon_surface(first_polygon[0][0], second_polygon) or (
                _point_in_polygon_surface(second_polygon[0][0], first_polygon)
            ):
                return False
    return True


def _point_in_polygon_surface(
    point: tuple[float, float],
    polygon: list[list[tuple[float, float]]],
) -> bool:
    shell, *holes = polygon
    return _point_in_ring_strict(point, shell) and not any(
        _point_in_ring_strict(point, hole) for hole in holes
    )


def _topology_ring(ring: list[list[float]]) -> list[tuple[float, float]] | None:
    points: list[tuple[float, float]] = []
    for coordinate in ring[:-1]:
        point = (coordinate[0], coordinate[1])
        if not points or point != points[-1]:
            points.append(point)
    while len(points) > 1 and points[-1] == points[0]:
        points.pop()
    if len(set(points)) < 3:
        return None
    return [*points, points[0]]


def _signed_ring_area(ring: list[tuple[float, float]]) -> float:
    origin_x, origin_y = ring[0]
    twice_area = 0.0
    for first, second in _ring_segments(ring):
        twice_area += (first[0] - origin_x) * (second[1] - origin_y)
        twice_area -= (second[0] - origin_x) * (first[1] - origin_y)
    return twice_area / 2.0


def _has_adjacent_segment_overlap(ring: list[tuple[float, float]]) -> bool:
    points = ring[:-1]
    for index, current in enumerate(points):
        previous = points[index - 1]
        following = points[(index + 1) % len(points)]
        if abs(_orientation(previous, current, following)) > _GEOMETRY_EPSILON:
            continue
        to_previous = (previous[0] - current[0], previous[1] - current[1])
        to_following = (following[0] - current[0], following[1] - current[1])
        if (
            to_previous[0] * to_following[0]
            + to_previous[1] * to_following[1]
            > _GEOMETRY_EPSILON
        ):
            return True
    return False


def _ring_segments(
    ring: list[tuple[float, float]],
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    return list(pairwise(ring))


def _rings_interact(
    first: list[tuple[float, float]],
    second: list[tuple[float, float]],
) -> bool:
    return any(
        _segments_interact(first_segment, second_segment)
        for first_segment in _ring_segments(first)
        for second_segment in _ring_segments(second)
    )


def _segments_interact(
    first: tuple[tuple[float, float], tuple[float, float]],
    second: tuple[tuple[float, float], tuple[float, float]],
) -> bool:
    first_start, first_end = first
    second_start, second_end = second
    orientations = (
        _orientation(first_start, first_end, second_start),
        _orientation(first_start, first_end, second_end),
        _orientation(second_start, second_end, first_start),
        _orientation(second_start, second_end, first_end),
    )
    first_crosses = (orientations[0] > _GEOMETRY_EPSILON) != (
        orientations[1] > _GEOMETRY_EPSILON
    )
    second_crosses = (orientations[2] > _GEOMETRY_EPSILON) != (
        orientations[3] > _GEOMETRY_EPSILON
    )
    if (
        abs(orientations[0]) > _GEOMETRY_EPSILON
        and abs(orientations[1]) > _GEOMETRY_EPSILON
        and abs(orientations[2]) > _GEOMETRY_EPSILON
        and abs(orientations[3]) > _GEOMETRY_EPSILON
    ):
        return first_crosses and second_crosses
    return (
        _point_on_segment(second_start, first_start, first_end)
        or _point_on_segment(second_end, first_start, first_end)
        or _point_on_segment(first_start, second_start, second_end)
        or _point_on_segment(first_end, second_start, second_end)
    )


def _orientation(
    start: tuple[float, float],
    end: tuple[float, float],
    point: tuple[float, float],
) -> float:
    return (end[0] - start[0]) * (point[1] - start[1]) - (
        end[1] - start[1]
    ) * (point[0] - start[0])


def _point_on_segment(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> bool:
    if abs(_orientation(start, end, point)) > _GEOMETRY_EPSILON:
        return False
    return (
        min(start[0], end[0]) - _GEOMETRY_EPSILON
        <= point[0]
        <= max(start[0], end[0]) + _GEOMETRY_EPSILON
        and min(start[1], end[1]) - _GEOMETRY_EPSILON
        <= point[1]
        <= max(start[1], end[1]) + _GEOMETRY_EPSILON
    )


def _point_in_ring_strict(
    point: tuple[float, float],
    ring: list[tuple[float, float]],
) -> bool:
    inside = False
    for start, end in _ring_segments(ring):
        if _point_on_segment(point, start, end):
            return False
        if (start[1] > point[1]) == (end[1] > point[1]):
            continue
        intersection_x = start[0] + (
            (point[1] - start[1]) * (end[0] - start[0]) / (end[1] - start[1])
        )
        if intersection_x > point[0]:
            inside = not inside
    return inside


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


def _invalid_geometry_rejection_id(placemark: Element) -> str:
    digest = hashlib.sha256(tostring(placemark, encoding="utf-8")).hexdigest()
    return f"invalid_geometry:{digest}"


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
    return _approved_wra_url(value, resource="KML sourceurl")


def _approved_metadata_url(value: object) -> str:
    return _approved_wra_url(value, resource="metadata URL")


def _approved_wra_url(value: object, *, resource: str) -> str:
    url = optional_str(value)
    if url is None:
        raise WraHistoricalFloodPayloadError(
            f"WRA historical {resource} is missing an approved HTTPS URL"
        )
    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise WraHistoricalFloodPayloadError(
            f"WRA historical {resource} must use the approved HTTPS "
            "opendata.wra.gov.tw host"
        ) from exc
    if (
        parsed.scheme.lower() != "https"
        or parsed.hostname is None
        or parsed.hostname.lower() != "opendata.wra.gov.tw"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
    ):
        raise WraHistoricalFloodPayloadError(
            f"WRA historical {resource} must use the approved HTTPS "
            "opendata.wra.gov.tw host"
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


def _direct_kml_child_text(element: Element, child_tag: str) -> str | None:
    for child in element:
        if child.tag == child_tag:
            return optional_str(child.text)
    return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _inject_missing_official_xsi_namespace(text: str) -> str:
    """Repair the one known WRA producer defect without broad XML recovery."""

    if re.search(r"\bxmlns:xsi\s*=", text) is not None:
        return text
    if re.findall(r"\bxsi:[A-Za-z_][\w.-]*", text) != ["xsi:schemaLocation"]:
        return text
    root_match = re.search(r"<kml\b(?P<attributes>[^>]*)>", text)
    if root_match is None:
        return text
    prefix = text[: root_match.start()].lstrip("\ufeff").strip()
    if prefix and re.fullmatch(r"<\?xml\b.*\?>", prefix, flags=re.DOTALL) is None:
        return text
    attributes = root_match.group("attributes")
    namespace_match = re.search(
        r"\bxmlns\s*=\s*(['\"])(?P<namespace>.*?)\1",
        attributes,
        flags=re.DOTALL,
    )
    if namespace_match is None or namespace_match.group("namespace") != _KML_22_NAMESPACE:
        return text
    schema_match = re.search(
        r"\bxsi:schemaLocation\s*=\s*(['\"])(?P<schema>.*?)\1",
        text,
        flags=re.DOTALL,
    )
    if schema_match is None or " ".join(schema_match.group("schema").split()) != (
        _CANONICAL_WRA_SCHEMA_LOCATION
    ):
        return text
    declaration = f' xmlns:xsi="{_XSI_NAMESPACE}"'
    insertion_point = root_match.end() - 1
    return f"{text[:insertion_point]}{declaration}{text[insertion_point:]}"
