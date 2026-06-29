from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.adapters.civil_iot import (
    GATE_WATER_LEVEL,
    POND_WATER_LEVEL,
    PUMP_WATER_LEVEL,
    SEWER_WATER_LEVEL,
    CivilIotRiverApiAdapter,
    FloodSensorStaApiAdapter,
    StaFetchJson,
    StaWaterLevelApiAdapter,
)
from app.adapters.contracts import DataSourceAdapter
from app.adapters.cwa import CwaRainfallApiAdapter, FetchJson
from app.adapters.flood_potential import FetchJson as FloodPotentialFetchJson
from app.adapters.flood_potential import FloodPotentialGeoJsonApiAdapter
from app.adapters.local_chiayi_city import ChiayiCityRainfallApiAdapter, ChiayiCityWaterLevelApiAdapter
from app.adapters.local_chiayi_city import FetchText as ChiayiCityFetchText
from app.adapters.local_chiayi_county import ChiayiCountyFloodSensorApiAdapter
from app.adapters.local_chiayi_county import FetchJson as ChiayiCountyFetchJson
from app.adapters.local_fhy import FetchJson as FhyFloodSensorFetchJson
from app.adapters.local_fhy import (
    CHANGHUA_FHY_FLOOD_SENSOR,
    FHY_LOCAL_FLOOD_SENSOR_SOURCES,
    HSINCHU_COUNTY_FHY_FLOOD_SENSOR,
    HUALIEN_FHY_FLOOD_SENSOR,
    MIAOLI_FHY_FLOOD_SENSOR,
    PINGTUNG_FHY_FLOOD_SENSOR,
    TAITUNG_FHY_FLOOD_SENSOR,
    FhyFloodSensorApiAdapter,
)
from app.adapters.local_hsinchu_city import FetchJson as HsinchuCityFetchJson
from app.adapters.local_hsinchu_city import (
    HsinchuCityFloodSensorApiAdapter,
    HsinchuCitySewerWaterLevelApiAdapter,
)
from app.adapters.local_kaohsiung import FetchJson as KaohsiungFetchJson
from app.adapters.local_kaohsiung import (
    KaohsiungFloodSensorApiAdapter,
    KaohsiungRainfallApiAdapter,
    KaohsiungSewerWaterLevelApiAdapter,
)
from app.adapters.local_keelung import FetchJson as KeelungFetchJson
from app.adapters.local_keelung import (
    KeelungFloodSensorApiAdapter,
    KeelungRainfallApiAdapter,
    KeelungWaterLevelApiAdapter,
)
from app.adapters.local_nantou import FetchText as NantouFetchText
from app.adapters.local_nantou import NantouSewerWaterLevelKmlAdapter
from app.adapters.local_new_taipei import FetchJson as NewTaipeiFetchJson
from app.adapters.local_new_taipei import (
    NewTaipeiDrainageWaterLevelApiAdapter,
    NewTaipeiFloodSensorApiAdapter,
    NewTaipeiRainfallApiAdapter,
    NewTaipeiWaterLevelApiAdapter,
)
from app.adapters.local_penghu import FetchJson as PenghuFetchJson
from app.adapters.local_penghu import PenghuWaterLevelArcgisAdapter
from app.adapters.local_taichung import FetchJson as TaichungFetchJson
from app.adapters.local_taichung import TaichungWaterLevelApiAdapter
from app.adapters.local_taipei import (
    TAIPEI_RIVER_WATER_LEVEL,
    TAIPEI_SEWER_WATER_LEVEL,
    FetchJson as TaipeiFetchJson,
)
from app.adapters.local_taipei import (
    FetchText as TaipeiFetchText,
)
from app.adapters.local_taipei import TaipeiPumpStationApiAdapter, TaipeiWaterLevelApiAdapter
from app.adapters.local_tainan import FetchJson as TainanFetchJson
from app.adapters.local_tainan import TainanFloodSensorApiAdapter
from app.adapters.local_taoyuan import FetchText as TaoyuanFetchText
from app.adapters.local_taoyuan import (
    TaoyuanFloodSensorApiAdapter,
    TaoyuanRainfallApiAdapter,
    TaoyuanWaterLevelApiAdapter,
)
from app.adapters.local_yilan import FetchJson as YilanFetchJson
from app.adapters.local_yilan import YilanFloodSensorArcgisAdapter, YilanWaterLevelArcgisAdapter
from app.adapters.local_yunlin import FetchJson as YunlinFetchJson
from app.adapters.local_yunlin import YunlinWaterLevelApiAdapter
from app.adapters.ncdr import FetchText as NcdrFetchText
from app.adapters.ncdr import NcdrCapAlertAdapter
from app.adapters.registry import enabled_adapter_keys
from app.adapters.wra import FetchJson as WraFetchJson
from app.adapters.wra import WraWaterLevelApiAdapter
from app.adapters.wra_iow import FetchJson as WraIowFetchJson
from app.adapters.wra_iow import WraIowFloodDepthApiAdapter
from app.config import WorkerSettings, load_worker_settings
from app.jobs.forum_candidate import build_forum_candidate_fixture_adapters
from app.jobs.freshness import FreshnessCheck, check_batch_freshness
from app.jobs.ingestion import (
    AdapterBatchRunSummary,
    IngestionRunSummaryWriter,
    run_adapter_batch,
)
from app.jobs.official_demo import build_official_demo_adapters
from app.jobs.public_web_sample import build_public_web_sample_adapters
from app.jobs.queue import (
    NullRuntimeQueue,
    PostgresRuntimeQueue,
    RuntimeQueueJob,
    RuntimeQueueUnavailable,
)
from app.logging import log_event
from app.pipelines.ingestion_runs import PostgresIngestionRunWriter
from app.pipelines.postgres_writer import PostgresStagingBatchWriter
from app.pipelines.promotion import (
    EvidencePromotionWriter,
    PostgresEvidencePromotionWriter,
    PromotionResult,
    promote_accepted_staging,
)
from app.pipelines.staging import StagingBatchWriter


RuntimeQueueWorkerStatus = Literal["succeeded", "failed", "skipped"]
RuntimeQueueProducerStatus = Literal["succeeded", "skipped", "deduped"]
RuntimeQueue = PostgresRuntimeQueue | NullRuntimeQueue


