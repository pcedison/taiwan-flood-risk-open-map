# data.gov.tw Source Review - 2026-05-12

Status: accepted for public-beta source planning
Reviewer: Codex automated source review
Verification method: Browser Use inspection of live `data.gov.tw` pages on
2026-05-12.

This review checks the current project source needs against the Taiwan
Government Open Data Platform and records which sources should be preferred for
public-beta development.

Machine-readable catalog:

- `docs/data-sources/official/official-source-catalog.yaml`
- `docs/data-sources/geocoding/geocoding-data-manifest.yaml`

## Primary Sources

| Need | Preferred source | data.gov.tw ref | Integration decision |
|---|---|---|---|
| Realtime rainfall | Central Weather Administration automatic rainfall observations | https://data.gov.tw/dataset/9177 | Keep as the primary rainfall adapter. Dataset 9177 maps to `O-A0002-001`, updates every 10 minutes, and exposes station coordinates plus 10m/1h/3h/6h/12h/24h precipitation fields. |
| Realtime water level | Water Resources Agency realtime water-level observations | https://data.gov.tw/dataset/25768 | Keep as the primary water-level adapter. Use with station metadata and show raw-data limitations because observations are not fully QC checked and can be interrupted. |
| Planning/historical flood potential | Water Resources Agency flood-potential maps | https://data.gov.tw/dataset/25766 | Prefer this as the canonical flood-potential import source. It is planning/reference data, not a live flood warning and not a land-use control basis. |
| Observed historical flood points | National Science and Technology Council flood disaster points | https://data.gov.tw/dataset/130016 | Add as the primary official observed historical flood-point source. It provides year, TWD97 point coordinates, and source agency label for flood disaster information; use it before public-news corroboration. |
| Flood warning layer | Water Resources Agency flood warning dataset | https://data.gov.tw/dataset/5982 | Candidate for Phase 4 warning layer and source freshness monitoring. Do not mix it with historical flood-potential scoring until parser, cadence, and alert semantics are implemented. |
| Village/admin fallback geocoder | National Land Surveying and Mapping Center village boundaries | https://data.gov.tw/dataset/7438 | Keep as the village/admin fallback source. It supports admin-area search and profile shard building, but it is not a doorplate/road-geometry source. |
| Shelter POI geocoder | National Fire Agency shelter point file | https://data.gov.tw/dataset/73242 | Keep as POI search enrichment and future public safety layer. It should not change flood-risk scoring by itself. |
| Road-name fallback geocoder | Ministry of the Interior national road-name data | https://data.gov.tw/dataset/35321 | Keep as road-name search fallback only. It has road names but no road geometry, lanes, alleys, segments, or doorplate coordinates. |

## Non-Sources And Remaining Gaps

- Historical news reports are not available through data.gov.tw as a reusable
  government dataset. Past news evidence still requires the existing reviewed
  public-news/GDELT backfill path, source allowlist, checksum/run evidence, and
  legal/terms approval.
- All-Taiwan doorplate coordinates remain unresolved. The page found on
  data.gov.tw is a public data suggestion/request, not a usable nationwide
  dataset: https://data.gov.tw/suggests/136942. Public beta can use road,
  village, POI, and local partial open-data geocoder rows, but production-grade
  exact address coverage still needs an approved source, license review, and
  coverage report.
- CWA daily rainfall dataset https://data.gov.tw/dataset/9161 is useful for
  historical climatology or QA, but it does not replace the 10-minute rainfall
  source for realtime flood-risk assessment.

## Browser Verification Notes

- Dataset 9177 currently lists `O-A0002-001` API/JSON/XML resources, a 10-minute
  update frequency, CWA as provider, and the government open data license. The
  page says the dataset includes station names/codes, observation time,
  WGS84-capable coordinates, and 10m/1h/3h/6h/12h/24h precipitation fields.
- Dataset 25768 currently lists WRA v2 CSV/JSON/XML resources for realtime
  water levels. Its description explicitly warns that the realtime values are
  raw, not fully quality checked, and may be interrupted or abnormal because of
  transmission or instrument problems.
- Dataset 25766 currently lists WRA v2 CSV/JSON/XML resources for flood
  potential maps. The page describes the layer as planning/reference data and
  says it cannot be used as a live event simulation, land-use control basis, or
  land-development restriction basis.
- Dataset 130016 currently lists a CSV resource with fields `FID`, `year`,
  `X_97`, `Y_97`, and `source`, 998 records, modified on 2025-11-04, and notes
  that the data was produced in 2023. It is a historical point dataset, not a
  depth or address-level event log.
- Dataset 5982 currently lists WRA v2 CSV/JSON/XML resources for flood warning
  KML inventory data. It is useful, but it needs a separate parser and warning
  semantics before entering scoring.
- Dataset 35321 currently confirms national road-name fields
  `city`, `site_id`, and `road`. Public comments from the provider also confirm
  that segment/lane/alley/doorplate detail is outside this dataset.
- The national doorplate coordinates page found on data.gov.tw is suggestion
  `136942`, not a dataset. Its official response says the request was closed as
  not opened because doorplate management is under local-government authority.

## Product Implications

- The UI must label profile-backed historical risk as a precomputed summary and
  show evidence-count provenance. A high historical label without visible
  evidence is not acceptable for public beta.
- Missing realtime rainfall or water-level messages are limitations, not proof
  that the historical profile has no basis.
- Flood-potential evidence must always carry a planning/reference warning. It
  can raise historical/planning concern, but it cannot be presented as an
  active flood event or as a land-use/legal determination.

## Next Implementation Steps

1. Keep dataset 9177 and 25768 as the canonical realtime official bridge and
   worker adapter targets.
2. Continue flood-potential import from reviewed WRA packages with checksum and
   scenario evidence; align any future import manifest to dataset 25766.
3. Add dataset 130016 as an official observed historical flood-point source,
   convert TWD97 / TM2 coordinates to WGS84, and present it separately from
   flood-potential planning polygons.
4. Keep geocoder imports based on dataset 7438, dataset 73242, road-name
   dataset 35321, and local reviewed open datasets until a nationwide
   doorplate source is approved. The import manifest now propagates these
   data.gov.tw IDs and resource URLs into row metadata and import evidence.
5. Make profile fast-path responses include evidence summaries and card-level
   basis text so users can see why historical/profile labels are high.
