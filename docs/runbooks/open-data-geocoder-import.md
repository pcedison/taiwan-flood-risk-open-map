# Open-Data Geocoder Import

Status: local file-backed path implemented
Date: 2026-05-04

This runbook describes the no-TGOS geocoder expansion path for public-interest
MVP work. It lets the API read reviewed local CSV or JSONL geocoding rows before
falling back to bundled fixtures, project-controlled OSM, public Nominatim, or
Wikimedia POI lookup.

## Runtime Configuration

Set `GEOCODER_OPEN_DATA_PATHS` to one or more comma-separated local files:

```powershell
$env:GEOCODER_OPEN_DATA_PATHS="docs\data-sources\geocoding\local-open-data-geocoder.example.csv"
```

Supported formats:

- `.csv`: UTF-8 or UTF-8 with BOM.
- `.jsonl`: one JSON object per line with the same keys as the CSV columns.

Missing or invalid files are ignored so local development does not fail closed
because a production data package is absent.

## Required Columns Or Keys

Required:

- `name`: display name or canonical address/road/POI.
- `lat`: latitude in WGS84.
- `lng`: longitude in WGS84.

Optional:

- `aliases`: alternate queries separated by `|`, `;`, or `,`.
- `address`, `road_name`, `poi_name`: accepted fallback names when `name` is
  absent.
- `admin_code`: Taiwan county/city/district code if known.
- `precision`: `exact_address`, `road_or_lane`, `poi`, `admin_area`,
  `map_click`, or `unknown`.
- `type`: `address`, `parcel`, `landmark`, `admin_area`, or `poi`.
- `source`: source label shown in API responses.

Rows outside Taiwan bounds are ignored. Invalid precision/type values fall back
to conservative defaults.

## Provider Order

The API checks providers in this order:

1. File-backed open-data geocoder from `GEOCODER_OPEN_DATA_PATHS`.
2. Bundled local Taiwan fixtures/gazetteer/admin centroids.
3. Project-controlled OSM-compatible lookup when configured in code.
4. Public Nominatim development fallback.
5. Wikimedia POI fallback.

This keeps TGOS optional and prevents public Nominatim from becoming a hidden
production dependency.

## Local Verification

Run:

```powershell
python -m pytest apps\api\tests\test_geocoding_provider_chain.py -q
python scripts\unknown_address_smoke.py
```

For the full no-secret MVP gate:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\public-beta-local-gate.ps1
```

## Production Notes

Before a large file is used for public beta, record:

- data source URL and license/terms;
- retrieval timestamp and checksum;
- transformation script or query;
- field mapping notes;
- row count and skipped-row count;
- owner who accepted the source for public beta.

Do not commit private or restricted datasets. If a dataset has unclear
redistribution terms, keep it out of the public repository and record only a
private evidence reference.
