"""Kaohsiung local official water adapters."""

from app.adapters.local_kaohsiung.water import (
    DEFAULT_KAOHSIUNG_WATER_TIMEOUT_SECONDS,
    KAOHSIUNG_DATA_URL,
    KAOHSIUNG_FLOOD_SENSOR_API_URL,
    KAOHSIUNG_FLOOD_SENSOR_METADATA,
    KAOHSIUNG_SEWER_WATER_LEVEL_API_URL,
    KAOHSIUNG_SEWER_WATER_LEVEL_METADATA,
    FetchJson,
    KaohsiungFloodSensorApiAdapter,
    KaohsiungSewerWaterLevelApiAdapter,
    KaohsiungWaterAdapterError,
    KaohsiungWaterFetchError,
    KaohsiungWaterPayloadError,
    fetch_kaohsiung_json,
    parse_kaohsiung_flood_sensor_payload,
    parse_kaohsiung_sewer_water_level_payload,
)

__all__ = [
    "DEFAULT_KAOHSIUNG_WATER_TIMEOUT_SECONDS",
    "KAOHSIUNG_DATA_URL",
    "KAOHSIUNG_FLOOD_SENSOR_API_URL",
    "KAOHSIUNG_FLOOD_SENSOR_METADATA",
    "KAOHSIUNG_SEWER_WATER_LEVEL_API_URL",
    "KAOHSIUNG_SEWER_WATER_LEVEL_METADATA",
    "FetchJson",
    "KaohsiungFloodSensorApiAdapter",
    "KaohsiungSewerWaterLevelApiAdapter",
    "KaohsiungWaterAdapterError",
    "KaohsiungWaterFetchError",
    "KaohsiungWaterPayloadError",
    "fetch_kaohsiung_json",
    "parse_kaohsiung_flood_sensor_payload",
    "parse_kaohsiung_sewer_water_level_payload",
]
