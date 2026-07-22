#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shlex
import sys
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


ROOT = Path(__file__).resolve().parents[1]
API_APP = ROOT / "apps" / "api"
sys.path.insert(0, str(API_APP))

from app.ops.local_source.local_source_action_plan import (  # noqa: E402
    COMPLETION_EVIDENCE_SCHEMA_VERSION,
    build_local_source_action_plan,
)
from app.ops.local_source.local_source_coverage import (  # noqa: E402
    list_local_source_coverage,
)
from app.ops.local_source.local_source_request_packets import (  # noqa: E402
    build_official_request_packets,
)


SCHEMA_VERSION = "local-source-contract-dispatch-readiness/v1"
SOURCE_CONTRACT_GATES = (
    "authorization_request",
    "metadata_release_monitor",
    "public_api_contract_review",
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a public-safe source-contract dispatch readiness checklist "
            "for the remaining authorization, metadata release, and public API "
            "contract blockers."
        )
    )
    parser.add_argument(
        "--captured-at",
        required=True,
        help="ISO-8601 timestamp for this readiness summary.",
    )
    parser.add_argument(
        "--completion-evidence-json",
        help=(
            "Optional sanitized local-source-completion-evidence/v1 overlay. "
            "Accepted entries remove completed source-contract targets; "
            "request_dispatched entries remain pending."
        ),
    )
    parser.add_argument(
        "--output",
        help="Optional output path. When omitted, content is written to stdout.",
    )
    args = parser.parse_args()

    completion_evidence = (
        _load_completion_evidence(Path(args.completion_evidence_json))
        if args.completion_evidence_json
        else None
    )
    plan = build_local_source_action_plan(
        list_local_source_coverage(),
        completion_evidence=completion_evidence,
    )
    packets = build_official_request_packets(
        plan,
        completion_evidence=completion_evidence,
    )
    readiness = build_source_contract_dispatch_readiness(
        packets,
        captured_at=args.captured_at,
    )
    content = json.dumps(readiness, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
        return 0
    print(content, end="")
    return 0


def build_source_contract_dispatch_readiness(
    packets: tuple[dict[str, Any], ...],
    *,
    captured_at: str,
) -> dict[str, Any]:
    items = _source_contract_items(packets)
    gate_counts = Counter(str(item["gate"]) for item in items)
    return {
        "schema_version": SCHEMA_VERSION,
        "captured_at": captured_at,
        "summary": {
            "source_contract_item_count": len(items),
            "dispatch_recommended_item_count": sum(
                1 for item in items if item["dispatch_recommended"]
            ),
            "authorization_request_count": gate_counts["authorization_request"],
            "metadata_release_monitor_count": gate_counts["metadata_release_monitor"],
            "public_api_contract_review_count": gate_counts[
                "public_api_contract_review"
            ],
        },
        "groups": [
            {
                "gate": gate,
                "item_count": gate_counts[gate],
                "dispatch_recommended": gate_counts[gate] > 0,
                "dispatch_command": _dispatch_command(),
            }
            for gate in SOURCE_CONTRACT_GATES
        ],
        "items": items,
        "notes": [
            "This public artifact is a dispatch checklist, not proof that requests were sent.",
            "It intentionally omits private evidence refs, official reply refs, tokens, and correspondence.",
            "The official_authorization_and_contracts gate remains incomplete until accepted source-contract evidence is recorded.",
        ],
    }


def _source_contract_items(
    packets: tuple[dict[str, Any], ...],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for packet in packets:
        county = str(packet.get("county", ""))
        for target in packet.get("completion_evidence_targets", []):
            if not isinstance(target, Mapping):
                continue
            if str(target.get("manifest_section", "")) != "source_contract_evidence":
                continue
            gate = str(target.get("gate", ""))
            key = (county, gate)
            if key in seen:
                continue
            seen.add(key)
            items.append(_source_contract_item(packet, target, county=county, gate=gate))
    return sorted(
        items,
        key=lambda item: (
            SOURCE_CONTRACT_GATES.index(str(item["gate"]))
            if item["gate"] in SOURCE_CONTRACT_GATES
            else len(SOURCE_CONTRACT_GATES),
            str(item.get("county", "")),
        ),
    )


def _source_contract_item(
    packet: Mapping[str, Any],
    target: Mapping[str, Any],
    *,
    county: str,
    gate: str,
) -> dict[str, Any]:
    return {
        "county": county,
        "gate": gate,
        "packet_type": packet.get("packet_type"),
        "requested_counterparty": packet.get("requested_counterparty"),
        "tracking_status": packet.get("tracking_status"),
        "target_signal_types": list(packet.get("target_signal_types", [])),
        "required_read_api_fields": list(packet.get("required_read_api_fields", [])),
        "accepted_completion_statuses": [
            str(status) for status in target.get("accepted_statuses", [])
        ],
        "dispatch_recommended": True,
        "dispatch_reasons": [
            "source_contract_completion_evidence_missing",
            "official_request_or_release_followup_required",
        ],
        "packet_review_command": (
            "python scripts/local-source-request-packets.py "
            f"--format markdown --county {_quote(county)}"
        ),
        "dispatch_command": (
            "python scripts/local-source-request-packets.py "
            "--format source-contract-dispatch-evidence "
            f"--county {_quote(county)} "
            "--dispatch-evidence-ref REPLACE_WITH_PRIVATE_DISPATCH_EVIDENCE_REF "
            "--dispatched-at REPLACE_WITH_DISPATCHED_AT "
            "--follow-up-due-at REPLACE_WITH_FOLLOW_UP_DUE_AT"
        ),
    }


def _dispatch_command() -> str:
    return (
        "python scripts/local-source-request-packets.py "
        "--format source-contract-dispatch-evidence "
        "--dispatch-evidence-ref REPLACE_WITH_PRIVATE_DISPATCH_EVIDENCE_REF "
        "--dispatched-at REPLACE_WITH_DISPATCHED_AT "
        "--follow-up-due-at REPLACE_WITH_FOLLOW_UP_DUE_AT"
    )


def _quote(value: str) -> str:
    return shlex.quote(value)


def _load_completion_evidence(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"{path}: completion evidence JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"{path}: completion evidence JSON must be an object")
    if payload.get("schema_version") != COMPLETION_EVIDENCE_SCHEMA_VERSION:
        raise SystemExit(
            f"{path}: schema_version must be "
            f"{COMPLETION_EVIDENCE_SCHEMA_VERSION!r}"
        )
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
