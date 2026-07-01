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
from app.domain.realtime.local_source_request_packets import (  # noqa: E402
    build_completion_evidence_template,
    build_official_request_packets,
    build_signal_gap_dispatch_evidence_template,
    build_signal_gap_request_batches,
    build_source_contract_dispatch_evidence_template,
    render_official_request_packets_markdown,
    render_signal_gap_request_batches_markdown,
)


SCHEMA_VERSION = "local-source-request-packet-bundle/v1"
DISPATCH_CHECKLIST_SCHEMA_VERSION = "local-source-dispatch-coverage-checklist/v1"
DISPATCH_EVIDENCE_SECRET_NAME = "LOCAL_SOURCE_REQUEST_DISPATCH_EVIDENCE_B64"
SIGNAL_DISPATCH_REF_PLACEHOLDER = "REPLACE_WITH_PRIVATE_DISPATCH_EVIDENCE_REF"
DISPATCHED_AT_PLACEHOLDER = "REPLACE_WITH_DISPATCHED_AT"
FOLLOW_UP_DUE_AT_PLACEHOLDER = "REPLACE_WITH_FOLLOW_UP_DUE_AT"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Write a public-safe local-source request packet bundle for the "
            "remaining official signal-gap and source-contract work."
        )
    )
    parser.add_argument(
        "--captured-at",
        required=True,
        help="ISO-8601 timestamp for this bundle manifest.",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory where the bundle artifacts should be written.",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    plan = build_local_source_action_plan(list_local_source_coverage())
    packets = build_official_request_packets(plan)
    batches = build_signal_gap_request_batches(plan)
    official_template = build_completion_evidence_template(packets)
    signal_dispatch_template = build_signal_gap_dispatch_evidence_template(
        batches,
        dispatch_evidence_ref=SIGNAL_DISPATCH_REF_PLACEHOLDER,
        dispatched_at=DISPATCHED_AT_PLACEHOLDER,
        follow_up_due_at=FOLLOW_UP_DUE_AT_PLACEHOLDER,
    )
    source_contract_template = build_source_contract_dispatch_evidence_template(
        packets,
        dispatch_evidence_ref=SIGNAL_DISPATCH_REF_PLACEHOLDER,
        dispatched_at=DISPATCHED_AT_PLACEHOLDER,
        follow_up_due_at=FOLLOW_UP_DUE_AT_PLACEHOLDER,
    )
    dispatch_checklist = _dispatch_coverage_checklist(
        captured_at=args.captured_at,
        signal_dispatch_template=signal_dispatch_template,
        source_contract_template=source_contract_template,
    )

    files: dict[str, str] = {
        "local-source-official-request-packets.json": _json(packets),
        "local-source-official-request-packets.md": (
            render_official_request_packets_markdown(packets)
        ),
        "local-source-official-request-completion-template.json": _json(
            official_template
        ),
        "local-source-signal-gap-request-batches.json": _json(batches),
        "local-source-signal-gap-request-batches.md": (
            render_signal_gap_request_batches_markdown(batches)
        ),
        "local-source-signal-gap-dispatch-template.json": _json(
            signal_dispatch_template
        ),
        "local-source-source-contract-dispatch-template.json": _json(
            source_contract_template
        ),
        "local-source-dispatch-coverage-checklist.json": _json(
            dispatch_checklist
        ),
    }

    summary = _summary(
        packets,
        batches,
        official_template=official_template,
        source_contract_template=source_contract_template,
    )
    all_file_names = tuple(
        sorted(
            (
                *files,
                "local-source-request-packet-bundle-manifest.json",
                "local-source-request-packet-bundle.md",
            )
        )
    )
    manifest = _manifest(
        captured_at=args.captured_at,
        summary=summary,
        file_names=all_file_names,
    )
    files["local-source-request-packet-bundle-manifest.json"] = _json(manifest)
    files["local-source-request-packet-bundle.md"] = _summary_markdown(
        captured_at=args.captured_at,
        summary=summary,
        file_names=all_file_names,
    )

    for name, content in files.items():
        (output_dir / name).write_text(content, encoding="utf-8")
    print(
        f"Wrote {len(files)} local-source request packet bundle files to {output_dir}",
        file=sys.stderr,
    )
    return 0


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _summary(
    packets: tuple[dict[str, Any], ...],
    batches: tuple[dict[str, Any], ...],
    *,
    official_template: dict[str, Any],
    source_contract_template: dict[str, Any],
) -> dict[str, int]:
    signal_gap_county_item_count = sum(
        len(batch.get("completion_evidence_targets", [])) for batch in batches
    )
    official_signal_targets = len(
        official_template.get("signal_family_gap_evidence", [])
    )
    source_contract_targets = len(
        source_contract_template.get("source_contract_evidence", [])
    )
    return {
        "official_request_packet_count": len(packets),
        "official_completion_target_count": official_signal_targets
        + source_contract_targets,
        "signal_gap_batch_count": len(batches),
        "signal_gap_county_item_count": signal_gap_county_item_count,
        "source_contract_completion_target_count": source_contract_targets,
    }


def _manifest(
    *,
    captured_at: str,
    summary: dict[str, int],
    file_names: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "captured_at": captured_at,
        "summary": summary,
        "remaining_completion_gates": [
            "required_signal_families",
            "official_authorization_and_contracts",
        ],
        "files": [
            {
                "path": name,
                "purpose": _file_purpose(name),
            }
            for name in file_names
        ],
        "notes": [
            "This bundle is an operator handoff and does not prove official requests were sent.",
            "Dispatch templates contain placeholders and must not be uploaded with real private evidence refs.",
            "Completion gates are satisfied only by accepted official replies, production adapters, authorization-gated adapters, official-unavailable decisions, or reviewed private evidence.",
        ],
    }


def _dispatch_coverage_checklist(
    *,
    captured_at: str,
    signal_dispatch_template: dict[str, Any],
    source_contract_template: dict[str, Any],
) -> dict[str, Any]:
    signal_items = [
        _signal_dispatch_checklist_item(item)
        for item in signal_dispatch_template.get("signal_family_gap_evidence", [])
        if isinstance(item, dict)
    ]
    source_contract_items = [
        _source_contract_dispatch_checklist_item(item)
        for item in source_contract_template.get("source_contract_evidence", [])
        if isinstance(item, dict)
    ]
    return {
        "schema_version": DISPATCH_CHECKLIST_SCHEMA_VERSION,
        "captured_at": captured_at,
        "secret_name": DISPATCH_EVIDENCE_SECRET_NAME,
        "summary": {
            "total_dispatch_item_count": len(signal_items) + len(source_contract_items),
            "signal_family_gap_dispatch_item_count": len(signal_items),
            "source_contract_dispatch_item_count": len(source_contract_items),
        },
        "signal_family_gap_dispatch_items": signal_items,
        "source_contract_dispatch_items": source_contract_items,
        "notes": [
            "Checklist is public-safe and intentionally excludes evidence_ref values.",
            "Each item should appear in private dispatch evidence only after the official request is sent.",
            "request_dispatched tracks operator follow-up and does not satisfy completion gates.",
        ],
    }


def _signal_dispatch_checklist_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "completion_gate": "required_signal_families",
        "county": str(item.get("county", "")),
        "signal_type": str(item.get("signal_type", "")),
        "dispatch_status": "request_dispatched",
        "follow_up_due_at_required": True,
        "accepted_completion_statuses": [
            str(status) for status in item.get("accepted_statuses", [])
        ],
    }


