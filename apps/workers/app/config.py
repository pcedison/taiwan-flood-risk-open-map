from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
FALSE_VALUES = frozenset({"0", "false", "no", "off"})


@dataclass(frozen=True)
class WorkerSettings:
    database_url: str | None
    source_cwa_enabled: bool | None
    source_cwa_api_enabled: bool
    source_wra_enabled: bool | None
    source_wra_api_enabled: bool
    source_wra_iow_flood_depth_enabled: bool | None
    source_wra_iow_flood_depth_api_enabled: bool
    source_ncdr_cap_enabled: bool | None
    source_ncdr_cap_api_enabled: bool
    source_flood_potential_enabled: bool | None
    source_flood_potential_geojson_enabled: bool
    source_flood_sensor_enabled: bool | None
    source_flood_sensor_api_enabled: bool
    source_flood_sensor_use_live: bool
    source_tainan_flood_sensor_enabled: bool | None
    source_tainan_flood_sensor_api_enabled: bool
    source_new_taipei_water_level_enabled: bool | None
    source_new_taipei_water_level_api_enabled: bool
    source_new_taipei_flood_sensor_enabled: bool | None
    source_new_taipei_flood_sensor_api_enabled: bool
    source_new_taipei_rainfall_enabled: bool | None
    source_new_taipei_rainfall_api_enabled: bool
    source_new_taipei_drainage_water_level_enabled: bool | None
    source_new_taipei_drainage_water_level_api_enabled: bool
    source_taipei_sewer_water_level_enabled: bool | None
    source_taipei_sewer_water_level_api_enabled: bool
    source_taipei_river_water_level_enabled: bool | None
    source_taipei_river_water_level_api_enabled: bool
    source_taipei_pump_station_enabled: bool | None
    source_taipei_pump_station_api_enabled: bool
    source_taoyuan_flood_sensor_enabled: bool | None
    source_taoyuan_flood_sensor_api_enabled: bool
    source_taoyuan_water_level_enabled: bool | None
    source_taoyuan_water_level_api_enabled: bool
    source_taoyuan_rainfall_enabled: bool | None
    source_taoyuan_rainfall_api_enabled: bool
    source_chiayi_city_water_level_enabled: bool | None
    source_chiayi_city_water_level_api_enabled: bool
    source_chiayi_city_rainfall_enabled: bool | None
    source_chiayi_city_rainfall_api_enabled: bool
    source_taichung_water_level_enabled: bool | None
    source_taichung_water_level_api_enabled: bool
    source_hsinchu_city_sewer_water_level_enabled: bool | None
    source_hsinchu_city_sewer_water_level_api_enabled: bool
    source_hsinchu_city_flood_sensor_enabled: bool | None
    source_hsinchu_city_flood_sensor_api_enabled: bool
    source_nantou_sewer_water_level_enabled: bool | None
    source_nantou_sewer_water_level_api_enabled: bool
    source_chiayi_county_flood_sensor_enabled: bool | None
    source_chiayi_county_flood_sensor_api_enabled: bool
    source_kaohsiung_sewer_water_level_enabled: bool | None
    source_kaohsiung_sewer_water_level_api_enabled: bool
    source_kaohsiung_flood_sensor_enabled: bool | None
    source_kaohsiung_flood_sensor_api_enabled: bool
    source_kaohsiung_rainfall_enabled: bool | None
    source_kaohsiung_rainfall_api_enabled: bool
    source_keelung_water_level_enabled: bool | None
    source_keelung_water_level_api_enabled: bool
    source_keelung_flood_sensor_enabled: bool | None
    source_keelung_flood_sensor_api_enabled: bool
    source_keelung_rainfall_enabled: bool | None
    source_keelung_rainfall_api_enabled: bool
    source_yunlin_water_level_enabled: bool | None
    source_yunlin_water_level_api_enabled: bool
    source_yilan_flood_sensor_enabled: bool | None
    source_yilan_flood_sensor_api_enabled: bool
    source_yilan_water_level_enabled: bool | None
    source_yilan_water_level_api_enabled: bool
    source_penghu_water_level_enabled: bool | None
    source_penghu_water_level_api_enabled: bool
    source_hsinchu_county_fhy_flood_sensor_enabled: bool | None
    source_hsinchu_county_fhy_flood_sensor_api_enabled: bool
    source_miaoli_fhy_flood_sensor_enabled: bool | None
    source_miaoli_fhy_flood_sensor_api_enabled: bool
    source_changhua_fhy_flood_sensor_enabled: bool | None
    source_changhua_fhy_flood_sensor_api_enabled: bool
    source_pingtung_fhy_flood_sensor_enabled: bool | None
    source_pingtung_fhy_flood_sensor_api_enabled: bool
    source_hualien_fhy_flood_sensor_enabled: bool | None
    source_hualien_fhy_flood_sensor_api_enabled: bool
    source_taitung_fhy_flood_sensor_enabled: bool | None
    source_taitung_fhy_flood_sensor_api_enabled: bool
    source_civil_iot_river_enabled: bool | None
    source_civil_iot_river_api_enabled: bool
    source_civil_iot_pond_enabled: bool | None
    source_civil_iot_pond_api_enabled: bool
    source_civil_iot_sewer_enabled: bool | None
    source_civil_iot_sewer_api_enabled: bool
    source_civil_iot_pump_enabled: bool | None
    source_civil_iot_pump_api_enabled: bool
    source_civil_iot_gate_enabled: bool | None
    source_civil_iot_gate_api_enabled: bool
    source_news_enabled: bool | None
    source_forum_enabled: bool | None
    source_ptt_enabled: bool | None
    source_dcard_enabled: bool | None
    source_ptt_candidate_approval_ack: bool
    source_dcard_candidate_approval_ack: bool
    source_terms_review_ack: bool
    source_sample_data_enabled: bool
    enabled_adapter_keys: tuple[str, ...] | None
    worker_idle_seconds: int
    scheduler_interval_seconds: int
    scheduler_max_ticks: int | None
    scheduler_lease_ttl_seconds: int
    evidence_realtime_retention_hours: int
    freshness_max_age_seconds: int
    runtime_fixtures_enabled: bool
    runtime_job_lease_seconds: int
    cwa_api_authorization: str | None
    cwa_api_url: str | None
    cwa_api_timeout_seconds: int
    wra_api_url: str | None
    wra_station_api_url: str | None
    wra_api_token: str | None
    wra_api_timeout_seconds: int
    wra_iow_flood_depth_api_url: str | None
    wra_iow_flood_sensor_metadata_api_url: str | None
    wra_iow_flood_depth_timeout_seconds: int
    ncdr_cap_api_url: str | None
    ncdr_cap_timeout_seconds: int
    flood_potential_geojson_url: str | None
    flood_potential_geojson_timeout_seconds: int
    civil_iot_flood_sensor_url: str | None
    source_flood_sensor_timeout_seconds: int
    tainan_flood_sensor_api_url: str | None
    tainan_flood_sensor_metadata_api_url: str | None
    source_tainan_flood_sensor_timeout_seconds: int
    new_taipei_water_level_api_url: str | None
    new_taipei_flood_sensor_api_url: str | None
    new_taipei_rainfall_api_url: str | None
    new_taipei_drainage_water_level_api_url: str | None
    taipei_sewer_water_level_api_url: str | None
    taipei_sewer_water_level_metadata_csv_url: str | None
    taipei_river_water_level_api_url: str | None
    taipei_river_water_level_metadata_csv_url: str | None
    taipei_pump_station_api_url: str | None
    taipei_water_timeout_seconds: int
    taoyuan_flood_sensor_api_url: str | None
    taoyuan_water_level_api_url: str | None
    taoyuan_rainfall_api_url: str | None
    taoyuan_water_timeout_seconds: int
    chiayi_city_water_level_api_url: str | None
    chiayi_city_rainfall_api_url: str | None
    taichung_water_level_api_url: str | None
    hsinchu_city_sewer_base_api_url: str | None
    hsinchu_city_sewer_realtime_api_url: str | None
    hsinchu_city_flood_sensor_station_api_url: str | None
    hsinchu_city_flood_sensor_realtime_api_url: str | None
    nantou_sewer_water_level_kml_url: str | None
    chiayi_county_flood_sensor_api_url: str | None
    kaohsiung_sewer_water_level_api_url: str | None
    kaohsiung_flood_sensor_api_url: str | None
    kaohsiung_rainfall_rt_api_url: str | None
    kaohsiung_rainfall_base_api_url: str | None
    keelung_water_level_api_url: str | None
    keelung_flood_sensor_api_url: str | None
    keelung_rainfall_api_url: str | None
    yunlin_stations_api_url: str | None
    yilan_flood_sensor_layer_url: str | None
    yilan_water_level_layer_url: str | None
    penghu_water_level_layer_url: str | None
    fhy_flood_sensor_station_api_url: str | None
    fhy_flood_sensor_realtime_api_url: str | None
    local_water_timeout_seconds: int
    civil_iot_river_url: str | None
    civil_iot_pond_url: str | None
    civil_iot_sewer_url: str | None
    civil_iot_pump_url: str | None
    civil_iot_gate_url: str | None
    civil_iot_api_timeout_seconds: int
    metrics_instance: str
    worker_metrics_textfile_path: str | None
    scheduler_metrics_textfile_path: str | None


