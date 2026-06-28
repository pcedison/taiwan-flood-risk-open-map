"""Taichung City local official water adapters."""

from app.adapters.local_taichung.water import (
    DEFAULT_TAICHUNG_WATER_TIMEOUT_SECONDS,
    TAICHUNG_WATER_LEVEL_API_URL,
    TAICHUNG_WATER_LEVEL_DATA_URL,
    TAICHUNG_WATER_LEVEL_METADATA,
    FetchJson,
    TaichungWaterAdapterError,
    TaichungWaterFetchError,
    TaichungWaterLevelApiAdapter,
    TaichungWaterPayloadError,
    fetch_taichung_json,
    parse_taichung_water_level_payload,
)

__all__ = [
    "DEFAULT_TAICHUNG_WATER_TIMEOUT_SECONDS",
    "TAICHUNG_WATER_LEVEL_API_URL",
    "TAICHUNG_WATER_LEVEL_DATA_URL",
    "TAICHUNG_WATER_LEVEL_METADATA",
    "FetchJson",
    "TaichungWaterAdapterError",
    "TaichungWaterFetchError",
    "TaichungWaterLevelApiAdapter",
    "TaichungWaterPayloadError",
    "fetch_taichung_json",
    "parse_taichung_water_level_payload",
]
