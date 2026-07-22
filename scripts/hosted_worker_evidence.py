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

INPUT_SCHEMA_VERSION = "hosted-worker-evidence-input/v1"
EVIDENCE_SCHEMA_VERSION = "hosted-worker-evidence/v1"
COMPLETION_EVIDENCE_SCHEMA_VERSION = "local-source-completion-evidence/v1"
HOSTED_WORKER_GATE_KEY = "hosted_worker_persisted_evidence"
REQUIREMENTS = (
    "freshness_policy",
    "raw_snapshot_retention_policy",
    "monitored_scheduler_cadence",
    "hosted_egress_review",
    "worker_persisted_evidence_path",
)
ACCEPTED_STATUS = "verified"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate hosted worker persistence evidence and optionally emit a "
            "local-source-completion-evidence/v1 overlay for "
            "hosted_worker_persisted_evidence."
        )
    )
    parser.add_argument("--manifest-json")
    parser.add_argument(
        "--captured-at",
        help="Optional ISO 8601 timestamp for generated manifest templates.",
    )
    parser.add_argument(
        "--template-output",
        help=(
            "Optional path for a pending hosted-worker-evidence-input/v1 "
            "manifest template covering every hosted worker requirement."
        ),
    )
    parser.add_argument(
        "--evidence-output",
        help="Optional normalized hosted-worker-evidence/v1 artifact path.",
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

    if args.template_output:
        captured_at = args.captured_at or datetime.now(UTC).replace(microsecond=0).isoformat()
        _write_json(
            args.template_output,
            build_manifest_template(captured_at=captured_at),
        )
        print("HOSTED_WORKER_EVIDENCE_TEMPLATE written")
        return 0

    if not args.manifest_json:
        parser.error("--manifest-json is required unless --template-output is used")

    manifest = _load_json(Path(args.manifest_json))
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
        print("HOSTED_WORKER_EVIDENCE failed")
        for failure in failures:
            print(f"- {failure}")
        return 1

    if args.completion_evidence_output:
        _write_json(
            args.completion_evidence_output,
            build_completion_evidence_overlay(
                captured_at=captured_at,
                evidence_ref=str(Path(args.evidence_output)),
                hosted_worker_evidence=evidence["hosted_worker_evidence"],
            ),
        )

    print("HOSTED_WORKER_EVIDENCE passed")
    return 0


def build_evidence_artifact(
    *,
    manifest: Mapping[str, Any],
    captured_at: str,
    status: str,
    failures: list[str],
) -> dict[str, Any]:
    hosted_worker_evidence = {
        requirement: _normalized_requirement_evidence(requirement, manifest)
        for requirement in REQUIREMENTS
        if isinstance(manifest.get(requirement), Mapping)
    }
    completion_evidence_targets = []
    if status == "passed":
        completion_evidence_targets = [
            {
                "gate_key": HOSTED_WORKER_GATE_KEY,
                "status": "accepted",
                "satisfied_requirements": list(REQUIREMENTS),
                "requirement_evidence": _requirement_evidence(
                    evidence_ref="<evidence-output>",
                    hosted_worker_evidence=hosted_worker_evidence,
                ),
            }
        ]
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "captured_at": captured_at,
        "status": status,
        "hosted_worker_evidence": hosted_worker_evidence,
        "completion_evidence_targets": completion_evidence_targets,
        "failures": failures,
    }


def build_completion_evidence_overlay(
    *,
    captured_at: str,
    evidence_ref: str,
    hosted_worker_evidence: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": COMPLETION_EVIDENCE_SCHEMA_VERSION,
        "captured_at": captured_at,
        "signal_family_gap_evidence": [],
        "source_contract_evidence": [],
        "production_gate_evidence": [
            {
                "gate_key": HOSTED_WORKER_GATE_KEY,
                "status": "accepted",
                "evidence_ref": evidence_ref,
                "satisfied_requirements": list(REQUIREMENTS),
                "requirement_evidence": _requirement_evidence(
                    evidence_ref=evidence_ref,
                    hosted_worker_evidence=hosted_worker_evidence,
                ),
            }
        ],
    }


