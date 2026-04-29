from __future__ import annotations

from types import MappingProxyType

from app.adapters.contracts import AdapterMetadata, SourceFamily


ADAPTER_REGISTRY = MappingProxyType(
    {
        "news.public_web.sample": AdapterMetadata(
            key="news.public_web.sample",
            family=SourceFamily.NEWS,
            enabled_by_default=False,
            display_name="Sample news/public web adapter",
        ),
        "news.public_web.gdelt_backfill": AdapterMetadata(
            key="news.public_web.gdelt_backfill",
            family=SourceFamily.NEWS,
            enabled_by_default=False,
            display_name="GDELT public-news historical flood backfill adapter",
            terms_review_required=True,
        ),
        "official.cwa.rainfall": AdapterMetadata(
            key="official.cwa.rainfall",
            family=SourceFamily.OFFICIAL,
            enabled_by_default=True,
            display_name="CWA rainfall observation adapter",
        ),
        "official.wra.water_level": AdapterMetadata(
            key="official.wra.water_level",
            family=SourceFamily.OFFICIAL,
            enabled_by_default=True,
            display_name="WRA water level observation adapter",
        ),
        "official.flood_potential.geojson": AdapterMetadata(
            key="official.flood_potential.geojson",
            family=SourceFamily.OFFICIAL,
            enabled_by_default=True,
            display_name="Flood potential GeoJSON import adapter",
        ),
        "ptt": AdapterMetadata(
            key="ptt",
            family=SourceFamily.FORUM,
            enabled_by_default=False,
            display_name="PTT adapter placeholder",
            terms_review_required=True,
        ),
        "dcard": AdapterMetadata(
            key="dcard",
            family=SourceFamily.FORUM,
            enabled_by_default=False,
            display_name="Dcard adapter placeholder",
            terms_review_required=True,
        ),
    }
)


def enabled_adapter_keys() -> tuple[str, ...]:
    return tuple(key for key, metadata in ADAPTER_REGISTRY.items() if metadata.enabled_by_default)
