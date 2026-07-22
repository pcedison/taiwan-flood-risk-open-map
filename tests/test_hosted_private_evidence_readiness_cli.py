from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "hosted_private_evidence_readiness.py"


SECRET_ENV_NAMES = [
    "ADMIN_BEARER_TOKEN",
    "HOSTED_WORKER_EVIDENCE_MANIFEST_B64",
    "HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64",
    "HOSTED_MONITORING_EVIDENCE_MANIFEST_B64",
    "LOCAL_SOURCE_REQUEST_DISPATCH_EVIDENCE_B64",
]


def test_hosted_private_evidence_readiness_reports_missing_inputs(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "hosted-private-evidence-readiness.json"
    env = os.environ.copy()
    for name in SECRET_ENV_NAMES:
        env.pop(name, None)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--captured-at",
            "2026-07-01T13:00:00+08:00",
            "--output",
            str(output_path),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "hosted-private-evidence-readiness/v1"
    assert payload["captured_at"] == "2026-07-01T13:00:00+08:00"
    assert payload["summary"] == {
        "configured_secret_count": 0,
        "missing_secret_count": 5,
        "missing_completion_gate_secret_count": 4,
        "completion_gate_blocker_count": 2,
    }
    readiness_by_name = {item["name"]: item for item in payload["secrets"]}
    assert readiness_by_name["ADMIN_BEARER_TOKEN"]["configured"] is False
    assert readiness_by_name["ADMIN_BEARER_TOKEN"]["unblocks"] == [
        "hosted_source_freshness_smoke",
    ]
    assert readiness_by_name["HOSTED_WORKER_EVIDENCE_MANIFEST_B64"][
        "blocks_completion_gates"
    ] == ["hosted_worker_persisted_evidence"]
    assert readiness_by_name["HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64"][
        "unblocks"
    ] == ["hosted_worker_policy_private_evidence"]
    assert readiness_by_name["HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64"][
        "required_evidence_requirements"
    ] == [
        "raw_snapshot_retention_policy",
        "monitored_scheduler_cadence",
        "hosted_egress_review",
    ]
    assert readiness_by_name["HOSTED_MONITORING_EVIDENCE_MANIFEST_B64"][
        "blocks_completion_gates"
    ] == ["production_monitoring_and_alerting"]
    assert readiness_by_name["LOCAL_SOURCE_REQUEST_DISPATCH_EVIDENCE_B64"][
        "blocks_completion_gates"
    ] == []
    assert payload["completion_gate_blockers"] == [
        {
            "gate_key": "hosted_worker_persisted_evidence",
            "missing_secret_names": [
                "ADMIN_BEARER_TOKEN",
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
                        "ADMIN_BEARER_TOKEN",
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
    route_by_key = {route["route_key"]: route for route in payload["completion_routes"]}
    assert route_by_key["hosted_worker_full_manifest"]["configured"] is False
    assert route_by_key["hosted_worker_admin_freshness_plus_policy_manifest"][
        "configured"
    ] is False


def test_hosted_private_evidence_readiness_never_outputs_secret_values() -> None:
    env = os.environ.copy()
    env.update(
        {
            "ADMIN_BEARER_TOKEN": "secret-admin-token-value",
            "HOSTED_WORKER_EVIDENCE_MANIFEST_B64": "secret-worker-manifest",
            "HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64": "secret-worker-policy-manifest",
            "HOSTED_MONITORING_EVIDENCE_MANIFEST_B64": "secret-monitoring-manifest",
            "LOCAL_SOURCE_REQUEST_DISPATCH_EVIDENCE_B64": "secret-dispatch-manifest",
        }
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--captured-at",
            "2026-07-01T13:00:00+08:00",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["summary"] == {
        "configured_secret_count": 5,
        "missing_secret_count": 0,
        "missing_completion_gate_secret_count": 0,
        "completion_gate_blocker_count": 0,
    }
    assert all(item["configured"] is True for item in payload["secrets"])
    assert payload["completion_gate_blockers"] == []
    assert "secret-admin-token-value" not in result.stdout
    assert "secret-worker-manifest" not in result.stdout
    assert "secret-worker-policy-manifest" not in result.stdout
    assert "secret-monitoring-manifest" not in result.stdout
    assert "secret-dispatch-manifest" not in result.stdout


def test_hosted_private_evidence_readiness_allows_full_worker_manifest_route() -> None:
    env = os.environ.copy()
    for name in SECRET_ENV_NAMES:
        env.pop(name, None)
    env.update(
        {
            "HOSTED_WORKER_EVIDENCE_MANIFEST_B64": "secret-worker-manifest",
        }
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--captured-at",
            "2026-07-01T13:00:00+08:00",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    blocker_by_gate = {
        blocker["gate_key"]: blocker for blocker in payload["completion_gate_blockers"]
    }
    assert "hosted_worker_persisted_evidence" not in blocker_by_gate
    assert blocker_by_gate["production_monitoring_and_alerting"]["missing_secret_names"] == [
        "HOSTED_MONITORING_EVIDENCE_MANIFEST_B64",
    ]
    route_by_key = {route["route_key"]: route for route in payload["completion_routes"]}
    assert route_by_key["hosted_worker_full_manifest"]["configured"] is True
    assert route_by_key["hosted_worker_admin_freshness_plus_policy_manifest"][
        "configured"
    ] is False
