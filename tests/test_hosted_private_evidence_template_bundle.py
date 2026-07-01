from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "hosted_private_evidence_template_bundle.py"


def test_hosted_private_evidence_template_bundle_writes_operator_handoff(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "private-evidence-bundle"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--captured-at",
            "2026-07-01T13:30:00+08:00",
            "--output-dir",
            str(output_dir),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr

    expected_files = {
        "hosted-private-evidence-template-bundle-manifest.json",
        "hosted-private-evidence-template-bundle.md",
        "hosted-worker-evidence-template.json",
        "hosted-worker-policy-evidence-template.json",
        "hosted-monitoring-evidence-template.json",
    }
    assert {path.name for path in output_dir.iterdir()} == expected_files

    manifest = json.loads(
        (
            output_dir / "hosted-private-evidence-template-bundle-manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest["schema_version"] == "hosted-private-evidence-template-bundle/v1"
    assert manifest["captured_at"] == "2026-07-01T13:30:00+08:00"
    assert manifest["summary"] == {
        "template_count": 3,
        "completion_gate_count": 2,
        "required_secret_count": 3,
    }
    assert manifest["completion_gates"] == [
        "hosted_worker_persisted_evidence",
        "production_monitoring_and_alerting",
    ]
    assert [file["path"] for file in manifest["files"]] == sorted(expected_files)
    assert [route["secret_name"] for route in manifest["secret_routes"]] == [
        "HOSTED_WORKER_EVIDENCE_MANIFEST_B64",
        "HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64",
        "HOSTED_MONITORING_EVIDENCE_MANIFEST_B64",
    ]
    assert manifest["secret_routes"][1]["pairs_with"] == ["ADMIN_BEARER_TOKEN"]
    assert manifest["secret_routes"][2]["completion_gate_key"] == (
        "production_monitoring_and_alerting"
    )

    worker_template = json.loads(
        (output_dir / "hosted-worker-evidence-template.json").read_text(
            encoding="utf-8"
        )
    )
    assert worker_template["schema_version"] == "hosted-worker-evidence-input/v1"
    assert worker_template["template_status"] == "pending_private_evidence"
    assert worker_template["freshness_policy"]["status"] == "pending"

    monitoring_template = json.loads(
        (output_dir / "hosted-monitoring-evidence-template.json").read_text(
            encoding="utf-8"
        )
    )
    assert monitoring_template["schema_version"] == (
        "hosted-monitoring-evidence-input/v1"
    )
    assert monitoring_template["scheduled_freshness_checks"]["status"] == "pending"

    markdown = (
        output_dir / "hosted-private-evidence-template-bundle.md"
    ).read_text(encoding="utf-8")
    assert "# Hosted Private Evidence Template Bundle" in markdown
    assert "HOSTED_WORKER_EVIDENCE_MANIFEST_B64" in markdown
    assert "HOSTED_MONITORING_EVIDENCE_MANIFEST_B64" in markdown
    assert "Do not commit filled private evidence manifests" in markdown

    all_content = "\n".join(path.read_text(encoding="utf-8") for path in output_dir.iterdir())
    assert "BEGIN PRIVATE KEY" not in all_content
    assert "Authorization: Bearer" not in all_content
    assert "secret-" not in all_content
