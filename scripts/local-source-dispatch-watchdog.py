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


SCHEMA_VERSION = "local-source-dispatch-watchdog/v1"
SIGNAL_GAP_SCHEMA_VERSION = "local-source-signal-gap-dispatch-readiness/v1"
SOURCE_CONTRACT_SCHEMA_VERSION = "local-source-contract-dispatch-readiness/v1"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a public-safe watchdog report for unresolved local-source "
            "signal-gap and source-contract dispatch work."
        )
    )
    parser.add_argument(
        "--signal-gap-dispatch-readiness-json",
        required=True,
        help="local-source-signal-gap-dispatch-readiness/v1 JSON artifact.",
    )
    parser.add_argument(
        "--source-contract-dispatch-readiness-json",
        required=True,
        help="local-source-contract-dispatch-readiness/v1 JSON artifact.",
    )
    parser.add_argument(
        "--captured-at",
        required=True,
        help="ISO-8601 timestamp for this watchdog report.",
    )
    parser.add_argument("--output", help="Optional JSON output path.")
    parser.add_argument("--markdown-output", help="Optional Markdown output path.")
    parser.add_argument(
        "--fail-on-dispatch-required",
        action="store_true",
        help="Exit 1 when any signal-gap group or source-contract item needs dispatch.",
    )
    args = parser.parse_args()

    signal_gap = _load_json(
        Path(args.signal_gap_dispatch_readiness_json),
        expected_schema=SIGNAL_GAP_SCHEMA_VERSION,
        label="signal gap dispatch readiness",
    )
    source_contract = _load_json(
        Path(args.source_contract_dispatch_readiness_json),
        expected_schema=SOURCE_CONTRACT_SCHEMA_VERSION,
        label="source contract dispatch readiness",
    )
    report = build_watchdog_report(
        signal_gap,
        source_contract,
        captured_at=args.captured_at,
    )
    content = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
    else:
        print(content, end="")
    if args.markdown_output:
        markdown_path = Path(args.markdown_output)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_markdown(report), encoding="utf-8")

    if args.fail_on_dispatch_required and report["summary"]["dispatch_required"]:
        return 1
    return 0


def build_watchdog_report(
    signal_gap: Mapping[str, Any],
    source_contract: Mapping[str, Any],
    *,
    captured_at: str,
) -> dict[str, Any]:
    signal_gap_summary = _mapping(signal_gap.get("summary"))
    source_contract_summary = _mapping(source_contract.get("summary"))
    signal_gap_groups = _signal_gap_groups(signal_gap.get("groups"))
    source_contract_groups = _source_contract_groups(source_contract.get("groups"))
    source_contract_items = _source_contract_items(source_contract.get("items"))

    signal_dispatch_count = _int(
        signal_gap_summary.get("dispatch_recommended_group_count")
    )
    source_contract_dispatch_count = _int(
        source_contract_summary.get("dispatch_recommended_item_count")
    )
    dispatch_required = signal_dispatch_count > 0 or source_contract_dispatch_count > 0
    return {
        "schema_version": SCHEMA_VERSION,
        "captured_at": captured_at,
        "status": "dispatch_required" if dispatch_required else "no_dispatch_required",
        "summary": {
            "dispatch_required": dispatch_required,
            "signal_gap_dispatch_recommended_group_count": signal_dispatch_count,
            "signal_gap_county_item_count": sum(
                _int(group.get("county_count")) for group in signal_gap_groups
            ),
            "signal_gap_total_metadata_only_count": _int(
                signal_gap_summary.get("total_metadata_only_count")
            ),
            "signal_gap_total_live_read_api_candidate_count": _int(
                signal_gap_summary.get("total_candidate_live_read_api_count")
            ),
            "source_contract_dispatch_recommended_item_count": (
                source_contract_dispatch_count
            ),
            "source_contract_item_count": _int(
                source_contract_summary.get("source_contract_item_count")
            ),
            "authorization_request_count": _int(
                source_contract_summary.get("authorization_request_count")
            ),
            "metadata_release_monitor_count": _int(
                source_contract_summary.get("metadata_release_monitor_count")
            ),
            "public_api_contract_review_count": _int(
                source_contract_summary.get("public_api_contract_review_count")
            ),
        },
        "next_workstreams": _next_workstreams(
            signal_dispatch_count=signal_dispatch_count,
            source_contract_dispatch_count=source_contract_dispatch_count,
        ),
        "signal_gap_groups": signal_gap_groups,
        "source_contract_groups": source_contract_groups,
        "source_contract_items": source_contract_items,
        "notes": [
            "This watchdog report is public-safe and omits private evidence refs.",
            "Dispatch required means official request, release, or contract follow-up is still needed; it is not completion evidence.",
            "Completion still requires accepted signal-family and source-contract evidence overlays.",
        ],
    }


