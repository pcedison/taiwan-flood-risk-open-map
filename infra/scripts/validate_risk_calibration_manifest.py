from __future__ import annotations

import argparse
from pathlib import Path
import json
import sys
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST_PATH = REPO_ROOT / "docs" / "scoring" / "risk-calibration-manifest.example.yaml"
SCHEMA_VERSION = "risk-calibration-manifest/v1"

REQUIRED_TOP_LEVEL_FIELDS = {
    "schema_version",
    "production_complete",
    "readiness_state",
    "score_version",
    "calibration_status",
    "calibration_decision_ref",
    "trusted_source_dependency",
    "fixtures",
    "coverage_gaps",
}
REQUIRED_SCENARIOS = {
    "high_risk",
    "low_risk",
    "stale_source",
    "missing_data",
}
ALLOWED_SCENARIOS = REQUIRED_SCENARIOS | {
    "conflicting_signal",
    "historical_signal",
}
REQUIRED_FIXTURE_FIELDS = {
    "name",
    "fixture_path",
    "scenario",
    "calibration_role",
    "source_basis_status",
    "source_launch_gate_keys",
    "trusted_evidence_refs",
    "limitations",
}
PRODUCTION_CALIBRATION_STATUSES = {"calibrated", "accepted"}
PLACEHOLDER_TOKENS = (
    "placeholder",
    "replace-with",
    "template-only",
    "template only",
    "todo",
    "tbd",
    "example",
    "missing",
)
RUNBOOK_ONLY_EVIDENCE_PREFIXES = (
    "docs/",
    "./docs/",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate risk calibration manifest YAML.")
    parser.add_argument(
        "manifest_path",
        nargs="?",
        default=str(DEFAULT_MANIFEST_PATH),
        help="Manifest YAML path. Defaults to the checked-in example template.",
    )
    parser.add_argument(
        "--production-complete",
        action="store_true",
        help=(
            "Require production_complete: true and private calibration/source "
            "evidence. The default mode accepts the checked-in baseline template."
        ),
    )
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest_path)
    errors = validate_manifest_file(
        manifest_path,
        require_production_complete=args.production_complete,
    )
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    try:
        display_path = manifest_path.resolve().relative_to(REPO_ROOT)
    except ValueError:
        display_path = manifest_path
    print(f"Risk calibration manifest valid: {display_path}")
    return 0


def validate_manifest_file(
    path: Path,
    *,
    require_production_complete: bool = False,
) -> list[str]:
    errors: list[str] = []
    manifest = _load_yaml(path, errors)
    if isinstance(manifest, dict):
        validate_manifest(
            manifest,
            errors,
            require_production_complete=require_production_complete,
        )
    return errors


def validate_manifest(
    manifest: dict[str, Any],
    errors: list[str],
    *,
    require_production_complete: bool = False,
) -> None:
    missing = REQUIRED_TOP_LEVEL_FIELDS - set(manifest)
    if missing:
        errors.append(f"manifest missing fields: {sorted(missing)}")

    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION!r}")

    production_complete = manifest.get("production_complete")
    if not isinstance(production_complete, bool):
        errors.append("production_complete must be true or false")
        production_complete = require_production_complete
    if require_production_complete and production_complete is not True:
        errors.append("production_complete must be true when --production-complete is used")

    production_acceptance = production_complete is True or require_production_complete
    expected_state = "production-complete" if production_acceptance else "not-production-complete"
    if manifest.get("readiness_state") != expected_state:
        errors.append(f"readiness_state must be {expected_state!r}")

    score_version = manifest.get("score_version")
    if not _non_empty_string(score_version):
        errors.append("score_version is required")

    _validate_trusted_source_dependency(
        manifest.get("trusted_source_dependency"),
        errors,
        production_acceptance=production_acceptance,
    )
    _validate_calibration_decision(
        manifest,
        errors,
        production_acceptance=production_acceptance,
    )
    _validate_fixtures(
        manifest.get("fixtures"),
        str(score_version or ""),
        errors,
        production_acceptance=production_acceptance,
    )
    _validate_coverage_gaps(
        manifest.get("coverage_gaps"),
        errors,
        production_acceptance=production_acceptance,
    )


def _validate_trusted_source_dependency(
    value: Any,
    errors: list[str],
    *,
    production_acceptance: bool,
) -> None:
    if not isinstance(value, dict):
        errors.append("trusted_source_dependency must be an object")
        return

    for field in (
        "p1_04_status",
        "source_launch_evidence_ref",
        "production_complete_required_before_weight_changes",
    ):
        if field not in value:
            errors.append(f"trusted_source_dependency.{field} is required")

    if value.get("production_complete_required_before_weight_changes") is not True:
        errors.append(
            "trusted_source_dependency.production_complete_required_before_weight_changes "
            "must be true"
        )

    if not production_acceptance:
        return

    if value.get("p1_04_status") != "accepted":
        errors.append(
            "trusted_source_dependency.p1_04_status must be accepted when "
            "production_complete is true"
        )
    ref = value.get("source_launch_evidence_ref")
    if _non_empty_string(ref):
        _validate_private_evidence_ref(
            ref,
            "trusted_source_dependency.source_launch_evidence_ref",
            errors,
        )


