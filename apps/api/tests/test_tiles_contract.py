from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.api.routes import tiles as tile_routes
from app.domain.tiles import TileLayerNotFound, TileRepositoryUnavailable, fetch_vector_tile
from app.main import create_app


client = TestClient(create_app())


def test_fetch_vector_tile_prefers_dedicated_layer_feature_table() -> None:
    connection = _FakeConnection(row={"tile": b"mvt-bytes"})

    tile = fetch_vector_tile(
        database_url="postgresql://example.test/flood",
        layer_id="flood-potential",
        z=8,
        x=215,
        y=107,
        connection_factory=lambda: connection,
    )

    sql, params = connection.cursor_instance.executions[0]
    assert tile == b"mvt-bytes"
    assert "FROM map_layers" in sql
    assert "WHERE layer_id = %s" in sql
    assert "FROM tile_cache_entries" in sql
    assert "FROM map_layer_features" in sql
    assert "AND (minzoom IS NULL OR minzoom <= %s)" in sql
    assert "AND (expires_at IS NULL OR expires_at > now())" in sql
    assert "FROM map_layer_features mlf" in sql
    assert "mlf.properties ->> 'source_id' AS source_id" in sql
    assert "NULLIF(mlf.properties ->> 'confidence', '')::numeric AS confidence" in sql
    assert "ST_TileEnvelope(%s, %s, %s)" in sql
    assert "ST_AsMVTGeom" in sql
    assert "ST_AsMVT(mvtgeom, %s, 4096, 'geom')" in sql
    assert "SELECT * FROM production_src" in sql
    assert "UNION ALL" in sql
    assert "SELECT * FROM fallback_src" in sql
    assert "AND NOT EXISTS (SELECT 1 FROM cached_tile)" in sql
    assert "WHEN EXISTS (SELECT 1 FROM cached_tile) THEN (SELECT tile_data FROM cached_tile)" in sql
    assert params == (
        "flood-potential",
        "flood-potential",
        8,
        215,
        107,
        "flood-potential",
        8,
        8,
        8,
        215,
        107,
        "flood-potential",
        8,
        8,
        "flood_potential",
    )


def test_fetch_vector_tile_keeps_explicit_fallback_when_layer_features_empty() -> None:
    connection = _FakeConnection(row={"tile": b"mvt-bytes"})

    fetch_vector_tile(
        database_url="postgresql://example.test/flood",
        layer_id="flood-potential",
        z=8,
        x=215,
        y=107,
        connection_factory=lambda: connection,
    )

    sql, _params = connection.cursor_instance.executions[0]
    assert "production_layer_has_features" in sql
    assert "WHERE NOT (SELECT has_features FROM production_layer_has_features)" in sql
    assert "FROM evidence e" in sql
    assert "e.event_type = 'flood_potential'" in sql


def test_tile_layer_feature_cache_migration_defines_cache_schema() -> None:
    migration = (
        Path(__file__).resolve().parents[3]
        / "infra"
        / "migrations"
        / "0007_tile_layer_feature_cache.sql"
    ).read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS map_layer_features" in migration
    assert "layer_id text NOT NULL REFERENCES map_layers(layer_id) ON DELETE CASCADE" in migration
    assert "geom geometry(Geometry, 4326) NOT NULL" in migration
    assert "properties jsonb NOT NULL DEFAULT '{}'::jsonb" in migration
    assert "UNIQUE (layer_id, feature_key)" in migration
    assert "CREATE INDEX IF NOT EXISTS idx_map_layer_features_geom" in migration
    assert "CREATE TABLE IF NOT EXISTS tile_cache_entries" in migration
    assert "tile_data bytea NOT NULL" in migration
    assert "UNIQUE (layer_id, z, x, y)" in migration
    assert "CREATE INDEX IF NOT EXISTS idx_tile_cache_entries_lookup" in migration


def test_fetch_vector_tile_rejects_unknown_layer_without_sql() -> None:
    connection = _FakeConnection(row={"tile": b"unused"})

    with pytest.raises(TileLayerNotFound):
        fetch_vector_tile(
            database_url="postgresql://example.test/flood",
            layer_id="not-a-layer",
            z=8,
            x=215,
            y=107,
            connection_factory=lambda: connection,
        )

    assert connection.cursor_instance.executions == []


def test_fetch_vector_tile_reports_db_unavailable() -> None:
    def unavailable() -> _FakeConnection:
        raise OSError("database unavailable")

    with pytest.raises(TileRepositoryUnavailable):
        fetch_vector_tile(
            database_url="postgresql://example.test/flood",
            layer_id="query-heat",
            z=8,
            x=215,
            y=107,
            connection_factory=unavailable,
        )


def test_tile_endpoint_returns_binary_tile_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_fetch(**kwargs: object) -> bytes:
        assert kwargs["layer_id"] == "query-heat"
        assert kwargs["z"] == 8
        assert kwargs["x"] == 215
        assert kwargs["y"] == 107
        return b"mvt-bytes"

    monkeypatch.setattr(tile_routes, "fetch_vector_tile", fake_fetch)

    response = client.get("/v1/tiles/query-heat/8/215/107.mvt")

    assert response.status_code == 200
    assert response.content == b"mvt-bytes"
    assert response.headers["content-type"] == "application/vnd.mapbox-vector-tile"
    assert response.headers["cache-control"] == "public, max-age=60"
    assert response.headers["x-tile-layer"] == "query-heat"


def test_tile_endpoint_returns_404_for_unknown_layer(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(**_kwargs: object) -> bytes:
        raise TileLayerNotFound("missing")

    monkeypatch.setattr(tile_routes, "fetch_vector_tile", missing)

    response = client.get("/v1/tiles/not-a-layer/8/215/107.mvt")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_tile_endpoint_returns_503_when_db_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(**_kwargs: object) -> bytes:
        raise TileRepositoryUnavailable("database unavailable")

    monkeypatch.setattr(tile_routes, "fetch_vector_tile", unavailable)

    response = client.get("/v1/tiles/query-heat/8/215/107.mvt")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "tiles_unavailable"


class _FakeConnection:
    def __init__(self, *, row: dict[str, object] | None = None) -> None:
        self.cursor_instance = _FakeCursor(row=row)

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def cursor(self) -> "_FakeCursor":
        return self.cursor_instance


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
