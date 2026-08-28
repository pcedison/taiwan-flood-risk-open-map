from __future__ import annotations

import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts import hosted_public_risk_evidence_smoke as smoke  # noqa: E402


def test_default_radius_reaches_the_nearest_official_tainan_rainfall_station() -> None:
    assert smoke.DEFAULT_RADIUS_M == 2000


def test_canonical_production_freshness_source_ids_are_accepted() -> None:
    payload = _risk_payload()
    payload["data_freshness"][0]["source_id"] = "official.cwa.rainfall"
    payload["data_freshness"][1]["source_id"] = "official.wra.water_level"

    contract_failures, data_source_failures, state = smoke.check_risk_payload(
        payload, radius_m=500
    )

    assert contract_failures == []
    assert data_source_failures == []
    assert state == "configured"


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

    contract_failures, data_source_failures, _state = smoke.check_risk_payload(
        payload, radius_m=500
    )
    failures = contract_failures + data_source_failures

    assert "risk response missing nearby_realtime_coverage" in failures
    assert (
        "risk response did not include official rainfall or water_level evidence "
        "with observed_at and ingested_at"
    ) in failures


def test_check_risk_payload_accepts_zero_radius_counts_without_nearest_sensor() -> None:
    payload = _risk_payload()
    coverage = payload["nearby_realtime_coverage"]
    coverage["overall_level"] = "no_local_sensor"
    for signal in coverage["signal_breakdown"]:
        signal["coverage_level"] = "no_local_sensor"
        signal["nearest_source_id"] = None
        signal["nearest_distance_m"] = None
        signal["nearest_observed_at"] = None
        signal["counts_by_radius_m"] = {"500": 0, "1000": 0, "3000": 0, "5000": 0}
        signal["fresh_count"] = 0
        signal["missing_reason"] = "no nearby fixture"

    contract_failures, data_source_failures, _state = smoke.check_risk_payload(
        payload, radius_m=500
    )
    failures = contract_failures + data_source_failures

    assert (
        "nearby_realtime_coverage did not include nearest sensor context or radius counts"
        not in failures
    )
    assert failures == []


def test_check_risk_payload_requires_counts_when_nearest_sensor_missing() -> None:
    payload = _risk_payload()
    coverage = payload["nearby_realtime_coverage"]
    for signal in coverage["signal_breakdown"]:
        signal["nearest_source_id"] = None
        signal["nearest_distance_m"] = None
        signal.pop("counts_by_radius_m", None)

    contract_failures, data_source_failures, _state = smoke.check_risk_payload(
        payload, radius_m=500
    )
    failures = contract_failures + data_source_failures

    assert (
        "nearby_realtime_coverage did not include nearest sensor context or radius counts"
        in failures
    )


def test_check_risk_payload_rejects_unchecked_worker_source_health() -> None:
    payload = _risk_payload()
    coverage = payload["nearby_realtime_coverage"]
    coverage["source_health_checked"] = False
    coverage["source_health"] = []

    contract_failures, data_source_failures, _state = smoke.check_risk_payload(
        payload, radius_m=500
    )
    failures = contract_failures + data_source_failures

    assert (
        "nearby_realtime_coverage did not verify worker source health; "
        "request-time official observations are not worker persistence evidence"
        in failures
    )


def test_check_risk_payload_rejects_stalled_required_worker_source() -> None:
    payload = _risk_payload()
    coverage = payload["nearby_realtime_coverage"]
    coverage["source_health"][0].update(
        health_status="failed",
        reason_code="pipeline_stalled",
    )

    contract_failures, data_source_failures, _state = smoke.check_risk_payload(
        payload, radius_m=500
    )
    failures = contract_failures + data_source_failures

    assert (
        "required worker source cwa-source health is failed (pipeline_stalled)"
        in failures
    )


def test_disabled_redundant_cwa_warning_does_not_fail_required_source_health() -> None:
    payload = _risk_payload()
    payload["nearby_realtime_coverage"]["source_health"] = [
        {
            "source_id": "official.ncdr.cap",
            "name": "NCDR CAP",
            "health_status": "healthy",
            "reason_code": "operational",
            "required_for_absence": True,
        },
        {
            "source_id": "official.cwa.heavy_rain_warning",
            "name": "CWA heavy-rain warning",
            "health_status": "disabled",
            "reason_code": "source_disabled",
            "required_for_absence": False,
        },
    ]

    contract_failures, data_source_failures, _state = smoke.check_risk_payload(
        payload, radius_m=500
    )

    assert contract_failures == []
    assert data_source_failures == []


