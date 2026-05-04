from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]


SCHEMA_VERSION = "gdelt-live-acceptance/v1"
DEFAULT_MINIMUM_CADENCE_SECONDS = 60

REQUIRED_FIELDS = {
    "schema_version",
    "production_complete",
    "readiness_state",
    "legal_source_approval_ref",
    "source_owner",
    "egress_owner",
    "rate_limit_policy",
    "cadence_seconds",
    "configured_minimum_cadence_seconds",
    "alert_owner",
    "alert_route",
    "production_persistence_evidence_ref",
    "rollback_kill_switch_ref",
    "last_dry_run_or_prod_candidate_evidence_ref",
}

PRODUCTION_REF_FIELDS = {
    "legal_source_approval_ref",
    "rate_limit_policy",
    "alert_route",
    "production_persistence_evidence_ref",
    "rollback_kill_switch_ref",
    "last_dry_run_or_prod_candidate_evidence_ref",
}

PRODUCTION_OWNER_FIELDS = {
    "source_owner",
    "egress_owner",
    "alert_owner",
}

PLACEHOLDER_TOKENS = (
    "placeholder",
    "replace-with",
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
    "pending",
    "<",
    ">",
)

TEMPLATE_OWNER_VALUES = {
    "alert-owner",
    "egress-owner",
    "governance-owner",
    "owner",
    "source-owner",
    "worker-owner",
}

RUNBOOK_ONLY_EVIDENCE_PREFIXES = (
    "docs/",
    "./docs/",
)


@dataclass(frozen=True)
class GdeltLiveAcceptanceResult:
    status: str
    production_complete: bool
    readiness_state: str | None
    errors: tuple[str, ...] = ()
    reason: str | None = None

    def as_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "network_allowed": False,
            "mode": "gdelt-live-acceptance",
            "production_complete": self.production_complete,
            "readiness_state": self.readiness_state,
        }
        if self.reason:
            payload["reason"] = self.reason
        if self.errors:
            payload["errors"] = list(self.errors)
        return payload


def validate_gdelt_live_acceptance_file(path: Path) -> GdeltLiveAcceptanceResult:
    errors: list[str] = []
    evidence = _load_evidence(path, errors)
    if not isinstance(evidence, dict):
        errors.append("evidence must be a YAML object")
        return _failed(errors)
    return validate_gdelt_live_acceptance(evidence)


def validate_gdelt_live_acceptance(evidence: dict[str, Any]) -> GdeltLiveAcceptanceResult:
    errors: list[str] = []

    missing = sorted(REQUIRED_FIELDS - set(evidence))
    if missing:
        errors.append(f"missing required fields: {missing}")

    if evidence.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION!r}")

    production_complete = evidence.get("production_complete")
    if not isinstance(production_complete, bool):
        errors.append("production_complete must be true or false")
        production_complete = False

    readiness_state = evidence.get("readiness_state")
    expected_readiness_state = (
        "production-complete" if production_complete else "not-production-complete"
    )
    if readiness_state != expected_readiness_state:
        errors.append(f"readiness_state must be {expected_readiness_state!r}")

    string_required_fields = REQUIRED_FIELDS - {
        "production_complete",
        "cadence_seconds",
        "configured_minimum_cadence_seconds",
    }
    for field in sorted(string_required_fields):
        if field in evidence and not _non_empty_string(evidence.get(field)):
            errors.append(f"{field} is required")

    cadence_seconds = _positive_int(
        evidence.get("cadence_seconds"),
        "cadence_seconds",
        errors,
    )
    configured_minimum = _positive_int(
        evidence.get("configured_minimum_cadence_seconds"),
        "configured_minimum_cadence_seconds",
        errors,
    )
    if configured_minimum is None:
        configured_minimum = DEFAULT_MINIMUM_CADENCE_SECONDS
    if cadence_seconds is not None and cadence_seconds < configured_minimum:
        errors.append(
            "cadence_seconds must be greater than or equal to "
            "configured_minimum_cadence_seconds"
        )

    if production_complete:
        for field in sorted(PRODUCTION_OWNER_FIELDS):
            if field in evidence:
                _validate_real_owner(evidence.get(field), field, errors)
        for field in sorted(PRODUCTION_REF_FIELDS):
            if field in evidence:
                _validate_production_evidence_ref(evidence.get(field), field, errors)

    if errors:
        return _failed(errors, production_complete=bool(production_complete), readiness_state=readiness_state)

    if production_complete:
        return GdeltLiveAcceptanceResult(
            status="succeeded",
            production_complete=True,
            readiness_state=readiness_state,
        )

    return GdeltLiveAcceptanceResult(
        status="skipped",
        production_complete=False,
        readiness_state=readiness_state,
        reason="not-production-complete",
    )


def render_gdelt_live_acceptance_json(result: GdeltLiveAcceptanceResult) -> str:
    return json.dumps(result.as_payload(), sort_keys=True)


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


def _positive_int(value: Any, field: str, errors: list[str]) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        errors.append(f"{field} must be a positive integer")
        return None
    if value < 1:
        errors.append(f"{field} must be a positive integer")
        return None
    return value


def _failed(
    errors: list[str],
    *,
    production_complete: bool = False,
    readiness_state: Any = None,
) -> GdeltLiveAcceptanceResult:
    return GdeltLiveAcceptanceResult(
        status="failed",
        production_complete=production_complete,
        readiness_state=readiness_state if isinstance(readiness_state, str) else None,
        errors=tuple(errors),
    )


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_real_owner(value: Any, field: str, errors: list[str]) -> None:
    if _is_placeholder_owner(value):
        errors.append(f"{field} must name a real owner, not a template placeholder")


def _validate_not_placeholder(value: Any, field: str, errors: list[str]) -> None:
    if _contains_placeholder(value):
        errors.append(f"{field} must not be a template placeholder")


def _validate_production_evidence_ref(value: Any, field: str, errors: list[str]) -> None:
    _validate_not_placeholder(value, field, errors)
    if _is_runbook_only_ref(value):
        errors.append(f"{field} must reference production evidence, not only runbook instructions")


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
    return value.strip().lower().startswith(RUNBOOK_ONLY_EVIDENCE_PREFIXES)
