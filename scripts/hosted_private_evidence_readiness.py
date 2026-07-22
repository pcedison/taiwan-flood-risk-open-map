#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


SCHEMA_VERSION = "hosted-private-evidence-readiness/v1"


@dataclass(frozen=True)
class SecretReadinessSpec:
    name: str
    required_for_completion: bool
    unblocks: tuple[str, ...]
    blocks_completion_gates: tuple[str, ...]
    required_evidence_requirements: tuple[str, ...]
    next_operator_action: str


@dataclass(frozen=True)
class CompletionRouteSpec:
    gate_key: str
    route_key: str
    required_secret_names: tuple[str, ...]
    satisfied_requirements: tuple[str, ...]
    next_operator_action: str


SECRET_SPECS = (
    SecretReadinessSpec(
        name="ADMIN_BEARER_TOKEN",
        required_for_completion=True,
        unblocks=("hosted_source_freshness_smoke",),
        blocks_completion_gates=("hosted_worker_persisted_evidence",),
        required_evidence_requirements=(
            "freshness_policy",
            "worker_persisted_evidence_path",
        ),
        next_operator_action=(
            "Set the ADMIN_BEARER_TOKEN repository secret before release-gate "
            "Hosted Monitoring runs that require /admin/v1/sources freshness evidence."
        ),
    ),
    SecretReadinessSpec(
        name="HOSTED_WORKER_EVIDENCE_MANIFEST_B64",
        required_for_completion=True,
        unblocks=("hosted_worker_private_evidence",),
        blocks_completion_gates=("hosted_worker_persisted_evidence",),
        required_evidence_requirements=(
            "freshness_policy",
            "raw_snapshot_retention_policy",
            "monitored_scheduler_cadence",
            "hosted_egress_review",
            "worker_persisted_evidence_path",
        ),
        next_operator_action=(
            "Store a reviewed hosted-worker evidence manifest as base64 after "
            "private freshness, retention, cadence, egress, and worker evidence refs are accepted."
        ),
    ),
    SecretReadinessSpec(
        name="HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64",
        required_for_completion=True,
        unblocks=("hosted_worker_policy_private_evidence",),
        blocks_completion_gates=("hosted_worker_persisted_evidence",),
        required_evidence_requirements=(
            "raw_snapshot_retention_policy",
            "monitored_scheduler_cadence",
            "hosted_egress_review",
        ),
        next_operator_action=(
            "Store a reviewed hosted-worker policy evidence manifest as base64 "
            "after retention, scheduler cadence, and egress-review evidence refs are accepted. "
            "This can satisfy the policy side of hosted_worker_persisted_evidence together "
            "with ADMIN_BEARER_TOKEN-backed source freshness evidence."
        ),
    ),
    SecretReadinessSpec(
        name="HOSTED_MONITORING_EVIDENCE_MANIFEST_B64",
        required_for_completion=True,
        unblocks=("hosted_monitoring_private_evidence",),
        blocks_completion_gates=("production_monitoring_and_alerting",),
        required_evidence_requirements=(
            "hosted_alert_routing",
            "scheduled_freshness_checks",
            "worker_scheduler_alert_ownership",
        ),
        next_operator_action=(
            "Store a reviewed hosted-monitoring evidence manifest as base64 "
            "after alert routing, scheduled checks, and ownership evidence are accepted."
        ),
    ),
    SecretReadinessSpec(
        name="LOCAL_SOURCE_REQUEST_DISPATCH_EVIDENCE_B64",
        required_for_completion=False,
        unblocks=("local_source_request_dispatch_followups",),
        blocks_completion_gates=(),
        required_evidence_requirements=(
            "official_request_dispatch_followup_visibility",
        ),
        next_operator_action=(
            "Optionally store a reviewed dispatch overlay as base64 to publish "
            "public-safe pending or overdue official request follow-up counts."
        ),
    ),
)


