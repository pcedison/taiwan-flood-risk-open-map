from __future__ import annotations

import gzip
import json
import threading
from pathlib import Path
from typing import Any


SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS geocoder_open_data_entries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_key text NOT NULL,
    source_record_id text,
    name text NOT NULL,
    aliases text[] NOT NULL DEFAULT '{}'::text[],
    normalized_aliases text[] NOT NULL DEFAULT '{}'::text[],
    admin_code text,
    precision text NOT NULL CHECK (
        precision IN ('exact_address', 'road_or_lane', 'poi', 'admin_area', 'map_click', 'unknown')
    ),
    place_type text NOT NULL CHECK (
        place_type IN ('address', 'parcel', 'landmark', 'admin_area', 'poi')
    ),
    geom geometry(Geometry, 4326) NOT NULL,
    centroid geometry(Point, 4326) NOT NULL,
    confidence numeric(6,3) CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    source_url text,
    license text,
    attribution text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    imported_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (cardinality(normalized_aliases) > 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_geocoder_open_data_entries_source_record
    ON geocoder_open_data_entries (source_key, source_record_id)
    WHERE source_record_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_geocoder_open_data_entries_source_key
    ON geocoder_open_data_entries (source_key);

CREATE INDEX IF NOT EXISTS idx_geocoder_open_data_entries_admin_code
    ON geocoder_open_data_entries (admin_code)
    WHERE admin_code IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_geocoder_open_data_entries_precision
    ON geocoder_open_data_entries (precision, place_type);

CREATE INDEX IF NOT EXISTS idx_geocoder_open_data_entries_aliases_gin
    ON geocoder_open_data_entries USING gin (aliases);

CREATE INDEX IF NOT EXISTS idx_geocoder_open_data_entries_normalized_aliases_gin
    ON geocoder_open_data_entries USING gin (normalized_aliases);

CREATE INDEX IF NOT EXISTS idx_geocoder_open_data_entries_geom_gist
    ON geocoder_open_data_entries USING gist (geom);

CREATE INDEX IF NOT EXISTS idx_geocoder_open_data_entries_centroid_gist
    ON geocoder_open_data_entries USING gist (centroid);

CREATE TABLE IF NOT EXISTS geocoder_open_data_import_runs (
    source_key text PRIMARY KEY,
    row_count integer NOT NULL,
    imported_at timestamptz NOT NULL DEFAULT now(),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);
"""

UPSERT_SQL = """
INSERT INTO geocoder_open_data_entries (
    source_key, source_record_id, name, aliases, normalized_aliases,
    admin_code, precision, place_type, geom, centroid, confidence,
    source_url, license, attribution, metadata
)
VALUES (
    %(source_key)s, %(source_record_id)s, %(name)s, %(aliases)s, %(normalized_aliases)s,
    %(admin_code)s, %(precision)s, %(place_type)s,
    ST_SetSRID(ST_MakePoint(%(lng)s, %(lat)s), 4326),
    ST_SetSRID(ST_MakePoint(%(lng)s, %(lat)s), 4326),
    %(confidence)s, %(source_url)s, %(license)s, %(attribution)s, %(metadata)s
)
ON CONFLICT (source_key, source_record_id) WHERE source_record_id IS NOT NULL
DO UPDATE SET
    name = EXCLUDED.name,
    aliases = EXCLUDED.aliases,
    normalized_aliases = EXCLUDED.normalized_aliases,
    admin_code = EXCLUDED.admin_code,
    precision = EXCLUDED.precision,
    place_type = EXCLUDED.place_type,
    geom = EXCLUDED.geom,
    centroid = EXCLUDED.centroid,
    confidence = EXCLUDED.confidence,
    source_url = EXCLUDED.source_url,
    license = EXCLUDED.license,
    attribution = EXCLUDED.attribution,
    metadata = EXCLUDED.metadata,
    updated_at = now()
"""

IMPORT_RUN_SQL = """
INSERT INTO geocoder_open_data_import_runs (source_key, row_count, metadata)
VALUES (%(source_key)s, %(row_count)s, %(metadata)s)
ON CONFLICT (source_key)
DO UPDATE SET
    row_count = EXCLUDED.row_count,
    metadata = EXCLUDED.metadata,
    imported_at = now()
"""


def start_postgis_geocoder_bootstrap(
    *,
    database_url: str,
    paths: tuple[str, ...],
    enabled: bool,
) -> None:
    if not enabled or not database_url or not paths:
        return
    thread = threading.Thread(
        target=bootstrap_postgis_geocoder,
        kwargs={"database_url": database_url, "paths": paths},
        name="postgis-geocoder-bootstrap",
        daemon=True,
    )
    thread.start()


def bootstrap_postgis_geocoder(*, database_url: str, paths: tuple[str, ...]) -> None:
    import psycopg
    from psycopg.types.json import Jsonb

    with psycopg.connect(database_url, connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(hashtext(%s))", ("flood-risk-geocoder-bootstrap",))
            locked = cursor.fetchone()
            if locked is None or locked[0] is not True:
                return
            try:
                cursor.execute(SCHEMA_SQL)
                connection.commit()
                for path in paths:
                    rows = list(iter_import_rows(Path(path), jsonb=Jsonb))
                    if not rows:
                        continue
                    source_key = str(rows[0]["source_key"])
                    cursor.execute(
                        "SELECT count(*) FROM geocoder_open_data_entries WHERE source_key = %s",
                        (source_key,),
                    )
                    existing_count = int(cursor.fetchone()[0])
                    if existing_count < len(rows):
                        for batch in batched(rows, size=500):
                            cursor.executemany(UPSERT_SQL, batch)
                            connection.commit()
                    cursor.execute(
                        IMPORT_RUN_SQL,
                        {
                            "source_key": source_key,
                            "row_count": len(rows),
                            "metadata": Jsonb({"path": Path(path).name, "mode": "bundled-runtime-bootstrap"}),
                        },
                    )
                    connection.commit()
            finally:
                cursor.execute("SELECT pg_advisory_unlock(hashtext(%s))", ("flood-risk-geocoder-bootstrap",))
                connection.commit()


def iter_import_rows(path: Path, *, jsonb: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    opener = gzip.open if path.name.casefold().endswith(".gz") else Path.open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                continue
            row = import_row_from_payload(payload, jsonb=jsonb)
            if row is not None:
                rows.append(row)
    return rows


def import_row_from_payload(payload: dict[str, Any], *, jsonb: Any) -> dict[str, Any] | None:
    source_key = str(payload.get("source_key") or "").strip()
    name = str(payload.get("name") or "").strip()
    lat = payload.get("lat")
    lng = payload.get("lng")
    normalized_aliases = text_list(payload.get("normalized_aliases"))
    if not source_key or not name or lat is None or lng is None or not normalized_aliases:
        return None
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    limitations = text_list(payload.get("limitations"))
    return {
        "source_key": source_key,
        "source_record_id": text_or_none(payload.get("source_record_id")),
        "name": name,
        "aliases": text_list(payload.get("aliases")) or [name],
        "normalized_aliases": normalized_aliases,
        "admin_code": text_or_none(payload.get("admin_code")),
        "precision": text_or_none(payload.get("precision")) or "unknown",
        "place_type": text_or_none(payload.get("place_type")) or "poi",
        "lat": float(lat),
        "lng": float(lng),
        "confidence": payload.get("confidence"),
        "source_url": text_or_none(payload.get("source_url")),
        "license": text_or_none(payload.get("license")),
        "attribution": text_or_none(payload.get("attribution")),
        "metadata": jsonb({**metadata, "limitations": limitations}),
    }


def text_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def text_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    return [part.strip() for part in str(value).replace(";", "|").split("|") if part.strip()]


def batched(rows: list[dict[str, Any]], *, size: int) -> list[list[dict[str, Any]]]:
    return [rows[index : index + size] for index in range(0, len(rows), size)]
