from __future__ import annotations

from datetime import datetime, timezone

from app.domain.layers import fetch_map_layer, fetch_map_layers
from app.domain.evidence.repository import (
    RiskAssessmentPersistence,
    fetch_query_heat_snapshot,
    persist_risk_assessment,
    query_nearby_evidence,
)


def test_fetch_map_layers_reads_layer_metadata() -> None:
    updated_at = datetime(2026, 4, 30, 3, 0, tzinfo=timezone.utc)
    connection = _FakeConnection(
        rows=[
            {
                "layer_id": "flood-potential",
                "name": "Flood potential",
                "description": "Seeded layer",
                "category": "flood_potential",
                "status": "disabled",
                "minzoom": 8,
                "maxzoom": 18,
                "attribution": "Government open data",
                "tilejson_url": "/v1/layers/flood-potential/tilejson",
                "updated_at": updated_at,
                "metadata": {
                    "tiles": [
                        "https://tiles.placeholder.flood-risk.local/"
                        "flood-potential/{z}/{x}/{y}.pbf"
                    ],
                    "bounds": [119.3, 21.8, 122.1, 25.4],
                },
            }
        ]
    )

    layers = fetch_map_layers(
        database_url="postgresql://example.test/flood",
        connection_factory=lambda: connection,
    )

    sql, params = connection.cursor_instance.executions[0]
    assert "FROM map_layers" in sql
    assert "ORDER BY" in sql
    assert params == ()
    assert layers[0].id == "flood-potential"
    assert layers[0].status == "disabled"
    assert layers[0].metadata["bounds"] == [119.3, 21.8, 122.1, 25.4]


def test_fetch_map_layer_filters_by_layer_id() -> None:
    connection = _FakeConnection(
        rows=[
            {
                "layer_id": "query-heat",
                "name": "Query heat",
                "description": None,
                "category": "query_heat",
                "status": "disabled",
                "minzoom": 8,
                "maxzoom": 14,
                "attribution": None,
                "tilejson_url": "/v1/layers/query-heat/tilejson",
                "updated_at": None,
                "metadata": '{"tiles":["https://tiles.local/query-heat/{z}/{x}/{y}.pbf"]}',
            }
        ]
    )

    layer = fetch_map_layer(
        database_url="postgresql://example.test/flood",
        layer_id="query-heat",
        connection_factory=lambda: connection,
    )

    sql, params = connection.cursor_instance.executions[0]
    assert "WHERE layer_id = %s" in sql
    assert params == ("query-heat",)
    assert layer is not None
    assert layer.id == "query-heat"
    assert layer.metadata["tiles"] == ["https://tiles.local/query-heat/{z}/{x}/{y}.pbf"]


def test_fetch_query_heat_snapshot_buckets_nearby_location_queries() -> None:
    connection = _FakeConnection(
        row={
            "query_count": 17,
            "unique_approx_count": 6,
            "updated_at": datetime(2026, 4, 30, 3, 0, tzinfo=timezone.utc),
        }
    )

    snapshot = fetch_query_heat_snapshot(
        database_url="postgresql://example.test/flood",
        lat=25.033,
        lng=121.5654,
        radius_m=500,
        connection_factory=lambda: connection,
    )

    sql, params = connection.cursor_instance.executions[0]
    assert "FROM location_queries lq" in sql
    assert "ST_DWithin" in sql
    assert params == (121.5654, 25.033, "7 days", 500)
    assert snapshot.period == "P7D"
    assert snapshot.query_count == 17
    assert snapshot.query_count_bucket == "10-49"
    assert snapshot.unique_approx_count_bucket == "1-9"


def test_query_nearby_evidence_uses_point_on_surface_for_non_point_geometry() -> None:
    connection = _FakeConnection(rows=[])

    records = query_nearby_evidence(
        database_url="postgresql://example.test/flood",
        lat=25.033,
        lng=121.5654,
        radius_m=500,
        connection_factory=lambda: connection,
    )

    sql, params = connection.cursor_instance.executions[0]
    assert records == ()
    assert "ST_PointOnSurface(e.geom::geometry)" in sql
    assert params == (121.5654, 25.033, 500, 50)


def test_persist_risk_assessment_inserts_query_assessment_and_links_evidence() -> None:
    connection = _FakeConnection()
    created_at = datetime(2026, 4, 30, 3, 0, tzinfo=timezone.utc)
    expires_at = datetime(2026, 4, 30, 3, 10, tzinfo=timezone.utc)

    persist_risk_assessment(
        database_url="postgresql://example.test/flood",
        assessment=RiskAssessmentPersistence(
            assessment_id="d315d0e6-9c1e-475a-9118-f299d12d5c62",
            lat=25.033,
            lng=121.5654,
            radius_m=500,
            location_text="Taipei 101",
            score_version="risk-v0.1.0",
            realtime_score=12.5,
            historical_score=34.5,
            confidence_score=0.67,
            realtime_level="雿?",
            historical_level="擃?",
            explanation={"summary": "Stored assessment"},
            data_freshness=[{"source_id": "db-evidence", "health_status": "healthy"}],
            evidence_ids=("b3f22a36-7316-4e2a-92b6-c6f6443c8528",),
            created_at=created_at,
            expires_at=expires_at,
        ),
        connection_factory=lambda: connection,
    )

    sql, params = connection.cursor_instance.executions[0]
    assert "INSERT INTO location_queries" in sql
    assert "INSERT INTO risk_assessments" in sql
    assert "INSERT INTO risk_assessment_evidence" in sql
    assert "JOIN evidence ON evidence.id = ANY" in sql
    assert params[0:7] == (
        "Taipei 101",
        121.5654,
        25.033,
        500,
        "25.03,121.57",
        "25.03,121.57",
        created_at,
    )
    assert params[7] == "d315d0e6-9c1e-475a-9118-f299d12d5c62"
    assert params[12:14] == ("low", "high")
    assert params[-1] == ["b3f22a36-7316-4e2a-92b6-c6f6443c8528"]


class _FakeConnection:
    def __init__(
        self,
        *,
        row: dict[str, object] | None = None,
        rows: list[dict[str, object]] | None = None,
    ) -> None:
        self.cursor_instance = _FakeCursor(row=row, rows=rows)

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def cursor(self) -> "_FakeCursor":
        return self.cursor_instance


class _FakeCursor:
    def __init__(
        self,
        *,
        row: dict[str, object] | None = None,
        rows: list[dict[str, object]] | None = None,
    ) -> None:
        self._row = row
        self._rows = rows
        self.executions: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.executions.append((sql, params))

    def fetchone(self) -> dict[str, object]:
        assert self._row is not None
        return self._row

    def fetchall(self) -> list[dict[str, object]]:
        assert self._rows is not None
        return self._rows
