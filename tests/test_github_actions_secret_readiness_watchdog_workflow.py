from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "github-actions-secret-readiness-watchdog.yml"
)


def test_github_actions_secret_readiness_watchdog_routes_missing_required_secrets() -> None:
    workflow = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    assert workflow["name"] == "GitHub Actions Secret Readiness Watchdog"
    triggers = workflow["on"]
    assert triggers["schedule"][0]["cron"] == "23 16 * * *"
    assert triggers["workflow_dispatch"]["inputs"]["fail_on_completion_blockers"] == {
        "description": "Fail and route an issue when required secret routes still block completion gates.",
        "required": "false",
        "default": "true",
        "type": "boolean",
    }

    job = workflow["jobs"]["secret-readiness-watchdog"]
    assert job["permissions"] == {
        "actions": "read",
        "contents": "read",
        "issues": "write",
    }
    assert job["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert job["env"]["FAIL_ON_COMPLETION_BLOCKERS"] == (
        "${{ github.event.inputs.fail_on_completion_blockers || 'true' }}"
    )

    steps = job["steps"]
    step_text = "\n".join(str(step) for step in steps)
    assert "scripts/github-actions-secret-readiness.py" in step_text
    assert "--fail-on-completion-blockers" in step_text
    assert "--output artifacts/github-actions-secret-readiness.json" in step_text
    assert "--markdown-output artifacts/github-actions-secret-readiness.md" in step_text
    assert "actions/upload-artifact@v4" in step_text

    issue_step = next(
        step
        for step in steps
        if step.get("name") == "Route secret readiness watchdog issue"
    )
    assert issue_step["if"] == "${{ failure() }}"
    assert issue_step["uses"] == "actions/github-script@v7"
    script = issue_step["with"]["script"]
    assert "secret-readiness-watchdog" in script
    assert "GitHub Actions required secrets missing" in script
    assert "github.rest.issues.create" in script
    assert "github.rest.issues.createComment" in script
    assert "secret values" in script
    assert "secrets." not in step_text
