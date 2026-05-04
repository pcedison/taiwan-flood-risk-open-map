from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = (
    REPO_ROOT / "infra" / "scripts" / "validate_public_reports_launch_evidence.py"
)
EXAMPLE_PATH = (
    REPO_ROOT / "docs" / "runbooks" / "public-reports-launch-evidence.example.yaml"
)


def _load_validator_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "validate_public_reports_launch_evidence",
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


def test_production_complete_evidence_is_valid() -> None:
    evidence = _production_complete_evidence()

    assert _errors_for(evidence) == []
    assert _production_errors_for(evidence) == []


def test_missing_challenge_secret_storage_fails() -> None:
    evidence = copy.deepcopy(_load_example())
    evidence["bot_defense"]["challenge"].pop("secret_storage_ref")

    errors = _errors_for(evidence)

    assert "bot_defense.challenge.secret_storage_ref is required" in errors


def test_production_complete_requires_challenge_secret_storage() -> None:
    evidence = _production_complete_evidence()
    evidence["bot_defense"]["challenge"]["secret_storage_ref"] = "docs/runbooks/public-reports-governance.md"

    errors = _errors_for(evidence)

    assert (
        "bot_defense.challenge.secret_storage_ref must point to private "
        "production evidence, not only docs"
    ) in errors
    assert (
        "bot_defense.challenge.secret_storage_ref must point to secret-manager "
        "or Zeabur secret storage"
    ) in errors


def test_production_complete_accepts_zeabur_secret_ref_alias() -> None:
    evidence = _production_complete_evidence()
    evidence["bot_defense"]["challenge"][
        "secret_storage_ref"
    ] = "zeabur://flood-risk-prod/env/USER_REPORTS_CHALLENGE_SECRET_KEY"

    errors = _errors_for(evidence)

    assert errors == []


def test_missing_sla_fails() -> None:
    evidence = copy.deepcopy(_load_example())
    evidence["moderation"].pop("sla_minutes")

    errors = _errors_for(evidence)

    assert "moderation.sla_minutes must be a positive integer" in errors


def test_placeholder_owner_fails_in_production_complete() -> None:
    evidence = _production_complete_evidence()
    evidence["moderation"]["owner"] = "moderation-owner"

    errors = _errors_for(evidence)

    assert (
        "moderation.owner must name a real production owner, not a template placeholder"
    ) in errors


def test_missing_media_policy_fails() -> None:
    evidence = copy.deepcopy(_load_example())
    evidence["privacy"]["media"].pop("disabled_media_confirmation")

    errors = _errors_for(evidence)

    assert "privacy.media.disabled_media_confirmation is required" in errors


def _production_complete_evidence() -> dict[str, Any]:
    evidence = copy.deepcopy(_load_example())
    evidence["production_complete"] = True
    evidence["readiness_state"] = "production-complete"
    evidence["captured_at"] = "2026-05-04T10:00:00+08:00"
    evidence["launch_owner"] = "launch.lead@flood-risk.internal"

    evidence["bot_defense"]["challenge"] = {
        "provider": "turnstile",
        "secret_storage_ref": "zeabur-secret://flood-risk-prod/USER_REPORTS_CHALLENGE_SECRET_KEY",
    }
    evidence["bot_defense"]["rate_limit_policy"] = {
        "backend": "redis",
        "max_requests": 12,
        "window_seconds": 60,
        "policy_ref": "private-ops://public-reports/rate-limit-review/2026-05-04",
    }
    evidence["bot_defense"]["abuse_salt"] = {
        "owner": "privacy.lead@flood-risk.internal",
        "secret_storage_ref": "zeabur-secret://flood-risk-prod/ABUSE_HASH_SALT",
    }

    evidence["moderation"] = {
        "sla_minutes": 45,
        "owner": "moderation.primary@flood-risk.internal",
        "backup_owner": "moderation.backup@flood-risk.internal",
        "queue_review_ref": "private-ops://public-reports/moderation-queue-drill/2026-05-04",
        "escalation_ref": "private-ops://public-reports/moderation-escalation/2026-05-04",
    }

    evidence["privacy"] = {
        "delete_redaction_procedure_ref": "private-ops://public-reports/privacy-redaction-drill/2026-05-04",
        "retention_policy": "private-ops://public-reports/retention-policy/2026-05-04",
        "opt_out_takedown_path": "private-ops://public-reports/takedown-path/2026-05-04",
        "audit_log_review": "private-ops://public-reports/audit-review/2026-05-04",
        "media": {
            "enabled": False,
            "disabled_media_confirmation": "private-ops://public-reports/media-disabled/2026-05-04",
        },
    }

    evidence["operations"] = {
        "owner": "ops.lead@flood-risk.internal",
        "dashboard_ref": "private-ops://public-reports/dashboard-review/2026-05-04",
        "abuse_metrics_ref": "private-ops://public-reports/abuse-metrics/2026-05-04",
        "moderation_backlog_alert_ref": "private-ops://public-reports/moderation-backlog-alert/2026-05-04",
        "launch_decision_ref": "private-ops://public-reports/launch-decision/2026-05-04",
    }
    return evidence
