#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKERS_APP = ROOT / "apps" / "workers"
sys.path.insert(0, str(WORKERS_APP))

from app.ops.local_source_candidate_smoke import (  # noqa: E402
    CANDIDATE_SOURCE_DEFINITIONS,
    CandidateSourceFetchResult,
    CandidateSourceSmokeResult,
    fetch_candidate_source,
    qualify_static_candidate_sources,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Smoke candidate local realtime water sources and classify upgrade blockers.",
    )
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="Print the tracked source catalog without making network requests.",
    )
    parser.add_argument(
        "--county",
        action="append",
        dest="counties",
        help="Only check the given county/city. Repeatable.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=20,
        help="Per-source request timeout.",
    )
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
        help="Output format.",
    )
    parser.add_argument(
        "--fail-on-promotion-ready",
        action="store_true",
        help="Exit non-zero when an unchecked candidate now has all fields needed for adapter work.",
    )
    args = parser.parse_args()

    definitions = tuple(
        definition
        for definition in CANDIDATE_SOURCE_DEFINITIONS
        if not args.counties or definition.county in set(args.counties)
    )
    fetch_results: dict[str, CandidateSourceFetchResult] = {}
    if not args.no_fetch:
        for definition in definitions:
            fetch_results[definition.key] = fetch_candidate_source(
                definition,
                timeout_seconds=max(1, args.timeout_seconds),
            )

    result = qualify_static_candidate_sources(
        fetch_results=fetch_results,
        definitions=definitions,
    )
    if args.format == "markdown":
        print(_markdown(result))
    else:
        print(result.to_json())

    if args.fail_on_promotion_ready and any(
        source.status == "promotion_ready" and source.next_action == "start_adapter_tdd"
        for source in result.sources
    ):
        return 1
    return 0


def _markdown(result: CandidateSourceSmokeResult) -> str:
    lines = [
        "# Local Source Candidate Smoke",
        "",
        "| 縣市 | key | status | next action | missing fields |",
        "| --- | --- | --- | --- | --- |",
    ]
    for source in result.sources:
        missing = ", ".join(source.missing_required_fields) or "-"
        lines.append(
            "| "
            f"{source.county} | `{source.key}` | `{source.status}` | "
            f"`{source.next_action}` | {missing} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
