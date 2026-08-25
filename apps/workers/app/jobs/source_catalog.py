from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final, Protocol

ConnectionFactory = Callable[[], Any]

OFFICIAL_INCIDENT_CATALOG_GATED_KEYS: Final[frozenset[str]] = frozenset(
    {
        "official.cwa.heavy_rain_warning",
        "official.ncdr.cap",
        "official.npa.police_radio_traffic",
        "official.wra.flood_warning",
    }
)


class SourceCatalogReader(Protocol):
    def enabled_keys(self, adapter_keys: tuple[str, ...]) -> frozenset[str]: ...


class SourceCatalogUnavailable(RuntimeError):
    """Raised when a required persisted source catalog cannot be read."""


class PostgresSourceCatalogReader:
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

    def enabled_keys(self, adapter_keys: tuple[str, ...]) -> frozenset[str]:
        normalized_keys = tuple(sorted(set(adapter_keys)))
        if not normalized_keys:
            return frozenset()
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT adapter_key
                FROM data_sources
                WHERE adapter_key = ANY(%s) AND is_enabled IS TRUE
                ORDER BY adapter_key ASC
                """,
                (list(normalized_keys),),
            )
            return frozenset(str(row[0]) for row in cursor.fetchall())

    def _connect(self) -> Any:
        if self._connection_factory is not None:
            return self._connection_factory()
        import psycopg

        assert self._database_url is not None
        return psycopg.connect(self._database_url)


def filter_catalog_enabled_adapter_keys(
    adapter_keys: tuple[str, ...],
    *,
    source_catalog_reader: SourceCatalogReader | None,
) -> tuple[str, ...]:
    gated_keys = tuple(key for key in adapter_keys if key in OFFICIAL_INCIDENT_CATALOG_GATED_KEYS)
    if not gated_keys:
        return adapter_keys
    if source_catalog_reader is None:
        raise SourceCatalogUnavailable("source catalog reader is required")
    try:
        enabled_gated_keys = source_catalog_reader.enabled_keys(gated_keys)
    except Exception as exc:
        raise SourceCatalogUnavailable("source catalog is unavailable") from exc
    return tuple(
        key
        for key in adapter_keys
        if key not in OFFICIAL_INCIDENT_CATALOG_GATED_KEYS or key in enabled_gated_keys
    )


def resolve_source_catalog_reader(
    *,
    database_url: str | None,
    source_catalog_reader: SourceCatalogReader | None,
) -> SourceCatalogReader | None:
    if source_catalog_reader is not None:
        return source_catalog_reader
    if database_url is None:
        return None
    return PostgresSourceCatalogReader(database_url=database_url)
