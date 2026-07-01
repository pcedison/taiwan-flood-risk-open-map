from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


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
                },
                {
                    "route_key": "hosted_worker_admin_freshness_plus_policy_manifest",
                    "missing_secret_names": [
                        "HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64",
                    ],
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
                },
            ],
        },
    ]

    markdown = output_md.read_text(encoding="utf-8")
    assert "# GitHub Actions Secret Readiness" in markdown
    assert "Configured tracked secrets: 1/5" in markdown
    assert "Missing required-for-completion secrets: 3" in markdown
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
