from __future__ import annotations

from datetime import UTC, datetime

from app.adapters.civil_iot import (
    FLOOD_SENSOR_METADATA,
    RIVER_WATER_LEVEL_METADATA,
    CivilIotStaPayloadError,
    CivilIotRiverAdapter,
    CivilIotRiverApiAdapter,
    FloodSensorAdapter,
    FloodSensorStaApiAdapter,
    parse_sta_things_payload,
)
from app.adapters.contracts import EventType, SourceFamily
from app.adapters.registry import ADAPTER_REGISTRY, enabled_adapter_keys
from app.config import load_worker_settings
from app.jobs.runtime import build_runtime_adapters


FETCHED_AT = datetime(2026, 6, 15, 3, 10, tzinfo=UTC)


def _flood_sensor_payload() -> dict:
    return {
        "value": [
            {
                "@iot.id": 1001,
                "name": "中正路淹水感測器",
                "properties": {
                    "stationID": "FS-001",
                    "authority": "水利署",
                    "city": "臺南市",
                    "town": "中西區",
                },
                "Locations": [
                    {"location": {"type": "Point", "coordinates": [120.2, 23.0]}}
                ],
                "Datastreams": [
                    {
                        "name": "淹水深度",
                        "unitOfMeasurement": {"symbol": "cm"},
                        "Observations": [
                            {
                                "phenomenonTime": "2026-06-15T03:00:00.000Z",
                                "result": 18.0,
                            }
                        ],
                    }
                ],
            },
            {
                "@iot.id": 1002,
                "name": "乾燥路段感測器",
                "properties": {"stationID": "FS-002", "authority": "水利署"},
                "Locations": [
                    {"location": {"type": "Point", "coordinates": [120.21, 23.01]}}
                ],
                "Datastreams": [
                    {
                        "name": "淹水深度",
                        "unitOfMeasurement": {"symbol": "cm"},
                        "Observations": [
                            {
                                "phenomenonTime": "2026-06-15T03:00:00.000Z",
                                "result": 0.0,
                            }
                        ],
                    }
                ],
            },
            {
                "@iot.id": 1003,
                "name": "低水深路段感測器",
                "properties": {"stationID": "FS-003", "authority": "水利署"},
                "Locations": [
                    {"location": {"type": "Point", "coordinates": [120.22, 23.02]}}
                ],
                "Datastreams": [
                    {
                        "name": "淹水深度",
                        "unitOfMeasurement": {"symbol": "cm"},
                        "Observations": [
                            {
                                "phenomenonTime": "2026-06-15T03:00:00.000Z",
                                "result": 2.0,
                            }
                        ],
                    }
                ],
            },
        ]
    }


def _river_payload() -> dict:
    return {
        "value": [
            {
                "@iot.id": 2001,
                "name": "二仁溪水位站",
                "properties": {"stationID": "WL-7", "authority": "水利署", "city": "高雄市"},
                "Locations": [
                    {"location": {"type": "Point", "coordinates": [120.3, 22.9]}}
                ],
                "Datastreams": [
                    {
                        "name": "水位",
                        "unitOfMeasurement": {"symbol": "m"},
                        "Observations": [
                            {
                                "phenomenonTime": "2026-06-15T03:05:00.000Z",
                                "result": 4.21,
                            }
                        ],
                    }
                ],
            },
            {
                "@iot.id": 2002,
                "name": "離線站",
                "properties": {"stationID": "WL-8", "authority": "水利署"},
                "Locations": [
                    {"location": {"type": "Point", "coordinates": [120.31, 22.91]}}
                ],
                "Datastreams": [
                    {
                        "name": "水位",
                        "unitOfMeasurement": {"symbol": "m"},
                        "Observations": [
                            {
                                "phenomenonTime": "2026-06-15T03:05:00.000Z",
                                "result": -999.0,
                            }
                        ],
                    }
                ],
            },
        ]
    }


def test_parse_sta_things_payload_flattens_latest_observation() -> None:
    records = parse_sta_things_payload(
        _flood_sensor_payload(), source_url="https://example.test/water_12"
    )

    assert len(records) == 3
    first = records[0]
    assert first["station_id"] == "FS-001"
    assert first["station_name"] == "中正路淹水感測器"
    assert first["value"] == 18.0
    assert first["observed_at"] == "2026-06-15T03:00:00+00:00"
    assert first["latitude"] == 23.0
    assert first["longitude"] == 120.2
    assert first["geometry"] == {"type": "Point", "coordinates": [120.2, 23.0]}
    assert first["location_text"] == "臺南市 中西區"
    assert first["authority"] == "水利署"


