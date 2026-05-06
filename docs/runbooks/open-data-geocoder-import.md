# Open-Data Geocoder Import

Status: PostGIS/file-backed path implemented; official beta seed import tooling added
Date: 2026-05-06

This runbook describes the no-TGOS geocoder expansion path for public-interest
MVP work. It lets the API read reviewed PostGIS rows or local CSV/JSONL
geocoding rows before falling back to bundled fixtures, project-controlled OSM,
public Nominatim, or Wikimedia POI lookup.

## Runtime Configuration

Set `GEOCODER_OPEN_DATA_PATHS` to one or more comma-separated local files:

```powershell
$env:GEOCODER_OPEN_DATA_PATHS="docs\data-sources\geocoding\local-open-data-geocoder.example.csv"
```

Supported formats:

- `.csv`: UTF-8 or UTF-8 with BOM.
- `.jsonl`: one JSON object per line with the same keys as the CSV columns.
- `.jsonl.gz`: gzip-compressed JSONL for deployable beta data bundles.

Missing or invalid files are ignored so local development does not fail closed
because a production data package is absent.

When `GEOCODER_OPEN_DATA_PATHS` is unset, the API defaults to the checked-in
public beta bundle under `apps/api/app/data/geocoder/*.normalized.jsonl.gz`.
Set `GEOCODER_BUNDLED_OPEN_DATA_ENABLED=false` only when intentionally testing
without the beta road/POI/admin fallback data.

For production PostGIS lookup, apply migration `0013` and set:

```powershell
$env:GEOCODER_POSTGIS_ENABLED="true"
```

The PostGIS provider fails open to the remaining providers if the table is not
available.

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

1. PostGIS open-data rows when `GEOCODER_POSTGIS_ENABLED=true`.
2. File-backed open-data geocoder from `GEOCODER_OPEN_DATA_PATHS`, or the
   bundled public beta open-data package when paths are unset.
3. Bundled local Taiwan fixtures/gazetteer/admin centroids.
4. Project-controlled OSM-compatible lookup when configured in code.
5. Public Nominatim development fallback.
6. Wikimedia POI fallback.

This keeps TGOS optional and prevents public Nominatim from becoming a hidden
production dependency.

## Data Manifest

Reviewed geocoding sources are tracked in:

```powershell
docs\data-sources\geocoding\geocoding-data-manifest.yaml
```

The manifest records source URL, license, owner, update frequency, intended
precision, and import status. Public beta may use point sources marked
`ready_for_point_import`; address-only sources stay as candidates until a
separate geocoding pass records precision and confidence.

Current beta seed categories:

- roads: Ministry of the Interior national road-name data. This source has no
  road geometry, so beta rows are imported as road search aliases with township
  representative coordinates, low confidence, and a required limitation.
- villages/admin fallback: NLSC village boundary map `TWD97經緯度`, extracted as
  representative village fallback points.
- POI: NFA shelter points.
- POI candidate requiring coordinate transform: NPA police office points.
- address-only POI candidate: MOHW medical institution records.

## PostGIS Import Table

Migration `0013_geocoder_open_data_entries.sql` adds
`geocoder_open_data_entries` with source evidence, aliases, normalized aliases,
precision, place type, geometry, centroid, and GIN/GiST indexes. Point imports
write the same point to `geom` and `centroid`; polygon/line imports should write
the source geometry plus a safe point-on-surface centroid.

## Import Tooling

Plan available sources:

```powershell
python infra\scripts\import_geocoder_open_data.py
```

Normalize a reviewed point CSV to JSONL:

```powershell
python infra\scripts\import_geocoder_open_data.py `
  --source-key npa-police-station-addresses `
  --source-file tmp\reviewed-police-points.csv `
  --output-jsonl tmp\geocoder-police-points.normalized.jsonl `
  --dry-run
```

Fetch and normalize the current beta seed sources:

