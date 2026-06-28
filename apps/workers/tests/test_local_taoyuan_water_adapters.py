from __future__ import annotations

from datetime import UTC, datetime

from app.adapters.contracts import EventType, SourceFamily
from app.adapters.local_taoyuan import (
    TAOYUAN_FLOOD_SENSOR_API_URL,
    TAOYUAN_RAINFALL_API_URL,
    TAOYUAN_WATER_LEVEL_API_URL,
    TaoyuanFloodSensorApiAdapter,
    TaoyuanRainfallApiAdapter,
    TaoyuanWaterLevelApiAdapter,
)
from app.config import load_worker_settings
from app.jobs.runtime import build_runtime_adapters


FETCHED_AT = datetime(2026, 6, 27, 16, 0, tzinfo=UTC)


def _flood_xml() -> str:
    return """
    <Root>
      <Data>
        <ID>20180510120206</ID>
        <NAME>樹仁三街、桃鶯路口</NAME>
        <LON>121.323435</LON>
        <LAT>24.975086</LAT>
        <ADDRESS>樹仁三街、桃鶯路口</ADDRESS>
        <HEIGHT>7</HEIGHT>
        <DATA_TIME>2026/6/27 下午 11:00:00</DATA_TIME>
      </Data>
    </Root>
    """


def _water_level_xml() -> str:
    return """
    <ROOT>
      <DATA>
        <DATATIME>2026-06-27 22:50:00</DATATIME>
        <LON>121.30874</LON>
        <LAT>24.9582</LAT>
        <STATION>DR0-102-大灣溝</STATION>
        <STATION_ID>1032598727</STATION_ID>
        <TOWN>八德區</TOWN>
        <WATERHEIGHT_M>0.75</WATERHEIGHT_M>
        <RedAlertLevel>2.08</RedAlertLevel>
        <YellowAlertLevel>1.56</YellowAlertLevel>
      </DATA>
    </ROOT>
    """


def _rainfall_xml() -> str:
    return """
    <TYCG>
      <Time>2026-06-28 00:10</Time>
      <Description>提供桃園水情雨量資料</Description>
      <Station>
        <ID>TYC002</ID>
        <Disrict>桃園市平鎮區</Disrict>
        <Name>滿庭芳</Name>
        <X>121.222676</X>
        <Y>24.93293</Y>
        <Rainfall>12.5</Rainfall>
      </Station>
      <Station>
        <ID>TYC999</ID>
        <Disrict>桃園市維護區</Disrict>
        <Name>維護站</Name>
        <X>121.1</X>
        <Y>24.9</Y>
        <Rainfall>-98</Rainfall>
      </Station>
    </TYCG>
    """


def test_taoyuan_flood_sensor_xml_outputs_flood_report() -> None:
    adapter = TaoyuanFloodSensorApiAdapter(
        fetched_at=FETCHED_AT,
        timeout_seconds=5,
        fetch_text=lambda url, timeout: _flood_xml(),
    )

    result = adapter.run()

    assert result.adapter_key == "local.taoyuan.flood_sensor"
    assert len(result.normalized) == 1
    raw_payload = result.fetched[0].payload
    assert raw_payload["station_id"] == "20180510120206"
    assert raw_payload["station_name"] == "樹仁三街、桃鶯路口"
    assert raw_payload["observed_at"] == "2026-06-27T15:00:00+00:00"
    assert raw_payload["flood_depth_cm"] == 7.0
    assert raw_payload["geometry"] == {
        "type": "Point",
        "coordinates": [121.323435, 24.975086],
    }
    evidence = result.normalized[0]
    assert evidence.event_type is EventType.FLOOD_REPORT
    assert evidence.source_family is SourceFamily.OFFICIAL
    assert "水深 7 公分" in evidence.summary
    assert "local_taoyuan" in evidence.tags
    assert "flood_sensor" in evidence.tags


