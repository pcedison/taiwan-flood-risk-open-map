from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest

from app.adapters.contracts import EventType, SourceFamily
from app.adapters.cwa import (
    CwaRainfallAdapter,
    CwaRainfallApiAdapter,
    CwaRainfallFetchError,
    CwaRainfallPayloadError,
    parse_cwa_rainfall_api_payload,
)
from app.adapters.flood_potential import FloodPotentialGeoJsonAdapter
from app.adapters.wra import WraWaterLevelAdapter
from app.adapters.wra import (
    WraWaterLevelApiAdapter,
    WraWaterLevelFetchError,
    WraWaterLevelPayloadError,
    parse_wra_water_level_api_payload,
)
from app.pipelines.validation import validate_evidence_for_promotion


FIXTURES_DIR = Path(__file__).parent / "fixtures"
FETCHED_AT = datetime(2026, 4, 28, 8, 10, tzinfo=timezone.utc)


def test_cwa_rainfall_adapter_normalizes_fixture_records() -> None:
    adapter = CwaRainfallAdapter(
        _load_records("cwa_rainfall_sample.json"),
        fetched_at=FETCHED_AT,
        raw_snapshot_key="raw/cwa/rainfall/2026-04-28T08.json",
    )

    result = adapter.run()

    assert result.adapter_key == "official.cwa.rainfall"
    assert len(result.fetched) == 2
    assert len(result.normalized) == 2
    assert result.rejected == ()

    first = result.normalized[0]
    assert first.source_family is SourceFamily.OFFICIAL
    assert first.event_type is EventType.RAINFALL
    assert first.location_text == "Taipei City Zhongzheng District Taipei Station"
    assert first.confidence == 0.93
    assert "42.5 mm in 1 hour" in first.summary


def test_cwa_rainfall_api_adapter_fetches_and_normalizes_official_payload() -> None:
    captured: dict[str, object] = {}

    def fetch_json(url: str, timeout_seconds: int) -> dict[str, Any]:
        captured["url"] = url
        captured["timeout_seconds"] = timeout_seconds
        return _load_mapping("cwa_rainfall_api_sample.json")

    adapter = CwaRainfallApiAdapter(
        authorization="test-token",
        api_url=(
            "https://example.test/cwa/rainfall?"
            "Authorization=old-token&station=all&format=XML"
        ),
        timeout_seconds=3,
        fetched_at=FETCHED_AT,
        fetch_json=fetch_json,
        raw_snapshot_key="raw/cwa/rainfall/api-sample.json",
    )

    result = adapter.run()

    request_url = str(captured["url"])
    request_params = parse_qs(urlsplit(request_url).query)
    assert captured["timeout_seconds"] == 3
    assert request_params["Authorization"] == ["test-token"]
    assert request_params["format"] == ["JSON"]
    assert request_params["station"] == ["all"]
    assert "old-token" not in request_url

    assert len(result.fetched) == 1
    assert len(result.normalized) == 1
    assert result.rejected == ()

    raw = result.fetched[0]
    assert raw.source_url == "https://example.test/cwa/rainfall?station=all&format=JSON"
    assert "test-token" not in raw.source_url
    assert raw.payload["rainfall_mm_10m"] == 7.5
    assert raw.payload["geometry"] == {
        "type": "Point",
        "coordinates": [121.514, 25.0375],
    }

    evidence = result.normalized[0]
    assert evidence.source_timestamp == datetime(2026, 4, 28, 8, 0, tzinfo=timezone.utc)
    assert evidence.location_text == "Taipei City Zhongzheng District Taipei Station"
    assert "42.5 mm in 1 hour" in evidence.summary
    assert "156.0 mm in 24 hours" in evidence.summary


def test_cwa_rainfall_api_payload_shape_errors_are_explicit() -> None:
    with pytest.raises(CwaRainfallPayloadError, match="records object"):
        parse_cwa_rainfall_api_payload({}, source_url="https://example.test/cwa/rainfall")

    with pytest.raises(CwaRainfallPayloadError, match="Station list"):
        parse_cwa_rainfall_api_payload(
            {"records": {"Station": {}}},
            source_url="https://example.test/cwa/rainfall",
        )


def test_cwa_rainfall_api_adapter_wraps_injected_fetch_errors() -> None:
    def fetch_json(url: str, timeout_seconds: int) -> dict[str, Any]:
        del url, timeout_seconds
        raise TimeoutError("timed out")

    adapter = CwaRainfallApiAdapter(
        authorization="test-token",
        api_url="https://example.test/cwa/rainfall",
        fetched_at=FETCHED_AT,
        fetch_json=fetch_json,
    )

    with pytest.raises(CwaRainfallFetchError, match="timed out"):
        adapter.run()


def test_wra_water_level_adapter_normalizes_fixture_records() -> None:
    adapter = WraWaterLevelAdapter(
        _load_records("wra_water_level_sample.json"),
        fetched_at=FETCHED_AT,
        raw_snapshot_key="raw/wra/water-level/2026-04-28T08.json",
    )

    result = adapter.run()

    assert result.adapter_key == "official.wra.water_level"
    assert len(result.fetched) == 2
    assert len(result.normalized) == 2
    assert result.rejected == ()

    first = result.normalized[0]
    assert first.source_family is SourceFamily.OFFICIAL
    assert first.event_type is EventType.WATER_LEVEL
    assert first.location_text == "Dahan River Dahan Bridge"
    assert "0.68 m below warning level" in first.summary


