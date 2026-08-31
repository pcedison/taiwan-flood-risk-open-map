from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.adapters.registry import enabled_adapter_keys
from app.adapters.wra import (
    WRA_FLOOD_INCIDENT_METADATA,
    WraFloodIncidentApiAdapter,
    WraFloodIncidentConfigurationError,
    parse_wra_flood_incident_payload,
)
from app.config import load_worker_settings
from app.jobs.runtime import build_runtime_adapters
from app.pipelines.staging import build_staging_batch


FETCHED_AT = datetime(2026, 8, 31, 4, 0, tzinfo=UTC)


def _payload() -> dict[str, object]:
    return {
        "UpdataTime": "2026-08-31T12:00:00",
        "Data": [
            {
                "CityCode": "66000",
                "DisasterFlooding": [
                    {
                        "DisasterFloodingID": "11111111-1111-1111-1111-111111111111",
                        "Time": "2026-08-24T12:30",
                        "CategoryCode": "24: 臺中市政府",
                        "SourceCode": "4: EMIC",
                        "OperatorName": "太平區",
                        "TownCode": "66000270",
                        "Location": "臺中市太平區樹孝路",
                        "Point": {"Latitude": 24.154, "Longitude": 120.716},
                        "Depth": 25,
                        "IsReceded": "true",
                        "RecededDate": "2026-08-24T16:00",
                        "Type": "1: 道路",
                    }
                ],
            },
            {
                "CityCode": "10013",
                "DisasterFlooding": [
                    {
                        "DisasterFloodingID": "22222222-2222-2222-2222-222222222222",
                        "Time": "2025-07-09T09:00",
                        "CategoryCode": "3: 傳播媒體",
                        "SourceCode": "5: 新聞媒體",
                        "OperatorName": "林邊鄉",
                        "TownCode": "10013030",
                        "Location": "屏東縣林邊鄉",
                        "Point": None,
                        "Depth": None,
                        "IsReceded": "false",
                        "Type": "15: 地區積淹水",
                    }
                ],
            },
        ],
    }


def test_parser_preserves_multiple_counties_years_and_location_precision() -> None:
    records = parse_wra_flood_incident_payload(_payload())

    assert len(records) == 2
    assert {record["city_code"] for record in records} == {"66000", "10013"}
    assert records[0]["occurred_at"] == "2026-08-24T04:30:00+00:00"
    assert records[0]["location_precision"] == "point"
    assert records[0]["evidence_scope"] == "historical"
    assert records[0]["reported_depth_unit"] == "upstream_schema_unspecified"
    assert records[1]["occurred_at"] == "2025-07-09T01:00:00+00:00"
    assert records[1]["location_precision"] == "admin_area"
    assert records[0]["is_receded"] is True
    assert records[1]["is_receded"] is False


def test_adapter_uses_secret_header_and_normalizes_historical_flood_reports() -> None:
    calls: list[tuple[str, dict[str, str], int]] = []

    def fetch_json(url: str, headers: dict[str, str], timeout: int) -> object:
        calls.append((url, headers, timeout))
        return _payload()

    adapter = WraFloodIncidentApiAdapter(
        api_key="test-secret",
        fetched_at=FETCHED_AT,
        fetch_json=fetch_json,
    )
    result = adapter.run()

    assert result.adapter_key == "official.wra.flood_incident"
    assert len(result.fetched) == 2
    assert len(result.normalized) == 2
    assert result.normalized[0].event_type.value == "flood_report"
    assert result.normalized[0].source_timestamp == datetime(2026, 8, 24, 4, 30, tzinfo=UTC)
    assert result.normalized[0].confidence == 0.94
    assert result.normalized[1].confidence == 0.72
    assert calls[0][0].endswith("/v2/Disaster/Flooding?$top=100")
    assert calls[0][1]["apikey"] == "test-secret"
    assert "AppKey" not in calls[0][1]
    assert "test-secret" not in result.fetched[0].source_url
    assert "test-secret" not in str(result.fetched[0].payload)
    assert "API 未標示單位" in result.normalized[0].summary
    assert "未退水" in result.normalized[1].summary
    assert result.no_active_event is False


def test_adapter_fails_closed_without_key_or_reviewed_host() -> None:
    with pytest.raises(WraFloodIncidentConfigurationError, match=r"\[REDACTED\]"):
        WraFloodIncidentApiAdapter(api_key=None)
    with pytest.raises(WraFloodIncidentConfigurationError, match="reviewed"):
        WraFloodIncidentApiAdapter(
            api_key="secret",
            api_url="https://example.test/flooding",
        )
    with pytest.raises(WraFloodIncidentConfigurationError, match="reviewed"):
        WraFloodIncidentApiAdapter(
            api_key="secret",
            api_url="https://fhy.wra.gov.tw/OpenApiv3/v2/Disaster/Flooding?$top=15",
        )


def test_runtime_requires_all_three_gates_and_key() -> None:
    base = {
        "SOURCE_WRA_FLOOD_INCIDENT_ENABLED": "true",
        "SOURCE_WRA_FLOOD_INCIDENT_API_ENABLED": "true",
        "SOURCE_WRA_FLOOD_INCIDENT_CONTRACT_ENABLED": "true",
        "WRA_FLOOD_INCIDENT_API_KEY": "test-secret",
        "WORKER_ENABLED_ADAPTER_KEYS": "official.wra.flood_incident",
    }
    settings = load_worker_settings(base)

    assert enabled_adapter_keys(settings) == ("official.wra.flood_incident",)
    adapters = build_runtime_adapters(
        settings,
        fetched_at=FETCHED_AT,
        wra_flood_incident_fetch_json=lambda _url, _headers, _timeout: _payload(),
    )
    assert tuple(adapters) == ("official.wra.flood_incident",)
    assert len(adapters["official.wra.flood_incident"].run().normalized) == 2

    for missing in (
        "SOURCE_WRA_FLOOD_INCIDENT_API_ENABLED",
        "SOURCE_WRA_FLOOD_INCIDENT_CONTRACT_ENABLED",
        "WRA_FLOOD_INCIDENT_API_KEY",
    ):
        env = {**base, missing: ""}
        assert enabled_adapter_keys(load_worker_settings(env)) == ()


def test_registry_metadata_documents_latest_event_and_incomplete_backfill() -> None:
    assert WRA_FLOOD_INCIDENT_METADATA.enabled_by_default is False
    assert any("latest disaster event" in item for item in WRA_FLOOD_INCIDENT_METADATA.limitations)


def test_wra_incidents_pass_reviewed_historical_staging_contract() -> None:
    result = WraFloodIncidentApiAdapter(
        api_key="test-secret",
        fetched_at=FETCHED_AT,
        fetch_json=lambda _url, _headers, _timeout: _payload(),
    ).run()

    batch = build_staging_batch(result)

    assert len(batch.accepted) == 2
    assert batch.rejected == ()
    assert batch.accepted[0].payload["evidence_scope"] == "historical"
    assert batch.accepted[0].payload["location_precision"] == "point"
    assert batch.accepted[0].payload["location_payload"]["geometry"] == {
        "type": "Point",
        "coordinates": [120.716, 24.154],
    }
    assert batch.accepted[1].payload["location_precision"] == "admin_area"
    assert "location_payload" not in batch.accepted[1].payload
