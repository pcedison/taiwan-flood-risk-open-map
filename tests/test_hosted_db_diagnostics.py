from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import scripts.hosted_db_diagnostics as collector


def _diagnostics() -> dict[str, Any]:
    return {
        "captured_at": "2026-09-05T12:00:00Z",
        "sample_point": {"lat": 25.033, "lng": 121.5654, "radius_m": 500},
        "tables": [
            {
                "relname": "evidence",
                "n_live_tup": 1_112_891,
                "n_dead_tup": 402_118,
                "dead_tuple_ratio": 0.2654,
                "last_autovacuum": "2026-09-04T03:12:00Z",
                "total_relation_size_bytes": 1_819_680_768,
            },
            {
                "relname": "official_realtime_latest",
                "n_live_tup": 3_700,
                "n_dead_tup": 9,
                "dead_tuple_ratio": 0.0024,
                "last_autovacuum": "2026-09-05T01:00:00Z",
                "total_relation_size_bytes": 2_277_376,
            },
        ],
        "indexes": [
            {"relname": "evidence", "indexrelname": "evidence_pkey", "idx_scan": 11_262}
        ],
        "staging_status_counts": {
            "status": "ok",
            "method": "exact",
            "rows": [
                {
                    "validation_status": "rejected",
                    "rows": 11_600_000,
                    "oldest": "2026-06-13T00:00:00Z",
                    "newest": "2026-09-05T11:55:00Z",
                },
                {
                    "validation_status": "accepted",
                    "rows": 2_400_000,
                    "oldest": "2026-06-13T00:10:00Z",
                    "newest": "2026-09-05T11:55:00Z",
                },
            ],
            "error": None,
        },
        "staging_used_by_evidence_estimate": {
            "status": "ok",
            "method": "exact",
            "rows": 2_310_000,
            "index_name": "idx_evidence_staging_evidence_id",
            "error": None,
        },
        "query_plans": [
            {
                "name": "nearby_evidence",
                "status": "ok",
                "plan": [{"Plan": {"Node Type": "Limit"}, "Execution Time": 5624.1}],
                "error": None,
            },
            {
                "name": "coverage_supplement",
                "status": "timeout",
                "plan": None,
                "error": "timeout",
            },
        ],
        "statements": None,
    }


@pytest.fixture(autouse=True)
def _admin_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", "test-admin-token")


