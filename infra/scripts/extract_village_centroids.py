from __future__ import annotations

import argparse
import csv
from pathlib import Path
import tempfile
import zipfile


TAIWAN_LAT_RANGE = (21.7, 26.5)
TAIWAN_LNG_RANGE = (118.0, 122.5)
VILLAGE_LIMITATION = "村里界資料以界線外框代表點供搜尋 fallback 使用，不能視為門牌或道路精準位置。"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract WGS84-ish village centroid rows from the NLSC village boundary SHP ZIP.",
    )
    parser.add_argument("zip_path", help="Downloaded village-boundary ZIP from data.gov.tw/TGOS.")
    parser.add_argument("output_csv", help="Normalized CSV output for import_geocoder_open_data.py.")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    rows = extract_rows(Path(args.zip_path), limit=args.limit)
    write_rows(Path(args.output_csv), rows)
    print(f"village centroid rows={len(rows)} output={args.output_csv}")
    return 0


def extract_rows(zip_path: Path, *, limit: int = 0) -> list[dict[str, object]]:
    try:
        import shapefile
    except ImportError as exc:
        raise SystemExit("pyshp is required: python -m pip install pyshp") from exc

    rows: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(temp_dir)
        shp_path = next(Path(temp_dir).glob("VILLAGE_NLSC_*.shp"), None)
        if shp_path is None:
            raise SystemExit("VILLAGE_NLSC_*.shp not found in ZIP")

        reader = shapefile.Reader(str(shp_path), encoding="utf-8")
        try:
            for shape_record in reader.iterShapeRecords():
                record = shape_record.record.as_dict()
                row = row_from_shape_record(record, shape_record.shape.bbox)
                if row is None:
                    continue
                rows.append(row)
                if limit and len(rows) >= limit:
                    break
        finally:
            reader.close()
    return rows


def row_from_shape_record(
    record: dict[str, object],
    bbox: list[float] | tuple[float, ...],
) -> dict[str, object] | None:
    county = text(record.get("COUNTYNAME"))
    town = text(record.get("TOWNNAME"))
    village = text(record.get("VILLNAME"))
    village_code = text(record.get("VILLCODE"))
    if not county or not town or not village or len(bbox) != 4:
        return None
    lng = (float(bbox[0]) + float(bbox[2])) / 2
    lat = (float(bbox[1]) + float(bbox[3])) / 2
    if not (TAIWAN_LAT_RANGE[0] <= lat <= TAIWAN_LAT_RANGE[1]):
        return None
    if not (TAIWAN_LNG_RANGE[0] <= lng <= TAIWAN_LNG_RANGE[1]):
        return None

    name = f"{county}{town}{village}"
    aliases = "|".join((name, f"{town}{village}"))
    return {
        "source_record_id": village_code,
        "name": name,
        "aliases": aliases,
        "lat": f"{lat:.8f}",
        "lng": f"{lng:.8f}",
        "admin_code": village_code,
        "precision": "admin_area",
        "type": "admin_area",
        "source": "nlsc-village-boundary-centroid",
        "confidence": "0.70",
        "limitations": VILLAGE_LIMITATION,
        "source_url": "https://data.gov.tw/dataset/7438",
        "license": "Open Government Data License, version 1.0",
        "attribution": "內政部國土測繪中心，村里界圖(TWD97經緯度)",
    }


def write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "source_record_id",
        "name",
        "aliases",
        "lat",
        "lng",
        "admin_code",
        "precision",
        "type",
        "source",
        "confidence",
        "limitations",
        "source_url",
        "license",
        "attribution",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def text(value: object) -> str:
    return str(value or "").strip()


if __name__ == "__main__":
    raise SystemExit(main())
