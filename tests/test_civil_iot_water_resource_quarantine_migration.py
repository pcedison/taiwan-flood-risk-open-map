from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "infra"
    / "migrations"
    / "0062_quarantine_civil_iot_water_resource.sql"
)

QUARANTINED_ADAPTER_KEYS = (
    "official.civil_iot.flood_sensor",
    "official.civil_iot.pump_water_level",
    "official.civil_iot.gate_water_level",
)


def test_water_resource_quarantine_is_explicit_and_preserves_rain_sewer() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "UPDATE data_sources" in sql
    assert "SET is_enabled = false" in sql
    assert "'availability_status', 'upstream_unavailable'" in sql
    assert "docs/reviews/civil-iot-source-recovery-2026-09-02.md" in sql
    assert "DELETE FROM ingestion_readiness_sources" in sql
    assert "readiness_count <> 9" in sql
    for adapter_key in QUARANTINED_ADAPTER_KEYS:
        assert sql.count(f"'{adapter_key}'") >= 3

    sewer_assertion = sql.split("SELECT is_enabled INTO sewer_enabled", 1)[1]
    assert "official.civil_iot.sewer_water_level" in sewer_assertion
    assert "sewer_enabled IS DISTINCT FROM true" in sewer_assertion
