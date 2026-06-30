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


COMPLETION_EVIDENCE_SCHEMA_VERSION = "local-source-completion-evidence/v1"
ACCEPTED_PRODUCTION_GATE_EVIDENCE_STATUSES = {"accepted", "satisfied", "verified"}
HOSTED_SOURCE_FRESHNESS_SCHEMA_VERSION = "hosted-source-freshness-smoke/v1"
HOSTED_WORKER_GATE_KEY = "hosted_worker_persisted_evidence"
HOSTED_SOURCE_FRESHNESS_REQUIREMENTS = {
    "freshness_policy",
    "worker_persisted_evidence_path",
}
REQUIRED_HOSTED_SOURCE_ADAPTER_KEYS = (
    "official.cwa.rainfall",
    "official.cwa.tide_level",
    "official.wra.water_level",
    "official.ncdr.cap",
    "official.wra_iow.flood_depth",
    "official.civil_iot.flood_sensor",
    "official.civil_iot.sewer_water_level",
    "official.civil_iot.pump_water_level",
    "official.civil_iot.gate_water_level",
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Print the nationwide local-source completion audit. Optionally apply "
            "a private completion evidence JSON manifest."
        )
    )
    parser.add_argument(
        "--completion-evidence-json",
        action="append",
        help=(
            "Optional local-source-completion-evidence/v1 JSON file. Repeat this "
            "option to merge public-risk, hosted-source, monitoring, and private "
            "official-response evidence overlays. The command prints only "
            "aggregate counts and gate status, not evidence refs. Production "
            "gates must include satisfied_requirements plus matching "
            "requirement_evidence entries for each accepted requirement. Local "
            "JSON evidence refs are validated; private/remote refs are not read."
        ),
    )
    parser.add_argument(
        "--fail-on-incomplete",
        action="store_true",
        help="Exit with status 1 when the resulting completion audit is incomplete.",
    )
    parser.add_argument(
        "--output",
        help=(
            "Optional path to write the aggregate completion-audit JSON artifact. "
            "The same JSON is still printed to stdout."
        ),
    )
    parser.add_argument(
        "--markdown-output",
        help=(
            "Optional path to write a public-safe Markdown summary of the "
            "aggregate completion audit."
        ),
    )
    args = parser.parse_args()

    completion_evidence = None
    if args.completion_evidence_json:
        completion_evidence = _load_and_merge_json(
            [Path(path) for path in args.completion_evidence_json]
        )
        _validate_local_evidence_refs(completion_evidence)

    plan = build_local_source_action_plan(
        list_local_source_coverage(),
        completion_evidence=completion_evidence,
    )
    audit = plan["completion_audit"]
    audit_json = json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(f"{audit_json}\n", encoding="utf-8")
    if args.markdown_output:
        markdown_output_path = Path(args.markdown_output)
        markdown_output_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_output_path.write_text(
            _render_markdown_audit(audit),
            encoding="utf-8",
        )
    print(audit_json)

    if args.fail_on_incomplete and audit["overall_status"] != "satisfied":
        return 1
    return 0


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise SystemExit(f"{path}: completion evidence JSON must be an object")
    return payload


def _load_and_merge_json(paths: list[Path]) -> dict[str, Any]:
    overlays = [_load_json(path) for path in paths]
    if len(overlays) == 1:
        return overlays[0]

    for path, overlay in zip(paths, overlays, strict=True):
        schema_version = overlay.get("schema_version")
        if schema_version != COMPLETION_EVIDENCE_SCHEMA_VERSION:
            raise SystemExit(
                f"{path}: schema_version must be {COMPLETION_EVIDENCE_SCHEMA_VERSION!r}"
            )

    captured_values = [
        str(overlay["captured_at"])
        for overlay in overlays
        if isinstance(overlay.get("captured_at"), str)
    ]
    return {
        "schema_version": COMPLETION_EVIDENCE_SCHEMA_VERSION,
        "captured_at": max(captured_values) if captured_values else None,
        "signal_family_gap_evidence": _merged_list(
            overlays,
            key="signal_family_gap_evidence",
        ),
        "source_contract_evidence": _merged_list(
            overlays,
            key="source_contract_evidence",
        ),
        "production_gate_evidence": _merged_list(
            overlays,
            key="production_gate_evidence",
        ),
    }


