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

from app.ops.local_source.local_source_action_plan import (  # noqa: E402
    COMPLETION_EVIDENCE_SCHEMA_VERSION as ACTION_PLAN_COMPLETION_SCHEMA_VERSION,
    build_local_source_action_plan,
)
from app.ops.local_source.local_source_coverage import (  # noqa: E402
    list_local_source_coverage,
)
from app.ops.local_source.local_source_request_packets import (  # noqa: E402
    build_completion_evidence_template,
    build_official_request_packets,
    build_signal_gap_dispatch_evidence_template,
    build_signal_gap_request_batches,
    build_source_contract_dispatch_evidence_template,
    render_official_request_packets_markdown,
    render_signal_gap_request_batches_markdown,
)


SCHEMA_VERSION = "local-source-request-packet-bundle/v1"
COMPLETION_EVIDENCE_SCHEMA_VERSION = "local-source-completion-evidence/v1"
DISPATCH_CHECKLIST_SCHEMA_VERSION = "local-source-dispatch-coverage-checklist/v1"
DISPATCH_QUEUE_SCHEMA_VERSION = "local-source-request-dispatch-queue/v1"
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
    parser.add_argument(
        "--completion-evidence-json",
        help=(
            "Optional sanitized local-source-completion-evidence/v1 overlay. "
            "Accepted entries are omitted from the remaining request bundle; "
            "request_dispatched entries remain pending."
        ),
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

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
    batches = build_signal_gap_request_batches(
        plan,
        completion_evidence=completion_evidence,
    )
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
    request_dispatch_evidence_draft = _request_dispatch_evidence_draft(
        signal_dispatch_template=signal_dispatch_template,
        source_contract_template=source_contract_template,
    )
    dispatch_checklist = _dispatch_coverage_checklist(
        captured_at=args.captured_at,
        signal_dispatch_template=signal_dispatch_template,
        source_contract_template=source_contract_template,
    )
    dispatch_queue = _request_dispatch_queue(
        captured_at=args.captured_at,
        batches=batches,
        source_contract_template=source_contract_template,
        packets=packets,
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
        "local-source-request-dispatch-evidence-draft.json": _json(
            request_dispatch_evidence_draft
        ),
        "local-source-dispatch-coverage-checklist.json": _json(
            dispatch_checklist
        ),
        "local-source-request-dispatch-queue.json": _json(dispatch_queue),
    }

    summary = _summary(
        packets,
        batches,
        official_template=official_template,
        source_contract_template=source_contract_template,
        request_dispatch_evidence_draft=request_dispatch_evidence_draft,
        dispatch_queue=dispatch_queue,
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


def _load_completion_evidence(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"{path}: completion evidence JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"{path}: completion evidence JSON must be an object")
    if payload.get("schema_version") != ACTION_PLAN_COMPLETION_SCHEMA_VERSION:
        raise SystemExit(
            f"{path}: schema_version must be "
            f"{ACTION_PLAN_COMPLETION_SCHEMA_VERSION!r}"
        )
    return payload


def _summary(
    packets: tuple[dict[str, Any], ...],
    batches: tuple[dict[str, Any], ...],
    *,
    official_template: dict[str, Any],
    source_contract_template: dict[str, Any],
    request_dispatch_evidence_draft: dict[str, Any],
    dispatch_queue: dict[str, Any],
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
    request_dispatch_draft_targets = len(
        request_dispatch_evidence_draft.get("signal_family_gap_evidence", [])
    ) + len(request_dispatch_evidence_draft.get("source_contract_evidence", []))
    dispatch_queue_summary = _mapping(dispatch_queue.get("summary"))
    return {
        "official_request_packet_count": len(packets),
        "official_completion_target_count": official_signal_targets
        + source_contract_targets,
        "signal_gap_batch_count": len(batches),
        "signal_gap_county_item_count": signal_gap_county_item_count,
        "source_contract_completion_target_count": source_contract_targets,
        "request_dispatch_evidence_draft_item_count": request_dispatch_draft_targets,
        "dispatch_queue_item_count": _int(
            dispatch_queue_summary.get("dispatch_queue_item_count")
        ),
        "signal_gap_dispatch_queue_item_count": _int(
            dispatch_queue_summary.get("signal_gap_dispatch_queue_item_count")
        ),
        "source_contract_dispatch_queue_item_count": _int(
            dispatch_queue_summary.get("source_contract_dispatch_queue_item_count")
        ),
    }


def _request_dispatch_evidence_draft(
    *,
    signal_dispatch_template: dict[str, Any],
    source_contract_template: dict[str, Any],
) -> dict[str, Any]:
    signal_items = [
        dict(item)
        for item in signal_dispatch_template.get("signal_family_gap_evidence", [])
        if isinstance(item, dict)
    ]
    source_contract_items = [
        dict(item)
        for item in source_contract_template.get("source_contract_evidence", [])
        if isinstance(item, dict)
    ]
    return {
        "schema_version": COMPLETION_EVIDENCE_SCHEMA_VERSION,
        "captured_at": DISPATCHED_AT_PLACEHOLDER,
        "signal_family_gap_evidence": signal_items,
        "source_contract_evidence": source_contract_items,
        "production_gate_evidence": [],
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
        "remaining_completion_gates": _remaining_completion_gates(summary),
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


def _request_dispatch_queue(
    *,
    captured_at: str,
    batches: tuple[dict[str, Any], ...],
    source_contract_template: dict[str, Any],
    packets: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    source_packet_lookup = _source_contract_packet_lookup(packets)
    signal_items = [
        _signal_gap_dispatch_queue_item(rank=index + 1, batch=batch)
        for index, batch in enumerate(batches)
    ]
    source_contract_entries = [
        item
        for item in source_contract_template.get("source_contract_evidence", [])
        if isinstance(item, dict)
    ]
    source_contract_items = [
        _source_contract_dispatch_queue_item(
            rank=len(signal_items) + index + 1,
            item=item,
            packet=source_packet_lookup.get(
                (str(item.get("county", "")), str(item.get("gate", ""))),
                {},
            ),
        )
        for index, item in enumerate(source_contract_entries)
    ]
    items = [*signal_items, *source_contract_items]
    return {
        "schema_version": DISPATCH_QUEUE_SCHEMA_VERSION,
        "captured_at": captured_at,
        "secret_name": DISPATCH_EVIDENCE_SECRET_NAME,
        "summary": {
            "dispatch_queue_item_count": len(items),
            "signal_gap_dispatch_queue_item_count": len(signal_items),
            "source_contract_dispatch_queue_item_count": len(source_contract_items),
            "signal_gap_completion_target_count": sum(
                _int(item.get("completion_target_count")) for item in signal_items
            ),
            "source_contract_completion_target_count": sum(
                _int(item.get("completion_target_count"))
                for item in source_contract_items
            ),
        },
        "items": items,
        "notes": [
            "Queue is public-safe operator handoff; it does not prove official requests were sent.",
            "Items intentionally omit private evidence refs and secret values.",
            "Completion gates remain open until accepted official replies, adapters, releases, or official-unavailable evidence are recorded.",
        ],
    }


def _signal_gap_dispatch_queue_item(
    *,
    rank: int,
    batch: dict[str, Any],
) -> dict[str, Any]:
    completion_targets = [
        item
        for item in batch.get("completion_evidence_targets", [])
        if isinstance(item, dict)
    ]
    return {
        "rank": rank,
        "queue_id": str(batch.get("batch_id", "")),
        "request_type": "signal_gap_batch_request",
        "status": "needs_dispatch",
        "completion_gate": "required_signal_families",
        "completion_gate_requirement": str(batch.get("completion_gate", "")),
        "target_signal_type": str(batch.get("target_signal_type", "")),
        "county_count": _int(batch.get("county_count")),
        "counties": _strings(batch.get("counties")),
        "completion_target_count": len(completion_targets),
        "requested_counterparties": _strings(batch.get("requested_counterparties")),
        "tracking_statuses": _strings(batch.get("tracking_statuses")),
        "required_read_api_fields": _strings(batch.get("required_read_api_fields")),
        "production_operational_requirements": _strings(
            batch.get("production_operational_requirements")
        ),
        "next_step": str(batch.get("next_step", "send_official_read_api_requests")),
        "accepted_completion_statuses": _accepted_statuses_from_targets(
            completion_targets
        ),
        "private_dispatch_manifest_section": "signal_family_gap_evidence",
        "private_dispatch_manifest_key_fields": ["county", "signal_type"],
        "follow_up_due_at_required": True,
        "dispatch_template_file": "local-source-signal-gap-dispatch-template.json",
        "request_packet_file": "local-source-signal-gap-request-batches.md",
    }


def _source_contract_dispatch_queue_item(
    *,
    rank: int,
    item: dict[str, Any],
    packet: dict[str, Any],
) -> dict[str, Any]:
    county = str(item.get("county", ""))
    gate = str(item.get("gate", ""))
    return {
        "rank": rank,
        "queue_id": f"source-contract/{gate}/{county}",
        "request_type": "source_contract_request",
        "status": "needs_dispatch",
        "completion_gate": "official_authorization_and_contracts",
        "source_contract_gate": gate,
        "county": county,
        "packet_type": str(packet.get("packet_type", "")),
        "completion_target_count": 1,
        "requested_counterparties": _single_or_empty(
            packet.get("requested_counterparty")
        ),
        "tracking_statuses": _single_or_empty(packet.get("tracking_status")),
        "target_signal_types": _strings(packet.get("target_signal_types")),
        "required_read_api_fields": _strings(packet.get("required_read_api_fields")),
        "application_urls": _strings(packet.get("application_urls")),
        "candidate_source_urls": _strings(packet.get("candidate_source_urls")),
        "accepted_completion_statuses": _strings(item.get("accepted_statuses")),
        "private_dispatch_manifest_section": "source_contract_evidence",
        "private_dispatch_manifest_key_fields": ["county", "gate"],
        "follow_up_due_at_required": True,
        "dispatch_template_file": "local-source-source-contract-dispatch-template.json",
        "request_packet_file": "local-source-official-request-packets.md",
    }


def _source_contract_packet_lookup(
    packets: tuple[dict[str, Any], ...],
) -> dict[tuple[str, str], dict[str, Any]]:
    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for packet in packets:
        for target in packet.get("completion_evidence_targets", []):
            if not isinstance(target, dict):
                continue
            if str(target.get("manifest_section", "")) != "source_contract_evidence":
                continue
            key = (str(target.get("county", "")), str(target.get("gate", "")))
            lookup.setdefault(key, packet)
    return lookup


def _accepted_statuses_from_targets(targets: list[dict[str, Any]]) -> list[str]:
    statuses: set[str] = set()
    for target in targets:
        statuses.update(_strings(target.get("accepted_statuses")))
    return sorted(statuses)


def _single_or_empty(value: Any) -> list[str]:
    text = str(value or "")
    return [text] if text else []


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    return [str(item) for item in value if str(item)]


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _summary_markdown(
    *,
    captured_at: str,
    summary: dict[str, int],
    file_names: tuple[str, ...],
) -> str:
    remaining_completion_gates = _remaining_completion_gates(summary)
    remaining_completion_gates_text = (
        ", ".join(remaining_completion_gates)
        if remaining_completion_gates
        else "none"
    )
    lines = [
        "# Local Source Request Packet Bundle",
        "",
        f"- captured_at: {captured_at}",
        f"- remaining_completion_gates: {remaining_completion_gates_text}",
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


def _remaining_completion_gates(summary: dict[str, int]) -> list[str]:
    gates: list[str] = []
    if summary["signal_gap_county_item_count"]:
        gates.append("required_signal_families")
    if summary["source_contract_completion_target_count"]:
        gates.append("official_authorization_and_contracts")
    return gates


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
    if name.endswith("request-dispatch-evidence-draft.json"):
        return "single private dispatch evidence draft for LOCAL_SOURCE_REQUEST_DISPATCH_EVIDENCE_B64 after review"
    if name.endswith("dispatch-coverage-checklist.json"):
        return "public-safe checklist for private dispatch evidence coverage"
    if name.endswith("request-dispatch-queue.json"):
        return "public-safe queue of grouped official request dispatch work"
    return "request packet bundle artifact"


if __name__ == "__main__":
    raise SystemExit(main())
