# Core Task 10 implementation report

Date: 2026-08-25 (Asia/Taipei)

## Scope

Implemented the approved `official.wra.historical_flood` metadata-index-to-KML
adapter. The adapter remains independently disabled by default and does not alter
the frozen generic runtime or persisted-only API boundary.

## Contract implemented

- Fetch the pinned WRA JSON metadata index first, select the latest imported KML
  record, then fetch only an HTTPS `opendata.wra.gov.tw` KML URL.
- Treat metadata as provenance only; emit evidence solely from KML Placemarks.
- Parse with `defusedxml`. The only producer repair is the current official KML's
  missing canonical `xmlns:xsi` declaration when `xsi:schemaLocation` is present.
  Generic malformed XML, unrelated unbound prefixes, and entity payloads remain
  rejected.
- Preserve valid Point, Polygon, MultiPolygon, and polygon-hole coordinates inside
  bounded Taiwan coordinates. A malformed member rejects its entire geometry.
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

## Verification evidence

Latest verification commands and expected results are recorded before the commit:

- Focused adapter/config/catalog suite: `91 passed`.
- Full Worker suite: see final verification section below.
- Worker mypy: `Success: no issues found in 107 source files`.
- Scoped Ruff (`app/adapters/wra` and the Task 10 contract): `All checks passed!`.
- OpenAPI validation: OpenAPI 3.1 valid (`15` paths, `75` schemas).
- Contract fixtures: all examples conform.
- `git diff --check`: clean.

## Read-only live compatibility diagnostic

The live check was deliberately outside unit tests. The adapter fetched the current
official metadata and 1,481,530-byte KML without test-network dependency:

- fetched Placemarks: `1232`
- normalized source-dated records: `1083`
- rejected missing-event-time records: `149`
- preserved geometries: `1231 Polygon`, `1 Point`
- unique stable IDs: `1232`
- first normalized event timestamp: `2016-09-26T16:00:00Z` (Taiwan-local
  `105-09-27` midnight)

The 149 rejected records plausibly correspond to the current `94-易淹水調查`
Document, which lacks a complete parseable event date; they are intentionally not
assigned the metadata revision or retrieval time.

## Residual risks and activation boundary

- Dataset 25770 is historical/irregular and its landing page is retained as historical
  data; upstream availability and shape can change.
- The source supplies no full date for 149 current Placemarks, so they remain auditable
  raw rejections rather than fabricated history.
- This commit does not activate the adapter, schedule it, deploy it, or use it as
  realtime evidence. Operator activation remains a later reviewed gate decision.
- No live network call occurs in automated tests; injected deterministic fixtures cover
  the contract.
- Independent task review is still required; this report is implementation evidence,
  not self-approval.

## Final verification

- Focused Task 10/config/catalog: `91 passed in 0.12s`.
- Full Worker: `712 passed, 58 skipped in 0.86s`; skips are the existing optional
  PostgreSQL-backed suite in this environment.
- Worker mypy: `Success: no issues found in 107 source files`.
- Scoped Ruff: `All checks passed!`.
- OpenAPI: valid (`15` paths, `75` schemas).
- Contract examples/fixtures: all conform.
- `git diff --check`: exit `0`.
