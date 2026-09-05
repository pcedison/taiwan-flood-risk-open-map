from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.evidence.repository import NearbyCoverageRow, RealtimeSourceHealthRow
from app.api.services.assessment import _is_upstream_stale
from app.domain.realtime.nearby_coverage import (
    RADIUS_BUCKETS_M,
    REQUIRED_SIGNAL_TYPES,
    build_nearby_realtime_coverage,
    build_nearby_source_health,
    coverage_signal_type,
)

NOW = datetime(2026, 6, 29, 12, 0, tzinfo=UTC)


def test_source_health_task9_fields_have_backward_compatible_defaults() -> None:
    row = RealtimeSourceHealthRow(
        adapter_key="official.cwa.rainfall",
        name="CWA rainfall",
        is_enabled=True,
        configured_health_status="healthy",
        last_success_at=NOW,
        last_failure_at=None,
        latest_run_status="succeeded",
        latest_run_at=NOW,
        latest_observed_at=NOW,
        latest_ingested_at=NOW,
        station_count=1,
    )

    assert row.latest_run_error_code is None
    assert row.freshness_threshold_seconds is None


def _row(
    *,
    adapter_key: str,
    source_id: str,
    event_type: str,
    distance_to_query_m: float,
    freshness_state: str = "fresh",
    observed_delta_minutes: int = 5,
    rainfall_mm_1h: float | None = None,
    water_level_m: float | None = None,
    warning_level_m: float | None = None,
    flood_depth_cm: float | None = None,
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
        rainfall_mm_1h=rainfall_mm_1h,
        water_level_m=water_level_m,
        warning_level_m=warning_level_m,
        flood_depth_cm=flood_depth_cm,
    )


def test_nearby_coverage_exposes_nearest_public_safe_measurements() -> None:
    coverage = build_nearby_realtime_coverage(
        rows=(
            _row(
                adapter_key="official.cwa.rainfall",
                source_id="cwa-rainfall:near",
                event_type="rainfall",
                distance_to_query_m=320.0,
                rainfall_mm_1h=12.5,
            ),
            _row(
                adapter_key="official.wra.water_level",
                source_id="wra-water-level:near",
                event_type="water_level",
                distance_to_query_m=450.0,
                water_level_m=1.75,
                warning_level_m=2.25,
            ),
            _row(
                adapter_key="official.wra_iow.flood_depth",
                source_id="wra-flood-depth:near",
                event_type="flood_depth",
                distance_to_query_m=520.0,
                flood_depth_cm=8.0,
            ),
        ),
        query_radius_m=500,
        evaluated_at=NOW,
    )

    by_type = {item.signal_type: item for item in coverage.signal_breakdown}
    assert by_type["rainfall"].nearest_observation_value == 12.5
    assert by_type["rainfall"].nearest_observation_unit == "mm_1h"
    assert by_type["water_level"].nearest_observation_value == 1.75
    assert by_type["water_level"].nearest_observation_unit == "m"
    assert by_type["water_level"].nearest_reference_value == 2.25
    assert by_type["water_level"].nearest_reference_unit == "m"
    assert by_type["flood_depth"].nearest_observation_value == 8.0
    assert by_type["flood_depth"].nearest_observation_unit == "cm"


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
    assert rainfall.counts_by_radius_m == {
        "500": 0,
        "1000": 1,
        "3000": 1,
        "5000": 1,
        "10000": 2,
        "15000": 2,
    }
    assert rainfall.nearest_distance_m == 900.0
    assert coverage.county_level_note


def test_v1_absence_proof_requires_exactly_three_reviewed_signal_types() -> None:
    assert REQUIRED_SIGNAL_TYPES == ("rainfall", "water_level", "flood_depth")


def test_catalog_kill_switch_wins_over_prior_healthy_runtime_state() -> None:
    row = RealtimeSourceHealthRow(
        adapter_key="official.wra_iow.flood_depth",
        name="WRA IoW",
        is_enabled=False,
        configured_health_status="healthy",
        last_success_at=NOW,
        last_failure_at=None,
        latest_run_status="succeeded",
        latest_run_at=NOW,
        latest_observed_at=NOW,
        latest_ingested_at=NOW,
        station_count=1,
        runtime_enabled=True,
        runtime_enabled_checked_at=NOW,
        runtime_pipeline_status="succeeded",
        runtime_pipeline_checked_at=NOW,
        runtime_pipeline_run_at=NOW,
        runtime_pipeline_complete=True,
        fresh_station_count=1,
    )
    health = build_nearby_source_health((row,), evaluated_at=NOW)
    assert health[0].health_status == "disabled"
    assert health[0].reason_code == "disabled"


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
    assert RADIUS_BUCKETS_M == (500, 1000, 3000, 5000, 10000, 15000)
    assert rainfall.counts_by_radius_m == {
        "500": 1,
        "1000": 2,
        "3000": 3,
        "5000": 4,
        "10000": 4,
        "15000": 4,
    }
    assert rainfall.fresh_count == 4
    assert rainfall.stale_count == 0
    assert coverage.overall_level == "low"


def test_nearby_coverage_reports_missing_required_flood_depth() -> None:
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
    assert "sewer_water_level" not in coverage.missing_signal_types
    assert "water_level" not in coverage.missing_signal_types


def test_nearby_coverage_uses_degraded_observation_instead_of_claiming_no_sensor() -> None:
    coverage = build_nearby_realtime_coverage(
        rows=(
            _row(
                adapter_key="official.cwa.rainfall",
                source_id="cwa-rainfall:degraded",
                event_type="rainfall",
                distance_to_query_m=2042.0,
                freshness_state="degraded",
                observed_delta_minutes=16,
            ),
        ),
        query_radius_m=500,
        evaluated_at=NOW,
    )

    rainfall = next(item for item in coverage.signal_breakdown if item.signal_type == "rainfall")
    assert coverage.overall_level == "low"
    assert rainfall.coverage_level == "medium"
    assert rainfall.fresh_count == 0
    assert rainfall.degraded_count == 1
    assert rainfall.stale_count == 0
    assert rainfall.nearest_freshness_state == "degraded"
    assert rainfall.availability_state == "degraded_nearby"


