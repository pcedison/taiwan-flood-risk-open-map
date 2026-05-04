from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from app.jobs.tile_cache import (
    PostgresTileCacheWriter,
    TileCacheUnavailable,
    TileLayerUnsupported,
)


EXPIRES_AT = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc)


def test_refresh_flood_potential_layer_features_upserts_accepted_evidence() -> None:
    connection = _FakeConnection(fetch_rows=[(2,)])
    writer = PostgresTileCacheWriter(connection_factory=lambda: connection)

    result = writer.refresh_layer_features(limit=100, expires_at=EXPIRES_AT)

    assert result.layer_id == "flood-potential"
    assert result.refreshed == 2
    assert connection.commits == 1
    sql, params = connection.cursor_instance.executions[0]
    assert "WITH requested_layer AS" in sql
    assert "FROM map_layers" in sql
    assert "WHERE layer_id = %s" in sql
    assert "SELECT DISTINCT ON (e.source_id)" in sql
    assert "FROM evidence e" in sql
    assert "e.ingestion_status = 'accepted'" in sql
    assert "e.event_type = %s" in sql
    assert "e.geom IS NOT NULL" in sql
    assert "INSERT INTO map_layer_features" in sql
    assert "CROSS JOIN requested_layer" in sql
    assert "ON CONFLICT (layer_id, feature_key) DO UPDATE SET" in sql
    assert "NOT ST_Equals(map_layer_features.geom, EXCLUDED.geom)" in sql
    assert "SELECT count(*) FROM upserted" in sql
    assert params == (
        "flood-potential",
        "flood_potential",
        100,
        EXPIRES_AT,
        '{"refreshed_by":"workers.tile_cache"}',
    )


def test_refresh_flood_potential_layer_features_handles_empty_result() -> None:
    connection = _FakeConnection(fetch_rows=[(0,)])
    writer = PostgresTileCacheWriter(connection_factory=lambda: connection)

    result = writer.refresh_layer_features()

    assert result.refreshed == 0
    assert connection.commits == 1
    sql, params = connection.cursor_instance.executions[0]
    assert "LIMIT %s" not in sql
    assert params == (
        "flood-potential",
        "flood_potential",
        None,
        '{"refreshed_by":"workers.tile_cache"}',
    )


def test_refresh_layer_features_accepts_refresh_metadata() -> None:
    connection = _FakeConnection(fetch_rows=[(1,)])
    writer = PostgresTileCacheWriter(connection_factory=lambda: connection)

    result = writer.refresh_layer_features(
        expires_at=EXPIRES_AT,
        refresh_metadata={"refresh_reason": "source-refresh"},
    )

    assert result.refreshed == 1
    sql, params = connection.cursor_instance.executions[0]
    assert "source_features.metadata || %s::jsonb" in sql
    assert params == (
        "flood-potential",
        "flood_potential",
        EXPIRES_AT,
        '{"refresh_reason":"source-refresh"}',
    )


def test_refresh_layer_features_reports_db_unavailable() -> None:
    writer = PostgresTileCacheWriter(connection_factory=lambda: _BrokenConnection())

    try:
        writer.refresh_layer_features()
    except TileCacheUnavailable as exc:
        assert "database unavailable" in str(exc)
    else:
        raise AssertionError("expected TileCacheUnavailable")


def test_refresh_layer_features_rejects_unsupported_layer_without_sql() -> None:
    connection = _FakeConnection(fetch_rows=[(0,)])
    writer = PostgresTileCacheWriter(connection_factory=lambda: connection)

    try:
        writer.refresh_layer_features(layer_id="query-heat")
    except TileLayerUnsupported as exc:
        assert str(exc) == "query-heat"
    else:
        raise AssertionError("expected TileLayerUnsupported")

    assert connection.cursor_instance.executions == []


def test_upsert_tile_cache_entry_writes_cache_entry() -> None:
    connection = _FakeConnection(fetch_rows=[("cache-entry-id",)])
    writer = PostgresTileCacheWriter(connection_factory=lambda: connection)

    result = writer.upsert_tile_cache_entry(
        layer_id="flood-potential",
        z=8,
        x=215,
        y=107,
        tile_data=b"mvt-bytes",
        content_hash="hash-1",
        expires_at=EXPIRES_AT,
        metadata={"source": "unit"},
    )

    assert result.cache_entry_id == "cache-entry-id"
    assert result.content_hash == "hash-1"
    assert connection.commits == 1
    sql, params = connection.cursor_instance.executions[0]
    assert "INSERT INTO tile_cache_entries" in sql
    assert "tile_data" in sql
    assert "content_hash" in sql
    assert "ON CONFLICT (layer_id, z, x, y) DO UPDATE SET" in sql
    assert "tile_data = EXCLUDED.tile_data" in sql
    assert "content_hash = EXCLUDED.content_hash" in sql
    assert "expires_at = EXCLUDED.expires_at" in sql
    assert params == (
        "flood-potential",
        8,
        215,
        107,
        b"mvt-bytes",
        "hash-1",
        EXPIRES_AT,
        '{"source":"unit"}',
    )


