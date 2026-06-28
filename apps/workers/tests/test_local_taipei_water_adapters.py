from __future__ import annotations

from datetime import UTC, datetime

from app.adapters.contracts import EventType, SourceFamily
from app.adapters.local_taipei import (
    TAIPEI_PUMP_STATION_API_URL,
    TAIPEI_RIVER_WATER_LEVEL,
    TAIPEI_RIVER_WATER_LEVEL_API_URL,
    TAIPEI_RIVER_WATER_LEVEL_METADATA_CSV_URL,
    TAIPEI_SEWER_WATER_LEVEL,
    TAIPEI_SEWER_WATER_LEVEL_API_URL,
    TAIPEI_SEWER_WATER_LEVEL_METADATA_CSV_URL,
    TaipeiPumpStationApiAdapter,
    TaipeiWaterLevelApiAdapter,
)
from app.config import load_worker_settings
from app.jobs.runtime import build_runtime_adapters


FETCHED_AT = datetime(2026, 6, 27, 4, 0, tzinfo=UTC)


def _sewer_payload() -> dict:
    return {
        "count": 1,
        "data": [
            {
                "stationNo": "U0006",
                "stationName": "大湖1",
                "recTime": "202606271150",
                "levelOut": 15.58,
                "groundFar": 3.73,
                "voltage": 12.7,
            }
        ],
    }


def _sewer_metadata_csv() -> str:
    return (
        "\ufeff設施編號,站名,行政區,經度,緯度\n"
        "U0006,大湖1,內湖區,121.5985629,25.08865652\n"
    )


def _river_payload() -> dict:
    return {
        "count": 2,
        "data": [
            {
                "stationNo": "001",
                "stationName": "承德橋",
                "recTime": "202606271150",
                "levelOut": 1.24,
            },
            {
                "stationNo": "022",
                "stationName": "三合橋",
                "recTime": "202310271040",
                "levelOut": 2.58,
            },
        ],
    }


def _river_metadata_csv() -> str:
    return (
        "\ufeff站碼,站名,流域,行政區,X座標,Y座標\n"
        "1,承德橋,基隆河,士林,121.521013,25.078129\n"
        "22,三合橋,基隆河,北投,121.500000,25.100000\n"
    )


def _pump_payload() -> list[dict]:
    return [
        {
            "stn_id": "110",
            "stn_name": "建國",
            "lon": 121.5289,
            "lat": 25.07241,
            "obs_time": "2026-06-27 11:50:00",
            "inner_value": "0.64",
            "outer_value": "1.6",
            "pumb_num": 6,
            "door_num": 4,
            "pumb_status": "停止",
            "door_status": "閘門關閉",
            "max_allowable_water_level": 1.06,
        }
    ]


def test_taipei_sewer_water_level_joins_station_metadata() -> None:
    adapter = TaipeiWaterLevelApiAdapter(
        TAIPEI_SEWER_WATER_LEVEL,
        fetched_at=FETCHED_AT,
        timeout_seconds=5,
        fetch_json=lambda url, timeout: _sewer_payload(),
        fetch_text=lambda url, timeout: _sewer_metadata_csv(),
    )

    result = adapter.run()

    assert result.adapter_key == "local.taipei.sewer_water_level"
    assert len(result.normalized) == 1
    raw_payload = result.fetched[0].payload
    assert raw_payload["station_id"] == "U0006"
    assert raw_payload["station_name"] == "大湖1"
    assert raw_payload["observed_at"] == "2026-06-27T03:50:00+00:00"
    assert raw_payload["water_level_m"] == 15.58
    assert raw_payload["district"] == "內湖區"
    assert raw_payload["geometry"] == {
        "type": "Point",
        "coordinates": [121.5985629, 25.08865652],
    }
    assert raw_payload["quality_flags"] == {
        "station_metadata_missing": False,
        "missing_station_coordinates": False,
        "stale_observation": False,
    }
    evidence = result.normalized[0]
    assert evidence.event_type is EventType.WATER_LEVEL
    assert evidence.source_family is SourceFamily.OFFICIAL
    assert "15.58 公尺" in evidence.summary
    assert "local_taipei" in evidence.tags
    assert "sewer_water_level" in evidence.tags


