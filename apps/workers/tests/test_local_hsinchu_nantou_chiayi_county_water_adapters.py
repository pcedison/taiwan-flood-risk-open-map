from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.adapters.contracts import EventType, SourceFamily
from app.adapters.local_chiayi_county import (
    CHIAYI_COUNTY_FLOOD_SENSOR_API_URL,
    ChiayiCountyFloodSensorApiAdapter,
)
from app.adapters.local_hsinchu_city import (
    HSINCHU_CITY_FLOOD_SENSOR_REALTIME_API_URL,
    HSINCHU_CITY_FLOOD_SENSOR_STATION_API_URL,
    HSINCHU_CITY_SEWER_BASE_API_URL,
    HSINCHU_CITY_SEWER_REALTIME_API_URL,
    HsinchuCityFloodSensorApiAdapter,
    HsinchuCitySewerWaterLevelApiAdapter,
)
from app.adapters.local_nantou import (
    NANTOU_SEWER_WATER_LEVEL_KML_URL,
    NantouSewerWaterLevelKmlAdapter,
)
from app.config import load_worker_settings
from app.jobs.runtime import build_runtime_adapters


FETCHED_AT = datetime(2026, 6, 28, 8, 30, tzinfo=UTC)


def _hsinchu_sewer_base_payload() -> list[dict[str, Any]]:
    return [
        {
            "Stt_No": "10018-000035",
            "Stt_Name": "東區埔頂路 LM35",
            "Lon": 121.0162175,
            "Lat": 24.7928,
            "Addr": "新竹市東區埔頂路與崇和路口",
            "Manager": "新竹市政府工務處下水道科",
            "EqInfos": [
                {
                    "Dev_UUID": "0806df2d-088a-4718-bb4c-49ce76a11e79",
                    "Stt_No": "10018-000035",
                    "Half_Elev": 0.75,
                    "Full_Elev": 1.5,
                    "Abs_Half_Elev": 18.085,
                    "Abs_Full_Elev": 18.835,
                    "Val_Name": "水深",
                    "Val_Unit": "m",
                }
            ],
        }
    ]


def _hsinchu_sewer_realtime_payload() -> list[dict[str, Any]]:
    return [
        {
            "Time": "2026-06-28T16:20:02.393",
            "Dev_UUID": "0806df2d-088a-4718-bb4c-49ce76a11e79",
            "WaterDepth": 0.3568076193332672,
            "WaterLevelElevation": 17.691807619333268,
            "Voltage": 13.195730209350586,
            "BatLevel": 38.18,
            "FlagName": "檢核通過，無異常",
        },
        {
            "Time": "2026-06-28T16:20:02.393",
            "Dev_UUID": "missing-station-metadata",
            "WaterDepth": 0.2,
        },
    ]


def _hsinchu_flood_station_payload() -> dict[str, Any]:
    return {
        "d": {
            "UpdataTime": "2026/06/28 15:22:01",
            "Data": [
                {
                    "SensorUUID": "6b6475a4-80ad-4770-b5e3-b346ee61d342",
                    "Supplier": "新竹市政府",
                    "CityCode": "10018",
                    "SensorName": "延平路二段1553號",
                    "Address": "延平路二段1553號",
                    "Point": {"Latitude": 24.823241, "Longitude": 120.926782},
                    "SensorType": "壓力式",
                },
                {
                    "SensorUUID": "outside-hsinchu-city",
                    "Supplier": "其他縣市政府",
                    "CityCode": "10004",
                    "SensorName": "不應匯入",
                    "Point": {"Latitude": 24.9, "Longitude": 121.0},
                },
            ],
        }
    }


def _hsinchu_flood_realtime_payload() -> dict[str, Any]:
    return {
        "d": {
            "UpdataTime": "2026/06/28 16:28:36",
            "Data": [
                {
                    "SensorUUID": "6b6475a4-80ad-4770-b5e3-b346ee61d342",
                    "Depth": 4,
                    "SourceTime": "/Date(1782632040000)/",
                    "TransferTime": "/Date(1782632736083)/",
                    "ToBeConfirm": False,
                },
                {
                    "SensorUUID": "outside-hsinchu-city",
                    "Depth": 9,
                    "SourceTime": "/Date(1782632040000)/",
                },
            ],
        }
    }


def _nantou_kml() -> str:
    return """
    <kml xmlns="http://www.opengis.net/kml/2.2">
      <Document>
        <Placemark>
          <name>埔里鎮-埔里01</name>
          <description><![CDATA[
            <jsonDescription style="display:none;">
            {"title":"埔里鎮-埔里01","datas":[
              {"title":"水位高度(m)","value":"0.03"},
              {"title":"時雨量(mm)","value":"0"},
              {"title":"更新時間","value":"2026/06/28 16:20:00"},
              {"type":"iframe","title":"","url":"https://sewer.nantou.gov.tw/SEWER/Chart/WaterValue?ID=NTSW0046"}
            ]}
            </jsonDescription>
          ]]></description>
          <Point><coordinates>120.969535,23.973575,0</coordinates></Point>
        </Placemark>
      </Document>
    </kml>
    """


