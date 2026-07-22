from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from app.adapters.contracts import EventType, SourceFamily
from app.adapters.cwa import (
    CWA_TIDE_LEVEL_DATASET_URL,
    CWA_TIDE_LEVEL_METADATA,
    CwaTideLevelApiAdapter,
    CwaTideLevelPayloadError,
    parse_cwa_tide_level_api_payload,
    parse_cwa_tide_station_metadata_payload,
)


FETCHED_AT = datetime(2026, 6, 30, 4, 10, tzinfo=timezone.utc)


def test_cwa_tide_level_api_adapter_joins_matsu_station_metadata() -> None:
    captured: dict[str, list[str]] = {"urls": []}

    def fetch_json(url: str, timeout_seconds: int) -> dict[str, Any]:
        captured["urls"].append(url)
        assert timeout_seconds == 5
        if "O-B0076" in url or "stations" in url:
            return _station_metadata_payload()
        return _tide_payload()

    adapter = CwaTideLevelApiAdapter(
        authorization="test-token",
        api_url=(
            "https://example.test/cwa/tide?"
            "Authorization=old-token&station=all&format=XML"
        ),
        station_api_url=(
            "https://example.test/cwa/stations?"
            "Authorization=old-token&downloadType=API&format=XML"
        ),
        timeout_seconds=5,
        fetched_at=FETCHED_AT,
        fetch_json=fetch_json,
        raw_snapshot_key="raw/cwa/tide-level/api-sample.json",
    )

    result = adapter.run()

    tide_request = captured["urls"][0]
    tide_request_params = parse_qs(urlsplit(tide_request).query)
    assert tide_request_params["Authorization"] == ["test-token"]
    assert tide_request_params["format"] == ["JSON"]
    assert tide_request_params["station"] == ["all"]
    assert "old-token" not in tide_request

    station_request = captured["urls"][1]
    station_request_params = parse_qs(urlsplit(station_request).query)
    assert station_request_params["Authorization"] == ["test-token"]
    assert station_request_params["format"] == ["JSON"]
    assert station_request_params["downloadType"] == ["WEB"]
    assert "old-token" not in station_request

    assert result.adapter_key == "official.cwa.tide_level"
    assert len(result.fetched) == 1
    assert len(result.normalized) == 1
    assert result.rejected == ()

    raw = result.fetched[0]
    assert raw.source_url == CWA_TIDE_LEVEL_DATASET_URL
    assert raw.payload["resource_url"] == "https://example.test/cwa/tide?station=all&format=JSON"
    assert raw.payload["station_metadata_url"] == (
        "https://example.test/cwa/stations?downloadType=WEB&format=JSON"
    )
    assert raw.payload["station_id"] == "C4W01"
    assert raw.payload["station_name"] == "Matsu tide station"
    assert raw.payload["county"] == "Lienchiang County"
    assert raw.payload["town"] == "Nangan Township"
    assert raw.payload["water_level_m"] == 2.16
    assert raw.payload["station_type"] == "tide_level"
    assert raw.payload["geometry"] == {
        "type": "Point",
        "coordinates": [119.9428, 26.1617],
    }

    evidence = result.normalized[0]
    assert evidence.source_family is SourceFamily.OFFICIAL
    assert evidence.event_type is EventType.WATER_LEVEL
    assert evidence.source_timestamp == datetime(2026, 6, 29, 15, 0, tzinfo=timezone.utc)
    assert evidence.location_text == "Lienchiang County Nangan Township Matsu tide station"
    assert "CWA tide level" in evidence.source_title
    assert "2.16 m" in evidence.summary
    assert "coastal" in evidence.summary
    assert evidence.confidence == 0.9
    assert "tide_level" in evidence.tags


def test_cwa_tide_level_parser_requires_station_metadata_for_location() -> None:
    station_metadata = parse_cwa_tide_station_metadata_payload(
        _station_metadata_payload(),
        station_metadata_url="https://example.test/cwa/stations?format=JSON",
    )
    records = parse_cwa_tide_level_api_payload(
        _tide_payload(),
        source_url=CWA_TIDE_LEVEL_DATASET_URL,
        resource_url="https://example.test/cwa/tide?format=JSON",
        station_metadata=station_metadata,
        station_metadata_url="https://example.test/cwa/stations?format=JSON",
    )

    assert [record["station_id"] for record in records] == ["C4W01"]


