from __future__ import annotations

import re
from datetime import datetime
from ipaddress import ip_address
from typing import Any, Protocol, cast
from unicodedata import normalize
from urllib.parse import SplitResult, unquote, urlsplit

from app.api.schemas import MapLayer, TileJson, TileJsonVectorLayer
from app.domain.layers import LayerRecord, LayerRepositoryUnavailable

PLACEHOLDER_TILE_URL_MARKERS = (
    "tiles.placeholder.flood-risk.local",
    "tiles.example.test",
)
REVIEWED_EXTERNAL_TILE_HOSTS_KEY = "reviewed_external_tile_hosts"
MAX_PERCENT_DECODE_PASSES = 5
NESTED_NETWORK_AUTHORITY_PATTERN = re.compile(
    r"(?<![a-z0-9+.-])(?:(?P<scheme>[a-z][a-z0-9+.-]*):)?//",
    re.IGNORECASE,
)
NESTED_AUTHORITY_TERMINATORS = frozenset("/?#&;")
UNSAFE_EXTERNAL_HOST_SUFFIXES = (
    ".example",
    ".home",
    ".internal",
    ".invalid",
    ".lan",
    ".local",
    ".localdomain",
    ".localhost",
    ".test",
)
RESERVED_PLACEHOLDER_HOSTS = frozenset(
    {
        "example.com",
        "example.net",
        "example.org",
    }
)


class FetchMapLayers(Protocol):
    def __call__(self, *, database_url: str) -> tuple[LayerRecord, ...]: ...


class FetchMapLayer(Protocol):
    def __call__(self, *, database_url: str, layer_id: str) -> LayerRecord | None: ...


class LayerTileJsonDisabled(RuntimeError):
    """Raised when a known layer is intentionally unavailable to clients."""


class LayerTileJsonUnavailable(RuntimeError):
    """Raised when an enabled layer has no usable tile template."""


def legacy_static_layers(now: datetime) -> list[MapLayer]:
    return [
        MapLayer(
            id="flood-potential",
            name="淹水潛勢",
            description="官方公開資料中的淹水潛勢範圍。",
            category="flood_potential",
            status="available",
            minzoom=8,
            maxzoom=18,
            attribution="政府開放資料",
            tilejson_url="/v1/layers/flood-potential/tilejson",
            updated_at=now,
        ),
    ]


def static_layer_records(now: datetime) -> tuple[LayerRecord, ...]:
    return (
        LayerRecord(
            id="flood-potential",
            name="淹水潛勢規劃圖資",
            description="官方淹水潛勢規劃圖資的靜態備援圖層。",
            category="flood_potential",
            status="disabled",
            minzoom=8,
            maxzoom=18,
            attribution="政府開放資料",
            tilejson_url="/v1/layers/flood-potential/tilejson",
            updated_at=now,
            metadata={
                "version": "static-fallback",
                "bounds": [119.3, 21.8, 122.1, 25.4],
                "vector_layers": [
                    {
                        "id": "flood_potential",
                        "fields": {"source_id": "String", "category": "String"},
                    }
                ],
            },
        ),
    )


def map_layer_from_record(record: LayerRecord) -> MapLayer:
    tilejson_url = public_tilejson_url(record)
    if tilejson_url is None:
        raise LayerTileJsonDisabled(record.id)
    return MapLayer(
        id=record.id,
        name=localized_layer_name(record),
        description=localized_layer_description(record),
        category=cast(Any, record.category),
        status=cast(Any, record.status),
        minzoom=record.minzoom,
        maxzoom=record.maxzoom,
        attribution=localized_layer_attribution(record),
        tilejson_url=tilejson_url,
        updated_at=record.updated_at,
    )


def localized_layer_name(record: LayerRecord) -> str:
    if record.id == "flood-potential":
        return "淹水潛勢規劃圖資"
    if record.id == "query-heat":
        return "查詢關注度"
    return record.name


def localized_layer_description(record: LayerRecord) -> str | None:
    if record.id == "flood-potential":
        return "官方淹水潛勢規劃圖資。"
    if record.id == "query-heat":
        return "去識別化後的區域查詢關注度。"
    return record.description


def localized_layer_attribution(record: LayerRecord) -> str | None:
    if record.id in {"flood-potential", "query-heat"}:
        return "政府開放資料" if record.id == "flood-potential" else "本服務去識別化統計"
    return record.attribution


