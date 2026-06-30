#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKERS_APP = ROOT / "apps" / "workers"
sys.path.insert(0, str(WORKERS_APP))

from app.ops.local_source_discovery_monitor import (  # noqa: E402
    DEFAULT_TARGET_COUNTIES,
    discover_local_source_candidates,
    fetch_data_gov_dataset_export,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Discover candidate local realtime water datasets for unresolved counties."
    )
    parser.add_argument(
        "--county",
        action="append",
        dest="counties",
        help="Target county/city name. Repeatable. Defaults to 金門縣 and 連江縣.",
    )
    parser.add_argument(
        "--signal-type",
        action="append",
        dest="signal_types",
        help=(
            "Required signal type to keep in discovery results. Repeatable, "
            "for example pump_or_gate_status."
        ),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=20,
        help="data.gov.tw export request timeout.",
    )
    parser.add_argument(
        "--fail-on-candidate",
        action="store_true",
        help="Exit non-zero when candidate_live_read_api datasets are found.",
    )
    args = parser.parse_args()

    target_counties = tuple(args.counties or DEFAULT_TARGET_COUNTIES)
    payload = fetch_data_gov_dataset_export(timeout_seconds=max(1, args.timeout_seconds))
    result = discover_local_source_candidates(
        payload,
        target_counties=target_counties,
        required_signal_types=tuple(args.signal_types or ()),
    )
    print(result.to_json())
    if args.fail_on_candidate and any(
        candidate.readiness == "candidate_live_read_api" for candidate in result.candidates
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
