from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.adapters.contracts import EventType, SourceFamily
from app.adapters.local_new_taipei import (
    NEW_TAIPEI_DRAINAGE_WATER_LEVEL_API_URL,
    NEW_TAIPEI_FLOOD_SENSOR_API_URL,
    NEW_TAIPEI_RAINFALL_API_URL,
    NEW_TAIPEI_WATER_LEVEL_API_URL,
    NewTaipeiDrainageWaterLevelApiAdapter,
    NewTaipeiFloodSensorApiAdapter,
    NewTaipeiRainfallApiAdapter,
    NewTaipeiWaterLevelApiAdapter,
)
from app.config import load_worker_settings
from app.jobs.runtime import build_runtime_adapters


FETCHED_AT = datetime(2026, 6, 28, 9, 30, tzinfo=UTC)


def _new_taipei_water_payload() -> list[dict[str, Any]]:
    return [
        {
            "st_no": "NTPC-WL-001",
            "st_name": "中和區瓦磘溝水位站",
            "lon": 121.50312,
            "lat": 24.99321,
            "datatime": "2026-06-28 17:16:00",
            "sendtime": "2026-06-28 17:16:28",
            "water_inner": 0.76,
            "warn_lv1": 1.50,
            "warn_lv2": 1.20,
            "warn_lv3": 0.90,
            "batteryvol": 4.11,
            "city": "新北市",
            "town": "中和區",
            "village": "瓦磘里",
            "river": "瓦磘溝",
            "status": "正常",
            "source": "新北市",
            "device_type": "water",
        }
    ]


def _new_taipei_flood_payload() -> list[dict[str, Any]]:
    return [
        {
            "st_no": "NTPC-FLD-001",
            "st_name": "三重區重新路五段",
            "lon": 121.46978,
            "lat": 25.04654,
            "datatime": "2026-06-28 17:20:00",
            "water_inner": 6.0,
            "warn_lv1": 30.0,
            "warn_lv2": 10.0,
            "batteryvol": 4.02,
            "city": "新北市",
            "town": "三重區",
            "village": "中興里",
            "status": "正常",
            "source": "新北市",
            "device_type": "flood",
        }
    ]


def _new_taipei_rainfall_payload() -> list[dict[str, Any]]:
    return [
        {
            "st_no": "NTPC-RF-001",
            "st_name": "汐止區保長坑雨量站",
            "lon": 121.66014,
            "lat": 25.07446,
            "datatime": "2026-06-28 17:23:00",
            "rain": 1.5,
            "min_10": 0.5,
            "min_30": 1.5,
            "hour_3": 4.0,
            "hour_6": 7.0,
            "hour_12": 12.0,
            "hour_24": 18.0,
            "city": "新北市",
            "town": "汐止區",
            "status": "正常",
            "source": "新北市",
        },
        {
            "st_no": "NTPC-RF-OLD",
            "st_name": "舊雨量站",
            "lon": 121.60,
            "lat": 25.10,
            "datatime": "2026-06-27 10:00:00",
            "rain": 0.0,
        },
    ]


def _new_taipei_drainage_payload() -> list[dict[str, Any]]:
    return [
        {
            "st_no": "NTPC-DR-001",
            "st_name": "板橋區民生路排水水位站",
            "lon": 121.47156,
            "lat": 25.01715,
            "datatime": "2026-06-28 17:22:00",
            "water_inner": 0.42,
            "warn_lv1": 1.20,
            "warn_lv2": 0.90,
            "warn_lv3": 0.70,
            "city": "新北市",
            "town": "板橋區",
            "village": "海山里",
            "status": "正常",
            "source": "新北市",
            "cctv_url": "https://example.test/cctv",
        }
    ]


def test_new_taipei_water_json_outputs_local_water_level() -> None:
    adapter = NewTaipeiWaterLevelApiAdapter(
        fetched_at=FETCHED_AT,
        fetch_json=lambda url, timeout: _new_taipei_water_payload(),
    )

    result = adapter.run()

    assert result.adapter_key == "local.new_taipei.water_level"
    assert len(result.normalized) == 1
    raw_payload = result.fetched[0].payload
    assert raw_payload["station_id"] == "NTPC-WL-001"
    assert raw_payload["observed_at"] == "2026-06-28T09:16:00+00:00"
    assert raw_payload["water_level_m"] == 0.76
    assert raw_payload["warning_level_m"] == 1.2
    assert raw_payload["red_alert_level_m"] == 1.5
    assert raw_payload["town"] == "中和區"
    assert raw_payload["geometry"] == {
        "type": "Point",
        "coordinates": [121.50312, 24.99321],
    }
    evidence = result.normalized[0]
    assert evidence.event_type is EventType.WATER_LEVEL
    assert evidence.source_family is SourceFamily.OFFICIAL
    assert "0.76 公尺" in evidence.summary
    assert "local_new_taipei" in evidence.tags
    assert "water_level" in evidence.tags


def test_new_taipei_flood_json_outputs_local_flood_depth() -> None:
    adapter = NewTaipeiFloodSensorApiAdapter(
        fetched_at=FETCHED_AT,
        fetch_json=lambda url, timeout: _new_taipei_flood_payload(),
    )

    result = adapter.run()

    assert result.adapter_key == "local.new_taipei.flood_sensor"
    assert len(result.normalized) == 1
    raw_payload = result.fetched[0].payload
    assert raw_payload["station_id"] == "NTPC-FLD-001"
    assert raw_payload["observed_at"] == "2026-06-28T09:20:00+00:00"
    assert raw_payload["flood_depth_cm"] == 6.0
    assert raw_payload["warning_level_cm"] == 10.0
    assert raw_payload["red_alert_level_cm"] == 30.0
    evidence = result.normalized[0]
    assert evidence.event_type is EventType.FLOOD_REPORT
    assert "水深 6 公分" in evidence.summary
    assert "local_new_taipei" in evidence.tags


