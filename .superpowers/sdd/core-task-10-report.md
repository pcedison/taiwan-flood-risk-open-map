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
  root namespaces, arbitrary schema mappings, and entity payloads remain rejected.
  Structural containers and geometries require exact KML 2.2 namespace identity and
  direct Point/Polygon/MultiGeometry/boundary/ring/coordinates hierarchy; mixed,
  foreign, sibling, or partially valid geometry is rejected as one Placemark.
- Bound metadata and KML response bytes, XML depth/elements/Placemark count,
  coordinates per ring and in total, and geometry parts per Placemark before any
  recursive walk or quadratic topology work.
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
- Declare the worker-owned `complete_replace` snapshot lifecycle. Its full 64-character
  content hash raw ref is stable for identical content and changes with source content
  or revision. A full successful promotion may atomically move the trusted
  `data_sources.metadata.active_snapshot_raw_ref` only for an eligible succeeded or
  source-quality-partial summary; failed, limited, staging-invalid, low-fraction, and
  older overlapping runs preserve the last-known-good marker. The public history
  reader fail-closes Task 10 rows to that marker while ordinary evidence is unchanged.

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

### Independent code-quality fix wave 1

The five review findings were implemented as isolated RED/GREEN contracts:

1. Metadata redirect and response-size boundaries first produced `13 failed`, then
   `20 passed` after the metadata and KML fetchers both used the controlled per-hop
   HTTPS WRA-host opener and `limit + 1` reads.
2. XML/geometry complexity caps first produced `7 failed, 1 passed`, then `8 passed`.
3. Exact KML geometry hierarchy and bounded rejection observability first produced
   `6 failed, 1 passed`, then `7 passed`; the full Task 10 contract was `66 passed`
   at that checkpoint.
4. Complete-replace raw-ref, worker-owned staging mode, summary eligibility, atomic
   activation, last-known-good and trusted-reader contracts produced `5 failed,
   1 passed`, then `6 passed`; atomic/runtime declarations produced `7 failed,
   1 passed`, then `10 passed`; the trusted public reader produced `1 failed`, then
   `2 passed` with its existing query regression. A separate audit-summary failure
   regression first demonstrated an unsafe activation (`1 failed`) and then passed
   after activation additionally required summary status `succeeded` or `partial`.
5. PostgreSQL lifecycle checks passed for A-visible/B-hidden-before-activation,
   atomic A-to-B switch including removed rows, ordinary untagged evidence, missing
   marker fail-closed behavior, later failed-poll last-known-good visibility, and
   older/newer-overlap marker preservation.

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

The live check was deliberately outside unit tests. On 2026-08-26 (Asia/Taipei), the
adapter fetched metadata revision `2018-06-08T16:26:00` and the current official
1,481,530-byte KML from the catalog-pinned URL without test-network dependency. The
artifact SHA-256 was
`70e44d54625ed8c1207e6e5f441819bbd45ff5cac7ecf17a3cac0b416c6fdce1`.
The stages and rejection classes are intentionally kept distinct:

- raw upstream KML Placemarks: `1232`
- rejected before `RawSourceItem` creation for invalid geometry/topology: `8`
- fetched records with valid geometry: `1224`
- rejected during normalization for missing event time: `149`
- normalized source-dated records: `1075`
- total `AdapterRunResult.rejected` entries: `157`
- preserved valid geometries: `1223 Polygon`, `1 Point`
- unique stable IDs among fetched records: `1224`
- first normalized event timestamp: `2016-09-26T16:00:00Z` (Taiwan-local
  `105-09-27` midnight)
- complete-replace activation eligibility: `true`; the valid fraction is
  `1075 / (1075 + 157)`, above the reviewed `0.75` floor.

The earlier pre-topology diagnostic (`1232 fetched / 1083 normalized / 149 timestamp
rejected`) counted all parseable-coordinate Placemarks. Seven topology rejections
remain deliberate: upstream contains self-interacting polygons in
`101-06-10豪雨` (`22`), `98-08-08莫拉克颱風` (`32`, `74`), and
`96-08-18聖帕颱風` (`2`), plus adjacent edge overlap/backtracking in
`97-07-18卡玫基颱風` (`23`, `57`, `157`). Those geometries cannot safely reach
staging. The exact-hierarchy review exposed one additional malformed official row:
one-based Document `5` / Placemark `5` (global Placemark `120`),
`104-05-20豪雨淹水範圍` / `虎尾_五間厝`, has one direct `innerBoundaryIs` with
two direct `LinearRing`/coordinates children. KML 2.2 and the reviewed contract
require exactly one ring per boundary, so choosing one or partially retaining that
Polygon would violate the fail-closed source-geometry boundary. A deterministic
fixture now pins this producer shape. The separate 149 timestamp rejects plausibly
correspond to the current
`94-易淹水調查` Document, which lacks a complete parseable event date; they are
intentionally not assigned the metadata revision or retrieval time.

## Residual risks and activation boundary

- Dataset 25770 is historical/irregular and its landing page is retained as historical
  data; upstream availability and shape can change.
- The source supplies no full date for 149 current Placemarks, so they remain auditable
  raw rejections rather than fabricated history.
- Eight current upstream Polygon Placemarks violate the reviewed topology or exact
  hierarchy contract and are filtered before raw-item creation; the source remains
  disabled by default while upstream correction or a separately reviewed repair
  policy is considered.
- A changed but still syntactically accepted upstream artifact can produce a new
  content-addressed generation. Public reads retain the last-known-good active marker
  until an eligible full promotion atomically activates that generation.
- This commit does not activate the adapter, schedule it, deploy it, or use it as
  realtime evidence. Operator activation remains a later reviewed gate decision.
- No live network call occurs in automated tests; injected deterministic fixtures cover
  the contract.
- Independent task review is still required; this report is implementation evidence,
  not self-approval.

## Final verification

- Task 10/staging/ingestion/runtime/promotion affected suite: `260 passed`.
- Full Worker without optional database acceptance: `777 passed, 59 skipped`.
- Full Worker with local PostgreSQL acceptance enabled: `836 passed`, including the
  new atomic marker and older/newer-overlap last-known-good regression.
- API evidence unit and optional-DB collection without a configured database:
  `42 passed, 15 skipped`; full API: `668 passed, 15 skipped`.
- New API PostgreSQL A-to-B visibility/last-known-good integration: `1 passed`.
- Full API with all local PostgreSQL acceptance tests enabled produced
  `682 passed, 1 failed`: the failure is the pre-existing untouched node
  `test_latest_reader_preserves_reviewed_precision_and_limitations` (expected absent
  realtime precision fallback `point`, received `unknown`). A focused rerun reproduces
  it; this wave changes only `query_nearby_evidence`, not
  `query_nearby_latest_official`. It is recorded as unrelated evidence and was not
  modified opportunistically.
- Worker mypy: `Success: no issues found in 107 source files`.
- API mypy: `Success: no issues found in 68 source files`.
- Scoped API Ruff: `All checks passed!`; Worker Ruff exposed only a test annotation
  (`_FakeResponse.__enter__`) and it was corrected to `Self` before final diff check.
- OpenAPI and contract behavior remained covered by the full API/Worker suites; this
  wave changes no schema or frozen public entry point.
