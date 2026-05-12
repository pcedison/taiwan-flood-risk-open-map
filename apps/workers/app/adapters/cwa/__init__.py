"""CWA adapters."""

from app.adapters.cwa.rainfall import (
    CWA_RAINFALL_API_URL,
    CWA_RAINFALL_DATA_GOV_DATASET_ID,
    CWA_RAINFALL_DATA_GOV_URL,
    CWA_RAINFALL_METADATA,
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
    "CWA_RAINFALL_DATA_GOV_DATASET_ID",
    "CWA_RAINFALL_DATA_GOV_URL",
    "CWA_RAINFALL_METADATA",
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
