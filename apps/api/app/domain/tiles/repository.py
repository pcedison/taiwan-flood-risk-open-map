from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

import psycopg
from psycopg.rows import dict_row


ConnectionFactory = Callable[[], Any]


class TileLayerNotFound(RuntimeError):
    """Raised when a requested tile layer is not registered or seeded."""


class TileRepositoryUnavailable(RuntimeError):
    """Raised when tile storage cannot be queried."""


@dataclass(frozen=True)
class TileLayerSpec:
    layer_id: str
    vector_layer_id: str
    source_sql: str
    property_columns: tuple[str, ...]
    bounds_filter_sql: str


_LAYER_SPECS: dict[str, TileLayerSpec] = {
    "flood-potential": TileLayerSpec(
        layer_id="flood-potential",
        vector_layer_id="flood_potential",
        source_sql="""
            SELECT
                e.geom AS feature_geom,
                e.source_id,
                e.event_type AS category,
                e.confidence
            FROM evidence e
            WHERE
                e.event_type = 'flood_potential'
                AND e.ingestion_status = 'accepted'
                AND e.geom IS NOT NULL
        """,
        property_columns=("source_id", "category", "confidence"),
        bounds_filter_sql="src.feature_geom && ST_Transform(bounds.geom, 4326)",
    ),
    "query-heat": TileLayerSpec(
        layer_id="query-heat",
        vector_layer_id="query_heat",
        source_sql="""
            SELECT
                lq.geom AS feature_geom,
                COALESCE(lq.privacy_bucket, 'unknown') AS privacy_bucket,
                CASE
                    WHEN COUNT(*) >= 50 THEN '50+'
                    WHEN COUNT(*) >= 10 THEN '10-49'
                    WHEN COUNT(*) >= 1 THEN '1-9'
                    ELSE '0'
                END AS query_count_bucket,
                'P7D' AS period
            FROM location_queries lq
            WHERE
                lq.created_at >= now() - interval '7 days'
                AND lq.geom IS NOT NULL
            GROUP BY
                lq.geom,
                COALESCE(lq.privacy_bucket, 'unknown')
        """,
        property_columns=("privacy_bucket", "query_count_bucket", "period"),
        bounds_filter_sql="src.feature_geom && ST_Transform(bounds.geom, 4326)",
    ),
}


def known_tile_layer_ids() -> tuple[str, ...]:
    return tuple(_LAYER_SPECS)


def fetch_vector_tile(
    *,
    database_url: str,
    layer_id: str,
    z: int,
    x: int,
    y: int,
    connection_factory: ConnectionFactory | None = None,
) -> bytes:
    spec = _LAYER_SPECS.get(layer_id)
    if spec is None:
        raise TileLayerNotFound(layer_id)

    sql, params = build_mvt_sql(spec=spec, z=z, x=x, y=y)
    try:
        with _connect(database_url, connection_factory) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                row = cursor.fetchone()
    except (OSError, psycopg.Error) as exc:
        raise TileRepositoryUnavailable(str(exc)) from exc

    if row is None:
        raise TileLayerNotFound(layer_id)

    tile = _row_value(row, "tile")
    return _bytes(tile)


def build_mvt_sql(*, spec: TileLayerSpec, z: int, x: int, y: int) -> tuple[str, tuple[object, ...]]:
    property_select = ",\n                ".join(
        f"src.{column}" for column in spec.property_columns
    )
    sql = f"""
        WITH requested_layer AS (
            SELECT layer_id
            FROM map_layers
            WHERE layer_id = %s
            LIMIT 1
        ),
        bounds AS (
            SELECT ST_TileEnvelope(%s, %s, %s) AS geom
        ),
        src AS (
            {spec.source_sql}
        ),
        mvtgeom AS (
            SELECT
                ST_AsMVTGeom(
                    ST_Transform(src.feature_geom, 3857),
                    bounds.geom,
                    extent => 4096,
                    buffer => 64
                ) AS geom,
                {property_select}
            FROM src
            CROSS JOIN bounds
            WHERE
                EXISTS (SELECT 1 FROM requested_layer)
                AND {spec.bounds_filter_sql}
        )
        SELECT
            CASE
                WHEN EXISTS (SELECT 1 FROM requested_layer)
                THEN COALESCE(ST_AsMVT(mvtgeom, %s, 4096, 'geom'), '\\x'::bytea)
                ELSE NULL
            END AS tile
        FROM mvtgeom
    """
    return sql, (spec.layer_id, z, x, y, spec.vector_layer_id)


def _connect(database_url: str, connection_factory: ConnectionFactory | None) -> Any:
    if connection_factory is not None:
        return connection_factory()
    return psycopg.connect(database_url, connect_timeout=2, row_factory=dict_row)


def _row_value(row: object, key: str) -> object:
    if isinstance(row, dict):
        return row.get(key)
    return cast(Any, row)[0]


def _bytes(value: object) -> bytes:
    if value is None:
        raise TileLayerNotFound("seeded layer is missing")
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, memoryview):
        return value.tobytes()
    return bytes(cast(Any, value))
