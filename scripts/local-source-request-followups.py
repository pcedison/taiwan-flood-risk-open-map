#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


COMPLETION_EVIDENCE_SCHEMA_VERSION = "local-source-completion-evidence/v1"
FOLLOWUPS_SCHEMA_VERSION = "local-source-request-followups/v1"
DISPATCHED_STATUS = "request_dispatched"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Summarize local-source official request follow-ups from private "
            "request-dispatch completion evidence overlays without printing "
            "private evidence refs."
        )
    )
    parser.add_argument(
        "--completion-evidence-json",
        action="append",
        required=True,
        help=(
            "local-source-completion-evidence/v1 JSON overlay. Repeat to merge "
            "signal-gap and source-contract dispatch overlays."
        ),
    )
    parser.add_argument(
        "--as-of",
        required=True,
        help="ISO-8601 timestamp used to classify pending and overdue follow-ups.",
    )
    parser.add_argument(
        "--output",
        help="Optional path to write the public-safe follow-up JSON report.",
    )
    parser.add_argument(
        "--fail-on-overdue",
        action="store_true",
        help="Exit with status 1 when one or more follow-ups are overdue.",
    )
    args = parser.parse_args()

    as_of = _parse_iso_datetime(args.as_of, field="--as-of")
    overlays = [_load_json(Path(path)) for path in args.completion_evidence_json]
    report = _build_followup_report(overlays, as_of=as_of, as_of_text=args.as_of)
    content = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
    print(content, end="")

    if args.fail_on_overdue and report["summary"]["overdue_count"]:
        return 1
    return 0


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"{path}: completion evidence JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"{path}: completion evidence JSON must be an object")
    if payload.get("schema_version") != COMPLETION_EVIDENCE_SCHEMA_VERSION:
        raise SystemExit(
            f"{path}: schema_version must be {COMPLETION_EVIDENCE_SCHEMA_VERSION!r}"
        )
    return payload


def _build_followup_report(
    overlays: list[dict[str, Any]],
    *,
    as_of: datetime,
    as_of_text: str,
) -> dict[str, Any]:
    dispatch_items = _dispatch_items(overlays)
    scheduled_items = [
        item for item in dispatch_items if isinstance(item.get("follow_up_due_at"), str)
    ]
    overdue_items = [
        item
        for item in scheduled_items
        if _parse_iso_datetime(
            str(item["follow_up_due_at"]),
            field=f"{item['section']}.follow_up_due_at",
        )
        <= as_of
    ]
    pending_count = len(scheduled_items) - len(overdue_items)
    next_follow_up_due_at = min(
        (str(item["follow_up_due_at"]) for item in scheduled_items),
        default=None,
    )
    return {
        "schema_version": FOLLOWUPS_SCHEMA_VERSION,
        "as_of": as_of_text,
        "summary": {
            "dispatch_item_count": len(dispatch_items),
            "follow_up_scheduled_count": len(scheduled_items),
            "missing_follow_up_count": len(dispatch_items) - len(scheduled_items),
            "pending_count": pending_count,
            "overdue_count": len(overdue_items),
            "next_follow_up_due_at": next_follow_up_due_at,
        },
        "overdue_items": [
            _public_followup_item(item)
            for item in sorted(
                overdue_items,
                key=lambda item: (
                    str(item.get("follow_up_due_at", "")),
                    str(item.get("section", "")),
                    str(item.get("county", "")),
                ),
            )
        ],
    }


def _dispatch_items(overlays: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for overlay in overlays:
        items.extend(
            _section_dispatch_items(
                overlay.get("signal_family_gap_evidence"),
                section="signal_family_gap_evidence",
            )
        )
        items.extend(
            _section_dispatch_items(
                overlay.get("source_contract_evidence"),
                section="source_contract_evidence",
            )
        )
    return items


def _section_dispatch_items(value: Any, *, section: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SystemExit(f"{section}: completion evidence field must be an array")
    items: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise SystemExit(f"{section}[{index}] must be an object")
        if item.get("status") != DISPATCHED_STATUS:
            continue
        public_item = {
            "section": section,
            "county": str(item.get("county", "")),
        }
        if section == "signal_family_gap_evidence":
            public_item["signal_type"] = str(item.get("signal_type", ""))
        if section == "source_contract_evidence":
            public_item["gate"] = str(item.get("gate", ""))
        if isinstance(item.get("follow_up_due_at"), str):
            public_item["follow_up_due_at"] = str(item["follow_up_due_at"])
        items.append(public_item)
    return items


def _public_followup_item(item: dict[str, Any]) -> dict[str, str]:
    output = {
        "section": str(item["section"]),
        "county": str(item["county"]),
    }
    if "signal_type" in item:
        output["signal_type"] = str(item["signal_type"])
    if "gate" in item:
        output["gate"] = str(item["gate"])
    output["follow_up_due_at"] = str(item["follow_up_due_at"])
    return output


def _parse_iso_datetime(value: str, *, field: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SystemExit(f"{field}: expected ISO-8601 timestamp") from exc


if __name__ == "__main__":
    raise SystemExit(main())