def _health_row(
    *,
    adapter_key: str,
    name: str = "公開即時來源",
    is_enabled: bool = True,
    configured_health_status: str = "healthy",
    latest_run_status: str | None = "succeeded",
    latest_run_error_code: str | None = None,
    latest_run_delta_minutes: float | None = 5,
    observed_delta_minutes: int | None = 5,
    station_count: int | None = 10,
    inventory_complete: bool = False,
    is_registered: bool = True,
    runtime_enabled: bool | None = None,
    runtime_enabled_delta_minutes: int | None = None,
    runtime_pipeline_status: str | None = None,
    runtime_pipeline_delta_minutes: int | None = None,
    runtime_pipeline_run_delta_minutes: int | None = None,
    runtime_pipeline_complete: bool = False,
    fresh_station_count: int | None = None,
    delayed_station_count: int | None = None,
    stale_station_count: int | None = None,
    active_station_count: int | None = None,
    freshness_threshold_seconds: int | None = None,
) -> RealtimeSourceHealthRow:
    latest_run_at = (
        NOW - timedelta(minutes=latest_run_delta_minutes)
        if latest_run_delta_minutes is not None
        else None
    )
    latest_observed_at = (
        NOW - timedelta(minutes=observed_delta_minutes)
        if observed_delta_minutes is not None
        else None
    )
    runtime_enabled_checked_at = (
        NOW - timedelta(minutes=runtime_enabled_delta_minutes)
        if runtime_enabled_delta_minutes is not None
        else None
    )
    runtime_pipeline_checked_at = (
        NOW - timedelta(minutes=runtime_pipeline_delta_minutes)
        if runtime_pipeline_delta_minutes is not None
        else None
    )
    runtime_pipeline_run_at = (
        NOW - timedelta(minutes=runtime_pipeline_run_delta_minutes)
        if runtime_pipeline_run_delta_minutes is not None
        else None
    )
    return RealtimeSourceHealthRow(
        adapter_key=adapter_key,
        name=name,
        is_enabled=is_enabled,
        configured_health_status=configured_health_status,
        last_success_at=latest_run_at if latest_run_status == "succeeded" else None,
        last_failure_at=latest_run_at if latest_run_status == "failed" else None,
        latest_run_status=latest_run_status,
        latest_run_error_code=latest_run_error_code,
        latest_run_at=latest_run_at,
        latest_observed_at=latest_observed_at,
        latest_ingested_at=latest_run_at,
        station_count=station_count,
        inventory_complete=inventory_complete,
        is_registered=is_registered,
        runtime_enabled=runtime_enabled,
        runtime_enabled_checked_at=runtime_enabled_checked_at,
        runtime_pipeline_status=runtime_pipeline_status,
        runtime_pipeline_checked_at=runtime_pipeline_checked_at,
        runtime_pipeline_run_at=runtime_pipeline_run_at,
        runtime_pipeline_complete=runtime_pipeline_complete,
        fresh_station_count=fresh_station_count,
        delayed_station_count=delayed_station_count,
        stale_station_count=stale_station_count,
        active_station_count=active_station_count,
        freshness_threshold_seconds=freshness_threshold_seconds,
    )


def _coverage_with_health(
    *health_rows: RealtimeSourceHealthRow,
    jurisdiction_checked: bool = True,
):
    source_health = build_nearby_source_health(tuple(health_rows), evaluated_at=NOW)
    return build_nearby_realtime_coverage(
        rows=(),
        query_radius_m=500,
        evaluated_at=NOW,
        source_health=source_health,
        source_health_checked=True,
        jurisdiction_status=("verified" if jurisdiction_checked else "unavailable"),
        jurisdiction_checked=jurisdiction_checked,
        jurisdiction_complete_signal_types=(
            REQUIRED_SIGNAL_TYPES if jurisdiction_checked else ()
        ),
    )


def test_source_health_proves_no_station_only_with_operational_national_inventory() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.cwa.rainfall",
            name="中央氣象署雨量觀測",
            station_count=42,
            inventory_complete=True,
        )
    )

    rainfall = next(item for item in coverage.signal_breakdown if item.signal_type == "rainfall")
    health = coverage.source_health[0]
    assert rainfall.availability_state == "no_station"
    assert rainfall.missing_cause == "no_station_in_range"
    assert rainfall.source_health_status == "healthy"
    assert rainfall.source_count == 1
    assert health.source_id == "official-cwa-rainfall"
    assert health.coverage_scope == "national"
    assert health.reason_code == "operational"
    assert health.station_count == 42
    assert health.inventory_complete is True
    assert "adapter_key" not in health.model_dump()


def test_positive_observed_station_count_is_not_complete_inventory_proof() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.cwa.rainfall",
            station_count=42,
            inventory_complete=False,
        )
    )

    rainfall = next(item for item in coverage.signal_breakdown if item.signal_type == "rainfall")
    assert rainfall.availability_state == "source_status_unknown"
    assert rainfall.missing_cause == "inventory_unverified"
    assert coverage.source_health[0].health_status == "healthy"
    assert coverage.source_health[0].inventory_complete is False
    assert "清冊完整性尚未驗證" in (rainfall.missing_reason or "")


def test_public_source_names_distinguish_multiple_water_networks() -> None:
    source_health = build_nearby_source_health(
        (
            _health_row(adapter_key="official.civil_iot.river_water_level"),
            _health_row(adapter_key="official.civil_iot.pond_water_level"),
        ),
        evaluated_at=NOW,
    )

    assert {item.name for item in source_health} == {
        "水利署 Civil IoT 河川水位",
        "水利署 Civil IoT 埤塘水位",
    }
    assert len({item.source_id for item in source_health}) == 2

    kinmen = build_nearby_source_health(
        (_health_row(adapter_key="local.kinmen.kwis_pump_station"),),
        evaluated_at=NOW,
    )[0]
    assert kinmen.name == "金門縣抽水站/水門狀態觀測"
    assert kinmen.coverage_scope == "local"

    yilan = build_nearby_source_health(
        (_health_row(adapter_key="local.yilan.mobile_pump_status"),),
        evaluated_at=NOW,
    )[0]
    assert yilan.name == "宜蘭縣抽水站/水門狀態觀測"
    assert yilan.signal_types == ["pump_or_gate_status"]
    assert yilan.coverage_scope == "local"


def test_source_observation_freshness_boundaries_are_inclusive() -> None:
    cases = (
        (10, "healthy", "operational"),
        (11, "degraded", "delayed"),
        (30, "degraded", "delayed"),
        (31, "failed", "upstream_unavailable"),
    )

    for observed_minutes, expected_status, expected_reason in cases:
        health = build_nearby_source_health(
            (
                _health_row(
                    adapter_key="official.cwa.rainfall",
                    observed_delta_minutes=observed_minutes,
                ),
            ),
            evaluated_at=NOW,
        )[0]
        assert health.health_status == expected_status
        assert health.reason_code == expected_reason


