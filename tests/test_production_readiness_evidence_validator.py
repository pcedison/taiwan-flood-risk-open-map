from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = REPO_ROOT / "infra" / "scripts" / "validate_production_readiness_evidence.py"
EXAMPLE_PATH = REPO_ROOT / "docs" / "runbooks" / "production-readiness-evidence.example.yaml"


def _load_validator_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "validate_production_readiness_evidence",
        VALIDATOR_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_example() -> dict[str, Any]:
    with EXAMPLE_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _errors_for(evidence: dict[str, Any]) -> list[str]:
    validator = _load_validator_module()
    errors: list[str] = []
    validator.validate_evidence(evidence, errors)
    return errors


def _production_errors_for(evidence: dict[str, Any]) -> list[str]:
    validator = _load_validator_module()
    errors: list[str] = []
    validator.validate_evidence(evidence, errors, require_production_complete=True)
    return errors


def test_example_evidence_template_is_valid() -> None:
    validator = _load_validator_module()

    assert validator.validate_evidence_file(EXAMPLE_PATH) == []


def test_missing_slo_owner_fails() -> None:
    evidence = copy.deepcopy(_load_example())
    evidence["slos"][0].pop("owner")

    errors = _errors_for(evidence)

    assert "slos[API availability].owner is required" in errors


def test_missing_secret_placeholder_fails() -> None:
    evidence = copy.deepcopy(_load_example())
    admin_token = next(
        item for item in evidence["required_env"] if item["name"] == "ADMIN_BEARER_TOKEN"
    )
    admin_token.pop("secret_placeholder")

    errors = _errors_for(evidence)

    assert "required_env[ADMIN_BEARER_TOKEN].secret_placeholder is required" in errors


def test_committed_secret_value_fails() -> None:
    evidence = copy.deepcopy(_load_example())
    database_url = next(item for item in evidence["required_env"] if item["name"] == "DATABASE_URL")
    database_url["value"] = "postgresql://flood_risk:real-secret@example/flood_risk"

    errors = _errors_for(evidence)

    assert "required_env[DATABASE_URL] must not contain secret values or previews" in errors


def test_missing_drill_timestamp_fails() -> None:
    evidence = copy.deepcopy(_load_example())
    drill = next(item for item in evidence["runbook_drills"] if item["name"] == "on-call drill")
    drill.pop("timestamp")

    errors = _errors_for(evidence)

    assert "runbook_drills[on-call drill].timestamp is required" in errors


def test_production_complete_evidence_is_valid() -> None:
    evidence = _production_complete_evidence()

    assert _errors_for(evidence) == []
    assert _production_errors_for(evidence) == []


def test_production_complete_flag_rejects_template() -> None:
    errors = _production_errors_for(copy.deepcopy(_load_example()))

    assert "production_complete must be true when --production-complete is used" in errors
    assert "readiness_state must be 'production-complete'" in errors


def test_production_complete_requires_secret_manager_status() -> None:
    evidence = _production_complete_evidence()
    admin_token = next(
        item for item in evidence["required_env"] if item["name"] == "ADMIN_BEARER_TOKEN"
    )
    admin_token["value_status"] = "placeholder-only"

    errors = _errors_for(evidence)

    assert (
        "required_env[ADMIN_BEARER_TOKEN].value_status must be "
        "stored-in-secret-manager when production_complete is true"
    ) in errors


def test_production_complete_rejects_placeholder_owner() -> None:
    evidence = _production_complete_evidence()
    app_env = next(item for item in evidence["required_env"] if item["name"] == "APP_ENV")
    app_env["owner"] = "platform-owner"

    errors = _errors_for(evidence)

    assert (
        "required_env[APP_ENV].owner must name a real production owner, "
        "not a template placeholder"
    ) in errors


def test_production_complete_rejects_placeholder_route() -> None:
    evidence = _production_complete_evidence()
    route = next(
        item for item in evidence["alert_routing"] if item["alert_family"] == "API readiness"
    )
    route["route"] = "incident-channel-placeholder"

    errors = _errors_for(evidence)

    assert "alert_routing[API readiness].route must not be a template placeholder" in errors


def test_production_complete_requires_reviewed_gate_status() -> None:
    evidence = _production_complete_evidence()
    source_gate = next(
        item for item in evidence["required_env"] if item["name"] == "SOURCE_CWA_ENABLED"
    )
    source_gate["status"] = "placeholder-only"

    errors = _errors_for(evidence)

    assert (
        "required_env[SOURCE_CWA_ENABLED].status must be accepted or reviewed "
        "when production_complete is true"
    ) in errors