def test_degraded_ok_mode_still_fails_when_required_ncdr_stalls(
    tmp_path: Path,
    monkeypatch,
) -> None:
    payload = _risk_payload()
    payload["nearby_realtime_coverage"]["source_health"] = [
        {
            "source_id": "official.ncdr.cap",
            "name": "NCDR CAP",
            "health_status": "failed",
            "reason_code": "pipeline_stalled",
            "required_for_absence": True,
        },
        {
            "source_id": "official.cwa.heavy_rain_warning",
            "name": "CWA heavy-rain warning",
            "health_status": "disabled",
            "reason_code": "source_disabled",
            "required_for_absence": False,
        },
    ]

    exit_code, evidence, _completion_output = _run_smoke(tmp_path, monkeypatch, payload)

    assert exit_code == 1
    assert evidence["data_source_mode"] == "degraded-ok"
    assert any("official.ncdr.cap" in failure for failure in evidence["failures"])
    assert not any(
        "official.cwa.heavy_rain_warning" in failure for failure in evidence["failures"]
    )


def test_jurisdiction_repository_has_no_global_revision_predicate() -> None:
    repository = (
        REPO_ROOT / "apps" / "api" / "app" / "domain" / "evidence" / "repository.py"
    ).read_text(encoding="utf-8")
    query = repository.split("def query_realtime_jurisdiction_context(", 1)[1].split(
        "\ndef ", 1
    )[0]

    assert "proof.contract_mapping_revision = mapping.mapping_revision" in query
    assert "mapping.mapping_revision = '2026-08-24-v1-baseline'" not in query
    assert "proof.contract_mapping_revision\n                                = '" not in query


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
            "source_health_checked": True,
            "source_health_status": "healthy",
            "source_health": [
                {
                    "source_id": "cwa-source",
                    "name": "中央氣象署雨量觀測",
                    "health_status": "healthy",
                    "reason_code": "operational",
                    "required_for_absence": True,
                },
                {
                    "source_id": "wra-source",
                    "name": "經濟部水利署河川水位觀測",
                    "health_status": "degraded",
                    "reason_code": "worker_delayed",
                    "required_for_absence": True,
                },
            ],
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


def _unconfigured_risk_payload() -> dict:
    """A hosted response from a deployment with no official realtime source enabled.

    Mirrors the live https://floodrisk.cc response observed on 2026-08-27: the
    public contract is intact, but every official signal reports
    ``source_not_configured`` and no worker source health record exists.
    """

    payload = _risk_payload()
    payload["evidence"] = []
    payload["data_freshness"] = [
        {
            "source_id": "persisted-current-official",
            "name": "已保存官方即時資料",
            "health_status": "healthy",
            "observed_at": None,
            "ingested_at": None,
            "feature_count": 0,
            "message": None,
        },
        {
            "source_id": "persisted-historical",
            "name": "已保存歷史資料",
            "health_status": "healthy",
            "observed_at": None,
            "ingested_at": None,
            "feature_count": 0,
            "message": None,
        },
    ]
    coverage = payload["nearby_realtime_coverage"]
    coverage["overall_level"] = "no_local_sensor"
    coverage["source_health"] = []
    coverage["source_health_status"] = "unknown"
    coverage["source_health_checked"] = True
    for signal in coverage["signal_breakdown"]:
        signal["coverage_level"] = "no_local_sensor"
        signal["nearest_source_id"] = None
        signal["nearest_distance_m"] = None
        signal["nearest_observed_at"] = None
        signal["counts_by_radius_m"] = {"500": 0, "1000": 0, "3000": 0, "5000": 0}
        signal["fresh_count"] = 0
        signal["source_count"] = 0
        signal["failed_source_count"] = 0
        signal["source_health_status"] = "unknown"
        signal["missing_cause"] = "source_not_configured"
        signal["missing_reason"] = "雨量來源目前未啟用"
    return payload


def _run_smoke(tmp_path: Path, monkeypatch, payload: dict, *extra_args: str):
    evidence_output = tmp_path / "hosted-risk-smoke.json"
    completion_output = tmp_path / "completion-evidence.json"

    def fake_request_json(method, url, body=None, *, timeout_seconds):
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
            return smoke.JsonResponse(status_code=200, payload=payload)
        raise AssertionError(f"unexpected request {method} {url} {body}")

    monkeypatch.setattr(smoke, "request_json", fake_request_json)
    exit_code = smoke.main(
        [
            "--base-url",
            "https://example.test",
            "--radius-m",
            "500",
            "--captured-at",
            "2026-08-27T04:00:00+00:00",
            "--evidence-output",
            str(evidence_output),
            "--completion-evidence-output",
            str(completion_output),
            *extra_args,
        ]
    )
    evidence = json.loads(evidence_output.read_text(encoding="utf-8"))
    return exit_code, evidence, completion_output


