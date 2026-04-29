"""Validate every contract example and fixture against its OpenAPI schema.

Catches drift between docs/api/openapi.yaml, packages/contracts/fixtures/*.json,
and inline `examples:` blocks. Run by CI after the OpenAPI spec validator.
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path
from typing import Any

import yaml

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from jsonschema import Draft202012Validator, RefResolver  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO_ROOT / "docs" / "api" / "openapi.yaml"
FIXTURES_DIR = REPO_ROOT / "packages" / "contracts" / "fixtures"

FIXTURE_SCHEMA_MAP: dict[str, str] = {
    "risk-assess-response.json": "RiskAssessmentResponse",
}


def schema_ref(spec: dict[str, Any], schema_name: str) -> dict[str, Any]:
    return {
        "$ref": f"#/components/schemas/{schema_name}",
        "components": spec["components"],
    }


def validate_payload(
    spec: dict[str, Any],
    schema_name: str,
    payload: Any,
    label: str,
) -> list[str]:
    schema = schema_ref(spec, schema_name)
    resolver = RefResolver.from_schema(schema)
    validator = Draft202012Validator(schema, resolver=resolver)
    return [
        f"{label} -> {schema_name}: "
        f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in validator.iter_errors(payload)
    ]


def collect_inline_example_failures(spec: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    for path, path_item in (spec.get("paths") or {}).items():
        for method, op in path_item.items():
            if not isinstance(op, dict):
                continue
            for status_code, response in (op.get("responses") or {}).items():
                content = (response.get("content") or {}).get("application/json")
                if not content:
                    continue
                schema_obj = content.get("schema") or {}
                ref = schema_obj.get("$ref")
                if not ref or not ref.startswith("#/components/schemas/"):
                    continue
                schema_name = ref.split("/")[-1]
                examples = content.get("examples") or {}
                for example_name, example_payload in examples.items():
                    payload = example_payload.get("value")
                    label = f"{method.upper()} {path} {status_code} example:{example_name}"
                    failures.extend(
                        validate_payload(spec, schema_name, payload, label)
                    )
    return failures


def collect_fixture_failures(spec: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if not FIXTURES_DIR.exists():
        return failures
    for filename, schema_name in FIXTURE_SCHEMA_MAP.items():
        fixture_path = FIXTURES_DIR / filename
        if not fixture_path.exists():
            failures.append(f"{filename}: fixture file missing")
            continue
        with fixture_path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        failures.extend(
            validate_payload(spec, schema_name, payload, f"fixture:{filename}")
        )
    return failures


def main() -> int:
    if not SPEC_PATH.exists():
        print(f"ERROR: OpenAPI spec not found at {SPEC_PATH}", file=sys.stderr)
        return 1
    with SPEC_PATH.open("r", encoding="utf-8") as fh:
        spec = yaml.safe_load(fh)

    failures = collect_inline_example_failures(spec) + collect_fixture_failures(spec)
    if failures:
        print(f"Contract fixture validation failed with {len(failures)} issue(s):", file=sys.stderr)
        for line in failures:
            print(f"  - {line}", file=sys.stderr)
        return 1

    print("All contract examples and fixtures conform to their OpenAPI schemas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
