#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
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
    build_local_source_action_plan,
)
from app.ops.local_source.local_source_coverage import (  # noqa: E402
    list_local_source_coverage,
)
from app.ops.local_source.local_source_request_packets import (  # noqa: E402
    build_signal_gap_request_batches,
)


READINESS_SCHEMA_VERSION = "local-source-signal-gap-dispatch-readiness/v1"
DISCOVERY_SUMMARY_SCHEMA_VERSION = "local-source-signal-gap-discovery-refresh/v1"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a public-safe signal-gap dispatch readiness summary from "
            "the latest discovery refresh and official request batches."
        )
    )
    parser.add_argument(
        "--discovery-summary-json",
        required=True,
        help="signal-gap-discovery-refresh-summary.json produced by discovery refresh.",
    )
    parser.add_argument(
        "--captured-at",
        required=True,
        help="ISO-8601 timestamp for this readiness summary.",
    )
    parser.add_argument(
        "--output",
        help="Optional output path. When omitted, content is written to stdout.",
    )
    args = parser.parse_args()

    discovery_summary = _load_discovery_summary(Path(args.discovery_summary_json))
    plan = build_local_source_action_plan(list_local_source_coverage())
    batches = build_signal_gap_request_batches(plan)
    readiness = build_dispatch_readiness(
        batches,
        discovery_summary=discovery_summary,
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


def _load_discovery_summary(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"{path}: discovery summary JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"{path}: discovery summary JSON must be an object")
    if payload.get("schema_version") != DISCOVERY_SUMMARY_SCHEMA_VERSION:
        raise SystemExit(
            f"{path}: schema_version must be {DISCOVERY_SUMMARY_SCHEMA_VERSION!r}"
        )
    return payload


def build_dispatch_readiness(
    batches: tuple[dict[str, Any], ...],
    *,
    discovery_summary: Mapping[str, Any],
    captured_at: str,
) -> dict[str, Any]:
    discovery_by_signal = {
        str(group.get("signal_type")): group
        for group in discovery_summary.get("groups", [])
        if isinstance(group, Mapping) and group.get("signal_type")
    }
    groups = [
        _build_group_readiness(batch, discovery_by_signal=discovery_by_signal)
        for batch in batches
    ]
    return {
        "schema_version": READINESS_SCHEMA_VERSION,
        "captured_at": captured_at,
        "discovery_summary": {
            "captured_at": discovery_summary.get("captured_at"),
            "source_catalog_url": discovery_summary.get("source_catalog_url"),
            "schema_version": discovery_summary.get("schema_version"),
        },
        "summary": {
            "signal_gap_group_count": len(groups),
            "dispatch_recommended_group_count": sum(
                1 for group in groups if group["dispatch_recommended"]
            ),
            "total_candidate_count": int(
                discovery_summary.get("total_candidate_count") or 0
            ),
            "total_metadata_only_count": int(
                discovery_summary.get("total_metadata_only_count") or 0
            ),
            "total_candidate_live_read_api_count": int(
                discovery_summary.get("total_candidate_live_read_api_count") or 0
            ),
        },
        "groups": groups,
        "notes": [
            "This public artifact is a dispatch checklist, not proof that requests were sent.",
            "Filled private dispatch evidence refs must stay in repository or workflow secrets.",
            "A group remains incomplete until official reply, production adapter, authorization-gated adapter, or official-unavailable evidence is accepted.",
        ],
    }


def _build_group_readiness(
    batch: Mapping[str, Any],
    *,
    discovery_by_signal: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    signal_type = str(batch.get("target_signal_type", ""))
    discovery_group = discovery_by_signal.get(signal_type, {})
    candidate_live_read_api_count = int(
        discovery_group.get("candidate_live_read_api_count") or 0
    )
    metadata_only_count = int(discovery_group.get("metadata_only_count") or 0)
    dispatch_reasons = _dispatch_reasons(
        candidate_live_read_api_count=candidate_live_read_api_count,
        metadata_only_count=metadata_only_count,
        has_discovery_group=bool(discovery_group),
    )
    return {
        "target_signal_type": signal_type,
        "batch_id": batch.get("batch_id"),
        "county_count": int(batch.get("county_count") or 0),
        "dispatch_recommended": bool(dispatch_reasons),
        "dispatch_reasons": dispatch_reasons,
        "next_step": batch.get("next_step", "send_official_read_api_requests"),
        "requested_counterparty_count": len(batch.get("requested_counterparties", [])),
        "tracking_statuses": list(batch.get("tracking_statuses", [])),
        "required_read_api_fields": list(batch.get("required_read_api_fields", [])),
        "production_operational_requirements": list(
            batch.get("production_operational_requirements", [])
        ),
        "completion_gate": batch.get("completion_gate"),
        "completion_evidence_target_count": len(
            batch.get("completion_evidence_targets", [])
        ),
        "packet_review_command": (
            "python scripts/local-source-request-packets.py "
            f"--format signal-gap-batches-markdown --signal-type {signal_type}"
        ),
        "dispatch_command": (
            "python scripts/local-source-request-packets.py "
            "--format signal-gap-dispatch-evidence "
            f"--signal-type {signal_type} "
            "--dispatch-evidence-ref REPLACE_WITH_PRIVATE_DISPATCH_EVIDENCE_REF "
            "--dispatched-at REPLACE_WITH_DISPATCHED_AT "
            "--follow-up-due-at REPLACE_WITH_FOLLOW_UP_DUE_AT"
        ),
        "discovery": _sanitized_discovery_group(discovery_group),
    }


def _dispatch_reasons(
    *,
    candidate_live_read_api_count: int,
    metadata_only_count: int,
    has_discovery_group: bool,
) -> list[str]:
    if candidate_live_read_api_count > 0:
        return ["review_live_read_api_candidate_before_dispatch"]
    reasons = ["no_live_read_api_candidate"]
    if metadata_only_count > 0:
        reasons.append("metadata_only_candidates_require_contract_followup")
    elif not has_discovery_group:
        reasons.append("no_discovery_group_match")
    else:
        reasons.append("no_public_candidate_found")
    return reasons


def _sanitized_discovery_group(group: Mapping[str, Any]) -> dict[str, Any]:
    readiness_by_county = group.get("readiness_by_county", {})
    if not isinstance(readiness_by_county, Mapping):
        readiness_by_county = {}
    return {
        "artifact_name": group.get("artifact_name"),
        "candidate_count": int(group.get("candidate_count") or 0),
        "metadata_only_count": int(group.get("metadata_only_count") or 0),
        "candidate_live_read_api_count": int(
            group.get("candidate_live_read_api_count") or 0
        ),
        "counties_without_candidates": [
            str(county) for county in group.get("target_counties_without_candidates", [])
        ],
        "metadata_only_counties": _metadata_only_counties(readiness_by_county),
    }


def _metadata_only_counties(readiness_by_county: Mapping[str, Any]) -> list[str]:
    counties: list[str] = []
    for county, readiness in readiness_by_county.items():
        if not isinstance(readiness, Mapping):
            continue
        if str(readiness.get("readiness_state", "")) == "metadata_only":
            counties.append(str(county))
            continue
        if int(readiness.get("metadata_only_count") or 0) > 0:
            counties.append(str(county))
    return sorted(counties)


if __name__ == "__main__":
    raise SystemExit(main())
