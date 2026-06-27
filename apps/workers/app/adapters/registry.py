from __future__ import annotations

from types import MappingProxyType

from app.adapters.contracts import AdapterMetadata, SourceFamily
from app.adapters.civil_iot import (
    FLOOD_SENSOR_METADATA,
    POND_WATER_LEVEL,
    PUMP_WATER_LEVEL,
    RIVER_WATER_LEVEL_METADATA,
    SEWER_WATER_LEVEL,
)
from app.adapters.cwa import CWA_RAINFALL_METADATA
from app.adapters.dcard import METADATA as DCARD_METADATA
from app.adapters.flood_potential import FLOOD_POTENTIAL_GEOJSON_METADATA
from app.adapters.local_tainan import TAINAN_FLOOD_SENSOR_METADATA
from app.adapters.ncdr import NCDR_CAP_METADATA
from app.adapters.ptt import METADATA as PTT_METADATA
from app.adapters.wra import WRA_WATER_LEVEL_METADATA
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
        CWA_RAINFALL_METADATA.key: CWA_RAINFALL_METADATA,
        WRA_WATER_LEVEL_METADATA.key: WRA_WATER_LEVEL_METADATA,
        NCDR_CAP_METADATA.key: NCDR_CAP_METADATA,
        FLOOD_SENSOR_METADATA.key: FLOOD_SENSOR_METADATA,
        RIVER_WATER_LEVEL_METADATA.key: RIVER_WATER_LEVEL_METADATA,
        POND_WATER_LEVEL.metadata.key: POND_WATER_LEVEL.metadata,
        SEWER_WATER_LEVEL.metadata.key: SEWER_WATER_LEVEL.metadata,
        PUMP_WATER_LEVEL.metadata.key: PUMP_WATER_LEVEL.metadata,
        FLOOD_POTENTIAL_GEOJSON_METADATA.key: FLOOD_POTENTIAL_GEOJSON_METADATA,
        TAINAN_FLOOD_SENSOR_METADATA.key: TAINAN_FLOOD_SENSOR_METADATA,
        PTT_METADATA.key: PTT_METADATA,
        DCARD_METADATA.key: DCARD_METADATA,
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
    if metadata.key == "official.ncdr.cap":
        return _with_optional_override(metadata.enabled_by_default, settings.source_ncdr_cap_enabled)
    if metadata.key == "official.flood_potential.geojson":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_flood_potential_enabled,
        )
    if metadata.key == "official.civil_iot.flood_sensor":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_flood_sensor_enabled,
        )
    if metadata.key == "local.tainan.flood_sensor":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_tainan_flood_sensor_enabled,
        )
    if metadata.key == "official.civil_iot.river_water_level":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_civil_iot_river_enabled,
        )
    if metadata.key == "official.civil_iot.pond_water_level":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_civil_iot_pond_enabled,
        )
    if metadata.key == "official.civil_iot.sewer_water_level":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_civil_iot_sewer_enabled,
        )
    if metadata.key == "official.civil_iot.pump_water_level":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_civil_iot_pump_enabled,
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
    if _is_reviewed_news_adapter(metadata) and settings.source_news_enabled is not True:
        return False
    if metadata.terms_review_required and not settings.source_terms_review_ack:
        return False
    if metadata.family is SourceFamily.FORUM and not _forum_candidate_approval_ack(
        metadata,
        settings,
    ):
        return False
    return True


def _legacy_flag_allows_adapter(metadata: AdapterMetadata, settings: WorkerSettings) -> bool:
    if metadata.key == "official.cwa.rainfall":
        return settings.source_cwa_enabled is not False
    if metadata.key == "official.wra.water_level":
        return settings.source_wra_enabled is not False
    if metadata.key == "official.ncdr.cap":
        return settings.source_ncdr_cap_enabled is not False
    if metadata.key == "official.flood_potential.geojson":
        return settings.source_flood_potential_enabled is not False
    if metadata.key == "official.civil_iot.flood_sensor":
        return settings.source_flood_sensor_enabled is not False
    if metadata.key == "local.tainan.flood_sensor":
        return settings.source_tainan_flood_sensor_enabled is True
    if metadata.key == "official.civil_iot.river_water_level":
        return settings.source_civil_iot_river_enabled is not False
    if metadata.key == "official.civil_iot.pond_water_level":
        return settings.source_civil_iot_pond_enabled is not False
    if metadata.key == "official.civil_iot.sewer_water_level":
        return settings.source_civil_iot_sewer_enabled is not False
    if metadata.key == "official.civil_iot.pump_water_level":
        return settings.source_civil_iot_pump_enabled is not False
    if metadata.key == "ptt":
        return settings.source_forum_enabled is True and settings.source_ptt_enabled is True
    if metadata.key == "dcard":
        return settings.source_forum_enabled is True and settings.source_dcard_enabled is True
    if metadata.family is SourceFamily.NEWS:
        return settings.source_news_enabled is True or _is_sample_adapter(metadata)
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


def _is_reviewed_news_adapter(metadata: AdapterMetadata) -> bool:
    return metadata.family is SourceFamily.NEWS and metadata.terms_review_required


def _forum_candidate_approval_ack(metadata: AdapterMetadata, settings: WorkerSettings) -> bool:
    if metadata.key == "ptt":
        return settings.source_ptt_candidate_approval_ack
    if metadata.key == "dcard":
        return settings.source_dcard_candidate_approval_ack
    return False
