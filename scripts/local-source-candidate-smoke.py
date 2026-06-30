#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
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
        "--allow-insecure-tls",
        action="store_true",
        help=(
            "Allow probing public government pages whose certificate chain is "
            "rejected by Python's strict TLS verifier. The artifact records this "
            "as tls_verification=disabled."
        ),
    )
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
        help="Output format.",
    )
    parser.add_argument(
        "--captured-at",
        help="Optional ISO 8601 timestamp for a reproducible evidence artifact.",
    )
    parser.add_argument(
        "--output",
        help="Optional UTF-8 JSON evidence artifact output path.",
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
                verify_tls=not args.allow_insecure_tls,
            )

    result = qualify_static_candidate_sources(
        fetch_results=fetch_results,
        definitions=definitions,
    )
    payload = result.to_dict()
    if args.output:
        _write_json(
            Path(args.output),
            _artifact(
                captured_at=args.captured_at
                or datetime.now(UTC).replace(microsecond=0).isoformat(),
                result=payload,
                tls_verification=(
                    "disabled" if args.allow_insecure_tls else "enabled"
                ),
            ),
        )
    if args.format == "markdown":
        print(_markdown(result))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))

    if args.fail_on_promotion_ready and any(
        source.status == "promotion_ready" and source.next_action == "start_adapter_tdd"
        for source in result.sources
    ):
        return 1
    return 0


def _artifact(*, captured_at: str, result: dict, tls_verification: str) -> dict:
    status_counts = result.get("status_counts", {})
    promotion_ready_count = (
        status_counts.get("promotion_ready", 0)
        if isinstance(status_counts, dict)
        else 0
    )
    return {
        "schema_version": "local-source-candidate-smoke/v1",
        "captured_at": captured_at,
        "summary": {
            "source_count": result.get("source_count", 0),
            "promotion_ready_count": promotion_ready_count,
            "tls_verification": tls_verification,
            "status_counts": status_counts,
        },
        "result": result,
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


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