def _chiayi_county_payload() -> dict[str, Any]:
    return {
        "data": [
            {
                "_id": "cb0cc0a5-664b-43a0-9566-c8db87c1a9bf",
                "name": "CYC018 布袋鎮樹林里",
                "lon": 120.217021,
                "lat": 23.4169616,
                "county": "嘉義縣",
                "town": "布袋鎮",
                "village": "樹林里",
                "institution": "嘉義縣政府",
                "department": "水利處防洪維護科",
                "status": "online",
                "latest": {
                    "data": {"waterDepth": 7, "mbBatteryVolt": 13.6},
                    "time": "2026-06-28T08:00:21Z",
                },
                "type": "RFD",
            },
            {
                "_id": "missing-latest",
                "name": "缺少即時資料",
                "lon": 120.2,
                "lat": 23.4,
                "county": "嘉義縣",
            },
        ]
    }


def test_hsinchu_city_sewer_api_outputs_water_level_from_live_and_base_join() -> None:
    def fetch_json(url: str, timeout: int) -> Any:
        if url == HSINCHU_CITY_SEWER_BASE_API_URL:
            return _hsinchu_sewer_base_payload()
        if url == HSINCHU_CITY_SEWER_REALTIME_API_URL:
            return _hsinchu_sewer_realtime_payload()
        raise AssertionError(f"unexpected URL {url}")

    adapter = HsinchuCitySewerWaterLevelApiAdapter(
        fetched_at=FETCHED_AT,
        timeout_seconds=5,
        fetch_json=fetch_json,
    )

    result = adapter.run()

    assert result.adapter_key == "local.hsinchu_city.sewer_water_level"
    assert len(result.fetched) == 1
    assert len(result.normalized) == 1
    raw_payload = result.fetched[0].payload
    assert raw_payload["station_id"] == "0806df2d-088a-4718-bb4c-49ce76a11e79"
    assert raw_payload["station_no"] == "10018-000035"
    assert raw_payload["station_name"] == "東區埔頂路 LM35"
    assert raw_payload["observed_at"] == "2026-06-28T08:20:02.393000+00:00"
    assert raw_payload["water_level_m"] == 0.3568076193332672
    assert raw_payload["water_level_elevation_m"] == 17.691807619333268
    assert raw_payload["warning_level_m"] == 0.75
    assert raw_payload["red_alert_level_m"] == 1.5
    assert raw_payload["geometry"] == {
        "type": "Point",
        "coordinates": [121.0162175, 24.7928],
    }
    evidence = result.normalized[0]
    assert evidence.event_type is EventType.WATER_LEVEL
    assert evidence.source_family is SourceFamily.OFFICIAL
    assert "0.36 公尺" in evidence.summary
    assert "local_hsinchu_city" in evidence.tags
    assert "sewer_water_level" in evidence.tags


def test_hsinchu_city_flood_sensor_api_filters_city_and_outputs_flood_depth() -> None:
    def fetch_json(url: str, timeout: int) -> Any:
        if url == HSINCHU_CITY_FLOOD_SENSOR_STATION_API_URL:
            return _hsinchu_flood_station_payload()
        if url == HSINCHU_CITY_FLOOD_SENSOR_REALTIME_API_URL:
            return _hsinchu_flood_realtime_payload()
        raise AssertionError(f"unexpected URL {url}")

    adapter = HsinchuCityFloodSensorApiAdapter(
        fetched_at=FETCHED_AT,
        fetch_json=fetch_json,
    )

    result = adapter.run()

    assert result.adapter_key == "local.hsinchu_city.flood_sensor"
    assert len(result.fetched) == 1
    assert len(result.normalized) == 1
    raw_payload = result.fetched[0].payload
    assert raw_payload["station_id"] == "6b6475a4-80ad-4770-b5e3-b346ee61d342"
    assert raw_payload["station_name"] == "延平路二段1553號"
    assert raw_payload["observed_at"] == "2026-06-28T07:34:00+00:00"
    assert raw_payload["flood_depth_cm"] == 4.0
    assert raw_payload["geometry"] == {
        "type": "Point",
        "coordinates": [120.926782, 24.823241],
    }
    evidence = result.normalized[0]
    assert evidence.event_type is EventType.FLOOD_REPORT
    assert "水深 4 公分" in evidence.summary
    assert "local_hsinchu_city" in evidence.tags
    assert "flood_sensor" in evidence.tags