def _source_contract_dispatch_checklist_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "completion_gate": "official_authorization_and_contracts",
        "county": str(item.get("county", "")),
        "gate": str(item.get("gate", "")),
        "dispatch_status": "request_dispatched",
        "follow_up_due_at_required": True,
        "accepted_completion_statuses": [
            str(status) for status in item.get("accepted_statuses", [])
        ],
    }


def _summary_markdown(
    *,
    captured_at: str,
    summary: dict[str, int],
    file_names: tuple[str, ...],
) -> str:
    lines = [
        "# Local Source Request Packet Bundle",
        "",
        f"- captured_at: {captured_at}",
        "- remaining_completion_gates: required_signal_families, official_authorization_and_contracts",
        "",
        "## Summary",
        "",
    ]
    for key in sorted(summary):
        lines.append(f"- {key}: {summary[key]}")
    lines.extend(
        [
            "",
            "## Files",
            "",
        ]
    )
    for name in file_names:
        lines.append(f"- `{name}` - {_file_purpose(name)}")
    lines.extend(
        [
            "",
            "These templates are not completion evidence until placeholders are replaced "
            "inside private evidence handling and the resulting records are accepted by "
            "the completion audit.",
            "",
        ]
    )
    return "\n".join(lines)


def _file_purpose(name: str) -> str:
    if name.endswith("manifest.json"):
        return "machine-readable bundle index and remaining gate summary"
    if name.endswith("bundle.md"):
        return "human-readable operator summary"
    if name.endswith("official-request-packets.json"):
        return "machine-readable official request packets"
    if name.endswith("official-request-packets.md"):
        return "human-readable official request packets"
    if name.endswith("official-request-completion-template.json"):
        return "pending completion evidence template generated from request packets"
    if name.endswith("signal-gap-request-batches.json"):
        return "machine-readable signal-family request batches"
    if name.endswith("signal-gap-request-batches.md"):
        return "human-readable signal-family request batches"
    if name.endswith("signal-gap-dispatch-template.json"):
        return "placeholder dispatch overlay template for signal-family requests"
    if name.endswith("source-contract-dispatch-template.json"):
        return "placeholder dispatch overlay template for source-contract requests"
    if name.endswith("dispatch-coverage-checklist.json"):
        return "public-safe checklist for private dispatch evidence coverage"
    return "request packet bundle artifact"


if __name__ == "__main__":
    raise SystemExit(main())
