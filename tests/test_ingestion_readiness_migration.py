from pathlib import Path
import re

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = REPO_ROOT / "infra" / "migrations" / "0057_ingestion_runtime_readiness.sql"
PROFILE_MIGRATIONS = (
    MIGRATION,
    REPO_ROOT / "infra" / "migrations" / "0058_nstc_recent_history_ingestion.sql",
    REPO_ROOT / "infra" / "migrations" / "0062_quarantine_civil_iot_water_resource.sql",
)
REGISTRY = REPO_ROOT / "config" / "source-registry.yaml"


def test_migration_persists_scheduler_heartbeat_without_holder_or_secret_fields() -> None:
    sql = "\n".join(path.read_text(encoding="utf-8") for path in PROFILE_MIGRATIONS)

    assert "CREATE TABLE IF NOT EXISTS ingestion_scheduler_heartbeats" in sql
    assert "last_seen_at timestamptz NOT NULL" in sql
    assert "stale_after_seconds integer NOT NULL" in sql
    heartbeat_table = sql.split("CREATE TABLE IF NOT EXISTS ingestion_scheduler_heartbeats", 1)[1]
    heartbeat_table = heartbeat_table.split(");", 1)[0]
    for forbidden in ("holder_id", "database_url", "credential", "secret", "source_url"):
        assert forbidden not in heartbeat_table


def test_migrated_readiness_profile_matches_registry_deployment_defaults() -> None:
    sql = "\n".join(path.read_text(encoding="utf-8") for path in PROFILE_MIGRATIONS)
    payload = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    expected = {
        source["adapter_key"] for source in payload["sources"] if source["deployment_default"]
    }
    migrated = set(
        re.findall(
            r"\(\s*'production_backbone'\s*,\s*'([^']+)'\s*,\s*"
            r"'(?:national_realtime|local_realtime|nationwide_history)'\s*,\s*\d+\s*\)",
            sql,
        )
    )
    quarantined = set(
        re.findall(
            r"DELETE FROM ingestion_readiness_sources.*?adapter_key IN \((.*?)\);",
            sql,
            flags=re.DOTALL,
        )[0].replace("'", "").replace("\n", " ").replace(" ", "").split(",")
    )
    migrated -= quarantined

    assert migrated == expected
    assert len(migrated) == 9


def test_historical_source_has_a_daily_not_realtime_stale_gate() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert (
        "('production_backbone', 'official.wra.historical_flood', "
        "'nationwide_history', 90000)"
    ) in sql