def test_taipei_river_water_level_rejects_stale_station_rows() -> None:
    adapter = TaipeiWaterLevelApiAdapter(
        TAIPEI_RIVER_WATER_LEVEL,
        fetched_at=FETCHED_AT,
        fetch_json=lambda url, timeout: _river_payload(),
        fetch_text=lambda url, timeout: _river_metadata_csv(),
    )

    result = adapter.run()

    assert len(result.fetched) == 2
    assert len(result.normalized) == 1
    assert result.normalized[0].source_id == "001:2026-06-27T03:50:00+00:00"
    assert result.rejected == ("022:2023-10-27T02:40:00+00:00",)
    stale_payload = result.fetched[1].payload
    assert stale_payload["quality_flags"]["stale_observation"] is True


def test_taipei_pump_station_uses_embedded_coordinates_and_outer_level() -> None:
    adapter = TaipeiPumpStationApiAdapter(
        fetched_at=FETCHED_AT,
        fetch_json=lambda url, timeout: _pump_payload(),
    )

    result = adapter.run()

    assert result.adapter_key == "local.taipei.pump_station"
    assert len(result.normalized) == 1
    raw_payload = result.fetched[0].payload
    assert raw_payload["station_id"] == "110"
    assert raw_payload["station_name"] == "建國"
    assert raw_payload["observed_at"] == "2026-06-27T03:50:00+00:00"
    assert raw_payload["water_level_m"] == 1.6
    assert raw_payload["inner_water_level_m"] == 0.64
    assert raw_payload["max_allowable_water_level_m"] == 1.06
    assert raw_payload["geometry"] == {
        "type": "Point",
        "coordinates": [121.5289, 25.07241],
    }
    evidence = result.normalized[0]
    assert "outer_water_level" in evidence.tags
    assert "warning_threshold_reached" in evidence.tags


def test_build_runtime_adapters_wires_taipei_sources_when_gates_are_on() -> None:
    settings = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": ",".join(
                (
                    "local.taipei.sewer_water_level",
                    "local.taipei.river_water_level",
                    "local.taipei.pump_station",
                )
            ),
            "SOURCE_TAIPEI_SEWER_WATER_LEVEL_ENABLED": "true",
            "SOURCE_TAIPEI_SEWER_WATER_LEVEL_API_ENABLED": "true",
            "SOURCE_TAIPEI_RIVER_WATER_LEVEL_ENABLED": "true",
            "SOURCE_TAIPEI_RIVER_WATER_LEVEL_API_ENABLED": "true",
            "SOURCE_TAIPEI_PUMP_STATION_ENABLED": "true",
            "SOURCE_TAIPEI_PUMP_STATION_API_ENABLED": "true",
            "TAIPEI_WATER_TIMEOUT_SECONDS": "5",
        }
    )

    adapters = build_runtime_adapters(
        settings,
        fetched_at=FETCHED_AT,
        taipei_sewer_fetch_json=lambda url, timeout: _sewer_payload(),
        taipei_sewer_fetch_text=lambda url, timeout: _sewer_metadata_csv(),
        taipei_river_fetch_json=lambda url, timeout: _river_payload(),
        taipei_river_fetch_text=lambda url, timeout: _river_metadata_csv(),
        taipei_pump_fetch_json=lambda url, timeout: _pump_payload(),
    )

    assert tuple(adapters) == (
        "local.taipei.sewer_water_level",
        "local.taipei.river_water_level",
        "local.taipei.pump_station",
    )
    assert len(adapters["local.taipei.sewer_water_level"].run().normalized) == 1
    assert len(adapters["local.taipei.river_water_level"].run().normalized) == 1
    assert len(adapters["local.taipei.pump_station"].run().normalized) == 1
    assert TAIPEI_SEWER_WATER_LEVEL_API_URL.startswith("https://wic.gov.taipei/")
    assert TAIPEI_SEWER_WATER_LEVEL_METADATA_CSV_URL.startswith("https://data.taipei/")
    assert TAIPEI_RIVER_WATER_LEVEL_API_URL.startswith("https://wic.gov.taipei/")
    assert TAIPEI_RIVER_WATER_LEVEL_METADATA_CSV_URL.startswith("https://data.taipei/")
    assert TAIPEI_PUMP_STATION_API_URL.startswith("https://heopublic.gov.taipei/")