@pytest.mark.parametrize(
    ("threshold_seconds", "observed_minutes", "expected_status"),
    (
        (120, 2, "healthy"),
        (120, 3, "degraded"),
        (120, 6, "degraded"),
        (120, 7, "failed"),
        (None, 10, "healthy"),
        (None, 30, "degraded"),
        (None, 31, "failed"),
    ),
)
def test_station_health_uses_catalog_threshold_with_600_second_fallback(
    threshold_seconds: int | None,
    observed_minutes: int,
    expected_status: str,
) -> None:
    health = build_nearby_source_health(
        (
            _health_row(
                adapter_key="official.cwa.rainfall",
                station_count=1,
                observed_delta_minutes=observed_minutes,
                freshness_threshold_seconds=threshold_seconds,
            ),
        ),
        evaluated_at=NOW,
    )[0]

    assert health.health_status == expected_status


def test_recent_no_active_warning_poll_is_healthy_without_local_coverage() -> None:
    source_health = build_nearby_source_health(
        (
            _health_row(
                adapter_key="official.cwa.heavy_rain_warning",
                latest_run_status="succeeded",
                latest_run_error_code="no_active_event",
                latest_run_delta_minutes=2,
                observed_delta_minutes=None,
                station_count=0,
                freshness_threshold_seconds=600,
            ),
        ),
        evaluated_at=NOW,
    )
    coverage = build_nearby_realtime_coverage(
        rows=(),
        query_radius_m=500,
        evaluated_at=NOW,
        source_health=source_health,
        source_health_checked=True,
    )

    warning = next(
        item for item in coverage.signal_breakdown if item.signal_type == "flood_warning"
    )
    assert source_health[0].health_status == "healthy"
    assert source_health[0].reason_code == "operational"
    assert warning.fresh_count == 0
    assert warning.counts_by_radius_m == {
        "500": 0,
        "1000": 0,
        "3000": 0,
        "5000": 0,
        "10000": 0,
        "15000": 0,
    }
    assert coverage.overall_level == "no_local_sensor"
    assert set(coverage.missing_signal_types) == set(REQUIRED_SIGNAL_TYPES)


def test_skipped_warning_poll_is_not_healthy_no_active_context() -> None:
    health = build_nearby_source_health(
        (
            _health_row(
                adapter_key="official.ncdr.cap",
                latest_run_status="skipped",
                latest_run_delta_minutes=2,
                observed_delta_minutes=None,
                station_count=0,
            ),
        ),
        evaluated_at=NOW,
    )[0]

    assert health.health_status != "healthy"


def test_recent_failed_source_is_not_reported_as_no_station() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.wra.water_level",
            name="postgresql://internal-user:private-token@db.internal/source",
            latest_run_status="failed",
            observed_delta_minutes=None,
        )
    )

    water_level = next(
        item for item in coverage.signal_breakdown if item.signal_type == "water_level"
    )
    health = coverage.source_health[0]
    assert water_level.availability_state == "source_unavailable"
    assert water_level.missing_cause == "source_failed"
    assert water_level.failed_source_count == 1
    assert health.health_status == "failed"
    assert health.reason_code == "pipeline_unavailable"
    assert "錯誤" in health.message
    assert "無法確認" in (water_level.missing_reason or "")
    assert health.name == "經濟部水利署河川水位觀測"
    assert "private-token" not in coverage.model_dump_json()


def test_configuration_failure_has_public_reason_without_leaking_error_code() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.ncdr.cap",
            latest_run_status="failed",
            latest_run_error_code="NcdrCapAlertConfigurationError",
            latest_run_delta_minutes=2,
            observed_delta_minutes=None,
            station_count=0,
            runtime_enabled=True,
            runtime_enabled_delta_minutes=1,
            runtime_pipeline_status="failed",
            runtime_pipeline_delta_minutes=1,
        )
    )

    health = coverage.source_health[0]
    assert health.health_status == "failed"
    assert health.reason_code == "source_misconfigured"
    assert "必要設定" in health.message
    assert "NcdrCapAlertConfigurationError" not in coverage.model_dump_json()


@pytest.mark.parametrize(
    "error_code",
    (
        "TainanFloodSensorTimeoutError",
        "TainanFloodSensorFetchError",
        "TainanFloodSensorHttpError",
        "TainanFloodSensorPayloadError",
    ),
)
def test_upstream_response_failures_have_public_reason_without_leaking_error_code(
    error_code: str,
) -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="local.tainan.flood_sensor",
            latest_run_status="failed",
            latest_run_error_code=error_code,
            latest_run_delta_minutes=2,
            observed_delta_minutes=None,
            station_count=0,
            runtime_enabled=True,
            runtime_enabled_delta_minutes=1,
            runtime_pipeline_status="failed",
            runtime_pipeline_delta_minutes=1,
        )
    )

    health = coverage.source_health[0]
    assert health.health_status == "failed"
    assert health.reason_code == "upstream_unavailable"
    assert "背景來源" in health.message
    assert error_code not in coverage.model_dump_json()


@pytest.mark.parametrize(
    "error_code",
    (
        "HTTPError",
        "URLError",
        "RemoteDisconnected",
        "ConnectionError",
        "CivilIotStaHTTPError",
    ),
)
def test_upstream_transport_failures_report_a_retrying_upstream_outage(
    error_code: str,
) -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="local.tainan.flood_sensor",
            latest_run_status="failed",
            latest_run_error_code=error_code,
            latest_run_delta_minutes=2,
            observed_delta_minutes=None,
            station_count=0,
            runtime_enabled=True,
            runtime_enabled_delta_minutes=1,
            runtime_pipeline_status="failed",
            runtime_pipeline_delta_minutes=1,
        )
    )

    health = coverage.source_health[0]
    assert health.health_status == "failed"
    assert health.reason_code == "upstream_unavailable"
    assert "上游服務" in health.message
    assert error_code not in coverage.model_dump_json()


def test_stalled_update_pipeline_has_distinct_missing_cause() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.wra.water_level",
            latest_run_status="succeeded",
            latest_run_delta_minutes=31,
            observed_delta_minutes=5,
        )
    )

    water_level = next(
        item for item in coverage.signal_breakdown if item.signal_type == "water_level"
    )
    assert water_level.availability_state == "source_unavailable"
    assert water_level.missing_cause == "update_pipeline_stalled"
    assert coverage.source_health[0].reason_code == "pipeline_stalled"
    assert "背景更新近期沒有活動" in (water_level.missing_reason or "")