@dataclass(frozen=True)
class RuntimeQueueWorkerResult:
    status: RuntimeQueueWorkerStatus
    job_id: str | None = None
    adapter_key: str | None = None
    reason: str | None = None
    summary: AdapterBatchRunSummary | None = None
    freshness_checks: tuple[FreshnessCheck, ...] = ()
    promoted: int = 0
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuntimeQueueProducerResult:
    status: RuntimeQueueProducerStatus
    adapter_keys: tuple[str, ...] = ()
    job_ids: tuple[str, ...] = ()
    enqueued_job_ids: tuple[str, ...] = ()
    deduped_job_ids: tuple[str, ...] = ()
    dedupe_keys: tuple[str, ...] = ()
    reason: str | None = None

    @property
    def durable_job_count(self) -> int:
        return len(self.job_ids)

    @property
    def enqueued_job_count(self) -> int:
        return len(self.enqueued_job_ids)

    @property
    def deduped_job_count(self) -> int:
        return len(self.deduped_job_ids)


def build_runtime_adapters(
    settings: WorkerSettings,
    *,
    fetched_at: datetime | None = None,
    cwa_fetch_json: FetchJson | None = None,
    wra_fetch_json: WraFetchJson | None = None,
    ncdr_cap_fetch_text: NcdrFetchText | None = None,
    flood_potential_fetch_json: FloodPotentialFetchJson | None = None,
    flood_sensor_fetch_json: StaFetchJson | None = None,
    tainan_flood_sensor_fetch_json: TainanFetchJson | None = None,
    new_taipei_water_level_fetch_json: NewTaipeiFetchJson | None = None,
    new_taipei_flood_sensor_fetch_json: NewTaipeiFetchJson | None = None,
    new_taipei_rainfall_fetch_json: NewTaipeiFetchJson | None = None,
    new_taipei_drainage_water_level_fetch_json: NewTaipeiFetchJson | None = None,
    taipei_sewer_fetch_json: TaipeiFetchJson | None = None,
    taipei_sewer_fetch_text: TaipeiFetchText | None = None,
    taipei_river_fetch_json: TaipeiFetchJson | None = None,
    taipei_river_fetch_text: TaipeiFetchText | None = None,
    taipei_pump_fetch_json: TaipeiFetchJson | None = None,
    taoyuan_flood_sensor_fetch_text: TaoyuanFetchText | None = None,
    taoyuan_water_level_fetch_text: TaoyuanFetchText | None = None,
    taoyuan_rainfall_fetch_text: TaoyuanFetchText | None = None,
    chiayi_city_water_level_fetch_text: ChiayiCityFetchText | None = None,
    chiayi_city_rainfall_fetch_text: ChiayiCityFetchText | None = None,
    taichung_water_level_fetch_json: TaichungFetchJson | None = None,
    hsinchu_city_sewer_fetch_json: HsinchuCityFetchJson | None = None,
    hsinchu_city_flood_sensor_fetch_json: HsinchuCityFetchJson | None = None,
    nantou_sewer_water_level_fetch_text: NantouFetchText | None = None,
    chiayi_county_flood_sensor_fetch_json: ChiayiCountyFetchJson | None = None,
    kaohsiung_sewer_fetch_json: KaohsiungFetchJson | None = None,
    kaohsiung_flood_sensor_fetch_json: KaohsiungFetchJson | None = None,
    kaohsiung_rainfall_fetch_json: KaohsiungFetchJson | None = None,
    keelung_water_level_fetch_json: KeelungFetchJson | None = None,
    keelung_flood_sensor_fetch_json: KeelungFetchJson | None = None,
    keelung_rainfall_fetch_json: KeelungFetchJson | None = None,
    yunlin_water_level_fetch_json: YunlinFetchJson | None = None,
    yilan_flood_sensor_fetch_json: YilanFetchJson | None = None,
    yilan_water_level_fetch_json: YilanFetchJson | None = None,
    penghu_water_level_fetch_json: PenghuFetchJson | None = None,
    fhy_flood_sensor_fetch_json: FhyFloodSensorFetchJson | None = None,
    wra_iow_flood_depth_fetch_json: WraIowFetchJson | None = None,
    civil_iot_river_fetch_json: StaFetchJson | None = None,
    civil_iot_pond_fetch_json: StaFetchJson | None = None,
    civil_iot_sewer_fetch_json: StaFetchJson | None = None,
    civil_iot_pump_fetch_json: StaFetchJson | None = None,
    civil_iot_gate_fetch_json: StaFetchJson | None = None,
) -> Mapping[str, DataSourceAdapter]:
    if settings.runtime_fixtures_enabled:
        resolved_fetched_at = fetched_at or datetime.now(UTC)
        fixture_adapters = dict(
            build_official_demo_adapters(fetched_at=resolved_fetched_at)
        )
        if (
            settings.enabled_adapter_keys is not None
            and "news.public_web.sample" in settings.enabled_adapter_keys
            and "news.public_web.sample" in enabled_adapter_keys(settings)
        ):
            fixture_adapters.update(
                build_public_web_sample_adapters(fetched_at=resolved_fetched_at)
            )
        fixture_adapters.update(
            build_forum_candidate_fixture_adapters(
                settings,
                fetched_at=resolved_fetched_at,
            )
        )
        log_event(
            "runtime.adapters.fixture_mode.enabled",
            available_adapter_keys=tuple(fixture_adapters),
        )
        return fixture_adapters

    enabled_keys = enabled_adapter_keys(settings)
    live_adapters: dict[str, DataSourceAdapter] = {}
    if settings.source_cwa_api_enabled and "official.cwa.rainfall" in enabled_keys:
        cwa_adapter = CwaRainfallApiAdapter(
            authorization=settings.cwa_api_authorization,
            api_url=settings.cwa_api_url,
            timeout_seconds=settings.cwa_api_timeout_seconds,
            fetched_at=fetched_at,
            fetch_json=cwa_fetch_json,
        )
        live_adapters[cwa_adapter.metadata.key] = cwa_adapter

    if settings.source_wra_api_enabled and "official.wra.water_level" in enabled_keys:
        wra_adapter = WraWaterLevelApiAdapter(
            api_url=settings.wra_api_url,
            station_api_url=settings.wra_station_api_url,
            api_token=settings.wra_api_token,
            timeout_seconds=settings.wra_api_timeout_seconds,
            fetched_at=fetched_at,
            fetch_json=wra_fetch_json,
        )
        live_adapters[wra_adapter.metadata.key] = wra_adapter

    if (
        settings.source_wra_iow_flood_depth_api_enabled
        and "official.wra_iow.flood_depth" in enabled_keys
    ):
        wra_iow_adapter = WraIowFloodDepthApiAdapter(
            api_url=settings.wra_iow_flood_depth_api_url,
            metadata_api_url=settings.wra_iow_flood_sensor_metadata_api_url,
            timeout_seconds=settings.wra_iow_flood_depth_timeout_seconds,
            fetched_at=fetched_at,
            fetch_json=wra_iow_flood_depth_fetch_json,
        )
        live_adapters[wra_iow_adapter.metadata.key] = wra_iow_adapter

    if settings.source_ncdr_cap_api_enabled and "official.ncdr.cap" in enabled_keys:
        ncdr_cap_adapter = NcdrCapAlertAdapter(
            api_url=settings.ncdr_cap_api_url,
            timeout_seconds=settings.ncdr_cap_timeout_seconds,
            fetched_at=fetched_at,
            fetch_text=ncdr_cap_fetch_text,
        )
        live_adapters[ncdr_cap_adapter.metadata.key] = ncdr_cap_adapter

    if (
        settings.source_flood_potential_geojson_enabled
        and "official.flood_potential.geojson" in enabled_keys
    ):
        flood_potential_adapter = FloodPotentialGeoJsonApiAdapter(
            geojson_url=settings.flood_potential_geojson_url,
            timeout_seconds=settings.flood_potential_geojson_timeout_seconds,
            fetched_at=fetched_at,
            fetch_json=flood_potential_fetch_json,
        )
        live_adapters[flood_potential_adapter.metadata.key] = flood_potential_adapter

    if (
        settings.source_flood_sensor_use_live
        and settings.source_flood_sensor_api_enabled
        and "official.civil_iot.flood_sensor" in enabled_keys
    ):
        flood_sensor_adapter = FloodSensorStaApiAdapter(
            sta_url=settings.civil_iot_flood_sensor_url,
            timeout_seconds=settings.source_flood_sensor_timeout_seconds,
            fetched_at=fetched_at,
            fetch_json=flood_sensor_fetch_json,
        )
        live_adapters[flood_sensor_adapter.metadata.key] = flood_sensor_adapter

    if (
        settings.source_flood_sensor_api_enabled
        and settings.source_flood_sensor_use_live
        is False
        and "official.civil_iot.flood_sensor" in enabled_keys
    ):
        log_event(
            "runtime.adapters.gated",
            adapter_key="official.civil_iot.flood_sensor",
            gate="SOURCE_FLOOD_SENSOR_USE_LIVE",
            source_intent="civil_iot_official_national_backbone",
        )

    if (
        settings.source_tainan_flood_sensor_api_enabled
        and "local.tainan.flood_sensor" in enabled_keys
    ):
        tainan_flood_sensor_adapter = TainanFloodSensorApiAdapter(
            api_url=settings.tainan_flood_sensor_api_url,
            metadata_api_url=settings.tainan_flood_sensor_metadata_api_url,
            timeout_seconds=settings.source_tainan_flood_sensor_timeout_seconds,
            fetched_at=fetched_at,
            fetch_json=tainan_flood_sensor_fetch_json,
        )
        live_adapters[tainan_flood_sensor_adapter.metadata.key] = tainan_flood_sensor_adapter

    if (
        settings.source_new_taipei_water_level_api_enabled
        and "local.new_taipei.water_level" in enabled_keys
    ):
        new_taipei_water_adapter = NewTaipeiWaterLevelApiAdapter(
            api_url=settings.new_taipei_water_level_api_url,
            timeout_seconds=settings.local_water_timeout_seconds,
            fetched_at=fetched_at,
            fetch_json=new_taipei_water_level_fetch_json,
        )
        live_adapters[new_taipei_water_adapter.metadata.key] = new_taipei_water_adapter

    if (
        settings.source_new_taipei_flood_sensor_api_enabled
        and "local.new_taipei.flood_sensor" in enabled_keys
    ):
        new_taipei_flood_adapter = NewTaipeiFloodSensorApiAdapter(
            api_url=settings.new_taipei_flood_sensor_api_url,
            timeout_seconds=settings.local_water_timeout_seconds,
            fetched_at=fetched_at,
            fetch_json=new_taipei_flood_sensor_fetch_json,
        )
        live_adapters[new_taipei_flood_adapter.metadata.key] = new_taipei_flood_adapter

    if (
        settings.source_new_taipei_rainfall_api_enabled
        and "local.new_taipei.rainfall" in enabled_keys
    ):
        new_taipei_rainfall_adapter = NewTaipeiRainfallApiAdapter(
            api_url=settings.new_taipei_rainfall_api_url,
            timeout_seconds=settings.local_water_timeout_seconds,
            fetched_at=fetched_at,
            fetch_json=new_taipei_rainfall_fetch_json,
        )
        live_adapters[new_taipei_rainfall_adapter.metadata.key] = new_taipei_rainfall_adapter

    if (
        settings.source_new_taipei_drainage_water_level_api_enabled
        and "local.new_taipei.drainage_water_level" in enabled_keys
    ):
        new_taipei_drainage_adapter = NewTaipeiDrainageWaterLevelApiAdapter(
            api_url=settings.new_taipei_drainage_water_level_api_url,
            timeout_seconds=settings.local_water_timeout_seconds,
            fetched_at=fetched_at,
            fetch_json=new_taipei_drainage_water_level_fetch_json,
        )
        live_adapters[new_taipei_drainage_adapter.metadata.key] = new_taipei_drainage_adapter

    for source, api_enabled, api_url, metadata_csv_url, fetch_json, fetch_text in (
        (
            TAIPEI_SEWER_WATER_LEVEL,
            settings.source_taipei_sewer_water_level_api_enabled,
            settings.taipei_sewer_water_level_api_url,
            settings.taipei_sewer_water_level_metadata_csv_url,
            taipei_sewer_fetch_json,
            taipei_sewer_fetch_text,
        ),
        (
            TAIPEI_RIVER_WATER_LEVEL,
            settings.source_taipei_river_water_level_api_enabled,
            settings.taipei_river_water_level_api_url,
            settings.taipei_river_water_level_metadata_csv_url,
            taipei_river_fetch_json,
            taipei_river_fetch_text,
        ),
    ):
        if api_enabled and source.metadata.key in enabled_keys:
            taipei_water_adapter = TaipeiWaterLevelApiAdapter(
                source,
                api_url=api_url,
                metadata_csv_url=metadata_csv_url,
                timeout_seconds=settings.taipei_water_timeout_seconds,
                fetched_at=fetched_at,
                fetch_json=fetch_json,
                fetch_text=fetch_text,
            )
            live_adapters[taipei_water_adapter.metadata.key] = taipei_water_adapter

    if (
        settings.source_taipei_pump_station_api_enabled
        and "local.taipei.pump_station" in enabled_keys
    ):
        taipei_pump_adapter = TaipeiPumpStationApiAdapter(
            api_url=settings.taipei_pump_station_api_url,
            timeout_seconds=settings.taipei_water_timeout_seconds,
            fetched_at=fetched_at,
            fetch_json=taipei_pump_fetch_json,
        )
        live_adapters[taipei_pump_adapter.metadata.key] = taipei_pump_adapter

    if (
        settings.source_taoyuan_flood_sensor_api_enabled
        and "local.taoyuan.flood_sensor" in enabled_keys
    ):
        taoyuan_flood_adapter = TaoyuanFloodSensorApiAdapter(
            api_url=settings.taoyuan_flood_sensor_api_url,
            timeout_seconds=settings.taoyuan_water_timeout_seconds,
            fetched_at=fetched_at,
            fetch_text=taoyuan_flood_sensor_fetch_text,
        )
        live_adapters[taoyuan_flood_adapter.metadata.key] = taoyuan_flood_adapter

    if (
        settings.source_taoyuan_water_level_api_enabled
        and "local.taoyuan.water_level" in enabled_keys
    ):
        taoyuan_water_adapter = TaoyuanWaterLevelApiAdapter(
            api_url=settings.taoyuan_water_level_api_url,
            timeout_seconds=settings.taoyuan_water_timeout_seconds,
            fetched_at=fetched_at,
            fetch_text=taoyuan_water_level_fetch_text,
        )
        live_adapters[taoyuan_water_adapter.metadata.key] = taoyuan_water_adapter

    if (
        settings.source_taoyuan_rainfall_api_enabled
        and "local.taoyuan.rainfall" in enabled_keys
    ):
        taoyuan_rainfall_adapter = TaoyuanRainfallApiAdapter(
            api_url=settings.taoyuan_rainfall_api_url,
            timeout_seconds=settings.taoyuan_water_timeout_seconds,
            fetched_at=fetched_at,
            fetch_text=taoyuan_rainfall_fetch_text,
        )
        live_adapters[taoyuan_rainfall_adapter.metadata.key] = taoyuan_rainfall_adapter

    if (
        settings.source_chiayi_city_water_level_api_enabled
        and "local.chiayi_city.water_level" in enabled_keys
    ):
        chiayi_adapter = ChiayiCityWaterLevelApiAdapter(
            api_url=settings.chiayi_city_water_level_api_url,
            timeout_seconds=settings.local_water_timeout_seconds,
            fetched_at=fetched_at,
            fetch_text=chiayi_city_water_level_fetch_text,
        )
        live_adapters[chiayi_adapter.metadata.key] = chiayi_adapter

    if (
        settings.source_chiayi_city_rainfall_api_enabled
        and "local.chiayi_city.rainfall" in enabled_keys
    ):
        chiayi_rainfall_adapter = ChiayiCityRainfallApiAdapter(
            api_url=settings.chiayi_city_rainfall_api_url,
            timeout_seconds=settings.local_water_timeout_seconds,
            fetched_at=fetched_at,
            fetch_text=chiayi_city_rainfall_fetch_text,
        )
        live_adapters[chiayi_rainfall_adapter.metadata.key] = chiayi_rainfall_adapter

    if (
        settings.source_taichung_water_level_api_enabled
        and "local.taichung.water_level" in enabled_keys
    ):
        taichung_adapter = TaichungWaterLevelApiAdapter(
            api_url=settings.taichung_water_level_api_url,
            timeout_seconds=settings.local_water_timeout_seconds,
            fetched_at=fetched_at,
            fetch_json=taichung_water_level_fetch_json,
        )
        live_adapters[taichung_adapter.metadata.key] = taichung_adapter

    if (
        settings.source_hsinchu_city_sewer_water_level_api_enabled
        and "local.hsinchu_city.sewer_water_level" in enabled_keys
    ):
        hsinchu_sewer_adapter = HsinchuCitySewerWaterLevelApiAdapter(
            base_api_url=settings.hsinchu_city_sewer_base_api_url,
            realtime_api_url=settings.hsinchu_city_sewer_realtime_api_url,
            timeout_seconds=settings.local_water_timeout_seconds,
            fetched_at=fetched_at,
            fetch_json=hsinchu_city_sewer_fetch_json,
        )
        live_adapters[hsinchu_sewer_adapter.metadata.key] = hsinchu_sewer_adapter

    if (
        settings.source_hsinchu_city_flood_sensor_api_enabled
        and "local.hsinchu_city.flood_sensor" in enabled_keys
    ):
        hsinchu_flood_adapter = HsinchuCityFloodSensorApiAdapter(
            station_api_url=settings.hsinchu_city_flood_sensor_station_api_url,
            realtime_api_url=settings.hsinchu_city_flood_sensor_realtime_api_url,
            timeout_seconds=settings.local_water_timeout_seconds,
            fetched_at=fetched_at,
            fetch_json=hsinchu_city_flood_sensor_fetch_json,
        )
        live_adapters[hsinchu_flood_adapter.metadata.key] = hsinchu_flood_adapter

    if (
        settings.source_nantou_sewer_water_level_api_enabled
        and "local.nantou.sewer_water_level" in enabled_keys
    ):
        nantou_adapter = NantouSewerWaterLevelKmlAdapter(
            kml_url=settings.nantou_sewer_water_level_kml_url,
            timeout_seconds=settings.local_water_timeout_seconds,
            fetched_at=fetched_at,
            fetch_text=nantou_sewer_water_level_fetch_text,
        )
        live_adapters[nantou_adapter.metadata.key] = nantou_adapter

    if (
        settings.source_chiayi_county_flood_sensor_api_enabled
        and "local.chiayi_county.flood_sensor" in enabled_keys
    ):
        chiayi_county_adapter = ChiayiCountyFloodSensorApiAdapter(
            api_url=settings.chiayi_county_flood_sensor_api_url,
            timeout_seconds=settings.local_water_timeout_seconds,
            fetched_at=fetched_at,
            fetch_json=chiayi_county_flood_sensor_fetch_json,
        )
        live_adapters[chiayi_county_adapter.metadata.key] = chiayi_county_adapter

    if (
        settings.source_kaohsiung_sewer_water_level_api_enabled
        and "local.kaohsiung.sewer_water_level" in enabled_keys
    ):
        kaohsiung_sewer_adapter = KaohsiungSewerWaterLevelApiAdapter(
            api_url=settings.kaohsiung_sewer_water_level_api_url,
            timeout_seconds=settings.local_water_timeout_seconds,
            fetched_at=fetched_at,
            fetch_json=kaohsiung_sewer_fetch_json,
        )
        live_adapters[kaohsiung_sewer_adapter.metadata.key] = kaohsiung_sewer_adapter

    if (
        settings.source_kaohsiung_flood_sensor_api_enabled
        and "local.kaohsiung.flood_sensor" in enabled_keys
    ):
        kaohsiung_flood_adapter = KaohsiungFloodSensorApiAdapter(
            api_url=settings.kaohsiung_flood_sensor_api_url,
            timeout_seconds=settings.local_water_timeout_seconds,
            fetched_at=fetched_at,
            fetch_json=kaohsiung_flood_sensor_fetch_json,
        )
        live_adapters[kaohsiung_flood_adapter.metadata.key] = kaohsiung_flood_adapter

    if (
        settings.source_kaohsiung_rainfall_api_enabled
        and "local.kaohsiung.rainfall" in enabled_keys
    ):
        kaohsiung_rainfall_adapter = KaohsiungRainfallApiAdapter(
            realtime_api_url=settings.kaohsiung_rainfall_rt_api_url,
            base_api_url=settings.kaohsiung_rainfall_base_api_url,
            timeout_seconds=settings.local_water_timeout_seconds,
            fetched_at=fetched_at,
            fetch_json=kaohsiung_rainfall_fetch_json,
        )
        live_adapters[kaohsiung_rainfall_adapter.metadata.key] = kaohsiung_rainfall_adapter

    if (
        settings.source_keelung_water_level_api_enabled
        and "local.keelung.water_level" in enabled_keys
    ):
        keelung_water_adapter = KeelungWaterLevelApiAdapter(
            api_url=settings.keelung_water_level_api_url,
            timeout_seconds=settings.local_water_timeout_seconds,
            fetched_at=fetched_at,
            fetch_json=keelung_water_level_fetch_json,
        )
        live_adapters[keelung_water_adapter.metadata.key] = keelung_water_adapter

    if (
        settings.source_keelung_flood_sensor_api_enabled
        and "local.keelung.flood_sensor" in enabled_keys
    ):
        keelung_flood_adapter = KeelungFloodSensorApiAdapter(
            api_url=settings.keelung_flood_sensor_api_url,
            timeout_seconds=settings.local_water_timeout_seconds,
            fetched_at=fetched_at,
            fetch_json=keelung_flood_sensor_fetch_json,
        )
        live_adapters[keelung_flood_adapter.metadata.key] = keelung_flood_adapter

    if (
        settings.source_keelung_rainfall_api_enabled
        and "local.keelung.rainfall" in enabled_keys
    ):
        keelung_rainfall_adapter = KeelungRainfallApiAdapter(
            api_url=settings.keelung_rainfall_api_url,
            timeout_seconds=settings.local_water_timeout_seconds,
            fetched_at=fetched_at,
            fetch_json=keelung_rainfall_fetch_json,
        )
        live_adapters[keelung_rainfall_adapter.metadata.key] = keelung_rainfall_adapter

    if (
        settings.source_yunlin_water_level_api_enabled
        and "local.yunlin.water_level" in enabled_keys
    ):
        yunlin_water_adapter = YunlinWaterLevelApiAdapter(
            api_url=settings.yunlin_stations_api_url,
            timeout_seconds=settings.local_water_timeout_seconds,
            fetched_at=fetched_at,
            fetch_json=yunlin_water_level_fetch_json,
        )
        live_adapters[yunlin_water_adapter.metadata.key] = yunlin_water_adapter

    if (
        settings.source_yilan_flood_sensor_api_enabled
        and "local.yilan.flood_sensor" in enabled_keys
    ):
        yilan_flood_adapter = YilanFloodSensorArcgisAdapter(
            api_url=settings.yilan_flood_sensor_layer_url,
            timeout_seconds=settings.local_water_timeout_seconds,
            fetched_at=fetched_at,
            fetch_json=yilan_flood_sensor_fetch_json,
        )
        live_adapters[yilan_flood_adapter.metadata.key] = yilan_flood_adapter

    if (
        settings.source_yilan_water_level_api_enabled
        and "local.yilan.water_level" in enabled_keys
    ):
        yilan_water_level_adapter = YilanWaterLevelArcgisAdapter(
            api_url=settings.yilan_water_level_layer_url,
            timeout_seconds=settings.local_water_timeout_seconds,
            fetched_at=fetched_at,
            fetch_json=yilan_water_level_fetch_json,
        )
        live_adapters[yilan_water_level_adapter.metadata.key] = yilan_water_level_adapter

    if (
        settings.source_penghu_water_level_api_enabled
        and "local.penghu.water_level" in enabled_keys
    ):
        penghu_water_level_adapter = PenghuWaterLevelArcgisAdapter(
            api_url=settings.penghu_water_level_layer_url,
            timeout_seconds=settings.local_water_timeout_seconds,
            fetched_at=fetched_at,
            fetch_json=penghu_water_level_fetch_json,
        )
        live_adapters[penghu_water_level_adapter.metadata.key] = penghu_water_level_adapter

    fhy_api_gates = {
        HSINCHU_COUNTY_FHY_FLOOD_SENSOR.metadata.key: (
            settings.source_hsinchu_county_fhy_flood_sensor_api_enabled
        ),
        MIAOLI_FHY_FLOOD_SENSOR.metadata.key: settings.source_miaoli_fhy_flood_sensor_api_enabled,
        CHANGHUA_FHY_FLOOD_SENSOR.metadata.key: (
            settings.source_changhua_fhy_flood_sensor_api_enabled
        ),
        PINGTUNG_FHY_FLOOD_SENSOR.metadata.key: (
            settings.source_pingtung_fhy_flood_sensor_api_enabled
        ),
        HUALIEN_FHY_FLOOD_SENSOR.metadata.key: settings.source_hualien_fhy_flood_sensor_api_enabled,
        TAITUNG_FHY_FLOOD_SENSOR.metadata.key: settings.source_taitung_fhy_flood_sensor_api_enabled,
    }
    for fhy_source in FHY_LOCAL_FLOOD_SENSOR_SOURCES:
        if fhy_api_gates[fhy_source.metadata.key] and fhy_source.metadata.key in enabled_keys:
            fhy_adapter = FhyFloodSensorApiAdapter(
                fhy_source,
                station_api_url=settings.fhy_flood_sensor_station_api_url,
                realtime_api_url=settings.fhy_flood_sensor_realtime_api_url,
                timeout_seconds=settings.local_water_timeout_seconds,
                fetched_at=fetched_at,
                fetch_json=fhy_flood_sensor_fetch_json,
            )
            live_adapters[fhy_adapter.metadata.key] = fhy_adapter

    if (
        settings.source_civil_iot_river_api_enabled
        and "official.civil_iot.river_water_level" in enabled_keys
    ):
        civil_iot_river_adapter = CivilIotRiverApiAdapter(
            sta_url=settings.civil_iot_river_url,
            timeout_seconds=settings.civil_iot_api_timeout_seconds,
            fetched_at=fetched_at,
            fetch_json=civil_iot_river_fetch_json,
        )
        live_adapters[civil_iot_river_adapter.metadata.key] = civil_iot_river_adapter

    for sta_source, api_enabled, sta_url, fetch_json in (
        (
            POND_WATER_LEVEL,
            settings.source_civil_iot_pond_api_enabled,
            settings.civil_iot_pond_url,
            civil_iot_pond_fetch_json,
        ),
        (
            SEWER_WATER_LEVEL,
            settings.source_civil_iot_sewer_api_enabled,
            settings.civil_iot_sewer_url,
            civil_iot_sewer_fetch_json,
        ),
        (
            PUMP_WATER_LEVEL,
            settings.source_civil_iot_pump_api_enabled,
            settings.civil_iot_pump_url,
            civil_iot_pump_fetch_json,
        ),
        (
            GATE_WATER_LEVEL,
            settings.source_civil_iot_gate_api_enabled,
            settings.civil_iot_gate_url,
            civil_iot_gate_fetch_json,
        ),
    ):
        if api_enabled and sta_source.metadata.key in enabled_keys:
            water_level_adapter = StaWaterLevelApiAdapter(
                sta_source,
                sta_url=sta_url,
                timeout_seconds=settings.civil_iot_api_timeout_seconds,
                fetched_at=fetched_at,
                fetch_json=fetch_json,
            )
            live_adapters[water_level_adapter.metadata.key] = water_level_adapter

    if not live_adapters:
        log_event(
            "runtime.adapters.noop",
            reason="runtime_sources_disabled",
            enabled_adapter_keys=enabled_keys,
            cwa_api_enabled=settings.source_cwa_api_enabled,
            wra_api_enabled=settings.source_wra_api_enabled,
            ncdr_cap_api_enabled=settings.source_ncdr_cap_api_enabled,
            flood_potential_geojson_enabled=settings.source_flood_potential_geojson_enabled,
            flood_sensor_api_enabled=settings.source_flood_sensor_api_enabled,
            flood_sensor_use_live=settings.source_flood_sensor_use_live,
            tainan_flood_sensor_api_enabled=settings.source_tainan_flood_sensor_api_enabled,
            civil_iot_river_api_enabled=settings.source_civil_iot_river_api_enabled,
            civil_iot_gate_api_enabled=settings.source_civil_iot_gate_api_enabled,
        )
        return {}

    log_event(
        "runtime.adapters.live_mode.enabled",
        available_adapter_keys=tuple(live_adapters),
        flood_sensor_source_intent="civil_iot_official_national_backbone",
    )
    return live_adapters


