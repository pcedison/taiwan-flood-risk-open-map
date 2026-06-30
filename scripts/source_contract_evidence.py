#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any, Mapping


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
API_APP = ROOT / "apps" / "api"
sys.path.insert(0, str(API_APP))

from app.domain.realtime.local_source_action_plan import (  # noqa: E402
    ACCEPTED_SOURCE_CONTRACT_EVIDENCE_STATUSES,
    build_local_source_action_plan,
)
from app.domain.realtime.local_source_coverage import (  # noqa: E402
    list_local_source_coverage,
)


INPUT_SCHEMA_VERSION = "source-contract-evidence-input/v1"
EVIDENCE_SCHEMA_VERSION = "source-contract-evidence/v1"
COMPLETION_EVIDENCE_SCHEMA_VERSION = "local-source-completion-evidence/v1"
GATE_BUCKETS = (
    ("authorization_request", "authorization_requests"),
    ("metadata_release_monitor", "metadata_release_monitors"),
    ("public_api_contract_review", "public_api_contract_reviews"),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate private source authorization/contract evidence and "
            "optionally emit a local-source-completion-evidence/v1 overlay."
        )
    )
    parser.add_argument("--manifest-json", required=True)
    parser.add_argument(
        "--evidence-output",
        help="Optional normalized source-contract-evidence/v1 artifact path.",
    )
    parser.add_argument(
        "--completion-evidence-output",
        help=(
            "Optional completion evidence overlay path. Requires a complete, "
            "accepted manifest for every currently required source contract item."
        ),
    )
    args = parser.parse_args(argv)

    manifest = _load_json(Path(args.manifest_json))
    captured_at = _captured_at(manifest)
    required_keys = _required_source_contract_keys()
    failures = _validate_manifest(manifest, required_keys=required_keys)

    status = "failed" if failures else "passed"
    evidence = build_evidence_artifact(
        manifest=manifest,
        captured_at=captured_at,
        required_keys=required_keys,
        status=status,
        failures=failures,
    )
    _write_json(args.evidence_output, evidence)

    if failures:
        print("SOURCE_CONTRACT_EVIDENCE failed")
        for failure in failures:
            print(f"- {failure}")
        return 1

    if args.completion_evidence_output:
        _write_json(
            args.completion_evidence_output,
            build_completion_evidence_overlay(
                captured_at=captured_at,
                source_contract_evidence=evidence["source_contract_evidence"],
            ),
        )

    print("SOURCE_CONTRACT_EVIDENCE passed")
    return 0


def build_evidence_artifact(
    *,
    manifest: Mapping[str, Any],
    captured_at: str,
    required_keys: set[tuple[str, str]],
    status: str,
    failures: list[str],
) -> dict[str, Any]:
    entries = _normalized_source_contract_entries(manifest)
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "captured_at": captured_at,
        "status": status,
        "required_source_contract_count": len(required_keys),
        "source_contract_evidence": entries,
        "completion_evidence_targets": (
            [
                {
                    "manifest_section": "source_contract_evidence",
                    "status": "accepted",
                    "required_source_contract_count": len(required_keys),
                }
            ]
            if status == "passed"
            else []
        ),
        "failures": failures,
    }