def layer_records(
    now: datetime,
    *,
    database_url: str,
    fetch_layers: FetchMapLayers,
) -> tuple[LayerRecord, ...]:
    try:
        records = fetch_layers(database_url=database_url)
    except LayerRepositoryUnavailable:
        records = static_layer_records(now)
    resolved_records = records or static_layer_records(now)
    return tuple(record for record in resolved_records if is_public_external_tile_layer(record))


def static_layer_by_id(layer_id: str, now: datetime) -> LayerRecord | None:
    record = {layer.id: layer for layer in static_layer_records(now)}.get(layer_id)
    return record if record is not None and is_public_external_tile_layer(record) else None


def layer_record(
    layer_id: str,
    now: datetime,
    *,
    database_url: str,
    fetch_layers: FetchMapLayers,
    fetch_layer: FetchMapLayer,
) -> LayerRecord | None:
    if layer_id == "query-heat":
        return None
    try:
        records = fetch_layers(database_url=database_url)
    except LayerRepositoryUnavailable:
        return static_layer_by_id(layer_id, now)
    if not records:
        return static_layer_by_id(layer_id, now)
    try:
        record = fetch_layer(database_url=database_url, layer_id=layer_id)
    except LayerRepositoryUnavailable:
        return static_layer_by_id(layer_id, now)
    return record if record is not None and is_public_external_tile_layer(record) else None


def layers(
    now: datetime,
    *,
    database_url: str,
    fetch_layers: FetchMapLayers,
) -> list[MapLayer]:
    return [map_layer_from_record(record) for record in layer_records(now, database_url=database_url, fetch_layers=fetch_layers)]


def tilejson_from_layer_record(
    record: LayerRecord,
    *,
    allow_local_tile_fallback: bool = False,
) -> TileJson:
    if record.status == "disabled" or not is_public_external_tile_layer(record):
        raise LayerTileJsonDisabled(record.id)

    metadata = record.metadata
    tile_templates, tile_url_source = tile_templates_for_layer(
        record,
        allow_local_tile_fallback=allow_local_tile_fallback,
    )
    return TileJson(
        tilejson=str(metadata.get("tilejson", "3.0.0")),
        name=localized_layer_name(record),
        version=_optional_str(metadata.get("version")),
        attribution=localized_layer_attribution(record),
        status=cast(Any, record.status),
        scheme=cast(Any, metadata.get("scheme", "xyz")),
        tiles=tile_templates,
        tile_url_source=cast(Any, tile_url_source),
        cache_control=tile_cache_control(metadata),
        minzoom=_optional_int(metadata.get("minzoom")) if "minzoom" in metadata else record.minzoom,
        maxzoom=_optional_int(metadata.get("maxzoom")) if "maxzoom" in metadata else record.maxzoom,
        bounds=_number_list(metadata.get("bounds"), expected_length=4),
        center=_number_list(metadata.get("center"), expected_length=3),
        updated_at=record.updated_at,
        vector_layers=tilejson_vector_layers(record),
    )


def tile_templates_for_layer(
    record: LayerRecord,
    *,
    allow_local_tile_fallback: bool,
) -> tuple[list[str], str]:
    del allow_local_tile_fallback
    metadata_tiles = _validated_raw_tile_templates(record.metadata)
    if metadata_tiles is None:
        raise LayerTileJsonDisabled(record.id)
    reviewed_hosts = reviewed_external_tile_hosts(record.metadata)
    if all(
        is_external_tile_url(tile, reviewed_hosts=reviewed_hosts)
        for tile in metadata_tiles
    ):
        return metadata_tiles, "metadata"
    raise LayerTileJsonDisabled(record.id)


def is_public_external_tile_layer(record: LayerRecord) -> bool:
    if record.id == "query-heat" or record.category == "query_heat":
        return False
    reviewed_hosts = reviewed_external_tile_hosts(record.metadata)
    if not reviewed_hosts or public_tilejson_url(record) is None:
        return False
    metadata_tiles = _validated_raw_tile_templates(record.metadata)
    return metadata_tiles is not None and all(
        is_external_tile_url(tile, reviewed_hosts=reviewed_hosts)
        for tile in metadata_tiles
    )


