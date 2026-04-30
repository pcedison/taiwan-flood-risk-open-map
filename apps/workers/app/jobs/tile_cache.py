from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from typing import Any, cast


ConnectionFactory = Callable[[], Any]


class TileCacheUnavailable(RuntimeError):
    """Raised when tile feature/cache storage cannot be reached."""


class TileLayerUnsupported(ValueError):
    """Raised when a worker-side tile refresh is not implemented for a layer."""


@dataclass(frozen=True)
class TileLayerFeatureSpec:
    layer_id: str
    event_type: str


@dataclass(frozen=True)
class TileFeatureRefreshResult:
    layer_id: str
    refreshed: int


@dataclass(frozen=True)
class TileCachePruneResult:
    layer_id: str | None
    expired_before: datetime
    tile_cache_deleted: int
    features_deleted: int


@dataclass(frozen=True)
class TileLayerInvalidationResult:
    layer_id: str
    invalidated_at: datetime
    features_invalidated: int
    tile_cache_deleted: int


@dataclass(frozen=True)
class TileCacheUpsertResult:
    cache_entry_id: str | None
    layer_id: str
    z: int
    x: int
    y: int
    content_hash: str


_FEATURE_LAYER_SPECS: dict[str, TileLayerFeatureSpec] = {
    "flood-potential": TileLayerFeatureSpec(
        layer_id="flood-potential",
        event_type="flood_potential",
    ),
}


