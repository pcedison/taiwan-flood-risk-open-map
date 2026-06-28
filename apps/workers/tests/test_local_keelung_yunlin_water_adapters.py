from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.adapters.contracts import EventType, SourceFamily
from app.adapters.local_keelung import (
    KEELUNG_FLOOD_SENSOR_API_URL,
    KEELUNG_RAINFALL_API_URL,
    KEELUNG_WATER_LEVEL_API_URL,
    KeelungFloodSensorApiAdapter,
    KeelungRainfallApiAdapter,
    KeelungWaterLevelApiAdapter,
)
from app.adapters.local_yunlin import (
    YUNLIN_STATIONS_API_URL,
    YunlinWaterLevelApiAdapter,
)
from app.config import load_worker_settings
from app.jobs.runtime import build_runtime_adapters


FETCHED_AT = datetime(2026, 6, 28, 9, 10, tzinfo=UTC)


def _keelung_water_payload() -> list[dict[str, Any]]:
    return [
        {
            "st_no": "WG_RR_W_00030",
            "st_name": "田寮河監測站",
            "lon": 121.747595,
            "lat": 25.128513,
            "datatime": "2026-06-28 16:56:00",
            "sendtime": "2026-06-28 16:56:36",
            "water_inner": 0.11,
            "batteryvol": 4.01,
            "warn_lv1": 1.51,
            "warn_lv2": 1.20,
            "city": "基隆市",
            "town": "仁愛區",
            "village": "和明里",
            "river": "田寮河",
            "status": "正常",
            "source": "基隆市",
            "basin": "基隆港",
            "device_type": "WG_RR_W",
            "ascent_rate": -0.012,
        }
    ]


def _keelung_flood_payload() -> list[dict[str, Any]]:
    return [
        {
            "st_no": "000000KEL1080027",
            "st_name": "仁愛區玉田里愛四路",
            "lon": 121.743269,
            "lat": 25.127762,
            "datatime": "2026-06-28 17:00:05",
            "water_inner": 6.0,
            "batteryvol": 4.0,
            "warn_lv1": 30.0,
            "warn_lv2": 10.0,
            "city": "基隆市",
            "town": "仁愛區",
            "village": "玉田里",
            "status": "正常",
            "source": "基隆市",
            "device_type": "flood",
        }
    ]


def _keelung_rain_payload() -> list[dict[str, Any]]:
    return [
        {
            "st_no": "01_YOLIQ",
            "st_name": "友蚋溪_友諒橋",
            "river": "友蚋溪",
            "lon": 121.669378,
            "lat": 25.093839,
            "datatime": "2026-06-28 16:40:00",
            "rain": 2.5,
            "min_10": 0.5,
            "min_30": 1.1,
            "hour_3": 3.0,
            "hour_6": 5.0,
            "hour_12": 8.0,
            "hour_24": 12.0,
            "city": "基隆市",
            "town": "七堵區",
            "status": "正常",
            "source": "基隆市",
        },
        {
            "st_no": "OLD_RAIN",
            "st_name": "舊雨量站",
            "lon": 121.70,
            "lat": 25.10,
            "datatime": "2026-05-26 10:00:00",
            "rain": 0.0,
        },
    ]


def _yunlin_stations_payload() -> dict[str, Any]:
    return {
        "success": True,
        "result": {
            "totalCount": 2,
            "items": [
                {
                    "id": "027f4035-d2c3-4784-bcd8-3f99486e5636",
                    "displayName": "水位_東勢鄉_馬公厝排水三",
                    "stationName": "馬公厝排水三",
                    "administrativeArea": "東勢鄉",
                    "stationType": "水位",
                    "owner": "雲林縣政府",
                    "longitude": 120.239311,
                    "latitude": 23.688625,
                    "alarmState": "正常",
                    "latestUpdateTime": "2026-06-28T17:00:30.135+08:00",
                    "levelHeight": 6.64,
                    "alertThreshold": {
                        "level1": 6.54,
                        "level2": 6.44,
                        "level3": None,
                    },
                    "jsonProperty": (
                        '{"observationPrinciple":"超音波式",'
                        '"observationFrequency":"十分鐘一筆",'
                        '"elevation":"0.72","drainage":"馬公厝大排"}'
                    ),
                    "elevation": 0.72,
                },
                {
                    "id": "01f29fe1-7a96-49ce-940a-flood-depth-not-exposed",
                    "displayName": "淹水感測_口湖鄉_港西村_中正路3-23號",
                    "stationName": "港西村_中正路3-23號",
                    "administrativeArea": "口湖鄉",
                    "stationType": "淹水感測",
                    "owner": "雲林縣政府",
                    "longitude": 120.147835,
                    "latitude": 23.575771,
                    "alarmState": "正常",
                    "latestUpdateTime": "2026-06-28T17:00:02.651+08:00",
                    "alertThreshold": {"level1": 30.0, "level2": 25.0, "level3": 15.0},
                },
            ],
        },
    }


