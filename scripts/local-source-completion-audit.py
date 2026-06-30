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
    print(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True))

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
        _validate_local_evidence_ref(
            item.get("evidence_ref"),
            field=f"production_gate_evidence[{evidence_index}].evidence_ref",
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


def _validate_local_evidence_ref(value: Any, *, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        return
    evidence_ref = value.strip()
    if "://" in evidence_ref:
        return

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


if __name__ == "__main__":
    raise SystemExit(main())