def enqueue_enabled_runtime_adapter_jobs(
    settings: WorkerSettings,
    *,
    queue: RuntimeQueue | None = None,
    job_key: str = "runtime.adapter.ingest",
) -> tuple[str, ...]:
    return produce_enabled_runtime_adapter_jobs(
        settings,
        queue=queue,
        job_key=job_key,
    ).job_ids


def produce_enabled_runtime_adapter_jobs(
    settings: WorkerSettings,
    *,
    queue: RuntimeQueue | None = None,
    job_key: str = "runtime.adapter.ingest",
    queue_name: str = "runtime-adapters",
) -> RuntimeQueueProducerResult:
    runnable_adapters = build_runtime_adapters(settings)
    enabled_keys = enabled_adapter_keys(settings)
    adapter_keys = tuple(key for key in enabled_keys if key in runnable_adapters)
    if not adapter_keys:
        reason = "no_enabled_adapters" if not enabled_keys else "no_runnable_adapters"
        log_event(
            "runtime.queue.enqueue.noop",
            reason=reason,
            enabled_adapter_keys=enabled_keys,
        )
        return RuntimeQueueProducerResult(status="skipped", reason=reason)

    if queue is None and not settings.database_url:
        log_event(
            "runtime.queue.enqueue.noop",
            reason="no_database_url",
            adapter_count=len(adapter_keys),
        )
        return RuntimeQueueProducerResult(
            status="skipped",
            adapter_keys=adapter_keys,
            reason="no_database_url",
        )

    runtime_queue = queue or (
        PostgresRuntimeQueue(database_url=settings.database_url)
        if settings.database_url
        else NullRuntimeQueue()
    )
    job_ids: list[str] = []
    enqueued_job_ids: list[str] = []
    deduped_job_ids: list[str] = []
    dedupe_keys: list[str] = []
    try:
        for adapter_key in adapter_keys:
            dedupe_key = _runtime_adapter_dedupe_key(
                queue_name=queue_name,
                job_key=job_key,
                adapter_key=adapter_key,
            )
            enqueue_result = runtime_queue.enqueue_adapter_job(
                adapter_key=adapter_key,
                job_key=job_key,
                queue_name=queue_name,
                payload={"adapter_key": adapter_key},
                dedupe_key=dedupe_key,
            )
            dedupe_keys.append(dedupe_key)
            if enqueue_result.job_id is not None:
                job_ids.append(enqueue_result.job_id)
                if enqueue_result.status == "enqueued":
                    enqueued_job_ids.append(enqueue_result.job_id)
                elif enqueue_result.status == "deduped":
                    deduped_job_ids.append(enqueue_result.job_id)
    except RuntimeQueueUnavailable as exc:
        log_event("runtime.queue.enqueue.unavailable", error=str(exc))
        return RuntimeQueueProducerResult(
            status="skipped",
            adapter_keys=adapter_keys,
            job_ids=tuple(job_ids),
            enqueued_job_ids=tuple(enqueued_job_ids),
            deduped_job_ids=tuple(deduped_job_ids),
            dedupe_keys=tuple(dedupe_keys),
            reason="queue_unavailable",
        )

    log_event(
        "runtime.queue.enqueue.completed",
        adapter_count=len(adapter_keys),
        durable_job_count=len(job_ids),
        enqueued_job_count=len(enqueued_job_ids),
        deduped_job_count=len(deduped_job_ids),
    )
    if not job_ids:
        return RuntimeQueueProducerResult(
            status="skipped",
            adapter_keys=adapter_keys,
            dedupe_keys=tuple(dedupe_keys),
            reason="no_durable_jobs",
        )
    if not enqueued_job_ids and deduped_job_ids:
        return RuntimeQueueProducerResult(
            status="deduped",
            adapter_keys=adapter_keys,
            job_ids=tuple(job_ids),
            enqueued_job_ids=tuple(enqueued_job_ids),
            deduped_job_ids=tuple(deduped_job_ids),
            dedupe_keys=tuple(dedupe_keys),
            reason="active_jobs_already_exist",
        )
    return RuntimeQueueProducerResult(
        status="succeeded",
        adapter_keys=adapter_keys,
        job_ids=tuple(job_ids),
        enqueued_job_ids=tuple(enqueued_job_ids),
        deduped_job_ids=tuple(deduped_job_ids),
        dedupe_keys=tuple(dedupe_keys),
    )


