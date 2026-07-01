#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


SCHEMA_VERSION = "github-actions-secret-readiness/v1"
DEFAULT_REPOSITORY = "pcedison/taiwan-flood-risk-open-map"


@dataclass(frozen=True)
class SecretSpec:
    name: str
    required_for_completion: bool
    unblocks: tuple[str, ...]
    blocks_completion_gates: tuple[str, ...]


@dataclass(frozen=True)
class CompletionRoute:
    gate_key: str
    route_key: str
    secret_names: tuple[str, ...]


SECRET_SPECS = (
    SecretSpec(
        name="ADMIN_BEARER_TOKEN",
        required_for_completion=True,
        unblocks=("hosted_source_freshness_smoke",),
        blocks_completion_gates=("hosted_worker_persisted_evidence",),
    ),
    SecretSpec(
        name="HOSTED_WORKER_EVIDENCE_MANIFEST_B64",
        required_for_completion=True,
        unblocks=("hosted_worker_private_evidence",),
        blocks_completion_gates=("hosted_worker_persisted_evidence",),
    ),
    SecretSpec(
        name="HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64",
        required_for_completion=True,
        unblocks=("hosted_worker_policy_private_evidence",),
        blocks_completion_gates=("hosted_worker_persisted_evidence",),
    ),
    SecretSpec(
        name="HOSTED_MONITORING_EVIDENCE_MANIFEST_B64",
        required_for_completion=True,
        unblocks=("hosted_monitoring_private_evidence",),
        blocks_completion_gates=("production_monitoring_and_alerting",),
    ),
    SecretSpec(
        name="LOCAL_SOURCE_REQUEST_DISPATCH_EVIDENCE_B64",
        required_for_completion=False,
        unblocks=("local_source_request_dispatch_followups",),
        blocks_completion_gates=(),
    ),
)


COMPLETION_ROUTES = (
    CompletionRoute(
        gate_key="hosted_worker_persisted_evidence",
        route_key="hosted_worker_full_manifest",
        secret_names=("HOSTED_WORKER_EVIDENCE_MANIFEST_B64",),
    ),
    CompletionRoute(
        gate_key="hosted_worker_persisted_evidence",
        route_key="hosted_worker_admin_freshness_plus_policy_manifest",
        secret_names=(
            "ADMIN_BEARER_TOKEN",
            "HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64",
        ),
    ),
    CompletionRoute(
        gate_key="production_monitoring_and_alerting",
        route_key="hosted_monitoring_manifest",
        secret_names=("HOSTED_MONITORING_EVIDENCE_MANIFEST_B64",),
    ),
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create public-safe evidence showing whether required GitHub Actions "
            "secrets are configured. Secret contents are never read or printed."
        )
    )
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPOSITORY),
        help="GitHub repository in OWNER/REPO form.",
    )
    parser.add_argument(
        "--captured-at",
        required=True,
        help="ISO-8601 timestamp for this readiness artifact.",
    )
    parser.add_argument(
        "--secrets-json",
        help=(
            "Optional path to JSON produced by `gh secret list --app actions "
            "--json name,updatedAt`. When omitted, the command is run locally."
        ),
    )
    parser.add_argument(
        "--output",
        help="Optional JSON output path. When omitted, JSON is written to stdout.",
    )
    parser.add_argument(
        "--markdown-output",
        help="Optional Markdown summary output path.",
    )
    args = parser.parse_args()

    if args.secrets_json:
        secret_rows = _load_secret_rows(Path(args.secrets_json))
        source = {"mode": "provided_json", "app": "actions"}
    else:
        secret_rows = _gh_actions_secret_rows(repository=args.repo)
        source = {"mode": "gh_cli", "app": "actions"}

    artifact = build_secret_readiness_artifact(
        repository=args.repo,
        captured_at=args.captured_at,
        source=source,
        secret_rows=secret_rows,
    )
    content = _json(artifact)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
    else:
        print(content, end="")

    if args.markdown_output:
        markdown_path = Path(args.markdown_output)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_markdown(artifact), encoding="utf-8")
    return 0


