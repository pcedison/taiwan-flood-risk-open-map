from datetime import UTC, datetime, timedelta

from app.domain.ingestion.readiness import (
    _jurisdiction_readiness,
    _scheduler_readiness,
    _source_readiness,
)


NOW = datetime(2026, 9, 1, 1, 0, tzinfo=UTC)


def _source_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "adapter_key": "official.cwa.rainfall",
        "coverage_kind": "national_realtime",
        "stale_after_seconds": 1800,
        "is_registered": True,
        "name": "中央氣象署雨量觀測",
        "is_enabled": True,
        "last_success_at": NOW - timedelta(minutes=2),
        "last_failure_at": None,
        "runtime_enabled": True,
        "runtime_enabled_checked_at": NOW - timedelta(minutes=1),
        "runtime_pipeline_status": "succeeded",
        "runtime_pipeline_checked_at": NOW - timedelta(minutes=2),
        "runtime_pipeline_run_at": NOW - timedelta(minutes=2),
        "runtime_pipeline_complete": True,
        "latest_run_status": "succeeded",
        "latest_run_at": NOW - timedelta(minutes=2),
    }
    row.update(overrides)
    return row


def test_scheduler_readiness_rejects_stale_persisted_heartbeat() -> None:
    readiness = _scheduler_readiness(
        {
            "runtime_status": "running",
            "last_seen_at": NOW - timedelta(minutes=11),
            "stale_after_seconds": 600,
        },
        evaluated_at=NOW,
    )

    assert readiness.status == "stale"
    assert readiness.last_heartbeat_at == NOW - timedelta(minutes=11)


def test_source_readiness_requires_latest_successful_pipeline_outcome() -> None:
    operational = _source_readiness(_source_row(), evaluated_at=NOW)
    incomplete = _source_readiness(
        _source_row(runtime_pipeline_complete=False),
        evaluated_at=NOW,
    )
    failed = _source_readiness(
        _source_row(
            runtime_pipeline_status="failed",
            runtime_pipeline_complete=False,
        ),
        evaluated_at=NOW,
    )

    assert operational.status == "operational"
    assert incomplete.status == "degraded"
    assert incomplete.reason_code == "pipeline_incomplete"
    assert failed.status == "failed"
    assert failed.reason_code == "pipeline_failed"


def test_source_readiness_honors_daily_historical_cadence() -> None:
    history = _source_readiness(
        _source_row(
            adapter_key="official.wra.historical_flood",
            coverage_kind="nationwide_history",
            stale_after_seconds=90000,
            latest_run_at=NOW - timedelta(hours=23),
            runtime_pipeline_run_at=NOW - timedelta(hours=23),
        ),
        evaluated_at=NOW,
    )

    assert history.status == "operational"


def test_jurisdiction_readiness_requires_all_four_proved_signals() -> None:
    rows = [
        {
            "jurisdiction_code": "67000000",
            "jurisdiction_name": "臺南市",
            "signal_type": signal_type,
            "required_adapter_keys": [adapter_key],
            "mapping_proof_valid": True,
        }
        for signal_type, adapter_key in (
            ("rainfall", "rain"),
            ("water_level", "water"),
            ("flood_depth", "depth"),
            ("flood_warning", "warning"),
        )
    ]
    statuses = {key: "operational" for key in ("rain", "water", "depth", "warning")}

    healthy = _jurisdiction_readiness(rows, source_status_by_key=statuses)
    unavailable = _jurisdiction_readiness(
        rows,
        source_status_by_key={**statuses, "depth": "failed"},
    )

    assert healthy[0].status == "operational"
    assert healthy[0].operational_signal_count == 4
    assert unavailable[0].status == "unavailable"
    assert unavailable[0].unavailable_signal_count == 1