def load_worker_settings(env: Mapping[str, str] | None = None) -> WorkerSettings:
    values = env if env is not None else os.environ
    return WorkerSettings(
        database_url=env_str(values, "WORKER_DATABASE_URL") or env_str(values, "DATABASE_URL"),
        source_cwa_enabled=env_bool(values, "SOURCE_CWA_ENABLED"),
        source_cwa_api_enabled=env_flag(values, "SOURCE_CWA_API_ENABLED"),
        source_wra_enabled=env_bool(values, "SOURCE_WRA_ENABLED"),
        source_wra_api_enabled=env_flag(values, "SOURCE_WRA_API_ENABLED"),
        source_wra_iow_flood_depth_enabled=env_bool(
            values,
            "SOURCE_WRA_IOW_FLOOD_DEPTH_ENABLED",
        ),
        source_wra_iow_flood_depth_api_enabled=env_flag(
            values,
            "SOURCE_WRA_IOW_FLOOD_DEPTH_API_ENABLED",
        ),
        source_ncdr_cap_enabled=env_bool(values, "SOURCE_NCDR_CAP_ENABLED"),
        source_ncdr_cap_api_enabled=env_flag(values, "SOURCE_NCDR_CAP_API_ENABLED"),
        source_flood_potential_enabled=env_bool(values, "SOURCE_FLOOD_POTENTIAL_ENABLED"),
        source_flood_potential_geojson_enabled=env_flag(
            values,
            "SOURCE_FLOOD_POTENTIAL_GEOJSON_ENABLED",
        ),
        source_flood_sensor_enabled=env_bool(values, "SOURCE_FLOOD_SENSOR_ENABLED"),
        source_flood_sensor_api_enabled=env_flag(values, "SOURCE_FLOOD_SENSOR_API_ENABLED"),
        source_flood_sensor_use_live=env_flag(values, "SOURCE_FLOOD_SENSOR_USE_LIVE"),
        source_tainan_flood_sensor_enabled=env_bool(
            values,
            "SOURCE_TAINAN_FLOOD_SENSOR_ENABLED",
        ),
        source_tainan_flood_sensor_api_enabled=env_flag(
            values,
            "SOURCE_TAINAN_FLOOD_SENSOR_API_ENABLED",
        ),
        source_new_taipei_water_level_enabled=env_bool(
            values,
            "SOURCE_NEW_TAIPEI_WATER_LEVEL_ENABLED",
        ),
        source_new_taipei_water_level_api_enabled=env_flag(
            values,
            "SOURCE_NEW_TAIPEI_WATER_LEVEL_API_ENABLED",
        ),
        source_new_taipei_flood_sensor_enabled=env_bool(
            values,
            "SOURCE_NEW_TAIPEI_FLOOD_SENSOR_ENABLED",
        ),
        source_new_taipei_flood_sensor_api_enabled=env_flag(
            values,
            "SOURCE_NEW_TAIPEI_FLOOD_SENSOR_API_ENABLED",
        ),
        source_new_taipei_rainfall_enabled=env_bool(
            values,
            "SOURCE_NEW_TAIPEI_RAINFALL_ENABLED",
        ),
        source_new_taipei_rainfall_api_enabled=env_flag(
            values,
            "SOURCE_NEW_TAIPEI_RAINFALL_API_ENABLED",
        ),
        source_new_taipei_drainage_water_level_enabled=env_bool(
            values,
            "SOURCE_NEW_TAIPEI_DRAINAGE_WATER_LEVEL_ENABLED",
        ),
        source_new_taipei_drainage_water_level_api_enabled=env_flag(
            values,
            "SOURCE_NEW_TAIPEI_DRAINAGE_WATER_LEVEL_API_ENABLED",
        ),
        source_taipei_sewer_water_level_enabled=env_bool(
            values,
            "SOURCE_TAIPEI_SEWER_WATER_LEVEL_ENABLED",
        ),
        source_taipei_sewer_water_level_api_enabled=env_flag(
            values,
            "SOURCE_TAIPEI_SEWER_WATER_LEVEL_API_ENABLED",
        ),
        source_taipei_river_water_level_enabled=env_bool(
            values,
            "SOURCE_TAIPEI_RIVER_WATER_LEVEL_ENABLED",
        ),
        source_taipei_river_water_level_api_enabled=env_flag(
            values,
            "SOURCE_TAIPEI_RIVER_WATER_LEVEL_API_ENABLED",
        ),
        source_taipei_pump_station_enabled=env_bool(
            values,
            "SOURCE_TAIPEI_PUMP_STATION_ENABLED",
        ),
        source_taipei_pump_station_api_enabled=env_flag(
            values,
            "SOURCE_TAIPEI_PUMP_STATION_API_ENABLED",
        ),
        source_taoyuan_flood_sensor_enabled=env_bool(
            values,
            "SOURCE_TAOYUAN_FLOOD_SENSOR_ENABLED",
        ),
        source_taoyuan_flood_sensor_api_enabled=env_flag(
            values,
            "SOURCE_TAOYUAN_FLOOD_SENSOR_API_ENABLED",
        ),
        source_taoyuan_water_level_enabled=env_bool(
            values,
            "SOURCE_TAOYUAN_WATER_LEVEL_ENABLED",
        ),
        source_taoyuan_water_level_api_enabled=env_flag(
            values,
            "SOURCE_TAOYUAN_WATER_LEVEL_API_ENABLED",
        ),
        source_taoyuan_rainfall_enabled=env_bool(
            values,
            "SOURCE_TAOYUAN_RAINFALL_ENABLED",
        ),
        source_taoyuan_rainfall_api_enabled=env_flag(
            values,
            "SOURCE_TAOYUAN_RAINFALL_API_ENABLED",
        ),
        source_chiayi_city_water_level_enabled=env_bool(
            values,
            "SOURCE_CHIAYI_CITY_WATER_LEVEL_ENABLED",
        ),
        source_chiayi_city_water_level_api_enabled=env_flag(
            values,
            "SOURCE_CHIAYI_CITY_WATER_LEVEL_API_ENABLED",
        ),
        source_chiayi_city_rainfall_enabled=env_bool(
            values,
            "SOURCE_CHIAYI_CITY_RAINFALL_ENABLED",
        ),
        source_chiayi_city_rainfall_api_enabled=env_flag(
            values,
            "SOURCE_CHIAYI_CITY_RAINFALL_API_ENABLED",
        ),
        source_taichung_water_level_enabled=env_bool(
            values,
            "SOURCE_TAICHUNG_WATER_LEVEL_ENABLED",
        ),
        source_taichung_water_level_api_enabled=env_flag(
            values,
            "SOURCE_TAICHUNG_WATER_LEVEL_API_ENABLED",
        ),
        source_hsinchu_city_sewer_water_level_enabled=env_bool(
            values,
            "SOURCE_HSINCHU_CITY_SEWER_WATER_LEVEL_ENABLED",
        ),
        source_hsinchu_city_sewer_water_level_api_enabled=env_flag(
            values,
            "SOURCE_HSINCHU_CITY_SEWER_WATER_LEVEL_API_ENABLED",
        ),
        source_hsinchu_city_flood_sensor_enabled=env_bool(
            values,
            "SOURCE_HSINCHU_CITY_FLOOD_SENSOR_ENABLED",
        ),
        source_hsinchu_city_flood_sensor_api_enabled=env_flag(
            values,
            "SOURCE_HSINCHU_CITY_FLOOD_SENSOR_API_ENABLED",
        ),
        source_nantou_sewer_water_level_enabled=env_bool(
            values,
            "SOURCE_NANTOU_SEWER_WATER_LEVEL_ENABLED",
        ),
        source_nantou_sewer_water_level_api_enabled=env_flag(
            values,
            "SOURCE_NANTOU_SEWER_WATER_LEVEL_API_ENABLED",
        ),
        source_chiayi_county_flood_sensor_enabled=env_bool(
            values,
            "SOURCE_CHIAYI_COUNTY_FLOOD_SENSOR_ENABLED",
        ),
        source_chiayi_county_flood_sensor_api_enabled=env_flag(
            values,
            "SOURCE_CHIAYI_COUNTY_FLOOD_SENSOR_API_ENABLED",
        ),
        source_kaohsiung_sewer_water_level_enabled=env_bool(
            values,
            "SOURCE_KAOHSIUNG_SEWER_WATER_LEVEL_ENABLED",
        ),
        source_kaohsiung_sewer_water_level_api_enabled=env_flag(
            values,
            "SOURCE_KAOHSIUNG_SEWER_WATER_LEVEL_API_ENABLED",
        ),
        source_kaohsiung_flood_sensor_enabled=env_bool(
            values,
            "SOURCE_KAOHSIUNG_FLOOD_SENSOR_ENABLED",
        ),
        source_kaohsiung_flood_sensor_api_enabled=env_flag(
            values,
            "SOURCE_KAOHSIUNG_FLOOD_SENSOR_API_ENABLED",
        ),
        source_kaohsiung_rainfall_enabled=env_bool(
            values,
            "SOURCE_KAOHSIUNG_RAINFALL_ENABLED",
        ),
        source_kaohsiung_rainfall_api_enabled=env_flag(
            values,
            "SOURCE_KAOHSIUNG_RAINFALL_API_ENABLED",
        ),
        source_keelung_water_level_enabled=env_bool(
            values,
            "SOURCE_KEELUNG_WATER_LEVEL_ENABLED",
        ),
        source_keelung_water_level_api_enabled=env_flag(
            values,
            "SOURCE_KEELUNG_WATER_LEVEL_API_ENABLED",
        ),
        source_keelung_flood_sensor_enabled=env_bool(
            values,
            "SOURCE_KEELUNG_FLOOD_SENSOR_ENABLED",
        ),
        source_keelung_flood_sensor_api_enabled=env_flag(
            values,
            "SOURCE_KEELUNG_FLOOD_SENSOR_API_ENABLED",
        ),
        source_keelung_rainfall_enabled=env_bool(
            values,
            "SOURCE_KEELUNG_RAINFALL_ENABLED",
        ),
        source_keelung_rainfall_api_enabled=env_flag(
            values,
            "SOURCE_KEELUNG_RAINFALL_API_ENABLED",
        ),
        source_yunlin_water_level_enabled=env_bool(
            values,
            "SOURCE_YUNLIN_WATER_LEVEL_ENABLED",
        ),
        source_yunlin_water_level_api_enabled=env_flag(
            values,
            "SOURCE_YUNLIN_WATER_LEVEL_API_ENABLED",
        ),
        source_yilan_flood_sensor_enabled=env_bool(
            values,
            "SOURCE_YILAN_FLOOD_SENSOR_ENABLED",
        ),
        source_yilan_flood_sensor_api_enabled=env_flag(
            values,
            "SOURCE_YILAN_FLOOD_SENSOR_API_ENABLED",
        ),
        source_yilan_water_level_enabled=env_bool(
            values,
            "SOURCE_YILAN_WATER_LEVEL_ENABLED",
        ),
        source_yilan_water_level_api_enabled=env_flag(
            values,
            "SOURCE_YILAN_WATER_LEVEL_API_ENABLED",
        ),
        source_penghu_water_level_enabled=env_bool(
            values,
            "SOURCE_PENGHU_WATER_LEVEL_ENABLED",
        ),
        source_penghu_water_level_api_enabled=env_flag(
            values,
            "SOURCE_PENGHU_WATER_LEVEL_API_ENABLED",
        ),
        source_hsinchu_county_fhy_flood_sensor_enabled=env_bool(
            values,
            "SOURCE_HSINCHU_COUNTY_FHY_FLOOD_SENSOR_ENABLED",
        ),
        source_hsinchu_county_fhy_flood_sensor_api_enabled=env_flag(
            values,
            "SOURCE_HSINCHU_COUNTY_FHY_FLOOD_SENSOR_API_ENABLED",
        ),
        source_miaoli_fhy_flood_sensor_enabled=env_bool(
            values,
            "SOURCE_MIAOLI_FHY_FLOOD_SENSOR_ENABLED",
        ),
        source_miaoli_fhy_flood_sensor_api_enabled=env_flag(
            values,
            "SOURCE_MIAOLI_FHY_FLOOD_SENSOR_API_ENABLED",
        ),
        source_changhua_fhy_flood_sensor_enabled=env_bool(
            values,
            "SOURCE_CHANGHUA_FHY_FLOOD_SENSOR_ENABLED",
        ),
        source_changhua_fhy_flood_sensor_api_enabled=env_flag(
            values,
            "SOURCE_CHANGHUA_FHY_FLOOD_SENSOR_API_ENABLED",
        ),
        source_pingtung_fhy_flood_sensor_enabled=env_bool(
            values,
            "SOURCE_PINGTUNG_FHY_FLOOD_SENSOR_ENABLED",
        ),
        source_pingtung_fhy_flood_sensor_api_enabled=env_flag(
            values,
            "SOURCE_PINGTUNG_FHY_FLOOD_SENSOR_API_ENABLED",
        ),
        source_hualien_fhy_flood_sensor_enabled=env_bool(
            values,
            "SOURCE_HUALIEN_FHY_FLOOD_SENSOR_ENABLED",
        ),
        source_hualien_fhy_flood_sensor_api_enabled=env_flag(
            values,
            "SOURCE_HUALIEN_FHY_FLOOD_SENSOR_API_ENABLED",
        ),
        source_taitung_fhy_flood_sensor_enabled=env_bool(
            values,
            "SOURCE_TAITUNG_FHY_FLOOD_SENSOR_ENABLED",
        ),
        source_taitung_fhy_flood_sensor_api_enabled=env_flag(
            values,
            "SOURCE_TAITUNG_FHY_FLOOD_SENSOR_API_ENABLED",
        ),
        source_civil_iot_river_enabled=env_bool(values, "SOURCE_CIVIL_IOT_RIVER_ENABLED"),
        source_civil_iot_river_api_enabled=env_flag(
            values,
            "SOURCE_CIVIL_IOT_RIVER_API_ENABLED",
        ),
        source_civil_iot_pond_enabled=env_bool(values, "SOURCE_CIVIL_IOT_POND_ENABLED"),
        source_civil_iot_pond_api_enabled=env_flag(
            values,
            "SOURCE_CIVIL_IOT_POND_API_ENABLED",
        ),
        source_civil_iot_sewer_enabled=env_bool(values, "SOURCE_CIVIL_IOT_SEWER_ENABLED"),
        source_civil_iot_sewer_api_enabled=env_flag(
            values,
            "SOURCE_CIVIL_IOT_SEWER_API_ENABLED",
        ),
        source_civil_iot_pump_enabled=env_bool(values, "SOURCE_CIVIL_IOT_PUMP_ENABLED"),
        source_civil_iot_pump_api_enabled=env_flag(
            values,
            "SOURCE_CIVIL_IOT_PUMP_API_ENABLED",
        ),
        source_civil_iot_gate_enabled=env_bool(values, "SOURCE_CIVIL_IOT_GATE_ENABLED"),
        source_civil_iot_gate_api_enabled=env_flag(
            values,
            "SOURCE_CIVIL_IOT_GATE_API_ENABLED",
        ),
        source_news_enabled=env_bool(values, "SOURCE_NEWS_ENABLED"),
        source_forum_enabled=env_bool(values, "SOURCE_FORUM_ENABLED"),
        source_ptt_enabled=env_bool(values, "SOURCE_PTT_ENABLED"),
        source_dcard_enabled=env_bool(values, "SOURCE_DCARD_ENABLED"),
        source_ptt_candidate_approval_ack=env_flag(
            values,
            "SOURCE_PTT_CANDIDATE_APPROVAL_ACK",
        ),
        source_dcard_candidate_approval_ack=env_flag(
            values,
            "SOURCE_DCARD_CANDIDATE_APPROVAL_ACK",
        ),
        source_terms_review_ack=env_flag(values, "SOURCE_TERMS_REVIEW_ACK"),
        source_sample_data_enabled=env_flag(values, "SOURCE_SAMPLE_DATA_ENABLED"),
        enabled_adapter_keys=env_list(values, "WORKER_ENABLED_ADAPTER_KEYS"),
        worker_idle_seconds=env_int(values, "WORKER_IDLE_SECONDS", default=60),
        scheduler_interval_seconds=env_int(values, "SCHEDULER_INTERVAL_SECONDS", default=300),
        scheduler_max_ticks=env_optional_int(values, "SCHEDULER_MAX_TICKS"),
        scheduler_lease_ttl_seconds=env_int(
            values,
            "SCHEDULER_LEASE_TTL_SECONDS",
            default=600,
        ),
        evidence_realtime_retention_hours=env_int(
            values,
            "EVIDENCE_REALTIME_RETENTION_HOURS",
            default=48,
        ),
        freshness_max_age_seconds=env_int(
            values,
            "FRESHNESS_MAX_AGE_SECONDS",
            default=6 * 60 * 60,
        ),
        runtime_fixtures_enabled=env_flag(values, "WORKER_RUNTIME_FIXTURES_ENABLED"),
        runtime_job_lease_seconds=env_int(values, "WORKER_RUNTIME_JOB_LEASE_SECONDS", default=300),
        cwa_api_authorization=env_str(values, "CWA_API_AUTHORIZATION"),
        cwa_api_url=env_str(values, "CWA_API_URL"),
        cwa_api_timeout_seconds=env_int(values, "CWA_API_TIMEOUT_SECONDS", default=8),
        wra_api_url=env_str(values, "WRA_API_URL"),
        wra_station_api_url=env_str(values, "WRA_STATION_API_URL"),
        wra_api_token=env_str(values, "WRA_API_TOKEN"),
        wra_api_timeout_seconds=env_int(values, "WRA_API_TIMEOUT_SECONDS", default=8),
        wra_iow_flood_depth_api_url=env_str(values, "WRA_IOW_FLOOD_DEPTH_API_URL"),
        wra_iow_flood_sensor_metadata_api_url=env_str(
            values,
            "WRA_IOW_FLOOD_SENSOR_METADATA_API_URL",
        ),
        wra_iow_flood_depth_timeout_seconds=env_int(
            values,
            "WRA_IOW_FLOOD_DEPTH_TIMEOUT_SECONDS",
            default=8,
        ),
        ncdr_cap_api_url=env_str(values, "NCDR_CAP_API_URL"),
        ncdr_cap_timeout_seconds=env_int(values, "NCDR_CAP_TIMEOUT_SECONDS", default=8),
        flood_potential_geojson_url=env_str(values, "FLOOD_POTENTIAL_GEOJSON_URL"),
        flood_potential_geojson_timeout_seconds=env_int(
            values,
            "FLOOD_POTENTIAL_GEOJSON_TIMEOUT_SECONDS",
            default=8,
        ),
        civil_iot_flood_sensor_url=env_str(values, "CIVIL_IOT_FLOOD_SENSOR_URL"),
        source_flood_sensor_timeout_seconds=env_int(
            values,
            "SOURCE_FLOOD_SENSOR_TIMEOUT_SECONDS",
            default=8,
        ),
        tainan_flood_sensor_api_url=env_str(values, "TAINAN_FLOOD_SENSOR_API_URL"),
        tainan_flood_sensor_metadata_api_url=env_str(
            values,
            "TAINAN_FLOOD_SENSOR_METADATA_API_URL",
        ),
        source_tainan_flood_sensor_timeout_seconds=env_int(
            values,
            "SOURCE_TAINAN_FLOOD_SENSOR_TIMEOUT_SECONDS",
            default=8,
        ),
        new_taipei_water_level_api_url=env_str(values, "NEW_TAIPEI_WATER_LEVEL_API_URL"),
        new_taipei_flood_sensor_api_url=env_str(values, "NEW_TAIPEI_FLOOD_SENSOR_API_URL"),
        new_taipei_rainfall_api_url=env_str(values, "NEW_TAIPEI_RAINFALL_API_URL"),
        new_taipei_drainage_water_level_api_url=env_str(
            values,
            "NEW_TAIPEI_DRAINAGE_WATER_LEVEL_API_URL",
        ),
        taipei_sewer_water_level_api_url=env_str(values, "TAIPEI_SEWER_WATER_LEVEL_API_URL"),
        taipei_sewer_water_level_metadata_csv_url=env_str(
            values,
            "TAIPEI_SEWER_WATER_LEVEL_METADATA_CSV_URL",
        ),
        taipei_river_water_level_api_url=env_str(values, "TAIPEI_RIVER_WATER_LEVEL_API_URL"),
        taipei_river_water_level_metadata_csv_url=env_str(
            values,
            "TAIPEI_RIVER_WATER_LEVEL_METADATA_CSV_URL",
        ),
        taipei_pump_station_api_url=env_str(values, "TAIPEI_PUMP_STATION_API_URL"),
        taipei_water_timeout_seconds=env_int(
            values,
            "TAIPEI_WATER_TIMEOUT_SECONDS",
            default=8,
        ),
        taoyuan_flood_sensor_api_url=env_str(values, "TAOYUAN_FLOOD_SENSOR_API_URL"),
        taoyuan_water_level_api_url=env_str(values, "TAOYUAN_WATER_LEVEL_API_URL"),
        taoyuan_rainfall_api_url=env_str(values, "TAOYUAN_RAINFALL_API_URL"),
        taoyuan_water_timeout_seconds=env_int(
            values,
            "TAOYUAN_WATER_TIMEOUT_SECONDS",
            default=8,
        ),
        chiayi_city_water_level_api_url=env_str(values, "CHIAYI_CITY_WATER_LEVEL_API_URL"),
        chiayi_city_rainfall_api_url=env_str(values, "CHIAYI_CITY_RAINFALL_API_URL"),
        taichung_water_level_api_url=env_str(values, "TAICHUNG_WATER_LEVEL_API_URL"),
        hsinchu_city_sewer_base_api_url=env_str(values, "HSINCHU_CITY_SEWER_BASE_API_URL"),
        hsinchu_city_sewer_realtime_api_url=env_str(
            values,
            "HSINCHU_CITY_SEWER_REALTIME_API_URL",
        ),
        hsinchu_city_flood_sensor_station_api_url=env_str(
            values,
            "HSINCHU_CITY_FLOOD_SENSOR_STATION_API_URL",
        ),
        hsinchu_city_flood_sensor_realtime_api_url=env_str(
            values,
            "HSINCHU_CITY_FLOOD_SENSOR_REALTIME_API_URL",
        ),
        nantou_sewer_water_level_kml_url=env_str(
            values,
            "NANTOU_SEWER_WATER_LEVEL_KML_URL",
        ),
        chiayi_county_flood_sensor_api_url=env_str(
            values,
            "CHIAYI_COUNTY_FLOOD_SENSOR_API_URL",
        ),
        kaohsiung_sewer_water_level_api_url=env_str(
            values,
            "KAOHSIUNG_SEWER_WATER_LEVEL_API_URL",
        ),
        kaohsiung_flood_sensor_api_url=env_str(
            values,
            "KAOHSIUNG_FLOOD_SENSOR_API_URL",
        ),
        kaohsiung_rainfall_rt_api_url=env_str(
            values,
            "KAOHSIUNG_RAINFALL_RT_API_URL",
        ),
        kaohsiung_rainfall_base_api_url=env_str(
            values,
            "KAOHSIUNG_RAINFALL_BASE_API_URL",
        ),
        keelung_water_level_api_url=env_str(
            values,
            "KEELUNG_WATER_LEVEL_API_URL",
        ),
        keelung_flood_sensor_api_url=env_str(
            values,
            "KEELUNG_FLOOD_SENSOR_API_URL",
        ),
        keelung_rainfall_api_url=env_str(
            values,
            "KEELUNG_RAINFALL_API_URL",
        ),
        yunlin_stations_api_url=env_str(
            values,
            "YUNLIN_STATIONS_API_URL",
        ),
        yilan_flood_sensor_layer_url=env_str(
            values,
            "YILAN_FLOOD_SENSOR_LAYER_URL",
        ),
        yilan_water_level_layer_url=env_str(
            values,
            "YILAN_WATER_LEVEL_LAYER_URL",
        ),
        penghu_water_level_layer_url=env_str(
            values,
            "PENGHU_WATER_LEVEL_LAYER_URL",
        ),
        fhy_flood_sensor_station_api_url=env_str(
            values,
            "FHY_FLOOD_SENSOR_STATION_API_URL",
        ),
        fhy_flood_sensor_realtime_api_url=env_str(
            values,
            "FHY_FLOOD_SENSOR_REALTIME_API_URL",
        ),
        local_water_timeout_seconds=env_int(
            values,
            "LOCAL_WATER_TIMEOUT_SECONDS",
            default=8,
        ),
        civil_iot_river_url=env_str(values, "CIVIL_IOT_RIVER_URL"),
        civil_iot_pond_url=env_str(values, "CIVIL_IOT_POND_URL"),
        civil_iot_sewer_url=env_str(values, "CIVIL_IOT_SEWER_URL"),
        civil_iot_pump_url=env_str(values, "CIVIL_IOT_PUMP_URL"),
        civil_iot_gate_url=env_str(values, "CIVIL_IOT_GATE_URL"),
        civil_iot_api_timeout_seconds=env_int(
            values,
            "CIVIL_IOT_API_TIMEOUT_SECONDS",
            default=8,
        ),
        metrics_instance=(
            env_str(values, "WORKER_INSTANCE")
            or env_str(values, "HOSTNAME")
            or env_str(values, "COMPUTERNAME")
            or "local"
        ),
        worker_metrics_textfile_path=env_str(values, "WORKER_METRICS_TEXTFILE_PATH"),
        scheduler_metrics_textfile_path=env_str(values, "SCHEDULER_METRICS_TEXTFILE_PATH"),
    )


def env_bool(
    env: Mapping[str, str],
    name: str,
    *,
    default: bool | None = None,
) -> bool | None:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    return default


def env_flag(env: Mapping[str, str], name: str) -> bool:
    return env_bool(env, name, default=False) is True


def env_int(env: Mapping[str, str], name: str, *, default: int) -> int:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def env_optional_int(env: Mapping[str, str], name: str) -> int | None:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return None
    try:
        return max(1, int(raw))
    except ValueError:
        return None


def env_list(env: Mapping[str, str], name: str) -> tuple[str, ...] | None:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return None
    values = tuple(
        dict.fromkeys(part.strip() for part in raw.replace("\n", ",").split(",") if part.strip())
    )
    return values or None


def env_str(env: Mapping[str, str], name: str) -> str | None:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return None
    return raw.strip()
