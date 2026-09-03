from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = REPO_ROOT / "infra" / "migrations" / "0060_historical_event_semantics.sql"


def test_migration_preserves_annual_precision_and_stable_record_identity() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    for table in ("staging_evidence", "evidence"):
        assert f"ALTER TABLE {table}" in sql
    assert "ADD COLUMN IF NOT EXISTS event_year integer" in sql
    assert "ADD COLUMN IF NOT EXISTS temporal_precision text" in sql
    assert "ADD COLUMN IF NOT EXISTS event_start_at timestamptz" in sql
    assert "ADD COLUMN IF NOT EXISTS event_end_at timestamptz" in sql
    assert "ADD COLUMN IF NOT EXISTS source_record_key text" in sql
    assert "temporal_precision IN ('instant', 'day', 'month', 'year', 'unknown')" in sql
    assert "temporal_precision <> 'year'" in sql
    assert "occurred_at IS NULL" in sql
    assert "observed_at IS NULL" in sql
    assert "source.adapter_key = 'official.nstc.flood_disaster_points'" in sql
    assert "temporal_precision = 'year'" in sql
    assert "digest(" in sql
    assert "'sha256'" in sql
    assert "'FM999990.000000'" in sql
    assert "md5(" not in sql
    assert "CREATE INDEX IF NOT EXISTS idx_evidence_flood_station_episode_time" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_evidence_source_record_key_year" in sql


def test_migration_removes_legacy_annual_snapshot_timestamps() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    annual_updates = sql.split(
        "-- Dataset 130016 supplies a year but no event date.",
        maxsplit=1,
    )[1]

    assert "occurred_at = NULL" in annual_updates
    assert "observed_at = NULL" in annual_updates
    assert "source_timestamp_min = NULL" in annual_updates
    assert "source_timestamp_max = NULL" in annual_updates
    assert "make_timestamptz" not in annual_updates
