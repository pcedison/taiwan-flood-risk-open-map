from __future__ import annotations

import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts import hosted_deployment_smoke as smoke  # noqa: E402


def test_hosted_deployment_smoke_writes_evidence_and_completion_overlay(
    tmp_path: Path,
    monkeypatch,
) -> None:
    evidence_output = tmp_path / "hosted-deployment-smoke.json"
    completion_output = tmp_path / "deployment-completion-evidence.json"

    def fake_request_json(url: str, *, timeout_seconds: float) -> smoke.JsonResponse:
        if url.endswith("/health"):
            return smoke.JsonResponse(
                status_code=200,
                payload={
                    "status": "ok",
                    "service": "flood-risk-api",
                    "deployment_sha": "abc123",
                },
            )
        if url.endswith("/ready"):
            return smoke.JsonResponse(
                status_code=200,
                payload={
                    "status": "ok",
                    "service": "flood-risk-api",
                    "deployment_sha": "abc123",
                    "dependencies": {
                        "database": {"status": "healthy"},
                        "redis": {"status": "healthy"},
                    },
                },
            )
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(smoke, "request_json", fake_request_json)

    result = smoke.main(
        [
            "--base-url",
            "https://example.test",
            "--expected-deployment-sha",
            "abc123",
            "--captured-at",
            "2026-06-30T14:20:00+08:00",
            "--evidence-output",
            str(evidence_output),
            "--completion-evidence-output",
            str(completion_output),
        ]
    )

    assert result == 0
    evidence = json.loads(evidence_output.read_text(encoding="utf-8"))
    assert evidence["schema_version"] == "hosted-deployment-smoke/v1"
    assert evidence["status"] == "passed"
    assert evidence["base_url"] == "https://example.test"
    assert evidence["expected_deployment_sha"] == "abc123"
    assert evidence["health"]["deployment_sha"] == "abc123"
    assert evidence["ready"]["deployment_sha"] == "abc123"
    assert evidence["ready"]["dependencies"] == {
        "database": "healthy",
        "redis": "healthy",
    }
    assert evidence["completion_evidence_targets"] == [
        {
            "gate_key": "production_deployment_evidence",
            "status": "accepted",
            "satisfied_requirements": [
                "main_branch_deployed_sha",
                "ready_dependency_smoke",
            ],
            "requirement_evidence": [
                {
                    "requirement": "main_branch_deployed_sha",
                    "evidence_ref": f"{evidence_output}#/health/deployment_sha",
                    "observed_at": "2026-06-30T14:20:00+08:00",
                },
                {
                    "requirement": "ready_dependency_smoke",
                    "evidence_ref": f"{evidence_output}#/ready/dependencies",
                    "observed_at": "2026-06-30T14:20:00+08:00",
                },
            ],
        }
    ]

    completion = json.loads(completion_output.read_text(encoding="utf-8"))
    assert completion == {
        "schema_version": "local-source-completion-evidence/v1",
        "captured_at": "2026-06-30T14:20:00+08:00",
        "signal_family_gap_evidence": [],
        "source_contract_evidence": [],
        "production_gate_evidence": [
            {
                "gate_key": "production_deployment_evidence",
                "status": "accepted",
                "evidence_ref": str(evidence_output),
                "satisfied_requirements": [
                    "main_branch_deployed_sha",
                    "ready_dependency_smoke",
                ],
                "requirement_evidence": [
                    {
                        "requirement": "main_branch_deployed_sha",
                        "evidence_ref": f"{evidence_output}#/health/deployment_sha",
                        "observed_at": "2026-06-30T14:20:00+08:00",
                    },
                    {
                        "requirement": "ready_dependency_smoke",
                        "evidence_ref": f"{evidence_output}#/ready/dependencies",
                        "observed_at": "2026-06-30T14:20:00+08:00",
                    },
                ],
            }
        ],
    }


def test_hosted_deployment_smoke_fails_when_ready_sha_differs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    evidence_output = tmp_path / "hosted-deployment-smoke.json"

    def fake_request_json(url: str, *, timeout_seconds: float) -> smoke.JsonResponse:
        if url.endswith("/health"):
            return smoke.JsonResponse(
                status_code=200,
                payload={"status": "ok", "deployment_sha": "abc123"},
            )
        if url.endswith("/ready"):
            return smoke.JsonResponse(
                status_code=200,
                payload={
                    "status": "ok",
                    "deployment_sha": "old-sha",
                    "dependencies": {
                        "database": {"status": "healthy"},
                        "redis": {"status": "healthy"},
                    },
                },
            )
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(smoke, "request_json", fake_request_json)

    result = smoke.main(
        [
            "--base-url",
            "https://example.test",
            "--expected-deployment-sha",
            "abc123",
            "--captured-at",
            "2026-06-30T14:25:00+08:00",
            "--evidence-output",
            str(evidence_output),
        ]
    )

    assert result == 1
    evidence = json.loads(evidence_output.read_text(encoding="utf-8"))
    assert evidence["status"] == "failed"
    assert "ready deployment_sha old-sha did not match expected abc123" in evidence[
        "failures"
    ]


def test_hosted_deployment_smoke_retries_until_deployed_sha_matches(
    tmp_path: Path,
    monkeypatch,
) -> None:
    evidence_output = tmp_path / "hosted-deployment-smoke.json"
    calls: list[str] = []

    def fake_request_json(url: str, *, timeout_seconds: float) -> smoke.JsonResponse:
        del timeout_seconds
        calls.append(url)
        attempt = (len(calls) + 1) // 2
        deployment_sha = "old-sha" if attempt == 1 else "abc123"
        payload = {
            "status": "ok",
            "service": "flood-risk-api",
            "deployment_sha": deployment_sha,
        }
        if url.endswith("/ready"):
            payload["dependencies"] = {
                "database": {"status": "healthy"},
                "redis": {"status": "healthy"},
            }
        return smoke.JsonResponse(status_code=200, payload=payload)

    monkeypatch.setattr(smoke, "request_json", fake_request_json)

    result = smoke.main(
        [
            "--base-url",
            "https://example.test",
            "--expected-deployment-sha",
            "abc123",
            "--captured-at",
            "2026-07-01T14:10:00+08:00",
            "--retry-count",
            "2",
            "--retry-delay-seconds",
            "0",
            "--evidence-output",
            str(evidence_output),
        ]
    )

    assert result == 0
    assert calls == [
        "https://example.test/health",
        "https://example.test/ready",
        "https://example.test/health",
        "https://example.test/ready",
    ]
    evidence = json.loads(evidence_output.read_text(encoding="utf-8"))
    assert evidence["status"] == "passed"
    assert evidence["attempt_count"] == 2
    assert evidence["health"]["deployment_sha"] == "abc123"
