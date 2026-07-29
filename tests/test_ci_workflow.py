from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def test_feature_branches_run_ci_once_through_pull_requests() -> None:
    workflow = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    triggers = workflow["on"]
    assert "pull_request" in triggers
    assert triggers["push"]["branches"] == ["main"]
