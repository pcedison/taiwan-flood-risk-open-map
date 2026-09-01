from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"


def test_feature_branches_run_ci_once_through_pull_requests() -> None:
    workflow = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    triggers = workflow["on"]
    assert "pull_request" in triggers
    assert triggers["push"]["branches"] == ["main"]


def test_ci_uses_read_only_repository_permissions() -> None:
    workflow = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    assert workflow["permissions"] == {"contents": "read"}


def test_compose_uses_tracked_runner_as_only_migration_authority() -> None:
    compose = yaml.load(COMPOSE_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    services = compose["services"]

    migrate_command = "\n".join(services["migrate"]["command"])
    assert "infra/scripts/apply_migrations.py" in migrate_command
    assert "requirements.lock" in migrate_command
    assert "for migration in" not in migrate_command

    postgres_volumes = services["postgres"]["volumes"]
    assert all("docker-entrypoint-initdb.d" not in volume for volume in postgres_volumes)


def test_ci_smokes_migration_rerun_and_recorded_manifest() -> None:
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert workflow_text.count("docker compose --profile tools run --rm migrate") == 2
    assert "SELECT count(*) FROM schema_migrations" in workflow_text
    assert "expected_migration_count" in workflow_text


def test_contract_job_installs_locked_worker_dependencies() -> None:
    workflow = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    contract_steps = workflow["jobs"]["contracts"]["steps"]
    install_step = next(
        step for step in contract_steps if step.get("name") == "Install contract validator dependencies"
    )

    assert "-r apps/workers/requirements.lock" in install_step["run"]
