from pathlib import Path
import re

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = REPO_ROOT / "infra" / "migrations" / "0057_ingestion_runtime_readiness.sql"
REGISTRY = REPO_ROOT / "config" / "source-registry.yaml"


def test_migration_persists_scheduler_heartbeat_without_holder_or_secret_fields() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS ingestion_scheduler_heartbeats" in sql
    assert "last_seen_at timestamptz NOT NULL" in sql
    assert "stale_after_seconds integer NOT NULL" in sql
    heartbeat_table = sql.split("CREATE TABLE IF NOT EXISTS ingestion_scheduler_heartbeats", 1)[1]
    heartbeat_table = heartbeat_table.split(");", 1)[0]
    for forbidden in ("holder_id", "database_url", "credential", "secret", "source_url"):
        assert forbidden not in heartbeat_table


def test_migrated_readiness_profile_matches_registry_deployment_defaults() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    payload = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    expected = {
        source["adapter_key"] for source in payload["sources"] if source["deployment_default"]
    }
    migrated = set(
        re.findall(
            r"\('production_backbone', '([^']+)', "
            r"'(?:national_realtime|local_realtime|nationwide_history)', \d+\)",
            sql,
        )
    )

    assert migrated == expected
    assert len(migrated) == 11


def test_historical_source_has_a_daily_not_realtime_stale_gate() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert (
        "('production_backbone', 'official.wra.historical_flood', "
        "'nationwide_history', 90000)"
    ) in sql
