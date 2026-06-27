from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.adapters.contracts import (
    AdapterMetadata,
    AdapterRunResult,
    EventType,
    NormalizedEvidence,
    RawSourceItem,
    SourceFamily,
)
from app.jobs.freshness import (
    check_batch_freshness,
    check_ncdr_cap_freshness,
    check_summary_freshness,
)
from app.jobs.ingestion import AdapterBatchRunSummary, AdapterBatchStatus, run_adapter_batch


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
    stale = check_ncdr_cap_freshness(
        adapter_key="official.ncdr.cap",
        effective_at=CHECKED_AT - timedelta(hours=1),
        expires_at=CHECKED_AT - timedelta(minutes=1),
        checked_at=CHECKED_AT,
    )

    assert fresh.status == "fresh"
    assert degraded.status == "degraded"
    assert degraded.reason == "CAP alert is not yet effective"
    assert stale.status == "stale"
    assert stale.reason == "CAP alert expired; no active alert"
    assert stale.is_alert()


def test_summary_freshness_uses_ncdr_cap_effective_expires_window() -> None:
    fresh = check_summary_freshness(
        _summary(
            adapter_key="official.ncdr.cap",
            source_timestamp_min=CHECKED_AT - timedelta(minutes=5),
            source_timestamp_max=CHECKED_AT + timedelta(minutes=25),
        ),
        checked_at=CHECKED_AT,
        max_age_seconds=60 * 60,
    )
    degraded = check_summary_freshness(
        _summary(
            adapter_key="official.ncdr.cap",
            source_timestamp_min=CHECKED_AT + timedelta(minutes=5),
            source_timestamp_max=CHECKED_AT + timedelta(minutes=35),
        ),
        checked_at=CHECKED_AT,
        max_age_seconds=60 * 60,
    )
    stale = check_summary_freshness(
        _summary(
            adapter_key="official.ncdr.cap",
            source_timestamp_min=CHECKED_AT - timedelta(hours=1),
            source_timestamp_max=CHECKED_AT - timedelta(minutes=1),
        ),
        checked_at=CHECKED_AT,
        max_age_seconds=60 * 60,
    )

    assert fresh.status == "fresh"
    assert degraded.status == "degraded"
    assert stale.status == "stale"
    assert stale.reason == "CAP alert expired; no active alert"
    assert stale.is_alert()


def test_ncdr_cap_failed_batch_is_the_only_failed_no_active_alert_case() -> None:
    no_active_alert = check_summary_freshness(
        _summary(
            adapter_key="official.ncdr.cap",
            source_timestamp_min=None,
            source_timestamp_max=None,
        ),
        checked_at=CHECKED_AT,
        max_age_seconds=60 * 60,
    )
    failed_batch = check_summary_freshness(
        _summary(
            adapter_key="official.ncdr.cap",
            status="failed",
            source_timestamp_min=CHECKED_AT - timedelta(hours=1),
            source_timestamp_max=CHECKED_AT - timedelta(minutes=1),
            error_message="upstream 500",
        ),
        checked_at=CHECKED_AT,
        max_age_seconds=60 * 60,
    )

    assert no_active_alert.status == "stale"
    assert no_active_alert.reason == "CAP alert is missing effective or expires timestamp"
    assert failed_batch.status == "failed"
    assert failed_batch.reason == "upstream 500"


def test_ncdr_cap_batch_summary_preserves_effective_expires_window() -> None:
    effective_at = CHECKED_AT - timedelta(minutes=5)
    expires_at = CHECKED_AT + timedelta(minutes=25)

    summary = run_adapter_batch(
        _CapAdapter(
            effective_at=effective_at,
            expires_at=expires_at,
            fetched_at=CHECKED_AT,
        )
    )
    check = check_summary_freshness(
        summary,
        checked_at=CHECKED_AT,
        max_age_seconds=60 * 60,
    )

    assert summary.source_timestamp_min == effective_at
    assert summary.source_timestamp_max == expires_at
    assert check.status == "fresh"


def _summary(
    *,
    adapter_key: str = "official.cwa.rainfall",
    status: AdapterBatchStatus = "succeeded",
    source_timestamp_min: datetime | None = CHECKED_AT,
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
        source_timestamp_min=source_timestamp_min,
        source_timestamp_max=source_timestamp_max,
    )


class _CapAdapter:
    metadata = AdapterMetadata(
        key="official.ncdr.cap",
        family=SourceFamily.OFFICIAL,
        enabled_by_default=False,
        display_name="NCDR CAP alert adapter",
    )

    def __init__(
        self,
        *,
        effective_at: datetime,
        expires_at: datetime,
        fetched_at: datetime,
    ) -> None:
        self.effective_at = effective_at
        self.expires_at = expires_at
        self.fetched_at = fetched_at

    def run(self) -> AdapterRunResult:
        raw_item = RawSourceItem(
            source_id="NCDR-CAP-001",
            source_url="https://example.test/ncdr/cap",
            fetched_at=self.fetched_at,
            payload={
                "identifier": "NCDR-CAP-001",
                "effective": self.effective_at.isoformat(),
                "expires": self.expires_at.isoformat(),
                "areaDesc": "Tainan City",
            },
        )
        evidence = NormalizedEvidence(
            evidence_id="ev_ncdr_cap_001",
            adapter_key="official.ncdr.cap",
            source_family=SourceFamily.OFFICIAL,
            event_type=EventType.FLOOD_WARNING,
            source_id="NCDR-CAP-001",
            source_url="https://example.test/ncdr/cap",
            source_title="NCDR CAP alert",
            source_timestamp=self.effective_at,
            fetched_at=self.fetched_at,
            summary="NCDR CAP flood warning",
            location_text="Tainan City",
            confidence=0.95,
        )
        return AdapterRunResult(
            adapter_key="official.ncdr.cap",
            fetched=(raw_item,),
            normalized=(evidence,),
        )
