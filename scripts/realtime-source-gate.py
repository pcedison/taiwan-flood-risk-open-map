#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WORKERS_APP = ROOT / "apps" / "workers"
sys.path.insert(0, str(WORKERS_APP))

from app.ops.local_source_discovery_monitor import (  # noqa: E402
    DEFAULT_TARGET_COUNTIES,
    discover_local_source_candidates,
    fetch_data_gov_dataset_export,
)
from app.ops.official_realtime_live_smoke import (  # noqa: E402
    load_env_file,
    run_official_realtime_live_smoke,
)
from app.ops.realtime_source_gate import (  # noqa: E402
    DEFAULT_EXPECTED_COVERAGE_SUMMARY,
    evaluate_realtime_source_gate,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gate official realtime backbone health and unresolved local source discovery."
    )
    parser.add_argument(
        "--env-file",
        default=str(ROOT / ".env"),
        help="Optional .env file used by the official live smoke.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=20,
        help="Per-source upstream timeout.",
    )
    parser.add_argument(
        "--coverage-summary-json",
        help="Optional JSON file with admin local-source coverage summary fields.",
    )
    parser.add_argument(
        "--fail-on-skipped-smoke",
        action="store_true",
        help="Fail when any official source is skipped, for example missing CWA key.",
    )
    parser.add_argument(
        "--fail-on-live-candidate",
        action="store_true",
        help="Fail when discovery finds a new candidate_live_read_api dataset.",
    )
    parser.add_argument(
        "--county",
        action="append",
        dest="counties",
        help="Target county/city for discovery. Repeatable; defaults to 金門縣 and 連江縣.",
    )
    args = parser.parse_args()

    env = load_env_file(Path(args.env_file), base_env=os.environ)
    smoke = run_official_realtime_live_smoke(
        env=env,
        timeout_seconds=max(1, args.timeout_seconds),
    )
    discovery_payload = fetch_data_gov_dataset_export(
        timeout_seconds=max(1, args.timeout_seconds)
    )
    discovery = discover_local_source_candidates(
        discovery_payload,
        target_counties=tuple(args.counties or DEFAULT_TARGET_COUNTIES),
    )
    gate = evaluate_realtime_source_gate(
        coverage_summary=_coverage_summary(args.coverage_summary_json),
        smoke_result=smoke,
        discovery_result=discovery,
        fail_on_live_candidate=args.fail_on_live_candidate,
        fail_on_skipped_smoke=args.fail_on_skipped_smoke,
    )
    print(gate.to_json())
    return 0 if gate.passed else 1


def _coverage_summary(path: str | None) -> dict[str, Any]:
    if path is None:
        return dict(DEFAULT_EXPECTED_COVERAGE_SUMMARY)
    return json.loads(Path(path).read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
