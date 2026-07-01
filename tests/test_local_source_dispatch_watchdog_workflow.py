from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "local-source-dispatch-watchdog.yml"
)


def test_local_source_dispatch_watchdog_refreshes_dispatch_artifacts_and_routes_issue() -> None:
    workflow = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    assert workflow["name"] == "Local Source Dispatch Watchdog"
    triggers = workflow["on"]
    assert triggers["schedule"][0]["cron"] == "7 16 * * *"
    assert triggers["workflow_dispatch"]["inputs"]["fail_on_dispatch_required"] == {
        "description": "Fail and route an issue when local-source request dispatch is still required.",
        "required": "false",
        "default": "true",
        "type": "boolean",
    }

    job = workflow["jobs"]["local-source-dispatch-watchdog"]
    assert job["permissions"] == {
        "contents": "read",
        "issues": "write",
    }
    assert job["env"]["FAIL_ON_DISPATCH_REQUIRED"] == (
        "${{ github.event.inputs.fail_on_dispatch_required || 'true' }}"
    )

    steps = job["steps"]
    step_text = "\n".join(str(step) for step in steps)
    assert "actions/checkout@v4" in step_text
    assert "actions/setup-python@v5" in step_text
    assert "scripts/local-source-signal-gap-discovery-refresh.py" in step_text
    assert "scripts/local-source-signal-gap-dispatch-readiness.py" in step_text
    assert "scripts/local-source-contract-dispatch-readiness.py" in step_text
    assert "scripts/local-source-request-packet-bundle.py" in step_text
    assert "scripts/local-source-dispatch-watchdog.py" in step_text
    assert "--fail-on-dispatch-required" in step_text
    assert "--output artifacts/local-source-dispatch-watchdog.json" in step_text
    assert "--markdown-output artifacts/local-source-dispatch-watchdog.md" in step_text
    assert "actions/upload-artifact@v4" in step_text

    issue_step = next(
        step
        for step in steps
        if step.get("name") == "Route local source dispatch watchdog issue"
    )
    assert issue_step["if"] == "${{ failure() }}"
    assert issue_step["uses"] == "actions/github-script@v7"
    script = issue_step["with"]["script"]
    assert "local-source-dispatch-watchdog" in script
    assert "Local source dispatch required" in script
    assert "github.rest.issues.create" in script
    assert "github.rest.issues.createComment" in script
    assert "private evidence" in script
    assert "ADMIN_BEARER_TOKEN" not in step_text

    resolve_step = next(
        step
        for step in steps
        if step.get("name") == "Close resolved local source dispatch issue"
    )
    assert resolve_step["if"] == "${{ success() }}"
    assert resolve_step["uses"] == "actions/github-script@v7"
    resolve_script = resolve_step["with"]["script"]
    assert "local-source-dispatch-watchdog" in resolve_script
    assert "Local source dispatch required" in resolve_script
    assert "github.rest.issues.createComment" in resolve_script
    assert "github.rest.issues.update" in resolve_script
    assert "resolved" in resolve_script
