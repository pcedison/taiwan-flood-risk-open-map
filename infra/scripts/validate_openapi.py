"""Validate the project OpenAPI spec against the OpenAPI 3.1 meta-schema.

Used by CI as the Phase 0 acceptance gate "OpenAPI draft 可被驗證".
Exits non-zero on the first schema violation it finds.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from openapi_spec_validator import OpenAPIV31SpecValidator

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO_ROOT / "docs" / "api" / "openapi.yaml"


def main() -> int:
    if not SPEC_PATH.exists():
        print(f"ERROR: OpenAPI spec not found at {SPEC_PATH}", file=sys.stderr)
        return 1

    with SPEC_PATH.open("r", encoding="utf-8") as fh:
        spec = yaml.safe_load(fh)

    errors = list(OpenAPIV31SpecValidator(spec).iter_errors())
    if errors:
        print(f"OpenAPI spec at {SPEC_PATH} has {len(errors)} validation error(s):", file=sys.stderr)
        for err in errors:
            location = "/".join(str(p) for p in err.absolute_path) or "<root>"
            print(f"  - {location}: {err.message}", file=sys.stderr)
        return 1

    paths = len(spec.get("paths", {}))
    schemas = len(spec.get("components", {}).get("schemas", {}))
    print(f"OpenAPI 3.1 spec valid. paths={paths} schemas={schemas}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
