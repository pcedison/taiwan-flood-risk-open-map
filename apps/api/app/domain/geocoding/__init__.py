"""Taiwan geocoding helpers."""

from app.domain.geocoding.providers import (
    FileBackedTaiwanOpenDataProvider,
    GeocoderChain,
    LocalTaiwanAddressProvider,
    NominatimDevelopmentFallbackProvider,
    OpenStreetMapProvider,
    TaiwanAdminFallbackProvider,
    WikimediaPoiFallbackProvider,
    admin_context_matches_query,
    build_open_data_geocoder,
    candidate_type_for_precision,
    geocode_limitations,
    nominatim_precision,
    requires_geocode_confirmation,
    stable_uuid,
    within_taiwan_bounds,
)
from app.domain.geocoding.taiwan import (
    build_taiwan_geocode_queries,
    extract_taiwan_search_location,
)

__all__ = [
    "FileBackedTaiwanOpenDataProvider",
    "GeocoderChain",
    "LocalTaiwanAddressProvider",
    "NominatimDevelopmentFallbackProvider",
    "OpenStreetMapProvider",
    "TaiwanAdminFallbackProvider",
    "WikimediaPoiFallbackProvider",
    "admin_context_matches_query",
    "build_open_data_geocoder",
    "build_taiwan_geocode_queries",
    "candidate_type_for_precision",
    "extract_taiwan_search_location",
    "geocode_limitations",
    "nominatim_precision",
    "requires_geocode_confirmation",
    "stable_uuid",
    "within_taiwan_bounds",
]
