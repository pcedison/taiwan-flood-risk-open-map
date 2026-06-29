from __future__ import annotations

from types import MappingProxyType

from app.adapters.contracts import AdapterMetadata, SourceFamily
from app.adapters.civil_iot import (
    FLOOD_SENSOR_METADATA,
    GATE_WATER_LEVEL,
    POND_WATER_LEVEL,
    PUMP_WATER_LEVEL,
    RIVER_WATER_LEVEL_METADATA,
    SEWER_WATER_LEVEL,
)
from app.adapters.cwa import CWA_RAINFALL_METADATA, CWA_TIDE_LEVEL_METADATA
from app.adapters.dcard import METADATA as DCARD_METADATA
from app.adapters.flood_potential import FLOOD_POTENTIAL_GEOJSON_METADATA
from app.adapters.local_chiayi_city import (
    CHIAYI_CITY_RAINFALL_METADATA,
    CHIAYI_CITY_WATER_LEVEL_METADATA,
)
from app.adapters.local_chiayi_county import CHIAYI_COUNTY_FLOOD_SENSOR_METADATA
from app.adapters.local_hsinchu_city import (
    HSINCHU_CITY_FLOOD_SENSOR_METADATA,
    HSINCHU_CITY_SEWER_WATER_LEVEL_METADATA,
)
from app.adapters.local_kaohsiung import (
    KAOHSIUNG_FLOOD_SENSOR_METADATA,
    KAOHSIUNG_RAINFALL_METADATA,
    KAOHSIUNG_SEWER_WATER_LEVEL_METADATA,
)
from app.adapters.local_kinmen import KINMEN_KWIS_PUMP_STATION_METADATA
from app.adapters.local_fhy import FHY_LOCAL_FLOOD_SENSOR_SOURCES
from app.adapters.local_keelung import (
    KEELUNG_FLOOD_SENSOR_METADATA,
    KEELUNG_RAINFALL_METADATA,
    KEELUNG_WATER_LEVEL_METADATA,
)
from app.adapters.local_nantou import NANTOU_SEWER_WATER_LEVEL_METADATA
from app.adapters.local_new_taipei import (
    NEW_TAIPEI_DRAINAGE_WATER_LEVEL_METADATA,
    NEW_TAIPEI_FLOOD_SENSOR_METADATA,
    NEW_TAIPEI_RAINFALL_METADATA,
    NEW_TAIPEI_WATER_LEVEL_METADATA,
)
from app.adapters.local_penghu import PENGHU_WATER_LEVEL_METADATA
from app.adapters.local_taichung import TAICHUNG_WATER_LEVEL_METADATA
from app.adapters.local_taipei import (
    TAIPEI_PUMP_STATION,
    TAIPEI_RIVER_WATER_LEVEL,
    TAIPEI_SEWER_WATER_LEVEL,
)
from app.adapters.local_taoyuan import (
    TAOYUAN_FLOOD_SENSOR_METADATA,
    TAOYUAN_RAINFALL_METADATA,
    TAOYUAN_WATER_LEVEL_METADATA,
)
from app.adapters.local_tainan import TAINAN_FLOOD_SENSOR_METADATA
from app.adapters.ncdr import NCDR_CAP_METADATA
from app.adapters.ptt import METADATA as PTT_METADATA
from app.adapters.wra import WRA_WATER_LEVEL_METADATA
from app.adapters.wra_iow import WRA_IOW_FLOOD_DEPTH_METADATA
from app.adapters.local_yunlin import YUNLIN_WATER_LEVEL_METADATA
from app.adapters.local_yilan import YILAN_FLOOD_SENSOR_METADATA, YILAN_WATER_LEVEL_METADATA
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
        CWA_TIDE_LEVEL_METADATA.key: CWA_TIDE_LEVEL_METADATA,
        WRA_WATER_LEVEL_METADATA.key: WRA_WATER_LEVEL_METADATA,
        WRA_IOW_FLOOD_DEPTH_METADATA.key: WRA_IOW_FLOOD_DEPTH_METADATA,
        NCDR_CAP_METADATA.key: NCDR_CAP_METADATA,
        FLOOD_SENSOR_METADATA.key: FLOOD_SENSOR_METADATA,
        RIVER_WATER_LEVEL_METADATA.key: RIVER_WATER_LEVEL_METADATA,
        POND_WATER_LEVEL.metadata.key: POND_WATER_LEVEL.metadata,
        SEWER_WATER_LEVEL.metadata.key: SEWER_WATER_LEVEL.metadata,
        PUMP_WATER_LEVEL.metadata.key: PUMP_WATER_LEVEL.metadata,
        GATE_WATER_LEVEL.metadata.key: GATE_WATER_LEVEL.metadata,
        FLOOD_POTENTIAL_GEOJSON_METADATA.key: FLOOD_POTENTIAL_GEOJSON_METADATA,
        NEW_TAIPEI_WATER_LEVEL_METADATA.key: NEW_TAIPEI_WATER_LEVEL_METADATA,
        NEW_TAIPEI_FLOOD_SENSOR_METADATA.key: NEW_TAIPEI_FLOOD_SENSOR_METADATA,
        NEW_TAIPEI_RAINFALL_METADATA.key: NEW_TAIPEI_RAINFALL_METADATA,
        NEW_TAIPEI_DRAINAGE_WATER_LEVEL_METADATA.key: (
            NEW_TAIPEI_DRAINAGE_WATER_LEVEL_METADATA
        ),
        TAIPEI_SEWER_WATER_LEVEL.metadata.key: TAIPEI_SEWER_WATER_LEVEL.metadata,
        TAIPEI_RIVER_WATER_LEVEL.metadata.key: TAIPEI_RIVER_WATER_LEVEL.metadata,
        TAIPEI_PUMP_STATION.key: TAIPEI_PUMP_STATION,
        TAOYUAN_FLOOD_SENSOR_METADATA.key: TAOYUAN_FLOOD_SENSOR_METADATA,
        TAOYUAN_WATER_LEVEL_METADATA.key: TAOYUAN_WATER_LEVEL_METADATA,
        TAOYUAN_RAINFALL_METADATA.key: TAOYUAN_RAINFALL_METADATA,
        CHIAYI_CITY_WATER_LEVEL_METADATA.key: CHIAYI_CITY_WATER_LEVEL_METADATA,
        CHIAYI_CITY_RAINFALL_METADATA.key: CHIAYI_CITY_RAINFALL_METADATA,
        CHIAYI_COUNTY_FLOOD_SENSOR_METADATA.key: CHIAYI_COUNTY_FLOOD_SENSOR_METADATA,
        HSINCHU_CITY_SEWER_WATER_LEVEL_METADATA.key: HSINCHU_CITY_SEWER_WATER_LEVEL_METADATA,
        HSINCHU_CITY_FLOOD_SENSOR_METADATA.key: HSINCHU_CITY_FLOOD_SENSOR_METADATA,
        KAOHSIUNG_SEWER_WATER_LEVEL_METADATA.key: KAOHSIUNG_SEWER_WATER_LEVEL_METADATA,
        KAOHSIUNG_FLOOD_SENSOR_METADATA.key: KAOHSIUNG_FLOOD_SENSOR_METADATA,
        KAOHSIUNG_RAINFALL_METADATA.key: KAOHSIUNG_RAINFALL_METADATA,
        KEELUNG_WATER_LEVEL_METADATA.key: KEELUNG_WATER_LEVEL_METADATA,
        KEELUNG_FLOOD_SENSOR_METADATA.key: KEELUNG_FLOOD_SENSOR_METADATA,
        KEELUNG_RAINFALL_METADATA.key: KEELUNG_RAINFALL_METADATA,
        NANTOU_SEWER_WATER_LEVEL_METADATA.key: NANTOU_SEWER_WATER_LEVEL_METADATA,
        YUNLIN_WATER_LEVEL_METADATA.key: YUNLIN_WATER_LEVEL_METADATA,
        YILAN_FLOOD_SENSOR_METADATA.key: YILAN_FLOOD_SENSOR_METADATA,
        YILAN_WATER_LEVEL_METADATA.key: YILAN_WATER_LEVEL_METADATA,
        PENGHU_WATER_LEVEL_METADATA.key: PENGHU_WATER_LEVEL_METADATA,
        KINMEN_KWIS_PUMP_STATION_METADATA.key: KINMEN_KWIS_PUMP_STATION_METADATA,
        **{
            source.metadata.key: source.metadata
            for source in FHY_LOCAL_FLOOD_SENSOR_SOURCES
        },
        TAICHUNG_WATER_LEVEL_METADATA.key: TAICHUNG_WATER_LEVEL_METADATA,
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
    if metadata.key == "official.cwa.tide_level":
        return _with_optional_override(metadata.enabled_by_default, settings.source_cwa_enabled)
    if metadata.key == "official.wra.water_level":
        return _with_optional_override(metadata.enabled_by_default, settings.source_wra_enabled)
    if metadata.key == "official.wra_iow.flood_depth":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_wra_iow_flood_depth_enabled,
        )
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
    if metadata.key == "local.new_taipei.water_level":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_new_taipei_water_level_enabled,
        )
    if metadata.key == "local.new_taipei.flood_sensor":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_new_taipei_flood_sensor_enabled,
        )
    if metadata.key == "local.new_taipei.rainfall":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_new_taipei_rainfall_enabled,
        )
    if metadata.key == "local.new_taipei.drainage_water_level":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_new_taipei_drainage_water_level_enabled,
        )
    if metadata.key == "local.taipei.sewer_water_level":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_taipei_sewer_water_level_enabled,
        )
    if metadata.key == "local.taipei.river_water_level":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_taipei_river_water_level_enabled,
        )
    if metadata.key == "local.taipei.pump_station":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_taipei_pump_station_enabled,
        )
    if metadata.key == "local.taoyuan.flood_sensor":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_taoyuan_flood_sensor_enabled,
        )
    if metadata.key == "local.taoyuan.water_level":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_taoyuan_water_level_enabled,
        )
    if metadata.key == "local.taoyuan.rainfall":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_taoyuan_rainfall_enabled,
        )
    if metadata.key == "local.chiayi_city.water_level":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_chiayi_city_water_level_enabled,
        )
    if metadata.key == "local.chiayi_city.rainfall":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_chiayi_city_rainfall_enabled,
        )
    if metadata.key == "local.taichung.water_level":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_taichung_water_level_enabled,
        )
    if metadata.key == "local.hsinchu_city.sewer_water_level":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_hsinchu_city_sewer_water_level_enabled,
        )
    if metadata.key == "local.hsinchu_city.flood_sensor":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_hsinchu_city_flood_sensor_enabled,
        )
    if metadata.key == "local.nantou.sewer_water_level":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_nantou_sewer_water_level_enabled,
        )
    if metadata.key == "local.chiayi_county.flood_sensor":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_chiayi_county_flood_sensor_enabled,
        )
    if metadata.key == "local.kaohsiung.sewer_water_level":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_kaohsiung_sewer_water_level_enabled,
        )
    if metadata.key == "local.kaohsiung.flood_sensor":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_kaohsiung_flood_sensor_enabled,
        )
    if metadata.key == "local.kaohsiung.rainfall":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_kaohsiung_rainfall_enabled,
        )
    if metadata.key == "local.keelung.water_level":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_keelung_water_level_enabled,
        )
    if metadata.key == "local.keelung.flood_sensor":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_keelung_flood_sensor_enabled,
        )
    if metadata.key == "local.keelung.rainfall":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_keelung_rainfall_enabled,
        )
    if metadata.key == "local.yunlin.water_level":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_yunlin_water_level_enabled,
        )
    if metadata.key == "local.yilan.flood_sensor":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_yilan_flood_sensor_enabled,
        )
    if metadata.key == "local.yilan.water_level":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_yilan_water_level_enabled,
        )
    if metadata.key == "local.penghu.water_level":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_penghu_water_level_enabled,
        )
    if metadata.key == "local.kinmen.kwis_pump_station":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_kinmen_kwis_pump_station_enabled,
        )
    if metadata.key == "local.hsinchu_county.flood_sensor":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_hsinchu_county_fhy_flood_sensor_enabled,
        )
    if metadata.key == "local.miaoli.flood_sensor":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_miaoli_fhy_flood_sensor_enabled,
        )
    if metadata.key == "local.changhua.flood_sensor":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_changhua_fhy_flood_sensor_enabled,
        )
    if metadata.key == "local.pingtung.flood_sensor":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_pingtung_fhy_flood_sensor_enabled,
        )
    if metadata.key == "local.hualien.flood_sensor":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_hualien_fhy_flood_sensor_enabled,
        )
    if metadata.key == "local.taitung.flood_sensor":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_taitung_fhy_flood_sensor_enabled,
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
    if metadata.key == "official.civil_iot.gate_water_level":
        return _with_optional_override(
            metadata.enabled_by_default,
            settings.source_civil_iot_gate_enabled,
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
    if metadata.key == "official.cwa.tide_level":
        return settings.source_cwa_enabled is not False
    if metadata.key == "official.wra.water_level":
        return settings.source_wra_enabled is not False
    if metadata.key == "official.wra_iow.flood_depth":
        return settings.source_wra_iow_flood_depth_enabled is True
    if metadata.key == "official.ncdr.cap":
        return settings.source_ncdr_cap_enabled is True
    if metadata.key == "official.flood_potential.geojson":
        return settings.source_flood_potential_enabled is not False
    if metadata.key == "official.civil_iot.flood_sensor":
        return settings.source_flood_sensor_enabled is True
    if metadata.key == "local.tainan.flood_sensor":
        return settings.source_tainan_flood_sensor_enabled is True
    if metadata.key == "local.new_taipei.water_level":
        return settings.source_new_taipei_water_level_enabled is True
    if metadata.key == "local.new_taipei.flood_sensor":
        return settings.source_new_taipei_flood_sensor_enabled is True
    if metadata.key == "local.new_taipei.rainfall":
        return settings.source_new_taipei_rainfall_enabled is True
    if metadata.key == "local.new_taipei.drainage_water_level":
        return settings.source_new_taipei_drainage_water_level_enabled is True
    if metadata.key == "local.taipei.sewer_water_level":
        return settings.source_taipei_sewer_water_level_enabled is True
    if metadata.key == "local.taipei.river_water_level":
        return settings.source_taipei_river_water_level_enabled is True
    if metadata.key == "local.taipei.pump_station":
        return settings.source_taipei_pump_station_enabled is True
    if metadata.key == "local.taoyuan.flood_sensor":
        return settings.source_taoyuan_flood_sensor_enabled is True
    if metadata.key == "local.taoyuan.water_level":
        return settings.source_taoyuan_water_level_enabled is True
    if metadata.key == "local.taoyuan.rainfall":
        return settings.source_taoyuan_rainfall_enabled is True
    if metadata.key == "local.chiayi_city.water_level":
        return settings.source_chiayi_city_water_level_enabled is True
    if metadata.key == "local.chiayi_city.rainfall":
        return settings.source_chiayi_city_rainfall_enabled is True
    if metadata.key == "local.taichung.water_level":
        return settings.source_taichung_water_level_enabled is True
    if metadata.key == "local.hsinchu_city.sewer_water_level":
        return settings.source_hsinchu_city_sewer_water_level_enabled is True
    if metadata.key == "local.hsinchu_city.flood_sensor":
        return settings.source_hsinchu_city_flood_sensor_enabled is True
    if metadata.key == "local.nantou.sewer_water_level":
        return settings.source_nantou_sewer_water_level_enabled is True
    if metadata.key == "local.chiayi_county.flood_sensor":
        return settings.source_chiayi_county_flood_sensor_enabled is True
    if metadata.key == "local.kaohsiung.sewer_water_level":
        return settings.source_kaohsiung_sewer_water_level_enabled is True
    if metadata.key == "local.kaohsiung.flood_sensor":
        return settings.source_kaohsiung_flood_sensor_enabled is True
    if metadata.key == "local.kaohsiung.rainfall":
        return settings.source_kaohsiung_rainfall_enabled is True
    if metadata.key == "local.keelung.water_level":
        return settings.source_keelung_water_level_enabled is True
    if metadata.key == "local.keelung.flood_sensor":
        return settings.source_keelung_flood_sensor_enabled is True
    if metadata.key == "local.keelung.rainfall":
        return settings.source_keelung_rainfall_enabled is True
    if metadata.key == "local.yunlin.water_level":
        return settings.source_yunlin_water_level_enabled is True
    if metadata.key == "local.yilan.flood_sensor":
        return settings.source_yilan_flood_sensor_enabled is True
    if metadata.key == "local.yilan.water_level":
        return settings.source_yilan_water_level_enabled is True
    if metadata.key == "local.penghu.water_level":
        return settings.source_penghu_water_level_enabled is True
    if metadata.key == "local.kinmen.kwis_pump_station":
        return settings.source_kinmen_kwis_pump_station_enabled is True
    if metadata.key == "local.hsinchu_county.flood_sensor":
        return settings.source_hsinchu_county_fhy_flood_sensor_enabled is True
    if metadata.key == "local.miaoli.flood_sensor":
        return settings.source_miaoli_fhy_flood_sensor_enabled is True
    if metadata.key == "local.changhua.flood_sensor":
        return settings.source_changhua_fhy_flood_sensor_enabled is True
    if metadata.key == "local.pingtung.flood_sensor":
        return settings.source_pingtung_fhy_flood_sensor_enabled is True
    if metadata.key == "local.hualien.flood_sensor":
        return settings.source_hualien_fhy_flood_sensor_enabled is True
    if metadata.key == "local.taitung.flood_sensor":
        return settings.source_taitung_fhy_flood_sensor_enabled is True
    if metadata.key == "official.civil_iot.river_water_level":
        return settings.source_civil_iot_river_enabled is True
    if metadata.key == "official.civil_iot.pond_water_level":
        return settings.source_civil_iot_pond_enabled is True
    if metadata.key == "official.civil_iot.sewer_water_level":
        return settings.source_civil_iot_sewer_enabled is True
    if metadata.key == "official.civil_iot.pump_water_level":
        return settings.source_civil_iot_pump_enabled is True
    if metadata.key == "official.civil_iot.gate_water_level":
        return settings.source_civil_iot_gate_enabled is True
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