def _merged_list(overlays: list[dict[str, Any]], *, key: str) -> list[Any]:
    merged: list[Any] = []
    for overlay in overlays:
        value = overlay.get(key)
        if value is None:
            continue
        if not isinstance(value, list):
            raise SystemExit(f"{key}: completion evidence field must be an array")
        merged.extend(value)
    return merged


def _validate_local_evidence_refs(completion_evidence: dict[str, Any]) -> None:
    production_gate_evidence = completion_evidence.get("production_gate_evidence")
    if not isinstance(production_gate_evidence, list):
        return

    for evidence_index, item in enumerate(production_gate_evidence):
        if not isinstance(item, dict):
            continue
        if item.get("status") not in ACCEPTED_PRODUCTION_GATE_EVIDENCE_STATUSES:
            continue
        payload = _validate_local_evidence_ref(
            item.get("evidence_ref"),
            field=f"production_gate_evidence[{evidence_index}].evidence_ref",
        )
        _validate_hosted_source_backbone_evidence(
            item,
            evidence_index=evidence_index,
            payload=payload,
        )
        requirement_evidence = item.get("requirement_evidence")
        if not isinstance(requirement_evidence, list):
            continue
        for detail_index, detail in enumerate(requirement_evidence):
            if not isinstance(detail, dict):
                continue
            _validate_local_evidence_ref(
                detail.get("evidence_ref"),
                field=(
                    "production_gate_evidence"
                    f"[{evidence_index}].requirement_evidence"
                    f"[{detail_index}].evidence_ref"
                ),
            )


def _validate_local_evidence_ref(value: Any, *, field: str) -> dict[str, Any] | None:
    if not isinstance(value, str) or not value.strip():
        return None
    evidence_ref = value.strip()
    if "://" in evidence_ref:
        return None

    path_part, pointer = _split_evidence_ref(evidence_ref)
    if not path_part:
        raise SystemExit(f"{field}: local evidence_ref path is required")

    artifact_path = _local_evidence_path(path_part)
    if not artifact_path.exists():
        raise SystemExit(f"{field}: local evidence_ref file does not exist: {path_part}")
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SystemExit(f"{field}: local evidence_ref JSON is invalid: {path_part}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"{field}: local evidence_ref JSON must be an object: {path_part}")

    status = payload.get("status")
    if status is not None and status != "passed":
        raise SystemExit(
            f"{field}: local evidence_ref status must be 'passed': {path_part}"
        )
    if pointer:
        _resolve_json_pointer(payload, pointer, field=field, evidence_ref=evidence_ref)
    return payload


def _validate_hosted_source_backbone_evidence(
    item: dict[str, Any],
    *,
    evidence_index: int,
    payload: dict[str, Any] | None,
) -> None:
    if item.get("gate_key") != HOSTED_WORKER_GATE_KEY or payload is None:
        return
    if payload.get("schema_version") != HOSTED_SOURCE_FRESHNESS_SCHEMA_VERSION:
        return

    requirements = item.get("satisfied_requirements")
    if not isinstance(requirements, list):
        return
    if HOSTED_SOURCE_FRESHNESS_REQUIREMENTS.isdisjoint(str(req) for req in requirements):
        return

    required_keys = _adapter_key_set(payload.get("required_adapter_keys"))
    checked_keys = _checked_source_adapter_key_set(payload.get("checked_sources"))
    expected_keys = set(REQUIRED_HOSTED_SOURCE_ADAPTER_KEYS)
    missing_required = sorted(expected_keys - required_keys)
    missing_checked = sorted(expected_keys - checked_keys)
    if not missing_required and not missing_checked:
        return

    details = []
    if missing_required:
        details.append(f"missing required_adapter_keys: {', '.join(missing_required)}")
    if missing_checked:
        details.append(f"missing checked_sources: {', '.join(missing_checked)}")
    raise SystemExit(
        "production_gate_evidence"
        f"[{evidence_index}].evidence_ref: hosted source freshness evidence "
        f"must cover the full hosted realtime backbone; {'; '.join(details)}"
    )


def _adapter_key_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item) for item in value if isinstance(item, str) and item.strip()}


