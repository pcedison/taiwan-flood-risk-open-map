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


def test_zeabur_single_service_scheduler_defaults_to_realtime_backbone() -> None:
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")

    for adapter_key in EXPECTED_BACKBONE_ADAPTERS:
        assert adapter_key in entrypoint


def test_zeabur_single_service_autostarts_backbone_when_database_is_attached() -> None:
    dockerfile = ENTRYPOINT.read_text(encoding="utf-8")

    assert 'SINGLE_SERVICE_INGESTION_SCHEDULER_ENABLED:-auto' in dockerfile
    assert 'worker_database_url="${WORKER_DATABASE_URL:-${DATABASE_URL:-}}"' in dockerfile
    assert 'realtime_backbone_force_ingestion="${REALTIME_BACKBONE_FORCE_INGESTION_ON_START:-true}"' in dockerfile
    assert 'realtime_backbone_ingestion_disabled="${REALTIME_BACKBONE_INGESTION_DISABLED:-false}"' in dockerfile
    assert 'realtime_backbone_adapter_keys="official.cwa.rainfall,official.cwa.tide_level,official.wra.water_level,official.wra_iow.flood_depth,official.ncdr.cap,official.civil_iot.flood_sensor,official.civil_iot.sewer_water_level,official.civil_iot.pump_water_level,official.civil_iot.gate_water_level,local.tainan.flood_sensor"' in dockerfile
    assert 'if [ -n "${worker_database_url}" ]; then' in dockerfile


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
    assert "python -m app.main --run-enabled-adapters --persist --scheduler &" in dockerfile


def test_zeabur_single_service_sets_backbone_source_gates() -> None:
    dockerfile = ENTRYPOINT.read_text(encoding="utf-8")
    expected_exports = (
        'export SOURCE_CWA_ENABLED="${SOURCE_CWA_ENABLED:-true}"',
        'export SOURCE_WRA_ENABLED="${SOURCE_WRA_ENABLED:-true}"',
        'export SOURCE_WRA_IOW_FLOOD_DEPTH_ENABLED="${SOURCE_WRA_IOW_FLOOD_DEPTH_ENABLED:-true}"',
        'export SOURCE_WRA_IOW_FLOOD_DEPTH_API_ENABLED="${SOURCE_WRA_IOW_FLOOD_DEPTH_API_ENABLED:-true}"',
        'export SOURCE_NCDR_CAP_ENABLED="${SOURCE_NCDR_CAP_ENABLED:-true}"',
        'export SOURCE_NCDR_CAP_API_ENABLED="${SOURCE_NCDR_CAP_API_ENABLED:-true}"',
        'export SOURCE_FLOOD_SENSOR_ENABLED="${SOURCE_FLOOD_SENSOR_ENABLED:-true}"',
        'export SOURCE_FLOOD_SENSOR_API_ENABLED="${SOURCE_FLOOD_SENSOR_API_ENABLED:-true}"',
        'export SOURCE_FLOOD_SENSOR_USE_LIVE="${SOURCE_FLOOD_SENSOR_USE_LIVE:-true}"',
        'export SOURCE_CIVIL_IOT_SEWER_ENABLED="${SOURCE_CIVIL_IOT_SEWER_ENABLED:-true}"',
        'export SOURCE_CIVIL_IOT_SEWER_API_ENABLED="${SOURCE_CIVIL_IOT_SEWER_API_ENABLED:-true}"',
        'export SOURCE_CIVIL_IOT_PUMP_ENABLED="${SOURCE_CIVIL_IOT_PUMP_ENABLED:-true}"',
        'export SOURCE_CIVIL_IOT_PUMP_API_ENABLED="${SOURCE_CIVIL_IOT_PUMP_API_ENABLED:-true}"',
        'export SOURCE_CIVIL_IOT_GATE_ENABLED="${SOURCE_CIVIL_IOT_GATE_ENABLED:-true}"',
        'export SOURCE_CIVIL_IOT_GATE_API_ENABLED="${SOURCE_CIVIL_IOT_GATE_API_ENABLED:-true}"',
        'export SOURCE_TAINAN_FLOOD_SENSOR_ENABLED="${SOURCE_TAINAN_FLOOD_SENSOR_ENABLED:-true}"',
        'export SOURCE_TAINAN_FLOOD_SENSOR_API_ENABLED="${SOURCE_TAINAN_FLOOD_SENSOR_API_ENABLED:-true}"',
    )

    for expected in expected_exports:
        assert expected in dockerfile

    assert 'required_adapter_keys="${REALTIME_BACKBONE_ADAPTER_KEYS:-${realtime_backbone_adapter_keys}}"' in dockerfile
    assert 'export WORKER_ENABLED_ADAPTER_KEYS="$(merge_adapter_keys "${required_adapter_keys}" "${configured_adapter_keys}")"' in dockerfile


def test_zeabur_single_service_runbook_lists_realtime_backbone() -> None:
    runbook = ZEABUR_ENV_RUNBOOK.read_text(encoding="utf-8")

    for adapter_key in EXPECTED_BACKBONE_ADAPTERS:
        assert adapter_key in runbook


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
    assert "exec python -m app.main --run-enabled-adapters --persist --scheduler" in entrypoint
