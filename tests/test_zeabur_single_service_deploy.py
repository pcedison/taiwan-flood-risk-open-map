from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = REPO_ROOT / "Dockerfile"
# The startup contract lives in the checked-in entrypoint (extracted from the
# old Dockerfile printf heredoc so it is testable and shell-lintable).
ENTRYPOINT = REPO_ROOT / "infra" / "docker" / "entrypoint.sh"
ZEABUR_ENV_RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "zeabur-single-service-env.md"

EXPECTED_BACKBONE_ADAPTERS = (
    "official.cwa.rainfall",
    "official.cwa.tide_level",
    "official.wra.water_level",
    "official.wra_iow.flood_depth",
    "official.ncdr.cap",
    "official.civil_iot.flood_sensor",
    "official.civil_iot.sewer_water_level",
    "official.civil_iot.pump_water_level",
    "official.civil_iot.gate_water_level",
)


def test_zeabur_build_avoids_shared_docker_hub_rate_limits() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert (
        "ARG DOCKER_OFFICIAL_IMAGE_REGISTRY=public.ecr.aws/docker/library"
        in dockerfile
    )
    assert (
        "FROM ${DOCKER_OFFICIAL_IMAGE_REGISTRY}/node:22-bookworm-slim AS web-builder"
        in dockerfile
    )
    assert (
        "FROM ${DOCKER_OFFICIAL_IMAGE_REGISTRY}/python:3.12-slim AS runtime"
        in dockerfile
    )
    assert "FROM node:22-bookworm-slim" not in dockerfile
    assert "FROM python:3.12-slim" not in dockerfile


def test_zeabur_single_service_scheduler_defaults_to_realtime_backbone() -> None:
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")

    for adapter_key in EXPECTED_BACKBONE_ADAPTERS:
        assert adapter_key in entrypoint


def test_zeabur_single_service_autostarts_backbone_when_database_is_attached() -> None:
    dockerfile = ENTRYPOINT.read_text(encoding="utf-8")

    assert 'SINGLE_SERVICE_INGESTION_SCHEDULER_ENABLED:-auto' in dockerfile
    assert (
        'worker_database_url="${WORKER_DATABASE_URL:-${DATABASE_URL:-${POSTGRES_CONNECTION_STRING:-${POSTGRES_URI:-}}}}"'
        in dockerfile
    )
    assert 'realtime_backbone_force_ingestion="${REALTIME_BACKBONE_FORCE_INGESTION_ON_START:-true}"' in dockerfile
    assert 'realtime_backbone_ingestion_disabled="${REALTIME_BACKBONE_INGESTION_DISABLED:-false}"' in dockerfile
    assert 'realtime_backbone_emergency_stop="${REALTIME_BACKBONE_EMERGENCY_STOP:-false}"' in dockerfile
    assert 'realtime_backbone_adapter_keys="official.cwa.rainfall,official.cwa.tide_level,official.wra.water_level,official.wra_iow.flood_depth,official.ncdr.cap,official.civil_iot.flood_sensor,official.civil_iot.sewer_water_level,official.civil_iot.pump_water_level,official.civil_iot.gate_water_level,local.tainan.flood_sensor,official.wra.historical_flood"' in dockerfile
    assert "SOURCE_WRA_HISTORICAL_FLOOD_ENABLED" in dockerfile
    assert "SOURCE_WRA_HISTORICAL_FLOOD_API_ENABLED" in dockerfile
    assert 'if [ -n "${worker_database_url}" ]; then' in dockerfile


def test_force_mode_supersedes_legacy_stop_but_not_emergency_stop() -> None:
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    startup_gate_block = entrypoint.split(
        'if truthy "${realtime_backbone_force_ingestion}"', 1
    )[1].split("apply_migrations() {", 1)[0]

    assert 'if truthy "${realtime_backbone_emergency_stop}"; then' in startup_gate_block
    assert 'elif truthy "${realtime_backbone_ingestion_disabled}"' in startup_gate_block
    assert 'truthy "${realtime_backbone_force_ingestion}"' in startup_gate_block
    assert "legacy ingestion stop ignored because force mode is active" in startup_gate_block


def test_split_scheduler_honors_resolved_ingestion_stop_without_restart_loop() -> None:
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    scheduler_block = entrypoint.split("  scheduler)", 1)[1].split("  all)", 1)[0]

    assert 'if ! truthy "${ingestion_enabled}"; then' in scheduler_block
    assert "python -m app.main --record-runtime-sources-disabled" in scheduler_block
    assert "exec sleep infinity" in scheduler_block
    assert scheduler_block.index("--record-runtime-sources-disabled") < scheduler_block.index(
        "--run-v1-baseline-adapters --scheduler"
    )