def test_taoyuan_water_level_xml_outputs_warning_metrics() -> None:
    adapter = TaoyuanWaterLevelApiAdapter(
        fetched_at=FETCHED_AT,
        fetch_text=lambda url, timeout: _water_level_xml(),
    )

    result = adapter.run()

    assert result.adapter_key == "local.taoyuan.water_level"
    assert len(result.normalized) == 1
    raw_payload = result.fetched[0].payload
    assert raw_payload["station_id"] == "1032598727"
    assert raw_payload["station_name"] == "DR0-102-大灣溝"
    assert raw_payload["observed_at"] == "2026-06-27T14:50:00+00:00"
    assert raw_payload["water_level_m"] == 0.75
    assert raw_payload["warning_level_m"] == 1.56
    assert raw_payload["yellow_alert_level_m"] == 1.56
    assert raw_payload["red_alert_level_m"] == 2.08
    assert raw_payload["town"] == "八德區"
    assert raw_payload["geometry"] == {
        "type": "Point",
        "coordinates": [121.30874, 24.9582],
    }
    evidence = result.normalized[0]
    assert evidence.event_type is EventType.WATER_LEVEL
    assert "0.75 公尺" in evidence.summary
    assert "local_taoyuan" in evidence.tags
    assert "water_level" in evidence.tags


def test_taoyuan_rainfall_xml_outputs_rainfall_observation_and_rejects_maintenance() -> None:
    adapter = TaoyuanRainfallApiAdapter(
        fetched_at=FETCHED_AT,
        fetch_text=lambda url, timeout: _rainfall_xml(),
    )

    result = adapter.run()

    assert result.adapter_key == "local.taoyuan.rainfall"
    assert len(result.fetched) == 1
    assert len(result.normalized) == 1
    raw_payload = result.fetched[0].payload
    assert raw_payload["station_id"] == "TYC002"
    assert raw_payload["station_name"] == "滿庭芳"
    assert raw_payload["observed_at"] == "2026-06-27T16:10:00+00:00"
    assert raw_payload["rainfall_mm"] == 12.5
    assert raw_payload["county"] == "桃園市"
    assert raw_payload["town"] == "平鎮區"
    assert raw_payload["geometry"] == {
        "type": "Point",
        "coordinates": [121.222676, 24.93293],
    }
    evidence = result.normalized[0]
    assert evidence.event_type is EventType.RAINFALL
    assert evidence.source_family is SourceFamily.OFFICIAL
    assert "12.5 mm" in evidence.summary
    assert "local_taoyuan" in evidence.tags
    assert "rainfall" in evidence.tags


def test_build_runtime_adapters_wires_taoyuan_sources_when_gates_are_on() -> None:
    settings = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": (
                "local.taoyuan.flood_sensor,local.taoyuan.water_level,local.taoyuan.rainfall"
            ),
            "SOURCE_TAOYUAN_FLOOD_SENSOR_ENABLED": "true",
            "SOURCE_TAOYUAN_FLOOD_SENSOR_API_ENABLED": "true",
            "SOURCE_TAOYUAN_WATER_LEVEL_ENABLED": "true",
            "SOURCE_TAOYUAN_WATER_LEVEL_API_ENABLED": "true",
            "SOURCE_TAOYUAN_RAINFALL_ENABLED": "true",
            "SOURCE_TAOYUAN_RAINFALL_API_ENABLED": "true",
            "TAOYUAN_WATER_TIMEOUT_SECONDS": "5",
        }
    )

    adapters = build_runtime_adapters(
        settings,
        fetched_at=FETCHED_AT,
        taoyuan_flood_sensor_fetch_text=lambda url, timeout: _flood_xml(),
        taoyuan_water_level_fetch_text=lambda url, timeout: _water_level_xml(),
        taoyuan_rainfall_fetch_text=lambda url, timeout: _rainfall_xml(),
    )

    assert tuple(adapters) == (
        "local.taoyuan.flood_sensor",
        "local.taoyuan.water_level",
        "local.taoyuan.rainfall",
    )
    assert len(adapters["local.taoyuan.flood_sensor"].run().normalized) == 1
    assert len(adapters["local.taoyuan.water_level"].run().normalized) == 1
    assert len(adapters["local.taoyuan.rainfall"].run().normalized) == 1
    assert TAOYUAN_FLOOD_SENSOR_API_URL.endswith("WATERFLOOD.xml")
    assert TAOYUAN_WATER_LEVEL_API_URL.endswith("WATERLEVEL.xml")
    assert TAOYUAN_RAINFALL_API_URL.startswith("https://opendata.tycg.gov.tw/")
