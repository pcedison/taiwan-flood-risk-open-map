from __future__ import annotations

from datetime import UTC, datetime

from app.adapters.contracts import EventType, SourceFamily
from app.adapters.local_chiayi_city import (
    CHIAYI_CITY_RAINFALL_API_URL,
    CHIAYI_CITY_WATER_LEVEL_API_URL,
    ChiayiCityRainfallApiAdapter,
    ChiayiCityWaterLevelApiAdapter,
)
from app.adapters.local_taichung import (
    TAICHUNG_WATER_LEVEL_API_URL,
    TaichungWaterLevelApiAdapter,
)
from app.config import load_worker_settings
from app.jobs.runtime import build_runtime_adapters


FETCHED_AT = datetime(2026, 6, 27, 16, 0, tzinfo=UTC)


def _chiayi_csv() -> str:
    return (
        "\ufeff代號,站名,經度,緯度,資料時間,水位-m,電池電壓,一級警戒,二級警戒\n"
        "WG_SRR_W_00013,嘉義交流道西南機車引道排水,120.3891,23.4944,"
        "2026-06-27 23:54:00,19.769,4.67,20.7,20.4\n"
    )


def _chiayi_rainfall_csv() -> str:
    return (
        "\ufeff代號,站名,經度,緯度,資料時間,10分鐘雨量-mm,1小時雨量-mm,"
        "3小時雨量-mm,6小時雨量-mm,12小時雨量-mm,24小時雨量-mm,狀態\n"
        "C2M910,嘉義大學,120.485903,23.471325,2026-06-28 00:00:00,"
        "0.5,3.0,7.0,12.0,27.5,70.0,正常\n"
        "MAINT,維護站,120.4,23.4,2026-06-28 00:00:00,"
        "-99,-99,-99,-99,-99,-99,維護\n"
    )


def _taichung_payload() -> dict:
    return {
        "ROOT": {
            "DATA": [
                {
                    "黃色警戒值m": "2.7",
                    "紅色警戒值m": "3.3",
                    "日期時間": "2026/6/27 下午 11:48:55",
                    "經度": "120.62747",
                    "緯度": "24.234125",
                    "水位高m": "0",
                    "水位站名稱": "十三寮排水上游",
                    "行政區": "大雅區",
                    "狀態": "正常",
                },
                {
                    "黃色警戒值m": "1.3",
                    "紅色警戒值m": "1.8",
                    "日期時間": "2026/3/8 下午 11:48:55",
                    "經度": "120.62945",
                    "緯度": "24.20874",
                    "水位高m": "0.03189",
                    "水位站名稱": "林厝排水上游",
                    "行政區": "大雅區",
                    "狀態": "正常",
                },
            ]
        }
    }


def test_chiayi_city_water_level_csv_outputs_warning_metrics() -> None:
    adapter = ChiayiCityWaterLevelApiAdapter(
        fetched_at=FETCHED_AT,
        timeout_seconds=5,
        fetch_text=lambda url, timeout: _chiayi_csv(),
    )

    result = adapter.run()

    assert result.adapter_key == "local.chiayi_city.water_level"
    assert len(result.normalized) == 1
    raw_payload = result.fetched[0].payload
    assert raw_payload["station_id"] == "WG_SRR_W_00013"
    assert raw_payload["station_name"] == "嘉義交流道西南機車引道排水"
    assert raw_payload["observed_at"] == "2026-06-27T15:54:00+00:00"
    assert raw_payload["water_level_m"] == 19.769
    assert raw_payload["warning_level_m"] == 20.4
    assert raw_payload["yellow_alert_level_m"] == 20.4
    assert raw_payload["red_alert_level_m"] == 20.7
    assert raw_payload["geometry"] == {
        "type": "Point",
        "coordinates": [120.3891, 23.4944],
    }
    evidence = result.normalized[0]
    assert evidence.event_type is EventType.WATER_LEVEL
    assert evidence.source_family is SourceFamily.OFFICIAL
    assert "19.77 公尺" in evidence.summary
    assert "local_chiayi_city" in evidence.tags


