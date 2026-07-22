#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from hosted_monitoring_evidence import build_manifest_template as build_monitoring_template
from hosted_worker_evidence import build_manifest_template as build_worker_template
from hosted_worker_policy_evidence import (
    build_manifest_template as build_worker_policy_template,
)


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


SCHEMA_VERSION = "hosted-private-evidence-template-bundle/v1"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Write a public-safe hosted private evidence template bundle for "
            "the remaining hosted worker and monitoring completion gates."
        )
    )
    parser.add_argument(
        "--captured-at",
        help="ISO-8601 timestamp for generated templates. Defaults to current UTC.",
    )
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    captured_at = args.captured_at or datetime.now(UTC).replace(microsecond=0).isoformat()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    templates = {
        "hosted-worker-evidence-template.json": build_worker_template(
            captured_at=captured_at
        ),
        "hosted-worker-policy-evidence-template.json": build_worker_policy_template(
            captured_at=captured_at
        ),
        "hosted-monitoring-evidence-template.json": build_monitoring_template(
            captured_at=captured_at
        ),
    }
    all_file_names = tuple(
        sorted(
            (
                *templates,
                "hosted-private-evidence-template-bundle-manifest.json",
                "hosted-private-evidence-template-bundle.md",
            )
        )
    )
    manifest = build_bundle_manifest(captured_at=captured_at, file_names=all_file_names)
    files: dict[str, str] = {
        name: _json(template) for name, template in templates.items()
    }
    files["hosted-private-evidence-template-bundle-manifest.json"] = _json(manifest)
    files["hosted-private-evidence-template-bundle.md"] = render_bundle_markdown(
        captured_at=captured_at,
        manifest=manifest,
    )

    for name, content in files.items():
        (output_dir / name).write_text(content, encoding="utf-8")
    print(
        f"Wrote {len(files)} hosted private evidence template bundle files to {output_dir}",
        file=sys.stderr,
    )
    return 0


def build_bundle_manifest(*, captured_at: str, file_names: tuple[str, ...]) -> dict[str, Any]:
    secret_routes = _secret_routes()
    completion_gates = [
        "hosted_worker_persisted_evidence",
        "production_monitoring_and_alerting",
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "captured_at": captured_at,
        "summary": {
            "template_count": 3,
            "completion_gate_count": len(completion_gates),
            "required_secret_count": len(secret_routes),
        },
        "completion_gates": completion_gates,
        "secret_routes": secret_routes,
        "files": [
            {
                "path": name,
                "purpose": _file_purpose(name),
            }
            for name in file_names
        ],
        "notes": [
            "Templates are public-safe pending manifests; they are not completion evidence.",
            "Do not commit filled private evidence manifests or real private evidence refs.",
            "Encode reviewed filled manifests into the matching GitHub Actions secret only after private review.",
        ],
    }


def render_bundle_markdown(*, captured_at: str, manifest: Mapping[str, Any]) -> str:
    lines = [
        "# Hosted Private Evidence Template Bundle",
        "",
        f"- captured_at: {captured_at}",
        "",
        "## Secret Routes",
        "",
    ]
    for route in manifest["secret_routes"]:
        pairs_with = route.get("pairs_with", [])
        suffix = f"; pairs with {', '.join(pairs_with)}" if pairs_with else ""
        lines.append(
            "- "
            f"`{route['secret_name']}` -> `{route['completion_gate_key']}` "
            f"({', '.join(route['satisfied_requirements'])}){suffix}"
        )
    lines.extend(
        [
            "",
            "## Files",
            "",
        ]
    )
    for file in manifest["files"]:
        lines.append(f"- `{file['path']}` - {file['purpose']}")
    lines.extend(
        [
            "",
            "Do not commit filled private evidence manifests. Keep completed "
            "manifests in private ops storage, base64-encode the reviewed JSON, "
            "and set only the matching GitHub Actions secret.",
            "",
        ]
    )
    return "\n".join(lines)


def _secret_routes() -> list[dict[str, Any]]:
    return [
        {
            "secret_name": "HOSTED_WORKER_EVIDENCE_MANIFEST_B64",
            "completion_gate_key": "hosted_worker_persisted_evidence",
            "template_path": "hosted-worker-evidence-template.json",
            "satisfied_requirements": [
                "freshness_policy",
                "raw_snapshot_retention_policy",
                "monitored_scheduler_cadence",
                "hosted_egress_review",
                "worker_persisted_evidence_path",
            ],
            "pairs_with": [],
        },
        {
            "secret_name": "HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64",
            "completion_gate_key": "hosted_worker_persisted_evidence",
            "template_path": "hosted-worker-policy-evidence-template.json",
            "satisfied_requirements": [
                "raw_snapshot_retention_policy",
                "monitored_scheduler_cadence",
                "hosted_egress_review",
            ],
            "pairs_with": ["ADMIN_BEARER_TOKEN"],
        },
        {
            "secret_name": "HOSTED_MONITORING_EVIDENCE_MANIFEST_B64",
            "completion_gate_key": "production_monitoring_and_alerting",
            "template_path": "hosted-monitoring-evidence-template.json",
            "satisfied_requirements": [
                "hosted_alert_routing",
                "scheduled_freshness_checks",
                "worker_scheduler_alert_ownership",
            ],
            "pairs_with": [],
        },
    ]


def _file_purpose(name: str) -> str:
    if name.endswith("manifest.json"):
        return "machine-readable bundle index, route mapping, and safety notes"
    if name.endswith("bundle.md"):
        return "human-readable private evidence handoff summary"
    if name == "hosted-worker-evidence-template.json":
        return "all-in-one hosted worker persisted evidence manifest template"
    if name == "hosted-worker-policy-evidence-template.json":
        return "split-route worker policy evidence manifest template"
    if name == "hosted-monitoring-evidence-template.json":
        return "production monitoring and alerting evidence manifest template"
    return "hosted private evidence template bundle artifact"


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
