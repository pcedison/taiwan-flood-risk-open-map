from __future__ import annotations

from datetime import UTC, datetime
from urllib.error import URLError

import pytest

from app.adapters.contracts import EventType, SourceFamily
from app.adapters.local_tainan import (
    DEFAULT_TAINAN_FLOOD_SENSOR_TIMEOUT_SECONDS,
    TAINAN_FLOOD_SENSOR_API_URL,
    TAINAN_FLOOD_SENSOR_DATA_GOV_URL,
    TAINAN_FLOOD_SENSOR_METADATA,
    TAINAN_FLOOD_SENSOR_METADATA_API_URL,
    TainanFloodSensorApiAdapter,
    parse_tainan_flood_sensor_metadata_payload,
    parse_tainan_flood_sensor_realtime_payload,
)
from app.adapters.local_tainan import flood_sensor as tainan_flood_sensor
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


class _ChunkedResponse:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = iter(chunks)
        self.read_count = 0

    def __enter__(self) -> _ChunkedResponse:
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def read1(self, size: int) -> bytes:
        assert size == tainan_flood_sensor.TAINAN_FLOOD_SENSOR_READ_CHUNK_BYTES
        self.read_count += 1
        try:
            return next(self._chunks)
        except StopIteration as exc:
            raise AssertionError("fetch waited for a terminal chunk after complete JSON") from exc

    def read(self, size: int) -> bytes:
        del size
        raise AssertionError("chunked responses must use read1 instead of EOF-bound read")


def test_tainan_fetch_returns_when_chunked_json_is_complete_without_waiting_for_eof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _ChunkedResponse((b'{"contentType":"application/json",', b'"data":[]}'))
    monkeypatch.setattr(tainan_flood_sensor, "urlopen", lambda *args, **kwargs: response)

    payload = tainan_flood_sensor.fetch_tainan_json(
        TAINAN_FLOOD_SENSOR_API_URL,
        DEFAULT_TAINAN_FLOOD_SENSOR_TIMEOUT_SECONDS,
    )

    assert payload == {"contentType": "application/json", "data": []}
    assert response.read_count == 2


def test_tainan_fetch_classifies_wrapped_upstream_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def timeout(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise URLError(TimeoutError("timed out"))

    monkeypatch.setattr(tainan_flood_sensor, "urlopen", timeout)

    with pytest.raises(tainan_flood_sensor.TainanFloodSensorTimeoutError):
        tainan_flood_sensor.fetch_tainan_json(
            TAINAN_FLOOD_SENSOR_API_URL,
            DEFAULT_TAINAN_FLOOD_SENSOR_TIMEOUT_SECONDS,
        )


def test_tainan_official_preview_extracts_html_encoded_json_without_waiting_for_eof() -> None:
    response = _ChunkedResponse(
        (
            b'<html><pre v-show="sourceType === type.json">[{&quot;StationID&quot;:',
            b'&quot;TN001&quot;,&quot;WaterDepth&quot;:0.0}]</pre><footer>',
        )
    )

    payload = tainan_flood_sensor._read_official_preview_json_document(response)

    assert payload == [{"StationID": "TN001", "WaterDepth": 0.0}]
    assert response.read_count == 2


def test_tainan_adapter_falls_back_to_same_resource_on_official_data_platform() -> None:
    calls: list[tuple[str, str]] = []

    def primary_fetch(url: str, timeout_seconds: int) -> object:
        assert timeout_seconds == DEFAULT_TAINAN_FLOOD_SENSOR_TIMEOUT_SECONDS
        calls.append(("primary", url))
        raise tainan_flood_sensor.TainanFloodSensorFetchError("primary unavailable")

    def preview_fetch(url: str, timeout_seconds: int) -> object:
        assert timeout_seconds == DEFAULT_TAINAN_FLOOD_SENSOR_TIMEOUT_SECONDS
        calls.append(("preview", url))
        if url == tainan_flood_sensor.TAINAN_FLOOD_SENSOR_METADATA_PREVIEW_URL:
            return _metadata_payload()["data"]
        return _realtime_payload()["data"]

    adapter = TainanFloodSensorApiAdapter(
        fetched_at=FETCHED_AT,
        fetch_json=primary_fetch,
        preview_fetch_json=preview_fetch,
    )

    result = adapter.run()

    assert calls == [
        ("primary", TAINAN_FLOOD_SENSOR_METADATA_API_URL),
        ("preview", tainan_flood_sensor.TAINAN_FLOOD_SENSOR_METADATA_PREVIEW_URL),
        ("primary", TAINAN_FLOOD_SENSOR_API_URL),
        ("preview", tainan_flood_sensor.TAINAN_FLOOD_SENSOR_PREVIEW_URL),
    ]
    assert len(result.normalized) == 1
    assert (
        result.fetched[0].payload["resource_url"]
        == tainan_flood_sensor.TAINAN_FLOOD_SENSOR_PREVIEW_URL
    )
    assert (
        result.fetched[0].payload["station_metadata_url"]
        == tainan_flood_sensor.TAINAN_FLOOD_SENSOR_METADATA_PREVIEW_URL
    )


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
        (
            TAINAN_FLOOD_SENSOR_METADATA_API_URL,
            DEFAULT_TAINAN_FLOOD_SENSOR_TIMEOUT_SECONDS,
        ),
        (TAINAN_FLOOD_SENSOR_API_URL, DEFAULT_TAINAN_FLOOD_SENSOR_TIMEOUT_SECONDS),
    ]
    assert result.adapter_key == "local.tainan.flood_sensor"
    assert len(result.fetched) == 2
    assert len(result.normalized) == 1
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
    assert result.fetched[0].payload["evidence_scope"] == "current"
    assert build_staging_batch(result).accepted[0].payload["evidence_scope"] == "current"