def build_completion_evidence_overlay(
    *,
    captured_at: str,
    source_contract_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": COMPLETION_EVIDENCE_SCHEMA_VERSION,
        "captured_at": captured_at,
        "signal_family_gap_evidence": [],
        "source_contract_evidence": source_contract_evidence,
        "production_gate_evidence": [],
    }


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SystemExit(f"{path}: manifest JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"{path}: manifest JSON must be an object")
    return payload


def _captured_at(manifest: Mapping[str, Any]) -> str:
    captured_at = manifest.get("captured_at")
    if _non_empty_string(captured_at):
        return str(captured_at).strip()
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _required_source_contract_keys() -> set[tuple[str, str]]:
    plan = build_local_source_action_plan(list_local_source_coverage())
    keys: set[tuple[str, str]] = set()
    for gate, bucket in GATE_BUCKETS:
        for item in plan[bucket]:
            keys.add((str(item["county"]), gate))
    return keys


def _validate_manifest(
    manifest: Mapping[str, Any],
    *,
    required_keys: set[tuple[str, str]],
) -> list[str]:
    failures: list[str] = []
    if manifest.get("schema_version") != INPUT_SCHEMA_VERSION:
        failures.append(f"schema_version must be {INPUT_SCHEMA_VERSION}")
    if not _non_empty_string(manifest.get("captured_at")):
        failures.append("captured_at is required")

    raw_entries = manifest.get("source_contract_evidence")
    if not isinstance(raw_entries, list):
        return [*failures, "source_contract_evidence must be an array"]

    accepted_keys: set[tuple[str, str]] = set()
    seen_keys: set[tuple[str, str]] = set()
    for index, item in enumerate(raw_entries):
        if not isinstance(item, Mapping):
            failures.append(f"source_contract_evidence[{index}] must be an object")
            continue
        key = _entry_key(item)
        failures.extend(_validate_entry(item, index=index, required_keys=required_keys))
        if key is None:
            continue
        if key in seen_keys:
            failures.append(
                "source_contract_evidence"
                f"[{index}] duplicates {key[0]}/{key[1]}"
            )
        seen_keys.add(key)
        if _entry_is_accepted(item):
            accepted_keys.add(key)

    missing_keys = sorted(required_keys - accepted_keys, key=lambda key: (key[1], key[0]))
    for county, gate in missing_keys:
        failures.append(f"missing required source contract evidence: {county}/{gate}")
    return failures


def _validate_entry(
    item: Mapping[str, Any],
    *,
    index: int,
    required_keys: set[tuple[str, str]],
) -> list[str]:
    failures: list[str] = []
    county = item.get("county")
    gate = item.get("gate")
    status = item.get("status")
    if not _non_empty_string(county):
        failures.append(f"source_contract_evidence[{index}].county is required")
    if gate not in {gate for gate, _bucket in GATE_BUCKETS}:
        failures.append(f"source_contract_evidence[{index}].gate is invalid")
    if status not in ACCEPTED_SOURCE_CONTRACT_EVIDENCE_STATUSES:
        accepted = ", ".join(sorted(ACCEPTED_SOURCE_CONTRACT_EVIDENCE_STATUSES))
        failures.append(
            f"source_contract_evidence[{index}].status must be one of {accepted}"
        )
    if not _non_empty_string(item.get("evidence_ref")):
        failures.append(f"source_contract_evidence[{index}].evidence_ref is required")
    if not _non_empty_string(item.get("reviewed_at")):
        failures.append(f"source_contract_evidence[{index}].reviewed_at is required")

    key = _entry_key(item)
    if key is not None and key not in required_keys:
        failures.append(
            "source_contract_evidence"
            f"[{index}] is not currently required: {key[0]}/{key[1]}"
        )
    return failures


def _entry_key(item: Mapping[str, Any]) -> tuple[str, str] | None:
    county = item.get("county")
    gate = item.get("gate")
    if not _non_empty_string(county) or not isinstance(gate, str):
        return None
    return (str(county).strip(), gate.strip())


def _entry_is_accepted(item: Mapping[str, Any]) -> bool:
    return (
        _entry_key(item) is not None
        and item.get("status") in ACCEPTED_SOURCE_CONTRACT_EVIDENCE_STATUSES
        and _non_empty_string(item.get("evidence_ref"))
        and _non_empty_string(item.get("reviewed_at"))
    )


def _normalized_source_contract_entries(
    manifest: Mapping[str, Any],
) -> list[dict[str, Any]]:
    raw_entries = manifest.get("source_contract_evidence")
    if not isinstance(raw_entries, list):
        return []
    entries: list[dict[str, Any]] = []
    allowed_keys = ("county", "gate", "status", "evidence_ref", "reviewed_at", "reviewer")
    for item in raw_entries:
        if not isinstance(item, Mapping):
            continue
        entries.append(
            {
                key: item[key]
                for key in allowed_keys
                if key in item and (_non_empty_string(item[key]) or not isinstance(item[key], str))
            }
        )
    return entries


def _write_json(output_path: str | None, payload: Mapping[str, Any]) -> None:
    if output_path is None:
        return
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


if __name__ == "__main__":
    raise SystemExit(main())
