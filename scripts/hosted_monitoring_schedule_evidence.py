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


EVIDENCE_SCHEMA_VERSION = "hosted-monitoring-schedule-evidence/v1"
COMPLETION_EVIDENCE_SCHEMA_VERSION = "local-source-completion-evidence/v1"
MONITORING_GATE_KEY = "production_monitoring_and_alerting"
SCHEDULED_FRESHNESS_REQUIREMENT = "scheduled_freshness_checks"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Emit public-safe evidence for the Hosted Monitoring schedule event. "
            "Only real schedule events produce completion evidence for "
            "scheduled_freshness_checks."
        )
    )
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--workflow-name", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--cron", required=True)
    parser.add_argument(
        "--captured-at",
        help="ISO-8601 timestamp for the evidence. Defaults to current UTC time.",
    )
    parser.add_argument("--evidence-output", required=True)
    parser.add_argument("--completion-evidence-output")
    args = parser.parse_args()

    captured_at = args.captured_at or datetime.now(UTC).replace(microsecond=0).isoformat()
    is_schedule = args.event_name == "schedule"
    evidence = build_evidence_artifact(
        event_name=args.event_name,
        workflow_name=args.workflow_name,
        run_id=args.run_id,
        run_url=args.run_url,
        cron=args.cron,
        captured_at=captured_at,
        status="passed" if is_schedule else "skipped",
    )
    _write_json(args.evidence_output, evidence)

    if is_schedule and args.completion_evidence_output:
        _write_json(
            args.completion_evidence_output,
            build_completion_evidence_overlay(
                captured_at=captured_at,
                evidence_ref=str(Path(args.evidence_output)),
            ),
        )

    if is_schedule:
        print("HOSTED_MONITORING_SCHEDULE_EVIDENCE passed")
    else:
        print("HOSTED_MONITORING_SCHEDULE_EVIDENCE skipped")
    return 0


def build_evidence_artifact(
    *,
    event_name: str,
    workflow_name: str,
    run_id: str,
    run_url: str,
    cron: str,
    captured_at: str,
    status: str,
) -> dict[str, Any]:
    completion_evidence_targets: list[dict[str, Any]] = []
    if status == "passed":
        completion_evidence_targets = [
            {
                "gate_key": MONITORING_GATE_KEY,
                "status": "accepted",
                "satisfied_requirements": [SCHEDULED_FRESHNESS_REQUIREMENT],
                "requirement_evidence": [
                    {
                        "requirement": SCHEDULED_FRESHNESS_REQUIREMENT,
                        "evidence_ref": "<evidence-output>#/schedule_evidence",
                        "observed_at": captured_at,
                    }
                ],
            }
        ]
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "captured_at": captured_at,
        "status": status,
        "schedule_evidence": {
            "event_name": event_name,
            "workflow_name": workflow_name,
            "run_id": run_id,
            "run_url": run_url,
            "cron": cron,
            "observed_at": captured_at,
        },
        "completion_evidence_targets": completion_evidence_targets,
        "failures": [],
    }


def build_completion_evidence_overlay(
    *,
    captured_at: str,
    evidence_ref: str,
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
                "satisfied_requirements": [SCHEDULED_FRESHNESS_REQUIREMENT],
                "requirement_evidence": [
                    {
                        "requirement": SCHEDULED_FRESHNESS_REQUIREMENT,
                        "evidence_ref": f"{evidence_ref}#/schedule_evidence",
                        "observed_at": captured_at,
                    }
                ],
            }
        ],
    }


def _write_json(output_path: str, payload: Mapping[str, Any]) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