def test_keelung_water_json_outputs_local_water_level() -> None:
    adapter = KeelungWaterLevelApiAdapter(
        fetched_at=FETCHED_AT,
        fetch_json=lambda url, timeout: _keelung_water_payload(),
    )

    result = adapter.run()

    assert result.adapter_key == "local.keelung.water_level"
    assert len(result.normalized) == 1
    raw_payload = result.fetched[0].payload
    assert raw_payload["station_id"] == "WG_RR_W_00030"
    assert raw_payload["station_name"] == "田寮河監測站"
    assert raw_payload["observed_at"] == "2026-06-28T08:56:00+00:00"
    assert raw_payload["water_level_m"] == 0.11
    assert raw_payload["warning_level_m"] == 1.2
    assert raw_payload["red_alert_level_m"] == 1.51
    assert raw_payload["town"] == "仁愛區"
    assert raw_payload["village"] == "和明里"
    assert raw_payload["geometry"] == {
        "type": "Point",
        "coordinates": [121.747595, 25.128513],
    }
    evidence = result.normalized[0]
    assert evidence.event_type is EventType.WATER_LEVEL
    assert evidence.source_family is SourceFamily.OFFICIAL
    assert "0.11 公尺" in evidence.summary
    assert "local_keelung" in evidence.tags
    assert "water_level" in evidence.tags


def test_keelung_flood_json_outputs_local_flood_depth() -> None:
    adapter = KeelungFloodSensorApiAdapter(
        fetched_at=FETCHED_AT,
        fetch_json=lambda url, timeout: _keelung_flood_payload(),
    )

    result = adapter.run()

    assert result.adapter_key == "local.keelung.flood_sensor"
    assert len(result.normalized) == 1
    raw_payload = result.fetched[0].payload
    assert raw_payload["station_id"] == "000000KEL1080027"
    assert raw_payload["station_name"] == "仁愛區玉田里愛四路"
    assert raw_payload["observed_at"] == "2026-06-28T09:00:05+00:00"
    assert raw_payload["flood_depth_cm"] == 6.0
    assert raw_payload["warning_level_cm"] == 10.0
    assert raw_payload["red_alert_level_cm"] == 30.0
    evidence = result.normalized[0]
    assert evidence.event_type is EventType.FLOOD_REPORT
    assert "水深 6 公分" in evidence.summary
    assert "local_keelung" in evidence.tags


def test_keelung_rain_json_outputs_rainfall_and_rejects_stale_station() -> None:
    adapter = KeelungRainfallApiAdapter(
        fetched_at=FETCHED_AT,
        fetch_json=lambda url, timeout: _keelung_rain_payload(),
    )

    result = adapter.run()

    assert result.adapter_key == "local.keelung.rainfall"
    assert len(result.fetched) == 2
    assert len(result.normalized) == 1
    assert result.rejected == ("OLD_RAIN:2026-05-26T02:00:00+00:00",)
    raw_payload = result.fetched[0].payload
    assert raw_payload["station_id"] == "01_YOLIQ"
    assert raw_payload["station_name"] == "友蚋溪_友諒橋"
    assert raw_payload["observed_at"] == "2026-06-28T08:40:00+00:00"
    assert raw_payload["rainfall_mm"] == 2.5
    assert raw_payload["rainfall_mm_10m"] == 0.5
    assert raw_payload["rainfall_mm_30m"] == 1.1
    assert raw_payload["rainfall_mm_3h"] == 3.0
    assert raw_payload["rainfall_mm_6h"] == 5.0
    assert raw_payload["rainfall_mm_12h"] == 8.0
    assert raw_payload["rainfall_mm_24h"] == 12.0
    evidence = result.normalized[0]
    assert evidence.event_type is EventType.RAINFALL
    assert "2.5 mm" in evidence.summary
    assert "local_keelung" in evidence.tags