def dequeue_runtime_adapter_job(
    settings: WorkerSettings,
    *,
    queue: RuntimeQueue | None = None,
    queue_name: str = "runtime-adapters",
    worker_id: str | None = None,
) -> RuntimeQueueJob | None:
    runtime_queue = queue or (
        PostgresRuntimeQueue(database_url=settings.database_url)
        if settings.database_url
        else NullRuntimeQueue()
    )
    try:
        return runtime_queue.dequeue_adapter_job(
            queue_name=queue_name,
            worker_id=worker_id or settings.metrics_instance,
            lease_seconds=settings.runtime_job_lease_seconds,
        )
    except RuntimeQueueUnavailable as exc:
        log_event("runtime.queue.dequeue.unavailable", error=str(exc))
        return None


def mark_runtime_adapter_job_succeeded(
    settings: WorkerSettings,
    *,
    job_id: str,
    queue: RuntimeQueue | None = None,
    worker_id: str | None = None,
) -> bool:
    runtime_queue = queue or (
        PostgresRuntimeQueue(database_url=settings.database_url)
        if settings.database_url
        else NullRuntimeQueue()
    )
    try:
        updated = runtime_queue.mark_job_succeeded(
            job_id=job_id,
            worker_id=worker_id or settings.metrics_instance,
        )
    except RuntimeQueueUnavailable as exc:
        log_event("runtime.queue.complete.unavailable", error=str(exc), status="succeeded")
        return False

    log_event("runtime.queue.complete", job_id=job_id, status="succeeded", updated=updated)
    return updated


