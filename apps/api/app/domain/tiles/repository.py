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
    fallback_source_sql: str
    property_columns: tuple[str, ...]
    production_property_sql: tuple[str, ...]
    bounds_filter_sql: str


_LAYER_SPECS: dict[str, TileLayerSpec] = {
    "flood-potential": TileLayerSpec(
        layer_id="flood-potential",
        vector_layer_id="flood_potential",
        fallback_source_sql="""
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
        production_property_sql=(
            "mlf.properties ->> 'source_id' AS source_id",
            "mlf.properties ->> 'category' AS category",
            "NULLIF(mlf.properties ->> 'confidence', '')::numeric AS confidence",
        ),
        bounds_filter_sql="src.feature_geom && ST_Transform(bounds.geom, 4326)",
    ),
    "query-heat": TileLayerSpec(
        layer_id="query-heat",
        vector_layer_id="query_heat",
        fallback_source_sql="""
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
        production_property_sql=(
            "mlf.properties ->> 'privacy_bucket' AS privacy_bucket",
            "mlf.properties ->> 'query_count_bucket' AS query_count_bucket",
            "mlf.properties ->> 'period' AS period",
        ),
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
    production_property_select = ",\n                ".join(spec.production_property_sql)
    sql = f"""
        WITH requested_layer AS (
            SELECT layer_id
            FROM map_layers
            WHERE layer_id = %s
            LIMIT 1
        ),
        cached_tile AS (
            SELECT tile_data
            FROM tile_cache_entries
            WHERE
                layer_id = %s
                AND z = %s
                AND x = %s
                AND y = %s
                AND (expires_at IS NULL OR expires_at > now())
            ORDER BY generated_at DESC
            LIMIT 1
        ),
        production_layer_has_features AS (
            SELECT EXISTS (
                SELECT 1
                FROM map_layer_features
                WHERE
                    layer_id = %s
                    AND geom IS NOT NULL
                    AND (minzoom IS NULL OR minzoom <= %s)
                    AND (maxzoom IS NULL OR maxzoom >= %s)
                    AND (expires_at IS NULL OR expires_at > now())
                LIMIT 1
            ) AS has_features
        ),
        bounds AS (
            SELECT ST_TileEnvelope(%s, %s, %s) AS geom
        ),
        production_src AS (
            SELECT
                mlf.geom AS feature_geom,
                {production_property_select}
            FROM map_layer_features mlf
            WHERE
                mlf.layer_id = %s
                AND mlf.geom IS NOT NULL
                AND (mlf.minzoom IS NULL OR mlf.minzoom <= %s)
                AND (mlf.maxzoom IS NULL OR mlf.maxzoom >= %s)
                AND (mlf.expires_at IS NULL OR mlf.expires_at > now())
        ),
        fallback_src AS (
            SELECT fallback.*
            FROM (
                {spec.fallback_source_sql}
            ) fallback
            WHERE NOT (SELECT has_features FROM production_layer_has_features)
        ),
        src AS (
            SELECT * FROM production_src
            UNION ALL
            SELECT * FROM fallback_src
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
                AND NOT EXISTS (SELECT 1 FROM cached_tile)
        ),
        generated_tile AS (
            SELECT COALESCE(ST_AsMVT(mvtgeom, %s, 4096, 'geom'), '\\x'::bytea) AS tile
            FROM mvtgeom
        )
        SELECT
            CASE
                WHEN NOT EXISTS (SELECT 1 FROM requested_layer) THEN NULL
                WHEN EXISTS (SELECT 1 FROM cached_tile) THEN (SELECT tile_data FROM cached_tile)
                ELSE (SELECT tile FROM generated_tile)
            END AS tile
    """
    return sql, (
        spec.layer_id,
        spec.layer_id,
        z,
        x,
        y,
        spec.layer_id,
        z,
        z,
        z,
        x,
        y,
        spec.layer_id,
        z,
        z,
        spec.vector_layer_id,
    )


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
