from __future__ import annotations

from types import MappingProxyType

from app.adapters.contracts import AdapterMetadata, SourceFamily
from app.config import WorkerSettings, load_worker_settings


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


def enabled_adapter_keys(settings: WorkerSettings | None = None) -> tuple[str, ...]:
    resolved_settings = settings or load_worker_settings()
    configured_keys = resolved_settings.enabled_adapter_keys
    if configured_keys is not None:
        _validate_configured_adapter_keys(configured_keys)
        return tuple(
            key
            for key in configured_keys
            if _adapter_passes_hard_gates(ADAPTER_REGISTRY[key], resolved_settings)
            and _legacy_flag_allows_adapter(ADAPTER_REGISTRY[key], resolved_settings)
        )

    return tuple(
        key
        for key, metadata in ADAPTER_REGISTRY.items()
        if adapter_is_enabled(metadata, resolved_settings)
    )


def adapter_is_enabled(metadata: AdapterMetadata, settings: WorkerSettings) -> bool:
    if not _adapter_passes_hard_gates(metadata, settings):
        return False

    if metadata.key == "official.cwa.rainfall":
        return _with_optional_override(metadata.enabled_by_default, settings.source_cwa_enabled)
    if metadata.key == "official.wra.water_level":
        return _with_optional_override(metadata.enabled_by_default, settings.source_wra_enabled)
    if metadata.key == "official.flood_potential.geojson":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_flood_potential_enabled,
        )
    if metadata.key == "ptt":
        return settings.source_forum_enabled is True and settings.source_ptt_enabled is True
    if metadata.key == "dcard":
        return settings.source_forum_enabled is True and settings.source_dcard_enabled is True
    if metadata.family is SourceFamily.NEWS:
        return settings.source_news_enabled is True

    return metadata.enabled_by_default


def _adapter_passes_hard_gates(metadata: AdapterMetadata, settings: WorkerSettings) -> bool:
    if _is_sample_adapter(metadata) and not settings.source_sample_data_enabled:
        return False
    if metadata.terms_review_required and not settings.source_terms_review_ack:
        return False
    return True


def _legacy_flag_allows_adapter(metadata: AdapterMetadata, settings: WorkerSettings) -> bool:
    if metadata.key == "official.cwa.rainfall":
        return settings.source_cwa_enabled is not False
    if metadata.key == "official.wra.water_level":
        return settings.source_wra_enabled is not False
    if metadata.key == "official.flood_potential.geojson":
        return settings.source_flood_potential_enabled is not False
    if metadata.key == "ptt":
        return (
            settings.source_forum_enabled is not False
            and settings.source_ptt_enabled is not False
        )
    if metadata.key == "dcard":
        return (
            settings.source_forum_enabled is not False
            and settings.source_dcard_enabled is not False
        )
    if metadata.family is SourceFamily.NEWS:
        return settings.source_news_enabled is not False
    return True


def _validate_configured_adapter_keys(configured_keys: tuple[str, ...]) -> None:
    unknown_keys = tuple(key for key in configured_keys if key not in ADAPTER_REGISTRY)
    if unknown_keys:
        formatted = ", ".join(sorted(unknown_keys))
        raise ValueError(f"Unknown WORKER_ENABLED_ADAPTER_KEYS adapter key(s): {formatted}")


def _with_optional_override(default: bool, override: bool | None) -> bool:
    return default if override is None else override


def _is_sample_adapter(metadata: AdapterMetadata) -> bool:
    return metadata.key.endswith(".sample")