def mark_runtime_adapter_job_failed(
    settings: WorkerSettings,
    *,
    job_id: str,
    error: str,
    retry_delay_seconds: int = 60,
    queue: RuntimeQueue | None = None,
    worker_id: str | None = None,
) -> bool:
    runtime_queue = queue or (
        PostgresRuntimeQueue(database_url=settings.database_url)
        if settings.database_url
        else NullRuntimeQueue()
    )
    try:
        updated = runtime_queue.mark_job_failed(
            job_id=job_id,
            worker_id=worker_id or settings.metrics_instance,
            error=error,
            retry_delay_seconds=retry_delay_seconds,
        )
    except RuntimeQueueUnavailable as exc:
        log_event("runtime.queue.complete.unavailable", error=str(exc), status="failed")
        return False

    log_event("runtime.queue.complete", job_id=job_id, status="failed", updated=updated)
    return updated


def work_runtime_queue_once(
    *,
    settings: WorkerSettings | None = None,
    queue: RuntimeQueue | None = None,
    adapter_by_key: Mapping[str, DataSourceAdapter] | None = None,
    writer: StagingBatchWriter | None = None,
    run_writer: IngestionRunSummaryWriter | None = None,
    promotion_writer: EvidencePromotionWriter | None = None,
    promote: bool = False,
    queue_name: str = "runtime-adapters",
    worker_id: str | None = None,
    retry_delay_seconds: int = 60,
) -> RuntimeQueueWorkerResult:
    resolved_settings = settings or load_worker_settings()
    resolved_worker_id = worker_id or resolved_settings.metrics_instance
    if queue is None and not resolved_settings.database_url:
        log_event(
            "runtime.queue.worker.noop",
            reason="no_database_url",
            queue_name=queue_name,
            worker_id=resolved_worker_id,
        )
        return RuntimeQueueWorkerResult(status="skipped", reason="no_database_url")

    if queue is not None:
        runtime_queue = queue
    else:
        assert resolved_settings.database_url is not None
        runtime_queue = PostgresRuntimeQueue(database_url=resolved_settings.database_url)
    try:
        job = runtime_queue.dequeue_adapter_job(
            queue_name=queue_name,
            worker_id=resolved_worker_id,
            lease_seconds=resolved_settings.runtime_job_lease_seconds,
        )
    except RuntimeQueueUnavailable as exc:
        log_event(
            "runtime.queue.worker.noop",
            reason="queue_unavailable",
            queue_name=queue_name,
            worker_id=resolved_worker_id,
            error=str(exc),
        )
        return RuntimeQueueWorkerResult(status="skipped", reason="queue_unavailable")

    if job is None:
        log_event(
            "runtime.queue.worker.noop",
            reason="no_job",
            queue_name=queue_name,
            worker_id=resolved_worker_id,
        )
        return RuntimeQueueWorkerResult(status="skipped", reason="no_job")

    adapter_key = _job_adapter_key(job)
    if adapter_key is None:
        return _fail_runtime_queue_job(
            resolved_settings,
            queue=runtime_queue,
            job=job,
            worker_id=resolved_worker_id,
            adapter_key=None,
            error="runtime queue job is missing adapter_key",
            retry_delay_seconds=retry_delay_seconds,
        )

    try:
        adapters = (
            adapter_by_key
            if adapter_by_key is not None
            else build_runtime_adapters(resolved_settings)
        )
        adapter = adapters.get(adapter_key)
        if adapter is None:
            return _fail_runtime_queue_job(
                resolved_settings,
                queue=runtime_queue,
                job=job,
                worker_id=resolved_worker_id,
                adapter_key=adapter_key,
                error=f"unknown runtime adapter_key: {adapter_key}",
                retry_delay_seconds=retry_delay_seconds,
            )

        summary = run_adapter_batch(
            adapter,
            job_key=job.job_key,
            writer=writer,
            run_writer=run_writer,
            parameters={
                "runtime_queue_job_id": job.id,
                "runtime_queue_name": job.queue_name,
                "payload": dict(job.payload),
            },
        )
        freshness_checks = check_batch_freshness(
            (summary,),
            max_age_seconds=resolved_settings.freshness_max_age_seconds,
        )
        failure_reason = _runtime_cycle_failure_reason(summary, freshness_checks)
        if failure_reason is not None:
            return _fail_runtime_queue_job(
                resolved_settings,
                queue=runtime_queue,
                job=job,
                worker_id=resolved_worker_id,
                adapter_key=adapter_key,
                error=failure_reason,
                retry_delay_seconds=retry_delay_seconds,
                summary=summary,
                freshness_checks=freshness_checks,
            )
        promotion = PromotionResult(promoted=0, evidence_ids=())
        if promote:
            promotion = promote_accepted_staging(
                _runtime_promotion_writer(promotion_writer),
                adapter_keys=(adapter_key,),
            )
    except Exception as exc:
        return _fail_runtime_queue_job(
            resolved_settings,
            queue=runtime_queue,
            job=job,
            worker_id=resolved_worker_id,
            adapter_key=adapter_key,
            error=f"{exc.__class__.__name__}: {exc}",
            retry_delay_seconds=retry_delay_seconds,
        )

    updated = mark_runtime_adapter_job_succeeded(
        resolved_settings,
        job_id=job.id,
        queue=runtime_queue,
        worker_id=resolved_worker_id,
    )
    if not updated:
        log_event(
            "runtime.queue.worker.completion_not_updated",
            job_id=job.id,
            adapter_key=adapter_key,
            status="failed",
            updated=updated,
        )
        return RuntimeQueueWorkerResult(
            status="failed",
            job_id=job.id,
            adapter_key=adapter_key,
            reason="queue_completion_not_updated",
            summary=summary,
            freshness_checks=freshness_checks,
            promoted=promotion.promoted,
            evidence_ids=promotion.evidence_ids,
        )
    log_event(
        "runtime.queue.worker.completed",
        job_id=job.id,
        adapter_key=adapter_key,
        status="succeeded",
        updated=updated,
        promoted=promotion.promoted,
    )
    return RuntimeQueueWorkerResult(
        status="succeeded",
        job_id=job.id,
        adapter_key=adapter_key,
        summary=summary,
        freshness_checks=freshness_checks,
        promoted=promotion.promoted,
        evidence_ids=promotion.evidence_ids,
    )


