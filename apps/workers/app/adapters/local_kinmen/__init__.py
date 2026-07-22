"""Kinmen County local official water adapters."""

from app.adapters.local_kinmen.kwis import (
    DEFAULT_KINMEN_KWIS_TIMEOUT_SECONDS,
    KINMEN_KWIS_DATA_URL,
    KINMEN_KWIS_PUMP_STATION_API_URL,
    KINMEN_KWIS_PUMP_STATION_METADATA,
    KINMEN_KWIS_SERVICE_ROOT,
    FetchText,
    KinmenKwisAdapterError,
    KinmenKwisAuthorizationError,
    KinmenKwisFetchError,
    KinmenKwisPayloadError,
    KinmenKwisPumpStationApiAdapter,
    fetch_kinmen_kwis_text,
    parse_kinmen_kwis_pump_payload,
)

__all__ = [
    "DEFAULT_KINMEN_KWIS_TIMEOUT_SECONDS",
    "KINMEN_KWIS_DATA_URL",
    "KINMEN_KWIS_PUMP_STATION_API_URL",
    "KINMEN_KWIS_PUMP_STATION_METADATA",
    "KINMEN_KWIS_SERVICE_ROOT",
    "FetchText",
    "KinmenKwisAdapterError",
    "KinmenKwisAuthorizationError",
    "KinmenKwisFetchError",
    "KinmenKwisPayloadError",
    "KinmenKwisPumpStationApiAdapter",
    "fetch_kinmen_kwis_text",
    "parse_kinmen_kwis_pump_payload",
]