def test_upsert_tile_cache_entry_hashes_tile_data_when_content_hash_is_missing() -> None:
    connection = _FakeConnection(fetch_rows=[("cache-entry-id",)])
    writer = PostgresTileCacheWriter(connection_factory=lambda: connection)

    result = writer.upsert_tile_cache_entry(
        layer_id="flood-potential",
        z=8,
        x=215,
        y=107,
        tile_data=b"generated-tile",
    )

    expected_hash = sha256(b"generated-tile").hexdigest()
    assert result.content_hash == expected_hash
    assert connection.cursor_instance.executions[0][1][5] == expected_hash


def test_upsert_tile_cache_entry_rejects_out_of_bounds_tile_without_sql() -> None:
    connection = _FakeConnection(fetch_rows=[("cache-entry-id",)])
    writer = PostgresTileCacheWriter(connection_factory=lambda: connection)

    try:
        writer.upsert_tile_cache_entry(
            layer_id="flood-potential",
            z=8,
            x=256,
            y=107,
            tile_data=b"mvt-bytes",
        )
    except ValueError as exc:
        assert "x must be within the zoom tile bounds" in str(exc)
    else:
        raise AssertionError("expected ValueError")

    assert connection.cursor_instance.executions == []


def test_prune_expired_deletes_bounded_expired_cache_and_features() -> None:
    connection = _FakeConnection(fetch_rows=[(4,), (2,)])
    writer = PostgresTileCacheWriter(connection_factory=lambda: connection)

    result = writer.prune_expired(
        expired_before=EXPIRES_AT,
        layer_id="flood-potential",
        limit=500,
    )

    assert result.layer_id == "flood-potential"
    assert result.expired_before == EXPIRES_AT
    assert result.tile_cache_deleted == 4
    assert result.features_deleted == 2
    assert connection.commits == 1
    cache_sql, cache_params = connection.cursor_instance.executions[0]
    features_sql, features_params = connection.cursor_instance.executions[1]
    assert "FROM tile_cache_entries" in cache_sql
    assert "DELETE FROM tile_cache_entries" in cache_sql
    assert "expires_at IS NOT NULL" in cache_sql
    assert "expires_at <= %s" in cache_sql
    assert "AND layer_id = %s" in cache_sql
    assert "LIMIT %s" in cache_sql
    assert cache_params == (EXPIRES_AT, "flood-potential", 500)
    assert "FROM map_layer_features" in features_sql
    assert "DELETE FROM map_layer_features" in features_sql
    assert features_params == (EXPIRES_AT, "flood-potential", 500)


def test_prune_expired_requires_positive_limit_without_sql() -> None:
    connection = _FakeConnection(fetch_rows=[(0,)])
    writer = PostgresTileCacheWriter(connection_factory=lambda: connection)

    try:
        writer.prune_expired(expired_before=EXPIRES_AT, limit=0)
    except ValueError as exc:
        assert "limit must be greater than 0" in str(exc)
    else:
        raise AssertionError("expected ValueError")

    assert connection.cursor_instance.executions == []


def test_invalidate_layer_marks_features_and_deletes_layer_cache() -> None:
    connection = _FakeConnection(fetch_rows=[(3,), (5,)])
    writer = PostgresTileCacheWriter(connection_factory=lambda: connection)

    result = writer.invalidate_layer(
        layer_id="flood-potential",
        invalidated_at=EXPIRES_AT,
        reason="source-refresh",
    )

    assert result.layer_id == "flood-potential"
    assert result.invalidated_at == EXPIRES_AT
    assert result.features_invalidated == 3
    assert result.tile_cache_deleted == 5
    assert connection.commits == 1
    feature_sql, feature_params = connection.cursor_instance.executions[0]
    cache_sql, cache_params = connection.cursor_instance.executions[1]
    assert "UPDATE map_layer_features" in feature_sql
    assert "metadata = metadata || %s::jsonb" in feature_sql
    assert "layer_id = %s" in feature_sql
    assert "expires_at IS NULL OR expires_at > now()" in feature_sql
    assert feature_params == (
        EXPIRES_AT,
        EXPIRES_AT,
        (
            '{"invalidated_at":"2026-04-30 12:00:00+00:00",'
            '"invalidated_by":"workers.tile_cache",'
            '"invalidation_reason":"source-refresh"}'
        ),
        "flood-potential",
    )
    assert "DELETE FROM tile_cache_entries" in cache_sql
    assert "WHERE layer_id = %s" in cache_sql
    assert cache_params == ("flood-potential",)


def test_invalidate_layer_rejects_unsupported_layer_without_sql() -> None:
    connection = _FakeConnection(fetch_rows=[(0,)])
    writer = PostgresTileCacheWriter(connection_factory=lambda: connection)

    try:
        writer.invalidate_layer(layer_id="query-heat", invalidated_at=EXPIRES_AT)
    except TileLayerUnsupported as exc:
        assert str(exc) == "query-heat"
    else:
        raise AssertionError("expected TileLayerUnsupported")

    assert connection.cursor_instance.executions == []


class _FakeConnection:
    def __init__(self, *, fetch_rows: list[tuple[Any, ...] | None]) -> None:
        self.cursor_instance = _FakeCursor(fetch_rows=fetch_rows)
        self.commits = 0

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.commits += 1


class _FakeCursor:
    def __init__(self, *, fetch_rows: list[tuple[Any, ...] | None]) -> None:
        self._fetch_rows = fetch_rows
        self.executions: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.executions.append((sql, params))

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._fetch_rows.pop(0)


class _BrokenConnection:
    def __enter__(self) -> _BrokenConnection:
        raise RuntimeError("database unavailable")

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None
