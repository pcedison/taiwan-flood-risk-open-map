from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any

import yaml


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
API_APP_PATH = REPO_ROOT / "apps" / "api"
DEFAULT_MANIFEST_PATH = REPO_ROOT / "docs" / "data-sources" / "geocoding" / "geocoding-data-manifest.yaml"

if str(API_APP_PATH) not in sys.path:
    sys.path.insert(0, str(API_APP_PATH))

from app.domain.geocoding.normalization import normalized_aliases, taiwan_address_aliases  # noqa: E402


GEOCODE_PRECISION_VALUES = {
    "exact_address",
    "road_or_lane",
    "poi",
    "admin_area",
    "map_click",
    "unknown",
}
PLACE_TYPE_VALUES = {"address", "parcel", "landmark", "admin_area", "poi"}
TAIWAN_LAT_RANGE = (21.5, 25.5)
TAIWAN_LNG_RANGE = (119.0, 122.5)


@dataclass(frozen=True)
class ImportSource:
    key: str
    license: str
    attribution: str
    source_url: str
    target_precision: str
    target_place_type: str


@dataclass(frozen=True)
class GeocoderImportRow:
    source_key: str
    source_record_id: str | None
    name: str
    aliases: tuple[str, ...]
    normalized_aliases: tuple[str, ...]
    lat: float
    lng: float
    admin_code: str | None
    precision: str
    place_type: str
    source_url: str
    license: str
    attribution: str
    confidence: float | None
    metadata: dict[str, Any]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Normalize reviewed open-data CSV/JSONL rows for the PostGIS geocoder table.",
    )
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument("--source-key", help="Dataset key from geocoding-data-manifest.yaml.")
    parser.add_argument("--source-file", action="append", default=[])
    parser.add_argument("--output-jsonl", help="Write normalized rows to this JSONL path.")
    parser.add_argument("--database-url", help="Optional PostGIS URL for direct upsert.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print summary only.")
    parser.add_argument("--limit", type=int, default=0, help="Optional per-run row limit.")
    args = parser.parse_args(argv)

    manifest = load_manifest(Path(args.manifest))
    sources = manifest_sources(manifest)
    if args.source_key and args.source_key not in sources:
        print(f"source key not found in manifest: {args.source_key}", file=sys.stderr)
        return 1

    if not args.source_file:
        print_manifest_summary(sources, manifest)
        return 0

    if not args.source_key:
        print("--source-key is required when --source-file is used", file=sys.stderr)
        return 1

    rows: list[GeocoderImportRow] = []
    skipped = 0
    source = sources[args.source_key]
    for raw_source_file in args.source_file:
        parsed_rows, parsed_skipped = read_source_file(Path(raw_source_file), source)
        rows.extend(parsed_rows)
        skipped += parsed_skipped
        if args.limit and len(rows) >= args.limit:
            rows = rows[: args.limit]
            break

    if args.output_jsonl:
        write_jsonl(Path(args.output_jsonl), rows)
    if args.database_url and not args.dry_run:
        upsert_rows(args.database_url, rows)

    print(f"geocoder import rows={len(rows)} skipped={skipped} source={source.key}")
    return 0


def load_manifest(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"manifest must be a YAML object: {path}")
    if payload.get("schema_version") != "geocoding-data-manifest/v1":
        raise SystemExit("unsupported geocoding manifest schema_version")
    return payload


def manifest_sources(manifest: dict[str, Any]) -> dict[str, ImportSource]:
    datasets = manifest.get("datasets")
    if not isinstance(datasets, list):
        raise SystemExit("manifest datasets must be a list")

    sources: dict[str, ImportSource] = {}
    for dataset in datasets:
        if not isinstance(dataset, dict):
            continue
        key = str(dataset.get("key") or "").strip()
        if not key:
            continue
        precision = str(dataset.get("target_precision") or "unknown").strip()
        place_type = str(dataset.get("target_place_type") or "poi").strip()
        sources[key] = ImportSource(
            key=key,
            license=str(dataset.get("license") or ""),
            attribution=str(dataset.get("attribution") or dataset.get("provider") or key),
            source_url=str(dataset.get("landing_url") or ""),
            target_precision=precision if precision in GEOCODE_PRECISION_VALUES else "unknown",
            target_place_type=place_type if place_type in PLACE_TYPE_VALUES else "poi",
        )
    return sources


def read_source_file(path: Path, source: ImportSource) -> tuple[list[GeocoderImportRow], int]:
    if path.suffix.casefold() == ".jsonl":
        return read_jsonl(path, source)
    return read_csv(path, source)


def read_csv(path: Path, source: ImportSource) -> tuple[list[GeocoderImportRow], int]:
    rows: list[GeocoderImportRow] = []
    skipped = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            parsed = geocoder_row_from_mapping(row, source)
            if parsed is None:
                skipped += 1
                continue
            rows.append(parsed)
    return rows, skipped


