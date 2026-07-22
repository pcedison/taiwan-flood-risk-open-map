from __future__ import annotations

import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts import hosted_source_freshness_smoke as smoke  # noqa: E402


FULL_OFFICIAL_BACKBONE = [
    "official.cwa.rainfall",
    "official.cwa.tide_level",
    "official.wra.water_level",
    "official.ncdr.cap",
    "official.wra_iow.flood_depth",
    "official.civil_iot.flood_sensor",
    "official.civil_iot.sewer_water_level",
    "official.civil_iot.pump_water_level",
    "official.civil_iot.gate_water_level",
]


def test_hosted_source_freshness_smoke_defaults_to_full_official_backbone(
    tmp_path: Path,
    monkeypatch,
) -> None:
    evidence_output = tmp_path / "source-freshness-smoke.json"

    monkeypatch.setenv("TEST_ADMIN_TOKEN", "secret-token")

    def fake_request_json(
        method: str,
        url: str,
        payload=None,
        *,
        headers: dict[str, str] | None = None,
        timeout_seconds: float,
    ) -> smoke.JsonResponse:
        del method, payload, headers, timeout_seconds
        if url.endswith("/health"):
            return smoke.JsonResponse(
                status_code=200,
                payload={
                    "status": "ok",
                    "version": "public-beta-mvp-2026-05-04",
                    "deployment_sha": "abc123",
                },
            )
        if url.endswith("/admin/v1/sources"):
            return smoke.JsonResponse(
                status_code=200,
                payload={"sources": [_source_payload(key) for key in FULL_OFFICIAL_BACKBONE]},
            )
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(smoke, "request_json", fake_request_json)

    result = smoke.main(
        [
            "--base-url",
            "https://example.test",
            "--admin-token-env",
            "TEST_ADMIN_TOKEN",
            "--captured-at",
            "2026-06-30T05:10:00+00:00",
            "--evidence-output",
            str(evidence_output),
        ]
    )

    assert result == 0
    evidence = json.loads(evidence_output.read_text(encoding="utf-8"))
    assert evidence["required_adapter_keys"] == FULL_OFFICIAL_BACKBONE
    assert [source["adapter_key"] for source in evidence["checked_sources"]] == (
        FULL_OFFICIAL_BACKBONE
    )


def test_hosted_source_freshness_smoke_writes_partial_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    evidence_output = tmp_path / "source-freshness-smoke.json"
    completion_output = tmp_path / "completion-evidence.json"
    seen_authorization_headers: list[str] = []

    monkeypatch.setenv("TEST_ADMIN_TOKEN", "secret-token")

    def fake_request_json(
        method: str,
        url: str,
        payload=None,
        *,
        headers: dict[str, str] | None = None,
        timeout_seconds: float,
    ) -> smoke.JsonResponse:
        del method, payload, timeout_seconds
        if url.endswith("/health"):
            return smoke.JsonResponse(
                status_code=200,
                payload={
                    "status": "ok",
                    "version": "public-beta-mvp-2026-05-04",
                    "deployment_sha": "abc123",
                },
            )
        if url.endswith("/admin/v1/sources"):
            seen_authorization_headers.append((headers or {}).get("Authorization", ""))
            return smoke.JsonResponse(status_code=200, payload=_sources_payload())
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(smoke, "request_json", fake_request_json)

    result = smoke.main(
        [
            "--base-url",
            "https://example.test",
            "--admin-token-env",
            "TEST_ADMIN_TOKEN",
            "--captured-at",
            "2026-06-30T05:10:00+00:00",
            "--required-adapter-key",
            "official.cwa.rainfall",
            "--required-adapter-key",
            "official.wra.water_level",
            "--evidence-output",
            str(evidence_output),
            "--completion-evidence-output",
            str(completion_output),
        ]
    )

    assert result == 0
    assert seen_authorization_headers == ["Bearer secret-token"]

    evidence = json.loads(evidence_output.read_text(encoding="utf-8"))
    assert evidence["schema_version"] == "hosted-source-freshness-smoke/v1"
    assert evidence["status"] == "passed"
    assert evidence["health"]["deployment_sha"] == "abc123"
    assert evidence["required_adapter_keys"] == [
        "official.cwa.rainfall",
        "official.wra.water_level",
    ]
    assert evidence["checked_sources"] == [
        {
            "adapter_key": "official.cwa.rainfall",
            "health_status": "healthy",
            "freshness_state": "fresh",
            "row_count": 7,
            "lag_seconds": 600,
            "latest_observed_at": "2026-06-30T04:50:00Z",
            "latest_ingested_at": "2026-06-30T04:56:00Z",
            "enabled_gates": ["data_sources.is_enabled", "SOURCE_CWA_API_ENABLED"],
        },
        {
            "adapter_key": "official.wra.water_level",
            "health_status": "degraded",
            "freshness_state": "degraded",
            "row_count": 3,
            "lag_seconds": 1400,
            "latest_observed_at": "2026-06-30T04:40:00Z",
            "latest_ingested_at": "2026-06-30T04:56:00Z",
            "enabled_gates": ["data_sources.is_enabled", "SOURCE_WRA_API_ENABLED"],
        },
    ]
    assert evidence["completion_evidence_targets"] == [
        {
            "gate_key": "hosted_worker_persisted_evidence",
            "status": "accepted",
            "satisfied_requirements": [
                "freshness_policy",
                "worker_persisted_evidence_path",
            ],
            "requirement_evidence": [
                {
                    "requirement": "freshness_policy",
                    "evidence_ref": f"{evidence_output}#/checked_sources",
                    "observed_at": "2026-06-30T05:10:00+00:00",
                },
                {
                    "requirement": "worker_persisted_evidence_path",
                    "evidence_ref": f"{evidence_output}#/checked_sources",
                    "observed_at": "2026-06-30T05:10:00+00:00",
                },
            ],
        }
    ]

    completion = json.loads(completion_output.read_text(encoding="utf-8"))
    assert completion == {
        "schema_version": "local-source-completion-evidence/v1",
        "captured_at": "2026-06-30T05:10:00+00:00",
        "signal_family_gap_evidence": [],
        "source_contract_evidence": [],
        "production_gate_evidence": [
            {
                "gate_key": "hosted_worker_persisted_evidence",
                "status": "accepted",
                "evidence_ref": str(evidence_output),
                "satisfied_requirements": [
                    "freshness_policy",
                    "worker_persisted_evidence_path",
                ],
                "requirement_evidence": [
                    {
                        "requirement": "freshness_policy",
                        "evidence_ref": f"{evidence_output}#/checked_sources",
                        "observed_at": "2026-06-30T05:10:00+00:00",
                    },
                    {
                        "requirement": "worker_persisted_evidence_path",
                        "evidence_ref": f"{evidence_output}#/checked_sources",
                        "observed_at": "2026-06-30T05:10:00+00:00",
                    },
                ],
            }
        ],
    }


