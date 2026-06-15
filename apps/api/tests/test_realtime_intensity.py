from __future__ import annotations

from datetime import datetime, timezone

from app.api.services.public_evidence import (
    evidence_from_record,
    rainfall_realtime_risk_factor,
    signal_from_evidence,
)
from app.domain.evidence.repository import EvidenceRecord


INGESTED_AT = datetime(2026, 6, 15, 3, 0, tzinfo=timezone.utc)


def _rainfall_record(rainfall_mm_1h: float | None) -> EvidenceRecord:
    return EvidenceRecord(
        id="11111111-1111-4111-8111-111111111111",
        source_id="cwa:rain-1",
        source_type="official",
        event_type="rainfall",
        title="CWA rainfall observation",
        summary="Observed rainfall",
        url=None,
        occurred_at=INGESTED_AT,
        observed_at=INGESTED_AT,
        ingested_at=INGESTED_AT,
        lat=25.0,
        lng=121.5,
        geometry={"type": "Point", "coordinates": [121.5, 25.0]},
        distance_to_query_m=300.0,
        confidence=0.93,
        freshness_score=0.9,
        source_weight=1.0,
        privacy_level="public",
        raw_ref=None,
        rainfall_mm_1h=rainfall_mm_1h,
    )


def test_rainfall_risk_factor_thresholds() -> None:
    assert rainfall_realtime_risk_factor(0.0) == 0.0
    assert rainfall_realtime_risk_factor(9.9) == 0.0
    assert rainfall_realtime_risk_factor(15.0) == 0.15
    assert rainfall_realtime_risk_factor(25.0) == 0.35
    assert rainfall_realtime_risk_factor(50.0) == 0.7
    assert rainfall_realtime_risk_factor(90.0) == 1.0


def test_dry_rainfall_evidence_scores_zero_intensity() -> None:
    evidence = evidence_from_record(_rainfall_record(0.0))
    assert evidence.realtime_risk_factor == 0.0
    assert signal_from_evidence(evidence).risk_factor == 0.0


def test_heavy_rainfall_evidence_scores_full_intensity() -> None:
    evidence = evidence_from_record(_rainfall_record(95.0))
    assert evidence.realtime_risk_factor == 1.0
    assert signal_from_evidence(evidence).risk_factor == 1.0


def test_missing_rainfall_metric_falls_back_to_neutral_factor() -> None:
    evidence = evidence_from_record(_rainfall_record(None))
    assert evidence.realtime_risk_factor is None
    # No intensity known -> neutral 1.0, preserving prior behavior.
    assert signal_from_evidence(evidence).risk_factor == 1.0


def test_realtime_risk_factor_is_not_serialized() -> None:
    evidence = evidence_from_record(_rainfall_record(0.0))
    assert "realtime_risk_factor" not in evidence.model_dump(mode="json")