def test_nantou_kml_outputs_sewer_water_level_with_hourly_rainfall_context() -> None:
    adapter = NantouSewerWaterLevelKmlAdapter(
        fetched_at=FETCHED_AT,
        fetch_text=lambda url, timeout: _nantou_kml(),
    )

    result = adapter.run()

    assert result.adapter_key == "local.nantou.sewer_water_level"
    assert len(result.fetched) == 1
    raw_payload = result.fetched[0].payload
    assert raw_payload["station_id"] == "NTSW0046"
    assert raw_payload["station_name"] == "埔里鎮-埔里01"
    assert raw_payload["town"] == "埔里鎮"
    assert raw_payload["observed_at"] == "2026-06-28T08:20:00+00:00"
    assert raw_payload["water_level_m"] == 0.03
    assert raw_payload["rainfall_mm_1h"] == 0.0
    assert raw_payload["geometry"] == {
        "type": "Point",
        "coordinates": [120.969535, 23.973575],
    }
    evidence = result.normalized[0]
    assert evidence.event_type is EventType.WATER_LEVEL
    assert "0.03 公尺" in evidence.summary
    assert "local_nantou" in evidence.tags
    assert "sewer_water_level" in evidence.tags


def test_chiayi_county_flood_sensor_api_outputs_public_rfd_depth() -> None:
    adapter = ChiayiCountyFloodSensorApiAdapter(
        fetched_at=FETCHED_AT,
        fetch_json=lambda url, timeout: _chiayi_county_payload(),
    )

    result = adapter.run()

    assert result.adapter_key == "local.chiayi_county.flood_sensor"
    assert len(result.fetched) == 1
    assert len(result.normalized) == 1
    raw_payload = result.fetched[0].payload
    assert raw_payload["station_id"] == "cb0cc0a5-664b-43a0-9566-c8db87c1a9bf"
    assert raw_payload["station_name"] == "CYC018 布袋鎮樹林里"
    assert raw_payload["observed_at"] == "2026-06-28T08:00:21+00:00"
    assert raw_payload["flood_depth_cm"] == 7.0
    assert raw_payload["battery_voltage"] == 13.6
    assert raw_payload["town"] == "布袋鎮"
    assert raw_payload["village"] == "樹林里"
    assert raw_payload["geometry"] == {
        "type": "Point",
        "coordinates": [120.217021, 23.4169616],
    }
    evidence = result.normalized[0]
    assert evidence.event_type is EventType.FLOOD_REPORT
    assert "水深 7 公分" in evidence.summary
    assert "local_chiayi_county" in evidence.tags
    assert "flood_sensor" in evidence.tags


def test_build_runtime_adapters_wires_new_local_sources_when_gates_are_on() -> None:
    settings = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": (
                "local.hsinchu_city.sewer_water_level,local.hsinchu_city.flood_sensor,"
                "local.nantou.sewer_water_level,local.chiayi_county.flood_sensor"
            ),
            "SOURCE_HSINCHU_CITY_SEWER_WATER_LEVEL_ENABLED": "true",
            "SOURCE_HSINCHU_CITY_SEWER_WATER_LEVEL_API_ENABLED": "true",
            "SOURCE_HSINCHU_CITY_FLOOD_SENSOR_ENABLED": "true",
            "SOURCE_HSINCHU_CITY_FLOOD_SENSOR_API_ENABLED": "true",
            "SOURCE_NANTOU_SEWER_WATER_LEVEL_ENABLED": "true",
            "SOURCE_NANTOU_SEWER_WATER_LEVEL_API_ENABLED": "true",
            "SOURCE_CHIAYI_COUNTY_FLOOD_SENSOR_ENABLED": "true",
            "SOURCE_CHIAYI_COUNTY_FLOOD_SENSOR_API_ENABLED": "true",
            "LOCAL_WATER_TIMEOUT_SECONDS": "5",
        }
    )

    adapters = build_runtime_adapters(
        settings,
        fetched_at=FETCHED_AT,
        hsinchu_city_sewer_fetch_json=lambda url, timeout: (
            _hsinchu_sewer_base_payload()
            if url == HSINCHU_CITY_SEWER_BASE_API_URL
            else _hsinchu_sewer_realtime_payload()
        ),
        hsinchu_city_flood_sensor_fetch_json=lambda url, timeout: (
            _hsinchu_flood_station_payload()
            if url == HSINCHU_CITY_FLOOD_SENSOR_STATION_API_URL
            else _hsinchu_flood_realtime_payload()
        ),
        nantou_sewer_water_level_fetch_text=lambda url, timeout: _nantou_kml(),
        chiayi_county_flood_sensor_fetch_json=lambda url, timeout: _chiayi_county_payload(),
    )

    assert tuple(adapters) == (
        "local.hsinchu_city.sewer_water_level",
        "local.hsinchu_city.flood_sensor",
        "local.nantou.sewer_water_level",
        "local.chiayi_county.flood_sensor",
    )
    assert len(adapters["local.hsinchu_city.sewer_water_level"].run().normalized) == 1
    assert len(adapters["local.hsinchu_city.flood_sensor"].run().normalized) == 1
    assert len(adapters["local.nantou.sewer_water_level"].run().normalized) == 1
    assert len(adapters["local.chiayi_county.flood_sensor"].run().normalized) == 1
    assert NANTOU_SEWER_WATER_LEVEL_KML_URL.startswith("https://dpinfo.nantou.gov.tw/")
    assert CHIAYI_COUNTY_FLOOD_SENSOR_API_URL.startswith("https://api.floodsolution.aiot.ing/")
