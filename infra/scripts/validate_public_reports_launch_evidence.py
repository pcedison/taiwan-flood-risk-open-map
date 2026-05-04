from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = (
    REPO_ROOT / "docs" / "runbooks" / "public-reports-launch-evidence.example.yaml"
)

SCHEMA_VERSION = "public-reports-launch-evidence/v1"

REQUIRED_TOP_LEVEL = {
    "launch_owner",
    "bot_defense",
    "moderation",
    "privacy",
    "operations",
}

PLACEHOLDER_TOKENS = (
    "placeholder",
    "replace-with",
    "replace_",
    "template-only",
    "template only",
    "not-run",
    "not run",
    "todo",
    "tbd",
    "example",
    "your-",
    "set-in",
    "missing",
    "<",
    ">",
)

TEMPLATE_OWNER_VALUES = {
    "abuse-owner",
    "governance-owner",
    "launch-owner",
    "moderation-backup-owner",
    "moderation-owner",
    "operations-owner",
    "owner",
    "privacy-governance-owner",
    "privacy-owner",
}

RUNBOOK_ONLY_EVIDENCE_PREFIXES = (
    "docs/",
    "./docs/",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate public reports launch governance evidence YAML/JSON."
    )
    parser.add_argument(
        "evidence_path",
        nargs="?",
        default=str(DEFAULT_EVIDENCE_PATH),
        help="Evidence YAML/JSON path. Defaults to the checked-in example template.",
    )
    parser.add_argument(
        "--production-complete",
        action="store_true",
        help=(
            "Require production_complete: true and reject template owners, "
            "placeholder refs, and runbook-only evidence."
        ),
    )
    args = parser.parse_args(argv)

    evidence_path = Path(args.evidence_path)
    errors = validate_evidence_file(
        evidence_path,
        require_production_complete=args.production_complete,
    )
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    try:
        display_path = evidence_path.resolve().relative_to(REPO_ROOT)
    except ValueError:
        display_path = evidence_path
    print(f"Public reports launch evidence valid: {display_path}")
    return 0


def validate_evidence_file(
    path: Path,
    *,
    require_production_complete: bool = False,
) -> list[str]:
    errors: list[str] = []
    evidence = _load_evidence(path, errors)
    if isinstance(evidence, dict):
        validate_evidence(
            evidence,
            errors,
            require_production_complete=require_production_complete,
        )
    return errors


def validate_evidence(
    evidence: dict[str, Any],
    errors: list[str],
    *,
    require_production_complete: bool = False,
) -> None:
    if evidence.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION!r}")

    production_complete = evidence.get("production_complete")
    if not isinstance(production_complete, bool):
        errors.append("production_complete must be true or false")
        production_complete = require_production_complete

    if require_production_complete and production_complete is not True:
        errors.append("production_complete must be true when --production-complete is used")

    production_acceptance = production_complete is True or require_production_complete
    expected_readiness_state = (
        "production-complete" if production_acceptance else "not-production-complete"
    )
    if evidence.get("readiness_state") != expected_readiness_state:
        errors.append(f"readiness_state must be {expected_readiness_state!r}")

    for field in sorted(REQUIRED_TOP_LEVEL):
        if field not in evidence:
            errors.append(f"{field} is required")

    _validate_timestamp(evidence.get("captured_at"), "captured_at", errors)
    _validate_owner(
        evidence.get("launch_owner"),
        "launch_owner",
        errors,
        production_acceptance=production_acceptance,
    )
    _validate_bot_defense(
        evidence.get("bot_defense"),
        errors,
        production_acceptance=production_acceptance,
    )
    _validate_moderation(
        evidence.get("moderation"),
        errors,
        production_acceptance=production_acceptance,
    )
    _validate_privacy(
        evidence.get("privacy"),
        errors,
        production_acceptance=production_acceptance,
    )
    _validate_operations(
        evidence.get("operations"),
        errors,
        production_acceptance=production_acceptance,
    )


