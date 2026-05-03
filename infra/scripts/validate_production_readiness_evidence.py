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
    REPO_ROOT / "docs" / "runbooks" / "production-readiness-evidence.example.yaml"
)

SCHEMA_VERSION = "production-readiness-evidence/v1"

REQUIRED_ENV_NAMES = {
    "ABUSE_HASH_SALT",
    "APP_ENV",
    "ADMIN_BEARER_TOKEN",
    "DATABASE_URL",
    "REDIS_URL",
    "MINIO_ROOT_USER",
    "MINIO_ROOT_PASSWORD",
    "CWA_API_AUTHORIZATION",
    "WRA_API_TOKEN",
    "GRAFANA_ADMIN_PASSWORD",
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
    "SOURCE_TERMS_REVIEW_ACK",
    "SOURCE_SAMPLE_DATA_ENABLED",
    "USER_REPORTS_ENABLED",
    "USER_REPORTS_RATE_LIMIT_BACKEND",
    "USER_REPORTS_RATE_LIMIT_CLIENT_HEADER",
    "USER_REPORTS_RATE_LIMIT_ENABLED",
    "USER_REPORTS_RATE_LIMIT_MAX_REQUESTS",
    "USER_REPORTS_RATE_LIMIT_WINDOW_SECONDS",
}

SECRET_ENV_NAMES = {
    "ABUSE_HASH_SALT",
    "ADMIN_BEARER_TOKEN",
    "DATABASE_URL",
    "REDIS_URL",
    "MINIO_ROOT_USER",
    "MINIO_ROOT_PASSWORD",
    "CWA_API_AUTHORIZATION",
    "WRA_API_TOKEN",
    "GRAFANA_ADMIN_PASSWORD",
}

PRODUCTION_GATES = {
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
    "SOURCE_TERMS_REVIEW_ACK",
    "SOURCE_SAMPLE_DATA_ENABLED",
    "USER_REPORTS_ENABLED",
}

SLO_NAMES = {
    "API availability",
    "Source freshness",
    "Worker heartbeat",
    "Scheduler heartbeat",
    "Queue visibility",
    "Backup restore",
}

ALERT_FAMILIES = {
    "API readiness",
    "Source freshness",
    "Worker heartbeat/last run",
    "Scheduler heartbeat",
    "Runtime queue rows",
    "Backup/restore drill",
}

DRILL_NAMES = {
    "on-call drill",
    "rollback drill",
    "backup restore drill",
}

REQUIRED_GAP_FRAGMENTS = {
    "real Zeabur env",
    "real Zeabur secrets",
    "on-call drill",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate production readiness evidence YAML/JSON."
    )
    parser.add_argument(
        "evidence_path",
        nargs="?",
        default=str(DEFAULT_EVIDENCE_PATH),
        help="Evidence YAML/JSON path. Defaults to the checked-in example template.",
    )
    args = parser.parse_args(argv)

    evidence_path = Path(args.evidence_path)
    errors = validate_evidence_file(evidence_path)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    try:
        display_path = evidence_path.resolve().relative_to(REPO_ROOT)
    except ValueError:
        display_path = evidence_path
    print(f"Production readiness evidence valid: {display_path}")
    return 0


def validate_evidence_file(path: Path) -> list[str]:
    errors: list[str] = []
    evidence = _load_evidence(path, errors)
    if isinstance(evidence, dict):
        validate_evidence(evidence, errors)
    return errors


def validate_evidence(evidence: dict[str, Any], errors: list[str]) -> None:
    if evidence.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION!r}")

    if evidence.get("production_complete") is not False:
        errors.append("production_complete must be false until real production evidence exists")

    readiness_state = evidence.get("readiness_state")
    if readiness_state != "not-production-complete":
        errors.append("readiness_state must be 'not-production-complete'")

    _validate_environment(evidence.get("environment"), errors)
    _validate_required_env(evidence.get("required_env"), errors)
    _validate_slos(evidence.get("slos"), errors)
    _validate_alert_routing(evidence.get("alert_routing"), errors)
    _validate_runbook_drills(evidence.get("runbook_drills"), errors)
    _validate_pending_gaps(evidence.get("pending_production_gaps"), errors)


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


