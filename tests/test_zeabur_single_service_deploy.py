from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = REPO_ROOT / "Dockerfile"
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
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    for adapter_key in EXPECTED_BACKBONE_ADAPTERS:
        assert adapter_key in dockerfile


def test_zeabur_single_service_autostarts_backbone_when_database_is_attached() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert 'SINGLE_SERVICE_INGESTION_SCHEDULER_ENABLED:-auto' in dockerfile
    assert 'worker_database_url="${WORKER_DATABASE_URL:-${DATABASE_URL:-}}"' in dockerfile
    assert 'realtime_backbone_force_ingestion="${REALTIME_BACKBONE_FORCE_INGESTION_ON_START:-true}"' in dockerfile
    assert 'realtime_backbone_ingestion_disabled="${REALTIME_BACKBONE_INGESTION_DISABLED:-false}"' in dockerfile
    assert 'realtime_backbone_adapter_keys="official.cwa.rainfall,official.cwa.tide_level,official.wra.water_level,official.wra_iow.flood_depth,official.ncdr.cap,official.civil_iot.flood_sensor,official.civil_iot.sewer_water_level,official.civil_iot.pump_water_level,official.civil_iot.gate_water_level"' in dockerfile
    assert 'if [ -n "${worker_database_url}" ]; then' in dockerfile


def test_zeabur_single_service_applies_migrations_before_startup() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert "COPY infra/migrations /app/infra/migrations" in dockerfile
    assert "COPY infra/scripts/apply_migrations.py /app/infra/scripts/apply_migrations.py" in dockerfile
    assert 'RUN_DATABASE_MIGRATIONS_ON_START:-true' in dockerfile
    assert 'python /app/infra/scripts/apply_migrations.py --database-url "${worker_database_url}"' in dockerfile


def test_zeabur_single_service_runs_initial_ingestion_before_scheduler_loop() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert 'python -m app.main --run-enabled-adapters --persist || echo "[start] initial official ingestion tick failed; scheduler will retry"' in dockerfile
    assert "python -m app.main --run-enabled-adapters --persist --scheduler &" in dockerfile


def test_zeabur_single_service_sets_backbone_source_gates() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
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
    )

    for expected in expected_exports:
        assert expected in dockerfile

    assert 'export WORKER_ENABLED_ADAPTER_KEYS="${REALTIME_BACKBONE_ADAPTER_KEYS:-${realtime_backbone_adapter_keys}}"' in dockerfile


def test_zeabur_single_service_runbook_lists_realtime_backbone() -> None:
    runbook = ZEABUR_ENV_RUNBOOK.read_text(encoding="utf-8")

    for adapter_key in EXPECTED_BACKBONE_ADAPTERS:
        assert adapter_key in runbook