def _checked_source_adapter_key_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    keys: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        adapter_key = item.get("adapter_key")
        if isinstance(adapter_key, str) and adapter_key.strip():
            keys.add(adapter_key)
    return keys


def _split_evidence_ref(evidence_ref: str) -> tuple[str, str | None]:
    path_part, separator, pointer = evidence_ref.partition("#")
    return path_part, pointer if separator else None


def _local_evidence_path(path_part: str) -> Path:
    normalized = path_part.replace("\\", "/")
    path = Path(normalized)
    if path.is_absolute():
        return path
    return ROOT / normalized


def _resolve_json_pointer(
    payload: Any,
    pointer: str,
    *,
    field: str,
    evidence_ref: str,
) -> Any:
    if pointer == "":
        return payload
    if not pointer.startswith("/"):
        raise SystemExit(f"{field}: local evidence_ref JSON pointer is invalid: {evidence_ref}")
    current = payload
    for raw_part in pointer.lstrip("/").split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        if isinstance(current, list) and part.isdigit():
            index = int(part)
            if index < len(current):
                current = current[index]
                continue
        raise SystemExit(f"{field}: local evidence_ref JSON pointer not found: {evidence_ref}")
    return current


def _render_markdown_audit(audit: dict[str, Any]) -> str:
    lines = [
        "# Local Source Completion Audit",
        "",
        f"- Overall status: {_inline_code(audit.get('overall_status'))}",
    ]
    next_workstreams = audit.get("next_priority_workstreams")
    if isinstance(next_workstreams, list):
        lines.append(f"- Next workstreams: {_inline_code_list(next_workstreams)}")
    lines.extend(["", "## Summary", ""])

    summary = audit.get("summary")
    if isinstance(summary, dict) and summary:
        for key in sorted(summary):
            lines.append(f"- {_inline_code(key)}: {_inline_code(summary[key])}")
    else:
        lines.append("- No summary fields supplied.")

    lines.extend(
        [
            "",
            "## Gate Status",
            "",
            "| Gate | Status | Blocking items | Next workstream |",
            "| --- | --- | --- | --- |",
        ]
    )
    gates = audit.get("gates")
    if isinstance(gates, list):
        for gate in gates:
            if not isinstance(gate, dict):
                continue
            lines.append(
                "| "
                + " | ".join(
                    (
                        _markdown_cell(_inline_code(gate.get("gate_key"))),
                        _markdown_cell(_inline_code(gate.get("status"))),
                        _markdown_cell(
                            _inline_code_list(gate.get("blocking_items"))
                        ),
                        _markdown_cell(_inline_code(gate.get("next_workstream"))),
                    )
                )
                + " |"
            )

    lines.extend(["", "## Evidence Overlay", ""])
    overlay = audit.get("evidence_overlay")
    if isinstance(overlay, dict) and overlay:
        for key in sorted(overlay):
            lines.append(f"- {_inline_code(key)}: {_inline_code(overlay[key])}")
    else:
        lines.append("- No evidence overlay supplied.")

    return "\n".join(lines) + "\n"


def _inline_code(value: Any) -> str:
    if value is None:
        return "`none`"
    if isinstance(value, (list, tuple)):
        return _inline_code_list(value)
    return f"`{str(value).replace('`', '\\`')}`"


def _inline_code_list(value: Any) -> str:
    if not isinstance(value, (list, tuple)) or not value:
        return "`none`"
    return ", ".join(_inline_code(item) for item in value)


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|")


if __name__ == "__main__":
    raise SystemExit(main())