def _validate_environment(value: Any, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("environment must be an object")
        return

    if value.get("provider") != "zeabur":
        errors.append("environment.provider must be 'zeabur'")
    for key in ("project", "deployment_sha", "captured_at"):
        if not _non_empty_string(value.get(key)):
            errors.append(f"environment.{key} is required")
    _validate_timestamp(value.get("captured_at"), "environment.captured_at", errors)


def _validate_required_env(value: Any, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append("required_env must be a list")
        return

    entries = _index_named_entries(value, "required_env", errors)
    missing = REQUIRED_ENV_NAMES - set(entries)
    if missing:
        errors.append(f"required_env missing names: {sorted(missing)}")

    for name, entry in entries.items():
        owner = entry.get("owner")
        if not _non_empty_string(owner):
            errors.append(f"required_env[{name}].owner is required")

        if name in SECRET_ENV_NAMES:
            _validate_secret_env_entry(name, entry, errors)
        if name in PRODUCTION_GATES and entry.get("expected_default") is not False:
            errors.append(f"required_env[{name}].expected_default must be false")


def _validate_secret_env_entry(name: str, entry: dict[str, Any], errors: list[str]) -> None:
    if entry.get("secret") is not True:
        errors.append(f"required_env[{name}].secret must be true")
    if "value" in entry or "value_preview" in entry:
        errors.append(f"required_env[{name}] must not contain secret values or previews")
    if not _non_empty_string(entry.get("secret_placeholder")):
        errors.append(f"required_env[{name}].secret_placeholder is required")
    if entry.get("value_status") not in {"placeholder-only", "stored-in-secret-manager"}:
        errors.append(
            f"required_env[{name}].value_status must be placeholder-only "
            "or stored-in-secret-manager"
        )


def _validate_slos(value: Any, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append("slos must be a list")
        return

    entries = _index_named_entries(value, "slos", errors)
    missing = SLO_NAMES - set(entries)
    if missing:
        errors.append(f"slos missing names: {sorted(missing)}")

    for name, entry in entries.items():
        for field in ("owner", "sli", "target"):
            if not _non_empty_string(entry.get(field)):
                errors.append(f"slos[{name}].{field} is required")


def _validate_alert_routing(value: Any, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append("alert_routing must be a list")
        return

    entries = _index_entries(value, "alert_family", "alert_routing", errors)
    missing = ALERT_FAMILIES - set(entries)
    if missing:
        errors.append(f"alert_routing missing families: {sorted(missing)}")

    for family, entry in entries.items():
        for field in ("primary_owner", "backup_owner", "route"):
            if not _non_empty_string(entry.get(field)):
                errors.append(f"alert_routing[{family}].{field} is required")


def _validate_runbook_drills(value: Any, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append("runbook_drills must be a list")
        return

    entries = _index_named_entries(value, "runbook_drills", errors)
    missing = DRILL_NAMES - set(entries)
    if missing:
        errors.append(f"runbook_drills missing names: {sorted(missing)}")

    for name, entry in entries.items():
        for field in ("operator", "result"):
            if not _non_empty_string(entry.get(field)):
                errors.append(f"runbook_drills[{name}].{field} is required")
        _validate_timestamp(entry.get("timestamp"), f"runbook_drills[{name}].timestamp", errors)
        refs = entry.get("evidence_refs")
        if not isinstance(refs, list) or not refs or not all(_non_empty_string(ref) for ref in refs):
            errors.append(f"runbook_drills[{name}].evidence_refs must be a non-empty list")


def _validate_pending_gaps(value: Any, errors: list[str]) -> None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        errors.append("pending_production_gaps must be a list of strings")
        return

    joined = "\n".join(value)
    for fragment in REQUIRED_GAP_FRAGMENTS:
        if fragment not in joined:
            errors.append(f"pending_production_gaps must mention {fragment!r}")


def _index_named_entries(
    value: list[Any],
    collection_name: str,
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    return _index_entries(value, "name", collection_name, errors)


def _index_entries(
    value: list[Any],
    key_field: str,
    collection_name: str,
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append(f"{collection_name}[{index}] must be an object")
            continue
        key = item.get(key_field)
        if not _non_empty_string(key):
            errors.append(f"{collection_name}[{index}].{key_field} is required")
            continue
        if key in entries:
            errors.append(f"{collection_name}[{key}] is duplicated")
        entries[key] = item
    return entries


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


if __name__ == "__main__":
    raise SystemExit(main())
