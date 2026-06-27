"""Tainan local-government open-data adapters."""

from app.adapters.local_tainan.flood_sensor import (
    DEFAULT_TAINAN_FLOOD_SENSOR_TIMEOUT_SECONDS,
    TAINAN_FLOOD_SENSOR_API_URL,
    TAINAN_FLOOD_SENSOR_DATA_GOV_URL,
    TAINAN_FLOOD_SENSOR_METADATA,
    TAINAN_FLOOD_SENSOR_METADATA_API_URL,
    FetchJson,
    TainanFloodSensorAdapterError,
    TainanFloodSensorApiAdapter,
    TainanFloodSensorFetchError,
    TainanFloodSensorPayloadError,
    parse_tainan_flood_sensor_metadata_payload,
    parse_tainan_flood_sensor_realtime_payload,
)

__all__ = [
    "DEFAULT_TAINAN_FLOOD_SENSOR_TIMEOUT_SECONDS",
    "TAINAN_FLOOD_SENSOR_API_URL",
    "TAINAN_FLOOD_SENSOR_DATA_GOV_URL",
    "TAINAN_FLOOD_SENSOR_METADATA",
    "TAINAN_FLOOD_SENSOR_METADATA_API_URL",
    "FetchJson",
    "TainanFloodSensorAdapterError",
    "TainanFloodSensorApiAdapter",
    "TainanFloodSensorFetchError",
    "TainanFloodSensorPayloadError",
    "parse_tainan_flood_sensor_metadata_payload",
    "parse_tainan_flood_sensor_realtime_payload",
]