def _load_json(path: Path, *, expected_schema: str, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"{path}: {label} JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"{path}: {label} JSON must be an object")
    if payload.get("schema_version") != expected_schema:
        raise SystemExit(f"{path}: schema_version must be {expected_schema!r}")
    return payload


def _signal_gap_groups(value: Any) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for group in _list_of_mappings(value):
        discovery = _mapping(group.get("discovery"))
        groups.append(
            {
                "target_signal_type": str(group.get("target_signal_type", "")),
                "county_count": _int(group.get("county_count")),
                "dispatch_recommended": bool(group.get("dispatch_recommended")),
                "dispatch_reasons": _string_list(group.get("dispatch_reasons")),
                "metadata_only_count": _int(discovery.get("metadata_only_count")),
                "candidate_live_read_api_count": _int(
                    discovery.get("candidate_live_read_api_count")
                ),
                "metadata_only_counties": _string_list(
                    discovery.get("metadata_only_counties")
                ),
                "counties_without_candidates": _string_list(
                    discovery.get("counties_without_candidates")
                ),
            }
        )
    return groups


def _source_contract_groups(value: Any) -> list[dict[str, Any]]:
    return [
        {
            "gate": str(group.get("gate", "")),
            "item_count": _int(group.get("item_count")),
            "dispatch_recommended": bool(group.get("dispatch_recommended")),
        }
        for group in _list_of_mappings(value)
    ]


def _source_contract_items(value: Any) -> list[dict[str, Any]]:
    return [
        {
            "county": str(item.get("county", "")),
            "gate": str(item.get("gate", "")),
            "packet_type": str(item.get("packet_type", "")),
            "tracking_status": str(item.get("tracking_status", "")),
            "target_signal_types": _string_list(item.get("target_signal_types")),
        }
        for item in _list_of_mappings(value)
        if bool(item.get("dispatch_recommended"))
    ]


def _next_workstreams(
    *,
    signal_dispatch_count: int,
    source_contract_dispatch_count: int,
) -> list[str]:
    workstreams: list[str] = []
    if signal_dispatch_count:
        workstreams.append("send_official_read_api_requests")
    if source_contract_dispatch_count:
        workstreams.append("resolve_authorization_gated_adapters")
    return workstreams


def render_markdown(report: Mapping[str, Any]) -> str:
    summary = _mapping(report.get("summary"))
    lines = [
        "# Local Source Dispatch Watchdog",
        "",
        f"- status: `{report.get('status')}`",
        f"- captured_at: `{report.get('captured_at')}`",
        f"- dispatch_required: `{summary.get('dispatch_required')}`",
        f"- signal gap groups needing dispatch: `{summary.get('signal_gap_dispatch_recommended_group_count')}`",
        f"- signal gap county-items: `{summary.get('signal_gap_county_item_count')}`",
        f"- source contract items needing dispatch: `{summary.get('source_contract_dispatch_recommended_item_count')}`",
        "",
        "## Signal Gap Groups",
        "",
    ]
    signal_groups = report.get("signal_gap_groups")
    if isinstance(signal_groups, list) and signal_groups:
        for group in signal_groups:
            if not isinstance(group, Mapping):
                continue
            lines.append(
                "- "
                f"`{group.get('target_signal_type')}`: "
                f"{group.get('county_count')} county-items, "
                f"live read API candidates `{group.get('candidate_live_read_api_count')}`, "
                f"metadata-only `{group.get('metadata_only_count')}`"
            )
    else:
        lines.append("- none")
    lines.extend(["", "## Source Contract Items", ""])
    source_items = report.get("source_contract_items")
    if isinstance(source_items, list) and source_items:
        for item in source_items:
            if not isinstance(item, Mapping):
                continue
            signals = ", ".join(_string_list(item.get("target_signal_types"))) or "none"
            lines.append(
                "- "
                f"`{item.get('county')}` / `{item.get('gate')}`: "
                f"{item.get('tracking_status')} "
                f"(signals: {signals})"
            )
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "This report tracks official request dispatch work. It is not official request completion evidence.",
            "",
        ]
    )
    return "\n".join(lines)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