def test_flood_sensor_api_adapter_keeps_zero_and_low_depth_readings_distinct() -> None:
    adapter = FloodSensorStaApiAdapter(
        fetched_at=FETCHED_AT,
        fetch_json=lambda url, timeout: _flood_sensor_payload(),
    )

    result = adapter.run()

    assert len(result.fetched) == 3
    assert len(result.normalized) == 3
    assert len(result.rejected) == 0
    evidence = result.normalized[0]
    assert evidence.event_type is EventType.FLOOD_REPORT
    assert evidence.source_family is SourceFamily.OFFICIAL
    assert "水深 18 公分" in evidence.summary
    assert "flood_sensor" in evidence.tags
    raw_payload = result.fetched[0].payload
    assert raw_payload["flood_depth_cm"] == 18.0
    assert raw_payload["station_id"] == "FS-001"
    assert raw_payload["station_name"] == "中正路淹水感測器"
    assert raw_payload["authority"] == "水利署"
    assert raw_payload["datastream_name"] == "淹水深度"
    assert raw_payload["source_url"] == "https://ci.taiwan.gov.tw/dsp/Views/dataset/detail.aspx?id=water_12"
    dry_raw_payload = result.fetched[1].payload
    dry_evidence = result.normalized[1]
    assert dry_raw_payload["flood_depth_cm"] == 0.0
    assert dry_evidence.summary == "路面淹水感測：無觀測到淹水（乾燥，0 公分）（乾燥路段感測器）"
    assert "dry" in dry_evidence.tags
    assert "no_flooding_observed" in dry_evidence.tags
    assert "水深" not in dry_evidence.summary
    low_depth_raw_payload = result.fetched[2].payload
    low_depth_evidence = result.normalized[2]
    assert low_depth_raw_payload["flood_depth_cm"] == 2.0
    assert low_depth_evidence.event_type is EventType.FLOOD_REPORT
    assert low_depth_evidence.summary == "路面淹水感測：低水深觀測 2 公分（低水深路段感測器）"
    assert "below_flood_threshold" in low_depth_evidence.tags
    assert "low_depth_observation" in low_depth_evidence.tags
    assert "dry" not in low_depth_evidence.tags
    assert "no_flooding_observed" not in low_depth_evidence.tags


def test_flood_sensor_fixture_adapter_matches_threshold_rule() -> None:
    records = parse_sta_things_payload(
        _flood_sensor_payload(), source_url="https://example.test/water_12"
    )
    adapter = FloodSensorAdapter(records, fetched_at=FETCHED_AT)

    result = adapter.run()

    assert len(result.normalized) == 3
    assert result.normalized[0].source_id == "FS-001:2026-06-15T03:00:00+00:00"
    assert result.normalized[1].source_id == "FS-002:2026-06-15T03:00:00+00:00"
    assert result.normalized[2].source_id == "FS-003:2026-06-15T03:00:00+00:00"


def test_flood_sensor_api_adapter_fetches_paginated_sta_payload() -> None:
    page_by_url = {
        "https://example.test/sta/flood?page=1": {
            "value": _flood_sensor_payload()["value"][:1],
            "@iot.nextLink": "https://example.test/sta/flood?page=2",
        },
        "https://example.test/sta/flood?page=2": {
            "value": _flood_sensor_payload()["value"][1:],
        },
    }
    calls: list[tuple[str, int]] = []

    def fetch_json(url: str, timeout: int) -> dict:
        calls.append((url, timeout))
        return page_by_url[url]

    adapter = FloodSensorStaApiAdapter(
        sta_url="https://example.test/sta/flood?page=1",
        fetched_at=FETCHED_AT,
        fetch_json=fetch_json,
    )

    result = adapter.run()

    assert calls == [
        ("https://example.test/sta/flood?page=1", 8),
        ("https://example.test/sta/flood?page=2", 8),
    ]
    assert [item.payload["station_id"] for item in result.fetched] == [
        "FS-001",
        "FS-002",
        "FS-003",
    ]
    assert [item.source_id for item in result.normalized] == [
        "FS-001:2026-06-15T03:00:00+00:00",
        "FS-002:2026-06-15T03:00:00+00:00",
        "FS-003:2026-06-15T03:00:00+00:00",
    ]


def test_flood_sensor_api_adapter_raises_on_paginated_sta_loop() -> None:
    adapter = FloodSensorStaApiAdapter(
        sta_url="https://example.test/sta/flood?page=1",
        fetched_at=FETCHED_AT,
        fetch_json=lambda url, timeout: {
            "value": _flood_sensor_payload()["value"][:1],
            "@iot.nextLink": "https://example.test/sta/flood?page=1",
        },
    )

    try:
        adapter.fetch()
    except CivilIotStaPayloadError as exc:
        assert "nextLink" in str(exc)
    else:
        raise AssertionError("expected CivilIotStaPayloadError")


def test_civil_iot_river_adapter_normalizes_and_drops_invalid() -> None:
    adapter = CivilIotRiverApiAdapter(
        fetched_at=FETCHED_AT,
        fetch_json=lambda url, timeout: _river_payload(),
    )

    result = adapter.run()

    assert len(result.normalized) == 1
    assert len(result.rejected) == 1
    evidence = result.normalized[0]
    assert evidence.event_type is EventType.WATER_LEVEL
    assert "4.21 公尺" in evidence.summary