def _validate_calibration_decision(
    manifest: dict[str, Any],
    errors: list[str],
    *,
    production_acceptance: bool,
) -> None:
    calibration_status = manifest.get("calibration_status")
    if not _non_empty_string(calibration_status):
        errors.append("calibration_status is required")

    decision_ref = manifest.get("calibration_decision_ref")
    if not _non_empty_string(decision_ref):
        errors.append("calibration_decision_ref is required")

    if not production_acceptance:
        return

    if calibration_status not in PRODUCTION_CALIBRATION_STATUSES:
        errors.append(
            "calibration_status must be calibrated or accepted when "
            "production_complete is true"
        )
    if _non_empty_string(decision_ref):
        _validate_private_evidence_ref(
            decision_ref,
            "calibration_decision_ref",
            errors,
        )


def _validate_fixtures(
    value: Any,
    score_version: str,
    errors: list[str],
    *,
    production_acceptance: bool,
) -> None:
    if not isinstance(value, list) or not value:
        errors.append("fixtures must be a non-empty list")
        return

    seen_names: set[str] = set()
    covered_scenarios: set[str] = set()
    for index, fixture in enumerate(value):
        if not isinstance(fixture, dict):
            errors.append(f"fixtures[{index}] must be an object")
            continue

        name = str(fixture.get("name", f"fixtures[{index}]"))
        if name in seen_names:
            errors.append(f"fixtures[{name}] is duplicated")
        seen_names.add(name)

        missing = REQUIRED_FIXTURE_FIELDS - set(fixture)
        if missing:
            errors.append(f"fixtures[{name}] missing fields: {sorted(missing)}")
            continue

        scenario = fixture.get("scenario")
        if scenario not in ALLOWED_SCENARIOS:
            errors.append(f"fixtures[{name}].scenario must be one of {sorted(ALLOWED_SCENARIOS)}")
        else:
            covered_scenarios.add(str(scenario))

        _validate_fixture_path(
            fixture.get("fixture_path"),
            score_version,
            errors,
            field=f"fixtures[{name}].fixture_path",
        )
        _validate_string_list(
            fixture.get("source_launch_gate_keys"),
            f"fixtures[{name}].source_launch_gate_keys",
            errors,
            allow_empty=True,
        )
        _validate_string_list(
            fixture.get("trusted_evidence_refs"),
            f"fixtures[{name}].trusted_evidence_refs",
            errors,
        )
        _validate_string_list(
            fixture.get("limitations"),
            f"fixtures[{name}].limitations",
            errors,
        )

        if production_acceptance:
            if fixture.get("source_basis_status") != "accepted":
                errors.append(
                    f"fixtures[{name}].source_basis_status must be accepted when "
                    "production_complete is true"
                )
            refs = fixture.get("trusted_evidence_refs")
            if isinstance(refs, list):
                for ref_index, ref in enumerate(refs):
                    _validate_private_evidence_ref(
                        ref,
                        f"fixtures[{name}].trusted_evidence_refs[{ref_index}]",
                        errors,
                    )

    missing_scenarios = REQUIRED_SCENARIOS - covered_scenarios
    if missing_scenarios:
        errors.append(f"fixtures missing required scenarios: {sorted(missing_scenarios)}")


def _validate_fixture_path(
    value: Any,
    score_version: str,
    errors: list[str],
    *,
    field: str,
) -> None:
    if not _non_empty_string(value):
        errors.append(f"{field} is required")
        return

    fixture_path = (REPO_ROOT / value).resolve()
    try:
        fixture_path.relative_to(REPO_ROOT)
    except ValueError:
        errors.append(f"{field} must stay inside the repository")
        return

    if not fixture_path.exists():
        errors.append(f"{field} does not exist: {value}")
        return

    try:
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{field} is not valid JSON: {exc}")
        return

    if not isinstance(fixture, dict):
        errors.append(f"{field} must point to a JSON object fixture")
        return
    expected = fixture.get("expected")
    if not isinstance(expected, dict):
        errors.append(f"{field} fixture expected block is required")
        return
    if score_version and expected.get("score_version") != score_version:
        errors.append(
            f"{field} score_version {expected.get('score_version')!r} does not "
            f"match manifest score_version {score_version!r}"
        )


def _validate_coverage_gaps(
    value: Any,
    errors: list[str],
    *,
    production_acceptance: bool,
) -> None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        errors.append("coverage_gaps must be a list of strings")
        return
    if production_acceptance and value:
        errors.append("coverage_gaps must be empty when production_complete is true")


def _validate_string_list(
    value: Any,
    field: str,
    errors: list[str],
    *,
    allow_empty: bool = False,
) -> None:
    if not isinstance(value, list) or not all(_non_empty_string(item) for item in value):
        errors.append(f"{field} must be a list of strings")
        return
    if not allow_empty and not value:
        errors.append(f"{field} must not be empty")


def _validate_private_evidence_ref(value: Any, field: str, errors: list[str]) -> None:
    if not _non_empty_string(value):
        errors.append(f"{field} is required")
        return
    text = value.strip().lower()
    if any(token in text for token in PLACEHOLDER_TOKENS):
        errors.append(f"{field} must not be a template placeholder")
    if text.startswith(RUNBOOK_ONLY_EVIDENCE_PREFIXES):
        errors.append(f"{field} must reference production evidence, not only docs")


def _load_yaml(path: Path, errors: list[str]) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        errors.append(f"{path}: {exc}")
        return None


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


if __name__ == "__main__":
    raise SystemExit(main())