def _fake_response(
    monkeypatch: pytest.MonkeyPatch,
    *,
    status_code: int = 200,
    payload: dict[str, Any] | None = None,
    error: str | None = None,
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake_request_json(
        url: str, *, headers: dict[str, str] | None = None, timeout_seconds: float
    ) -> dict[str, Any]:
        calls.append({"url": url, "headers": headers, "timeout": timeout_seconds})
        return {
            "status_code": status_code,
            "payload": payload if payload is not None else {},
            "error": error,
        }

    monkeypatch.setattr(collector, "request_json", fake_request_json)
    return calls


def test_collects_diagnostics_and_writes_the_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _fake_response(monkeypatch, payload=_diagnostics())
    output = tmp_path / "hosted-db-diagnostics.json"

    exit_code = collector.main(
        ["--output", str(output), "--captured-at", "2026-09-05T12:00:00Z"]
    )

    assert exit_code == 0
    assert calls[0]["url"] == "https://floodrisk.cc/admin/v1/db-diagnostics"
    assert calls[0]["headers"]["Authorization"] == "Bearer test-admin-token"

    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence["schema_version"] == "hosted-db-diagnostics/v1"
    assert evidence["status"] == "collected"
    assert evidence["failures"] == []
    assert evidence["diagnostics"]["tables"][0]["relname"] == "evidence"
    summary = evidence["summary"]
    assert summary["tables"][0]["n_dead_tup"] == 402_118
    assert summary["index_count"] == 1
    assert summary["statements_available"] is False
    assert summary["staging_status_counts"]["method"] == "exact"
    assert summary["staging_used_by_evidence_estimate"]["rows"] == 2_310_000
    plans = {plan["name"]: plan for plan in summary["query_plans"]}
    assert plans["nearby_evidence"]["execution_time_ms"] == pytest.approx(5624.1)
    # A timed-out plan still appears in the summary, with no execution time.
    assert plans["coverage_supplement"]["status"] == "timeout"
    assert plans["coverage_supplement"]["execution_time_ms"] is None


def test_missing_admin_token_is_recorded_without_calling_the_endpoint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("ADMIN_BEARER_TOKEN", raising=False)

    def must_not_call(*args: object, **kwargs: object) -> None:
        raise AssertionError("the endpoint must not be called without a token")

    monkeypatch.setattr(collector, "request_json", must_not_call)
    output = tmp_path / "hosted-db-diagnostics.json"

    exit_code = collector.main(["--output", str(output)])

    assert exit_code == 1
    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence["status"] == "skipped"
    assert evidence["diagnostics"] is None
    assert "ADMIN_BEARER_TOKEN is not set" in evidence["failures"][0]


def test_http_error_is_recorded_as_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake_response(monkeypatch, status_code=503, error="Service Unavailable")
    output = tmp_path / "hosted-db-diagnostics.json"

    exit_code = collector.main(["--output", str(output)])

    assert exit_code == 1
    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence["status"] == "unavailable"
    assert evidence["status_code"] == 503
    assert "HTTP 503" in evidence["failures"][0]
    assert evidence["diagnostics"] is None


def test_unreachable_endpoint_is_recorded_rather_than_raised(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake_response(monkeypatch, status_code=0, error="timed out")
    output = tmp_path / "hosted-db-diagnostics.json"

    exit_code = collector.main(["--output", str(output)])

    assert exit_code == 1
    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence["status"] == "unavailable"
    assert "timed out" in evidence["failures"][0]


def test_custom_base_url_and_token_env_are_honoured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OTHER_TOKEN", "other-secret")
    calls = _fake_response(monkeypatch, payload=_diagnostics())
    output = tmp_path / "out.json"

    exit_code = collector.main(
        [
            "--base-url",
            "https://staging.example.test/",
            "--admin-token-env",
            "OTHER_TOKEN",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    assert calls[0]["url"] == "https://staging.example.test/admin/v1/db-diagnostics"
    assert calls[0]["headers"]["Authorization"] == "Bearer other-secret"


def test_summary_tolerates_a_payload_without_plans_or_tables() -> None:
    summary = collector.summarize({})

    assert summary == {
        "tables": [],
        "query_plans": [],
        "staging_status_counts": {},
        "staging_used_by_evidence_estimate": {},
        "index_count": 0,
        "statements_available": False,
    }
    assert collector.summary_lines(summary) == []


def test_summary_prints_the_staging_split_with_shares() -> None:
    lines = collector.summary_lines(collector.summarize(_diagnostics()))
    staging = [line for line in lines if line.startswith("STAGING ")]

    assert staging[0].startswith("STAGING rejected | rows=11600000 share=82.9%")
    assert "method=exact" in staging[0]
    assert "oldest=2026-06-13T00:00:00Z" in staging[0]
    assert staging[1].startswith("STAGING accepted | rows=2400000 share=17.1%")
    assert any(
        line.startswith("STAGING USED BY EVIDENCE | rows=2310000") for line in lines
    )


def test_summary_marks_an_estimated_staging_split_as_estimated() -> None:
    """A sampled estimate must never read as a count."""

    diagnostics = _diagnostics()
    diagnostics["staging_status_counts"] = {
        "status": "timeout",
        "method": "pg_stats_estimate",
        "rows": [
            {
                "validation_status": "rejected",
                "rows": 11_600_000,
                "oldest": None,
                "newest": None,
            }
        ],
        "error": "timeout",
    }
    lines = collector.summary_lines(collector.summarize(diagnostics))
    staging = next(line for line in lines if line.startswith("STAGING rejected"))

    assert "method=pg_stats_estimate" in staging
    assert "probe=timeout" in staging
    assert "oldest=None" in staging


def test_summary_reports_a_staging_section_that_returned_nothing() -> None:
    diagnostics = _diagnostics()
    diagnostics["staging_status_counts"] = {
        "status": "unavailable",
        "method": None,
        "rows": [],
        "error": "OperationalError",
    }
    lines = collector.summary_lines(collector.summarize(diagnostics))

    assert "STAGING STATUS | status=unavailable method=None rows=none" in lines


@pytest.mark.parametrize(
    "plan",
    [
        {"plan": None},
        {"plan": []},
        {"plan": ["not-an-object"]},
        {"plan": [{"Plan": {}}]},
        {},
    ],
)
def test_plan_execution_time_is_none_for_unusable_plans(plan: dict[str, Any]) -> None:
    assert collector.plan_execution_time_ms(plan) is None


def test_artifact_is_written_even_when_the_directory_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake_response(monkeypatch, payload=_diagnostics())
    output = tmp_path / "artifacts" / "nested" / "hosted-db-diagnostics.json"

    assert collector.main(["--output", str(output)]) == 0
    assert output.exists()
