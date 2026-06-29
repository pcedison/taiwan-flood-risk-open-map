from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.domain.evidence.repository import NearbyCoverageRow
from app.domain.realtime.nearby_coverage import (
    RADIUS_BUCKETS_M,
    REQUIRED_SIGNAL_TYPES,
    build_nearby_realtime_coverage,
    coverage_signal_type,
)


NOW = datetime(2026, 6, 29, 12, 0, tzinfo=UTC)


def _row(
    *,
    adapter_key: str,
    source_id: str,
    event_type: str,
    distance_to_query_m: float,
    freshness_state: str = "fresh",
    observed_delta_minutes: int = 5,
) -> NearbyCoverageRow:
    return NearbyCoverageRow(
        adapter_key=adapter_key,
        source_id=source_id,
        event_type=event_type,
        station_id=source_id.rsplit(":", 1)[-1],
        observed_at=NOW - timedelta(minutes=observed_delta_minutes),
        ingested_at=NOW,
        distance_to_query_m=distance_to_query_m,
        freshness_state=freshness_state,
    )


def test_nearby_coverage_distinguishes_nearby_from_county_available() -> None:
    coverage = build_nearby_realtime_coverage(
        rows=(
            _row(
                adapter_key="official.cwa.rainfall",
                source_id="cwa-rainfall:near",
                event_type="rainfall",
                distance_to_query_m=900.0,
            ),
            _row(
                adapter_key="official.cwa.rainfall",
                source_id="cwa-rainfall:far",
                event_type="rainfall",
                distance_to_query_m=6100.0,
            ),
        ),
        query_radius_m=500,
        evaluated_at=NOW,
    )

    rainfall = next(item for item in coverage.signal_breakdown if item.signal_type == "rainfall")
    assert coverage.overall_level == "low"
    assert rainfall.coverage_level == "high"
    assert rainfall.counts_by_radius_m == {"500": 0, "1000": 1, "3000": 1, "5000": 1}
    assert rainfall.nearest_distance_m == 900.0
    assert coverage.county_level_note


def test_nearby_coverage_counts_500_1000_3000_5000_buckets() -> None:
    coverage = build_nearby_realtime_coverage(
        rows=(
            _row(
                adapter_key="official.cwa.rainfall",
                source_id="cwa-rainfall:1",
                event_type="rainfall",
                distance_to_query_m=120.0,
            ),
            _row(
                adapter_key="official.cwa.rainfall",
                source_id="cwa-rainfall:2",
                event_type="rainfall",
                distance_to_query_m=800.0,
            ),
            _row(
                adapter_key="official.cwa.rainfall",
                source_id="cwa-rainfall:3",
                event_type="rainfall",
                distance_to_query_m=2200.0,
            ),
            _row(
                adapter_key="official.cwa.rainfall",
                source_id="cwa-rainfall:4",
                event_type="rainfall",
                distance_to_query_m=4200.0,
            ),
        ),
        query_radius_m=500,
        evaluated_at=NOW,
    )

    rainfall = next(item for item in coverage.signal_breakdown if item.signal_type == "rainfall")
    assert RADIUS_BUCKETS_M == (500, 1000, 3000, 5000)
    assert rainfall.counts_by_radius_m == {"500": 1, "1000": 2, "3000": 3, "5000": 4}
    assert rainfall.fresh_count == 4
    assert rainfall.stale_count == 0
    assert coverage.overall_level == "low"


def test_nearby_coverage_reports_missing_flood_depth_and_sewer() -> None:
    coverage = build_nearby_realtime_coverage(
        rows=(
            _row(
                adapter_key="official.cwa.rainfall",
                source_id="cwa-rainfall:1",
                event_type="rainfall",
                distance_to_query_m=120.0,
            ),
            _row(
                adapter_key="official.wra.water_level",
                source_id="wra-water-level:1",
                event_type="water_level",
                distance_to_query_m=450.0,
            ),
        ),
        query_radius_m=500,
        evaluated_at=NOW,
    )

    assert coverage.overall_level == "high"
    assert "flood_depth" in coverage.missing_signal_types
    assert "sewer_water_level" in coverage.missing_signal_types
    assert "water_level" not in coverage.missing_signal_types