def build_runtime_persistence_writers(
    database_url: str,
) -> tuple[StagingBatchWriter, IngestionRunSummaryWriter, EvidencePromotionWriter]:
    return (
        PostgresStagingBatchWriter(database_url=database_url),
        PostgresIngestionRunWriter(database_url=database_url),
        PostgresEvidencePromotionWriter(database_url=database_url),
    )


def _job_adapter_key(job: RuntimeQueueJob) -> str | None:
    if job.adapter_key:
        return job.adapter_key
    payload_adapter_key = job.payload.get("adapter_key")
    if isinstance(payload_adapter_key, str) and payload_adapter_key.strip():
        return payload_adapter_key.strip()
    return None


def _runtime_adapter_dedupe_key(
    *,
    queue_name: str,
    job_key: str,
    adapter_key: str,
) -> str:
    return f"{queue_name}:{job_key}:{adapter_key}"


def _runtime_cycle_failure_reason(
    summary: AdapterBatchRunSummary,
    freshness_checks: tuple[FreshnessCheck, ...],
) -> str | None:
    if summary.status == "failed":
        return summary.error_message or summary.error_code or "adapter batch failed"

    alert = next((check for check in freshness_checks if check.is_alert()), None)
    if alert is not None:
        return alert.reason or f"freshness check {alert.status}"
    return None