def test_pipeline_stall_threshold_is_strictly_over_thirty_minutes() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.wra.water_level",
            latest_run_status="succeeded",
            latest_run_delta_minutes=30,
            observed_delta_minutes=5,
        )
    )

    water_level = next(
        item for item in coverage.signal_breakdown if item.signal_type == "water_level"
    )
    assert water_level.missing_cause == "source_degraded"
    assert coverage.source_health[0].health_status == "degraded"
    assert coverage.source_health[0].reason_code == "delayed"


def test_explicit_disabled_job_status_overrides_old_observation_state() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.cwa.rainfall",
            latest_run_status="disabled",
            latest_run_delta_minutes=5,
            observed_delta_minutes=5,
            station_count=42,
        )
    )

    rainfall = next(item for item in coverage.signal_breakdown if item.signal_type == "rainfall")
    assert rainfall.missing_cause == "source_not_configured"
    assert coverage.source_health[0].health_status == "disabled"
    assert coverage.source_health[0].reason_code == "disabled"


def test_stale_persisted_disabled_gate_without_runtime_snapshot_stays_unknown() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.cwa.rainfall",
            is_enabled=False,
            configured_health_status="disabled",
            latest_run_status="succeeded",
            latest_run_delta_minutes=31,
            observed_delta_minutes=31,
            station_count=42,
        )
    )

    rainfall = next(item for item in coverage.signal_breakdown if item.signal_type == "rainfall")
    assert rainfall.missing_cause == "source_not_configured"
    assert coverage.source_health[0].health_status == "disabled"
    assert coverage.source_health[0].reason_code == "disabled"


def test_fresh_runtime_disabled_snapshot_overrides_old_activity() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.cwa.rainfall",
            is_enabled=True,
            latest_run_status="succeeded",
            latest_run_delta_minutes=90,
            observed_delta_minutes=90,
            runtime_enabled=False,
            runtime_enabled_delta_minutes=5,
        )
    )

    rainfall = next(item for item in coverage.signal_breakdown if item.signal_type == "rainfall")
    assert rainfall.missing_cause == "source_not_configured"
    assert coverage.source_health[0].health_status == "disabled"
    assert coverage.source_health[0].reason_code == "disabled"


def test_fresh_runtime_enabled_snapshot_exposes_stalled_worker() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.cwa.rainfall",
            is_enabled=False,
            configured_health_status="disabled",
            latest_run_status="succeeded",
            latest_run_delta_minutes=31,
            observed_delta_minutes=31,
            runtime_enabled=True,
            runtime_enabled_delta_minutes=5,
        )
    )

    rainfall = next(item for item in coverage.signal_breakdown if item.signal_type == "rainfall")
    assert rainfall.missing_cause == "source_not_configured"
    assert coverage.source_health[0].health_status == "disabled"
    assert coverage.source_health[0].reason_code == "disabled"


def test_fresh_runtime_enabled_snapshot_does_not_fall_back_to_persisted_disabled_gate() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.cwa.rainfall",
            is_enabled=False,
            configured_health_status="disabled",
            latest_run_status=None,
            latest_run_delta_minutes=None,
            observed_delta_minutes=None,
            station_count=None,
            runtime_enabled=True,
            runtime_enabled_delta_minutes=5,
        )
    )

    rainfall = next(item for item in coverage.signal_breakdown if item.signal_type == "rainfall")
    assert rainfall.missing_cause == "source_not_configured"
    assert coverage.source_health[0].health_status == "disabled"
    assert coverage.source_health[0].reason_code == "disabled"


def test_stale_runtime_selection_snapshot_exposes_worker_stall() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.cwa.rainfall",
            latest_run_status=None,
            latest_run_delta_minutes=None,
            observed_delta_minutes=None,
            station_count=None,
            runtime_enabled=True,
            runtime_enabled_delta_minutes=31,
        )
    )

    rainfall = next(item for item in coverage.signal_breakdown if item.signal_type == "rainfall")
    assert rainfall.missing_cause == "update_pipeline_stalled"
    assert coverage.source_health[0].reason_code == "pipeline_stalled"


def test_final_pipeline_failure_overrides_successful_ingestion_summary() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.wra.water_level",
            latest_run_status="succeeded",
            latest_run_delta_minutes=5,
            observed_delta_minutes=5,
            runtime_pipeline_status="failed",
            runtime_pipeline_delta_minutes=1,
        )
    )

    water_level = next(
        item for item in coverage.signal_breakdown if item.signal_type == "water_level"
    )
    assert water_level.missing_cause == "source_failed"
    assert coverage.source_health[0].health_status == "failed"
    assert coverage.source_health[0].reason_code == "pipeline_unavailable"
    assert "處理或發布流程未完成" in coverage.source_health[0].message


def test_current_builder_failure_overrides_older_disabled_job() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.wra.water_level",
            latest_run_status="disabled",
            latest_run_delta_minutes=60,
            observed_delta_minutes=None,
            station_count=None,
            runtime_enabled=True,
            runtime_enabled_delta_minutes=1,
            runtime_pipeline_status="failed",
            runtime_pipeline_delta_minutes=1,
        )
    )

    water_level = next(
        item for item in coverage.signal_breakdown if item.signal_type == "water_level"
    )
    assert water_level.missing_cause == "source_failed"
    assert coverage.source_health[0].health_status == "failed"
    assert coverage.source_health[0].reason_code == "pipeline_unavailable"


def test_newer_pre_fetch_failure_generation_overrides_previous_success() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.wra.water_level",
            latest_run_status="succeeded",
            latest_run_delta_minutes=5,
            observed_delta_minutes=5,
            runtime_enabled=True,
            runtime_enabled_delta_minutes=1,
            runtime_pipeline_status="failed",
            runtime_pipeline_delta_minutes=1,
            runtime_pipeline_run_delta_minutes=1,
        )
    )

    water_level = next(
        item for item in coverage.signal_breakdown if item.signal_type == "water_level"
    )
    assert water_level.missing_cause == "source_failed"
    assert coverage.source_health[0].health_status == "failed"
    assert coverage.source_health[0].reason_code == "pipeline_unavailable"