def test_yunlin_station_api_outputs_water_level_without_fabricating_flood_depth() -> None:
    adapter = YunlinWaterLevelApiAdapter(
        fetched_at=FETCHED_AT,
        fetch_json=lambda url, timeout: _yunlin_stations_payload(),
    )

    result = adapter.run()

    assert result.adapter_key == "local.yunlin.water_level"
    assert len(result.fetched) == 1
    assert len(result.normalized) == 1
    raw_payload = result.fetched[0].payload
    assert raw_payload["station_id"] == "027f4035-d2c3-4784-bcd8-3f99486e5636"
    assert raw_payload["station_name"] == "馬公厝排水三"
    assert raw_payload["observed_at"] == "2026-06-28T09:00:30.135000+00:00"
    assert raw_payload["water_level_m"] == 6.64
    assert raw_payload["warning_level_m"] == 6.44
    assert raw_payload["red_alert_level_m"] == 6.54
    assert raw_payload["town"] == "東勢鄉"
    assert raw_payload["drainage"] == "馬公厝大排"
    assert raw_payload["observation_frequency"] == "十分鐘一筆"
    evidence = result.normalized[0]
    assert evidence.event_type is EventType.WATER_LEVEL
    assert "6.64 公尺" in evidence.summary
    assert "warning_threshold_reached" in evidence.tags
    assert "local_yunlin" in evidence.tags


def test_build_runtime_adapters_wires_keelung_and_yunlin_sources_when_gates_are_on() -> None:
    settings = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": (
                "local.keelung.water_level,local.keelung.flood_sensor,"
                "local.keelung.rainfall,local.yunlin.water_level"
            ),
            "SOURCE_KEELUNG_WATER_LEVEL_ENABLED": "true",
            "SOURCE_KEELUNG_WATER_LEVEL_API_ENABLED": "true",
            "SOURCE_KEELUNG_FLOOD_SENSOR_ENABLED": "true",
            "SOURCE_KEELUNG_FLOOD_SENSOR_API_ENABLED": "true",
            "SOURCE_KEELUNG_RAINFALL_ENABLED": "true",
            "SOURCE_KEELUNG_RAINFALL_API_ENABLED": "true",
            "SOURCE_YUNLIN_WATER_LEVEL_ENABLED": "true",
            "SOURCE_YUNLIN_WATER_LEVEL_API_ENABLED": "true",
            "LOCAL_WATER_TIMEOUT_SECONDS": "5",
        }
    )

    adapters = build_runtime_adapters(
        settings,
        fetched_at=FETCHED_AT,
        keelung_water_level_fetch_json=lambda url, timeout: _keelung_water_payload(),
        keelung_flood_sensor_fetch_json=lambda url, timeout: _keelung_flood_payload(),
        keelung_rainfall_fetch_json=lambda url, timeout: _keelung_rain_payload(),
        yunlin_water_level_fetch_json=lambda url, timeout: _yunlin_stations_payload(),
    )

    assert tuple(adapters) == (
        "local.keelung.water_level",
        "local.keelung.flood_sensor",
        "local.keelung.rainfall",
        "local.yunlin.water_level",
    )
    assert len(adapters["local.keelung.water_level"].run().normalized) == 1
    assert len(adapters["local.keelung.flood_sensor"].run().normalized) == 1
    assert len(adapters["local.keelung.rainfall"].run().normalized) == 1
    assert len(adapters["local.yunlin.water_level"].run().normalized) == 1
    assert KEELUNG_WATER_LEVEL_API_URL.startswith("https://smartflood.klcg.gov.tw/")
    assert KEELUNG_FLOOD_SENSOR_API_URL.startswith("https://smartflood.klcg.gov.tw/")
    assert KEELUNG_RAINFALL_API_URL.startswith("https://smartflood.klcg.gov.tw/")
    assert YUNLIN_STATIONS_API_URL.startswith("https://yliflood.yunlin.gov.tw/")
