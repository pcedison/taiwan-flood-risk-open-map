# Taiwan Open Geocoder MVP Plan

## Goal

The public beta must support Taiwan-wide user searches without making TGOS a launch blocker.
The MVP should return the best honest location level available, then clearly separate
"risk found" from "data insufficient".

## Open Sources Used Now

- g0v/twgeojson administrative divisions, CC0 1.0:
  https://github.com/g0v/twgeojson
- OpenStreetMap / Nominatim Taiwan search fallback, ODbL:
  https://operations.osmfoundation.org/policies/nominatim/
- OpenStreetData / OSM-derived address extracts are a candidate for a later self-hosted index:
  https://openstreetdata.org/
- Taiwan government administrative boundary datasets are published under the Open Government
  Data License:
  https://data.gov.tw/dataset/32157

## Current MVP Behavior

1. Prefer project-owned/file-backed open-data address points when configured.
2. Use bundled Taiwan fixtures only for deterministic local smoke checks.
3. Try project-controlled OSM, then public Nominatim development fallback.
4. If OSM cannot locate an address, parse Taiwan county/city and township/district text and
   return a Taiwan administrative centroid from the bundled CC0 centroid index.
5. The administrative fallback always uses `precision=admin_area` and
   `requires_confirmation=true`. It is not a road or parcel coordinate.
6. The frontend still runs the risk query for coarse fallback points, but displays the geocode
   limitation and the risk API now says "資料不足" when evidence is empty.

## Not Yet Solved

- This is not full doorplate geocoding.
- OSM/Nominatim coverage varies by region and should not be treated as authoritative.
- The bundled admin centroid is only a representative point for fallback UX.
- County/city-only or district-only queries can be ambiguous; ambiguous district names without a
  county/city are intentionally not guessed.

## Next Data Upgrade Path

1. Add a self-hosted OSM/OpenStreetData address and street extract for Taiwan.
2. Add local government doorplate datasets where licenses and schemas are usable.
3. Normalize all open address datasets into `GEOCODER_OPEN_DATA_PATHS` CSV/JSONL imports.
4. Keep TGOS optional for organizations that can satisfy its IP/domain constraints.
5. Add evidence coverage metadata so the UI can distinguish "no evidence found" from
   "coverage unavailable".