def test_wra_water_level_api_adapter_fetches_and_normalizes_official_payload() -> None:
    captured: dict[str, object] = {}

    def fetch_json(url: str, timeout_seconds: int) -> dict[str, Any]:
        captured["url"] = url
        captured["timeout_seconds"] = timeout_seconds
        return _load_mapping("wra_water_level_api_sample.json")

    adapter = WraWaterLevelApiAdapter(
        api_url="https://example.test/wra/water-level?format=XML&county=taipei",
        timeout_seconds=5,
        fetched_at=FETCHED_AT,
        fetch_json=fetch_json,
        raw_snapshot_key="raw/wra/water-level/api-sample.json",
    )

    result = adapter.run()

    request_url = str(captured["url"])
    request_params = parse_qs(urlsplit(request_url).query)
    assert captured["timeout_seconds"] == 5
    assert request_params["format"] == ["JSON"]
    assert request_params["county"] == ["taipei"]

    assert len(result.fetched) == 1
    assert len(result.normalized) == 1
    assert result.rejected == ()

    raw = result.fetched[0]
    assert raw.source_url == "https://example.test/wra/water-level?county=taipei&format=JSON"
    assert raw.payload["water_level_m"] == 7.82
    assert raw.payload["geometry"] == {
        "type": "Point",
        "coordinates": [121.482, 25.032],
    }

    evidence = result.normalized[0]
    assert evidence.source_timestamp == datetime(2026, 4, 28, 8, 5, tzinfo=timezone.utc)
    assert evidence.location_text == "Dahan River Dahan Bridge"
    assert "0.68 m below warning level" in evidence.summary


def test_wra_water_level_api_payload_accepts_wra_v2_list_shape() -> None:
    records = parse_wra_water_level_api_payload(
        [
            {
                "stationid": "WRA-2001",
                "datetime": "2026-04-28T16:05:00+08:00",
                "waterlevel": "3.21",
                "rivername": "Keelung River",
                "alertlevel2": "4.00",
            },
            {
                "stationid": "WRA-BAD",
                "datetime": "2026-04-28T16:05:00+08:00",
                "waterlevel": "-99",
            },
        ],
        source_url="https://example.test/wra/water-level?format=JSON",
    )

    assert len(records) == 1
    assert records[0]["station_id"] == "WRA-2001"
    assert records[0]["station_name"] == "WRA-2001"
    assert records[0]["river_name"] == "Keelung River"
    assert records[0]["observed_at"] == "2026-04-28T08:05:00+00:00"
    assert records[0]["water_level_m"] == 3.21
    assert records[0]["warning_level_m"] == 4.0


def test_wra_water_level_api_adapter_omits_optional_token_from_source_url() -> None:
    captured: dict[str, object] = {}

    def fetch_json(url: str, timeout_seconds: int) -> dict[str, Any]:
        captured["url"] = url
        del timeout_seconds
        return _load_mapping("wra_water_level_api_sample.json")

    adapter = WraWaterLevelApiAdapter(
        api_url="https://example.test/wra/water-level?api_key=old-token",
        api_token="test-token",
        fetched_at=FETCHED_AT,
        fetch_json=fetch_json,
    )

    result = adapter.run()

    request_url = str(captured["url"])
    request_params = parse_qs(urlsplit(request_url).query)
    assert request_params["api_key"] == ["test-token"]
    assert "old-token" not in request_url
    assert result.fetched[0].source_url == "https://example.test/wra/water-level?format=JSON"


def test_wra_water_level_api_payload_shape_errors_are_explicit() -> None:
    with pytest.raises(WraWaterLevelPayloadError, match="record list"):
        parse_wra_water_level_api_payload({}, source_url="https://example.test/wra/water-level")


def test_wra_water_level_api_adapter_wraps_injected_fetch_errors() -> None:
    def fetch_json(url: str, timeout_seconds: int) -> dict[str, Any]:
        del url, timeout_seconds
        raise TimeoutError("timed out")

    adapter = WraWaterLevelApiAdapter(
        api_url="https://example.test/wra/water-level",
        fetched_at=FETCHED_AT,
        fetch_json=fetch_json,
    )

    with pytest.raises(WraWaterLevelFetchError, match="timed out"):
        adapter.run()


def test_flood_potential_geojson_adapter_normalizes_feature_collection() -> None:
    adapter = FloodPotentialGeoJsonAdapter(
        _load_feature_collection("flood_potential_sample.geojson"),
        fetched_at=FETCHED_AT,
        raw_snapshot_key="raw/flood-potential/2026-04.geojson",
    )

    result = adapter.run()

    assert result.adapter_key == "official.flood_potential.geojson"
    assert len(result.fetched) == 2
    assert len(result.normalized) == 2
    assert result.rejected == ()

    first = result.normalized[0]
    assert first.source_family is SourceFamily.OFFICIAL
    assert first.event_type is EventType.FLOOD_POTENTIAL
    assert first.source_id == "FP-TPE-ZZ-001"
    assert first.location_text == "Taipei City Zhongzheng District low-lying area"
    assert "0.5-1.0m" in first.summary


def test_official_adapter_outputs_pass_promotion_validation() -> None:
    normalized = (
        *CwaRainfallAdapter(_load_records("cwa_rainfall_sample.json"), fetched_at=FETCHED_AT)
        .run()
        .normalized,
        *WraWaterLevelAdapter(_load_records("wra_water_level_sample.json"), fetched_at=FETCHED_AT)
        .run()
        .normalized,
        *FloodPotentialGeoJsonAdapter(
            _load_feature_collection("flood_potential_sample.geojson"), fetched_at=FETCHED_AT
        )
        .run()
        .normalized,
    )

    validation = validate_evidence_for_promotion(normalized)

    assert len(validation.accepted) == 6
    assert validation.rejected == ()


def _load_records(name: str) -> list[dict[str, Any]]:
    return cast(
        list[dict[str, Any]],
        json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8")),
    )


def _load_feature_collection(name: str) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8")),
    )


def _load_mapping(name: str) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8")),
    )