def _load_evidence(path: Path, errors: list[str]) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"{path}: {exc}")
        return None

    try:
        if path.suffix.lower() == ".json":
            return json.loads(text)
        return yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        errors.append(f"{path}: {exc}")
        return None


def _validate_bot_defense(
    value: Any,
    errors: list[str],
    *,
    production_acceptance: bool,
) -> None:
    if not isinstance(value, dict):
        errors.append("bot_defense must be an object")
        return

    challenge = _require_object(value.get("challenge"), "bot_defense.challenge", errors)
    if challenge is not None:
        _validate_ref(
            challenge.get("provider"),
            "bot_defense.challenge.provider",
            errors,
            production_acceptance=production_acceptance,
        )
        _validate_ref(
            challenge.get("secret_storage_ref"),
            "bot_defense.challenge.secret_storage_ref",
            errors,
            production_acceptance=production_acceptance,
            require_production_secret=True,
        )

    rate_limit = _require_object(
        value.get("rate_limit_policy"),
        "bot_defense.rate_limit_policy",
        errors,
    )
    if rate_limit is not None:
        for field in ("backend", "max_requests", "window_seconds", "policy_ref"):
            if field not in rate_limit:
                errors.append(f"bot_defense.rate_limit_policy.{field} is required")
        if rate_limit.get("max_requests") is not None:
            _validate_positive_int(
                rate_limit.get("max_requests"),
                "bot_defense.rate_limit_policy.max_requests",
                errors,
            )
        if rate_limit.get("window_seconds") is not None:
            _validate_positive_int(
                rate_limit.get("window_seconds"),
                "bot_defense.rate_limit_policy.window_seconds",
                errors,
            )
        _validate_ref(
            rate_limit.get("backend"),
            "bot_defense.rate_limit_policy.backend",
            errors,
            production_acceptance=production_acceptance,
        )
        _validate_ref(
            rate_limit.get("policy_ref"),
            "bot_defense.rate_limit_policy.policy_ref",
            errors,
            production_acceptance=production_acceptance,
        )

    abuse_salt = _require_object(value.get("abuse_salt"), "bot_defense.abuse_salt", errors)
    if abuse_salt is not None:
        _validate_owner(
            abuse_salt.get("owner"),
            "bot_defense.abuse_salt.owner",
            errors,
            production_acceptance=production_acceptance,
        )
        _validate_ref(
            abuse_salt.get("secret_storage_ref"),
            "bot_defense.abuse_salt.secret_storage_ref",
            errors,
            production_acceptance=production_acceptance,
            require_production_secret=True,
        )


def _validate_moderation(
    value: Any,
    errors: list[str],
    *,
    production_acceptance: bool,
) -> None:
    if not isinstance(value, dict):
        errors.append("moderation must be an object")
        return

    _validate_positive_int(value.get("sla_minutes"), "moderation.sla_minutes", errors)
    _validate_owner(
        value.get("owner"),
        "moderation.owner",
        errors,
        production_acceptance=production_acceptance,
    )
    _validate_owner(
        value.get("backup_owner"),
        "moderation.backup_owner",
        errors,
        production_acceptance=production_acceptance,
    )
    _validate_ref(
        value.get("queue_review_ref"),
        "moderation.queue_review_ref",
        errors,
        production_acceptance=production_acceptance,
    )
    _validate_ref(
        value.get("escalation_ref"),
        "moderation.escalation_ref",
        errors,
        production_acceptance=production_acceptance,
    )


