#!/usr/bin/env python3
"""Review and atomically activate one imported NCDR township snapshot."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import UTC, datetime
from uuid import UUID

import psycopg
from import_ncdr_alert_area_boundaries import (
    EXPECTED_ARCHIVE_SHA256,
    EXPECTED_TOWN_COUNT,
    GEOCODE_PROFILE,
    MANIFEST_VERSION,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--approved-manifest-sha256", required=True)
    parser.add_argument(
        "--approved-archive-sha256",
        default=EXPECTED_ARCHIVE_SHA256,
    )
    parser.add_argument("--review-ref", required=True)
    args = parser.parse_args(argv)

    snapshot_id = _uuid(args.snapshot_id)
    manifest_sha256 = _sha256(args.approved_manifest_sha256, "manifest")
    archive_sha256 = _sha256(args.approved_archive_sha256, "archive")
    if archive_sha256 != EXPECTED_ARCHIVE_SHA256:
        raise SystemExit("approved archive checksum is not the pinned official archive")
    review_ref = args.review_ref.strip()
    if not 1 <= len(review_ref) <= 1024:
        raise SystemExit("review reference must contain 1..1024 characters")

    with psycopg.connect(args.database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    adapter_key,
                    geocode_profile,
                    archive_sha256,
                    manifest_version,
                    expected_count,
                    imported_count,
                    manifest_sha256,
                    is_complete,
                    is_active
                FROM ncdr_alert_area_boundary_snapshots
                WHERE id = %s
                FOR UPDATE
                """,
                (snapshot_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise SystemExit("NCDR alert boundary snapshot was not found")
            if row[0] != "official.ncdr.cap" or row[1] != GEOCODE_PROFILE:
                raise SystemExit("snapshot does not use the reviewed NCDR geocode profile")
            if row[2] != archive_sha256 or row[3] != MANIFEST_VERSION:
                raise SystemExit("snapshot archive or manifest contract is not approved")
            if int(row[4]) != EXPECTED_TOWN_COUNT or int(row[5]) != EXPECTED_TOWN_COUNT:
                raise SystemExit("snapshot does not contain exactly 368 townships")
            if row[6] != manifest_sha256:
                raise SystemExit("approved manifest checksum does not match the snapshot")
            if bool(row[7]) or bool(row[8]):
                raise SystemExit("snapshot is already reviewed or active")

            cursor.execute(
                """
                SELECT
                    count(*),
                    count(DISTINCT geocode_value),
                    bool_and(
                        geocode_value ~ '^[0-9]{7}$'
                        AND NOT ST_IsEmpty(geom)
                        AND ST_IsValid(geom)
                        AND GeometryType(geom) IN ('POLYGON', 'MULTIPOLYGON')
                        AND geom_sha256 = encode(
                            digest(ST_AsEWKB(geom), 'sha256'),
                            'hex'
                        )
                    ),
                    encode(
                        digest(
                            convert_to(
                                jsonb_agg(
                                    jsonb_build_array(
                                        geocode_value,
                                        county_name,
                                        town_name,
                                        english_name,
                                        geom_sha256
                                    )
                                    ORDER BY geocode_value
                                )::text,
                                'UTF8'
                            ),
                            'sha256'
                        ),
                        'hex'
                    )
                FROM ncdr_alert_area_boundaries
                WHERE snapshot_id = %s
                """,
                (snapshot_id,),
            )
            proof = cursor.fetchone()
            if (
                proof is None
                or int(proof[0]) != EXPECTED_TOWN_COUNT
                or int(proof[1]) != EXPECTED_TOWN_COUNT
                or proof[2] is not True
                or proof[3] != manifest_sha256
            ):
                raise SystemExit("snapshot boundary integrity or manifest proof failed")

            reviewed_at = datetime.now(UTC)
            cursor.execute(
                """
                UPDATE ncdr_alert_area_boundary_snapshots
                SET
                    approved_archive_sha256 = %s,
                    approved_manifest_sha256 = %s,
                    is_complete = true,
                    reviewed_at = %s,
                    review_ref = %s
                WHERE id = %s
                """,
                (
                    archive_sha256,
                    manifest_sha256,
                    reviewed_at,
                    review_ref,
                    snapshot_id,
                ),
            )
            cursor.execute(
                """
                UPDATE ncdr_alert_area_boundary_snapshots
                SET is_active = false
                WHERE adapter_key = 'official.ncdr.cap'
                    AND geocode_profile = %s
                    AND id <> %s
                    AND is_active
                """,
                (GEOCODE_PROFILE, snapshot_id),
            )
            cursor.execute(
                """
                UPDATE ncdr_alert_area_boundary_snapshots
                SET is_active = true
                WHERE id = %s
                """,
                (snapshot_id,),
            )
            cursor.execute(
                """
                SELECT count(*)
                FROM ncdr_alert_area_boundary_snapshots
                WHERE adapter_key = 'official.ncdr.cap'
                    AND geocode_profile = %s
                    AND is_active
                """,
                (GEOCODE_PROFILE,),
            )
            active = cursor.fetchone()
            if active is None or int(active[0]) != 1:
                raise SystemExit("NCDR alert boundary activation was not unique")
        connection.commit()
    print(f"activated NCDR alert boundary snapshot: {snapshot_id}")
    print(f"reviewed_at: {reviewed_at.isoformat()}")
    return 0


def _uuid(value: str) -> str:
    try:
        return str(UUID(value.strip()))
    except (AttributeError, ValueError) as exc:
        raise SystemExit("snapshot id must be a UUID") from exc


def _sha256(value: str, label: str) -> str:
    text = value.strip().lower()
    if re.fullmatch(r"[0-9a-f]{64}", text) is None:
        raise SystemExit(f"approved {label} checksum must be lowercase SHA-256")
    return text


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