def _validated_raw_tile_templates(metadata: dict[str, Any]) -> list[str] | None:
    raw_tiles = metadata.get("tiles")
    if not isinstance(raw_tiles, list) or not raw_tiles:
        return None
    if any(not isinstance(tile, str) or not tile for tile in raw_tiles):
        return None
    return raw_tiles


def public_tilejson_url(record: LayerRecord) -> str | None:
    decoded = _fully_percent_decoded_url(record.tilejson_url)
    if decoded is None:
        return None
    parsed = _safe_urlsplit(decoded)
    if parsed is None:
        return None
    if not parsed.scheme and not parsed.netloc:
        if parsed.query or parsed.fragment or not _has_safe_product_path(parsed):
            return None
        expected_path = f"/v1/layers/{record.id}/tilejson"
        return record.tilejson_url.strip() if parsed.path == expected_path else None
    reviewed_hosts = reviewed_external_tile_hosts(record.metadata)
    if is_external_tile_url(record.tilejson_url, reviewed_hosts=reviewed_hosts):
        return record.tilejson_url.strip()
    return None


def reviewed_external_tile_hosts(metadata: dict[str, Any]) -> frozenset[str]:
    raw_hosts = metadata.get(REVIEWED_EXTERNAL_TILE_HOSTS_KEY)
    if not isinstance(raw_hosts, list) or not raw_hosts:
        return frozenset()
    normalized_hosts: set[str] = set()
    for raw_host in raw_hosts:
        if not isinstance(raw_host, str):
            return frozenset()
        host = _normalized_public_host(raw_host)
        if host is None:
            return frozenset()
        normalized_hosts.add(host)
    return frozenset(normalized_hosts)


def is_external_tile_url(
    value: str,
    *,
    reviewed_hosts: frozenset[str] | tuple[str, ...] = (),
) -> bool:
    parsed = _safe_external_url(value)
    if parsed is None:
        return False
    host = _normalized_public_host(parsed.hostname or "")
    normalized_reviewed_hosts = {
        normalized
        for candidate in reviewed_hosts
        if (normalized := _normalized_public_host(candidate)) is not None
    }
    return (
        host is not None
        and host in normalized_reviewed_hosts
        and _has_only_reviewed_nested_authorities(
            parsed,
            reviewed_hosts=normalized_reviewed_hosts,
        )
    )


def _has_only_reviewed_nested_authorities(
    parsed: SplitResult,
    *,
    reviewed_hosts: set[str],
) -> bool:
    """Validate each syntactic URI or network-path authority in URL components."""
    for component in (parsed.path, parsed.query, parsed.fragment):
        for match in NESTED_NETWORK_AUTHORITY_PATTERN.finditer(component):
            authority_start = match.end()
            authority_end = next(
                (
                    index
                    for index in range(authority_start, len(component))
                    if component[index] in NESTED_AUTHORITY_TERMINATORS
                ),
                len(component),
            )
            authority = component[authority_start:authority_end]
            scheme = (match.group("scheme") or parsed.scheme).casefold()
            nested = _safe_urlsplit(f"{scheme}://{authority}")
            if nested is None or not _is_reviewed_http_authority(
                nested,
                reviewed_hosts=reviewed_hosts,
            ):
                return False
    return True


def _is_reviewed_http_authority(
    parsed: SplitResult,
    *,
    reviewed_hosts: set[str],
) -> bool:
    scheme = parsed.scheme.casefold()
    if scheme not in {"http", "https"} or not parsed.netloc:
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    try:
        port = parsed.port
    except ValueError:
        return False
    if port is not None and port != (443 if scheme == "https" else 80):
        return False
    host = _normalized_public_host(parsed.hostname or "")
    return host is not None and host in reviewed_hosts


def _safe_external_url(value: str) -> SplitResult | None:
    decoded = _fully_percent_decoded_url(value)
    if decoded is None:
        return None
    parsed = _safe_urlsplit(decoded)
    if parsed is None:
        return None
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    if port is not None and port != (443 if parsed.scheme.casefold() == "https" else 80):
        return None
    if _normalized_public_host(parsed.hostname or "") is None:
        return None
    if is_placeholder_tile_url(decoded) or not _has_safe_product_path(parsed):
        return None
    return parsed


def _safe_urlsplit(value: str) -> SplitResult | None:
    try:
        return urlsplit(value)
    except ValueError:
        return None