def test_recent_ingestion_waiting_for_final_pipeline_is_degraded() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.wra.water_level",
            latest_run_status="succeeded",
            latest_run_delta_minutes=5,
            observed_delta_minutes=5,
            runtime_enabled=True,
            runtime_enabled_delta_minutes=1,
        )
    )

    water_level = next(
        item for item in coverage.signal_breakdown if item.signal_type == "water_level"
    )
    assert water_level.missing_cause == "source_degraded"
    assert coverage.source_health[0].health_status == "degraded"
    assert coverage.source_health[0].reason_code == "delayed"


def test_unconfirmed_final_pipeline_becomes_failure_after_grace_period() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.wra.water_level",
            latest_run_status="succeeded",
            latest_run_delta_minutes=16,
            observed_delta_minutes=5,
            runtime_enabled=True,
            runtime_enabled_delta_minutes=1,
        )
    )

    water_level = next(
        item for item in coverage.signal_breakdown if item.signal_type == "water_level"
    )
    assert water_level.missing_cause == "source_failed"
    assert coverage.source_health[0].health_status == "failed"
    assert coverage.source_health[0].reason_code == "pipeline_unavailable"


def test_current_but_incomplete_final_pipeline_is_degraded() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.wra.water_level",
            latest_run_status="succeeded",
            latest_run_delta_minutes=5,
            observed_delta_minutes=5,
            runtime_enabled=True,
            runtime_enabled_delta_minutes=1,
            runtime_pipeline_status="succeeded",
            runtime_pipeline_delta_minutes=1,
            runtime_pipeline_run_delta_minutes=5,
            runtime_pipeline_complete=False,
        )
    )

    water_level = next(
        item for item in coverage.signal_breakdown if item.signal_type == "water_level"
    )
    assert water_level.missing_cause == "source_degraded"
    assert coverage.source_health[0].health_status == "degraded"
    assert coverage.source_health[0].reason_code == "delayed"


def test_exact_complete_final_pipeline_can_report_healthy_source() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.wra.water_level",
            latest_run_status="succeeded",
            latest_run_delta_minutes=5,
            observed_delta_minutes=5,
            runtime_enabled=True,
            runtime_enabled_delta_minutes=1,
            runtime_pipeline_status="succeeded",
            runtime_pipeline_delta_minutes=1,
            runtime_pipeline_run_delta_minutes=5,
            runtime_pipeline_complete=True,
        )
    )

    assert coverage.source_health[0].health_status == "healthy"
    assert coverage.source_health[0].reason_code == "operational"


def test_late_outcome_from_older_run_cannot_override_latest_run_health() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.wra.water_level",
            latest_run_status="succeeded",
            latest_run_delta_minutes=5,
            observed_delta_minutes=5,
            runtime_enabled=True,
            runtime_enabled_delta_minutes=1,
            runtime_pipeline_status="failed",
            runtime_pipeline_delta_minutes=1,
            runtime_pipeline_run_delta_minutes=20,
        )
    )

    assert coverage.source_health[0].health_status == "degraded"
    assert coverage.source_health[0].reason_code == "delayed"


def test_unregistered_expected_source_is_publicly_unknown() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.cwa.rainfall",
            is_registered=False,
            is_enabled=False,
            configured_health_status="unknown",
            latest_run_status=None,
            latest_run_delta_minutes=None,
            observed_delta_minutes=None,
            station_count=None,
        )
    )

    rainfall = next(item for item in coverage.signal_breakdown if item.signal_type == "rainfall")
    assert rainfall.missing_cause == "source_not_configured"
    assert coverage.source_health[0].health_status == "disabled"
    assert coverage.source_health[0].reason_code == "disabled"


def test_recent_runtime_activity_overrides_stale_persisted_disabled_gate() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="local.tainan.flood_sensor",
            is_enabled=False,
            configured_health_status="disabled",
            latest_run_status="succeeded",
            latest_run_delta_minutes=5,
            observed_delta_minutes=5,
            station_count=18,
        )
    )

    assert coverage.source_health[0].health_status == "disabled"
    assert coverage.source_health[0].reason_code == "disabled"


def test_one_fresh_station_cannot_hide_stale_stations() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.cwa.rainfall",
            station_count=10,
            observed_delta_minutes=1,
            fresh_station_count=1,
            delayed_station_count=0,
            stale_station_count=9,
        )
    )

    rainfall = next(item for item in coverage.signal_breakdown if item.signal_type == "rainfall")
    assert rainfall.missing_cause == "source_degraded"
    assert coverage.source_health[0].health_status == "degraded"
    assert coverage.source_health[0].reason_code == "upstream_unavailable"


def test_recent_queued_job_is_delayed_instead_of_unknown() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.cwa.rainfall",
            latest_run_status="queued",
            latest_run_delta_minutes=5,
            observed_delta_minutes=None,
            station_count=None,
        )
    )

    rainfall = next(item for item in coverage.signal_breakdown if item.signal_type == "rainfall")
    assert rainfall.missing_cause == "source_degraded"
    assert coverage.source_health[0].health_status == "degraded"
    assert coverage.source_health[0].reason_code == "delayed"


def test_empty_station_inventory_is_degraded_not_no_station_proof() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.cwa.rainfall",
            station_count=0,
            observed_delta_minutes=None,
        )
    )

    rainfall = next(item for item in coverage.signal_breakdown if item.signal_type == "rainfall")
    assert rainfall.availability_state == "source_unavailable"
    assert rainfall.missing_cause == "source_degraded"
    assert coverage.source_health[0].health_status == "degraded"
    assert coverage.source_health[0].reason_code == "upstream_unavailable"


def test_disabled_source_is_reported_as_not_configured() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.cwa.rainfall",
            is_enabled=False,
            configured_health_status="disabled",
            latest_run_status=None,
            latest_run_delta_minutes=None,
            observed_delta_minutes=None,
            station_count=None,
        )
    )

    rainfall = next(item for item in coverage.signal_breakdown if item.signal_type == "rainfall")
    assert rainfall.availability_state == "source_unavailable"
    assert rainfall.missing_cause == "source_not_configured"
    assert coverage.source_health[0].health_status == "disabled"


