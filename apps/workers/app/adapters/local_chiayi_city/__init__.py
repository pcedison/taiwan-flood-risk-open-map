"""Chiayi City local official water adapters."""

from app.adapters.local_chiayi_city.water import (
    CHIAYI_CITY_RAINFALL_API_URL,
    CHIAYI_CITY_RAINFALL_DATA_URL,
    CHIAYI_CITY_RAINFALL_METADATA,
    CHIAYI_CITY_WATER_LEVEL_API_URL,
    CHIAYI_CITY_WATER_LEVEL_DATA_URL,
    CHIAYI_CITY_WATER_LEVEL_METADATA,
    DEFAULT_CHIAYI_CITY_WATER_TIMEOUT_SECONDS,
    ChiayiCityRainfallApiAdapter,
    ChiayiCityWaterAdapterError,
    ChiayiCityWaterFetchError,
    ChiayiCityWaterLevelApiAdapter,
    ChiayiCityWaterPayloadError,
    FetchText,
    fetch_chiayi_city_text,
    parse_chiayi_city_rainfall_csv,
    parse_chiayi_city_water_level_csv,
)

__all__ = [
    "CHIAYI_CITY_RAINFALL_API_URL",
    "CHIAYI_CITY_RAINFALL_DATA_URL",
    "CHIAYI_CITY_RAINFALL_METADATA",
    "CHIAYI_CITY_WATER_LEVEL_API_URL",
    "CHIAYI_CITY_WATER_LEVEL_DATA_URL",
    "CHIAYI_CITY_WATER_LEVEL_METADATA",
    "DEFAULT_CHIAYI_CITY_WATER_TIMEOUT_SECONDS",
    "ChiayiCityRainfallApiAdapter",
    "ChiayiCityWaterAdapterError",
    "ChiayiCityWaterFetchError",
    "ChiayiCityWaterLevelApiAdapter",
    "ChiayiCityWaterPayloadError",
    "FetchText",
    "fetch_chiayi_city_text",
    "parse_chiayi_city_rainfall_csv",
    "parse_chiayi_city_water_level_csv",
]