def _fully_percent_decoded_url(value: str) -> str | None:
    current = value.strip()
    if not current or current != value:
        return None
    for _pass in range(MAX_PERCENT_DECODE_PASSES):
        canonical = normalize("NFKC", current)
        if re.search(r"%(?![0-9a-fA-F]{2})", canonical):
            return None
        try:
            decoded = unquote(canonical, errors="strict")
        except UnicodeDecodeError:
            return None
        if decoded == current:
            return None if _has_unsafe_url_characters(current) else current
        current = decoded
    canonical = normalize("NFKC", current)
    if re.search(r"%(?![0-9a-fA-F]{2})", canonical):
        return None
    try:
        if unquote(canonical, errors="strict") != current:
            return None
        return None if _has_unsafe_url_characters(current) else current
    except UnicodeDecodeError:
        return None


def _has_unsafe_url_characters(value: str) -> bool:
    return any(
        character.isspace() or ord(character) < 32 or ord(character) == 127
        for character in value
    )


def _has_safe_product_path(parsed: SplitResult) -> bool:
    decoded_url = parsed.geturl()
    if _has_unsafe_url_characters(decoded_url):
        return False
    if "\\" in decoded_url:
        return False
    if "//" in parsed.path:
        return False
    path_segments = [segment.casefold() for segment in parsed.path.split("/") if segment]
    if any(segment in {".", ".."} for segment in path_segments):
        return False
    product_components = f"{parsed.path}?{parsed.query}#{parsed.fragment}".casefold()
    if re.search(r"(?<![a-z0-9])v1[^a-z0-9]+tiles(?![a-z0-9])", product_components):
        return False
    return "pmtiles" not in product_components


def _normalized_public_host(value: str) -> str | None:
    candidate = value.strip().rstrip(".").casefold()
    if not candidate or any(character.isspace() for character in candidate):
        return None
    try:
        host = candidate.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    try:
        address = ip_address(host)
    except ValueError:
        if re.fullmatch(r"[0-9.]+", host) or any(
            label.startswith("0x") for label in host.split(".")
        ):
            return None
        if "." not in host:
            return None
        if any(
            not label
            or len(label) > 63
            or label.startswith("-")
            or label.endswith("-")
            or re.fullmatch(r"[a-z0-9-]+", label) is None
            for label in host.split(".")
        ):
            return None
    else:
        return host if address.is_global else None
    if host in RESERVED_PLACEHOLDER_HOSTS or any(
        host.endswith(f".{reserved}") for reserved in RESERVED_PLACEHOLDER_HOSTS
    ):
        return None
    if any(host == suffix[1:] or host.endswith(suffix) for suffix in UNSAFE_EXTERNAL_HOST_SUFFIXES):
        return None
    if any(marker in host for marker in PLACEHOLDER_TILE_URL_MARKERS):
        return None
    return host


def is_placeholder_tile_url(value: str) -> bool:
    normalized = value.casefold()
    return any(marker in normalized for marker in PLACEHOLDER_TILE_URL_MARKERS)


def tile_cache_control(metadata: dict[str, Any]) -> str | None:
    configured = _optional_str(metadata.get("cache_control"))
    if configured:
        return configured
    return None


def tilejson_vector_layers(record: LayerRecord) -> list[TileJsonVectorLayer]:
    vector_layers = record.metadata.get("vector_layers")
    if isinstance(vector_layers, list) and vector_layers:
        return [
            TileJsonVectorLayer(
                id=str(item.get("id", record.id.replace("-", "_"))),
                description=_optional_str(item.get("description")),
                minzoom=_optional_int(item.get("minzoom")),
                maxzoom=_optional_int(item.get("maxzoom")),
                fields=_string_dict(item.get("fields")),
            )
            for item in vector_layers
            if isinstance(item, dict)
        ]
    return [
        TileJsonVectorLayer(
            id=record.id.replace("-", "_"),
            fields={"source_id": "String", "category": "String"},
        )
    ]


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(cast(Any, value))
    except (TypeError, ValueError):
        return None


def _number_list(value: object, *, expected_length: int) -> list[float] | None:
    if not isinstance(value, list) or len(value) != expected_length:
        return None
    try:
        return [float(cast(Any, item)) for item in value]
    except (TypeError, ValueError):
        return None


def _string_dict(value: object) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    return {str(key): str(item) for key, item in value.items()}
