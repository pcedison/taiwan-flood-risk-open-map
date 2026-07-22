from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "github-actions-secret-readiness.py"


def test_github_actions_secret_readiness_cli_emits_public_safe_evidence(
    tmp_path: Path,
) -> None:
    secrets_json = tmp_path / "gh-secrets.json"
    output_json = tmp_path / "github-actions-secret-readiness.json"
    output_md = tmp_path / "github-actions-secret-readiness.md"
    secrets_json.write_text(
        json.dumps(
            [
                {
                    "name": "ADMIN_BEARER_TOKEN",
                    "updatedAt": "2026-07-01T05:00:00Z",
                    "value": "must-not-be-copied",
                },
                {
                    "name": "UNRELATED_SECRET",
                    "updatedAt": "2026-07-01T04:00:00Z",
                },
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo",
            "pcedison/taiwan-flood-risk-open-map",
            "--captured-at",
            "2026-07-01T14:05:00+08:00",
            "--secrets-json",
            str(secrets_json),
            "--output",
            str(output_json),
            "--markdown-output",
            str(output_md),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""

    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "github-actions-secret-readiness/v1"
    assert payload["captured_at"] == "2026-07-01T14:05:00+08:00"
    assert payload["repository"] == "pcedison/taiwan-flood-risk-open-map"
    assert payload["source"] == {
        "mode": "provided_json",
        "app": "actions",
    }
    assert payload["summary"] == {
        "tracked_secret_count": 5,
        "configured_tracked_secret_count": 1,
        "missing_tracked_secret_count": 4,
        "required_for_completion_count": 4,
        "missing_required_for_completion_count": 3,
        "optional_secret_count": 1,
        "completion_gate_blocker_count": 2,
    }

    readiness_by_name = {item["name"]: item for item in payload["secrets"]}
    assert readiness_by_name["ADMIN_BEARER_TOKEN"] == {
        "name": "ADMIN_BEARER_TOKEN",
        "configured": True,
        "updated_at": "2026-07-01T05:00:00Z",
        "required_for_completion": True,
        "unblocks": ["hosted_source_freshness_smoke"],
        "blocks_completion_gates": ["hosted_worker_persisted_evidence"],
    }
    assert readiness_by_name["HOSTED_MONITORING_EVIDENCE_MANIFEST_B64"][
        "configured"
    ] is False
    assert payload["completion_gate_blockers"] == [
        {
            "gate_key": "hosted_worker_persisted_evidence",
            "missing_secret_names": [
                "HOSTED_WORKER_EVIDENCE_MANIFEST_B64",
                "HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64",
            ],
            "unsatisfied_routes": [
                {
                    "route_key": "hosted_worker_full_manifest",
                    "missing_secret_names": [
                        "HOSTED_WORKER_EVIDENCE_MANIFEST_B64",
                    ],
                    "satisfied_requirements": [
                        "freshness_policy",
                        "raw_snapshot_retention_policy",
                        "monitored_scheduler_cadence",
                        "hosted_egress_review",
                        "worker_persisted_evidence_path",
                    ],
                    "next_operator_action": (
                        "Set HOSTED_WORKER_EVIDENCE_MANIFEST_B64 with a reviewed "
                        "full worker evidence manifest."
                    ),
                },
                {
                    "route_key": "hosted_worker_admin_freshness_plus_policy_manifest",
                    "missing_secret_names": [
                        "HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64",
                    ],
                    "satisfied_requirements": [
                        "freshness_policy",
                        "worker_persisted_evidence_path",
                        "raw_snapshot_retention_policy",
                        "monitored_scheduler_cadence",
                        "hosted_egress_review",
                    ],
                    "next_operator_action": (
                        "Set ADMIN_BEARER_TOKEN for hosted source freshness evidence "
                        "and HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64 for retention, "
                        "cadence, and egress evidence."
                    ),
                },
            ],
        },
        {
            "gate_key": "production_monitoring_and_alerting",
            "missing_secret_names": [
                "HOSTED_MONITORING_EVIDENCE_MANIFEST_B64",
            ],
            "unsatisfied_routes": [
                {
                    "route_key": "hosted_monitoring_manifest",
                    "missing_secret_names": [
                        "HOSTED_MONITORING_EVIDENCE_MANIFEST_B64",
                    ],
                    "satisfied_requirements": [
                        "hosted_alert_routing",
                        "scheduled_freshness_checks",
                        "worker_scheduler_alert_ownership",
                    ],
                    "next_operator_action": (
                        "Set HOSTED_MONITORING_EVIDENCE_MANIFEST_B64 with reviewed "
                        "alert routing, scheduled checks, and ownership evidence."
                    ),
                },
            ],
        },
    ]
    route_by_key = {route["route_key"]: route for route in payload["completion_routes"]}
    assert route_by_key["hosted_monitoring_manifest"]["satisfied_requirements"] == [
        "hosted_alert_routing",
        "scheduled_freshness_checks",
        "worker_scheduler_alert_ownership",
    ]
    assert (
        route_by_key["hosted_monitoring_manifest"]["next_operator_action"]
        == "Set HOSTED_MONITORING_EVIDENCE_MANIFEST_B64 with reviewed alert routing, scheduled checks, and ownership evidence."
    )

    markdown = output_md.read_text(encoding="utf-8")
    assert "# GitHub Actions Secret Readiness" in markdown
    assert "Configured tracked secrets: 1/5" in markdown
    assert "Missing required-for-completion secrets: 3" in markdown
    assert "use the route-aware blocker count" in markdown
    assert "hosted_worker_full_manifest" in markdown
    assert "freshness_policy" in markdown
    assert "Set HOSTED_MONITORING_EVIDENCE_MANIFEST_B64" in markdown
    assert "must-not-be-copied" not in markdown
    assert "must-not-be-copied" not in json.dumps(payload, ensure_ascii=False)


def test_github_actions_secret_readiness_cli_writes_stdout_when_no_output(
    tmp_path: Path,
) -> None:
    secrets_json = tmp_path / "gh-secrets.json"
    secrets_json.write_text("[]", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo",
            "pcedison/taiwan-flood-risk-open-map",
            "--captured-at",
            "2026-07-01T14:05:00+08:00",
            "--secrets-json",
            str(secrets_json),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["summary"]["configured_tracked_secret_count"] == 0
    assert payload["summary"]["missing_required_for_completion_count"] == 4
    assert "value" not in result.stdout


def test_github_actions_secret_readiness_cli_accepts_presence_rows(
    tmp_path: Path,
) -> None:
    secrets_json = tmp_path / "secret-presence.json"
    output_json = tmp_path / "github-actions-secret-readiness.json"
    secrets_json.write_text(
        json.dumps(
            [
                {
                    "name": "ADMIN_BEARER_TOKEN",
                    "configured": True,
                },
                {
                    "name": "HOSTED_WORKER_EVIDENCE_MANIFEST_B64",
                    "configured": False,
                },
                {
                    "name": "HOSTED_MONITORING_EVIDENCE_MANIFEST_B64",
                    "configured": False,
                },
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo",
            "pcedison/taiwan-flood-risk-open-map",
            "--captured-at",
            "2026-07-01T14:05:00+08:00",
            "--secrets-json",
            str(secrets_json),
            "--output",
            str(output_json),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    readiness_by_name = {item["name"]: item for item in payload["secrets"]}
    assert readiness_by_name["ADMIN_BEARER_TOKEN"]["configured"] is True
    assert readiness_by_name["ADMIN_BEARER_TOKEN"]["updated_at"] is None
    assert readiness_by_name["HOSTED_WORKER_EVIDENCE_MANIFEST_B64"][
        "configured"
    ] is False
    assert readiness_by_name["HOSTED_MONITORING_EVIDENCE_MANIFEST_B64"][
        "configured"
    ] is False
    assert payload["summary"]["configured_tracked_secret_count"] == 1
    assert payload["summary"]["missing_required_for_completion_count"] == 3


def test_github_actions_secret_readiness_cli_can_fail_on_completion_blockers(
    tmp_path: Path,
) -> None:
    secrets_json = tmp_path / "gh-secrets.json"
    output_json = tmp_path / "github-actions-secret-readiness.json"
    secrets_json.write_text("[]", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo",
            "pcedison/taiwan-flood-risk-open-map",
            "--captured-at",
            "2026-07-01T14:05:00+08:00",
            "--secrets-json",
            str(secrets_json),
            "--output",
            str(output_json),
            "--fail-on-completion-blockers",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 1
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["summary"]["completion_gate_blocker_count"] == 2
    assert "ADMIN_BEARER_TOKEN" in json.dumps(payload, ensure_ascii=False)
    assert "secret-admin-token-value" not in result.stdout


@pytest.mark.parametrize(
    (
        "configured_names",
        "configured_worker_route",
        "missing_individually_tracked_count",
    ),
    [
        (
            {
                "HOSTED_WORKER_EVIDENCE_MANIFEST_B64",
                "HOSTED_MONITORING_EVIDENCE_MANIFEST_B64",
            },
            "hosted_worker_full_manifest",
            2,
        ),
        (
            {
                "ADMIN_BEARER_TOKEN",
                "HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64",
                "HOSTED_MONITORING_EVIDENCE_MANIFEST_B64",
            },
            "hosted_worker_admin_freshness_plus_policy_manifest",
            1,
        ),
    ],
)
def test_github_actions_secret_readiness_cli_accepts_either_worker_route(
    tmp_path: Path,
    configured_names: set[str],
    configured_worker_route: str,
    missing_individually_tracked_count: int,
) -> None:
    secrets_json = tmp_path / "secret-presence.json"
    output_json = tmp_path / "github-actions-secret-readiness.json"
    secrets_json.write_text(
        json.dumps(
            [
                {"name": name, "configured": True}
                for name in sorted(configured_names)
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo",
            "pcedison/taiwan-flood-risk-open-map",
            "--captured-at",
            "2026-07-22T12:00:00+08:00",
            "--secrets-json",
            str(secrets_json),
            "--output",
            str(output_json),
            "--fail-on-completion-blockers",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["summary"]["completion_gate_blocker_count"] == 0
    assert (
        payload["summary"]["missing_required_for_completion_count"]
        == missing_individually_tracked_count
    )
    assert payload["completion_gate_blockers"] == []
    route_by_key = {route["route_key"]: route for route in payload["completion_routes"]}
    assert route_by_key[configured_worker_route]["configured"] is True
    assert route_by_key["hosted_monitoring_manifest"]["configured"] is True
    secret_by_name = {item["name"]: item for item in payload["secrets"]}
    assert secret_by_name["LOCAL_SOURCE_REQUEST_DISPATCH_EVIDENCE_B64"] == {
        "name": "LOCAL_SOURCE_REQUEST_DISPATCH_EVIDENCE_B64",
        "configured": False,
        "updated_at": None,
        "required_for_completion": False,
        "unblocks": ["local_source_request_dispatch_followups"],
        "blocks_completion_gates": [],
    }


def test_github_actions_secret_readiness_cli_rejects_incomplete_worker_route(
    tmp_path: Path,
) -> None:
    secrets_json = tmp_path / "secret-presence.json"
    output_json = tmp_path / "github-actions-secret-readiness.json"
    secrets_json.write_text(
        json.dumps(
            [
                {"name": "ADMIN_BEARER_TOKEN", "configured": True},
                {
                    "name": "HOSTED_MONITORING_EVIDENCE_MANIFEST_B64",
                    "configured": True,
                },
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo",
            "pcedison/taiwan-flood-risk-open-map",
            "--captured-at",
            "2026-07-22T12:00:00+08:00",
            "--secrets-json",
            str(secrets_json),
            "--output",
            str(output_json),
            "--fail-on-completion-blockers",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 1
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["summary"]["completion_gate_blocker_count"] == 1
    assert [
        blocker["gate_key"] for blocker in payload["completion_gate_blockers"]
    ] == ["hosted_worker_persisted_evidence"]
