from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SMOKE = REPO_ROOT / "scripts" / "runtime-smoke.ps1"
RUNTIME_SMOKE_RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "runtime-smoke.md"
WORKER_SCHEDULER_RUNBOOK = (
    REPO_ROOT / "docs" / "runbooks" / "worker-scheduler-deployment.md"
)
NATIONWIDE_PLAN = (
    REPO_ROOT
    / "docs"
    / "superpowers"
    / "plans"
    / "2026-06-30-nationwide-sensor-integration.md"
)


def test_runtime_smoke_disables_hosted_diagnostic_fallback() -> None:
    script = RUNTIME_SMOKE.read_text(encoding="utf-8")

    assert "Assert-HostedDiagnosticFallbackDisabled" in script
    assert "REALTIME_OFFICIAL_DIAGNOSTIC_FALLBACK_ENABLED=false" in script
    assert "Hosted diagnostic fallback guard" in script
    assert (
        "REALTIME_OFFICIAL_DIAGNOSTIC_FALLBACK_ENABLED must stay false during runtime smoke"
        in script
    )


def test_runtime_smoke_verifies_worker_persisted_latest_rows_by_adapter() -> None:
    script = RUNTIME_SMOKE.read_text(encoding="utf-8")

    assert "Checking worker-persisted official realtime latest rows" in script
    assert "official_realtime_latest" in script
    assert "official.wra.water_level" in script
    assert "latest_row_count" in script
    assert "fresh_ingested_count" in script
    assert "ingested_at >= smoke_started_at" in script
    assert "water_level_m IS NOT NULL" in script


def test_runtime_smoke_cleans_worker_persisted_latest_rows() -> None:
    script = RUNTIME_SMOKE.read_text(encoding="utf-8")

    assert "deleted_latest AS (" in script
    assert "DELETE FROM official_realtime_latest" in script
    assert "adapter_key IN (" in script


def test_runbooks_require_hosted_worker_persisted_evidence_before_claiming_ready() -> None:
    runtime_runbook = RUNTIME_SMOKE_RUNBOOK.read_text(encoding="utf-8")
    scheduler_runbook = WORKER_SCHEDULER_RUNBOOK.read_text(encoding="utf-8")

    assert "REALTIME_OFFICIAL_DIAGNOSTIC_FALLBACK_ENABLED=false" in runtime_runbook
    assert "official_realtime_latest" in runtime_runbook
    assert "worker-persisted latest rows" in runtime_runbook
    assert "worker-persisted evidence" in scheduler_runbook
    assert "do not use the API realtime bridge" in scheduler_runbook
    assert "official_realtime_latest" in scheduler_runbook


def test_nationwide_plan_marks_hosted_persistence_gate_complete() -> None:
    plan = NATIONWIDE_PLAN.read_text(encoding="utf-8")

    assert "- [x] Add runtime smoke assertions for `official_realtime_latest` row freshness by adapter." in plan
    assert "- [x] Add a hosted-mode guard assertion that `REALTIME_OFFICIAL_DIAGNOSTIC_FALLBACK_ENABLED` is not used during normal smoke." in plan
    assert "- [x] Document required evidence before claiming production readiness." in plan
