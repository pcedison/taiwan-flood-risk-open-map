from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    REPO_ROOT
    / "infra"
    / "migrations"
    / "0059_historical_coverage_15y_retention.sql"
)


def test_migration_expands_coverage_and_retains_rolling_history() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "generate_series(2012, 2026)" in sql
    assert "coverage_year BETWEEN 2012 AND 2100" in sql
    assert "'snapshot_generation_mode'" in sql
    assert "'append_historical_revisions'" in sql
    assert "'public_history_window_years', 15" in sql
    assert "'{rolling_lookback_years}'" in sql
    assert "'15'::jsonb" in sql
