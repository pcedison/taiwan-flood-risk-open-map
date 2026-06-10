from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import sys
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SMOKE_PATH = REPO_ROOT / "scripts" / "event_public_value_smoke.py"

spec = importlib.util.spec_from_file_location("event_public_value_smoke", SMOKE_PATH)
assert spec is not None and spec.loader is not None
event_smoke = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = event_smoke
spec.loader.exec_module(event_smoke)


def test_event_sample_selection_is_deterministic_and_covers_all_counties() -> None:
    candidates = [
        event_smoke.CandidateLocation(
            query=f"{county}測試地點{index}-{duplicate}",
            source_key="test-source",
            source_label="test",
            county=county,
            expected_precision="admin_area",
            expected_lat=23.5 + index * 0.001 + duplicate * 0.0001,
            expected_lng=120.5 + index * 0.001 + duplicate * 0.0001,
            event_focus=event_smoke.event_focus_for_county(county),
        )
        for index, county in enumerate(event_smoke.TAIWAN_COUNTIES)
        for duplicate in range(8)
    ]

    first = event_smoke.select_event_samples(candidates, sample_size=100, seed="fixed-seed")
    second = event_smoke.select_event_samples(candidates, sample_size=100, seed="fixed-seed")

    assert [sample.query for sample in first] == [sample.query for sample in second]
    assert len(first) == 100
    assert {sample.county for sample in first} == set(event_smoke.TAIWAN_COUNTIES)
    assert sum(1 for sample in first if sample.event_focus == "core-alert") >= 30
    assert sum(1 for sample in first if sample.event_focus == "high-concern") >= 25


def test_simulated_heavy_rain_failure_rules_accept_visible_official_evidence() -> None:
    payload = {
        "realtime": {"level": "高"},
        "confidence": {"level": "中"},
        "evidence": [
            {"source_type": "official", "event_type": "rainfall"},
            {"source_type": "official", "event_type": "water_level"},
        ],
        "data_freshness": [
            {"source_id": "cwa-rainfall", "health_status": "healthy"},
            {"source_id": "wra-water-level", "health_status": "healthy"},
        ],
    }

    assert event_smoke.simulated_heavy_rain_failures(payload) == []


def test_simulated_heavy_rain_failure_rules_reject_false_reassurance() -> None:
    payload = {
        "realtime": {"level": "低"},
        "confidence": {"level": "未知"},
        "evidence": [{"source_type": "official", "event_type": "rainfall"}],
        "data_freshness": [
            {"source_id": "cwa-rainfall", "health_status": "healthy"},
            {"source_id": "wra-water-level", "health_status": "degraded"},
        ],
    }

    failures = event_smoke.simulated_heavy_rain_failures(payload)

    assert any("should produce high realtime risk" in failure for failure in failures)
    assert any("should produce medium/high confidence" in failure for failure in failures)
    assert any("water-level evidence" in failure for failure in failures)
    assert any("wra-water-level status should be healthy" in failure for failure in failures)


def test_report_interpretation_distinguishes_no_network_from_simulated_mode() -> None:
    no_network_result = _sample_result(
        realtime_level="未知",
        evidence_count=0,
        warnings=["risk response has no location-specific evidence"],
    )
    simulated_result = _sample_result(realtime_level="高", evidence_count=2)

    no_network = event_smoke.build_report_payload(
        [no_network_result],
        sample_size=100,
        seed="seed",
        mode="no-network",
    )
    simulated = event_smoke.build_report_payload(
        [simulated_result],
        sample_size=100,
        seed="seed",
        mode="simulated-heavy-rain",
    )

    assert no_network["interpretation"]["public_value_readiness"] == "local_candidate_honest_but_not_event_complete"
    assert simulated["interpretation"]["public_value_readiness"] == "simulated_official_signal_propagates"


def test_report_payload_can_pin_generated_at_for_reproducible_artifacts() -> None:
    generated_at = event_smoke.parse_generated_at("2026-06-10T10:00:00+08:00")

    payload = event_smoke.build_report_payload(
        [_sample_result()],
        sample_size=100,
        seed="seed",
        mode="no-network",
        generated_at=generated_at,
    )

    assert payload["generated_at"] == "2026-06-10T02:00:00+00:00"


def test_parse_generated_at_requires_timezone() -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="timezone offset"):
        event_smoke.parse_generated_at("2026-06-10T02:00:00")


def test_configure_event_mode_restores_realtime_fetcher_between_modes() -> None:
    original_fetcher = event_smoke.ORIGINAL_FETCH_OFFICIAL_REALTIME_BUNDLE

    event_smoke.configure_event_mode("simulated-heavy-rain")
    assert event_smoke.public_routes.fetch_official_realtime_bundle is event_smoke.simulated_heavy_rain_bundle
    assert event_smoke.public_routes._cached_nominatim_candidates("query", "address", 1) == ()

    event_smoke.configure_event_mode("no-network")
    assert event_smoke.public_routes.fetch_official_realtime_bundle is original_fetcher
    assert event_smoke.public_routes._cached_wikimedia_candidates("query", 1) == ()


def _sample_result(**overrides: Any) -> Any:
    values = {
        "index": 1,
        "query": "高雄市測試地點",
        "county": "高雄市",
        "source_label": "test",
        "event_focus": "core-alert",
        "geocode_status": 200,
        "geocode_name": "高雄市測試地點",
        "geocode_source": "test",
        "geocode_precision": "poi",
        "geocode_requires_confirmation": False,
        "geocode_distance_m": 0.0,
        "risk_status": 200,
        "realtime_level": "未知",
        "historical_level": "未知",
        "confidence_level": "未知",
        "evidence_count": 0,
        "freshness_count": 2,
        "source_health": {
            "cwa-rainfall": "healthy",
            "wra-water-level": "healthy",
        },
        "explanation_summary": "test summary",
        "missing_sources": [],
        "pass_checks": ["risk_explanation_visible"],
        "warnings": [],
        "failures": [],
    }
    values.update(overrides)
    return event_smoke.SampleResult(**values)