def test_civil_iot_river_fixture_adapter_normalizes() -> None:
    records = parse_sta_things_payload(
        _river_payload(), source_url="https://example.test/iow01"
    )
    adapter = CivilIotRiverAdapter(records, fetched_at=FETCHED_AT)

    result = adapter.run()

    assert len(result.normalized) == 1
    assert result.normalized[0].event_type is EventType.WATER_LEVEL


def test_new_adapters_registered_and_disabled_by_default() -> None:
    assert ADAPTER_REGISTRY[FLOOD_SENSOR_METADATA.key] is FLOOD_SENSOR_METADATA
    assert ADAPTER_REGISTRY[RIVER_WATER_LEVEL_METADATA.key] is RIVER_WATER_LEVEL_METADATA
    assert FLOOD_SENSOR_METADATA.enabled_by_default is False
    assert RIVER_WATER_LEVEL_METADATA.enabled_by_default is False

    default_keys = enabled_adapter_keys(load_worker_settings({}))
    assert "official.civil_iot.flood_sensor" not in default_keys
    assert "official.civil_iot.river_water_level" not in default_keys


def test_civil_iot_flags_enable_adapters() -> None:
    settings = load_worker_settings(
        {
            "SOURCE_FLOOD_SENSOR_ENABLED": "true",
            "SOURCE_CIVIL_IOT_RIVER_ENABLED": "true",
        }
    )

    keys = enabled_adapter_keys(settings)
    assert "official.civil_iot.flood_sensor" in keys
    assert "official.civil_iot.river_water_level" in keys


def test_civil_iot_config_reads_env() -> None:
    settings = load_worker_settings(
        {
            "SOURCE_FLOOD_SENSOR_API_ENABLED": "true",
            "SOURCE_FLOOD_SENSOR_USE_LIVE": "true",
            "SOURCE_CIVIL_IOT_RIVER_API_ENABLED": "true",
            "CIVIL_IOT_FLOOD_SENSOR_URL": "https://example.test/sta/flood",
            "CIVIL_IOT_RIVER_URL": "https://example.test/sta/river",
            "SOURCE_FLOOD_SENSOR_TIMEOUT_SECONDS": "5",
            "CIVIL_IOT_API_TIMEOUT_SECONDS": "5",
        }
    )

    assert settings.source_flood_sensor_api_enabled is True
    assert settings.source_flood_sensor_use_live is True
    assert settings.source_civil_iot_river_api_enabled is True
    assert settings.civil_iot_flood_sensor_url == "https://example.test/sta/flood"
    assert settings.civil_iot_river_url == "https://example.test/sta/river"
    assert settings.source_flood_sensor_timeout_seconds == 5
    assert settings.civil_iot_api_timeout_seconds == 5


def test_build_runtime_adapters_includes_enabled_civil_iot_live_adapters() -> None:
    settings = load_worker_settings(
        {
            "SOURCE_FLOOD_SENSOR_ENABLED": "true",
            "SOURCE_FLOOD_SENSOR_API_ENABLED": "true",
            "SOURCE_FLOOD_SENSOR_USE_LIVE": "true",
            "SOURCE_FLOOD_SENSOR_TIMEOUT_SECONDS": "5",
            "SOURCE_CIVIL_IOT_RIVER_ENABLED": "true",
            "SOURCE_CIVIL_IOT_RIVER_API_ENABLED": "true",
        }
    )

    flood_sensor_calls: list[tuple[str, int]] = []
    adapters = build_runtime_adapters(
        settings,
        fetched_at=FETCHED_AT,
        flood_sensor_fetch_json=lambda url, timeout: (
            flood_sensor_calls.append((url, timeout)) or _flood_sensor_payload()
        ),
        civil_iot_river_fetch_json=lambda url, timeout: _river_payload(),
    )

    assert "official.civil_iot.flood_sensor" in adapters
    assert "official.civil_iot.river_water_level" in adapters
    flood_result = adapters["official.civil_iot.flood_sensor"].run()
    assert len(flood_result.normalized) == 3
    assert flood_sensor_calls == [(adapters["official.civil_iot.flood_sensor"]._sta_url, 5)]


def test_build_runtime_adapters_keeps_flood_sensor_live_gate_off_by_default() -> None:
    settings = load_worker_settings(
        {
            "SOURCE_FLOOD_SENSOR_ENABLED": "true",
            "SOURCE_FLOOD_SENSOR_API_ENABLED": "true",
        }
    )

    adapters = build_runtime_adapters(
        settings,
        fetched_at=FETCHED_AT,
        flood_sensor_fetch_json=lambda url, timeout: _flood_sensor_payload(),
    )

    assert "official.civil_iot.flood_sensor" not in adapters