def test_disabled_sources_are_not_summarized_as_pipeline_faults() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.wra.water_level",
            station_count=30,
            inventory_complete=True,
        ),
        _health_row(
            adapter_key="official.cwa.rainfall",
            latest_run_status="disabled",
            observed_delta_minutes=None,
            station_count=None,
        ),
        _health_row(
            adapter_key="official.wra_iow.flood_depth",
            latest_run_status="disabled",
            observed_delta_minutes=None,
            station_count=None,
        ),
        _health_row(
            adapter_key="official.civil_iot.sewer_water_level",
            latest_run_status="disabled",
            observed_delta_minutes=None,
            station_count=None,
        ),
    )

    water_level = next(
        item for item in coverage.signal_breakdown if item.signal_type == "water_level"
    )
    assert water_level.missing_cause == "no_station_in_range"
    assert "尚未啟用" in coverage.summary
    assert "管線異常" not in coverage.summary
    assert any("尚未啟用" in limitation for limitation in coverage.limitations)


def test_failed_source_remains_distinct_from_disabled_sources_in_summary() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.wra.water_level",
            station_count=30,
            inventory_complete=True,
        ),
        _health_row(
            adapter_key="official.cwa.rainfall",
            latest_run_status="failed",
            observed_delta_minutes=None,
        ),
        _health_row(
            adapter_key="official.wra_iow.flood_depth",
            latest_run_status="disabled",
            observed_delta_minutes=None,
            station_count=None,
        ),
    )

    assert "管線異常" in coverage.summary
    assert "尚未啟用" not in coverage.summary


def test_health_repository_failure_is_reported_as_unknown() -> None:
    coverage = build_nearby_realtime_coverage(
        rows=(),
        query_radius_m=500,
        evaluated_at=NOW,
        source_health_unavailable=True,
        source_health_checked=False,
    )

    rainfall = next(item for item in coverage.signal_breakdown if item.signal_type == "rainfall")
    assert rainfall.availability_state == "source_status_unknown"
    assert rainfall.missing_cause == "health_unknown"
    assert coverage.source_health_status == "unknown"
    assert any("健康診斷" in limitation for limitation in coverage.limitations)


def test_unchecked_empty_health_uses_safe_unknown_default() -> None:
    coverage = build_nearby_realtime_coverage(
        rows=(),
        query_radius_m=500,
        evaluated_at=NOW,
    )

    rainfall = next(item for item in coverage.signal_breakdown if item.signal_type == "rainfall")
    assert rainfall.availability_state == "source_status_unknown"
    assert rainfall.missing_cause == "health_unknown"
    assert rainfall.missing_cause != "no_station_in_range"


def test_healthy_local_source_cannot_prove_no_station_without_jurisdiction_mapping() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="local.tainan.flood_sensor",
            name="臺南市淹水感測",
            station_count=18,
        ),
        jurisdiction_checked=False,
    )

    flood_depth = next(
        item for item in coverage.signal_breakdown if item.signal_type == "flood_depth"
    )
    assert coverage.source_health[0].coverage_scope == "local"
    assert flood_depth.availability_state == "source_status_unknown"
    assert flood_depth.missing_cause == "jurisdiction_unverified"


def test_disabled_complementary_network_blocks_absolute_no_station_claim() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.cwa.rainfall",
            station_count=236,
            inventory_complete=True,
        ),
        _health_row(
            adapter_key="local.new_taipei.rainfall",
            latest_run_status="disabled",
            observed_delta_minutes=None,
            station_count=None,
        ),
    )

    rainfall = next(item for item in coverage.signal_breakdown if item.signal_type == "rainfall")
    assert rainfall.missing_cause == "source_not_configured"
    assert rainfall.missing_cause != "no_station_in_range"


def test_unknown_complementary_network_is_health_unknown_not_inventory_only() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.cwa.rainfall",
            station_count=236,
            inventory_complete=True,
        ),
        _health_row(
            adapter_key="local.new_taipei.rainfall",
            is_registered=False,
            latest_run_status=None,
            latest_run_delta_minutes=None,
            observed_delta_minutes=None,
            station_count=None,
        ),
    )

    rainfall = next(item for item in coverage.signal_breakdown if item.signal_type == "rainfall")
    assert rainfall.availability_state == "source_status_unknown"
    assert rainfall.missing_cause == "health_unknown"
    assert rainfall.missing_cause != "inventory_unverified"
    assert rainfall.missing_cause != "no_station_in_range"


def test_partial_national_source_failure_cannot_be_hidden_by_healthy_source() -> None:
    coverage = _coverage_with_health(
        _health_row(adapter_key="official.wra.water_level", station_count=50),
        _health_row(
            adapter_key="official.civil_iot.river_water_level",
            latest_run_status="failed",
            observed_delta_minutes=None,
            station_count=12,
        ),
    )

    water_level = next(
        item for item in coverage.signal_breakdown if item.signal_type == "water_level"
    )
    assert water_level.availability_state == "source_unavailable"
    assert water_level.missing_cause == "source_degraded"
    assert water_level.source_health_status == "degraded"
    assert water_level.failed_source_count == 1


def test_failed_source_plus_only_unknown_companion_is_not_partially_available() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.wra.water_level",
            latest_run_status="failed",
            observed_delta_minutes=None,
            station_count=None,
        ),
        _health_row(
            adapter_key="official.civil_iot.river_water_level",
            is_registered=False,
            latest_run_status=None,
            latest_run_delta_minutes=None,
            observed_delta_minutes=None,
            station_count=None,
        ),
    )

    water_level = next(
        item for item in coverage.signal_breakdown if item.signal_type == "water_level"
    )
    assert water_level.availability_state == "source_unavailable"
    assert water_level.missing_cause == "source_failed"
    assert water_level.source_health_status == "failed"
    assert "部分可用" not in (water_level.missing_reason or "")


def test_nearby_coverage_keeps_regional_station_as_labeled_fallback() -> None:
    coverage = build_nearby_realtime_coverage(
        rows=(
            _row(
                adapter_key="official.cwa.rainfall",
                source_id="cwa-rainfall:regional",
                event_type="rainfall",
                distance_to_query_m=7200.0,
            ),
        ),
        query_radius_m=500,
        evaluated_at=NOW,
    )

    rainfall = next(item for item in coverage.signal_breakdown if item.signal_type == "rainfall")
    assert coverage.overall_level == "no_local_sensor"
    assert rainfall.coverage_level == "no_local_sensor"
    assert rainfall.nearest_distance_m == 7200.0
    assert rainfall.counts_by_radius_m["5000"] == 0
    assert rainfall.counts_by_radius_m["10000"] == 1
    assert rainfall.missing_reason is not None
    assert "區域參考" in rainfall.missing_reason
    assert "15 公里內有較遠測站" in coverage.summary
    assert rainfall.availability_state == "regional_reference"


