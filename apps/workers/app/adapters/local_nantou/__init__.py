"""Nantou County local official water adapters."""

from app.adapters.local_nantou.water import (
    DEFAULT_NANTOU_WATER_TIMEOUT_SECONDS,
    NANTOU_SEWER_WATER_LEVEL_DATA_URL,
    NANTOU_SEWER_WATER_LEVEL_KML_URL,
    NANTOU_SEWER_WATER_LEVEL_METADATA,
    FetchText,
    NantouSewerWaterLevelKmlAdapter,
    NantouWaterAdapterError,
    NantouWaterFetchError,
    NantouWaterPayloadError,
    fetch_nantou_text,
    parse_nantou_sewer_water_level_kml,
)

__all__ = [
    "DEFAULT_NANTOU_WATER_TIMEOUT_SECONDS",
    "NANTOU_SEWER_WATER_LEVEL_DATA_URL",
    "NANTOU_SEWER_WATER_LEVEL_KML_URL",
    "NANTOU_SEWER_WATER_LEVEL_METADATA",
    "FetchText",
    "NantouSewerWaterLevelKmlAdapter",
    "NantouWaterAdapterError",
    "NantouWaterFetchError",
    "NantouWaterPayloadError",
    "fetch_nantou_text",
    "parse_nantou_sewer_water_level_kml",
]
