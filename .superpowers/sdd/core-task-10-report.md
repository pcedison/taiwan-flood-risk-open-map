# Core Task 10 implementation report

Date: 2026-08-25 (Asia/Taipei)

## Scope

Implemented the approved `official.wra.historical_flood` metadata-index-to-KML
adapter. The adapter remains independently disabled by default and does not alter
the frozen generic runtime or persisted-only API boundary.

## Contract implemented

- Fetch the pinned WRA JSON metadata index first, select the latest imported KML
  record, then fetch only an HTTPS `opendata.wra.gov.tw` KML URL. The initial URL
  and every relative or absolute redirect hop must remain on that exact HTTPS host,
  without userinfo and with no port other than `443`.
- Treat metadata as provenance only; emit evidence solely from KML Placemarks.
- Parse with `defusedxml` and require the exact
  `{http://www.opengis.net/kml/2.2}kml` root. The only producer repair is the
  current official KML's missing canonical `xmlns:xsi` declaration when its exact
  four-part WRA `xsi:schemaLocation` mapping is present and it is the sole `xsi:`
  use. Generic malformed XML, unrelated unbound prefixes, arbitrary XML roots or
  root namespaces, arbitrary schema mappings, and entity payloads remain rejected;
  descendant elements continue to be interpreted by local name.
- Preserve valid Point, Polygon, MultiPolygon, and polygon-hole coordinates inside
  bounded Taiwan coordinates. Before staging, a source-local pure-Python topology
  guard rejects zero-area, self-intersecting/self-touching rings; holes outside,
  touching, crossing, overlapping, or nested; and interacting/overlapping
  MultiPolygon members. A malformed member rejects its entire geometry.
- Derive stable position-independent IDs from canonical event, Placemark, timestamp,
  name, and geometry content; exact duplicates deduplicate and no-ID Placemarks remain
  deterministic.
- Use only a parseable source-provided Placemark or ancestor event timestamp. ROC dates
  are Taiwan-local dates and are normalized to UTC. Metadata revision and retrieval
  time never substitute for event time.
- Propagate historical scope, precision, geometry, source/resource provenance,
  limitations, and dataset revision through the existing Task 8 staging boundary.
- Register dataset `25770` and the exact pinned metadata URL under Government Open
  Data License v1.0.
- Add independent catalog and live-fetch gates:
  `SOURCE_WRA_HISTORICAL_FLOOD_ENABLED` and
  `SOURCE_WRA_HISTORICAL_FLOOD_API_ENABLED`; both default off.

## TDD evidence

### Initial implementation

Observed RED before each production correction:

1. Initial focused collection failed because the new WRA historical exports did not
   exist (`ImportError: WRA_HISTORICAL_FLOOD_INDEX_URL`).
2. After initial wiring, focused contracts reported `8 failed, 81 passed`: the known
   official missing-`xsi` namespace defect was rejected and metadata still identified
   the wrong dataset.
3. Latest-import selection regression failed because `createdatatime` incorrectly won
   over `_importdate` (`1 failed`).
4. Partial MultiGeometry regression failed because one invalid polygon was silently
   dropped (`1 failed`).
5. Exact catalog URL regression failed because the query contract was omitted
   (`1 failed`).
6. First full Worker run reported `1 failed, 710 passed, 58 skipped`: the existing
   Task 9 synthetic historical test did not opt into Task 10's new independent source
   gate. The fixture was updated to express that gate explicitly.

Each failing contract was rerun green before continuing.

### Independent spec-review fix wave 1

The review findings were implemented in two strict RED/GREEN cycles:

1. Exact KML 2.2 identity/canonical WRA `xsi` repair, per-hop redirect validation,
   and polygon/ring/hole topology contracts first produced `20 failed, 17 passed`.
   The minimal implementation then produced `37 passed` in the Task 10 contract.
2. Two additional fail-closed regressions were added for an extra unbound `xsi:*`
   attribute and overlapping MultiPolygon members. They first produced `2 failed`,
   then passed after the narrow `xsi`-use check and cross-polygon topology guard.

The final Task 10 adapter contract is `39 passed`; affected staging/runtime
regressions are `61 passed`.

## Verification evidence

Latest verification commands and results are recorded before the fix commit:

- Focused adapter/config/catalog suite: `114 passed`.
- Affected staging/runtime suite: `61 passed`.
- Full Worker suite: `735 passed, 58 skipped`.
- Worker mypy: `Success: no issues found in 107 source files`.
- Scoped Ruff (`app/adapters/wra` and the Task 10 contract): `All checks passed!`.
- OpenAPI validation: OpenAPI 3.1 valid (`15` paths, `75` schemas).
- Contract fixtures: all examples conform.
- `git diff --check`: clean.

## Read-only live compatibility diagnostic

The live check was deliberately outside unit tests. The adapter fetched the current
official metadata and 1,481,530-byte KML without test-network dependency. The stages
and rejection classes are intentionally kept distinct:

- raw upstream KML Placemarks: `1232`
- rejected before `RawSourceItem` creation for invalid polygon topology: `7`
- fetched records with valid geometry: `1225`
- rejected during normalization for missing event time: `149`
- normalized source-dated records: `1076`
- preserved valid geometries: `1224 Polygon`, `1 Point`
- unique stable IDs among fetched records: `1225`
- first normalized event timestamp: `2016-09-26T16:00:00Z` (Taiwan-local
  `105-09-27` midnight)

The earlier pre-topology diagnostic (`1232 fetched / 1083 normalized / 149 timestamp
rejected`) counted all parseable-coordinate Placemarks. The evidence-backed seven-row
difference is deliberate: upstream contains self-interacting polygons in
`101-06-10豪雨` (`22`), `98-08-08莫拉克颱風` (`32`, `74`), and
`96-08-18聖帕颱風` (`2`), plus adjacent edge overlap/backtracking in
`97-07-18卡玫基颱風` (`23`, `57`, `157`). Those geometries cannot safely reach
staging. The separate 149 timestamp rejects plausibly correspond to the current
`94-易淹水調查` Document, which lacks a complete parseable event date; they are
intentionally not assigned the metadata revision or retrieval time.

## Residual risks and activation boundary

- Dataset 25770 is historical/irregular and its landing page is retained as historical
  data; upstream availability and shape can change.
- The source supplies no full date for 149 current Placemarks, so they remain auditable
  raw rejections rather than fabricated history.
- Seven current upstream polygon Placemarks violate the reviewed topology contract and
  are filtered before raw-item creation; the source remains disabled by default while
  upstream correction or a separately reviewed repair policy is considered.
- This commit does not activate the adapter, schedule it, deploy it, or use it as
  realtime evidence. Operator activation remains a later reviewed gate decision.
- No live network call occurs in automated tests; injected deterministic fixtures cover
  the contract.
- Independent task review is still required; this report is implementation evidence,
  not self-approval.

## Final verification

- Task 10 adapter contract: `39 passed in 0.09s`.
- Focused Task 10/config/catalog: `114 passed in 0.14s`.
- Affected staging/runtime: `61 passed in 0.08s`.
- Full Worker: `735 passed, 58 skipped in 0.89s`; skips are the existing optional
  PostgreSQL-backed suite in this environment.
- Worker mypy: `Success: no issues found in 107 source files`.
- Scoped Ruff: `All checks passed!`.
- OpenAPI: valid (`15` paths, `75` schemas).
- Contract examples/fixtures: all conform.
- `git diff --check`: exit `0`.
