from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from xml.etree.ElementTree import Element, ParseError

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

MAX_CAP_BYTES = 2 * 1024 * 1024
MAX_XML_DEPTH = 32
MAX_XML_ELEMENTS = 20_000
MAX_CAP_MESSAGES = 256
MAX_AREAS_PER_MESSAGE = 128
MAX_REFERENCES_PER_MESSAGE = 64
MAX_POLYGON_COORDINATES = 4_096
CAP_12_NAMESPACE = "urn:oasis:names:tc:emergency:cap:1.2"


class CapDocumentError(ValueError):
    """Raised when a CAP document is unsafe, unbounded, or invalid."""


@dataclass(frozen=True)
class ParsedCapReference:
    sender: str
    identifier: str
    sent: datetime


@dataclass(frozen=True)
class ParsedCapArea:
    area_desc: str
    geocodes: tuple[tuple[str, str], ...]
    polygon: tuple[tuple[float, float], ...] | None
    circle: tuple[float, float, float] | None


@dataclass(frozen=True)
class ParsedCapMessage:
    sender: str
    identifier: str
    sent: datetime
    status: str
    message_type: str
    scope: str
    event: str
    headline: str | None
    description: str | None
    effective: datetime | None
    onset: datetime | None
    expires: datetime | None
    references: tuple[ParsedCapReference, ...]
    areas: tuple[ParsedCapArea, ...]


ParseCapDocument = Callable[[str], tuple[ParsedCapMessage, ...]]


def parse_cap_document(xml_text: str) -> tuple[ParsedCapMessage, ...]:
    if not isinstance(xml_text, str):
        raise CapDocumentError("CAP document must be text")
    if len(xml_text.encode("utf-8")) > MAX_CAP_BYTES:
        raise CapDocumentError("CAP document exceeds the 2 MiB input limit")

    try:
        root = ElementTree.fromstring(xml_text)
    except (ParseError, DefusedXmlException, ValueError) as exc:
        raise CapDocumentError(f"CAP XML could not be parsed: {type(exc).__name__}") from exc

    _validate_tree_bounds(root)
    alerts = tuple(element for element in root.iter() if _local_name(element.tag) == "alert")
    if len(alerts) > MAX_CAP_MESSAGES:
        raise CapDocumentError("CAP document exceeds the 256 message limit")
    if any(_namespace(alert.tag) != CAP_12_NAMESPACE for alert in alerts):
        raise CapDocumentError("CAP alert must use the CAP 1.2 namespace")
    if not alerts and root.tag != f"{{{CAP_12_NAMESPACE}}}alerts":
        raise CapDocumentError("CAP empty collection must use the CAP 1.2 alerts root")
    return tuple(_parse_message(alert) for alert in alerts)


def _validate_tree_bounds(root: Element) -> None:
    count = 0
    stack = [(root, 1)]
    while stack:
        element, depth = stack.pop()
        count += 1
        if count > MAX_XML_ELEMENTS:
            raise CapDocumentError("CAP XML exceeds the 20000 element limit")
        if depth > MAX_XML_DEPTH:
            raise CapDocumentError("CAP XML exceeds the depth limit of 32")
        stack.extend((child, depth + 1) for child in element)


def _parse_message(alert: Element) -> ParsedCapMessage:
    sender = _required_text(alert, "sender")
    identifier = _required_text(alert, "identifier")
    sent = _required_datetime(alert, "sent")
    status = _required_text(alert, "status")
    message_type = _required_text(alert, "msgType")
    scope = _required_text(alert, "scope")

    infos = _children(alert, "info")
    if not infos:
        raise CapDocumentError("CAP alert is missing info")
    info = infos[0]
    event = _required_text(info, "event")
    areas = tuple(_parse_area(area) for parent in infos for area in _children(parent, "area"))
    if len(areas) > MAX_AREAS_PER_MESSAGE:
        raise CapDocumentError("CAP alert exceeds the 128 area limit")

    return ParsedCapMessage(
        sender=sender,
        identifier=identifier,
        sent=sent,
        status=status,
        message_type=message_type,
        scope=scope,
        event=event,
        headline=_optional_text(info, "headline"),
        description=_optional_text(info, "description"),
        effective=_optional_datetime(info, "effective"),
        onset=_optional_datetime(info, "onset"),
        expires=_optional_datetime(info, "expires"),
        references=_parse_references(_optional_text(alert, "references")),
        areas=areas,
    )


