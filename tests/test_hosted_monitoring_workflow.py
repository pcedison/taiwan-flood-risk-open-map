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
    assert workflow_dispatch_inputs["expected_deployment_sha"]["description"] == (
        "Expected /health deployment_sha. Defaults to production-release branch HEAD."
    )
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
    assert triggers["schedule"][0]["cron"] == "7,37 * * * *"

    job = workflow["jobs"]["hosted-monitoring"]
    assert job["permissions"] == {"contents": "read", "issues": "write"}
    assert job["env"]["ADMIN_BEARER_TOKEN"] == "${{ secrets.ADMIN_BEARER_TOKEN }}"
    assert job["env"]["HOSTED_WORKER_EVIDENCE_MANIFEST_B64"] == (
        "${{ secrets.HOSTED_WORKER_EVIDENCE_MANIFEST_B64 }}"
    )
    assert job["env"]["HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64"] == (
        "${{ secrets.HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64 }}"
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
    assert "scripts/public-api-contract-probe.py" in step_text
    assert "scripts/hosted_deployment_smoke.py" in step_text
    assert "scripts/hosted_public_risk_evidence_smoke.py" in step_text
    assert "scripts/hosted_source_freshness_smoke.py" in step_text
    assert "scripts/hosted_worker_evidence.py" in step_text
    assert "scripts/hosted_worker_policy_evidence.py" in step_text
    assert "scripts/hosted_monitoring_evidence.py" in step_text
    assert "scripts/hosted_monitoring_schedule_evidence.py" in step_text
    assert "scripts/hosted_private_evidence_template_bundle.py" in step_text
    assert "scripts/local-source-signal-gap-discovery-refresh.py" in step_text
    assert "scripts/local-source-signal-gap-dispatch-readiness.py" in step_text
    assert "scripts/local-source-contract-dispatch-readiness.py" in step_text
    assert "scripts/local-source-request-packet-bundle.py" in step_text
    assert "scripts/hosted_private_evidence_readiness.py" in step_text
    assert "scripts/local-source-request-followups.py" in step_text
    assert "scripts/local-source-completion-audit.py" in step_text
    assert "--markdown-output artifacts/hosted-completion-audit.md" in step_text
    assert "actions/upload-artifact@v6" in step_text

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
    assert (
        "--completion-evidence-output "
        "artifacts/hosted-source-freshness-completion-evidence.json"
    ) in source_freshness_step["run"]

    deployment_smoke_step = next(
        step for step in steps if step.get("name") == "Hosted deployment smoke"
    )
    assert "--retry-count 6" in deployment_smoke_step["run"]
    assert "--retry-delay-seconds 45" in deployment_smoke_step["run"]

    expected_sha_step = next(
        step for step in steps if step.get("name") == "Resolve expected deployment SHA"
    )
    assert "git ls-remote --heads origin production-release" in expected_sha_step["run"]
    assert "workflow_commit_sha" in expected_sha_step["run"]

    contract_probe_step = next(
        step
        for step in steps
        if step.get("name") == "Public API contract probe"
    )
    assert steps.index(contract_probe_step) < steps.index(deployment_smoke_step)
    assert "scripts/public-api-contract-probe.py" in contract_probe_step["run"]
    assert "--output artifacts/public-api-contract-probe.json" in (
        contract_probe_step["run"]
    )
    assert "--captured-at" in contract_probe_step["run"]
    assert "--allow-insecure-tls" in contract_probe_step["run"]

    missing_token_step = next(
        step for step in steps if step.get("name") == "Skip admin freshness smoke without token"
    )
    assert missing_token_step["if"] == (
        "${{ env.ADMIN_BEARER_TOKEN == '' && env.REQUIRE_ADMIN_SOURCE_FRESHNESS != 'true' }}"
    )

    worker_evidence_step = next(
        step for step in steps if step.get("name") == "Hosted worker private evidence"
    )
    assert worker_evidence_step["if"] == "${{ env.HOSTED_WORKER_EVIDENCE_MANIFEST_B64 != '' }}"
    assert "base64 --decode" in worker_evidence_step["run"]
    assert "--completion-evidence-output artifacts/hosted-worker-completion-evidence.json" in (
        worker_evidence_step["run"]
    )

    worker_policy_evidence_step = next(
        step
        for step in steps
        if step.get("name") == "Hosted worker policy private evidence"
    )
    assert worker_policy_evidence_step["if"] == (
        "${{ env.HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64 != '' }}"
    )
    assert "base64 --decode" in worker_policy_evidence_step["run"]
    assert "scripts/hosted_worker_policy_evidence.py" in worker_policy_evidence_step["run"]
    assert (
        "--completion-evidence-output "
        "artifacts/hosted-worker-policy-completion-evidence.json"
    ) in worker_policy_evidence_step["run"]

    missing_worker_policy_step = next(
        step
        for step in steps
        if step.get("name") == "Skip hosted worker policy private evidence without manifest"
    )
    assert missing_worker_policy_step["if"] == (
        "${{ env.HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64 == '' }}"
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

    optional_skip_step_names = [
        "Skip admin freshness smoke without token",
        "Skip hosted worker private evidence without manifest",
        "Skip hosted worker policy private evidence without manifest",
        "Skip hosted monitoring private evidence without manifest",
        "Skip local source request dispatch follow-ups without manifest",
    ]
    for step_name in optional_skip_step_names:
        step = next(step for step in steps if step.get("name") == step_name)
        assert "::notice" not in step["run"]
        assert "GITHUB_STEP_SUMMARY" in step["run"]

    signal_gap_discovery_step = next(
        step for step in steps if step.get("name") == "Local source signal-gap discovery refresh"
    )
    assert "scripts/local-source-signal-gap-discovery-refresh.py" in (
        signal_gap_discovery_step["run"]
    )
    assert "--output-dir artifacts" in signal_gap_discovery_step["run"]
    assert "--captured-at" in signal_gap_discovery_step["run"]
    assert "--allow-fetch-failure" in signal_gap_discovery_step["run"]

    signal_gap_dispatch_step = next(
        step
        for step in steps
        if step.get("name") == "Local source signal-gap dispatch readiness"
    )
    assert "scripts/local-source-signal-gap-dispatch-readiness.py" in (
        signal_gap_dispatch_step["run"]
    )
    assert (
        "--discovery-summary-json "
        "artifacts/signal-gap-discovery-refresh-summary.json"
    ) in signal_gap_dispatch_step["run"]
    assert "--output artifacts/signal-gap-dispatch-readiness.json" in (
        signal_gap_dispatch_step["run"]
    )
    assert "--captured-at" in signal_gap_dispatch_step["run"]

    source_contract_dispatch_step = next(
        step
        for step in steps
        if step.get("name") == "Local source contract dispatch readiness"
    )
    assert "scripts/local-source-contract-dispatch-readiness.py" in (
        source_contract_dispatch_step["run"]
    )
    assert "--output artifacts/source-contract-dispatch-readiness.json" in (
        source_contract_dispatch_step["run"]
    )
    assert "--captured-at" in source_contract_dispatch_step["run"]

    request_packet_bundle_step = next(
        step
        for step in steps
        if step.get("name") == "Local source request packet bundle"
    )
    assert "scripts/local-source-request-packet-bundle.py" in (
        request_packet_bundle_step["run"]
    )
    assert "--output-dir artifacts" in request_packet_bundle_step["run"]
    assert "--captured-at" in request_packet_bundle_step["run"]

    private_evidence_readiness_step = next(
        step
        for step in steps
        if step.get("name") == "Hosted private evidence readiness"
    )
    assert "scripts/hosted_private_evidence_readiness.py" in (
        private_evidence_readiness_step["run"]
    )
    assert "--output artifacts/hosted-private-evidence-readiness.json" in (
        private_evidence_readiness_step["run"]
    )
    assert "--captured-at" in private_evidence_readiness_step["run"]

    private_evidence_template_bundle_step = next(
        step
        for step in steps
        if step.get("name") == "Hosted private evidence template bundle"
    )
    assert "scripts/hosted_private_evidence_template_bundle.py" in (
        private_evidence_template_bundle_step["run"]
    )
    assert "--output-dir artifacts" in private_evidence_template_bundle_step["run"]
    assert "--captured-at" in private_evidence_template_bundle_step["run"]

    schedule_evidence_step = next(
        step
        for step in steps
        if step.get("name") == "Hosted monitoring schedule evidence"
    )
    assert steps.index(schedule_evidence_step) > steps.index(source_freshness_step)
    assert steps.index(schedule_evidence_step) > steps.index(worker_evidence_step)
    assert steps.index(schedule_evidence_step) > steps.index(worker_policy_evidence_step)
    assert steps.index(schedule_evidence_step) > steps.index(monitoring_evidence_step)
    assert steps.index(schedule_evidence_step) > steps.index(dispatch_followups_step)
    assert steps.index(schedule_evidence_step) > steps.index(missing_dispatch_step)
    assert "scripts/hosted_monitoring_schedule_evidence.py" in (
        schedule_evidence_step["run"]
    )
    assert "--event-name \"${GITHUB_EVENT_NAME}\"" in schedule_evidence_step["run"]
    assert "--cron \"${{ github.event.schedule || '7,37 * * * *' }}\"" in (
        schedule_evidence_step["run"]
    )
    assert "--evidence-output artifacts/hosted-monitoring-schedule-evidence.json" in (
        schedule_evidence_step["run"]
    )
    assert (
        "--completion-evidence-output "
        "artifacts/hosted-monitoring-schedule-completion-evidence.json"
    ) in schedule_evidence_step["run"]

    audit_step = next(
        step for step in steps if step.get("name") == "Hosted completion audit"
    )
    assert audit_step["if"] == "${{ always() }}"
    assert steps.index(schedule_evidence_step) < steps.index(audit_step)
    assert "artifacts/*-completion-evidence.json" in audit_step["run"]
    assert "--output artifacts/hosted-completion-audit.json" in audit_step["run"]

    alert_routing_step = next(
        step
        for step in steps
        if step.get("name") == "Route hosted monitoring failure issue"
    )
    assert alert_routing_step["if"] == "${{ failure() }}"
    assert alert_routing_step["uses"] == "actions/github-script@v8"
    assert "hosted-monitoring-alert" in alert_routing_step["with"]["script"]
    assert "Hosted Monitoring failure" in alert_routing_step["with"]["script"]
    assert "github.rest.issues.create" in alert_routing_step["with"]["script"]
    assert "github.rest.issues.createComment" in alert_routing_step["with"]["script"]
    assert "process.env.GITHUB_RUN_ID" in alert_routing_step["with"]["script"]
    assert "artifacts/hosted-deployment-smoke.json" in alert_routing_step["with"]["script"]
    assert "expected deployment SHA" in alert_routing_step["with"]["script"]
    assert "health deployment SHA" in alert_routing_step["with"]["script"]
    assert "ready deployment SHA" in alert_routing_step["with"]["script"]

    resolve_step = next(
        step
        for step in steps
        if step.get("name") == "Close resolved hosted monitoring failure issue"
    )
    assert resolve_step["if"] == "${{ success() }}"
    assert resolve_step["uses"] == "actions/github-script@v8"
    resolve_script = resolve_step["with"]["script"]
    assert "hosted-monitoring-alert" in resolve_script
    assert "Hosted Monitoring failure" in resolve_script
    assert "Hosted Monitoring failure resolved" in resolve_script
    assert "github.rest.issues.createComment" in resolve_script
    assert "github.rest.issues.update" in resolve_script
    assert "state_reason" in resolve_script
