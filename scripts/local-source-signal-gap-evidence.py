#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
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
from app.domain.realtime.local_source_signal_gap_evidence import (  # noqa: E402
    build_signal_gap_official_smoke_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare unresolved signal-gap groups with an official live-smoke "
            "artifact and emit public-safe diagnostic evidence."
        )
    )
    parser.add_argument(
        "--official-live-smoke-json",
        required=True,
        help="Path to an official-realtime-live-smoke/v1 JSON artifact.",
    )
    parser.add_argument(
        "--captured-at",
        help="Optional ISO 8601 timestamp for reproducible evidence artifacts.",
    )
    parser.add_argument(
        "--output",
        help="Optional UTF-8 JSON output path. The same payload is printed.",
    )
    parser.add_argument(
        "--fail-on-unresolved",
        action="store_true",
        help="Exit with status 1 when any target signal-gap item remains unresolved.",
    )
    args = parser.parse_args()

    official_live_smoke_artifact = _load_json(Path(args.official_live_smoke_json))
    plan = build_local_source_action_plan(list_local_source_coverage())
    captured_at = args.captured_at or datetime.now(UTC).replace(microsecond=0).isoformat()
    evidence = build_signal_gap_official_smoke_evidence(
        plan=plan,
        official_live_smoke_artifact=official_live_smoke_artifact,
        captured_at=captured_at,
    )
    output = json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(f"{output}\n", encoding="utf-8")
    print(output)
    if (
        args.fail_on_unresolved
        and evidence["summary"]["unresolved_after_official_smoke_item_count"] > 0
    ):
        return 1
    return 0


def _load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SystemExit(f"{path}: cannot read official live-smoke JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"{path}: official live-smoke JSON must be an object")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
