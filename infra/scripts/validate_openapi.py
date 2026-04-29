"""Validate the project OpenAPI spec against the OpenAPI 3.1 meta-schema.

Used by CI as the Phase 0 acceptance gate "OpenAPI draft 可被驗證".
Exits non-zero on the first schema violation it finds.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml
from openapi_spec_validator import OpenAPIV31SpecValidator

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO_ROOT / "docs" / "api" / "openapi.yaml"
HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
ADMIN_PATH_PREFIX = "/admin/"


def iter_operations(spec: dict[str, Any]):
    for path, path_item in spec.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            yield path, method, operation


def validate_admin_auth_contract(spec: dict[str, Any]) -> list[str]:
    """Ensure admin endpoints cannot be added without auth/RBAC in the contract."""
    errors: list[str] = []
    security_schemes = spec.get("components", {}).get("securitySchemes", {})

    if "AdminBearerAuth" not in security_schemes:
        errors.append("components/securitySchemes/AdminBearerAuth is required for admin APIs")

    for path, method, operation in iter_operations(spec):
        if not path.startswith(ADMIN_PATH_PREFIX):
            continue

        location = f"{method.upper()} {path}"
        security = operation.get("security")
        if not isinstance(security, list) or not security:
            errors.append(f"{location}: admin operation must define non-empty operation-level security")
        elif not any(isinstance(requirement, dict) and "AdminBearerAuth" in requirement for requirement in security):
            errors.append(f"{location}: admin operation security must require AdminBearerAuth")

        required_roles = operation.get("x-required-roles")
        if not isinstance(required_roles, list) or "admin" not in required_roles:
            errors.append(f"{location}: admin operation must declare x-required-roles including admin")

        responses = operation.get("responses", {})
        for status_code in ("401", "403"):
            if status_code not in responses:
                errors.append(f"{location}: admin operation must document {status_code} response")

    return errors


def main() -> int:
    if not SPEC_PATH.exists():
        print(f"ERROR: OpenAPI spec not found at {SPEC_PATH}", file=sys.stderr)
        return 1

    with SPEC_PATH.open("r", encoding="utf-8") as fh:
        spec = yaml.safe_load(fh)

    errors = list(OpenAPIV31SpecValidator(spec).iter_errors())
    contract_errors = validate_admin_auth_contract(spec)
    if errors:
        print(f"OpenAPI spec at {SPEC_PATH} has {len(errors)} validation error(s):", file=sys.stderr)
        for err in errors:
            location = "/".join(str(p) for p in err.absolute_path) or "<root>"
            print(f"  - {location}: {err.message}", file=sys.stderr)
        return 1
    if contract_errors:
        print(
            f"OpenAPI spec at {SPEC_PATH} has {len(contract_errors)} admin auth contract error(s):",
            file=sys.stderr,
        )
        for err in contract_errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    paths = len(spec.get("paths", {}))
    schemas = len(spec.get("components", {}).get("schemas", {}))
    print(f"OpenAPI 3.1 spec valid. paths={paths} schemas={schemas}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
