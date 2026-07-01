from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "hosted-monitoring.yml"


def test_hosted_monitoring_workflow_schedules_public_and_admin_smokes() -> None:
    workflow = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    assert workflow["name"] == "Hosted Monitoring"
    triggers = workflow["on"]
    workflow_dispatch_inputs = triggers["workflow_dispatch"]["inputs"]
    assert workflow_dispatch_inputs["expected_deployment_sha"]["required"] == "false"
    assert workflow_dispatch_inputs["require_admin_source_freshness"] == {
        "description": (
            "Fail the workflow when ADMIN_BEARER_TOKEN is missing instead of "
            "skipping /admin/v1/sources freshness evidence."
        ),
        "required": "false",
        "default": "false",
        "type": "boolean",
    }
    assert workflow_dispatch_inputs["fail_on_overdue_local_source_followups"] == {
        "description": (
            "Fail when private local-source request dispatch evidence contains "
            "overdue official follow-ups."
        ),
        "required": "false",
        "default": "false",
        "type": "boolean",
    }
    assert triggers["schedule"][0]["cron"] == "*/30 * * * *"

    job = workflow["jobs"]["hosted-monitoring"]
    assert job["permissions"] == {"contents": "read"}
    assert job["env"]["ADMIN_BEARER_TOKEN"] == "${{ secrets.ADMIN_BEARER_TOKEN }}"
    assert job["env"]["HOSTED_WORKER_EVIDENCE_MANIFEST_B64"] == (
        "${{ secrets.HOSTED_WORKER_EVIDENCE_MANIFEST_B64 }}"
    )
    assert job["env"]["HOSTED_MONITORING_EVIDENCE_MANIFEST_B64"] == (
        "${{ secrets.HOSTED_MONITORING_EVIDENCE_MANIFEST_B64 }}"
    )
    assert job["env"]["LOCAL_SOURCE_REQUEST_DISPATCH_EVIDENCE_B64"] == (
        "${{ secrets.LOCAL_SOURCE_REQUEST_DISPATCH_EVIDENCE_B64 }}"
    )
    assert job["env"]["REQUIRE_ADMIN_SOURCE_FRESHNESS"] == (
        "${{ github.event.inputs.require_admin_source_freshness || 'false' }}"
    )
    assert job["env"]["FAIL_ON_OVERDUE_LOCAL_SOURCE_FOLLOWUPS"] == (
        "${{ github.event.inputs.fail_on_overdue_local_source_followups || 'false' }}"
    )

    steps = job["steps"]
    step_text = "\n".join(str(step) for step in steps)
    assert "scripts/hosted_deployment_smoke.py" in step_text
    assert "scripts/hosted_public_risk_evidence_smoke.py" in step_text
    assert "scripts/hosted_source_freshness_smoke.py" in step_text
    assert "scripts/hosted_worker_evidence.py" in step_text
    assert "scripts/hosted_monitoring_evidence.py" in step_text
    assert "scripts/local-source-signal-gap-discovery-refresh.py" in step_text
    assert "scripts/local-source-request-followups.py" in step_text
    assert "scripts/local-source-completion-audit.py" in step_text
    assert "--markdown-output artifacts/hosted-completion-audit.md" in step_text
    assert "actions/upload-artifact@v4" in step_text

    required_admin_step = next(
        step for step in steps if step.get("name") == "Require admin source freshness token"
    )
    assert required_admin_step["if"] == (
        "${{ env.REQUIRE_ADMIN_SOURCE_FRESHNESS == 'true' && env.ADMIN_BEARER_TOKEN == '' }}"
    )
    assert "ADMIN_BEARER_TOKEN is required" in required_admin_step["run"]

    source_freshness_step = next(
        step for step in steps if step.get("name") == "Hosted source freshness smoke"
    )
    assert source_freshness_step["if"] == "${{ env.ADMIN_BEARER_TOKEN != '' }}"
    assert "--completion-evidence-output artifacts/hosted-source-freshness-completion-evidence.json" in (
        source_freshness_step["run"]
    )

    missing_token_step = next(
        step for step in steps if step.get("name") == "Skip admin freshness smoke without token"
    )
    assert missing_token_step["if"] == (
        "${{ env.ADMIN_BEARER_TOKEN == '' && env.REQUIRE_ADMIN_SOURCE_FRESHNESS != 'true' }}"
    )
    assert "::notice" in missing_token_step["run"]

    worker_evidence_step = next(
        step for step in steps if step.get("name") == "Hosted worker private evidence"
    )
    assert worker_evidence_step["if"] == "${{ env.HOSTED_WORKER_EVIDENCE_MANIFEST_B64 != '' }}"
    assert "base64 --decode" in worker_evidence_step["run"]
    assert "--completion-evidence-output artifacts/hosted-worker-completion-evidence.json" in (
        worker_evidence_step["run"]
    )

    monitoring_evidence_step = next(
        step for step in steps if step.get("name") == "Hosted monitoring private evidence"
    )
    assert monitoring_evidence_step["if"] == (
        "${{ env.HOSTED_MONITORING_EVIDENCE_MANIFEST_B64 != '' }}"
    )
    assert "base64 --decode" in monitoring_evidence_step["run"]
    assert "--completion-evidence-output artifacts/hosted-monitoring-completion-evidence.json" in (
        monitoring_evidence_step["run"]
    )

    dispatch_followups_step = next(
        step for step in steps if step.get("name") == "Local source request dispatch follow-ups"
    )
    assert dispatch_followups_step["if"] == (
        "${{ env.LOCAL_SOURCE_REQUEST_DISPATCH_EVIDENCE_B64 != '' }}"
    )
    assert "base64 --decode" in dispatch_followups_step["run"]
    assert "--output artifacts/local-source-request-followups.json" in (
        dispatch_followups_step["run"]
    )
    assert (
        "--sanitized-completion-evidence-output "
        "artifacts/local-source-request-dispatch-completion-evidence.json"
    ) in dispatch_followups_step["run"]
    assert "--fail-on-overdue" in dispatch_followups_step["run"]

    missing_dispatch_step = next(
        step
        for step in steps
        if step.get("name") == "Skip local source request dispatch follow-ups without manifest"
    )
    assert missing_dispatch_step["if"] == (
        "${{ env.LOCAL_SOURCE_REQUEST_DISPATCH_EVIDENCE_B64 == '' }}"
    )
    assert "::notice" in missing_dispatch_step["run"]

    signal_gap_discovery_step = next(
        step for step in steps if step.get("name") == "Local source signal-gap discovery refresh"
    )
    assert "scripts/local-source-signal-gap-discovery-refresh.py" in (
        signal_gap_discovery_step["run"]
    )
    assert "--output-dir artifacts" in signal_gap_discovery_step["run"]
    assert "--captured-at" in signal_gap_discovery_step["run"]

    audit_step = next(
        step for step in steps if step.get("name") == "Hosted completion audit"
    )
    assert audit_step["if"] == "${{ always() }}"
    assert "artifacts/*-completion-evidence.json" in audit_step["run"]
    assert "--output artifacts/hosted-completion-audit.json" in audit_step["run"]