def test_zeabur_single_service_applies_migrations_before_startup() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")

    assert "COPY infra/migrations /app/infra/migrations" in dockerfile
    assert "COPY infra/scripts/apply_migrations.py /app/infra/scripts/apply_migrations.py" in dockerfile
    assert "COPY infra/docker/entrypoint.sh /app/entrypoint.sh" in dockerfile
    assert 'RUN_DATABASE_MIGRATIONS_ON_START:-true' in entrypoint
    assert 'python /app/infra/scripts/apply_migrations.py --database-url "${worker_database_url}"' in entrypoint


def test_zeabur_single_service_scheduler_loop_runs_the_initial_tick() -> None:
    dockerfile = ENTRYPOINT.read_text(encoding="utf-8")

    assert "first tick runs immediately" in dockerfile
    # The legacy `--run-enabled-adapters` entry point is frozen and exits 2, which
    # takes the whole container down under `set -Eeuo pipefail`. The deployed
    # scheduler must use the sanctioned v1 baseline runner instead.
    assert "python -m app.main --run-v1-baseline-adapters --scheduler &" in dockerfile
    assert "--run-enabled-adapters" not in dockerfile


def test_zeabur_single_service_sets_backbone_source_gates() -> None:
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    expected_gates = (
        "SOURCE_CWA_ENABLED",
        "SOURCE_CWA_API_ENABLED",
        "SOURCE_WRA_ENABLED",
        "SOURCE_WRA_API_ENABLED",
        "SOURCE_WRA_IOW_FLOOD_DEPTH_ENABLED",
        "SOURCE_WRA_IOW_FLOOD_DEPTH_API_ENABLED",
        "SOURCE_NCDR_CAP_ENABLED",
        "SOURCE_NCDR_CAP_API_ENABLED",
        "SOURCE_NCDR_CAP_CONTRACT_ENABLED",
        "SOURCE_FLOOD_SENSOR_ENABLED",
        "SOURCE_FLOOD_SENSOR_API_ENABLED",
        "SOURCE_FLOOD_SENSOR_USE_LIVE",
        "SOURCE_CIVIL_IOT_SEWER_ENABLED",
        "SOURCE_CIVIL_IOT_SEWER_API_ENABLED",
        "SOURCE_CIVIL_IOT_PUMP_ENABLED",
        "SOURCE_CIVIL_IOT_PUMP_API_ENABLED",
        "SOURCE_CIVIL_IOT_GATE_ENABLED",
        "SOURCE_CIVIL_IOT_GATE_API_ENABLED",
        "SOURCE_TAINAN_FLOOD_SENSOR_ENABLED",
        "SOURCE_TAINAN_FLOOD_SENSOR_API_ENABLED",
    )

    force_block = entrypoint.split("configure_backbone_source_gates() {", 1)[1].split(
        "setup_ingestion_env() {", 1
    )[0]
    assert 'if truthy "${realtime_backbone_force_ingestion}"; then' in force_block
    assert 'printf -v "${gate}" "%s" "true"' in force_block
    assert 'if [ -z "${!gate:-}" ]; then' in force_block
    assert 'export "${gate}"' in force_block
    for expected_gate in expected_gates:
        assert expected_gate in force_block

    assert "configure_backbone_source_gates" in entrypoint

    assert 'required_adapter_keys="${REALTIME_BACKBONE_ADAPTER_KEYS:-${realtime_backbone_adapter_keys}}"' in entrypoint
    assert 'export WORKER_ENABLED_ADAPTER_KEYS="$(merge_adapter_keys "${required_adapter_keys}" "${configured_adapter_keys}")"' in entrypoint


def test_zeabur_single_service_runbook_lists_realtime_backbone() -> None:
    runbook = ZEABUR_ENV_RUNBOOK.read_text(encoding="utf-8")

    for adapter_key in EXPECTED_BACKBONE_ADAPTERS:
        assert adapter_key in runbook
    assert "SOURCE_NCDR_CAP_CONTRACT_ENABLED" in runbook
    assert "NCDR_ALERTS_API_KEY" in runbook


def test_image_runs_as_non_root_with_role_dispatch() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")

    assert "USER app" in dockerfile
    assert 'CMD ["/app/entrypoint.sh"]' in dockerfile
    for role_case in ("api)", "web)", "scheduler)", "all)"):
        assert role_case in entrypoint
    assert 'role="${SERVICE_ROLE:-all}"' in entrypoint
    # Single-role paths must exec so signals reach the real process.
    assert "exec python -m uvicorn app.main:app" in entrypoint
    assert "exec node node_modules/next/dist/bin/next start" in entrypoint
    assert "exec python -m app.main --run-v1-baseline-adapters --scheduler" in entrypoint
