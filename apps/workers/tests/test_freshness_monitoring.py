from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.jobs.freshness import (
    check_batch_freshness,
    check_ncdr_cap_freshness,
    check_summary_freshness,
)
from app.jobs.ingestion import AdapterBatchRunSummary, AdapterBatchStatus


CHECKED_AT = datetime(2026, 4, 30, 4, 0, tzinfo=UTC)


def test_freshness_check_marks_recent_source_timestamp_fresh() -> None:
    check = check_summary_freshness(
        _summary(source_timestamp_max=CHECKED_AT - timedelta(minutes=5)),
        checked_at=CHECKED_AT,
        max_age_seconds=60 * 60,
    )

    assert check.status == "fresh"
    assert check.age_seconds == 5 * 60
    assert not check.is_alert()


def test_realtime_freshness_thresholds_progress_from_degraded_to_stale_to_failed() -> None:
    degraded = check_summary_freshness(
        _summary(source_timestamp_max=CHECKED_AT - timedelta(minutes=20)),
        checked_at=CHECKED_AT,
        max_age_seconds=60 * 60,
    )
    stale = check_summary_freshness(
        _summary(
            adapter_key="official.wra.water_level",
            source_timestamp_max=CHECKED_AT - timedelta(minutes=45),
        ),
        checked_at=CHECKED_AT,
        max_age_seconds=60 * 60,
    )
    failed = check_summary_freshness(
        _summary(
            adapter_key="official.civil_iot.flood_sensor",
            source_timestamp_max=CHECKED_AT - timedelta(minutes=75),
        ),
        checked_at=CHECKED_AT,
        max_age_seconds=60 * 60,
    )

    assert degraded.status == "degraded"
    assert not degraded.is_alert()
    assert stale.status == "stale"
    assert stale.reason == "source data is older than stale freshness threshold"
    assert stale.is_alert()
    assert failed.status == "failed"
    assert failed.reason == "source data is older than failed freshness threshold"
    assert failed.is_alert()


def test_legacy_freshness_check_marks_old_source_timestamp_stale() -> None:
    check = check_summary_freshness(
        _summary(
            adapter_key="news.public_web.sample",
            source_timestamp_max=CHECKED_AT - timedelta(hours=7),
        ),
        checked_at=CHECKED_AT,
        max_age_seconds=6 * 60 * 60,
    )

    assert check.status == "stale"
    assert check.reason == "source data is older than freshness threshold"
    assert check.is_alert()


def test_freshness_check_marks_failed_batch_failed() -> None:
    check = check_summary_freshness(
        _summary(status="failed", error_message="fetch failed"),
        checked_at=CHECKED_AT,
        max_age_seconds=6 * 60 * 60,
    )

    assert check.status == "failed"
    assert check.reason == "fetch failed"
    assert check.is_alert()


def test_batch_freshness_checks_each_summary() -> None:
    checks = check_batch_freshness(
        (
            _summary(
                adapter_key="official.cwa.rainfall",
                source_timestamp_max=CHECKED_AT - timedelta(minutes=5),
            ),
            _summary(adapter_key="official.wra.water_level", status="failed"),
        ),
        checked_at=CHECKED_AT,
        max_age_seconds=6 * 60 * 60,
    )

    assert [check.status for check in checks] == ["fresh", "failed"]


def test_static_flood_potential_is_not_failed_by_realtime_thresholds() -> None:
    check = check_summary_freshness(
        _summary(
            adapter_key="official.flood_potential.geojson",
            source_timestamp_max=CHECKED_AT - timedelta(days=90),
        ),
        checked_at=CHECKED_AT,
        max_age_seconds=60 * 60,
    )

    assert check.status == "fresh"
    assert check.cadence == "static"
    assert not check.is_alert()
    assert (
        check.reason
        == "static/slow-cadence source is not evaluated against realtime thresholds"
    )


def test_ncdr_cap_freshness_uses_effective_expires_window() -> None:
    fresh = check_ncdr_cap_freshness(
        adapter_key="official.ncdr.cap",
        effective_at=CHECKED_AT - timedelta(minutes=5),
        expires_at=CHECKED_AT + timedelta(minutes=25),
        checked_at=CHECKED_AT,
    )
    degraded = check_ncdr_cap_freshness(
        adapter_key="official.ncdr.cap",
        effective_at=CHECKED_AT + timedelta(minutes=5),
        expires_at=CHECKED_AT + timedelta(minutes=35),
        checked_at=CHECKED_AT,
    )
    failed = check_ncdr_cap_freshness(
        adapter_key="official.ncdr.cap",
        effective_at=CHECKED_AT - timedelta(hours=1),
        expires_at=CHECKED_AT - timedelta(minutes=1),
        checked_at=CHECKED_AT,
    )

    assert fresh.status == "fresh"
    assert degraded.status == "degraded"
    assert degraded.reason == "CAP alert is not yet effective"
    assert failed.status == "failed"
    assert failed.reason == "CAP alert expired"


def _summary(
    *,
    adapter_key: str = "official.cwa.rainfall",
    status: AdapterBatchStatus = "succeeded",
    source_timestamp_max: datetime | None = CHECKED_AT,
    error_message: str | None = None,
) -> AdapterBatchRunSummary:
    return AdapterBatchRunSummary(
        adapter_key=adapter_key,
        status=status,
        started_at=CHECKED_AT,
        finished_at=CHECKED_AT,
        items_fetched=1,
        items_promoted=1,
        items_rejected=0,
        error_message=error_message,
        source_timestamp_max=source_timestamp_max,
    )
