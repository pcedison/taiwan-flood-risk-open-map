from __future__ import annotations

from datetime import UTC, datetime

from app.adapters.contracts import EventType, SourceFamily
from app.adapters.local_tainan import (
    TAINAN_FLOOD_SENSOR_API_URL,
    TAINAN_FLOOD_SENSOR_DATA_GOV_URL,
    TAINAN_FLOOD_SENSOR_METADATA,
    TAINAN_FLOOD_SENSOR_METADATA_API_URL,
    TainanFloodSensorApiAdapter,
    parse_tainan_flood_sensor_metadata_payload,
    parse_tainan_flood_sensor_realtime_payload,
)
from app.adapters.registry import ADAPTER_REGISTRY, enabled_adapter_keys
from app.config import load_worker_settings
from app.jobs.runtime import build_runtime_adapters
from app.pipelines.staging import build_staging_batch


FETCHED_AT = datetime(2026, 6, 27, 4, 0, tzinfo=UTC)


def _realtime_payload() -> dict:
    return {
        "contentType": "application/json; charset=utf-8",
        "data": [
            {
                "StationID": "f001",
                "InfoTime": "2026-06-27T11:25:03",
                "WaterDepth": 18.5,
                "BatteryVoltage": 4.05,
                "RSSI": -135.0,
                "SNR": -16.0,
                "IsWaterInnerDoubt": False,
                "IsEnabled": True,
            },
            {
                "StationID": "f002",
                "InfoTime": "2026-06-27T11:26:03",
                "WaterDepth": 0.0,
                "BatteryVoltage": 3.98,
                "RSSI": -90.0,
                "SNR": -7.0,
                "IsWaterInnerDoubt": True,
                "IsEnabled": True,
            },
        ],
    }


def _metadata_payload() -> dict:
    return {
        "contentType": "application/json; charset=utf-8",
        "data": [
            {
                "StationID": "f001",
                "StationName": "仁德區-行大街172巷46號前",
                "DistrictID": 717,
                "Owner": "臺南市政府水利局",
                "LandLevel": 3.709,
                "AlertLevel": 15.0,
                "Point": {"Longitude": 120.219152, "Latitude": 22.915643},
                "IsEnabled": True,
            },
            {
                "StationID": "f002",
                "StationName": "永康區-崑山國小前",
                "DistrictID": 710,
                "Owner": "臺南市政府水利局",
                "LandLevel": 8.414,
                "AlertLevel": 10.0,
                "Point": None,
                "IsEnabled": True,
            },
        ],
    }


def test_tainan_metadata_and_realtime_join_to_station_point() -> None:
    metadata = parse_tainan_flood_sensor_metadata_payload(_metadata_payload())

    records = parse_tainan_flood_sensor_realtime_payload(
        _realtime_payload(),
        source_url=TAINAN_FLOOD_SENSOR_DATA_GOV_URL,
        resource_url=TAINAN_FLOOD_SENSOR_API_URL,
        station_metadata=metadata,
        station_metadata_url=TAINAN_FLOOD_SENSOR_METADATA_API_URL,
    )

    assert len(records) == 2
    first = records[0]
    assert first["station_id"] == "f001"
    assert first["station_name"] == "仁德區-行大街172巷46號前"
    assert first["observed_at"] == "2026-06-27T03:25:03+00:00"
    assert first["flood_depth_cm"] == 18.5
    assert first["alert_level_cm"] == 15.0
    assert first["authority"] == "臺南市政府水利局"
    assert first["geometry"] == {
        "type": "Point",
        "coordinates": [120.219152, 22.915643],
    }
    assert first["location_text"] == "仁德區-行大街172巷46號前"
    assert first["quality_flags"]["missing_station_coordinates"] is False


def test_tainan_api_adapter_outputs_local_flood_report_evidence() -> None:
    calls: list[tuple[str, int]] = []

    def fetch_json(url: str, timeout_seconds: int) -> dict:
        calls.append((url, timeout_seconds))
        if url == TAINAN_FLOOD_SENSOR_METADATA_API_URL:
            return _metadata_payload()
        return _realtime_payload()

    adapter = TainanFloodSensorApiAdapter(
        fetched_at=FETCHED_AT,
        timeout_seconds=5,
        fetch_json=fetch_json,
    )

    result = adapter.run()

    assert calls == [
        (TAINAN_FLOOD_SENSOR_METADATA_API_URL, 5),
        (TAINAN_FLOOD_SENSOR_API_URL, 5),
    ]
    assert result.adapter_key == "local.tainan.flood_sensor"
    assert len(result.fetched) == 2
    assert len(result.normalized) == 2
    evidence = result.normalized[0]
    assert evidence.adapter_key == "local.tainan.flood_sensor"
    assert evidence.source_family is SourceFamily.OFFICIAL
    assert evidence.event_type is EventType.FLOOD_REPORT
    assert evidence.source_id == "f001:2026-06-27T03:25:03+00:00"
    assert "水深 18.5 公分" in evidence.summary
    assert "local_tainan" in evidence.tags
    assert "supplemental_civil_iot" in evidence.tags
    assert result.fetched[0].source_url == TAINAN_FLOOD_SENSOR_DATA_GOV_URL
    assert result.fetched[0].payload["resource_url"] == TAINAN_FLOOD_SENSOR_API_URL


