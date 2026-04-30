"""CWA adapters."""

from app.adapters.cwa.rainfall import (
    CWA_RAINFALL_API_URL,
    DEFAULT_CWA_RAINFALL_TIMEOUT_SECONDS,
    CwaRainfallAdapter,
    CwaRainfallApiAdapter,
    CwaRainfallAdapterError,
    CwaRainfallConfigurationError,
    CwaRainfallFetchError,
    CwaRainfallPayloadError,
    FetchJson,
    parse_cwa_rainfall_api_payload,
)

__all__ = [
    "CWA_RAINFALL_API_URL",
    "DEFAULT_CWA_RAINFALL_TIMEOUT_SECONDS",
    "CwaRainfallAdapter",
    "CwaRainfallApiAdapter",
    "CwaRainfallAdapterError",
    "CwaRainfallConfigurationError",
    "CwaRainfallFetchError",
    "CwaRainfallPayloadError",
    "FetchJson",
    "parse_cwa_rainfall_api_payload",
]