def test_nearby_coverage_treats_four_kilometre_water_level_as_local_low_coverage() -> None:
    coverage = build_nearby_realtime_coverage(
        rows=(
            _row(
                adapter_key="official.wra.water_level",
                source_id="wra-water-level:four-km",
                event_type="water_level",
                distance_to_query_m=4000.0,
            ),
        ),
        query_radius_m=500,
        evaluated_at=NOW,
    )

    water_level = next(
        item for item in coverage.signal_breakdown if item.signal_type == "water_level"
    )
    assert coverage.overall_level == "low"
    assert water_level.coverage_level == "low"
    assert water_level.availability_state == "fresh_nearby"
    assert water_level.missing_reason is None


def test_nearby_coverage_applies_local_and_regional_distance_boundaries() -> None:
    coverage = build_nearby_realtime_coverage(
        rows=(
            _row(
                adapter_key="official.wra.water_level",
                source_id="wra-water-level:local-boundary",
                event_type="water_level",
                distance_to_query_m=5000.0,
            ),
            _row(
                adapter_key="official.cwa.rainfall",
                source_id="cwa-rainfall:regional-boundary",
                event_type="rainfall",
                distance_to_query_m=15000.0,
            ),
            _row(
                adapter_key="official.cwa.rainfall",
                source_id="cwa-rainfall:outside",
                event_type="rainfall",
                distance_to_query_m=15000.1,
            ),
        ),
        query_radius_m=500,
        evaluated_at=NOW,
    )

    water_level = next(
        item for item in coverage.signal_breakdown if item.signal_type == "water_level"
    )
    rainfall = next(item for item in coverage.signal_breakdown if item.signal_type == "rainfall")
    assert water_level.coverage_level == "low"
    assert water_level.availability_state == "fresh_nearby"
    assert rainfall.coverage_level == "no_local_sensor"
    assert rainfall.availability_state == "regional_reference"
    assert rainfall.counts_by_radius_m["15000"] == 1


def test_nearby_coverage_treats_cwa_tide_level_as_water_level_context() -> None:
    coverage = build_nearby_realtime_coverage(
        rows=(
            _row(
                adapter_key="official.cwa.tide_level",
                source_id="cwa-tide-level:C4W01",
                event_type="water_level",
                distance_to_query_m=480.0,
            ),
        ),
        query_radius_m=500,
        evaluated_at=NOW,
    )

    water_level = next(
        item for item in coverage.signal_breakdown if item.signal_type == "water_level"
    )
    assert coverage_signal_type("water_level", "official.cwa.tide_level") == "water_level"
    assert water_level.coverage_level == "high"
    assert water_level.fresh_count == 1
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
    assert status_only.label == "狀態線索"
    assert status_only.status_only_count == 1
    assert status_only.fresh_count == 1
    assert coverage.overall_level == "no_local_sensor"
    assert coverage.summary == "附近有狀態線索，但沒有可用的雨量、水位或淹水深度量測。"
    assert "狀態線索只表示設備或警示狀態，不能代表雨量、水位或淹水深度。" in coverage.limitations
    assert "flood_depth" in coverage.missing_signal_types
    assert "rainfall" in coverage.missing_signal_types
    assert "water_level" in coverage.missing_signal_types
    assert "pump_or_gate_status" not in coverage.missing_signal_types
    assert "flood_warning" not in coverage.missing_signal_types
    assert "status_only" not in coverage.missing_signal_types


def test_yilan_mobile_pump_status_remains_status_only_risk_context() -> None:
    coverage = build_nearby_realtime_coverage(
        rows=(
            _row(
                adapter_key="local.yilan.mobile_pump_status",
                source_id="yilan-mobile-pump:1",
                event_type="status_only",
                distance_to_query_m=150.0,
            ),
        ),
        query_radius_m=500,
        evaluated_at=NOW,
    )

    status_only = next(
        item for item in coverage.signal_breakdown if item.signal_type == "status_only"
    )
    assert coverage_signal_type(
        "status_only", "local.yilan.mobile_pump_status"
    ) == "status_only"
    assert status_only.status_only_count == 1
    assert status_only.fresh_count == 1
    assert coverage.overall_level == "no_local_sensor"


def test_nearby_coverage_does_not_present_stale_status_as_current_context() -> None:
    coverage = build_nearby_realtime_coverage(
        rows=(
            _row(
                adapter_key="local.taipei.pump_station",
                source_id="taipei-pump:stale",
                event_type="status_only",
                distance_to_query_m=150.0,
                freshness_state="stale",
                observed_delta_minutes=90,
            ),
        ),
        query_radius_m=500,
        evaluated_at=NOW,
    )

    assert "無法取得完整來源健康狀態" in coverage.summary
    assert all("附近有狀態線索" not in item for item in coverage.limitations)


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


def test_nearby_coverage_stale_water_level_does_not_satisfy_summary_available() -> None:
    coverage = build_nearby_realtime_coverage(
        rows=(
            _row(
                adapter_key="official.cwa.rainfall",
                source_id="cwa-rainfall:fresh",
                event_type="rainfall",
                distance_to_query_m=120.0,
            ),
            _row(
                adapter_key="official.wra.water_level",
                source_id="wra-water-level:stale",
                event_type="water_level",
                distance_to_query_m=150.0,
                freshness_state="stale",
                observed_delta_minutes=90,
            ),
        ),
        query_radius_m=500,
        evaluated_at=NOW,
    )
    rainfall_only_coverage = build_nearby_realtime_coverage(
        rows=(
            _row(
                adapter_key="official.cwa.rainfall",
                source_id="cwa-rainfall:fresh",
                event_type="rainfall",
                distance_to_query_m=120.0,
            ),
        ),
        query_radius_m=500,
        evaluated_at=NOW,
    )

    water_level = next(
        item for item in coverage.signal_breakdown if item.signal_type == "water_level"
    )
    assert coverage.overall_level == "low"
    assert water_level.coverage_level == "no_local_sensor"
    assert water_level.stale_count == 1
    assert "water_level" in coverage.missing_signal_types
    assert "water_level" not in coverage.summary
    assert coverage.limitations[1:] == rainfall_only_coverage.limitations[1:]
    assert coverage.limitations[1:]


