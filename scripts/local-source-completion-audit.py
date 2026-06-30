#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
API_APP = ROOT / "apps" / "api"
sys.path.insert(0, str(API_APP))

from app.domain.realtime.local_source_action_plan import (  # noqa: E402
    build_local_source_action_plan,
)
from app.domain.realtime.local_source_coverage import (  # noqa: E402
    list_local_source_coverage,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Print the nationwide local-source completion audit. Optionally apply "
            "a private completion evidence JSON manifest."
        )
    )
    parser.add_argument(
        "--completion-evidence-json",
        help=(
            "Optional local-source-completion-evidence/v1 JSON file. The command "
            "prints only aggregate counts and gate status, not evidence refs. "
            "Production gates must include satisfied_requirements for each "
            "accepted requirement."
        ),
    )
    parser.add_argument(
        "--fail-on-incomplete",
        action="store_true",
        help="Exit with status 1 when the resulting completion audit is incomplete.",
    )
    args = parser.parse_args()

    completion_evidence = None
    if args.completion_evidence_json:
        completion_evidence = _load_json(Path(args.completion_evidence_json))

    plan = build_local_source_action_plan(
        list_local_source_coverage(),
        completion_evidence=completion_evidence,
    )
    audit = plan["completion_audit"]
    print(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True))

    if args.fail_on_incomplete and audit["overall_status"] != "satisfied":
        return 1
    return 0


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise SystemExit(f"{path}: completion evidence JSON must be an object")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
