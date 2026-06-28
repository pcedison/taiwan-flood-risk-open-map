"""Civil IoT Taiwan (ci.taiwan.gov.tw) SensorThings-based official adapters."""

from app.adapters.civil_iot.flood_sensor import (
    FLOOD_SENSOR_METADATA,
    FLOOD_SENSOR_MIN_DEPTH_CM,
    FLOOD_SENSOR_STA_URL,
    FloodSensorAdapter,
    FloodSensorAdapterError,
    FloodSensorStaApiAdapter,
)
from app.adapters.civil_iot.river_water_level import (
    RIVER_WATER_LEVEL_METADATA,
    RIVER_WATER_LEVEL_STA_URL,
    CivilIotRiverAdapter,
    CivilIotRiverAdapterError,
    CivilIotRiverApiAdapter,
)
from app.adapters.civil_iot.sta_client import (
    DEFAULT_STA_TIMEOUT_SECONDS,
    STA_RAIN_SEWER_BASE,
    STA_WATER_RESOURCE_BASE,
    CivilIotStaError,
    CivilIotStaFetchError,
    CivilIotStaPayloadError,
    StaFetchJson,
    fetch_sta_json,
    parse_sta_things_payload,
)
from app.adapters.civil_iot.sta_water_level import (
    GATE_WATER_LEVEL,
    POND_WATER_LEVEL,
    PUMP_WATER_LEVEL,
    SEWER_WATER_LEVEL,
    StaWaterLevelAdapter,
    StaWaterLevelApiAdapter,
    StaWaterLevelSource,
)

__all__ = [
    "DEFAULT_STA_TIMEOUT_SECONDS",
    "STA_RAIN_SEWER_BASE",
    "STA_WATER_RESOURCE_BASE",
    "CivilIotStaError",
    "CivilIotStaFetchError",
    "CivilIotStaPayloadError",
    "StaFetchJson",
    "fetch_sta_json",
    "parse_sta_things_payload",
    "FLOOD_SENSOR_METADATA",
    "FLOOD_SENSOR_MIN_DEPTH_CM",
    "FLOOD_SENSOR_STA_URL",
    "FloodSensorAdapter",
    "FloodSensorAdapterError",
    "FloodSensorStaApiAdapter",
    "RIVER_WATER_LEVEL_METADATA",
    "RIVER_WATER_LEVEL_STA_URL",
    "CivilIotRiverAdapter",
    "CivilIotRiverAdapterError",
    "CivilIotRiverApiAdapter",
    "GATE_WATER_LEVEL",
    "POND_WATER_LEVEL",
    "PUMP_WATER_LEVEL",
    "SEWER_WATER_LEVEL",
    "StaWaterLevelAdapter",
    "StaWaterLevelApiAdapter",
    "StaWaterLevelSource",
]
