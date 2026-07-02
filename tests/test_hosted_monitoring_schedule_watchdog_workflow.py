from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "hosted-monitoring-schedule-watchdog.yml"
)


def test_hosted_monitoring_schedule_watchdog_routes_stale_schedule_failures() -> None:
    workflow = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    assert workflow["name"] == "Hosted Monitoring Schedule Watchdog"
    triggers = workflow["on"]
    assert triggers["schedule"][0]["cron"] == "17,47 * * * *"

    workflow_dispatch_inputs = triggers["workflow_dispatch"]["inputs"]
    assert workflow_dispatch_inputs["expected_head_sha"]["required"] == "false"
    assert workflow_dispatch_inputs["expected_head_sha"]["description"] == (
        "Expected Hosted Monitoring schedule run SHA. Defaults to this workflow SHA."
    )
    assert workflow_dispatch_inputs["expected_deployment_sha"] == {
        "description": (
            "Expected fallback Hosted Monitoring deployment SHA. Defaults to "
            "production-release branch HEAD."
        ),
        "required": "false",
        "type": "string",
    }
    assert workflow_dispatch_inputs["max_age_minutes"] == {
        "description": "Maximum accepted age for the latest Hosted Monitoring schedule run.",
        "required": "false",
        "default": "90",
        "type": "number",
    }
    assert workflow_dispatch_inputs["fail_on_not_ready"] == {
        "description": (
            "Fail the watchdog run when schedule readiness is not accepted. "
            "Scheduled runs report and dispatch fallback by default."
        ),
        "required": "false",
        "default": "false",
        "type": "boolean",
    }
    assert workflow_dispatch_inputs["dispatch_hosted_monitoring_on_failure"] == {
        "description": "Dispatch Hosted Monitoring as a fallback when schedule readiness fails.",
        "required": "false",
        "default": "true",
        "type": "boolean",
    }

    job = workflow["jobs"]["hosted-schedule-watchdog"]
    assert job["permissions"] == {
        "actions": "write",
        "contents": "read",
        "issues": "write",
    }
    assert job["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert job["env"]["EXPECTED_HEAD_SHA"] == (
        "${{ github.event.inputs.expected_head_sha || github.sha }}"
    )
    assert job["env"]["MAX_AGE_MINUTES"] == (
        "${{ github.event.inputs.max_age_minutes || '90' }}"
    )
    assert job["env"]["FAIL_ON_NOT_READY"] == (
        "${{ github.event.inputs.fail_on_not_ready || 'false' }}"
    )
    assert job["env"]["DISPATCH_HOSTED_MONITORING_ON_FAILURE"] == (
        "${{ github.event.inputs.dispatch_hosted_monitoring_on_failure || 'true' }}"
    )

    steps = job["steps"]
    step_text = "\n".join(str(step) for step in steps)
    assert "actions/checkout@v4" in step_text
    assert "actions/setup-python@v5" in step_text
    assert "Resolve fallback deployment SHA" in step_text
    assert "git ls-remote --heads origin production-release" in step_text
    assert "workflow_commit_sha" in step_text
    assert "scripts/hosted-monitoring-schedule-readiness.py" in step_text
    assert "--expected-head-sha \"${EXPECTED_HEAD_SHA}\"" in step_text
    assert "--max-age-minutes \"${MAX_AGE_MINUTES}\"" in step_text
    assert "--fail-on-not-ready" in step_text
    assert "Read schedule readiness status" in step_text
    assert "steps.readiness-status.outputs.status != 'passed'" in step_text
    assert "--output artifacts/hosted-monitoring-schedule-readiness.json" in step_text
    assert "--markdown-output artifacts/hosted-monitoring-schedule-readiness.md" in step_text
    assert (
        "--completion-evidence-output "
        "artifacts/hosted-monitoring-schedule-completion-evidence.json"
    ) in step_text
    assert "Dispatch fallback Hosted Monitoring" in step_text
    assert "hosted-monitoring-schedule-fallback-dispatch.json" in step_text
    assert "createWorkflowDispatch" in step_text
    assert "hosted-monitoring.yml" in step_text
    assert "expected_deployment_sha: expectedDeploymentSha" in step_text
    assert "actions/upload-artifact@v4" in step_text

    fallback_step = next(
        step
        for step in steps
        if step.get("name") == "Dispatch fallback Hosted Monitoring"
    )
    assert fallback_step["if"] == (
        "${{ always() && env.DISPATCH_HOSTED_MONITORING_ON_FAILURE == 'true' && steps.readiness-status.outputs.status != 'passed' }}"
    )
    assert fallback_step["uses"] == "actions/github-script@v7"

    alert_routing_step = next(
        step
        for step in steps
        if step.get("name") == "Route schedule watchdog failure issue"
    )
    assert alert_routing_step["if"] == (
        "${{ always() && steps.readiness-status.outputs.status != 'passed' }}"
    )
    assert alert_routing_step["uses"] == "actions/github-script@v7"
    alert_script = alert_routing_step["with"]["script"]
    assert 'const fs = require("fs");' in alert_script
    assert "artifacts/hosted-monitoring-schedule-readiness.json" in alert_script
    assert "failure.code" in alert_script
    assert "latest_schedule_run" in alert_script
    assert "summary.age_minutes" in alert_script
    assert "hosted-monitoring-schedule-fallback-dispatch.json" in alert_script
    assert "fallback dispatch status" in alert_script
    assert "hosted-schedule-watchdog" in alert_script
    assert "Hosted Monitoring schedule not ready" in alert_script
    assert "github.rest.issues.create" in alert_script
    assert "github.rest.issues.createComment" in alert_script

    resolve_step = next(
        step
        for step in steps
        if step.get("name") == "Close resolved schedule watchdog issue"
    )
    assert resolve_step["if"] == "${{ success() }}"
    assert resolve_step["uses"] == "actions/github-script@v7"
    resolve_script = resolve_step["with"]["script"]
    assert 'const fs = require("fs");' in resolve_script
    assert "artifacts/hosted-monitoring-schedule-readiness.json" in resolve_script
    assert 'report.status !== "passed"' in resolve_script
    assert "hosted-schedule-watchdog" in resolve_script
    assert "Hosted Monitoring schedule not ready" in resolve_script
    assert "github.rest.issues.createComment" in resolve_script
    assert "github.rest.issues.update" in resolve_script
    assert "resolved" in resolve_script
