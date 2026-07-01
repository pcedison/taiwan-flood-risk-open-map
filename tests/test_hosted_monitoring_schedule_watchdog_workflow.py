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
    assert workflow_dispatch_inputs["max_age_minutes"] == {
        "description": "Maximum accepted age for the latest Hosted Monitoring schedule run.",
        "required": "false",
        "default": "90",
        "type": "number",
    }
    assert workflow_dispatch_inputs["fail_on_not_ready"] == {
        "description": "Fail the watchdog run and route an issue when schedule readiness is not accepted.",
        "required": "false",
        "default": "true",
        "type": "boolean",
    }

    job = workflow["jobs"]["hosted-schedule-watchdog"]
    assert job["permissions"] == {
        "actions": "read",
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
        "${{ github.event.inputs.fail_on_not_ready || 'true' }}"
    )

    steps = job["steps"]
    step_text = "\n".join(str(step) for step in steps)
    assert "actions/checkout@v4" in step_text
    assert "actions/setup-python@v5" in step_text
    assert "scripts/hosted-monitoring-schedule-readiness.py" in step_text
    assert "--expected-head-sha \"${EXPECTED_HEAD_SHA}\"" in step_text
    assert "--max-age-minutes \"${MAX_AGE_MINUTES}\"" in step_text
    assert "--fail-on-not-ready" in step_text
    assert "--output artifacts/hosted-monitoring-schedule-readiness.json" in step_text
    assert "--markdown-output artifacts/hosted-monitoring-schedule-readiness.md" in step_text
    assert (
        "--completion-evidence-output "
        "artifacts/hosted-monitoring-schedule-completion-evidence.json"
    ) in step_text
    assert "actions/upload-artifact@v4" in step_text

    alert_routing_step = next(
        step
        for step in steps
        if step.get("name") == "Route schedule watchdog failure issue"
    )
    assert alert_routing_step["if"] == "${{ failure() }}"
    assert alert_routing_step["uses"] == "actions/github-script@v7"
    assert "hosted-schedule-watchdog" in alert_routing_step["with"]["script"]
    assert "Hosted Monitoring schedule not ready" in alert_routing_step["with"]["script"]
    assert "github.rest.issues.create" in alert_routing_step["with"]["script"]
    assert "github.rest.issues.createComment" in alert_routing_step["with"]["script"]

    resolve_step = next(
        step
        for step in steps
        if step.get("name") == "Close resolved schedule watchdog issue"
    )
    assert resolve_step["if"] == "${{ success() }}"
    assert resolve_step["uses"] == "actions/github-script@v7"
    resolve_script = resolve_step["with"]["script"]
    assert "hosted-schedule-watchdog" in resolve_script
    assert "Hosted Monitoring schedule not ready" in resolve_script
    assert "github.rest.issues.createComment" in resolve_script
    assert "github.rest.issues.update" in resolve_script
    assert "resolved" in resolve_script
