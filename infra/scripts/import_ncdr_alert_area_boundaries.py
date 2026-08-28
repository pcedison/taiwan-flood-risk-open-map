#!/usr/bin/env python3
"""Import the reviewed NCDR Taiwan_Geocode_103 township boundary archive.

The importer is intentionally non-activating.  It verifies the pinned official
archive, canonicalizes all 368 geometries in PostGIS, and writes an immutable
manifest candidate.  A separate reviewed activation command must approve the
archive and manifest checksums before the worker may use the geometry.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any

import psycopg

EXPECTED_TOWN_COUNT = 368
EXPECTED_ARCHIVE_SHA256 = (
    "26a0e1d3496847905a5d4956cf29369a932febba546bf165d9923085aa3ed9bb"
)
SOURCE_NAME = "NCDR Taiwan_Geocode_103 township boundaries"
SOURCE_URL = (
    "https://alerts.ncdr.nat.gov.tw/web/StaticFile/Document/"
    "town_103.shp(utf8).zip"
)
GEOCODE_PROFILE = "Taiwan_Geocode_103"
MANIFEST_VERSION = "ncdr-alert-area-jsonb-v1"
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 64
TAIWAN_BOUNDS = (117.0, 20.0, 125.0, 27.0)


@dataclass(frozen=True)
class SourceBoundary:
    geocode_value: str
    county_name: str
    town_name: str
    english_name: str
    geometry_json: str


@dataclass(frozen=True)
class CanonicalBoundary:
    geocode_value: str
    county_name: str
    town_name: str
    english_name: str
    ewkb: bytes
    geom_sha256: str


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip_path", help="Pinned official NCDR township SHP ZIP.")
    parser.add_argument("--database-url", required=True)
    parser.add_argument(
        "--source-revision",
        required=True,
        help="Reviewed source revision, for example town_103cap-v2.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and compute the canonical manifest without writing a snapshot.",
    )
    args = parser.parse_args(argv)

    archive_path = Path(args.zip_path)
    archive_sha256 = _verified_archive_sha256(archive_path)
    source_boundaries = _read_source_boundaries(archive_path)
    with psycopg.connect(args.database_url) as connection:
        boundaries = _canonicalize_boundaries(connection, source_boundaries)
        manifest_sha256 = _manifest_sha256(connection, boundaries)
        print(f"archive_sha256  : {archive_sha256}")
        print(f"townships       : {len(boundaries)}")
        print(f"manifest_sha256 : {manifest_sha256}")
        if args.dry_run:
            print("dry run: nothing written")
            return 0
        snapshot_id = _write_snapshot(
            connection,
            boundaries=boundaries,
            archive_sha256=archive_sha256,
            manifest_sha256=manifest_sha256,
            source_revision=args.source_revision,
        )
        connection.commit()
    print(f"snapshot written: {snapshot_id} (is_active=false, is_complete=false)")
    print("activation requires separately approved archive and manifest checksums")
    return 0


def _verified_archive_sha256(path: Path) -> str:
    if not path.is_file():
        raise SystemExit("NCDR township archive does not exist")
    size = path.stat().st_size
    if size < 1 or size > MAX_ARCHIVE_BYTES:
        raise SystemExit("NCDR township archive size is outside the reviewed bound")
    digest = sha256(path.read_bytes()).hexdigest()
    if digest != EXPECTED_ARCHIVE_SHA256:
        raise SystemExit(
            "NCDR township archive checksum differs from the reviewed official archive"
        )
    return digest


def _read_source_boundaries(path: Path) -> tuple[SourceBoundary, ...]:
    try:
        import shapefile
    except ImportError as exc:  # pragma: no cover - operator dependency guard
        raise SystemExit("pyshp is required to import NCDR township boundaries") from exc

    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise SystemExit("NCDR township archive is not a valid ZIP") from exc
    with archive:
        members = archive.infolist()
        if not 1 <= len(members) <= MAX_ARCHIVE_MEMBERS:
            raise SystemExit("NCDR township archive member count is outside the reviewed bound")
        if sum(member.file_size for member in members) > MAX_UNCOMPRESSED_BYTES:
            raise SystemExit("NCDR township archive expands beyond the reviewed bound")
        names = tuple(
            member.filename
            for member in members
            if not member.is_dir() and _safe_member_name(member.filename)
        )
        shp_names = tuple(name for name in names if name.lower().endswith(".shp"))
        if len(shp_names) != 1:
            raise SystemExit("NCDR township archive must contain exactly one SHP")
        shp_name = shp_names[0]
        stem = shp_name[:-4]
        shx_name = _matching_member(names, stem, ".shx")
        dbf_name = _matching_member(names, stem, ".dbf")
        prj_name = _matching_member(names, stem, ".prj")
        cpg_name = _matching_member(names, stem, ".cpg")
        projection = archive.read(prj_name).decode("ascii", "strict")
        encoding = archive.read(cpg_name).decode("ascii", "strict").strip().upper()
        if encoding.replace("-", "") != "UTF8":
            raise SystemExit("NCDR township DBF encoding is not UTF-8")
        if "GCS_WGS_1984" not in projection or "UNIT[\"Degree\"" not in projection:
            raise SystemExit("NCDR township projection is not reviewed WGS84 longitude/latitude")
        reader = shapefile.Reader(
            shp=BytesIO(archive.read(shp_name)),
            shx=BytesIO(archive.read(shx_name)),
            dbf=BytesIO(archive.read(dbf_name)),
            encoding="utf-8",
        )
        try:
            boundaries = tuple(_source_boundary(record) for record in reader.iterShapeRecords())
        finally:
            reader.close()

    if len(boundaries) != EXPECTED_TOWN_COUNT:
        raise SystemExit(
            f"NCDR township archive has {len(boundaries)} rows; expected {EXPECTED_TOWN_COUNT}"
        )
    codes = tuple(boundary.geocode_value for boundary in boundaries)
    if len(set(codes)) != EXPECTED_TOWN_COUNT:
        raise SystemExit("NCDR township archive contains duplicate Taiwan_Geocode_103 values")
    return tuple(sorted(boundaries, key=lambda boundary: boundary.geocode_value))


def _safe_member_name(value: str) -> bool:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        raise SystemExit("NCDR township archive contains an unsafe member path")
    return True


def _matching_member(names: tuple[str, ...], stem: str, suffix: str) -> str:
    expected = (stem + suffix).lower()
    matches = tuple(name for name in names if name.lower() == expected)
    if len(matches) != 1:
        raise SystemExit(f"NCDR township archive is missing exactly one {suffix.upper()} companion")
    return matches[0]


def _source_boundary(shape_record: Any) -> SourceBoundary:
    record = shape_record.record.as_dict()
    geocode_value = _required_text(record.get("nTown103"), "nTown103", 7)
    if re.fullmatch(r"[0-9]{7}", geocode_value) is None:
        raise SystemExit("NCDR township nTown103 is not a canonical 7-digit code")
    county_name = _required_text(record.get("C_NAME103"), "C_NAME103", 64)
    town_name = _required_text(record.get("T_NAME103"), "T_NAME103", 64)
    english_name = _required_text(record.get("E_NAME103"), "E_NAME103", 128)
    geometry = shape_record.shape.__geo_interface__
    if not isinstance(geometry, dict) or geometry.get("type") not in {
        "Polygon",
        "MultiPolygon",
    }:
        raise SystemExit(f"NCDR township {geocode_value} is not polygon geometry")
    return SourceBoundary(
        geocode_value=geocode_value,
        county_name=county_name,
        town_name=town_name,
        english_name=english_name,
        geometry_json=json.dumps(geometry, ensure_ascii=False, separators=(",", ":")),
    )


def _required_text(value: object, field: str, maximum: int) -> str:
    text = str(value).strip() if value is not None else ""
    if not 1 <= len(text) <= maximum:
        raise SystemExit(f"NCDR township {field} is outside the reviewed text bound")
    return text


def _canonicalize_boundaries(
    connection: psycopg.Connection[Any],
    boundaries: tuple[SourceBoundary, ...],
) -> tuple[CanonicalBoundary, ...]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TEMP TABLE _ncdr_alert_area_import (
                geocode_value text,
                county_name text,
                town_name text,
                english_name text,
                geometry_json text
            ) ON COMMIT DROP
            """
        )
        with cursor.copy(
            """
            COPY _ncdr_alert_area_import (
                geocode_value, county_name, town_name, english_name, geometry_json
            ) FROM STDIN
            """
        ) as copy:
            for boundary in boundaries:
                copy.write_row(
                    (
                        boundary.geocode_value,
                        boundary.county_name,
                        boundary.town_name,
                        boundary.english_name,
                        boundary.geometry_json,
                    )
                )
        cursor.execute(
            """
            WITH parsed AS (
                SELECT
                    geocode_value,
                    county_name,
                    town_name,
                    english_name,
                    ST_Multi(
                        ST_CollectionExtract(
                            ST_MakeValid(
                                ST_SetSRID(ST_GeomFromGeoJSON(geometry_json), 4326)
                            ),
                            3
                        )
                    )::geometry(MultiPolygon, 4326) AS geom
                FROM _ncdr_alert_area_import
            )
            SELECT
                geocode_value,
                county_name,
                town_name,
                english_name,
                ST_AsEWKB(geom),
                encode(digest(ST_AsEWKB(geom), 'sha256'), 'hex')
            FROM parsed
            WHERE NOT ST_IsEmpty(geom)
                AND ST_IsValid(geom)
                AND ST_XMin(geom) >= %s
                AND ST_YMin(geom) >= %s
                AND ST_XMax(geom) <= %s
                AND ST_YMax(geom) <= %s
            ORDER BY geocode_value
            """,
            TAIWAN_BOUNDS,
        )
        rows = cursor.fetchall()
    if len(rows) != EXPECTED_TOWN_COUNT:
        raise SystemExit("PostGIS rejected one or more NCDR township geometries")
    return tuple(
        CanonicalBoundary(
            geocode_value=str(row[0]),
            county_name=str(row[1]),
            town_name=str(row[2]),
            english_name=str(row[3]),
            ewkb=bytes(row[4]),
            geom_sha256=str(row[5]),
        )
        for row in rows
    )