def build_manifest_template(*, captured_at: str) -> dict[str, Any]:
    return {
        "schema_version": INPUT_SCHEMA_VERSION,
        "captured_at": captured_at,
        "template_status": "pending_private_evidence",
        "notes": [
            "Fill this template only after hosted worker policy, scheduler, egress, and persisted evidence are accepted.",
            "Keep filled private evidence refs in private ops storage; do not commit completed private evidence.",
            "The default pending status is intentionally rejected by this CLI and by the completion audit.",
        ],
        "freshness_policy": {
            "status": "pending",
            "accepted_status": ACCEPTED_STATUS,
            "evidence_ref": "private-ops://hosted-worker/freshness_policy",
            "observed_at": "REPLACE_WITH_OBSERVED_AT",
            "max_lag_minutes": "REPLACE_WITH_MAX_LAG_MINUTES",
        },
        "raw_snapshot_retention_policy": {
            "status": "pending",
            "accepted_status": ACCEPTED_STATUS,
            "evidence_ref": "private-ops://hosted-worker/raw_snapshot_retention_policy",
            "reviewed_at": "REPLACE_WITH_REVIEWED_AT",
            "retention_days": "REPLACE_WITH_RETENTION_DAYS",
        },
        "monitored_scheduler_cadence": {
            "status": "pending",
            "accepted_status": ACCEPTED_STATUS,
            "evidence_ref": "private-ops://hosted-worker/monitored_scheduler_cadence",
            "observed_at": "REPLACE_WITH_OBSERVED_AT",
            "cadence": "REPLACE_WITH_ISO_8601_DURATION",
        },
        "hosted_egress_review": {
            "status": "pending",
            "accepted_status": ACCEPTED_STATUS,
            "evidence_ref": "private-ops://hosted-worker/hosted_egress_review",
            "reviewed_at": "REPLACE_WITH_REVIEWED_AT",
            "reviewer": "REPLACE_WITH_REVIEWER_OR_TEAM",
        },
        "worker_persisted_evidence_path": {
            "status": "pending",
            "accepted_status": ACCEPTED_STATUS,
            "evidence_ref": "private-ops://hosted-worker/worker_persisted_evidence_path",
            "observed_at": "REPLACE_WITH_OBSERVED_AT",
            "adapter_keys": ["REPLACE_WITH_ADAPTER_KEY"],
        },
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


def _validate_manifest(manifest: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    if manifest.get("schema_version") != INPUT_SCHEMA_VERSION:
        failures.append(f"schema_version must be {INPUT_SCHEMA_VERSION}")
    if not _non_empty_string(manifest.get("captured_at")):
        failures.append("captured_at is required")
    failures.extend(_validate_freshness_policy(manifest))
    failures.extend(_validate_raw_snapshot_retention(manifest))
    failures.extend(_validate_scheduler_cadence(manifest))
    failures.extend(_validate_hosted_egress_review(manifest))
    failures.extend(_validate_worker_persisted_path(manifest))
    return failures


def _validate_freshness_policy(manifest: Mapping[str, Any]) -> list[str]:
    requirement = "freshness_policy"
    item = manifest.get(requirement)
    if not isinstance(item, Mapping):
        return [f"{requirement} is required"]
    failures = _validate_common_requirement(item, requirement)
    if not _non_empty_string(item.get("observed_at")):
        failures.append(f"{requirement}.observed_at is required")
    max_lag_minutes = item.get("max_lag_minutes")
    if not isinstance(max_lag_minutes, int) or max_lag_minutes <= 0:
        failures.append(f"{requirement}.max_lag_minutes must be greater than 0")
    return failures


def _validate_raw_snapshot_retention(manifest: Mapping[str, Any]) -> list[str]:
    requirement = "raw_snapshot_retention_policy"
    item = manifest.get(requirement)
    if not isinstance(item, Mapping):
        return [f"{requirement} is required"]
    failures = _validate_common_requirement(item, requirement)
    if not _non_empty_string(item.get("reviewed_at")):
        failures.append(f"{requirement}.reviewed_at is required")
    retention_days = item.get("retention_days")
    if not isinstance(retention_days, int) or retention_days <= 0:
        failures.append(f"{requirement}.retention_days must be greater than 0")
    return failures


def _validate_scheduler_cadence(manifest: Mapping[str, Any]) -> list[str]:
    requirement = "monitored_scheduler_cadence"
    item = manifest.get(requirement)
    if not isinstance(item, Mapping):
        return [f"{requirement} is required"]
    failures = _validate_common_requirement(item, requirement)
    if not _non_empty_string(item.get("observed_at")):
        failures.append(f"{requirement}.observed_at is required")
    if not _non_empty_string(item.get("cadence")):
        failures.append(f"{requirement}.cadence is required")
    return failures


def _validate_hosted_egress_review(manifest: Mapping[str, Any]) -> list[str]:
    requirement = "hosted_egress_review"
    item = manifest.get(requirement)
    if not isinstance(item, Mapping):
        return [f"{requirement} is required"]
    failures = _validate_common_requirement(item, requirement)
    if not _non_empty_string(item.get("reviewed_at")):
        failures.append(f"{requirement}.reviewed_at is required")
    if not _non_empty_string(item.get("reviewer")):
        failures.append(f"{requirement}.reviewer is required")
    return failures


def _validate_worker_persisted_path(manifest: Mapping[str, Any]) -> list[str]:
    requirement = "worker_persisted_evidence_path"
    item = manifest.get(requirement)
    if not isinstance(item, Mapping):
        return [f"{requirement} is required"]
    failures = _validate_common_requirement(item, requirement)
    if not _non_empty_string(item.get("observed_at")):
        failures.append(f"{requirement}.observed_at is required")
    adapter_keys = item.get("adapter_keys")
    if not isinstance(adapter_keys, list) or not any(
        _non_empty_string(adapter_key) for adapter_key in adapter_keys
    ):
        failures.append(f"{requirement}.adapter_keys is required")
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
        "evidence_ref",
        "observed_at",
        "reviewed_at",
        "max_lag_minutes",
        "retention_days",
        "cadence",
        "reviewer",
        "adapter_keys",
    )
    return {
        key: item[key]
        for key in allowed_keys
        if key in item and (_non_empty_string(item[key]) or not isinstance(item[key], str))
    }


def _requirement_evidence(
    *,
    evidence_ref: str,
    hosted_worker_evidence: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, str]]:
    details: list[dict[str, str]] = []
    for requirement in REQUIREMENTS:
        item = hosted_worker_evidence[requirement]
        detail = {
            "requirement": requirement,
            "evidence_ref": f"{evidence_ref}#/hosted_worker_evidence/{requirement}",
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