def test_production_complete_requires_passed_drill_result() -> None:
    evidence = _production_complete_evidence()
    drill = next(item for item in evidence["runbook_drills"] if item["name"] == "rollback drill")
    drill["result"] = "template-only-not-run"

    errors = _errors_for(evidence)

    assert (
        "runbook_drills[rollback drill].result must be passed or succeeded "
        "when production_complete is true"
    ) in errors


def test_production_complete_rejects_runbook_only_drill_evidence() -> None:
    evidence = _production_complete_evidence()
    drill = next(
        item for item in evidence["runbook_drills"] if item["name"] == "backup restore drill"
    )
    drill["evidence_refs"] = ["docs/runbooks/backup-restore-drill.md"]

    errors = _errors_for(evidence)

    assert (
        "runbook_drills[backup restore drill].evidence_refs must include at least "
        "one production evidence reference, not only runbook instructions"
    ) in errors


def test_production_complete_rejects_runbook_only_runtime_smoke_ref() -> None:
    evidence = _production_complete_evidence()
    evidence["drill_preflight"]["runtime_smoke_ref"] = "docs/runbooks/runtime-smoke.md"

    errors = _errors_for(evidence)

    assert (
        "drill_preflight.runtime_smoke_ref must reference production evidence, "
        "not only runbook instructions"
    ) in errors


def test_production_complete_requires_rollback_target() -> None:
    evidence = _production_complete_evidence()
    evidence["drill_preflight"]["rollback"]["target"] = (
        "replace-with-known-good-zeabur-deployment-or-commit"
    )

    errors = _errors_for(evidence)

    assert "drill_preflight.rollback.target must not be a template placeholder" in errors


def test_production_complete_rejects_runbook_only_backup_restore_ref() -> None:
    evidence = _production_complete_evidence()
    evidence["drill_preflight"]["backup_restore_ref"] = (
        "docs/runbooks/backup-restore-drill.md"
    )

    errors = _errors_for(evidence)

    assert (
        "drill_preflight.backup_restore_ref must reference production evidence, "
        "not only runbook instructions"
    ) in errors


def test_production_complete_rejects_secret_value_as_secret_manager_ref() -> None:
    evidence = _production_complete_evidence()
    secret_ref = next(
        item
        for item in evidence["drill_preflight"]["secret_manager_refs"]
        if item["name"] == "DATABASE_URL"
    )
    secret_ref["ref"] = "postgresql://flood_risk:real-secret@example/flood_risk"

    errors = _errors_for(evidence)

    assert (
        "drill_preflight.secret_manager_refs[DATABASE_URL].ref must be a "
        "secret manager reference, not a secret value"
    ) in errors


def test_production_complete_requires_empty_pending_gaps() -> None:
    evidence = _production_complete_evidence()
    evidence["pending_production_gaps"] = ["alert routing drill still pending"]

    errors = _errors_for(evidence)

    assert "pending_production_gaps must be empty when production_complete is true" in errors