def _manifest_sha256(
    connection: psycopg.Connection[Any],
    boundaries: tuple[CanonicalBoundary, ...],
) -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT jsonb_agg(
                jsonb_build_array(
                    entry.geocode_value,
                    entry.county_name,
                    entry.town_name,
                    entry.english_name,
                    entry.geom_sha256
                )
                ORDER BY entry.geocode_value
            )::text
            FROM unnest(%s::text[], %s::text[], %s::text[], %s::text[], %s::text[])
                AS entry(
                    geocode_value,
                    county_name,
                    town_name,
                    english_name,
                    geom_sha256
                )
            """,
            (
                [boundary.geocode_value for boundary in boundaries],
                [boundary.county_name for boundary in boundaries],
                [boundary.town_name for boundary in boundaries],
                [boundary.english_name for boundary in boundaries],
                [boundary.geom_sha256 for boundary in boundaries],
            ),
        )
        row = cursor.fetchone()
    if row is None or row[0] is None:
        raise SystemExit("NCDR alert boundary manifest aggregation returned no rows")
    return sha256(str(row[0]).encode("utf-8")).hexdigest()


def _write_snapshot(
    connection: psycopg.Connection[Any],
    *,
    boundaries: tuple[CanonicalBoundary, ...],
    archive_sha256: str,
    manifest_sha256: str,
    source_revision: str,
) -> str:
    revision = source_revision.strip()
    if not 1 <= len(revision) <= 256:
        raise SystemExit("NCDR township source revision is outside the reviewed bound")
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO ncdr_alert_area_boundary_snapshots (
                adapter_key,
                geocode_profile,
                source_name,
                source_url,
                source_revision,
                archive_sha256,
                manifest_version,
                expected_count,
                imported_count,
                manifest_sha256,
                is_complete,
                is_active
            )
            VALUES (
                'official.ncdr.cap', %s, %s, %s, %s, %s, %s,
                %s, %s, %s, false, false
            )
            RETURNING id::text
            """,
            (
                GEOCODE_PROFILE,
                SOURCE_NAME,
                SOURCE_URL,
                revision,
                archive_sha256,
                MANIFEST_VERSION,
                EXPECTED_TOWN_COUNT,
                len(boundaries),
                manifest_sha256,
            ),
        )
        row = cursor.fetchone()
        if row is None:
            raise SystemExit("NCDR alert boundary snapshot insert returned no id")
        snapshot_id = str(row[0])
        # PostgreSQL text COPY serializes ``bytes`` as ``\\x...`` while a
        # PostGIS geometry column expects geometry text, not bytea text.  Bind
        # EWKB explicitly so psycopg keeps it binary and PostGIS performs the
        # only supported conversion at the database boundary.
        cursor.executemany(
            """
            INSERT INTO ncdr_alert_area_boundaries (
                snapshot_id,
                geocode_value,
                county_name,
                town_name,
                english_name,
                geom,
                geom_sha256
            )
            VALUES (%s, %s, %s, %s, %s, ST_GeomFromEWKB(%s), %s)
            """,
            (
                (
                    snapshot_id,
                    boundary.geocode_value,
                    boundary.county_name,
                    boundary.town_name,
                    boundary.english_name,
                    boundary.ewkb,
                    boundary.geom_sha256,
                )
                for boundary in boundaries
            ),
        )
    return snapshot_id


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
