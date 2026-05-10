from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.domain.profiles import enqueue_profile_refresh_job, fetch_best_profile_for_point


def test_profile_migration_defines_cold_lookup_schema() -> None:
    migration_sql = (
        Path(__file__).resolve().parents[3]
        / "infra"
        / "migrations"
        / "0015_precomputed_risk_profiles.sql"
    ).read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS admin_area_profiles" in migration_sql
    assert "CREATE TABLE IF NOT EXISTS risk_grid_profiles" in migration_sql
    assert "CREATE TABLE IF NOT EXISTS profile_evidence_links" in migration_sql
    assert "CREATE TABLE IF NOT EXISTS profile_refresh_jobs" in migration_sql
    assert "CREATE TABLE IF NOT EXISTS evidence_embeddings" in migration_sql
    assert "idx_admin_area_profiles_geom" in migration_sql
    assert "idx_risk_grid_profiles_geom" in migration_sql
    assert "idx_profile_refresh_jobs_active_unique" in migration_sql
    assert "WHERE status IN ('queued', 'running')" in migration_sql
    assert "content_scope IN ('title_summary_metadata', 'metadata_only')" in migration_sql


def test_fetch_best_profile_for_point_reads_fresh_grid_or_admin_profile() -> None:
    now = datetime(2026, 5, 8, 2, 30, tzinfo=timezone.utc)
    connection = _FakeConnection(
        row={
            "profile_kind": "risk_grid",
            "profile_key": "h3:842ab57ffffffff",
            "profile_scope": "h3:8",
            "profile_radius_m": 1000,
            "score_version": "risk-v0.1.0",
            "realtime_level": "unknown",
            "historical_level": "high",
            "confidence_level": "medium",
            "evidence_counts": {"news": 2, "official": 1},
            "top_evidence_ids": ["b3f22a36-7316-4e2a-92b6-c6f6443c8528"],
            "latest_observed_at": None,
            "latest_occurred_at": now,
            "latest_ingested_at": now,
            "coverage_gaps": ["historical_news_backfill_partial"],
            "missing_sources": ["exact-radius refresh pending"],
            "computed_at": now,
            "expires_at": None,
            "status": "healthy",
            "distance_to_query_m": 123.4,
        }
    )

    profile = fetch_best_profile_for_point(
        database_url="postgresql://example.test/flood",
        lat=22.65646,
        lng=120.32574,
        radius_m=500,
        now=now,
        connection_factory=lambda: connection,
    )

    assert profile is not None
    sql, params = connection.cursor_instance.executions[0]
    assert "FROM admin_area_profiles ap" in sql
    assert "FROM risk_grid_profiles gp" in sql
    assert "ST_Covers" in sql
    assert "ORDER BY" in sql
    assert params == (120.32574, 22.65646, 120.32574, 22.65646, now, now, 500, now, now, 500)
    assert profile.profile_kind == "risk_grid"
    assert profile.historical_level == "high"
    assert profile.evidence_counts == {"news": 2, "official": 1}
    assert profile.coverage_gaps == ("historical_news_backfill_partial",)
    assert profile.missing_sources == ("exact-radius refresh pending",)


def test_enqueue_profile_refresh_job_is_idempotent_for_active_profiles() -> None:
    run_after = datetime(2026, 5, 8, 2, 45, tzinfo=timezone.utc)
    connection = _FakeConnection(row={"id": "0d0cc506-b034-4d48-9441-813d14de51a1"})

    job_id = enqueue_profile_refresh_job(
        database_url="postgresql://example.test/flood",
        profile_kind="admin_area",
        profile_key="village:64000050-本和里",
        priority=20,
        reason="query_heat_priority",
        run_after=run_after,
        payload={"radius_m": 2000},
        connection_factory=lambda: connection,
    )

    sql, params = connection.cursor_instance.executions[0]
    assert "INSERT INTO profile_refresh_jobs" in sql
    assert "ON CONFLICT DO NOTHING" in sql
    assert params[:5] == (
        "admin_area",
        "village:64000050-本和里",
        20,
        "query_heat_priority",
        run_after,
    )
    assert job_id == "0d0cc506-b034-4d48-9441-813d14de51a1"
    assert connection.commits == 1


class _FakeConnection:
    def __init__(self, *, row: dict[str, object] | None = None) -> None:
        self.cursor_instance = _FakeCursor(row=row)
        self.commits = 0

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def cursor(self) -> "_FakeCursor":
        return self.cursor_instance

    def commit(self) -> None:
        self.commits += 1


class _FakeCursor:
    def __init__(self, *, row: dict[str, object] | None = None) -> None:
        self._row = row
        self.executions: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.executions.append((sql, params))

    def fetchone(self) -> dict[str, object] | None:
        return self._row
