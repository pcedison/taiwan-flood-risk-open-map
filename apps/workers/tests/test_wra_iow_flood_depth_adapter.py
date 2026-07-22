from __future__ import annotations

import ssl
from datetime import UTC, datetime
from typing import Any, cast

from app.adapters.contracts import EventType, SourceFamily
from app.adapters.wra_iow import (
    WRA_IOW_FLOOD_DEPTH_API_URL,
    WRA_IOW_FLOOD_SENSOR_METADATA_API_URL,
    WraIowFloodDepthApiAdapter,
)
from app.adapters.wra_iow import flood_depth as wra_iow_flood_depth_module
from app.config import load_worker_settings
from app.jobs.runtime import build_runtime_adapters


FETCHED_AT = datetime(2026, 6, 27, 12, 0, tzinfo=UTC)


def _latest_payload() -> dict:
    return {
        "records": [
            {
                "sensorid": "YL-FD-001",
                "latestvalue": "12.5",
                "timestamp": "2026-06-27T19:55:00+08:00",
                "countycode": "10009",
                "areacode": "10009010",
            },
            {
                "sensorid": "YL-FD-002",
                "latestvalue": "0",
                "timestamp": "2026-06-27T19:56:00+08:00",
                "countycode": "10009",
                "areacode": "10009020",
            },
        ]
    }


def _metadata_payload() -> dict:
    return {
        "records": [
            {
                "sensorid": "YL-FD-001",
                "orgname": "雲林縣政府",
                "countyname": "雲林縣",
                "townname": "斗六市",
                "stationname": "斗六市測站",
                "longitude": "120.5401",
                "latitude": "23.7072",
                "isenable": "Y",
            },
            {
                "sensorid": "YL-FD-002",
                "orgname": "雲林縣政府",
                "countyname": "雲林縣",
                "townname": "虎尾鎮",
                "longitude": "120.4310",
                "latitude": "23.7090",
                "isenable": "Y",
            },
        ]
    }


def test_wra_iow_flood_depth_join_outputs_flood_report() -> None:
    calls: list[tuple[str, int]] = []

    def fetch_json(url: str, timeout_seconds: int) -> dict:
        calls.append((url, timeout_seconds))
        return _metadata_payload() if "basic" in url else _latest_payload()

    adapter = WraIowFloodDepthApiAdapter(
        api_url="https://example.test/latest",
        metadata_api_url="https://example.test/basic",
        fetched_at=FETCHED_AT,
        timeout_seconds=5,
        fetch_json=fetch_json,
    )

    result = adapter.run()

    assert calls == [
        ("https://example.test/basic", 5),
        ("https://example.test/latest", 5),
    ]
    assert result.adapter_key == "official.wra_iow.flood_depth"
    assert len(result.fetched) == 2
    assert len(result.normalized) == 2

    first_raw = result.fetched[0].payload
    assert first_raw["station_id"] == "YL-FD-001"
    assert first_raw["station_name"] == "斗六市測站"
    assert first_raw["observed_at"] == "2026-06-27T11:55:00+00:00"
    assert first_raw["flood_depth_cm"] == 12.5
    assert first_raw["county"] == "雲林縣"
    assert first_raw["town"] == "斗六市"
    assert first_raw["authority"] == "雲林縣政府"
    assert first_raw["geometry"] == {
        "type": "Point",
        "coordinates": [120.5401, 23.7072],
    }
    assert first_raw["quality_flags"] == {
        "station_metadata_missing": False,
        "missing_station_coordinates": False,
        "sensor_disabled": False,
    }

    evidence = result.normalized[0]
    assert evidence.event_type is EventType.FLOOD_REPORT
    assert evidence.source_family is SourceFamily.OFFICIAL
    assert evidence.source_id == "YL-FD-001:2026-06-27T11:55:00+00:00"
    assert "水深 12.5 公分" in evidence.summary
    assert "wra_iow" in evidence.tags
    assert "flood_sensor" in evidence.tags


