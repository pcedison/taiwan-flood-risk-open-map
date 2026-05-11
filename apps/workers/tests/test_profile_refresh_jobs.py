from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.jobs.profiles import (
    claim_profile_refresh_jobs,
    complete_profile_refresh_job,
    rebuild_risk_profile,
    seed_admin_area_profiles_from_geocoder,
    seed_grid_profiles_from_query_heat,
)


def test_claim_profile_refresh_jobs_leases_due_jobs_in_priority_order() -> None:
    run_after = datetime(2026, 5, 8, 3, 0, tzinfo=timezone.utc)
    lease_expires_at = datetime(2026, 5, 8, 3, 5, tzinfo=timezone.utc)
    connection = _FakeConnection(
        rows=[
            {
                "id": "0d0cc506-b034-4d48-9441-813d14de51a1",
                "profile_kind": "risk_grid",
                "profile_key": "h3:842ab57ffffffff",
                "priority": 30,
                "reason": "query_heat_priority",
                "attempts": 1,
                "max_attempts": 3,
                "payload": {"radius_m": 2000},
                "run_after": run_after,
                "lease_expires_at": lease_expires_at,
            }
        ]
    )

    jobs = claim_profile_refresh_jobs(
        database_url="postgresql://example.test/flood",
        worker_id="worker-a",
        limit=3,
        lease_seconds=120,
        connection_factory=lambda: connection,
    )

    sql, params = connection.cursor_instance.executions[0]
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "UPDATE profile_refresh_jobs jobs" in sql
    assert "status = 'running'" in sql
    assert "lease_expires_at <= now()" in sql
    assert "attempts < max_attempts" in sql
    assert params == (3, "worker-a", 120)
    assert jobs[0].profile_key == "h3:842ab57ffffffff"
    assert jobs[0].payload == {"radius_m": 2000}
    assert connection.commits == 1


def test_seed_admin_area_profiles_from_geocoder_seeds_village_profiles_and_refresh_jobs() -> None:
    connection = _FakeConnection(row={"seeded": 2, "refresh_jobs_enqueued": 2})

    summary = seed_admin_area_profiles_from_geocoder(
        database_url="postgresql://example.test/flood",
        source_key="moi-village-boundary-twd97-geographic",
        limit=10,
        connection_factory=lambda: connection,
    )

    sql, params = connection.cursor_instance.executions[0]
    assert "FROM geocoder_open_data_entries" in sql
    assert "INSERT INTO admin_area_profiles" in sql
    assert "INSERT INTO profile_refresh_jobs" in sql
    assert "ST_Buffer(centroid::geography" in sql
    assert "'source_key', %s::text" in sql
    assert "'scope', %s::text" in sql
    assert params[:4] == (
        "moi-village-boundary-twd97-geographic",
        10,
        "village",
        "village",
    )
    assert summary.profile_kind == "admin_area"
    assert summary.seeded == 2
    assert summary.refresh_jobs_enqueued == 2
    assert connection.commits == 1


def test_seed_grid_profiles_from_query_heat_uses_existing_h3_or_privacy_bucket_shards() -> None:
    connection = _FakeConnection(row={"seeded": 3, "refresh_jobs_enqueued": 1})

    summary = seed_grid_profiles_from_query_heat(
        database_url="postgresql://example.test/flood",
        grid_system="h3",
        grid_resolution="8",
        include_privacy_bucket_fallback=True,
        limit=5,
        connection_factory=lambda: connection,
    )

    sql, params = connection.cursor_instance.executions[0]
    assert "WITH query_rows AS" in sql
    assert "FROM location_queries lq" in sql
    assert "FROM query_rows" in sql
    assert "GROUP BY raw_grid_key" in sql
    assert "INSERT INTO risk_grid_profiles" in sql
    assert "grid_geometry_approximated_from_query_heat" in sql
    assert "INSERT INTO profile_refresh_jobs" in sql
    assert "ELSE %s::text || ':' || raw_grid_key" in sql
    assert "'grid_system', %s::text" in sql
    assert "'grid_resolution', %s::text" in sql
    assert params[:3] == (True, 5, "h3")
    assert summary.profile_kind == "risk_grid"
    assert summary.seeded == 3
    assert summary.refresh_jobs_enqueued == 1
    assert connection.commits == 1


