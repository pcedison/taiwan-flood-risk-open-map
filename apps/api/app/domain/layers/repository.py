from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any, cast

import psycopg
from psycopg.rows import dict_row


ConnectionFactory = Callable[[], Any]


class LayerRepositoryUnavailable(RuntimeError):
    """Raised when map layer storage cannot be queried."""


@dataclass(frozen=True)
class LayerRecord:
    id: str
    name: str
    description: str | None
    category: str
    status: str
    minzoom: int | None
    maxzoom: int | None
    attribution: str | None
    tilejson_url: str
    updated_at: datetime | None
    metadata: dict[str, Any]


def fetch_map_layers(
    *,
    database_url: str,
    connection_factory: ConnectionFactory | None = None,
) -> tuple[LayerRecord, ...]:
    sql = """
        SELECT
            layer_id,
            name,
            description,
            category,
            status,
            minzoom,
            maxzoom,
            attribution,
            tilejson_url,
            updated_at,
            metadata
        FROM map_layers
        ORDER BY
            CASE status
                WHEN 'available' THEN 0
                WHEN 'degraded' THEN 1
                ELSE 2
            END,
            layer_id ASC
    """
    return _fetch_layers(sql, (), database_url=database_url, connection_factory=connection_factory)


def fetch_map_layer(
    *,
    database_url: str,
    layer_id: str,
    connection_factory: ConnectionFactory | None = None,
) -> LayerRecord | None:
    sql = """
        SELECT
            layer_id,
            name,
            description,
            category,
            status,
            minzoom,
            maxzoom,
            attribution,
            tilejson_url,
            updated_at,
            metadata
        FROM map_layers
        WHERE layer_id = %s
        LIMIT 1
    """
    layers = _fetch_layers(
        sql,
        (layer_id,),
        database_url=database_url,
        connection_factory=connection_factory,
    )
    return layers[0] if layers else None


def _fetch_layers(
    sql: str,
    params: tuple[object, ...],
    *,
    database_url: str,
    connection_factory: ConnectionFactory | None,
) -> tuple[LayerRecord, ...]:
    try:
        with _connect(database_url, connection_factory) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                return tuple(_layer_from_row(row) for row in cursor.fetchall())
    except (OSError, psycopg.Error) as exc:
        raise LayerRepositoryUnavailable(str(exc)) from exc


def _connect(database_url: str, connection_factory: ConnectionFactory | None) -> Any:
    if connection_factory is not None:
        return connection_factory()
    return psycopg.connect(database_url, connect_timeout=2, row_factory=dict_row)


def _layer_from_row(row: dict[str, Any]) -> LayerRecord:
    return LayerRecord(
        id=str(row["layer_id"]),
        name=str(row["name"]),
        description=str(row["description"]) if row.get("description") is not None else None,
        category=str(row["category"]),
        status=str(row["status"]),
        minzoom=_optional_int(row.get("minzoom")),
        maxzoom=_optional_int(row.get("maxzoom")),
        attribution=str(row["attribution"]) if row.get("attribution") is not None else None,
        tilejson_url=str(row["tilejson_url"]),
        updated_at=cast(datetime | None, row.get("updated_at")),
        metadata=_metadata(row.get("metadata")),
    )


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(cast(Any, value))


def _metadata(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        payload = json.loads(value)
        return payload if isinstance(payload, dict) else {}
    return {}