def test_check_sources_rejects_missing_or_stale_required_source() -> None:
    payload = _sources_payload()
    payload["sources"][0]["freshness_state"] = "stale"
    payload["sources"][1]["row_count"] = 0

    failures = smoke.check_sources(
        payload,
        required_adapter_keys=("official.cwa.rainfall", "official.wra.water_level", "missing.adapter"),
    )

    assert "required source official.cwa.rainfall freshness_state is stale" in failures
    assert "required source official.wra.water_level row_count must be greater than 0" in failures
    assert "required source missing.adapter was not returned by /admin/v1/sources" in failures


def _sources_payload() -> dict:
    return {
        "sources": [
            _source_payload(
                "official.cwa.rainfall",
                row_count=7,
                lag_seconds=600,
                enabled_gates=["data_sources.is_enabled", "SOURCE_CWA_API_ENABLED"],
            ),
            _source_payload(
                "official.wra.water_level",
                health_status="degraded",
                freshness_state="degraded",
                row_count=3,
                lag_seconds=1400,
                observed_at="2026-06-30T04:40:00Z",
                enabled_gates=["data_sources.is_enabled", "SOURCE_WRA_API_ENABLED"],
            ),
        ]
    }


def _source_payload(
    adapter_key: str,
    *,
    health_status: str = "healthy",
    freshness_state: str = "fresh",
    row_count: int = 5,
    lag_seconds: int = 600,
    observed_at: str = "2026-06-30T04:50:00Z",
    enabled_gates: list[str] | None = None,
) -> dict:
    return {
        "id": adapter_key.replace(".", "-"),
        "name": adapter_key,
        "adapter_key": adapter_key,
        "source_type": "official",
        "license": "Government open data",
        "update_frequency": "PT10M",
        "health_status": health_status,
        "legal_basis": "L1",
        "is_enabled": True,
        "latest_observed_at": observed_at,
        "latest_fetched_at": "2026-06-30T04:55:00Z",
        "latest_ingested_at": "2026-06-30T04:56:00Z",
        "lag_seconds": lag_seconds,
        "row_count": row_count,
        "covered_counties": ["Tainan City"],
        "covered_county_count": 1,
        "fresh_county_count": 1 if freshness_state == "fresh" else 0,
        "stale_county_count": 0 if freshness_state == "fresh" else 1,
        "station_count_by_county": {"Tainan City": row_count},
        "missing_counties": [],
        "upstream_status": "succeeded",
        "enabled_gates": enabled_gates or ["data_sources.is_enabled"],
        "freshness_state": freshness_state,
    }
