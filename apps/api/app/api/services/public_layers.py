from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, cast

from app.api.schemas import MapLayer, TileJson, TileJsonVectorLayer
from app.domain.layers import LayerRecord, LayerRepositoryUnavailable
from app.domain.tiles import VECTOR_TILE_CACHE_CONTROL


PLACEHOLDER_TILE_URL_MARKERS = (
    "tiles.placeholder.flood-risk.local",
    "tiles.example.test",
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
        MapLayer(
            id="query-heat",
            name="查詢關注度",
            description="去識別化後的區域查詢關注度。",
            category="query_heat",
            status="available",
            minzoom=8,
            maxzoom=14,
            attribution="Flood Risk 去識別化統計",
            tilejson_url="/v1/layers/query-heat/tilejson",
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
        LayerRecord(
            id="query-heat",
            name="查詢關注度",
            description="去識別化區域查詢密度的靜態備援圖層。",
            category="query_heat",
            status="disabled",
            minzoom=8,
            maxzoom=14,
            attribution="本服務去識別化統計",
            tilejson_url="/v1/layers/query-heat/tilejson",
            updated_at=now,
            metadata={
                "version": "static-fallback",
                "bounds": [119.3, 21.8, 122.1, 25.4],
                "vector_layers": [
                    {
                        "id": "query_heat",
                        "fields": {"query_count_bucket": "String", "period": "String"},
                    }
                ],
            },
        ),
    )


def map_layer_from_record(record: LayerRecord) -> MapLayer:
    return MapLayer(
        id=record.id,
        name=localized_layer_name(record),
        description=localized_layer_description(record),
        category=cast(Any, record.category),
        status=cast(Any, record.status),
        minzoom=record.minzoom,
        maxzoom=record.maxzoom,
        attribution=localized_layer_attribution(record),
        tilejson_url=record.tilejson_url,
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
        return static_layer_records(now)
    return records or static_layer_records(now)


def static_layer_by_id(layer_id: str, now: datetime) -> LayerRecord | None:
    return {layer.id: layer for layer in static_layer_records(now)}.get(layer_id)


def layer_record(
    layer_id: str,
    now: datetime,
    *,
    database_url: str,
    fetch_layers: FetchMapLayers,
    fetch_layer: FetchMapLayer,
) -> LayerRecord | None:
    try:
        records = fetch_layers(database_url=database_url)
    except LayerRepositoryUnavailable:
        return static_layer_by_id(layer_id, now)
    if not records:
        return static_layer_by_id(layer_id, now)
    try:
        return fetch_layer(database_url=database_url, layer_id=layer_id)
    except LayerRepositoryUnavailable:
        return static_layer_by_id(layer_id, now)


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
    if record.status == "disabled":
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
        cache_control=tile_cache_control(metadata, tile_url_source),
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
    metadata_tiles = _string_list(record.metadata.get("tiles"), fallback=[])
    safe_tiles = [tile for tile in metadata_tiles if not is_placeholder_tile_url(tile)]
    if safe_tiles:
        return safe_tiles, "metadata"
    if allow_local_tile_fallback:
        return [f"/v1/tiles/{record.id}/{{z}}/{{x}}/{{y}}.mvt"], "local_vector_tile_endpoint"
    raise LayerTileJsonUnavailable(record.id)


def is_placeholder_tile_url(value: str) -> bool:
    normalized = value.lower()
    return any(marker in normalized for marker in PLACEHOLDER_TILE_URL_MARKERS)


def tile_cache_control(metadata: dict[str, Any], tile_url_source: str) -> str | None:
    configured = _optional_str(metadata.get("cache_control"))
    if configured:
        return configured
    if tile_url_source == "local_vector_tile_endpoint":
        return VECTOR_TILE_CACHE_CONTROL
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


def _string_list(value: object, *, fallback: list[str]) -> list[str]:
    if isinstance(value, list):
        items = [str(item) for item in value if item]
        if items:
            return items
    return fallback


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
