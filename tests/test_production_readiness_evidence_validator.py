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
