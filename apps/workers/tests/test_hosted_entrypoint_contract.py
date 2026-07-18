from pathlib import Path


ENTRYPOINT = Path(__file__).resolve().parents[3] / "infra" / "docker" / "entrypoint.sh"


def _entrypoint() -> str:
    return ENTRYPOINT.read_text(encoding="utf-8")


def test_forced_backbone_preserves_operator_configured_local_adapters() -> None:
    script = _entrypoint()

    assert "merge_adapter_keys" in script
    assert 'local configured_adapter_keys="${WORKER_ENABLED_ADAPTER_KEYS:-}"' in script
    assert '"${required_adapter_keys}" "${configured_adapter_keys}"' in script


def test_tainan_flood_sensor_is_in_the_default_hosted_ingestion_path() -> None:
    script = _entrypoint()

    assert "local.tainan.flood_sensor" in script
    assert 'SOURCE_TAINAN_FLOOD_SENSOR_ENABLED:-true' in script
    assert 'SOURCE_TAINAN_FLOOD_SENSOR_API_ENABLED:-true' in script


def test_unified_service_shares_database_and_supervises_scheduler() -> None:
    script = _entrypoint()

    assert 'export DATABASE_URL="${worker_database_url}"' in script
    assert '"${DATABASE_URL}" != "${WORKER_DATABASE_URL}"' in script
    assert "must match for SERVICE_ROLE=all" in script
    assert 'wait -n "${api_pid}" "${web_pid}" "${scheduler_pid}"' in script
    assert "running initial official ingestion tick" not in script
    assert "first tick runs immediately" in script
    assert script.index("setup_ingestion_env\nfi\napply_migrations") < script.index(
        'echo "[start] launching api"'
    )


def test_unified_service_records_intentional_ingestion_disable_before_api_start() -> None:
    script = _entrypoint()

    disabled_command = "python -m app.main --record-runtime-sources-disabled"
    assert disabled_command in script
    assert script.index(disabled_command) < script.index('echo "[start] launching api"')
