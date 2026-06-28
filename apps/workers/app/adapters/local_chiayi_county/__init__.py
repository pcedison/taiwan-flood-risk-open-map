"""Chiayi County local official water adapters."""

from app.adapters.local_chiayi_county.water import (
    CHIAYI_COUNTY_FLOOD_SENSOR_API_URL,
    CHIAYI_COUNTY_FLOOD_SENSOR_DATA_URL,
    CHIAYI_COUNTY_FLOOD_SENSOR_METADATA,
    DEFAULT_CHIAYI_COUNTY_WATER_TIMEOUT_SECONDS,
    FetchJson,
    ChiayiCountyFloodSensorApiAdapter,
    ChiayiCountyWaterAdapterError,
    ChiayiCountyWaterFetchError,
    ChiayiCountyWaterPayloadError,
    fetch_chiayi_county_json,
    parse_chiayi_county_flood_sensor_payload,
)

__all__ = [
    "CHIAYI_COUNTY_FLOOD_SENSOR_API_URL",
    "CHIAYI_COUNTY_FLOOD_SENSOR_DATA_URL",
    "CHIAYI_COUNTY_FLOOD_SENSOR_METADATA",
    "DEFAULT_CHIAYI_COUNTY_WATER_TIMEOUT_SECONDS",
    "FetchJson",
    "ChiayiCountyFloodSensorApiAdapter",
    "ChiayiCountyWaterAdapterError",
    "ChiayiCountyWaterFetchError",
    "ChiayiCountyWaterPayloadError",
    "fetch_chiayi_county_json",
    "parse_chiayi_county_flood_sensor_payload",
]