def test_unconfigured_official_sources_are_reported_as_not_configured() -> None:
    assert (
        smoke.resolve_official_source_state(_unconfigured_risk_payload())
        == "not_configured"
    )


def test_enabled_official_sources_are_reported_as_configured() -> None:
    assert smoke.resolve_official_source_state(_risk_payload()) == "configured"


def test_degraded_ok_mode_does_not_fail_when_official_sources_are_off(
    tmp_path: Path,
    monkeypatch,
) -> None:
    exit_code, evidence, completion_output = _run_smoke(
        tmp_path, monkeypatch, _unconfigured_risk_payload()
    )

    assert exit_code == 0
    assert evidence["status"] == "degraded"
    assert evidence["official_source_state"] == "not_configured"
    assert evidence["data_source_mode"] == "degraded-ok"
    assert evidence["contract_failures"] == []
    assert evidence["failures"] == []
    assert evidence["degraded_notes"]
    # A degraded run must never claim the production gate is satisfied.
    assert evidence["completion_evidence_targets"][0]["status"] == "blocked"
    assert not completion_output.exists()


def test_strict_mode_still_fails_when_official_sources_are_off(
    tmp_path: Path,
    monkeypatch,
) -> None:
    exit_code, evidence, completion_output = _run_smoke(
        tmp_path,
        monkeypatch,
        _unconfigured_risk_payload(),
        "--data-source-mode",
        "strict",
    )

    assert exit_code == 1
    assert evidence["status"] == "failed"
    assert evidence["degraded_notes"] == []
    assert evidence["data_source_failures"]
    assert not completion_output.exists()


def test_degraded_ok_mode_still_fails_when_a_configured_source_stalls(
    tmp_path: Path,
    monkeypatch,
) -> None:
    payload = _risk_payload()
    payload["nearby_realtime_coverage"]["source_health"][0].update(
        health_status="failed",
        reason_code="pipeline_stalled",
    )

    exit_code, evidence, _completion_output = _run_smoke(tmp_path, monkeypatch, payload)

    assert exit_code == 1
    assert evidence["status"] == "failed"
    assert evidence["official_source_state"] == "configured"
    assert any("pipeline_stalled" in failure for failure in evidence["failures"])


def test_strict_mode_also_fails_when_a_configured_source_stalls(
    tmp_path: Path,
    monkeypatch,
) -> None:
    payload = _risk_payload()
    payload["nearby_realtime_coverage"]["source_health"][0].update(
        health_status="failed",
        reason_code="pipeline_stalled",
    )

    exit_code, evidence, _completion_output = _run_smoke(
        tmp_path,
        monkeypatch,
        payload,
        "--data-source-mode",
        "strict",
    )

    # A stalled source is a real outage, not a not-yet-enabled source. Neither
    # mode may excuse it, so degraded-ok is never the reason the run failed.
    assert exit_code == 1
    assert evidence["status"] == "failed"
    assert evidence["data_source_mode"] == "strict"
    assert evidence["official_source_state"] == "configured"
    assert evidence["degraded_notes"] == []
    assert any("pipeline_stalled" in failure for failure in evidence["failures"])


def test_contract_regression_fails_even_when_official_sources_are_off(
    tmp_path: Path,
    monkeypatch,
) -> None:
    payload = _unconfigured_risk_payload()
    payload.pop("assessment_id")

    exit_code, evidence, _completion_output = _run_smoke(tmp_path, monkeypatch, payload)

    assert exit_code == 1
    assert evidence["status"] == "failed"
    assert "risk response missing assessment_id" in evidence["contract_failures"]


def test_degraded_ok_mode_fails_when_the_jurisdiction_mapping_is_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # This is the state the live deployment was actually in: the sources are
    # switched on and ingesting, but a verified county resolves to zero reviewed
    # source mappings, so the API never reads the health table. Excusing that as
    # "sources are off" is exactly the masking the degraded path must not do.
    payload = _unconfigured_risk_payload()
    for signal in payload["nearby_realtime_coverage"]["signal_breakdown"]:
        signal["missing_cause"] = "jurisdiction_mapping_missing"
        signal["missing_reason"] = "本轄區的即時來源對應清單缺失"

    exit_code, evidence, completion_output = _run_smoke(tmp_path, monkeypatch, payload)

    assert exit_code == 1
    assert evidence["status"] == "failed"
    assert evidence["official_source_state"] != "not_configured"
    assert evidence["degraded_notes"] == []
    assert evidence["data_source_failures"]
    assert not completion_output.exists()