def build_secret_readiness_artifact(
    *,
    repository: str,
    captured_at: str,
    source: Mapping[str, str],
    secret_rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    configured = _configured_secret_map(secret_rows)
    secrets = [_secret_item(spec, configured=configured) for spec in SECRET_SPECS]
    blockers = _completion_gate_blockers(configured)
    required_count = sum(1 for spec in SECRET_SPECS if spec.required_for_completion)
    configured_tracked_count = sum(1 for item in secrets if item["configured"])
    missing_required_count = sum(
        1
        for item in secrets
        if item["required_for_completion"] and not item["configured"]
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "captured_at": captured_at,
        "repository": repository,
        "source": dict(source),
        "summary": {
            "tracked_secret_count": len(SECRET_SPECS),
            "configured_tracked_secret_count": configured_tracked_count,
            "missing_tracked_secret_count": len(SECRET_SPECS) - configured_tracked_count,
            "required_for_completion_count": required_count,
            "missing_required_for_completion_count": missing_required_count,
            "optional_secret_count": len(SECRET_SPECS) - required_count,
            "completion_gate_blocker_count": len(blockers),
        },
        "secrets": secrets,
        "completion_routes": _completion_routes(configured),
        "completion_gate_blockers": blockers,
        "notes": [
            "This artifact is based only on GitHub Actions secret names and update timestamps.",
            "It never reads, decodes, hashes, or previews secret data.",
            "Configured secrets still need their private evidence manifests to pass validation before completion gates can be accepted.",
        ],
    }


def render_markdown(artifact: Mapping[str, Any]) -> str:
    summary = artifact["summary"]
    lines = [
        "# GitHub Actions Secret Readiness",
        "",
        f"- repository: `{artifact['repository']}`",
        f"- captured_at: `{artifact['captured_at']}`",
        f"- source: `{artifact['source']['mode']}` / `{artifact['source']['app']}`",
        f"- Configured tracked secrets: {summary['configured_tracked_secret_count']}/{summary['tracked_secret_count']}",
        f"- Missing required-for-completion secrets: {summary['missing_required_for_completion_count']}",
        f"- Completion gate blockers: {summary['completion_gate_blocker_count']}",
        "",
        "## Tracked Secrets",
        "",
        "| Secret | Configured | Updated At | Blocks |",
        "|---|---:|---|---|",
    ]
    for item in artifact["secrets"]:
        configured = "yes" if item["configured"] else "no"
        updated_at = item["updated_at"] or ""
        blocks = ", ".join(item["blocks_completion_gates"])
        lines.append(f"| `{item['name']}` | {configured} | {updated_at} | {blocks} |")
    lines.extend(
        [
            "",
            "## Blocked Completion Gates",
            "",
        ]
    )
    blockers = artifact["completion_gate_blockers"]
    if not blockers:
        lines.append("- none")
    else:
        for blocker in blockers:
            missing = ", ".join(f"`{name}`" for name in blocker["missing_secret_names"])
            lines.append(f"- `{blocker['gate_key']}`: missing {missing}")
    lines.extend(
        [
            "",
            "This artifact records only presence/absence metadata for known secret names. "
            "It is not private evidence and does not satisfy completion gates by itself.",
            "",
        ]
    )
    return "\n".join(lines)


def _load_secret_rows(path: Path) -> list[Mapping[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit(f"Expected a JSON list in {path}")
    return [row for row in payload if isinstance(row, Mapping)]


def _gh_actions_secret_rows(*, repository: str) -> list[Mapping[str, Any]]:
    result = subprocess.run(
        [
            "gh",
            "secret",
            "list",
            "--repo",
            repository,
            "--app",
            "actions",
            "--json",
            "name,updatedAt",
        ],
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() or "gh secret list failed"
        raise SystemExit(stderr)
    payload = json.loads(result.stdout or "[]")
    if not isinstance(payload, list):
        raise SystemExit("gh secret list returned non-list JSON")
    return [row for row in payload if isinstance(row, Mapping)]


def _configured_secret_map(secret_rows: list[Mapping[str, Any]]) -> dict[str, str | None]:
    configured: dict[str, str | None] = {}
    for row in secret_rows:
        name = row.get("name")
        if not isinstance(name, str) or not name:
            continue
        updated_at = row.get("updatedAt")
        configured[name] = updated_at if isinstance(updated_at, str) else None
    return configured


def _secret_item(
    spec: SecretSpec,
    *,
    configured: Mapping[str, str | None],
) -> dict[str, Any]:
    return {
        "name": spec.name,
        "configured": spec.name in configured,
        "updated_at": configured.get(spec.name),
        "required_for_completion": spec.required_for_completion,
        "unblocks": list(spec.unblocks),
        "blocks_completion_gates": list(spec.blocks_completion_gates),
    }


def _completion_routes(configured: Mapping[str, str | None]) -> list[dict[str, Any]]:
    routes: list[dict[str, Any]] = []
    for route in COMPLETION_ROUTES:
        missing = _missing_secret_names(route.secret_names, configured)
        routes.append(
            {
                "gate_key": route.gate_key,
                "route_key": route.route_key,
                "configured": not missing,
                "required_secret_names": list(route.secret_names),
                "missing_secret_names": missing,
            }
        )
    return routes


def _completion_gate_blockers(
    configured: Mapping[str, str | None],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    gate_keys = tuple(dict.fromkeys(route.gate_key for route in COMPLETION_ROUTES))
    for gate_key in gate_keys:
        routes = [route for route in COMPLETION_ROUTES if route.gate_key == gate_key]
        unsatisfied_routes = [
            {
                "route_key": route.route_key,
                "missing_secret_names": _missing_secret_names(
                    route.secret_names,
                    configured,
                ),
            }
            for route in routes
            if _missing_secret_names(route.secret_names, configured)
        ]
        if len(unsatisfied_routes) != len(routes):
            continue
        blockers.append(
            {
                "gate_key": gate_key,
                "missing_secret_names": sorted(
                    {
                        name
                        for route in unsatisfied_routes
                        for name in route["missing_secret_names"]
                    }
                ),
                "unsatisfied_routes": unsatisfied_routes,
            }
        )
    return blockers


def _missing_secret_names(
    secret_names: tuple[str, ...],
    configured: Mapping[str, str | None],
) -> list[str]:
    return [name for name in secret_names if name not in configured]


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
