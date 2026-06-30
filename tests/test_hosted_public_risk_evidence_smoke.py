from __future__ import annotations

import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts import hosted_public_risk_evidence_smoke as smoke  # noqa: E402


def test_hosted_public_risk_evidence_smoke_writes_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    evidence_output = tmp_path / "hosted-risk-smoke.json"
    completion_output = tmp_path / "completion-evidence.json"

    def fake_request_json(
        method: str,
        url: str,
        payload=None,
        *,
        timeout_seconds: float,
    ) -> smoke.JsonResponse:
        if url.endswith("/health"):
            return smoke.JsonResponse(
                status_code=200,
                payload={
                    "status": "ok",
                    "service": "flood-risk-api",
                    "version": "public-beta-mvp-2026-05-04",
                    "deployment_sha": "abc123",
                },
            )
        if url.endswith("/v1/risk/assess"):
            return smoke.JsonResponse(status_code=200, payload=_risk_payload())
        raise AssertionError(f"unexpected request {method} {url} {payload}")

    monkeypatch.setattr(smoke, "request_json", fake_request_json)

    result = smoke.main(
        [
            "--base-url",
            "https://example.test",
            "--lat",
            "23.01929",
            "--lng",
            "120.18726",
            "--radius-m",
            "500",
            "--location-text",
            "Tainan sample",
            "--captured-at",
            "2026-06-30T12:45:00+00:00",
            "--evidence-output",
            str(evidence_output),
            "--completion-evidence-output",
            str(completion_output),
        ]
    )

    assert result == 0
    evidence = json.loads(evidence_output.read_text(encoding="utf-8"))
    assert evidence["schema_version"] == "hosted-public-risk-evidence-smoke/v1"
    assert evidence["status"] == "passed"
    assert evidence["health"]["deployment_sha"] == "abc123"
    assert evidence["request"] == {
        "lat": 23.01929,
        "lng": 120.18726,
        "radius_m": 500,
        "location_text": "Tainan sample",
    }
    assert evidence["risk_assessment"]["assessment_id"] == "risk-1"
    assert evidence["risk_assessment"]["worker_evidence"] == {
        "freshness_source_ids": ["cwa-rainfall", "wra-water-level"],
        "official_evidence_event_types": ["rainfall", "water_level"],
    }
    assert evidence["risk_assessment"]["nearby_coverage"]["query_radius_m"] == 500
    assert set(evidence["risk_assessment"]["nearby_coverage"]["signal_types"]) >= {
        "rainfall",
        "water_level",
        "flood_depth",
        "sewer_water_level",
        "pump_or_gate_status",
    }
    assert evidence["completion_evidence_targets"] == [
        {
            "gate_key": "public_risk_worker_evidence_path",
            "status": "accepted",
            "satisfied_requirements": [
                "hosted_risk_response_worker_evidence_smoke",
                "query_point_nearby_coverage_smoke",
            ],
            "requirement_evidence": [
                {
                    "requirement": "hosted_risk_response_worker_evidence_smoke",
                    "evidence_ref": f"{evidence_output}#/risk_assessment/worker_evidence",
                    "observed_at": "2026-06-30T12:45:00+00:00",
                },
                {
                    "requirement": "query_point_nearby_coverage_smoke",
                    "evidence_ref": f"{evidence_output}#/risk_assessment/nearby_coverage",
                    "observed_at": "2026-06-30T12:45:00+00:00",
                },
            ],
        }
    ]

    completion = json.loads(completion_output.read_text(encoding="utf-8"))
    assert completion == {
        "schema_version": "local-source-completion-evidence/v1",
        "captured_at": "2026-06-30T12:45:00+00:00",
        "signal_family_gap_evidence": [],
        "source_contract_evidence": [],
        "production_gate_evidence": [
            {
                "gate_key": "public_risk_worker_evidence_path",
                "status": "accepted",
                "evidence_ref": str(evidence_output),
                "satisfied_requirements": [
                    "hosted_risk_response_worker_evidence_smoke",
                    "query_point_nearby_coverage_smoke",
                ],
                "requirement_evidence": [
                    {
                        "requirement": "hosted_risk_response_worker_evidence_smoke",
                        "evidence_ref": (
                            f"{evidence_output}#/risk_assessment/worker_evidence"
                        ),
                        "observed_at": "2026-06-30T12:45:00+00:00",
                    },
                    {
                        "requirement": "query_point_nearby_coverage_smoke",
                        "evidence_ref": (
                            f"{evidence_output}#/risk_assessment/nearby_coverage"
                        ),
                        "observed_at": "2026-06-30T12:45:00+00:00",
                    },
                ],
            }
        ],
    }