def _parse_references(text: str | None) -> tuple[ParsedCapReference, ...]:
    if text is None:
        return ()
    tokens = text.split()
    if len(tokens) > MAX_REFERENCES_PER_MESSAGE:
        raise CapDocumentError("CAP alert exceeds the 64 reference limit")
    references: list[ParsedCapReference] = []
    for token in tokens:
        fields = token.split(",")
        if len(fields) != 3 or any(not field.strip() for field in fields):
            raise CapDocumentError("CAP reference must be a sender,identifier,sent triple")
        references.append(
            ParsedCapReference(
                sender=fields[0].strip(),
                identifier=fields[1].strip(),
                sent=_parse_datetime(fields[2], field_name="references.sent"),
            )
        )
    return tuple(references)


def _parse_area(area: Element) -> ParsedCapArea:
    area_desc = _required_text(area, "areaDesc")
    geocodes: list[tuple[str, str]] = []
    for geocode in _children(area, "geocode"):
        geocodes.append(
            (
                _required_text(geocode, "valueName"),
                _required_text(geocode, "value"),
            )
        )
    polygon_text = _optional_text(area, "polygon")
    circle_text = _optional_text(area, "circle")
    return ParsedCapArea(
        area_desc=area_desc,
        geocodes=tuple(geocodes),
        polygon=_parse_polygon(polygon_text) if polygon_text is not None else None,
        circle=_parse_circle(circle_text) if circle_text is not None else None,
    )


def _parse_polygon(text: str) -> tuple[tuple[float, float], ...]:
    tokens = text.split()
    if not tokens:
        raise CapDocumentError("CAP polygon must contain coordinates")
    if len(tokens) > MAX_POLYGON_COORDINATES:
        raise CapDocumentError("CAP polygon exceeds the 4096 coordinate limit")
    return tuple(_parse_pair(token, field_name="polygon") for token in tokens)


def _parse_circle(text: str) -> tuple[float, float, float]:
    fields = text.split()
    if len(fields) != 2:
        raise CapDocumentError("CAP circle must contain a coordinate and radius")
    latitude, longitude = _parse_pair(fields[0], field_name="circle")
    radius = _finite_float(fields[1], field_name="circle radius")
    if radius < 0:
        raise CapDocumentError("CAP circle radius must be non-negative")
    return latitude, longitude, radius


def _parse_pair(text: str, *, field_name: str) -> tuple[float, float]:
    fields = text.split(",")
    if len(fields) != 2:
        raise CapDocumentError(f"CAP {field_name} coordinate must contain two numbers")
    return (
        _finite_float(fields[0], field_name=field_name),
        _finite_float(fields[1], field_name=field_name),
    )


def _finite_float(text: str, *, field_name: str) -> float:
    try:
        value = float(text)
    except ValueError as exc:
        raise CapDocumentError(f"CAP {field_name} contains a non-numeric value") from exc
    if not math.isfinite(value):
        raise CapDocumentError(f"CAP {field_name} contains a non-finite value")
    return value


def _required_datetime(parent: Element, name: str) -> datetime:
    return _parse_datetime(_required_text(parent, name), field_name=name)


def _optional_datetime(parent: Element, name: str) -> datetime | None:
    text = _optional_text(parent, name)
    return _parse_datetime(text, field_name=name) if text is not None else None


def _parse_datetime(text: str, *, field_name: str) -> datetime:
    try:
        value = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CapDocumentError(f"CAP {field_name} must be an ISO 8601 datetime") from exc
    if value.tzinfo is None or value.utcoffset() is None:
        raise CapDocumentError(f"CAP {field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _required_text(parent: Element, name: str) -> str:
    text = _optional_text(parent, name)
    if text is None:
        raise CapDocumentError(f"CAP field {name} is required")
    return text


def _optional_text(parent: Element, name: str) -> str | None:
    for child in parent:
        if _local_name(child.tag) == name and _namespace(child.tag) == CAP_12_NAMESPACE:
            text = (child.text or "").strip()
            return text or None
    return None


def _children(parent: Element, name: str) -> tuple[Element, ...]:
    return tuple(
        child
        for child in parent
        if _local_name(child.tag) == name and _namespace(child.tag) == CAP_12_NAMESPACE
    )


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _namespace(tag: str) -> str | None:
    if not tag.startswith("{") or "}" not in tag:
        return None
    return tag[1:].split("}", 1)[0]
