from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.api.schemas import Evidence
from app.api.services import public_freshness
from app.domain.realtime import OfficialRealtimeSourceStatus


NOW = datetime(2026, 4, 30, 4, 0, tzinfo=UTC)


def test_freshness_from_status_preserves_public_schema_fields() -> None:
    status = OfficialRealtimeSourceStatus(
        source_id="cwa-rainfall",
        name="中央氣象署即時雨量",
        health_status="degraded",
        observed_at=NOW - timedelta(hours=7),
        ingested_at=NOW - timedelta(minutes=10),
        message="最新觀測已超過公開 freshness threshold。",
    )

    freshness = public_freshness.freshness_from_status(status)

    assert freshness.source_id == "cwa-rainfall"
    assert freshness.name == "中央氣象署即時雨量"
    assert freshness.health_status == "degraded"
    assert freshness.observed_at == NOW - timedelta(hours=7)
    assert freshness.ingested_at == NOW - timedelta(minutes=10)
    assert freshness.message == "最新觀測已超過公開 freshness threshold。"


def test_persisted_official_realtime_freshness_marks_old_observation_degraded() -> None:
    freshness = public_freshness.persisted_official_realtime_data_freshness(
        (
            _evidence(
                event_type="rainfall",
                source_id="station-001",
                observed_at=NOW - timedelta(hours=7),
            ),
        ),
        now=NOW,
    )

    assert len(freshness) == 1
    item = freshness[0]
    assert item.source_id == "cwa-rainfall"
    assert item.health_status == "degraded"
    assert item.feature_count == 1
    assert item.observed_at == NOW - timedelta(hours=7)
    assert "已過期" in (item.message or "")


def test_historical_data_freshness_without_db_evidence_reports_unknown_gap() -> None:
    freshness = public_freshness.historical_data_freshness(
        historical_records=(),
        db_evidence_items=(),
        now=NOW,
    )

    assert freshness.source_id == "db-evidence"
    assert freshness.health_status == "unknown"
    assert freshness.feature_count == 0
    assert "資料不足" in (freshness.message or "")


def _evidence(
    *,
    event_type: str,
    source_id: str,
    observed_at: datetime,
) -> Evidence:
    return Evidence(
        id=f"ev-{source_id}",
        source_id=source_id,
        source_type="official",
        event_type=event_type,
        title="Realtime observation",
        summary="Persisted official realtime observation.",
        occurred_at=observed_at,
        observed_at=observed_at,
        ingested_at=NOW - timedelta(minutes=3),
        confidence=0.9,
        url="https://example.test/realtime",
        freshness_score=0.7,
        source_weight=1.0,
        privacy_level="public",
    )