class PostgresTileCacheWriter:
    def __init__(
        self,
        *,
        database_url: str | None = None,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        if database_url is None and connection_factory is None:
            raise ValueError("database_url or connection_factory is required")
        self._database_url = database_url
        self._connection_factory = connection_factory

    def refresh_layer_features(
        self,
        *,
        layer_id: str = "flood-potential",
        limit: int | None = None,
        expires_at: datetime | None = None,
        refresh_metadata: dict[str, Any] | None = None,
    ) -> TileFeatureRefreshResult:
        spec = _FEATURE_LAYER_SPECS.get(layer_id)
        if spec is None:
            raise TileLayerUnsupported(layer_id)
        if limit is not None and limit < 1:
            raise ValueError("limit must be greater than 0")

        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        _feature_refresh_sql(limit=limit),
                        _feature_refresh_params(
                            spec=spec,
                            limit=limit,
                            expires_at=expires_at,
                            refresh_metadata=refresh_metadata,
                        ),
                    )
                    row = cursor.fetchone()
                    refreshed = _count_from_row(row)
                connection.commit()
        except Exception as exc:
            raise TileCacheUnavailable(str(exc)) from exc

        return TileFeatureRefreshResult(layer_id=layer_id, refreshed=refreshed)

    def prune_expired(
        self,
        *,
        expired_before: datetime,
        layer_id: str | None = None,
        limit: int = 1000,
    ) -> TileCachePruneResult:
        if limit < 1:
            raise ValueError("limit must be greater than 0")

        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        _prune_expired_sql(table_name="tile_cache_entries", layer_id=layer_id),
                        _prune_expired_params(
                            expired_before=expired_before,
                            layer_id=layer_id,
                            limit=limit,
                        ),
                    )
                    tile_cache_deleted = _count_from_row(cursor.fetchone())
                    cursor.execute(
                        _prune_expired_sql(table_name="map_layer_features", layer_id=layer_id),
                        _prune_expired_params(
                            expired_before=expired_before,
                            layer_id=layer_id,
                            limit=limit,
                        ),
                    )
                    features_deleted = _count_from_row(cursor.fetchone())
                connection.commit()
        except Exception as exc:
            raise TileCacheUnavailable(str(exc)) from exc

        return TileCachePruneResult(
            layer_id=layer_id,
            expired_before=expired_before,
            tile_cache_deleted=tile_cache_deleted,
            features_deleted=features_deleted,
        )

    def invalidate_layer(
        self,
        *,
        layer_id: str = "flood-potential",
        invalidated_at: datetime,
        reason: str = "manual",
    ) -> TileLayerInvalidationResult:
        if layer_id not in _FEATURE_LAYER_SPECS:
            raise TileLayerUnsupported(layer_id)
        if not reason:
            raise ValueError("reason is required")

        metadata = _json(
            {
                "invalidated_at": invalidated_at,
                "invalidated_by": "workers.tile_cache",
                "invalidation_reason": reason,
            }
        )

        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        _invalidate_layer_features_sql(),
                        (invalidated_at, invalidated_at, metadata, layer_id),
                    )
                    features_invalidated = _count_from_row(cursor.fetchone())
                    cursor.execute(_delete_layer_tile_cache_sql(), (layer_id,))
                    tile_cache_deleted = _count_from_row(cursor.fetchone())
                connection.commit()
        except Exception as exc:
            raise TileCacheUnavailable(str(exc)) from exc

        return TileLayerInvalidationResult(
            layer_id=layer_id,
            invalidated_at=invalidated_at,
            features_invalidated=features_invalidated,
            tile_cache_deleted=tile_cache_deleted,
        )

    def upsert_tile_cache_entry(
        self,
        *,
        layer_id: str,
        z: int,
        x: int,
        y: int,
        tile_data: bytes,
        content_hash: str | None = None,
        expires_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TileCacheUpsertResult:
        _validate_tile_coordinate(z=z, x=x, y=y)
        resolved_hash = content_hash or sha256(tile_data).hexdigest()

        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO tile_cache_entries (
                            layer_id,
                            z,
                            x,
                            y,
                            tile_data,
                            content_hash,
                            expires_at,
                            metadata
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                        ON CONFLICT (layer_id, z, x, y) DO UPDATE SET
                            tile_data = EXCLUDED.tile_data,
                            content_hash = EXCLUDED.content_hash,
                            generated_at = now(),
                            expires_at = EXCLUDED.expires_at,
                            metadata = EXCLUDED.metadata
                        RETURNING id
                        """,
                        (
                            layer_id,
                            z,
                            x,
                            y,
                            tile_data,
                            resolved_hash,
                            expires_at,
                            _json(metadata or {}),
                        ),
                    )
                    row = cursor.fetchone()
                    cache_entry_id = str(row[0]) if row is not None else None
                connection.commit()
        except Exception as exc:
            raise TileCacheUnavailable(str(exc)) from exc

        return TileCacheUpsertResult(
            cache_entry_id=cache_entry_id,
            layer_id=layer_id,
            z=z,
            x=x,
            y=y,
            content_hash=resolved_hash,
        )

    def _connect(self) -> Any:
        if self._connection_factory is not None:
            return self._connection_factory()

        import psycopg

        assert self._database_url is not None
        return psycopg.connect(self._database_url)


def _feature_refresh_sql(*, limit: int | None) -> str:
    limit_clause = "LIMIT %s" if limit is not None else ""
    return f"""
        WITH requested_layer AS (
            SELECT layer_id, minzoom, maxzoom
            FROM map_layers
            WHERE layer_id = %s
            LIMIT 1
        ),
        source_features AS (
            SELECT DISTINCT ON (e.source_id)
                e.source_id AS feature_key,
                e.id::text AS source_ref,
                e.geom,
                e.properties
                    || jsonb_strip_nulls(
                        jsonb_build_object(
                            'source_id', e.source_id,
                            'category', e.event_type,
                            'confidence', e.confidence,
                            'title', e.title,
                            'summary', e.summary,
                            'url', e.url,
                            'raw_ref', e.raw_ref,
                            'occurred_at', e.occurred_at,
                            'observed_at', e.observed_at
                        )
                    ) AS properties,
                jsonb_strip_nulls(
                    jsonb_build_object(
                        'generated_by', 'workers.tile_cache',
                        'evidence_id', e.id::text,
                        'data_source_id', e.data_source_id::text
                    )
                ) AS metadata
            FROM evidence e
            WHERE
                e.ingestion_status = 'accepted'
                AND e.event_type = %s
                AND e.geom IS NOT NULL
                AND e.source_id IS NOT NULL
            ORDER BY
                e.source_id ASC,
                COALESCE(e.observed_at, e.occurred_at, e.updated_at, e.created_at) DESC,
                e.updated_at DESC,
                e.id DESC
            {limit_clause}
        ),
        upserted AS (
            INSERT INTO map_layer_features (
                layer_id,
                feature_key,
                source_ref,
                geom,
                minzoom,
                maxzoom,
                properties,
                expires_at,
                metadata
            )
            SELECT
                requested_layer.layer_id,
                source_features.feature_key,
                source_features.source_ref,
                source_features.geom,
                requested_layer.minzoom,
                requested_layer.maxzoom,
                source_features.properties,
                %s,
                source_features.metadata || %s::jsonb
            FROM source_features
            CROSS JOIN requested_layer
            ON CONFLICT (layer_id, feature_key) DO UPDATE SET
                source_ref = EXCLUDED.source_ref,
                geom = EXCLUDED.geom,
                minzoom = EXCLUDED.minzoom,
                maxzoom = EXCLUDED.maxzoom,
                properties = EXCLUDED.properties,
                generated_at = now(),
                expires_at = EXCLUDED.expires_at,
                metadata = EXCLUDED.metadata
            WHERE
                map_layer_features.source_ref IS DISTINCT FROM EXCLUDED.source_ref
                OR NOT ST_Equals(map_layer_features.geom, EXCLUDED.geom)
                OR map_layer_features.minzoom IS DISTINCT FROM EXCLUDED.minzoom
                OR map_layer_features.maxzoom IS DISTINCT FROM EXCLUDED.maxzoom
                OR map_layer_features.properties IS DISTINCT FROM EXCLUDED.properties
                OR map_layer_features.expires_at IS DISTINCT FROM EXCLUDED.expires_at
                OR map_layer_features.metadata IS DISTINCT FROM EXCLUDED.metadata
            RETURNING id
        )
        SELECT count(*) FROM upserted
    """


def _feature_refresh_params(
    *,
    spec: TileLayerFeatureSpec,
    limit: int | None,
    expires_at: datetime | None,
    refresh_metadata: dict[str, Any] | None,
) -> tuple[object, ...]:
    params: list[object] = [spec.layer_id, spec.event_type]
    if limit is not None:
        params.append(limit)
    params.append(expires_at)
    params.append(_json(refresh_metadata or {"refreshed_by": "workers.tile_cache"}))
    return tuple(params)


def _prune_expired_sql(*, table_name: str, layer_id: str | None) -> str:
    if table_name not in {"tile_cache_entries", "map_layer_features"}:
        raise ValueError("unsupported tile cache table")
    layer_clause = "AND layer_id = %s" if layer_id is not None else ""
    return f"""
        WITH expired AS (
            SELECT id
            FROM {table_name}
            WHERE
                expires_at IS NOT NULL
                AND expires_at <= %s
                {layer_clause}
            ORDER BY expires_at ASC, id ASC
            LIMIT %s
        ),
        deleted AS (
            DELETE FROM {table_name}
            WHERE id IN (SELECT id FROM expired)
            RETURNING id
        )
        SELECT count(*) FROM deleted
    """


def _prune_expired_params(
    *,
    expired_before: datetime,
    layer_id: str | None,
    limit: int,
) -> tuple[object, ...]:
    params: list[object] = [expired_before]
    if layer_id is not None:
        params.append(layer_id)
    params.append(limit)
    return tuple(params)


def _invalidate_layer_features_sql() -> str:
    return """
        WITH invalidated AS (
            UPDATE map_layer_features
            SET
                expires_at = CASE
                    WHEN %s > generated_at THEN %s
                    ELSE generated_at + interval '1 microsecond'
                END,
                metadata = metadata || %s::jsonb
            WHERE
                layer_id = %s
                AND (expires_at IS NULL OR expires_at > now())
            RETURNING id
        )
        SELECT count(*) FROM invalidated
    """


def _delete_layer_tile_cache_sql() -> str:
    return """
        WITH deleted AS (
            DELETE FROM tile_cache_entries
            WHERE layer_id = %s
            RETURNING id
        )
        SELECT count(*) FROM deleted
    """


def _count_from_row(row: object) -> int:
    if row is None:
        return 0
    return int(cast(tuple[Any, ...], row)[0])


def _validate_tile_coordinate(*, z: int, x: int, y: int) -> None:
    if z < 0 or z > 24:
        raise ValueError("z must be between 0 and 24")
    max_index = (1 << z) - 1
    if x < 0:
        raise ValueError("x must be greater than or equal to 0")
    if x > max_index:
        raise ValueError("x must be within the zoom tile bounds")
    if y < 0:
        raise ValueError("y must be greater than or equal to 0")
    if y > max_index:
        raise ValueError("y must be within the zoom tile bounds")


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
