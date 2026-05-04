from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
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
    "NEXT_PUBLIC_BASEMAP_STYLE_URL",
    "NEXT_PUBLIC_BASEMAP_KIND",
    "NEXT_PUBLIC_BASEMAP_PMTILES_URL",
    "NEXT_PUBLIC_BASEMAP_RASTER_TILES",
    "NEXT_PUBLIC_BASEMAP_ATTRIBUTION",
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
    "GDELT_PRODUCTION_APPROVAL_EVIDENCE_PATH",
    "GDELT_PRODUCTION_APPROVAL_EVIDENCE_ACK",
    "GDELT_PRODUCTION_QUERIES",
    "GDELT_PRODUCTION_MAX_RECORDS_PER_QUERY",
    "GDELT_PRODUCTION_CADENCE_SECONDS",
    "USER_REPORTS_ENABLED",
    "USER_REPORTS_CHALLENGE_REQUIRED",
    "USER_REPORTS_CHALLENGE_PROVIDER",
    "USER_REPORTS_CHALLENGE_SECRET_KEY",
    "USER_REPORTS_CHALLENGE_STATIC_TOKEN",
    "USER_REPORTS_CHALLENGE_VERIFY_URL",
    "USER_REPORTS_CHALLENGE_TIMEOUT_SECONDS",
    "USER_REPORTS_CHALLENGE_NON_PRODUCTION_BYPASS",
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
    "USER_REPORTS_CHALLENGE_SECRET_KEY",
    "USER_REPORTS_CHALLENGE_STATIC_TOKEN",
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
}

PRODUCTION_REVIEWED_ENV_NAMES = PRODUCTION_GATES | {
    "NEXT_PUBLIC_BASEMAP_STYLE_URL",
    "NEXT_PUBLIC_BASEMAP_KIND",
    "NEXT_PUBLIC_BASEMAP_PMTILES_URL",
    "NEXT_PUBLIC_BASEMAP_RASTER_TILES",
    "NEXT_PUBLIC_BASEMAP_ATTRIBUTION",
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

PASSING_DRILL_RESULTS = {"passed", "succeeded"}
PRODUCTION_GATE_STATUSES = {"accepted", "reviewed"}

DEPLOYMENT_SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{7,40}$")

SECRET_MANAGER_REF_PREFIXES = (
    "1password://",
    "aws-secretsmanager://",
    "azure-keyvault://",
    "bitwarden://",
    "doppler://",
    "gcp-secret-manager://",
    "op://",
    "private-ops://",
    "secret-manager://",
    "vault://",
    "zeabur://",
)

SECRET_VALUE_PREFIXES = (
    "http://",
    "https://",
    "postgres://",
    "postgresql://",
    "redis://",
)

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
    "api-operator-owner",
    "backend-owner",
    "database-owner",
    "governance-owner",
    "observability-owner",
    "owner",
    "platform-owner",
    "privacy-governance-owner",
    "source-owner",
    "worker-owner",
}