def test_stale_short_cadence_redundant_source_cannot_satisfy_low_coverage() -> None:
    coverage = build_nearby_realtime_coverage(
        rows=(
            _row(
                adapter_key="local.tainan.rainfall",
                source_id="local-tainan-rainfall:stale",
                event_type="rainfall",
                distance_to_query_m=120.0,
                freshness_state="stale",
                observed_delta_minutes=12,
            ),
            _row(
                adapter_key="official.wra.water_level",
                source_id="wra-water-level:fresh",
                event_type="water_level",
                distance_to_query_m=150.0,
            ),
        ),
        query_radius_m=500,
        evaluated_at=NOW,
    )

    rainfall = next(
        item for item in coverage.signal_breakdown if item.signal_type == "rainfall"
    )
    assert coverage.overall_level != "low"
    assert rainfall.fresh_count == 0
    assert rainfall.stale_count == 1


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


def test_verified_jurisdiction_without_source_mappings_is_not_source_not_configured() -> None:
    # A verified jurisdiction that resolves to zero adapter keys never reached the
    # database, so its empty source health says nothing about whether the operator
    # enabled the sources.  Reporting "not configured" there asserts a benign cause
    # for what is a catalog fault, and monitoring exempts that cause from failing.
    coverage = build_nearby_realtime_coverage(
        rows=(),
        query_radius_m=500,
        evaluated_at=NOW,
        source_health=(),
        source_health_unavailable=False,
        source_health_checked=True,
        jurisdiction_status="verified",
        jurisdiction_checked=True,
        jurisdiction_mapping_missing=True,
    )

    rainfall = next(item for item in coverage.signal_breakdown if item.signal_type == "rainfall")
    assert rainfall.missing_cause == "jurisdiction_mapping_missing"


def test_empty_source_health_without_mapping_fault_still_reports_not_configured() -> None:
    # Guard the narrow scope: an empty health table with mappings present is still
    # the deployment-configuration state the degraded path is allowed to excuse.
    coverage = build_nearby_realtime_coverage(
        rows=(),
        query_radius_m=500,
        evaluated_at=NOW,
        source_health=(),
        source_health_unavailable=False,
        source_health_checked=True,
        jurisdiction_status="verified",
        jurisdiction_checked=True,
        jurisdiction_mapping_missing=False,
    )

    rainfall = next(item for item in coverage.signal_breakdown if item.signal_type == "rainfall")
    assert rainfall.missing_cause == "source_not_configured"


def test_majority_fresh_active_stations_are_healthy() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.cwa.rainfall",
            station_count=1_000,
            active_station_count=1_000,
            fresh_station_count=950,
            delayed_station_count=20,
            stale_station_count=30,
            observed_delta_minutes=1,
        )
    )

    health = coverage.source_health[0]
    assert health.health_status == "healthy"
    assert health.reason_code == "operational"
    assert "950/1000" in health.message


def test_partially_updated_station_network_is_delayed() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.cwa.rainfall",
            station_count=1_000,
            active_station_count=1_000,
            fresh_station_count=600,
            delayed_station_count=300,
            stale_station_count=100,
            observed_delta_minutes=1,
        )
    )

    health = coverage.source_health[0]
    assert health.health_status == "degraded"
    assert health.reason_code == "delayed"
    assert "600" in health.message
    assert "300" in health.message


def test_stalled_upstream_with_running_worker_is_upstream_stale() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.wra_iow.flood_depth",
            latest_run_status="succeeded",
            latest_run_delta_minutes=0.5,
            observed_delta_minutes=60 * 20,
            station_count=1_366,
            active_station_count=1_366,
            fresh_station_count=0,
            delayed_station_count=0,
            stale_station_count=1_366,
        )
    )

    health = coverage.source_health[0]
    assert health.health_status == "degraded"
    assert health.reason_code == "upstream_stale"
    assert "上游" in health.message
    assert "本站背景更新正常" in health.message


def test_upstream_stale_message_survives_the_public_explanation_filter() -> None:
    # The risk explanation keeps an upstream publication gap verbatim while it
    # summarises every other delayed source.  Pin producer and consumer
    # together so a reworded message cannot silently drop out of the filter.
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.wra_iow.flood_depth",
            latest_run_status="succeeded",
            latest_run_delta_minutes=0.5,
            observed_delta_minutes=60 * 20,
            station_count=1_366,
            active_station_count=1_366,
            fresh_station_count=0,
            delayed_station_count=0,
            stale_station_count=1_366,
        )
    )

    health = coverage.source_health[0]
    assert health.reason_code == "upstream_stale"
    assert _is_upstream_stale(health.message)


def test_ten_day_upstream_stall_stays_upstream_stale_after_active_drains() -> None:
    # After the seven-day active window closes, active_station_count reaches
    # zero.  The public reason must still name the upstream publisher instead of
    # claiming this site produced no station observations.
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.wra_iow.flood_depth",
            latest_run_status="succeeded",
            latest_run_delta_minutes=1,
            observed_delta_minutes=60 * 24 * 10,
            station_count=1_366,
            active_station_count=0,
            fresh_station_count=0,
            delayed_station_count=0,
            stale_station_count=1_366,
        )
    )

    health = coverage.source_health[0]
    assert health.health_status == "degraded"
    assert health.reason_code == "upstream_stale"
    assert "上游" in health.message
    assert "尚未產生可用站點觀測" not in health.message


def test_zero_active_stations_without_a_stalled_upstream_stays_unavailable() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.cwa.rainfall",
            latest_run_status="succeeded",
            latest_run_delta_minutes=20,
            observed_delta_minutes=60 * 24 * 10,
            station_count=42,
            active_station_count=0,
            fresh_station_count=0,
            delayed_station_count=0,
            stale_station_count=42,
        )
    )

    health = coverage.source_health[0]
    assert health.reason_code == "upstream_unavailable"
    assert "尚未產生可用站點觀測" in health.message


def test_partial_run_with_fresh_observations_stays_healthy() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.cwa.rainfall",
            latest_run_status="partial",
            latest_run_delta_minutes=2,
            observed_delta_minutes=1,
            station_count=1_000,
            active_station_count=1_000,
            fresh_station_count=950,
            delayed_station_count=20,
            stale_station_count=30,
        )
    )

    health = coverage.source_health[0]
    assert health.health_status == "healthy"
    assert health.reason_code == "operational"


def test_missing_active_station_count_falls_back_to_station_count() -> None:
    coverage = _coverage_with_health(
        _health_row(
            adapter_key="official.cwa.rainfall",
            station_count=10,
            active_station_count=None,
            fresh_station_count=9,
            delayed_station_count=1,
            stale_station_count=0,
            observed_delta_minutes=1,
        )
    )

    health = coverage.source_health[0]
    assert health.health_status == "healthy"
    assert health.reason_code == "operational"
    assert "9/10" in health.message