COMPLETION_ROUTES = (
    CompletionRouteSpec(
        gate_key="hosted_worker_persisted_evidence",
        route_key="hosted_worker_full_manifest",
        required_secret_names=("HOSTED_WORKER_EVIDENCE_MANIFEST_B64",),
        satisfied_requirements=(
            "freshness_policy",
            "raw_snapshot_retention_policy",
            "monitored_scheduler_cadence",
            "hosted_egress_review",
            "worker_persisted_evidence_path",
        ),
        next_operator_action=(
            "Set HOSTED_WORKER_EVIDENCE_MANIFEST_B64 with a reviewed full worker "
            "evidence manifest."
        ),
    ),
    CompletionRouteSpec(
        gate_key="hosted_worker_persisted_evidence",
        route_key="hosted_worker_admin_freshness_plus_policy_manifest",
        required_secret_names=(
            "ADMIN_BEARER_TOKEN",
            "HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64",
        ),
        satisfied_requirements=(
            "freshness_policy",
            "worker_persisted_evidence_path",
            "raw_snapshot_retention_policy",
            "monitored_scheduler_cadence",
            "hosted_egress_review",
        ),
        next_operator_action=(
            "Set ADMIN_BEARER_TOKEN for hosted source freshness evidence and "
            "HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64 for retention, cadence, "
            "and egress evidence."
        ),
    ),
    CompletionRouteSpec(
        gate_key="production_monitoring_and_alerting",
        route_key="hosted_monitoring_manifest",
        required_secret_names=("HOSTED_MONITORING_EVIDENCE_MANIFEST_B64",),
        satisfied_requirements=(
            "hosted_alert_routing",
            "scheduled_freshness_checks",
            "worker_scheduler_alert_ownership",
        ),
        next_operator_action=(
            "Set HOSTED_MONITORING_EVIDENCE_MANIFEST_B64 with reviewed alert "
            "routing, scheduled checks, and ownership evidence."
        ),
    ),
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Write a public-safe Hosted Monitoring readiness artifact showing "
            "which private evidence secrets are configured without printing "
            "or decoding secret values."
        )
    )
    parser.add_argument(
        "--captured-at",
        required=True,
        help="ISO-8601 timestamp for this readiness artifact.",
    )
    parser.add_argument(
        "--output",
        help="Optional output path. When omitted, content is written to stdout.",
    )
    args = parser.parse_args()

    artifact = build_readiness_artifact(captured_at=args.captured_at)
    content = json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
        return 0
    print(content, end="")
    return 0


def build_readiness_artifact(*, captured_at: str) -> dict[str, object]:
    secrets = [_secret_readiness_item(spec) for spec in SECRET_SPECS]
    completion_routes = [_completion_route_item(route) for route in COMPLETION_ROUTES]
    completion_gate_blockers = _completion_gate_blockers(completion_routes)
    missing_completion_secret_names = sorted(
        {
            secret_name
            for blocker in completion_gate_blockers
            for secret_name in blocker["missing_secret_names"]
        }
    )
    configured_count = sum(1 for item in secrets if item["configured"])
    return {
        "schema_version": SCHEMA_VERSION,
        "captured_at": captured_at,
        "summary": {
            "configured_secret_count": configured_count,
            "missing_secret_count": len(secrets) - configured_count,
            "missing_completion_gate_secret_count": len(missing_completion_secret_names),
            "completion_gate_blocker_count": len(completion_gate_blockers),
        },
        "secrets": secrets,
        "completion_routes": completion_routes,
        "completion_gate_blockers": completion_gate_blockers,
        "notes": [
            "This artifact records only whether required environment variables are configured.",
            "It never prints, decodes, hashes, or previews secret values.",
            (
                "Completion gates can have alternative routes; configured secrets still "
                "need their underlying private evidence to be reviewed before a "
                "completion gate can be accepted."
            ),
        ],
    }


def _secret_readiness_item(spec: SecretReadinessSpec) -> dict[str, object]:
    configured = bool(os.environ.get(spec.name, "").strip())
    return {
        "name": spec.name,
        "configured": configured,
        "required_for_completion": spec.required_for_completion,
        "unblocks": list(spec.unblocks),
        "blocks_completion_gates": list(spec.blocks_completion_gates),
        "required_evidence_requirements": list(spec.required_evidence_requirements),
        "next_operator_action": spec.next_operator_action,
    }


def _completion_route_item(route: CompletionRouteSpec) -> dict[str, object]:
    missing_secret_names = [
        name for name in route.required_secret_names if not os.environ.get(name, "").strip()
    ]
    return {
        "gate_key": route.gate_key,
        "route_key": route.route_key,
        "configured": not missing_secret_names,
        "required_secret_names": list(route.required_secret_names),
        "missing_secret_names": missing_secret_names,
        "satisfied_requirements": list(route.satisfied_requirements),
        "next_operator_action": route.next_operator_action,
    }


def _completion_gate_blockers(
    completion_routes: list[dict[str, object]],
) -> list[dict[str, object]]:
    routes_by_gate: dict[str, list[dict[str, object]]] = {}
    for route in completion_routes:
        routes_by_gate.setdefault(str(route["gate_key"]), []).append(route)

    blockers: list[dict[str, object]] = []
    for gate_key, routes in sorted(routes_by_gate.items()):
        if any(route["configured"] for route in routes):
            continue
        unsatisfied_routes = [
            {
                "route_key": route["route_key"],
                "missing_secret_names": route["missing_secret_names"],
            }
            for route in routes
        ]
        missing_secret_names = sorted(
            {
                str(secret_name)
                for route in routes
                for secret_name in route["missing_secret_names"]
            }
        )
        blockers.append(
            {
                "gate_key": gate_key,
                "missing_secret_names": missing_secret_names,
                "unsatisfied_routes": unsatisfied_routes,
            }
        )
    return blockers


if __name__ == "__main__":
    raise SystemExit(main())
