#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
WORKERS_APP = ROOT / "apps" / "workers"
sys.path.insert(0, str(WORKERS_APP))

from app.ops.local_source_discovery_monitor import (  # noqa: E402
    DATA_GOV_DATASET_EXPORT_URL,
    DEFAULT_TARGET_COUNTIES,
    DiscoveryResult,
    discover_local_source_candidates,
    fetch_data_gov_dataset_export,
)

EVIDENCE_SCHEMA_VERSION = "local-source-discovery-refresh/v1"


def main(argv: list[str] | None = None) -> int:
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
    parser.add_argument(
        "--captured-at",
        help="Optional ISO 8601 timestamp for reproducible evidence artifacts.",
    )
    parser.add_argument(
        "--evidence-output",
        help="Optional UTF-8 JSON evidence artifact path for this discovery run.",
    )
    args = parser.parse_args(argv)

    target_counties = tuple(args.counties or DEFAULT_TARGET_COUNTIES)
    payload = fetch_data_gov_dataset_export(timeout_seconds=max(1, args.timeout_seconds))
    result = discover_local_source_candidates(
        payload,
        target_counties=target_counties,
        required_signal_types=tuple(args.signal_types or ()),
    )
    print(result.to_json())
    live_candidate_found = any(
        candidate.readiness == "candidate_live_read_api"
        for candidate in result.candidates
    )
    _write_json(
        args.evidence_output,
        build_discovery_evidence_artifact(
            captured_at=args.captured_at
            or datetime.now(UTC).replace(microsecond=0).isoformat(),
            result=result,
            live_candidate_found=live_candidate_found,
        ),
    )
    if args.fail_on_candidate and live_candidate_found:
        return 1
    return 0


def build_discovery_evidence_artifact(
    *,
    captured_at: str,
    result: DiscoveryResult,
    live_candidate_found: bool,
) -> dict[str, Any]:
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "captured_at": captured_at,
        "source_catalog_url": DATA_GOV_DATASET_EXPORT_URL,
        "conclusion": (
            "candidate_live_read_api_found"
            if live_candidate_found
            else "no_candidate_live_read_api_found"
        ),
        "discovery": result.to_dict(),
    }


def _write_json(output_path: str | None, payload: Mapping[str, Any]) -> None:
    if output_path is None:
        return
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
