"""WRA adapters."""

from app.adapters.wra.water_level import (
    DEFAULT_WRA_WATER_LEVEL_TIMEOUT_SECONDS,
    WRA_WATER_LEVEL_API_URL,
    WRA_WATER_LEVEL_DATA_GOV_DATASET_ID,
    WRA_WATER_LEVEL_DATA_GOV_URL,
    WRA_WATER_LEVEL_METADATA,
    WRA_WATER_STATION_API_URL,
    FetchJson,
    WraWaterLevelAdapter,
    WraWaterLevelAdapterError,
    WraWaterLevelApiAdapter,
    WraWaterLevelFetchError,
    WraWaterLevelPayloadError,
    parse_wra_station_metadata_payload,
    parse_wra_water_level_api_payload,
)

__all__ = [
    "DEFAULT_WRA_WATER_LEVEL_TIMEOUT_SECONDS",
    "WRA_WATER_LEVEL_API_URL",
    "WRA_WATER_LEVEL_DATA_GOV_DATASET_ID",
    "WRA_WATER_LEVEL_DATA_GOV_URL",
    "WRA_WATER_LEVEL_METADATA",
    "WRA_WATER_STATION_API_URL",
    "FetchJson",
    "WraWaterLevelAdapter",
    "WraWaterLevelAdapterError",
    "WraWaterLevelApiAdapter",
    "WraWaterLevelFetchError",
    "WraWaterLevelPayloadError",
    "parse_wra_station_metadata_payload",
    "parse_wra_water_level_api_payload",
]