def _production_complete_evidence() -> dict[str, Any]:
    evidence = copy.deepcopy(_load_example())
    evidence["production_complete"] = True
    evidence["readiness_state"] = "production-complete"
    evidence["environment"]["project"] = "flood-risk-production-beta"
    evidence["environment"]["deployment_sha"] = "0123456789abcdef0123456789abcdef01234567"
    evidence["environment"]["captured_at"] = "2026-05-04T10:00:00+08:00"
    evidence["drill_preflight"] = {
        "schema_version": "production-readiness-drill-preflight/v1",
        "generated_at": "2026-05-04T10:05:00+08:00",
        "target_env": "production-beta",
        "commit_sha": "0123456789abcdef0123456789abcdef01234567",
        "operator": "drill-operator@flood-risk.internal",
        "alert_route_refs": {
            "API readiness": "pagerduty:flood-risk-api-readiness",
            "Source freshness": "pagerduty:flood-risk-source-freshness",
            "Worker heartbeat/last run": "pagerduty:flood-risk-worker-heartbeat",
            "Scheduler heartbeat": "pagerduty:flood-risk-scheduler-heartbeat",
            "Runtime queue rows": "pagerduty:flood-risk-runtime-queue",
            "Backup/restore drill": "pagerduty:flood-risk-backup-restore",
        },
        "drill_timestamps": {
            "on-call drill": "2026-05-04T10:10:00+08:00",
            "rollback drill": "2026-05-04T10:20:00+08:00",
            "backup restore drill": "2026-05-04T10:30:00+08:00",
        },
        "runtime_smoke_ref": "private-ops://drills/runtime-smoke/2026-05-04",
        "playwright_ref": "private-ops://drills/playwright/2026-05-04",
        "alert_test_ref": "private-ops://drills/alert-test/2026-05-04",
        "rollback": {
            "target": "fedcba9876543210fedcba9876543210fedcba98",
            "evidence_ref": "private-ops://drills/rollback/2026-05-04",
        },
        "backup_restore_ref": "private-ops://drills/backup-restore/2026-05-04",
        "secret_manager_refs": [
            {"name": name, "ref": f"zeabur://flood-risk-production-beta/env/{name}"}
            for name in {
                "ABUSE_HASH_SALT",
                "ADMIN_BEARER_TOKEN",
                "DATABASE_URL",
                "REDIS_URL",
                "MINIO_ROOT_USER",
                "MINIO_ROOT_PASSWORD",
                "CWA_API_AUTHORIZATION",
                "WRA_API_TOKEN",
                "GRAFANA_ADMIN_PASSWORD",
                "USER_REPORTS_CHALLENGE_SECRET_KEY",
                "USER_REPORTS_CHALLENGE_STATIC_TOKEN",
            }
        ],
    }

    for index, item in enumerate(evidence["required_env"], start=1):
        item["owner"] = f"env-owner-{index}@flood-risk.internal"
        item["evidence"] = f"private-ops://production-env-review/{item['name']}"
        if item["name"] in {
            "SOURCE_CWA_ENABLED",
            "SOURCE_WRA_ENABLED",
            "SOURCE_FLOOD_POTENTIAL_ENABLED",
            "SOURCE_CWA_API_ENABLED",
            "SOURCE_WRA_API_ENABLED",
            "SOURCE_FLOOD_POTENTIAL_GEOJSON_ENABLED",
            "SOURCE_NEWS_ENABLED",
            "SOURCE_FORUM_ENABLED",
            "SOURCE_PTT_ENABLED",
            "SOURCE_DCARD_ENABLED",
            "SOURCE_PTT_CANDIDATE_APPROVAL_ACK",
            "SOURCE_DCARD_CANDIDATE_APPROVAL_ACK",
            "SOURCE_TERMS_REVIEW_ACK",
            "SOURCE_SAMPLE_DATA_ENABLED",
            "GDELT_SOURCE_ENABLED",
            "GDELT_BACKFILL_ENABLED",
            "GDELT_PRODUCTION_INGESTION_ENABLED",
            "GDELT_PRODUCTION_APPROVAL_EVIDENCE_ACK",
            "USER_REPORTS_ENABLED",
            "USER_REPORTS_CHALLENGE_REQUIRED",
            "USER_REPORTS_CHALLENGE_NON_PRODUCTION_BYPASS",
            "NEXT_PUBLIC_BASEMAP_STYLE_URL",
            "NEXT_PUBLIC_BASEMAP_KIND",
            "NEXT_PUBLIC_BASEMAP_PMTILES_URL",
            "NEXT_PUBLIC_BASEMAP_RASTER_TILES",
            "NEXT_PUBLIC_BASEMAP_ATTRIBUTION",
        }:
            item["status"] = "reviewed"
        if item.get("secret") is True:
            item["value_status"] = "stored-in-secret-manager"
            item["secret_placeholder"] = "redacted"

    for index, item in enumerate(evidence["slos"], start=1):
        item["owner"] = f"slo-owner-{index}@flood-risk.internal"
        item["evidence_ref"] = f"private-ops://slo-review/{index}"

    for index, item in enumerate(evidence["alert_routing"], start=1):
        item["primary_owner"] = f"alert-primary-{index}@flood-risk.internal"
        item["backup_owner"] = f"alert-backup-{index}@flood-risk.internal"
        item["route"] = f"pagerduty:flood-risk-production-{index}"
        item["evidence_ref"] = f"private-ops://alert-routing-test/{index}"

    drill_refs = {
        "on-call drill": "private-ops://drills/on-call/2026-05-04",
        "rollback drill": "private-ops://drills/rollback/2026-05-04",
        "backup restore drill": "private-ops://drills/backup-restore/2026-05-04",
    }
    for index, item in enumerate(evidence["runbook_drills"], start=1):
        item["operator"] = f"drill-operator-{index}@flood-risk.internal"
        item["result"] = "passed"
        item["evidence_refs"] = [drill_refs[item["name"]]]
        item["blockers"] = []

    evidence["pending_production_gaps"] = []
    return evidence