def test_wra_iow_flood_depth_rejects_missing_coordinates_and_disabled_sensors() -> None:
    latest_payload = {
        "records": [
            {
                "sensorid": "NO-COORD",
                "latestvalue": "8",
                "timestamp": "2026-06-27T20:00:00+08:00",
            },
            {
                "sensorid": "DISABLED",
                "latestvalue": "9",
                "timestamp": "2026-06-27T20:01:00+08:00",
            },
        ]
    }
    metadata_payload = {
        "records": [
            {
                "sensorid": "NO-COORD",
                "stationname": "缺座標測站",
                "countyname": "彰化縣",
                "townname": "二林鎮",
                "isenable": "Y",
            },
            {
                "sensorid": "DISABLED",
                "stationname": "停用測站",
                "countyname": "彰化縣",
                "townname": "芳苑鄉",
                "longitude": "120.3200",
                "latitude": "23.9200",
                "isenable": "N",
            },
        ]
    }

    adapter = WraIowFloodDepthApiAdapter(
        api_url="https://example.test/latest",
        metadata_api_url="https://example.test/basic",
        fetched_at=FETCHED_AT,
        fetch_json=lambda url, timeout: metadata_payload if "basic" in url else latest_payload,
    )

    result = adapter.run()

    assert len(result.fetched) == 2
    assert len(result.normalized) == 0
    assert result.rejected == (
        "NO-COORD:2026-06-27T12:00:00+00:00",
        "DISABLED:2026-06-27T12:01:00+00:00",
    )


def test_build_runtime_adapters_wires_wra_iow_when_both_gates_are_on() -> None:
    settings = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": "official.wra_iow.flood_depth",
            "SOURCE_WRA_IOW_FLOOD_DEPTH_ENABLED": "true",
            "SOURCE_WRA_IOW_FLOOD_DEPTH_API_ENABLED": "true",
            "WRA_IOW_FLOOD_DEPTH_API_URL": "https://example.test/latest",
            "WRA_IOW_FLOOD_SENSOR_METADATA_API_URL": "https://example.test/basic",
            "WRA_IOW_FLOOD_DEPTH_TIMEOUT_SECONDS": "5",
        }
    )
    calls: list[tuple[str, int]] = []

    def fetch_json(url: str, timeout_seconds: int) -> dict:
        calls.append((url, timeout_seconds))
        return _metadata_payload() if "basic" in url else _latest_payload()

    adapters = build_runtime_adapters(
        settings,
        fetched_at=FETCHED_AT,
        wra_iow_flood_depth_fetch_json=fetch_json,
    )

    assert tuple(adapters) == ("official.wra_iow.flood_depth",)
    assert len(adapters["official.wra_iow.flood_depth"].run().normalized) == 2
    assert calls == [
        ("https://example.test/basic", 5),
        ("https://example.test/latest", 5),
    ]
    assert WRA_IOW_FLOOD_DEPTH_API_URL.startswith("https://opendata.wra.gov.tw/api/v2/")
    assert WRA_IOW_FLOOD_SENSOR_METADATA_API_URL.startswith(
        "https://opendata.wra.gov.tw/api/v2/"
    )


def test_wra_iow_fetch_uses_taiwan_gov_tls_context(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"records":[]}'

    def fake_urlopen(request, *, timeout: int, context: ssl.SSLContext):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["context"] = context
        return FakeResponse()

    monkeypatch.setattr(wra_iow_flood_depth_module, "urlopen", fake_urlopen)

    assert wra_iow_flood_depth_module.fetch_wra_iow_json(
        "https://opendata.wra.gov.tw/api/v2/example?format=JSON",
        5,
    ) == {"records": []}

    context = cast(ssl.SSLContext, captured["context"])
    strict = getattr(ssl, "VERIFY_X509_STRICT", 0)
    assert captured["timeout"] == 5
    assert context.verify_mode is ssl.CERT_REQUIRED
    assert context.check_hostname is True
    if strict:
        assert not context.verify_flags & strict