def test_new_taipei_rainfall_json_outputs_rainfall_and_rejects_stale_station() -> None:
    adapter = NewTaipeiRainfallApiAdapter(
        fetched_at=FETCHED_AT,
        fetch_json=lambda url, timeout: _new_taipei_rainfall_payload(),
    )

    result = adapter.run()

    assert result.adapter_key == "local.new_taipei.rainfall"
    assert len(result.fetched) == 2
    assert len(result.normalized) == 1
    assert result.rejected == ("NTPC-RF-OLD:2026-06-27T02:00:00+00:00",)
    raw_payload = result.fetched[0].payload
    assert raw_payload["station_id"] == "NTPC-RF-001"
    assert raw_payload["observed_at"] == "2026-06-28T09:23:00+00:00"
    assert raw_payload["rainfall_mm"] == 1.5
    assert raw_payload["rainfall_mm_10m"] == 0.5
    assert raw_payload["rainfall_mm_24h"] == 18.0
    evidence = result.normalized[0]
    assert evidence.event_type is EventType.RAINFALL
    assert "1.5 mm" in evidence.summary
    assert "local_new_taipei" in evidence.tags


def test_new_taipei_drainage_json_outputs_local_drainage_water_level() -> None:
    adapter = NewTaipeiDrainageWaterLevelApiAdapter(
        fetched_at=FETCHED_AT,
        fetch_json=lambda url, timeout: _new_taipei_drainage_payload(),
    )

    result = adapter.run()

    assert result.adapter_key == "local.new_taipei.drainage_water_level"
    assert len(result.normalized) == 1
    raw_payload = result.fetched[0].payload
    assert raw_payload["station_id"] == "NTPC-DR-001"
    assert raw_payload["observed_at"] == "2026-06-28T09:22:00+00:00"
    assert raw_payload["water_level_m"] == 0.42
    assert raw_payload["cctv_url"] == "https://example.test/cctv"
    evidence = result.normalized[0]
    assert evidence.event_type is EventType.WATER_LEVEL
    assert "0.42 公尺" in evidence.summary
    assert "drainage_water_level" in evidence.tags


def test_build_runtime_adapters_wires_new_taipei_sources_when_gates_are_on() -> None:
    settings = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": (
                "local.new_taipei.water_level,local.new_taipei.flood_sensor,"
                "local.new_taipei.rainfall,local.new_taipei.drainage_water_level"
            ),
            "SOURCE_NEW_TAIPEI_WATER_LEVEL_ENABLED": "true",
            "SOURCE_NEW_TAIPEI_WATER_LEVEL_API_ENABLED": "true",
            "SOURCE_NEW_TAIPEI_FLOOD_SENSOR_ENABLED": "true",
            "SOURCE_NEW_TAIPEI_FLOOD_SENSOR_API_ENABLED": "true",
            "SOURCE_NEW_TAIPEI_RAINFALL_ENABLED": "true",
            "SOURCE_NEW_TAIPEI_RAINFALL_API_ENABLED": "true",
            "SOURCE_NEW_TAIPEI_DRAINAGE_WATER_LEVEL_ENABLED": "true",
            "SOURCE_NEW_TAIPEI_DRAINAGE_WATER_LEVEL_API_ENABLED": "true",
            "LOCAL_WATER_TIMEOUT_SECONDS": "5",
        }
    )

    adapters = build_runtime_adapters(
        settings,
        fetched_at=FETCHED_AT,
        new_taipei_water_level_fetch_json=lambda url, timeout: _new_taipei_water_payload(),
        new_taipei_flood_sensor_fetch_json=lambda url, timeout: _new_taipei_flood_payload(),
        new_taipei_rainfall_fetch_json=lambda url, timeout: _new_taipei_rainfall_payload(),
        new_taipei_drainage_water_level_fetch_json=(
            lambda url, timeout: _new_taipei_drainage_payload()
        ),
    )

    assert tuple(adapters) == (
        "local.new_taipei.water_level",
        "local.new_taipei.flood_sensor",
        "local.new_taipei.rainfall",
        "local.new_taipei.drainage_water_level",
    )
    assert len(adapters["local.new_taipei.water_level"].run().normalized) == 1
    assert len(adapters["local.new_taipei.flood_sensor"].run().normalized) == 1
    assert len(adapters["local.new_taipei.rainfall"].run().normalized) == 1
    assert len(adapters["local.new_taipei.drainage_water_level"].run().normalized) == 1
    assert NEW_TAIPEI_WATER_LEVEL_API_URL.startswith("https://newtaipei.wavegis.com.tw/")
    assert NEW_TAIPEI_FLOOD_SENSOR_API_URL.startswith("https://newtaipei.wavegis.com.tw/")
    assert NEW_TAIPEI_RAINFALL_API_URL.startswith("https://newtaipei.wavegis.com.tw/")
    assert NEW_TAIPEI_DRAINAGE_WATER_LEVEL_API_URL.startswith(
        "https://newtaipei.wavegis.com.tw/"
    )
