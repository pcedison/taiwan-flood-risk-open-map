from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "hosted-monitoring.yml"


def test_hosted_monitoring_workflow_schedules_public_and_admin_smokes() -> None:
    workflow = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    assert workflow["name"] == "Hosted Monitoring"
    triggers = workflow["on"]
    assert triggers["workflow_dispatch"]["inputs"]["expected_deployment_sha"]["required"] == "false"
    assert triggers["schedule"][0]["cron"] == "*/30 * * * *"

    job = workflow["jobs"]["hosted-monitoring"]
    assert job["permissions"] == {"contents": "read"}
    assert job["env"]["ADMIN_BEARER_TOKEN"] == "${{ secrets.ADMIN_BEARER_TOKEN }}"

    steps = job["steps"]
    step_text = "\n".join(str(step) for step in steps)
    assert "scripts/hosted_deployment_smoke.py" in step_text
    assert "scripts/hosted_public_risk_evidence_smoke.py" in step_text
    assert "scripts/hosted_source_freshness_smoke.py" in step_text
    assert "actions/upload-artifact@v4" in step_text

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
    assert missing_token_step["if"] == "${{ env.ADMIN_BEARER_TOKEN == '' }}"
    assert "::notice" in missing_token_step["run"]