def _runtime_promotion_writer(
    promotion_writer: EvidencePromotionWriter | None,
) -> EvidencePromotionWriter:
    if promotion_writer is None:
        raise RuntimeError("promotion_writer is required when promote=True")
    return promotion_writer


def _fail_runtime_queue_job(
    settings: WorkerSettings,
    *,
    queue: RuntimeQueue,
    job: RuntimeQueueJob,
    worker_id: str,
    adapter_key: str | None,
    error: str,
    retry_delay_seconds: int,
    summary: AdapterBatchRunSummary | None = None,
    freshness_checks: tuple[FreshnessCheck, ...] = (),
) -> RuntimeQueueWorkerResult:
    updated = mark_runtime_adapter_job_failed(
        settings,
        job_id=job.id,
        error=error,
        retry_delay_seconds=retry_delay_seconds,
        queue=queue,
        worker_id=worker_id,
    )
    log_event(
        "runtime.queue.worker.completed",
        job_id=job.id,
        adapter_key=adapter_key,
        status="failed",
        error=error[:1000],
        updated=updated,
    )
    return RuntimeQueueWorkerResult(
        status="failed",
        job_id=job.id,
        adapter_key=adapter_key,
        reason=error,
        summary=summary,
        freshness_checks=freshness_checks,
    )
