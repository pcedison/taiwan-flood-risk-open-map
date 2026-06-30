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

INPUT_SCHEMA_VERSION = "hosted-monitoring-evidence-input/v1"
EVIDENCE_SCHEMA_VERSION = "hosted-monitoring-evidence/v1"
COMPLETION_EVIDENCE_SCHEMA_VERSION = "local-source-completion-evidence/v1"
MONITORING_GATE_KEY = "production_monitoring_and_alerting"
REQUIREMENTS = (
    "hosted_alert_routing",
    "scheduled_freshness_checks",
    "worker_scheduler_alert_ownership",
)
ACCEPTED_STATUS = "verified"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate hosted monitoring evidence and optionally emit a "
            "local-source-completion-evidence/v1 overlay for "
            "production_monitoring_and_alerting."
        )
    )
    parser.add_argument("--manifest-json", required=True)
    parser.add_argument(
        "--evidence-output",
        help="Optional normalized hosted-monitoring-evidence/v1 artifact path.",
    )
    parser.add_argument(
        "--completion-evidence-output",
        help=(
            "Optional completion evidence overlay path. Requires "
            "--evidence-output so requirement evidence can point to a passed "
            "local artifact."
        ),
    )
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest_json)
    manifest = _load_json(manifest_path)
    captured_at = _captured_at(manifest)
    failures = _validate_manifest(manifest)

    if args.completion_evidence_output and not args.evidence_output:
        failures.append("--completion-evidence-output requires --evidence-output")

    status = "failed" if failures else "passed"
    evidence = build_evidence_artifact(
        manifest=manifest,
        captured_at=captured_at,
        status=status,
        failures=failures,
    )
    _write_json(args.evidence_output, evidence)

    if failures:
        print("HOSTED_MONITORING_EVIDENCE failed")
        for failure in failures:
            print(f"- {failure}")
        return 1

    if args.completion_evidence_output:
        _write_json(
            args.completion_evidence_output,
            build_completion_evidence_overlay(
                captured_at=captured_at,
                evidence_ref=str(Path(args.evidence_output)),
                monitoring_evidence=evidence["monitoring_evidence"],
            ),
        )

    print("HOSTED_MONITORING_EVIDENCE passed")
    return 0


def build_evidence_artifact(
    *,
    manifest: Mapping[str, Any],
    captured_at: str,
    status: str,
    failures: list[str],
) -> dict[str, Any]:
    monitoring_evidence = {
        requirement: _normalized_requirement_evidence(requirement, manifest)
        for requirement in REQUIREMENTS
        if isinstance(manifest.get(requirement), Mapping)
    }
    completion_evidence_targets = []
    if status == "passed":
        completion_evidence_targets = [
            {
                "gate_key": MONITORING_GATE_KEY,
                "status": "accepted",
                "satisfied_requirements": list(REQUIREMENTS),
                "requirement_evidence": _requirement_evidence(
                    evidence_ref="<evidence-output>",
                    monitoring_evidence=monitoring_evidence,
                ),
            }
        ]
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "captured_at": captured_at,
        "status": status,
        "monitoring_evidence": monitoring_evidence,
        "completion_evidence_targets": completion_evidence_targets,
        "failures": failures,
    }


def build_completion_evidence_overlay(
    *,
    captured_at: str,
    evidence_ref: str,
    monitoring_evidence: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": COMPLETION_EVIDENCE_SCHEMA_VERSION,
        "captured_at": captured_at,
        "signal_family_gap_evidence": [],
        "source_contract_evidence": [],
        "production_gate_evidence": [
            {
                "gate_key": MONITORING_GATE_KEY,
                "status": "accepted",
                "evidence_ref": evidence_ref,
                "satisfied_requirements": list(REQUIREMENTS),
                "requirement_evidence": _requirement_evidence(
                    evidence_ref=evidence_ref,
                    monitoring_evidence=monitoring_evidence,
                ),
            }
        ],
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
    if isinstance(captured_at, str) and captured_at.strip():
        return captured_at.strip()
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _validate_manifest(manifest: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    if manifest.get("schema_version") != INPUT_SCHEMA_VERSION:
        failures.append(f"schema_version must be {INPUT_SCHEMA_VERSION}")
    if not _non_empty_string(manifest.get("captured_at")):
        failures.append("captured_at is required")
    failures.extend(_validate_owner_requirement(manifest, "hosted_alert_routing"))
    failures.extend(_validate_scheduled_freshness(manifest))
    failures.extend(
        _validate_owner_requirement(manifest, "worker_scheduler_alert_ownership")
    )
    return failures


def _validate_owner_requirement(
    manifest: Mapping[str, Any],
    requirement: str,
) -> list[str]:
    item = manifest.get(requirement)
    if not isinstance(item, Mapping):
        return [f"{requirement} is required"]
    failures = _validate_common_requirement(item, requirement)
    if not _non_empty_string(item.get("owner")):
        failures.append(f"{requirement}.owner is required")
    if not _non_empty_string(item.get("reviewed_at")):
        failures.append(f"{requirement}.reviewed_at is required")
    return failures


def _validate_scheduled_freshness(manifest: Mapping[str, Any]) -> list[str]:
    requirement = "scheduled_freshness_checks"
    item = manifest.get(requirement)
    if not isinstance(item, Mapping):
        return [f"{requirement} is required"]
    failures = _validate_common_requirement(item, requirement)
    if not _non_empty_string(item.get("cadence")):
        failures.append(f"{requirement}.cadence is required")
    if not _non_empty_string(item.get("observed_at")):
        failures.append(f"{requirement}.observed_at is required")
    return failures


def _validate_common_requirement(
    item: Mapping[str, Any],
    requirement: str,
) -> list[str]:
    failures: list[str] = []
    if item.get("status") != ACCEPTED_STATUS:
        failures.append(f"{requirement}.status must be {ACCEPTED_STATUS}")
    if not _non_empty_string(item.get("evidence_ref")):
        failures.append(f"{requirement}.evidence_ref is required")
    return failures


def _normalized_requirement_evidence(
    requirement: str,
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    item = manifest[requirement]
    assert isinstance(item, Mapping)
    allowed_keys = (
        "status",
        "owner",
        "cadence",
        "evidence_ref",
        "observed_at",
        "reviewed_at",
    )
    return {
        key: item[key]
        for key in allowed_keys
        if _non_empty_string(item.get(key))
    }


def _requirement_evidence(
    *,
    evidence_ref: str,
    monitoring_evidence: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, str]]:
    details: list[dict[str, str]] = []
    for requirement in REQUIREMENTS:
        item = monitoring_evidence[requirement]
        detail = {
            "requirement": requirement,
            "evidence_ref": f"{evidence_ref}#/monitoring_evidence/{requirement}",
        }
        if _non_empty_string(item.get("observed_at")):
            detail["observed_at"] = str(item["observed_at"])
        if _non_empty_string(item.get("reviewed_at")):
            detail["reviewed_at"] = str(item["reviewed_at"])
        details.append(detail)
    return details


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
