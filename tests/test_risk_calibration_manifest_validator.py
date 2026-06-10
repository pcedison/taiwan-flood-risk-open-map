from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = REPO_ROOT / "infra" / "scripts" / "validate_risk_calibration_manifest.py"
EXAMPLE_PATH = REPO_ROOT / "docs" / "scoring" / "risk-calibration-manifest.example.yaml"


def _load_validator_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "validate_risk_calibration_manifest",
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


def _errors_for(manifest: dict[str, Any], *, production: bool = False) -> list[str]:
    validator = _load_validator_module()
    errors: list[str] = []
    validator.validate_manifest(
        manifest,
        errors,
        require_production_complete=production,
    )
    return errors


def test_example_manifest_template_is_valid() -> None:
    validator = _load_validator_module()

    assert validator.validate_manifest_file(EXAMPLE_PATH) == []


def test_production_complete_manifest_is_valid() -> None:
    manifest = _production_complete_manifest()

    assert _errors_for(manifest) == []
    assert _errors_for(manifest, production=True) == []


def test_missing_required_scenario_fails() -> None:
    manifest = copy.deepcopy(_load_example())
    manifest["fixtures"] = [
        fixture for fixture in manifest["fixtures"] if fixture["scenario"] != "stale_source"
    ]

    errors = _errors_for(manifest)

    assert "fixtures missing required scenarios: ['stale_source']" in errors


def test_unknown_fixture_path_fails() -> None:
    manifest = copy.deepcopy(_load_example())
    manifest["fixtures"][0]["fixture_path"] = "apps/api/tests/fixtures/scoring/missing.json"

    errors = _errors_for(manifest)

    assert any("does not exist" in error for error in errors)


def test_production_complete_rejects_runbook_only_source_ref() -> None:
    manifest = _production_complete_manifest()
    manifest["trusted_source_dependency"]["source_launch_evidence_ref"] = (
        "docs/runbooks/production-readiness-evidence.example.yaml#source_launch_gates"
    )

    errors = _errors_for(manifest)

    assert (
        "trusted_source_dependency.source_launch_evidence_ref must reference "
        "production evidence, not only docs"
    ) in errors


def test_production_complete_requires_empty_coverage_gaps() -> None:
    manifest = _production_complete_manifest()
    manifest["coverage_gaps"] = ["known no-event replay set still pending"]

    errors = _errors_for(manifest)

    assert "coverage_gaps must be empty when production_complete is true" in errors


def _production_complete_manifest() -> dict[str, Any]:
    manifest = copy.deepcopy(_load_example())
    manifest["production_complete"] = True
    manifest["readiness_state"] = "production-complete"
    manifest["calibration_status"] = "accepted"
    manifest["calibration_decision_ref"] = (
        "private-ops://risk-calibration/risk-v0.1.0/decision/2026-06-09"
    )
    manifest["trusted_source_dependency"] = {
        "p1_04_status": "accepted",
        "source_launch_evidence_ref": (
            "private-ops://risk-calibration/risk-v0.1.0/source-launch-gates/2026-06-09"
        ),
        "production_complete_required_before_weight_changes": True,
    }
    manifest["coverage_gaps"] = []
    for fixture in manifest["fixtures"]:
        fixture["source_basis_status"] = "accepted"
        fixture["trusted_evidence_refs"] = [
            f"private-ops://risk-calibration/{fixture['name']}/source-evidence/2026-06-09"
        ]
    return manifest
