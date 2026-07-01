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
        "contents": "read",
        "issues": "write",
    }
    assert job["env"]["FAIL_ON_COMPLETION_BLOCKERS"] == (
        "${{ github.event.inputs.fail_on_completion_blockers || 'true' }}"
    )
    assert job["env"]["ADMIN_BEARER_TOKEN_CONFIGURED"] == (
        "${{ secrets.ADMIN_BEARER_TOKEN != '' }}"
    )
    assert job["env"]["HOSTED_WORKER_EVIDENCE_MANIFEST_B64_CONFIGURED"] == (
        "${{ secrets.HOSTED_WORKER_EVIDENCE_MANIFEST_B64 != '' }}"
    )
    assert job["env"]["HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64_CONFIGURED"] == (
        "${{ secrets.HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64 != '' }}"
    )
    assert job["env"]["HOSTED_MONITORING_EVIDENCE_MANIFEST_B64_CONFIGURED"] == (
        "${{ secrets.HOSTED_MONITORING_EVIDENCE_MANIFEST_B64 != '' }}"
    )
    assert job["env"]["LOCAL_SOURCE_REQUEST_DISPATCH_EVIDENCE_B64_CONFIGURED"] == (
        "${{ secrets.LOCAL_SOURCE_REQUEST_DISPATCH_EVIDENCE_B64 != '' }}"
    )

    steps = job["steps"]
    step_text = "\n".join(str(step) for step in steps)
    assert "gh secret list" not in step_text
    assert "github-actions-secret-presence.json" in step_text
    assert "scripts/github-actions-secret-readiness.py" in step_text
    assert "--secrets-json artifacts/github-actions-secret-presence.json" in step_text
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
    assert "Operator next steps:" in script
    assert "docs/runbooks/monitoring-freshness-alerts.md" in script
    assert "ADMIN_BEARER_TOKEN unlocks admin source freshness smoke" in script
    assert "HOSTED_WORKER_EVIDENCE_MANIFEST_B64 unlocks hosted worker evidence" in script
    assert "HOSTED_MONITORING_EVIDENCE_MANIFEST_B64 unlocks monitoring evidence" in script
    assert "github.rest.issues.create" in script
    assert "github.rest.issues.createComment" in script
    assert "secret values" in script
    assert "secrets.ADMIN_BEARER_TOKEN }}" not in step_text

    resolve_step = next(
        step
        for step in steps
        if step.get("name") == "Close resolved secret readiness issue"
    )
    assert resolve_step["if"] == "${{ success() }}"
    assert resolve_step["uses"] == "actions/github-script@v7"
    resolve_script = resolve_step["with"]["script"]
    assert 'const fs = require("fs");' in resolve_script
    assert "artifacts/github-actions-secret-readiness.json" in resolve_script
    assert "summary.completion_gate_blocker_count !== 0" in resolve_script
    assert "summary.missing_required_for_completion_count !== 0" in resolve_script
    assert "secret-readiness-watchdog" in resolve_script
    assert "GitHub Actions required secrets missing" in resolve_script
    assert "github.rest.issues.createComment" in resolve_script
    assert "github.rest.issues.update" in resolve_script
    assert "resolved" in resolve_script