def test_check_risk_payload_requires_nearby_coverage_and_worker_evidence() -> None:
    payload = _risk_payload()
    del payload["nearby_realtime_coverage"]
    payload["evidence"] = []

    failures = smoke.check_risk_payload(payload, radius_m=500)

    assert "risk response missing nearby_realtime_coverage" in failures
    assert (
        "risk response did not include official rainfall or water_level evidence "
        "with observed_at and ingested_at"
    ) in failures


def _risk_payload() -> dict:
    return {
        "assessment_id": "risk-1",
        "realtime": {"level": "low"},
        "historical": {"level": "medium"},
        "confidence": {"level": "high"},
        "explanation": {"summary": "fixture"},
        "data_freshness": [
            {
                "source_id": "cwa-rainfall",
                "health_status": "healthy",
                "observed_at": "2026-06-30T04:30:00Z",
                "ingested_at": "2026-06-30T04:40:00Z",
            },
            {
                "source_id": "wra-water-level",
                "health_status": "healthy",
                "observed_at": "2026-06-30T04:20:00Z",
                "ingested_at": "2026-06-30T04:40:00Z",
            },
        ],
        "evidence": [
            {
                "source_type": "official",
                "event_type": "rainfall",
                "observed_at": "2026-06-30T04:30:00Z",
                "ingested_at": "2026-06-30T04:40:00Z",
                "distance_to_query_m": 1219.4,
                "confidence": 0.92,
                "url": "https://data.gov.tw/dataset/9177",
            },
            {
                "source_type": "official",
                "event_type": "water_level",
                "observed_at": "2026-06-30T04:20:00Z",
                "ingested_at": "2026-06-30T04:40:00Z",
                "distance_to_query_m": 2923.2,
                "confidence": 0.88,
                "url": "https://data.gov.tw/dataset/25768",
            },
        ],
        "nearby_realtime_coverage": {
            "overall_level": "low",
            "evaluated_at": "2026-06-30T04:40:00Z",
            "query_radius_m": 500,
            "radius_buckets_m": [500, 1000, 3000, 5000],
            "summary": "fixture coverage",
            "signal_breakdown": [
                _signal("rainfall", "no_local_sensor", 1216.8, 3),
                _signal("water_level", "low", 2928.0, 4),
                _signal("flood_depth", "no_local_sensor", 2321.2, 22),
                _signal("sewer_water_level", "low", 905.0, 54),
                _signal("pump_or_gate_status", "no_local_sensor", None, 0),
            ],
            "missing_signal_types": ["rainfall", "flood_depth"],
            "limitations": ["county-level coverage is not query-point coverage"],
            "county_level_note": "county-level coverage is not query-point coverage",
        },
    }


def _signal(
    signal_type: str,
    coverage_level: str,
    nearest_distance_m: float | None,
    count_5000m: int,
) -> dict:
    return {
        "signal_type": signal_type,
        "label": signal_type,
        "coverage_level": coverage_level,
        "nearest_distance_m": nearest_distance_m,
        "nearest_source_id": "station-1" if nearest_distance_m is not None else None,
        "nearest_observed_at": "2026-06-30T04:30:00Z"
        if nearest_distance_m is not None
        else None,
        "counts_by_radius_m": {"500": 0, "1000": 0, "3000": 1, "5000": count_5000m},
        "fresh_count": 1 if count_5000m else 0,
        "stale_count": 0,
        "status_only_count": 0,
        "missing_reason": None if count_5000m else "missing fixture",
    }
