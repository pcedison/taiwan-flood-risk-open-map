from __future__ import annotations

from datetime import UTC, datetime

from app.adapters.cwa import CwaRainfallAdapter, parse_cwa_rainfall_api_payload
from app.pipelines.staging import build_staging_batch


FETCHED_AT = datetime(2026, 6, 15, 3, 10, tzinfo=UTC)
SOURCE_URL = "https://example.test/cwa/rainfall"


def _station(station_id: str, *, p1h=None, p24h=None, p10m=None) -> dict:
    element: dict = {}
    if p1h is not None:
        element["Past1hr"] = {"Precipitation": p1h}
    if p24h is not None:
        element["Past24hr"] = {"Precipitation": p24h}
    if p10m is not None:
        element["Past10Min"] = {"Precipitation": p10m}
    return {
        "StationId": station_id,
        "StationName": f"站{station_id}",
        "GeoInfo": {"CountyName": "臺南市", "TownName": "中西區"},
        "ObsTime": {"DateTime": "2026-06-15T03:00:00+08:00"},
        "RainfallElement": element,
    }


def _payload(stations: list[dict]) -> dict:
    return {"records": {"Station": stations}}


def test_station_kept_when_only_24h_valid_and_1h_is_sentinel() -> None:
    records = parse_cwa_rainfall_api_payload(
        _payload([_station("A", p1h=-99.0, p24h=12.0)]),
        source_url=SOURCE_URL,
    )

    assert len(records) == 1
    record = records[0]
    assert "rainfall_mm_1h" not in record  # sentinel 1h not stored
    assert record["rainfall_mm_24h"] == 12.0


def test_dry_station_is_kept_with_zero_1h() -> None:
    records = parse_cwa_rainfall_api_payload(
        _payload([_station("C", p1h=0.0)]),
        source_url=SOURCE_URL,
    )

    assert len(records) == 1
    assert records[0]["rainfall_mm_1h"] == 0.0


def test_station_dropped_only_when_all_windows_are_sentinel() -> None:
    records = parse_cwa_rainfall_api_payload(
        _payload([_station("B", p1h=-99.0, p24h=-99.0, p10m=-99.0)]),
        source_url=SOURCE_URL,
    )

    assert records == ()


def test_normalize_keeps_station_without_1h_reading() -> None:
    records = parse_cwa_rainfall_api_payload(
        _payload([_station("A", p1h=-99.0, p24h=12.0)]),
        source_url=SOURCE_URL,
    )
    result = CwaRainfallAdapter(records, fetched_at=FETCHED_AT).run()

    assert len(result.normalized) == 1
    assert "24 hours" in result.normalized[0].summary


def test_staging_payload_carries_rainfall_metric() -> None:
    records = parse_cwa_rainfall_api_payload(
        _payload([_station("C", p1h=8.0, p24h=20.0)]),
        source_url=SOURCE_URL,
    )
    result = CwaRainfallAdapter(records, fetched_at=FETCHED_AT).run()

    batch = build_staging_batch(result)
    projection = batch.accepted[0]
    assert projection.payload["rainfall_mm_1h"] == 8.0
    assert projection.payload["rainfall_mm_24h"] == 20.0