```powershell
curl.exe -L --output tmp\geocoder-data\roads-114.csv `
  "https://opdadm.moi.gov.tw/api/v1/no-auth/resource/api/dataset/E2EDC47D-2D3F-4EB1-878A-4DEB6160FD4C/resource/6E8E059B-9E8E-403F-B3B7-BC6B95074C18/download"

curl.exe -L --output tmp\geocoder-data\shelters.csv `
  "https://opdadm.moi.gov.tw/api/v1/no-auth/resource/api/dataset/ED6CF735-6C03-4573-A882-72C1BEC799CB/resource/54550E2F-4567-4C8F-BD2E-E54E9D0386B8/download"

curl.exe -L --output tmp\geocoder-data\villages-1150407.zip `
  "https://www.tgos.tw/tgos/VirtualDir/Product/a04697c8-64db-450a-a105-3eb471c45abd/村(里)界(TWD97經緯度)1150407.zip"

python infra\scripts\extract_village_centroids.py `
  tmp\geocoder-data\villages-1150407.zip `
  tmp\geocoder-data\villages-centroids.csv

python infra\scripts\import_geocoder_open_data.py `
  --source-key moi-national-road-names `
  --source-file tmp\geocoder-data\roads-114.csv `
  --output-jsonl tmp\geocoder-data\roads-114.normalized.jsonl `
  --evidence-json tmp\geocoder-data\roads-114.evidence.json

python infra\scripts\import_geocoder_open_data.py `
  --source-key nfa-evacuation-shelter-locations `
  --source-file tmp\geocoder-data\shelters.csv `
  --output-jsonl tmp\geocoder-data\shelters.normalized.jsonl `
  --evidence-json tmp\geocoder-data\shelters.evidence.json

python infra\scripts\import_geocoder_open_data.py `
  --source-key moi-village-boundary-twd97-geographic `
  --source-file tmp\geocoder-data\villages-centroids.csv `
  --output-jsonl tmp\geocoder-data\villages.normalized.jsonl `
  --evidence-json tmp\geocoder-data\villages.evidence.json
```

Apply to PostGIS after migration:

```powershell
python infra\scripts\import_geocoder_open_data.py `
  --source-key moi-national-road-names `
  --source-file tmp\geocoder-data\roads-114.csv `
  --database-url $env:DATABASE_URL
```

The importer rejects rows outside Taiwan bounds and expands aliases for `臺/台`,
full-width digits, and road-section variants such as `二段`/`2段`.

Validate beta coverage evidence:

```powershell
python infra\scripts\geocoder_coverage_smoke.py `
  --input-jsonl tmp\geocoder-data\roads-114.normalized.jsonl `
  --input-jsonl tmp\geocoder-data\shelters.normalized.jsonl `
  --input-jsonl tmp\geocoder-data\villages.normalized.jsonl `
  --evidence-json tmp\geocoder-data\coverage.evidence.json
```

The 2026-05-06 local evidence run produced 46,463 normalized rows:

- roads: 32,874
- POI shelters: 5,878
- village/admin fallback: 7,711

This satisfies the public beta category smoke for roads, villages, and POI. It
is still not production-complete doorplate geocoding because no complete
reviewed national doorplate dataset is imported.

The same rows are committed as compressed runtime data:

```powershell
apps\api\app\data\geocoder\roads-114.normalized.jsonl.gz
apps\api\app\data\geocoder\shelters.normalized.jsonl.gz
apps\api\app\data\geocoder\villages.normalized.jsonl.gz
```

Bundle coverage evidence is recorded at
`docs\data-sources\geocoding\beta-coverage-evidence-2026-05-06.json`.

## Local Verification

Run:

```powershell
python -m pytest apps\api\tests\test_geocoding_provider_chain.py -q
python -m pytest apps\api\tests\test_geocoding_normalization.py tests\test_geocoder_open_data_import.py -q
python infra\scripts\validate_migrations.py
python infra\scripts\geocoder_coverage_smoke.py --input-jsonl tmp\geocoder-data\roads-114.normalized.jsonl --input-jsonl tmp\geocoder-data\shelters.normalized.jsonl --input-jsonl tmp\geocoder-data\villages.normalized.jsonl
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
