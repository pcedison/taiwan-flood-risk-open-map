"""Yunlin County local official water adapters."""

from app.adapters.local_yunlin.water import (
    DEFAULT_YUNLIN_WATER_TIMEOUT_SECONDS,
    YUNLIN_DATA_URL,
    YUNLIN_STATIONS_API_URL,
    YUNLIN_WATER_LEVEL_METADATA,
    FetchJson,
    YunlinWaterAdapterError,
    YunlinWaterFetchError,
    YunlinWaterLevelApiAdapter,
    YunlinWaterPayloadError,
    fetch_yunlin_json,
    parse_yunlin_water_level_payload,
)

__all__ = [
    "DEFAULT_YUNLIN_WATER_TIMEOUT_SECONDS",
    "YUNLIN_DATA_URL",
    "YUNLIN_STATIONS_API_URL",
    "YUNLIN_WATER_LEVEL_METADATA",
    "FetchJson",
    "YunlinWaterAdapterError",
    "YunlinWaterFetchError",
    "YunlinWaterLevelApiAdapter",
    "YunlinWaterPayloadError",
    "fetch_yunlin_json",
    "parse_yunlin_water_level_payload",
]