def test_tainan_records_missing_coordinates_keep_quality_flag_and_are_not_normalized() -> None:
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
    missing_coordinate_source_id = "f002:2026-06-27T03:26:03+00:00"

    assert missing_coordinate_raw.source_id == missing_coordinate_source_id
    assert "geometry" not in missing_coordinate_raw.payload
    assert missing_coordinate_raw.payload["quality_flags"] == {
        "missing_station_coordinates": True,
        "station_metadata_missing": False,
        "water_inner_doubt": True,
    }
    assert [evidence.source_id for evidence in result.normalized] == [
        "f001:2026-06-27T03:25:03+00:00"
    ]
    assert result.rejected == (missing_coordinate_source_id,)

    staging = build_staging_batch(result, raw_ref="raw/local/tainan/flood_sensor/test.json")
    assert [candidate.source_id for candidate in staging.accepted] == [
        "f001:2026-06-27T03:25:03+00:00"
    ]
    assert missing_coordinate_source_id not in {candidate.source_id for candidate in staging.accepted}
    assert staging.rejected_raw_source_ids == (missing_coordinate_source_id,)


def test_tainan_adapter_registry_and_config_are_default_off() -> None:
    settings = load_worker_settings({})

    assert ADAPTER_REGISTRY[TAINAN_FLOOD_SENSOR_METADATA.key] is TAINAN_FLOOD_SENSOR_METADATA
    assert TAINAN_FLOOD_SENSOR_METADATA.key == "local.tainan.flood_sensor"
    assert TAINAN_FLOOD_SENSOR_METADATA.enabled_by_default is False
    assert settings.source_tainan_flood_sensor_enabled is None
    assert settings.source_tainan_flood_sensor_api_enabled is False
    assert settings.source_tainan_flood_sensor_timeout_seconds == 45
    assert "local.tainan.flood_sensor" not in enabled_adapter_keys(settings)
    assert TAINAN_FLOOD_SENSOR_API_URL == (
        "https://soa.tainan.gov.tw/Api/Service/Get/21b31a27-3e61-48b8-8259-83c2001bec8c"
    )
    assert TAINAN_FLOOD_SENSOR_METADATA_API_URL == (
        "https://soa.tainan.gov.tw/Api/Service/Get/cdc1ead4-d56a-4092-8e1c-e1f2fa9ee864"
    )


def test_configured_tainan_key_cannot_bypass_source_and_api_gates() -> None:
    adapter_key = "local.tainan.flood_sensor"
    api_only_settings = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": adapter_key,
            "SOURCE_TAINAN_FLOOD_SENSOR_API_ENABLED": "true",
        }
    )
    source_only_settings = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": adapter_key,
            "SOURCE_TAINAN_FLOOD_SENSOR_ENABLED": "true",
        }
    )
    live_settings = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": adapter_key,
            "SOURCE_TAINAN_FLOOD_SENSOR_ENABLED": "true",
            "SOURCE_TAINAN_FLOOD_SENSOR_API_ENABLED": "true",
        }
    )

    assert adapter_key not in enabled_adapter_keys(api_only_settings)
    assert adapter_key not in build_runtime_adapters(api_only_settings, fetched_at=FETCHED_AT)
    assert adapter_key not in build_runtime_adapters(source_only_settings, fetched_at=FETCHED_AT)
    assert adapter_key in build_runtime_adapters(live_settings, fetched_at=FETCHED_AT)


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
    assert len(adapters["local.tainan.flood_sensor"].run().normalized) == 1
    assert calls == [
        (
            TAINAN_FLOOD_SENSOR_METADATA_API_URL,
            DEFAULT_TAINAN_FLOOD_SENSOR_TIMEOUT_SECONDS,
        ),
        (TAINAN_FLOOD_SENSOR_API_URL, DEFAULT_TAINAN_FLOOD_SENSOR_TIMEOUT_SECONDS),
    ]
