from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.adapters.contracts import EventType, SourceFamily
from app.adapters.local_kaohsiung import (
    KAOHSIUNG_FLOOD_SENSOR_API_URL,
    KAOHSIUNG_SEWER_WATER_LEVEL_API_URL,
    KaohsiungFloodSensorApiAdapter,
    KaohsiungSewerWaterLevelApiAdapter,
)
from app.adapters.local_yilan import (
    YILAN_FLOOD_SENSOR_LAYER_URL,
    YILAN_WATER_LEVEL_LAYER_URL,
    YilanFloodSensorArcgisAdapter,
    YilanWaterLevelArcgisAdapter,
)
from app.config import load_worker_settings
from app.jobs.runtime import build_runtime_adapters


FETCHED_AT = datetime(2026, 6, 28, 8, 45, tzinfo=UTC)


def _kaohsiung_sewer_payload() -> list[dict[str, Any]]:
    return [
        {
            "basin": "寶珠溝排水",
            "lat": 22.643807,
            "lon": 120.320786,
            "source": "水利局",
            "stage": 2.182,
            "stn_name": "民族國小",
            "stn_no": "KCRS012C",
            "time": "2026-06-28 16:30:00",
            "voltage": 7.29,
            "warn_Level1": 5.257,
            "warn_level2": 3.994,
        }
        ,
        {
            "basin": "測試排水",
            "lat": 22.65,
            "lon": 120.33,
            "source": "水利局",
            "stage": 1.2,
            "stn_name": "未來時間站",
            "stn_no": "FUTURE001",
            "time": "2027-06-19 11:07:00",
            "warn_Level1": 5.0,
            "warn_level2": 3.0,
        },
    ]


def _kaohsiung_flood_payload() -> list[dict[str, Any]]:
    return [
        {
            "lat": 22.89857,
            "lon": 120.53998,
            "obs_value": 8.0,
            "source": "經濟部水利署第七河川局",
            "stn_id": "3132017FL4001",
            "stn_name": "美濃區_天后宮",
            "time": "2026-06-28 16:41:32",
            "town": "美濃區",
            "uuid": {"depth": "aad74e1c-7789-496d-b1e3-ef45d8b6e218"},
        }
    ]


def _yilan_flood_layer_payload() -> dict[str, Any]:
    return {
        "features": [
            {
                "attributes": {
                    "st_no": "000060flood00001",
                    "名稱": "冬山鄉九分二路",
                    "鄉鎮": "冬山鄉",
                    "E": 121.7820847,
                    "N": 24.6646528,
                    "water_inner": 6.0,
                    "縣府編號": "FP1031",
                    "warn_lv1": 30.0,
                    "warn_lv2": 10.0,
                    "warn_lv3": 5.0,
                    "write_date": 1782629820000,
                    "警戒等級": "6公分",
                }
            }
        ]
    }


def _yilan_water_level_layer_payload() -> dict[str, Any]:
    return {
        "features": [
            {
                "attributes": {
                    "g_num": "LR1033",
                    "st_name": "大坑罟防潮閘門內水位",
                    "E": 121.827356,
                    "N": 24.8519241,
                    "st_id": "WG_R_W_00040",
                    "st_no": "WG_R_W_00040",
                    "water_inner": 0.424,
                    "write_date": 1782635760000,
                    "war": "無警戒",
                    "war_ele": 2.689,
                    "影像路徑": "https://wrd1.unioncatv.com.tw/QCHLSLive.cgi?cam=75",
                }
            }
        ]
    }


def test_kaohsiung_sewer_json_outputs_water_level_warning_metrics() -> None:
    adapter = KaohsiungSewerWaterLevelApiAdapter(
        fetched_at=FETCHED_AT,
        fetch_json=lambda url, timeout: _kaohsiung_sewer_payload(),
    )

    result = adapter.run()

    assert result.adapter_key == "local.kaohsiung.sewer_water_level"
    assert len(result.fetched) == 2
    assert len(result.normalized) == 1
    assert result.rejected == ("FUTURE001:2027-06-19T03:07:00+00:00",)
    raw_payload = result.fetched[0].payload
    assert raw_payload["station_id"] == "KCRS012C"
    assert raw_payload["station_name"] == "民族國小"
    assert raw_payload["observed_at"] == "2026-06-28T08:30:00+00:00"
    assert raw_payload["water_level_m"] == 2.182
    assert raw_payload["warning_level_m"] == 3.994
    assert raw_payload["red_alert_level_m"] == 5.257
    assert raw_payload["geometry"] == {
        "type": "Point",
        "coordinates": [120.320786, 22.643807],
    }
    evidence = result.normalized[0]
    assert evidence.event_type is EventType.WATER_LEVEL
    assert evidence.source_family is SourceFamily.OFFICIAL
    assert "2.18 公尺" in evidence.summary
    assert "local_kaohsiung" in evidence.tags
    assert "sewer_water_level" in evidence.tags


def test_kaohsiung_flood_json_outputs_flood_depth() -> None:
    adapter = KaohsiungFloodSensorApiAdapter(
        fetched_at=FETCHED_AT,
        fetch_json=lambda url, timeout: _kaohsiung_flood_payload(),
    )

    result = adapter.run()

    assert result.adapter_key == "local.kaohsiung.flood_sensor"
    assert len(result.normalized) == 1
    raw_payload = result.fetched[0].payload
    assert raw_payload["station_id"] == "3132017FL4001"
    assert raw_payload["station_name"] == "美濃區_天后宮"
    assert raw_payload["observed_at"] == "2026-06-28T08:41:32+00:00"
    assert raw_payload["flood_depth_cm"] == 8.0
    assert raw_payload["town"] == "美濃區"
    assert raw_payload["geometry"] == {
        "type": "Point",
        "coordinates": [120.53998, 22.89857],
    }
    evidence = result.normalized[0]
    assert evidence.event_type is EventType.FLOOD_REPORT
    assert "水深 8 公分" in evidence.summary
    assert "local_kaohsiung" in evidence.tags