def test_chiayi_city_rainfall_csv_outputs_multiple_rainfall_windows() -> None:
    adapter = ChiayiCityRainfallApiAdapter(
        fetched_at=FETCHED_AT,
        fetch_text=lambda url, timeout: _chiayi_rainfall_csv(),
    )

    result = adapter.run()

    assert result.adapter_key == "local.chiayi_city.rainfall"
    assert len(result.fetched) == 1
    assert len(result.normalized) == 1
    raw_payload = result.fetched[0].payload
    assert raw_payload["station_id"] == "C2M910"
    assert raw_payload["station_name"] == "嘉義大學"
    assert raw_payload["observed_at"] == "2026-06-27T16:00:00+00:00"
    assert raw_payload["rainfall_mm_10m"] == 0.5
    assert raw_payload["rainfall_mm_1h"] == 3.0
    assert raw_payload["rainfall_mm_3h"] == 7.0
    assert raw_payload["rainfall_mm_6h"] == 12.0
    assert raw_payload["rainfall_mm_12h"] == 27.5
    assert raw_payload["rainfall_mm_24h"] == 70.0
    assert raw_payload["geometry"] == {
        "type": "Point",
        "coordinates": [120.485903, 23.471325],
    }
    evidence = result.normalized[0]
    assert evidence.event_type is EventType.RAINFALL
    assert evidence.source_family is SourceFamily.OFFICIAL
    assert "3.0 mm in 1 hour" in evidence.summary
    assert "local_chiayi_city" in evidence.tags
    assert "rainfall" in evidence.tags


def test_taichung_water_level_json_rejects_stale_rows() -> None:
    adapter = TaichungWaterLevelApiAdapter(
        fetched_at=FETCHED_AT,
        fetch_json=lambda url, timeout: _taichung_payload(),
    )

    result = adapter.run()

    assert result.adapter_key == "local.taichung.water_level"
    assert len(result.fetched) == 2
    assert len(result.normalized) == 1
    assert result.rejected == ("林厝排水上游:2026-03-08T15:48:55+00:00",)
    raw_payload = result.fetched[0].payload
    assert raw_payload["station_id"] == "十三寮排水上游"
    assert raw_payload["observed_at"] == "2026-06-27T15:48:55+00:00"
    assert raw_payload["water_level_m"] == 0.0
    assert raw_payload["district"] == "大雅區"
    assert raw_payload["status_text"] == "正常"
    evidence = result.normalized[0]
    assert "local_taichung" in evidence.tags
    assert "water_level" in evidence.tags


def test_build_runtime_adapters_wires_chiayi_and_taichung_when_gates_are_on() -> None:
    settings = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": (
                "local.chiayi_city.water_level,local.chiayi_city.rainfall,"
                "local.taichung.water_level"
            ),
            "SOURCE_CHIAYI_CITY_WATER_LEVEL_ENABLED": "true",
            "SOURCE_CHIAYI_CITY_WATER_LEVEL_API_ENABLED": "true",
            "SOURCE_CHIAYI_CITY_RAINFALL_ENABLED": "true",
            "SOURCE_CHIAYI_CITY_RAINFALL_API_ENABLED": "true",
            "SOURCE_TAICHUNG_WATER_LEVEL_ENABLED": "true",
            "SOURCE_TAICHUNG_WATER_LEVEL_API_ENABLED": "true",
            "LOCAL_WATER_TIMEOUT_SECONDS": "5",
        }
    )

    adapters = build_runtime_adapters(
        settings,
        fetched_at=FETCHED_AT,
        chiayi_city_water_level_fetch_text=lambda url, timeout: _chiayi_csv(),
        chiayi_city_rainfall_fetch_text=lambda url, timeout: _chiayi_rainfall_csv(),
        taichung_water_level_fetch_json=lambda url, timeout: _taichung_payload(),
    )

    assert tuple(adapters) == (
        "local.chiayi_city.water_level",
        "local.chiayi_city.rainfall",
        "local.taichung.water_level",
    )
    assert len(adapters["local.chiayi_city.water_level"].run().normalized) == 1
    assert len(adapters["local.chiayi_city.rainfall"].run().normalized) == 1
    assert len(adapters["local.taichung.water_level"].run().normalized) == 1
    assert CHIAYI_CITY_WATER_LEVEL_API_URL.startswith("https://data.chiayi.gov.tw/")
    assert CHIAYI_CITY_RAINFALL_API_URL.startswith("https://data.chiayi.gov.tw/")
    assert TAICHUNG_WATER_LEVEL_API_URL.startswith("https://wrbeocin.taichung.gov.tw/")
