from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import pytest

from app.domain.risk import RiskEvidenceSignal, score_risk


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "scoring"


@pytest.mark.parametrize(
    "fixture_name",
    [
        "flood_potential_only.json",
        "heavy_rainfall_water_level.json",
        "no_evidence_found.json",
        "partial_source_outage.json",
        "conflicting_public_report_low_official_signal.json",
    ],
)
def test_scoring_golden_fixtures(fixture_name: str) -> None:
    fixture = json.loads((FIXTURE_DIR / fixture_name).read_text(encoding="utf-8"))
    result = score_risk(
        tuple(_signal_from_fixture(signal) for signal in fixture["signals"]),
        now=datetime.fromisoformat(fixture["now"]),
    )

    expected = fixture["expected"]
    assert result.score_version == expected["score_version"]
    assert result.realtime_level == expected["realtime_level"]
    assert result.historical_level == expected["historical_level"]
    assert result.confidence_level == expected["confidence_level"]
    assert result.missing_sources == tuple(expected["missing_sources"])
    assert result.main_reasons
    assert result.explanation_summary


def test_scoring_returns_unknown_without_evidence() -> None:
    result = score_risk((), now=datetime.fromisoformat("2026-04-29T00:00:00+00:00"))

    assert result.realtime_level == "未知"
    assert result.historical_level == "未知"
    assert result.confidence_level == "未知"


def test_overlapping_flood_potential_polygons_do_not_stack_to_extreme() -> None:
    signals = tuple(
        RiskEvidenceSignal(
            source_type="official",
            event_type="flood_potential",
            confidence=0.78,
            distance_to_query_m=0.0,
            freshness_score=1.0,
            source_weight=1.0,
        )
        for _ in range(31)
    )

    result = score_risk(signals, now=datetime.fromisoformat("2026-05-05T14:30:00+00:00"))

    assert result.historical_score == 40.0
    assert result.historical_level == "中"
    assert result.realtime_level == "未知"
    assert "情境參考" in result.main_reasons[0]


def _signal_from_fixture(payload: dict[str, object]) -> RiskEvidenceSignal:
    observed_at = payload.get("observed_at")
    return RiskEvidenceSignal(
        source_type=str(payload["source_type"]),
        event_type=str(payload["event_type"]),
        confidence=float(cast(Any, payload["confidence"])),
        distance_to_query_m=float(cast(Any, payload["distance_to_query_m"]))
        if payload.get("distance_to_query_m") is not None
        else None,
        freshness_score=float(cast(Any, payload["freshness_score"])),
        source_weight=float(cast(Any, payload["source_weight"])),
        risk_factor=float(cast(Any, payload.get("risk_factor", 1.0))),
        observed_at=datetime.fromisoformat(str(observed_at)) if observed_at else None,
    )
