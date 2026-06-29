from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from app.adapters.contracts import EventType, SourceFamily
from app.adapters.local_kinmen import (
    KINMEN_KWIS_DATA_URL,
    KINMEN_KWIS_PUMP_STATION_API_URL,
    KinmenKwisAuthorizationError,
    KinmenKwisPumpStationApiAdapter,
    parse_kinmen_kwis_pump_payload,
)
from app.config import load_worker_settings
from app.jobs.runtime import build_runtime_adapters
from app.adapters.local_kinmen.kwis import _redact_token_url


FETCHED_AT = datetime(2026, 6, 30, 3, 0, tzinfo=UTC)


def test_kinmen_kwis_pump_string_payload_outputs_status_only_record() -> None:
    records = parse_kinmen_kwis_pump_payload(
        _kwis_string_payload(
            [
                {
                    "PumpID": "KM-PUMP-001",
                    "PumpName": "Kinmen Pump Station 1",
                    "PumpStatus": "running",
                    "UpdateTime": "2026-06-30 10:20:00",
                    "Longitude": "118.4215",
                    "Latitude": "24.4378",
                }
            ]
        ),
        source_url=KINMEN_KWIS_DATA_URL,
        resource_url=KINMEN_KWIS_PUMP_STATION_API_URL,
        fetched_at=FETCHED_AT,
    )

    assert records == (
        {
            "station_id": "KM-PUMP-001",
            "station_name": "Kinmen Pump Station 1",
            "observed_at": "2026-06-30T02:20:00+00:00",
            "pump_status": "running",
            "source_url": KINMEN_KWIS_DATA_URL,
            "resource_url": KINMEN_KWIS_PUMP_STATION_API_URL,
            "location_text": "Kinmen County Kinmen Pump Station 1",
            "authority": "Kinmen County Government / KWIS",
            "longitude": 118.4215,
            "latitude": 24.4378,
            "geometry": {"type": "Point", "coordinates": [118.4215, 24.4378]},
            "attribution": "Kinmen County Government KWIS",
            "confidence": 0.78,
            "quality_flags": {"future_observation": False, "stale_observation": False},
        },
    )


def test_kinmen_kwis_pump_adapter_normalizes_status_only_evidence() -> None:
    adapter = KinmenKwisPumpStationApiAdapter(
        api_token="test-token",
        fetched_at=FETCHED_AT,
        fetch_text=lambda url, timeout: _kwis_string_payload(
            [
                {
                    "station_id": "KM-PUMP-001",
                    "station_name": "Kinmen Pump Station 1",
                    "pump_status": "running",
                    "observed_at": "2026-06-30T10:20:00+08:00",
                    "longitude": 118.4215,
                    "latitude": 24.4378,
                }
            ]
        ),
    )

    result = adapter.run()

    assert result.adapter_key == "local.kinmen.kwis_pump_station"
    assert len(result.fetched) == 1
    assert len(result.normalized) == 1
    evidence = result.normalized[0]
    assert evidence.event_type is EventType.STATUS_ONLY
    assert evidence.source_family is SourceFamily.OFFICIAL
    assert evidence.source_timestamp == datetime(2026, 6, 30, 2, 20, tzinfo=UTC)
    assert "running" in evidence.summary
    assert "local_kinmen" in evidence.tags
    assert "pump_or_gate_status" in evidence.tags


def test_kinmen_kwis_invalid_token_payload_is_authorization_error() -> None:
    with pytest.raises(KinmenKwisAuthorizationError):
        parse_kinmen_kwis_pump_payload(
            _kwis_result({"ErrMsg": "(7) invalid Token value.", "Data": []}),
            source_url=KINMEN_KWIS_DATA_URL,
            fetched_at=FETCHED_AT,
        )


def test_kinmen_kwis_fetch_error_url_redacts_token() -> None:
    redacted = _redact_token_url(
        f"{KINMEN_KWIS_PUMP_STATION_API_URL}?Token=private-token&Other=1"
    )

    assert "private-token" not in redacted
    assert "Token=%2A%2A%2A" in redacted
    assert "Other=1" in redacted


def test_build_runtime_adapters_does_not_wire_kinmen_kwis_without_token() -> None:
    settings = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": "local.kinmen.kwis_pump_station",
            "SOURCE_KINMEN_KWIS_PUMP_STATION_ENABLED": "true",
            "SOURCE_KINMEN_KWIS_PUMP_STATION_API_ENABLED": "true",
        }
    )

    assert build_runtime_adapters(settings) == {}


def test_build_runtime_adapters_wires_kinmen_kwis_when_token_gate_is_satisfied() -> None:
    captured: dict[str, Any] = {}

    def fetch_text(url: str, timeout_seconds: int) -> str:
        captured["url"] = url
        captured["timeout_seconds"] = timeout_seconds
        return _kwis_string_payload(
            [
                {
                    "station_id": "KM-PUMP-001",
                    "station_name": "Kinmen Pump Station 1",
                    "pump_status": "running",
                    "observed_at": "2026-06-30T10:20:00+08:00",
                    "longitude": 118.4215,
                    "latitude": 24.4378,
                }
            ]
        )

    settings = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": "local.kinmen.kwis_pump_station",
            "SOURCE_KINMEN_KWIS_PUMP_STATION_ENABLED": "true",
            "SOURCE_KINMEN_KWIS_PUMP_STATION_API_ENABLED": "true",
            "KINMEN_KWIS_API_TOKEN": "test-token",
            "LOCAL_WATER_TIMEOUT_SECONDS": "5",
        }
    )

    adapters = build_runtime_adapters(
        settings,
        fetched_at=FETCHED_AT,
        kinmen_kwis_pump_station_fetch_text=fetch_text,
    )

    assert tuple(adapters) == ("local.kinmen.kwis_pump_station",)
    assert len(adapters["local.kinmen.kwis_pump_station"].run().normalized) == 1
    assert captured["timeout_seconds"] == 5
    assert captured["url"].startswith(KINMEN_KWIS_PUMP_STATION_API_URL)
    assert "Token=test-token" in captured["url"]


def _kwis_string_payload(data: list[dict[str, Any]]) -> str:
    return _kwis_result({"ErrMsg": "", "Data": data})


def _kwis_result(result: dict[str, Any]) -> str:
    text = json.dumps(result, ensure_ascii=False, indent=2)
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<string xmlns="http://www.hztc.com.tw">'
        f"{text}"
        "</string>"
    )