RUNBOOK_ONLY_EVIDENCE_PREFIXES = (
    "docs/runbooks/",
)


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
    parser.add_argument(
        "--production-complete",
        action="store_true",
        help=(
            "Require production_complete: true and run production acceptance checks. "
            "The default mode still accepts the checked-in template."
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
    print(f"Production readiness evidence valid: {display_path}")
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

    readiness_state = evidence.get("readiness_state")
    expected_readiness_state = (
        "production-complete" if production_acceptance else "not-production-complete"
    )
    if readiness_state != expected_readiness_state:
        errors.append(f"readiness_state must be {expected_readiness_state!r}")

    _validate_environment(
        evidence.get("environment"),
        errors,
        production_acceptance=production_acceptance,
    )
    _validate_required_env(
        evidence.get("required_env"),
        errors,
        production_acceptance=production_acceptance,
    )
    _validate_slos(
        evidence.get("slos"),
        errors,
        production_acceptance=production_acceptance,
    )
    _validate_alert_routing(
        evidence.get("alert_routing"),
        errors,
        production_acceptance=production_acceptance,
    )
    _validate_drill_preflight(
        evidence.get("drill_preflight"),
        errors,
        production_acceptance=production_acceptance,
    )
    _validate_runbook_drills(
        evidence.get("runbook_drills"),
        errors,
        production_acceptance=production_acceptance,
    )
    _validate_pending_gaps(
        evidence.get("pending_production_gaps"),
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


def _validate_environment(
    value: Any,
    errors: list[str],
    *,
    production_acceptance: bool,
) -> None:
    if not isinstance(value, dict):
        errors.append("environment must be an object")
        return

    if value.get("provider") != "zeabur":
        errors.append("environment.provider must be 'zeabur'")
    for key in ("project", "deployment_sha", "captured_at"):
        if not _non_empty_string(value.get(key)):
            errors.append(f"environment.{key} is required")
    _validate_timestamp(value.get("captured_at"), "environment.captured_at", errors)

    if production_acceptance:
        _validate_not_placeholder(
            value.get("project"),
            "environment.project",
            errors,
        )
        deployment_sha = value.get("deployment_sha")
        _validate_not_placeholder(
            deployment_sha,
            "environment.deployment_sha",
            errors,
        )
        if _non_empty_string(deployment_sha) and not DEPLOYMENT_SHA_PATTERN.fullmatch(
            deployment_sha.strip()
        ):
            errors.append(
                "environment.deployment_sha must be a 7-40 character git commit SHA "
                "when production_complete is true"
            )


def _validate_required_env(
    value: Any,
    errors: list[str],
    *,
    production_acceptance: bool,
) -> None:
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
        elif production_acceptance:
            _validate_real_owner(owner, f"required_env[{name}].owner", errors)

        if name in SECRET_ENV_NAMES:
            _validate_secret_env_entry(
                name,
                entry,
                errors,
                production_acceptance=production_acceptance,
            )
        if name in PRODUCTION_GATES and entry.get("expected_default") is not False:
            errors.append(f"required_env[{name}].expected_default must be false")
        if production_acceptance and name in PRODUCTION_REVIEWED_ENV_NAMES:
            if entry.get("status") not in PRODUCTION_GATE_STATUSES:
                errors.append(
                    f"required_env[{name}].status must be accepted or reviewed "
                    "when production_complete is true"
                )


def _validate_secret_env_entry(
    name: str,
    entry: dict[str, Any],
    errors: list[str],
    *,
    production_acceptance: bool,
) -> None:
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
    if production_acceptance and entry.get("value_status") != "stored-in-secret-manager":
        errors.append(
            f"required_env[{name}].value_status must be stored-in-secret-manager "
            "when production_complete is true"
        )


def _validate_slos(
    value: Any,
    errors: list[str],
    *,
    production_acceptance: bool,
) -> None:
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
        if production_acceptance and _non_empty_string(entry.get("owner")):
            _validate_real_owner(entry.get("owner"), f"slos[{name}].owner", errors)


def _validate_alert_routing(
    value: Any,
    errors: list[str],
    *,
    production_acceptance: bool,
) -> None:
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
        if production_acceptance:
            for field in ("primary_owner", "backup_owner"):
                if _non_empty_string(entry.get(field)):
                    _validate_real_owner(
                        entry.get(field),
                        f"alert_routing[{family}].{field}",
                        errors,
                    )
            if _non_empty_string(entry.get("route")):
                _validate_not_placeholder(
                    entry.get("route"),
                    f"alert_routing[{family}].route",
                    errors,
                )


def _validate_drill_preflight(
    value: Any,
    errors: list[str],
    *,
    production_acceptance: bool,
) -> None:
    if value is None and not production_acceptance:
        return
    if not isinstance(value, dict):
        errors.append("drill_preflight must be an object")
        return

    if value.get("schema_version") not in (None, "production-readiness-drill-preflight/v1"):
        errors.append(
            "drill_preflight.schema_version must be "
            "'production-readiness-drill-preflight/v1'"
        )

    for field in ("target_env", "commit_sha", "operator"):
        if not _non_empty_string(value.get(field)):
            errors.append(f"drill_preflight.{field} is required")

    _validate_timestamp(
        value.get("generated_at"),
        "drill_preflight.generated_at",
        errors,
    )

    if production_acceptance:
        for field in ("target_env", "commit_sha", "operator"):
            if _non_empty_string(value.get(field)):
                _validate_not_placeholder(value.get(field), f"drill_preflight.{field}", errors)
        commit_sha = value.get("commit_sha")
        if _non_empty_string(commit_sha) and not DEPLOYMENT_SHA_PATTERN.fullmatch(
            commit_sha.strip()
        ):
            errors.append(
                "drill_preflight.commit_sha must be a 7-40 character git commit SHA "
                "when production_complete is true"
            )

    timestamps = value.get("drill_timestamps")
    if not isinstance(timestamps, dict):
        errors.append("drill_preflight.drill_timestamps must be an object")
    else:
        for name in DRILL_NAMES:
            _validate_timestamp(
                timestamps.get(name),
                f"drill_preflight.drill_timestamps[{name}]",
                errors,
            )

    alert_route_refs = value.get("alert_route_refs")
    if not isinstance(alert_route_refs, dict):
        errors.append("drill_preflight.alert_route_refs must be an object")
    else:
        missing = ALERT_FAMILIES - set(alert_route_refs)
        if missing:
            errors.append(f"drill_preflight.alert_route_refs missing families: {sorted(missing)}")
        if production_acceptance:
            for family in ALERT_FAMILIES:
                ref = alert_route_refs.get(family)
                if not _non_empty_string(ref):
                    errors.append(f"drill_preflight.alert_route_refs[{family}] is required")
                else:
                    _validate_not_placeholder(
                        ref,
                        f"drill_preflight.alert_route_refs[{family}]",
                        errors,
                    )

    for field in ("runtime_smoke_ref", "playwright_ref", "alert_test_ref", "backup_restore_ref"):
        if not _non_empty_string(value.get(field)):
            errors.append(f"drill_preflight.{field} is required")
        elif production_acceptance:
            _validate_not_placeholder(value.get(field), f"drill_preflight.{field}", errors)
            _validate_single_production_ref(
                value.get(field),
                f"drill_preflight.{field}",
                errors,
            )

    rollback = value.get("rollback")
    if not isinstance(rollback, dict):
        errors.append("drill_preflight.rollback must be an object")
    else:
        for field in ("target", "evidence_ref"):
            if not _non_empty_string(rollback.get(field)):
                errors.append(f"drill_preflight.rollback.{field} is required")
            elif production_acceptance:
                _validate_not_placeholder(
                    rollback.get(field),
                    f"drill_preflight.rollback.{field}",
                    errors,
                )
        if production_acceptance and _non_empty_string(rollback.get("evidence_ref")):
            _validate_single_production_ref(
                rollback.get("evidence_ref"),
                "drill_preflight.rollback.evidence_ref",
                errors,
            )

    _validate_secret_manager_refs(
        value.get("secret_manager_refs"),
        errors,
        production_acceptance=production_acceptance,
    )


def _validate_runbook_drills(
    value: Any,
    errors: list[str],
    *,
    production_acceptance: bool,
) -> None:
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
        if production_acceptance:
            if _non_empty_string(entry.get("operator")):
                _validate_not_placeholder(
                    entry.get("operator"),
                    f"runbook_drills[{name}].operator",
                    errors,
                )
            if entry.get("result") not in PASSING_DRILL_RESULTS:
                errors.append(
                    f"runbook_drills[{name}].result must be passed or succeeded "
                    "when production_complete is true"
                )
            if isinstance(refs, list) and refs and all(_non_empty_string(ref) for ref in refs):
                _validate_production_evidence_refs(refs, f"runbook_drills[{name}]", errors)
            blockers = entry.get("blockers")
            if blockers not in (None, []):
                errors.append(
                    f"runbook_drills[{name}].blockers must be empty "
                    "when production_complete is true"
                )


def _validate_pending_gaps(
    value: Any,
    errors: list[str],
    *,
    production_acceptance: bool,
) -> None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        errors.append("pending_production_gaps must be a list of strings")
        return

    if production_acceptance:
        if value:
            errors.append("pending_production_gaps must be empty when production_complete is true")
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


def _validate_real_owner(value: Any, field: str, errors: list[str]) -> None:
    if _is_placeholder_owner(value):
        errors.append(f"{field} must name a real production owner, not a template placeholder")


def _validate_not_placeholder(value: Any, field: str, errors: list[str]) -> None:
    if _contains_placeholder(value):
        errors.append(f"{field} must not be a template placeholder")


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


def _validate_production_evidence_refs(
    refs: list[Any],
    field: str,
    errors: list[str],
) -> None:
    for ref in refs:
        _validate_not_placeholder(ref, f"{field}.evidence_refs", errors)

    real_refs = [
        ref.strip()
        for ref in refs
        if _non_empty_string(ref)
        and not ref.strip().lower().startswith(RUNBOOK_ONLY_EVIDENCE_PREFIXES)
    ]
    if not real_refs:
        errors.append(
            f"{field}.evidence_refs must include at least one production evidence "
            "reference, not only runbook instructions"
        )


def _validate_single_production_ref(value: Any, field: str, errors: list[str]) -> None:
    if (
        _non_empty_string(value)
        and value.strip().lower().startswith(RUNBOOK_ONLY_EVIDENCE_PREFIXES)
    ):
        errors.append(
            f"{field} must reference production evidence, not only runbook instructions"
        )


def _validate_secret_manager_refs(
    value: Any,
    errors: list[str],
    *,
    production_acceptance: bool,
) -> None:
    if not isinstance(value, list):
        errors.append("drill_preflight.secret_manager_refs must be a list")
        return

    entries = _index_named_entries(value, "drill_preflight.secret_manager_refs", errors)
    unknown = set(entries) - SECRET_ENV_NAMES
    if unknown:
        errors.append(
            f"drill_preflight.secret_manager_refs unknown secret names: {sorted(unknown)}"
        )

    if production_acceptance:
        missing = SECRET_ENV_NAMES - set(entries)
        if missing:
            errors.append(
                f"drill_preflight.secret_manager_refs missing names: {sorted(missing)}"
            )

    for name, entry in entries.items():
        if "value" in entry or "value_preview" in entry:
            errors.append(
                f"drill_preflight.secret_manager_refs[{name}] must not contain "
                "secret values or previews"
            )
        ref = entry.get("ref")
        if not _non_empty_string(ref):
            errors.append(f"drill_preflight.secret_manager_refs[{name}].ref is required")
            continue
        if production_acceptance:
            _validate_not_placeholder(
                ref,
                f"drill_preflight.secret_manager_refs[{name}].ref",
                errors,
            )
            if not _is_secret_manager_ref(ref):
                errors.append(
                    f"drill_preflight.secret_manager_refs[{name}].ref must be a "
                    "secret manager reference, not a secret value"
                )


def _is_secret_manager_ref(value: Any) -> bool:
    if not _non_empty_string(value):
        return False
    text = value.strip().lower()
    if text.startswith(SECRET_VALUE_PREFIXES):
        return False
    return text.startswith(SECRET_MANAGER_REF_PREFIXES)


if __name__ == "__main__":
    raise SystemExit(main())
