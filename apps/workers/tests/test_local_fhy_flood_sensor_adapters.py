from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.adapters.contracts import EventType, SourceFamily
from app.adapters.local_fhy import (
    CHANGHUA_FHY_FLOOD_SENSOR,
    HSINCHU_COUNTY_FHY_FLOOD_SENSOR,
    HUALIEN_FHY_FLOOD_SENSOR,
    MIAOLI_FHY_FLOOD_SENSOR,
    PINGTUNG_FHY_FLOOD_SENSOR,
    TAITUNG_FHY_FLOOD_SENSOR,
    FHY_FLOOD_SENSOR_REALTIME_API_URL,
    FHY_FLOOD_SENSOR_STATION_API_URL,
    FhyFloodSensorApiAdapter,
)
from app.config import load_worker_settings
from app.jobs.runtime import build_runtime_adapters


FETCHED_AT = datetime(2026, 6, 28, 10, 0, tzinfo=UTC)


def _station_payload(source: Any) -> dict[str, Any]:
    local_supplier = source.supplier_tokens[0]
    return {
        "d": {
            "Data": [
                {
                    "SensorUUID": f"{source.slug}-local",
                    "Supplier": local_supplier,
                    "CityCode": str(source.city_code),
                    "SensorName": f"{source.county}地方淹水感測器",
                    "Address": f"{source.county}測試路1號",
                    "Point": {"Latitude": 24.1, "Longitude": 120.5},
                    "SensorType": "壓力式",
                },
                {
                    "SensorUUID": f"{source.slug}-central",
                    "Supplier": "經濟部水利署第四河川分署",
                    "CityCode": str(source.city_code),
                    "SensorName": "中央供應站不應列 local",
                    "Address": "中央供應站",
                    "Point": {"Latitude": 24.2, "Longitude": 120.6},
                    "SensorType": "壓力式",
                },
            ]
        }
    }


def _realtime_payload(source: Any, *, stale: bool = False) -> dict[str, Any]:
    source_time = "/Date(1782639600000)/"
    if stale:
        source_time = "/Date(1782532800000)/"
    return {
        "d": {
            "Data": [
                {
                    "SensorUUID": f"{source.slug}-local",
                    "Depth": 6,
                    "SourceTime": source_time,
                    "TransferTime": "/Date(1782639660000)/",
                    "ToBeConfirm": False,
                },
                {
                    "SensorUUID": f"{source.slug}-central",
                    "Depth": 9,
                    "SourceTime": "/Date(1782639600000)/",
                    "ToBeConfirm": False,
                },
            ]
        }
    }


def test_fhy_local_flood_adapter_filters_to_local_government_supplier() -> None:
    adapter = FhyFloodSensorApiAdapter(
        HSINCHU_COUNTY_FHY_FLOOD_SENSOR,
        fetched_at=FETCHED_AT,
        fetch_json=lambda url, timeout, body: (
            _station_payload(HSINCHU_COUNTY_FHY_FLOOD_SENSOR)
            if url == FHY_FLOOD_SENSOR_STATION_API_URL
            else _realtime_payload(HSINCHU_COUNTY_FHY_FLOOD_SENSOR)
        ),
    )

    result = adapter.run()

    assert result.adapter_key == "local.hsinchu_county.flood_sensor"
    assert len(result.fetched) == 1
    assert len(result.normalized) == 1
    raw_payload = result.fetched[0].payload
    assert raw_payload["station_id"] == "hsinchu_county-local"
    assert raw_payload["authority"] == "新竹縣政府"
    assert raw_payload["observed_at"] == "2026-06-28T09:40:00+00:00"
    assert raw_payload["flood_depth_cm"] == 6.0
    assert raw_payload["geometry"] == {
        "type": "Point",
        "coordinates": [120.5, 24.1],
    }
    evidence = result.normalized[0]
    assert evidence.event_type is EventType.FLOOD_REPORT
    assert evidence.source_family is SourceFamily.OFFICIAL
    assert "水深 6 公分" in evidence.summary
    assert "local_hsinchu_county" in evidence.tags
    assert "fhy_flood_sensor" in evidence.tags