def test_complete_profile_refresh_job_marks_running_job_finished() -> None:
    connection = _FakeConnection(row={"id": "0d0cc506-b034-4d48-9441-813d14de51a1"})

    completed = complete_profile_refresh_job(
        database_url="postgresql://example.test/flood",
        job_id="0d0cc506-b034-4d48-9441-813d14de51a1",
        status="succeeded",
        connection_factory=lambda: connection,
    )

    sql, params = connection.cursor_instance.executions[0]
    assert "UPDATE profile_refresh_jobs" in sql
    assert "AND status = 'running'" in sql
    assert params == ("succeeded", None, "0d0cc506-b034-4d48-9441-813d14de51a1")
    assert completed is True
    assert connection.commits == 1


def test_complete_profile_refresh_job_requires_error_for_failed_status() -> None:
    with pytest.raises(ValueError, match="error_message"):
        complete_profile_refresh_job(
            database_url="postgresql://example.test/flood",
            job_id="0d0cc506-b034-4d48-9441-813d14de51a1",
            status="failed",
            error_message=None,
        )


def test_rebuild_risk_profile_scores_and_links_existing_profile() -> None:
    computed_at = datetime(2026, 5, 8, 3, 15, tzinfo=timezone.utc)
    connection = _FakeConnection(
        row={
            "profile_key": "village:64000050-本和里",
            "evidence_count": 3,
            "top_evidence_ids": [
                "b3f22a36-7316-4e2a-92b6-c6f6443c8528",
                "62f677b5-ae0c-44d7-9e65-f0567a92a5ca",
            ],
            "realtime_level": "unknown",
            "historical_level": "high",
            "confidence_level": "medium",
            "computed_at": computed_at,
        }
    )

    summary = rebuild_risk_profile(
        database_url="postgresql://example.test/flood",
        profile_kind="admin_area",
        profile_key="village:64000050-本和里",
        now=computed_at,
        connection_factory=lambda: connection,
    )

    assert summary is not None
    sql, params = connection.cursor_instance.executions[0]
    assert "FROM admin_area_profiles" in sql
    assert "FROM evidence e" in sql
    assert "e.ingestion_status = 'accepted'" in sql
    assert "UPDATE admin_area_profiles profile" in sql
    assert "INSERT INTO profile_evidence_links" in sql
    assert "historical_news_backfill_partial" in sql
    assert params == (
        "village:64000050-本和里",
        computed_at,
        computed_at,
        computed_at,
        computed_at,
        "admin_area",
        "village:64000050-本和里",
        "admin_area",
        computed_at,
    )
    assert summary.profile_kind == "admin_area"
    assert summary.profile_key == "village:64000050-本和里"
    assert summary.evidence_count == 3
    assert summary.historical_level == "high"
    assert summary.top_evidence_ids == (
        "b3f22a36-7316-4e2a-92b6-c6f6443c8528",
        "62f677b5-ae0c-44d7-9e65-f0567a92a5ca",
    )
    assert connection.commits == 1


def test_rebuild_risk_profile_rejects_unknown_profile_kind() -> None:
    with pytest.raises(ValueError, match="profile_kind"):
        rebuild_risk_profile(
            database_url="postgresql://example.test/flood",
            profile_kind="parcel",
            profile_key="bad",
        )


class _FakeConnection:
    def __init__(
        self,
        *,
        row: dict[str, object] | None = None,
        rows: list[dict[str, object]] | None = None,
    ) -> None:
        self.cursor_instance = _FakeCursor(row=row, rows=rows)
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
    def __init__(
        self,
        *,
        row: dict[str, object] | None = None,
        rows: list[dict[str, object]] | None = None,
    ) -> None:
        self._row = row
        self._rows = rows or []
        self.executions: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.executions.append((sql, params))

    def fetchone(self) -> dict[str, object] | None:
        return self._row

    def fetchall(self) -> list[dict[str, object]]:
        return self._rows