def read_jsonl(path: Path, source: ImportSource) -> tuple[list[GeocoderImportRow], int]:
    rows: list[GeocoderImportRow] = []
    skipped = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                skipped += 1
                continue
            parsed = geocoder_row_from_mapping(payload, source)
            if parsed is None:
                skipped += 1
                continue
            rows.append(parsed)
    return rows, skipped


def geocoder_row_from_mapping(row: dict[str, Any], source: ImportSource) -> GeocoderImportRow | None:
    name = row_text(
        row,
        "name",
        "poi_name",
        "road_name",
        "address",
        "Shelter Name",
        "ShelterName",
        "避難收容處所名稱",
        "中文單位名稱",
        "機構名稱",
        "road",
    )
    lat = row_float(row, "lat", "latitude", "Latitude", "緯度", "POINT_Y", "y")
    lng = row_float(row, "lng", "lon", "longitude", "Longitude", "經度", "POINT_X", "x")
    if not name or lat is None or lng is None or not within_taiwan_bounds(lat, lng):
        return None

    address = row_text(row, "address", "Shelter address", "避難收容處所地址", "地址")
    raw_aliases = row_text(row, "aliases", "alias", "matched_query")
    alias_values = [name]
    if address:
        alias_values.append(address)
    if raw_aliases:
        alias_values.extend(part.strip() for part in raw_aliases.replace(";", "|").split("|"))

    precision = row_text(row, "precision", "geocode_precision") or source.target_precision
    place_type = row_text(row, "type", "place_type") or source.target_place_type
    return GeocoderImportRow(
        source_key=source.key,
        source_record_id=row_text(row, "id", "source_record_id", "編號", "Serial number", "機構代碼"),
        name=name,
        aliases=taiwan_address_aliases(*alias_values, limit=24),
        normalized_aliases=normalized_aliases(*alias_values, limit=24),
        lat=lat,
        lng=lng,
        admin_code=row_text(row, "admin_code", "county_code", "city_code", "VILLCODE"),
        precision=precision if precision in GEOCODE_PRECISION_VALUES else source.target_precision,
        place_type=place_type if place_type in PLACE_TYPE_VALUES else source.target_place_type,
        source_url=row_text(row, "source_url") or source.source_url,
        license=row_text(row, "license") or source.license,
        attribution=row_text(row, "attribution") or source.attribution,
        confidence=row_float(row, "confidence"),
        metadata={"raw": {key: value for key, value in row.items() if value not in (None, "")}},
    )


def row_text(row: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def row_float(row: dict[str, Any], *keys: str) -> float | None:
    text = row_text(row, *keys)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def within_taiwan_bounds(lat: float, lng: float) -> bool:
    return TAIWAN_LAT_RANGE[0] <= lat <= TAIWAN_LAT_RANGE[1] and TAIWAN_LNG_RANGE[0] <= lng <= TAIWAN_LNG_RANGE[1]


def write_jsonl(path: Path, rows: list[GeocoderImportRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row_to_payload(row), ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def upsert_rows(database_url: str, rows: list[GeocoderImportRow]) -> None:
    import psycopg
    from psycopg.types.json import Jsonb

    statement = """
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
    with psycopg.connect(database_url, connect_timeout=5) as connection:
        with connection.cursor() as cursor:
            cursor.executemany(
                statement,
                [
                    {
                        **row_to_payload(row),
                        "aliases": list(row.aliases),
                        "normalized_aliases": list(row.normalized_aliases),
                        "metadata": Jsonb(row.metadata),
                    }
                    for row in rows
                ],
            )


def row_to_payload(row: GeocoderImportRow) -> dict[str, Any]:
    return {
        "source_key": row.source_key,
        "source_record_id": row.source_record_id,
        "name": row.name,
        "aliases": list(row.aliases),
        "normalized_aliases": list(row.normalized_aliases),
        "lat": row.lat,
        "lng": row.lng,
        "admin_code": row.admin_code,
        "precision": row.precision,
        "place_type": row.place_type,
        "source_url": row.source_url,
        "license": row.license,
        "attribution": row.attribution,
        "confidence": row.confidence,
        "metadata": row.metadata,
    }


def print_manifest_summary(sources: dict[str, ImportSource], manifest: dict[str, Any]) -> None:
    categories = sorted(
        {
            str(dataset.get("category"))
            for dataset in manifest.get("datasets", [])
            if isinstance(dataset, dict) and dataset.get("category")
        }
    )
    print(f"geocoding manifest sources={len(sources)} categories={','.join(categories)}")
    for key in sorted(sources):
        source = sources[key]
        print(f"- {key}: precision={source.target_precision} type={source.target_place_type}")


if __name__ == "__main__":
    raise SystemExit(main())