def test_yilan_arcgis_flood_layer_outputs_flood_depth() -> None:
    adapter = YilanFloodSensorArcgisAdapter(
        fetched_at=FETCHED_AT,
        fetch_json=lambda url, timeout: _yilan_flood_layer_payload(),
    )

    result = adapter.run()

    assert result.adapter_key == "local.yilan.flood_sensor"
    assert len(result.normalized) == 1
    raw_payload = result.fetched[0].payload
    assert raw_payload["station_id"] == "000060flood00001"
    assert raw_payload["station_name"] == "冬山鄉九分二路"
    assert raw_payload["observed_at"] == "2026-06-28T06:57:00+00:00"
    assert raw_payload["flood_depth_cm"] == 6.0
    assert raw_payload["town"] == "冬山鄉"
    assert raw_payload["warning_level_cm"] == 10.0
    assert raw_payload["red_alert_level_cm"] == 30.0
    assert raw_payload["geometry"] == {
        "type": "Point",
        "coordinates": [121.7820847, 24.6646528],
    }
    evidence = result.normalized[0]
    assert evidence.event_type is EventType.FLOOD_REPORT
    assert "水深 6 公分" in evidence.summary
    assert "local_yilan" in evidence.tags


def test_yilan_arcgis_water_level_layer_outputs_water_level() -> None:
    adapter = YilanWaterLevelArcgisAdapter(
        fetched_at=FETCHED_AT,
        fetch_json=lambda url, timeout: _yilan_water_level_layer_payload(),
    )

    result = adapter.run()

    assert result.adapter_key == "local.yilan.water_level"
    assert len(result.normalized) == 1
    raw_payload = result.fetched[0].payload
    assert raw_payload["station_id"] == "WG_R_W_00040"
    assert raw_payload["station_name"] == "大坑罟防潮閘門內水位"
    assert raw_payload["observed_at"] == "2026-06-28T08:36:00+00:00"
    assert raw_payload["water_level_m"] == 0.424
    assert raw_payload["warning_level_m"] == 2.689
    assert raw_payload["geometry"] == {
        "type": "Point",
        "coordinates": [121.827356, 24.8519241],
    }
    evidence = result.normalized[0]
    assert evidence.event_type is EventType.WATER_LEVEL
    assert "0.42 公尺" in evidence.summary
    assert "local_yilan" in evidence.tags


def test_build_runtime_adapters_wires_kaohsiung_and_yilan_sources_when_gates_are_on() -> None:
    settings = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": (
                "local.kaohsiung.sewer_water_level,local.kaohsiung.flood_sensor,"
                "local.yilan.flood_sensor,local.yilan.water_level"
            ),
            "SOURCE_KAOHSIUNG_SEWER_WATER_LEVEL_ENABLED": "true",
            "SOURCE_KAOHSIUNG_SEWER_WATER_LEVEL_API_ENABLED": "true",
            "SOURCE_KAOHSIUNG_FLOOD_SENSOR_ENABLED": "true",
            "SOURCE_KAOHSIUNG_FLOOD_SENSOR_API_ENABLED": "true",
            "SOURCE_YILAN_FLOOD_SENSOR_ENABLED": "true",
            "SOURCE_YILAN_FLOOD_SENSOR_API_ENABLED": "true",
            "SOURCE_YILAN_WATER_LEVEL_ENABLED": "true",
            "SOURCE_YILAN_WATER_LEVEL_API_ENABLED": "true",
            "LOCAL_WATER_TIMEOUT_SECONDS": "5",
        }
    )

    adapters = build_runtime_adapters(
        settings,
        fetched_at=FETCHED_AT,
        kaohsiung_sewer_fetch_json=lambda url, timeout: _kaohsiung_sewer_payload(),
        kaohsiung_flood_sensor_fetch_json=lambda url, timeout: _kaohsiung_flood_payload(),
        yilan_flood_sensor_fetch_json=lambda url, timeout: _yilan_flood_layer_payload(),
        yilan_water_level_fetch_json=lambda url, timeout: _yilan_water_level_layer_payload(),
    )

    assert tuple(adapters) == (
        "local.kaohsiung.sewer_water_level",
        "local.kaohsiung.flood_sensor",
        "local.yilan.flood_sensor",
        "local.yilan.water_level",
    )
    assert len(adapters["local.kaohsiung.sewer_water_level"].run().normalized) == 1
    assert len(adapters["local.kaohsiung.flood_sensor"].run().normalized) == 1
    assert len(adapters["local.yilan.flood_sensor"].run().normalized) == 1
    assert len(adapters["local.yilan.water_level"].run().normalized) == 1
    assert KAOHSIUNG_SEWER_WATER_LEVEL_API_URL.startswith("https://wrbswi.kcg.gov.tw/")
    assert KAOHSIUNG_FLOOD_SENSOR_API_URL.startswith("https://wrbswi.kcg.gov.tw/")
    assert YILAN_FLOOD_SENSOR_LAYER_URL.startswith("https://wragis.e-land.gov.tw/")
    assert YILAN_WATER_LEVEL_LAYER_URL.startswith("https://wragis.e-land.gov.tw/")