def test_tainan_records_missing_coordinates_keep_quality_flag_without_point_payload() -> None:
    def fetch_json(url: str, timeout_seconds: int) -> dict:
        del timeout_seconds
        if url == TAINAN_FLOOD_SENSOR_METADATA_API_URL:
            return _metadata_payload()
        return _realtime_payload()

    adapter = TainanFloodSensorApiAdapter(
        fetched_at=FETCHED_AT,
        fetch_json=fetch_json,
    )

    result = adapter.run()
    missing_coordinate_raw = result.fetched[1]

    assert "geometry" not in missing_coordinate_raw.payload
    assert missing_coordinate_raw.payload["quality_flags"] == {
        "missing_station_coordinates": True,
        "station_metadata_missing": False,
        "water_inner_doubt": True,
    }
    assert "missing_station_coordinates" in result.normalized[1].tags
    staging = build_staging_batch(result, raw_ref="raw/local/tainan/flood_sensor/test.json")
    missing_coordinate_staged = staging.accepted[1]
    assert "location_payload" not in missing_coordinate_staged.payload
    assert missing_coordinate_staged.payload["quality_flags"]["missing_station_coordinates"] is True


def test_tainan_adapter_registry_and_config_are_default_off() -> None:
    settings = load_worker_settings({})

    assert ADAPTER_REGISTRY[TAINAN_FLOOD_SENSOR_METADATA.key] is TAINAN_FLOOD_SENSOR_METADATA
    assert TAINAN_FLOOD_SENSOR_METADATA.key == "local.tainan.flood_sensor"
    assert TAINAN_FLOOD_SENSOR_METADATA.enabled_by_default is False
    assert settings.source_tainan_flood_sensor_enabled is None
    assert settings.source_tainan_flood_sensor_api_enabled is False
    assert settings.source_tainan_flood_sensor_timeout_seconds == 8
    assert "local.tainan.flood_sensor" not in enabled_adapter_keys(settings)
    assert TAINAN_FLOOD_SENSOR_API_URL == (
        "https://soa.tainan.gov.tw/Api/Service/Get/21b31a27-3e61-48b8-8259-83c2001bec8c"
    )
    assert TAINAN_FLOOD_SENSOR_METADATA_API_URL == (
        "https://soa.tainan.gov.tw/Api/Service/Get/cdc1ead4-d56a-4092-8e1c-e1f2fa9ee864"
    )


def test_build_runtime_adapters_includes_tainan_only_when_both_gates_are_on() -> None:
    source_only_settings = load_worker_settings({"SOURCE_TAINAN_FLOOD_SENSOR_ENABLED": "true"})

    assert "local.tainan.flood_sensor" in enabled_adapter_keys(source_only_settings)
    assert (
        "local.tainan.flood_sensor"
        not in build_runtime_adapters(source_only_settings, fetched_at=FETCHED_AT)
    )

    live_settings = load_worker_settings(
        {
            "SOURCE_TAINAN_FLOOD_SENSOR_ENABLED": "true",
            "SOURCE_TAINAN_FLOOD_SENSOR_API_ENABLED": "true",
            "SOURCE_TAINAN_FLOOD_SENSOR_TIMEOUT_SECONDS": "5",
        }
    )
    calls: list[tuple[str, int]] = []

    def fetch_json(url: str, timeout_seconds: int) -> dict:
        calls.append((url, timeout_seconds))
        if url == TAINAN_FLOOD_SENSOR_METADATA_API_URL:
            return _metadata_payload()
        return _realtime_payload()

    adapters = build_runtime_adapters(
        live_settings,
        fetched_at=FETCHED_AT,
        tainan_flood_sensor_fetch_json=fetch_json,
    )

    assert "local.tainan.flood_sensor" in adapters
    assert len(adapters["local.tainan.flood_sensor"].run().normalized) == 2
    assert calls == [
        (TAINAN_FLOOD_SENSOR_METADATA_API_URL, 5),
        (TAINAN_FLOOD_SENSOR_API_URL, 5),
    ]
