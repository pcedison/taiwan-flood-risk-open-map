from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from app.api.routes import tiles as tile_routes
from app.domain.tiles import TileLayerNotFound, TileRepositoryUnavailable, fetch_vector_tile
from app.main import create_app


client = TestClient(create_app())


def test_fetch_vector_tile_builds_postgis_mvt_sql_for_seeded_layer() -> None:
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
    assert "ST_TileEnvelope(%s, %s, %s)" in sql
    assert "ST_AsMVTGeom" in sql
    assert "ST_AsMVT(mvtgeom, %s, 4096, 'geom')" in sql
    assert "FROM evidence e" in sql
    assert "e.event_type = 'flood_potential'" in sql
    assert params == ("flood-potential", 8, 215, 107, "flood_potential")


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