def _validate_privacy(
    value: Any,
    errors: list[str],
    *,
    production_acceptance: bool,
) -> None:
    if not isinstance(value, dict):
        errors.append("privacy must be an object")
        return

    for field in (
        "delete_redaction_procedure_ref",
        "retention_policy",
        "opt_out_takedown_path",
        "audit_log_review",
    ):
        _validate_ref(
            value.get(field),
            f"privacy.{field}",
            errors,
            production_acceptance=production_acceptance,
        )

    media = _require_object(value.get("media"), "privacy.media", errors)
    if media is None:
        return

    enabled = media.get("enabled")
    if not isinstance(enabled, bool):
        errors.append("privacy.media.enabled must be true or false")
        enabled = True

    if enabled:
        _validate_ref(
            media.get("exif_policy_ref"),
            "privacy.media.exif_policy_ref",
            errors,
            production_acceptance=production_acceptance,
        )
    else:
        _validate_ref(
            media.get("disabled_media_confirmation"),
            "privacy.media.disabled_media_confirmation",
            errors,
            production_acceptance=production_acceptance,
        )


def _validate_operations(
    value: Any,
    errors: list[str],
    *,
    production_acceptance: bool,
) -> None:
    if not isinstance(value, dict):
        errors.append("operations must be an object")
        return

    for field in ("dashboard_ref", "abuse_metrics_ref", "moderation_backlog_alert_ref"):
        _validate_ref(
            value.get(field),
            f"operations.{field}",
            errors,
            production_acceptance=production_acceptance,
        )
    _validate_owner(
        value.get("owner"),
        "operations.owner",
        errors,
        production_acceptance=production_acceptance,
    )
    _validate_ref(
        value.get("launch_decision_ref"),
        "operations.launch_decision_ref",
        errors,
        production_acceptance=production_acceptance,
    )


def _require_object(value: Any, field: str, errors: list[str]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        errors.append(f"{field} must be an object")
        return None
    return value


def _validate_owner(
    value: Any,
    field: str,
    errors: list[str],
    *,
    production_acceptance: bool,
) -> None:
    if not _non_empty_string(value):
        errors.append(f"{field} is required")
        return
    if production_acceptance and _is_placeholder_owner(value):
        errors.append(f"{field} must name a real production owner, not a template placeholder")


def _validate_ref(
    value: Any,
    field: str,
    errors: list[str],
    *,
    production_acceptance: bool,
    require_production_secret: bool = False,
) -> None:
    if not _non_empty_string(value):
        errors.append(f"{field} is required")
        return
    if not production_acceptance:
        return

    if _contains_placeholder(value):
        errors.append(f"{field} must not be a template placeholder")
    if _is_runbook_only_ref(value):
        errors.append(f"{field} must point to private production evidence, not only docs")
    if require_production_secret and not _looks_like_secret_storage_ref(value):
        errors.append(f"{field} must point to secret-manager or Zeabur secret storage")


def _validate_positive_int(value: Any, field: str, errors: list[str]) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        errors.append(f"{field} must be a positive integer")


def _validate_timestamp(value: Any, field: str, errors: list[str]) -> None:
    if isinstance(value, datetime):
        return
    if not _non_empty_string(value):
        errors.append(f"{field} is required")
        return
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{field} must be an ISO-8601 timestamp")


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _contains_placeholder(value: Any) -> bool:
    if not _non_empty_string(value):
        return False
    text = value.strip().lower()
    return any(token in text for token in PLACEHOLDER_TOKENS)


def _is_placeholder_owner(value: Any) -> bool:
    if not _non_empty_string(value):
        return False
    text = value.strip().lower()
    return (
        text in TEMPLATE_OWNER_VALUES
        or text.endswith("-owner")
        or _contains_placeholder(text)
    )


def _is_runbook_only_ref(value: Any) -> bool:
    if not _non_empty_string(value):
        return False
    text = value.strip().lower()
    return text.startswith(RUNBOOK_ONLY_EVIDENCE_PREFIXES)


def _looks_like_secret_storage_ref(value: Any) -> bool:
    if not _non_empty_string(value):
        return False
    text = value.strip().lower()
    return (
        text.startswith("zeabur-secret://")
        or text.startswith("zeabur://")
        or text.startswith("secret-manager://")
        or text.startswith("vault://")
        or text.startswith("aws-secretsmanager://")
        or text.startswith("gcp-secret-manager://")
        or text.startswith("azure-key-vault://")
    )


if __name__ == "__main__":
    raise SystemExit(main())