def test_fhy_local_flood_adapter_rejects_stale_joined_observation() -> None:
    adapter = FhyFloodSensorApiAdapter(
        MIAOLI_FHY_FLOOD_SENSOR,
        fetched_at=FETCHED_AT,
        fetch_json=lambda url, timeout, body: (
            _station_payload(MIAOLI_FHY_FLOOD_SENSOR)
            if url == FHY_FLOOD_SENSOR_STATION_API_URL
            else _realtime_payload(MIAOLI_FHY_FLOOD_SENSOR, stale=True)
        ),
    )

    result = adapter.run()

    assert result.adapter_key == "local.miaoli.flood_sensor"
    assert len(result.fetched) == 1
    assert result.normalized == ()
    assert result.rejected == ("miaoli-local:2026-06-27T04:00:00+00:00",)


def test_build_runtime_adapters_wires_all_new_fhy_local_sources_when_gates_are_on() -> None:
    sources = (
        HSINCHU_COUNTY_FHY_FLOOD_SENSOR,
        MIAOLI_FHY_FLOOD_SENSOR,
        CHANGHUA_FHY_FLOOD_SENSOR,
        PINGTUNG_FHY_FLOOD_SENSOR,
        HUALIEN_FHY_FLOOD_SENSOR,
        TAITUNG_FHY_FLOOD_SENSOR,
    )
    source_by_city_code = {source.city_code: source for source in sources}

    def fetch_json(url: str, timeout: int, body: dict[str, Any] | None) -> Any:
        if url == FHY_FLOOD_SENSOR_STATION_API_URL:
            assert body is not None
            return _station_payload(source_by_city_code[int(body["cityCode"])])
        assert url == FHY_FLOOD_SENSOR_REALTIME_API_URL
        return {
            "d": {
                "Data": [
                    item
                    for source in sources
                    for item in _realtime_payload(source)["d"]["Data"]
                ]
            }
        }

    settings = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": ",".join(source.metadata.key for source in sources),
            "SOURCE_HSINCHU_COUNTY_FHY_FLOOD_SENSOR_ENABLED": "true",
            "SOURCE_HSINCHU_COUNTY_FHY_FLOOD_SENSOR_API_ENABLED": "true",
            "SOURCE_MIAOLI_FHY_FLOOD_SENSOR_ENABLED": "true",
            "SOURCE_MIAOLI_FHY_FLOOD_SENSOR_API_ENABLED": "true",
            "SOURCE_CHANGHUA_FHY_FLOOD_SENSOR_ENABLED": "true",
            "SOURCE_CHANGHUA_FHY_FLOOD_SENSOR_API_ENABLED": "true",
            "SOURCE_PINGTUNG_FHY_FLOOD_SENSOR_ENABLED": "true",
            "SOURCE_PINGTUNG_FHY_FLOOD_SENSOR_API_ENABLED": "true",
            "SOURCE_HUALIEN_FHY_FLOOD_SENSOR_ENABLED": "true",
            "SOURCE_HUALIEN_FHY_FLOOD_SENSOR_API_ENABLED": "true",
            "SOURCE_TAITUNG_FHY_FLOOD_SENSOR_ENABLED": "true",
            "SOURCE_TAITUNG_FHY_FLOOD_SENSOR_API_ENABLED": "true",
            "LOCAL_WATER_TIMEOUT_SECONDS": "5",
        }
    )

    adapters = build_runtime_adapters(
        settings,
        fetched_at=FETCHED_AT,
        fhy_flood_sensor_fetch_json=fetch_json,
    )

    assert tuple(adapters) == tuple(source.metadata.key for source in sources)
    for source in sources:
        result = adapters[source.metadata.key].run()
        assert len(result.fetched) == 1
        assert len(result.normalized) == 1