def test_nearby_coverage_status_only_does_not_count_as_flood_depth() -> None:
    coverage = build_nearby_realtime_coverage(
        rows=(
            _row(
                adapter_key="local.taipei.pump_station",
                source_id="taipei-pump:1",
                event_type="status_only",
                distance_to_query_m=150.0,
            ),
        ),
        query_radius_m=500,
        evaluated_at=NOW,
    )

    status_only = next(item for item in coverage.signal_breakdown if item.signal_type == "status_only")
    assert coverage_signal_type("status_only", "local.taipei.pump_station") == "status_only"
    assert status_only.status_only_count == 1
    assert status_only.fresh_count == 1
    assert coverage.overall_level == "no_local_sensor"
    assert "flood_depth" in coverage.missing_signal_types
    assert "rainfall" in coverage.missing_signal_types
    assert "water_level" in coverage.missing_signal_types
    assert "pump_or_gate_status" not in coverage.missing_signal_types
    assert "flood_warning" not in coverage.missing_signal_types
    assert "status_only" not in coverage.missing_signal_types


def test_nearby_coverage_stale_only_rainfall_and_warning_do_not_satisfy_fallback() -> None:
    coverage = build_nearby_realtime_coverage(
        rows=(
            _row(
                adapter_key="official.cwa.rainfall",
                source_id="cwa-rainfall:stale",
                event_type="rainfall",
                distance_to_query_m=120.0,
                freshness_state="stale",
                observed_delta_minutes=90,
            ),
            _row(
                adapter_key="official.ncdr.cap",
                source_id="ncdr-cap:stale",
                event_type="flood_warning",
                distance_to_query_m=150.0,
                freshness_state="stale",
                observed_delta_minutes=90,
            ),
        ),
        query_radius_m=500,
        evaluated_at=NOW,
    )

    rainfall = next(item for item in coverage.signal_breakdown if item.signal_type == "rainfall")
    warning = next(item for item in coverage.signal_breakdown if item.signal_type == "flood_warning")
    assert coverage.overall_level == "no_local_sensor"
    assert rainfall.coverage_level == "no_local_sensor"
    assert rainfall.fresh_count == 0
    assert rainfall.stale_count == 1
    assert warning.coverage_level == "no_local_sensor"
    assert warning.fresh_count == 0
    assert warning.stale_count == 1
    assert set(coverage.missing_signal_types) == set(REQUIRED_SIGNAL_TYPES)


def test_nearby_coverage_warning_only_does_not_satisfy_rainfall_fallback() -> None:
    coverage = build_nearby_realtime_coverage(
        rows=(
            _row(
                adapter_key="official.ncdr.cap",
                source_id="ncdr-cap:fresh",
                event_type="flood_warning",
                distance_to_query_m=150.0,
            ),
        ),
        query_radius_m=500,
        evaluated_at=NOW,
    )
    no_rows_coverage = build_nearby_realtime_coverage(
        rows=(),
        query_radius_m=500,
        evaluated_at=NOW,
    )

    warning = next(item for item in coverage.signal_breakdown if item.signal_type == "flood_warning")
    assert coverage.overall_level == "no_local_sensor"
    assert coverage.summary == no_rows_coverage.summary
    assert warning.fresh_count == 1
    assert set(coverage.missing_signal_types) == set(REQUIRED_SIGNAL_TYPES)


def test_nearby_coverage_missing_signals_ignore_context_and_status_rows() -> None:
    coverage = build_nearby_realtime_coverage(
        rows=(
            _row(
                adapter_key="official.civil_iot.pump_water_level",
                source_id="civil-iot-pump:1",
                event_type="pump_water_level",
                distance_to_query_m=150.0,
            ),
            _row(
                adapter_key="official.ncdr.cap",
                source_id="ncdr-cap:1",
                event_type="flood_warning",
                distance_to_query_m=180.0,
            ),
            _row(
                adapter_key="local.taipei.pump_station",
                source_id="taipei-pump:1",
                event_type="status_only",
                distance_to_query_m=220.0,
            ),
        ),
        query_radius_m=500,
        evaluated_at=NOW,
    )

    assert coverage.overall_level == "no_local_sensor"
    assert set(coverage.missing_signal_types) == set(REQUIRED_SIGNAL_TYPES)


def test_nearby_coverage_unavailable_when_repository_unavailable() -> None:
    coverage = build_nearby_realtime_coverage(
        rows=(),
        query_radius_m=500,
        evaluated_at=NOW,
        repository_unavailable=True,
    )

    assert coverage.overall_level == "unavailable"
    assert coverage.signal_breakdown == []
    assert coverage.limitations
    assert "無法" in coverage.summary or "unavailable" in coverage.summary
    assert coverage.county_level_note
    assert set(coverage.missing_signal_types) == set(REQUIRED_SIGNAL_TYPES)