def test_cwa_tide_level_payload_shape_errors_are_explicit() -> None:
    with pytest.raises(CwaTideLevelPayloadError, match="Records"):
        parse_cwa_tide_level_api_payload(
            {},
            source_url=CWA_TIDE_LEVEL_DATASET_URL,
            station_metadata={},
        )

    with pytest.raises(CwaTideLevelPayloadError, match="station metadata"):
        parse_cwa_tide_station_metadata_payload({})


def test_cwa_tide_level_metadata_is_coastal_water_level_source() -> None:
    assert CWA_TIDE_LEVEL_METADATA.key == "official.cwa.tide_level"
    assert CWA_TIDE_LEVEL_METADATA.family is SourceFamily.OFFICIAL
    assert CWA_TIDE_LEVEL_METADATA.data_gov_dataset_id == "O-B0075-001"
    assert "coastal" in " ".join(CWA_TIDE_LEVEL_METADATA.limitations)


def _tide_payload() -> dict[str, Any]:
    return {
        "Success": "true",
        "Records": {
            "SeaSurfaceObs": {
                "Location": [
                    {
                        "Station": {"StationID": "C4W01"},
                        "StationObsTimes": {
                            "StationObsTime": [
                                {
                                    "DateTime": "2026-06-29T23:00:00+08:00",
                                    "WeatherElements": {
                                        "TideHeight": "2.16",
                                        "TideLevel": "rising",
                                        "SeaTemperature": "24.0",
                                    },
                                }
                            ]
                        },
                    },
                    {
                        "Station": {"StationID": "C6W08"},
                        "StationObsTimes": {
                            "StationObsTime": [
                                {
                                    "DateTime": "2026-06-29T23:00:00+08:00",
                                    "WeatherElements": {
                                        "TideHeight": "None",
                                        "TideLevel": "-",
                                    },
                                }
                            ]
                        },
                    },
                ]
            }
        },
    }


def _station_metadata_payload() -> dict[str, Any]:
    return {
        "cwaopendata": {
            "Resources": {
                "Resource": {
                    "Metadata": {
                        "ResourceName": "CWA marine station metadata",
                        "ResourceDescription": (
                            "Offshore tide stations such as Matsu use local mean sea level."
                        ),
                    },
                    "Data": {
                        "SeaSurfaceObs": {
                            "Location": [
                                {
                                    "Station": {
                                        "StationID": "C4W01",
                                        "StationName": "Matsu tide station",
                                        "StationNameEN": "Matsu",
                                        "StationLongitude": "119.9428",
                                        "StationLatitude": "26.1617",
                                        "StationAttribute": "Tidal Station",
                                        "StationAddress": "Fu-ao Harbor",
                                        "County": {
                                            "CountyName": "Lienchiang County",
                                        },
                                        "Town": {
                                            "TownName": "Nangan Township",
                                        },
                                        "Area": {
                                            "AreaName": "Matsu inshore",
                                        },
                                        "StationChargeIns": "Central Weather Administration",
                                    },
                                    "StationObsStatus": {
                                        "StationStatus": "1",
                                        "ObservedProperties": {
                                            "TideHeight": {"ObsStatus": "1"},
                                            "TideLevel": {"ObsStatus": "1"},
                                        },
                                    },
                                },
                                {
                                    "Station": {
                                        "StationID": "C6W08",
                                        "StationName": "Matsu buoy",
                                        "StationLongitude": "120.5136",
                                        "StationLatitude": "26.3553",
                                        "StationAttribute": "Data Buoy Station",
                                        "County": {"CountyName": "Lienchiang County"},
                                        "Town": {"TownName": "Dongyin Township"},
                                    },
                                    "StationObsStatus": {
                                        "StationStatus": "1",
                                        "ObservedProperties": {
                                            "TideHeight": {"ObsStatus": "0"},
                                        },
                                    },
                                },
                            ]
                        }
                    },
                }
            }
        }
    }
