"""Penghu County local official water adapters."""

from app.adapters.local_penghu.water import (
    DEFAULT_PENGHU_WATER_TIMEOUT_SECONDS,
    PENGHU_DATA_URL,
    PENGHU_WATER_LEVEL_LAYER_URL,
    PENGHU_WATER_LEVEL_METADATA,
    FetchJson,
    PenghuWaterAdapterError,
    PenghuWaterFetchError,
    PenghuWaterLevelArcgisAdapter,
    PenghuWaterPayloadError,
    fetch_penghu_json,
    parse_penghu_water_level_layer,
)

__all__ = [
    "DEFAULT_PENGHU_WATER_TIMEOUT_SECONDS",
    "PENGHU_DATA_URL",
    "PENGHU_WATER_LEVEL_LAYER_URL",
    "PENGHU_WATER_LEVEL_METADATA",
    "FetchJson",
    "PenghuWaterAdapterError",
    "PenghuWaterFetchError",
    "PenghuWaterLevelArcgisAdapter",
    "PenghuWaterPayloadError",
    "fetch_penghu_json",
    "parse_penghu_water_level_layer",
]
