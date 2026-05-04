# Open Basemap PMTiles Runbook

## Purpose

This runbook defines the low-operations basemap path for the MVP and
public-interest launch. The baseline is MapLibre GL JS plus PMTiles or
Protomaps-compatible OpenStreetMap-derived data served from object storage/CDN.
TGOS is a future optional Taiwan-local provider and is not required for runtime
smoke, MVP acceptance, or public launch.

## Launch Architecture

- Renderer: MapLibre GL JS in the web app.
- Basemap data: prebuilt Taiwan/region PMTiles or a licensed hosted MapLibre
  style JSON using OpenStreetMap-derived data.
- Delivery: Cloudflare R2 or another S3-compatible object store, preferably
  behind CDN/cache.
- Overlays: flood potential, risk evidence, query heat, and project MVT layers
  remain separate from the basemap and continue to use project APIs.

The first production path should not run a long-lived tile server. Add
OpenMapTiles, Tegola, PostGIS/ST_AsMVT, Martin, or another tile server only
after the team accepts the higher maintenance cost for generation, refresh,
monitoring, cache invalidation, and rollback.

## Source Selection Checklist

Before publishing a basemap, record:

- PMTiles or style provider name and URL.
- Data source and extract scope, such as Taiwan or East Asia.
- Generation date or provider version.
- License terms for tiles, style JSON, sprites, glyphs, and fonts.
- Required attribution text and links.
- Whether redistribution, CDN caching, and public web use are permitted.

Do not use `tile.openstreetmap.org` or another public OSM community tile
endpoint as production infrastructure. Public OSM tiles are only acceptable for
local development, prototypes, or an explicit temporary incident fallback while
respecting the upstream usage policy.

## Object Storage/CDN Setup

1. Create a bucket dedicated to public map assets.
2. Upload PMTiles files using versioned paths, for example:

   ```text
   basemaps/taiwan/2026-05-04/taiwan.pmtiles
   styles/taiwan-open/2026-05-04/style.json
   ```

3. Keep the previous known-good PMTiles and style JSON available for rollback.
4. Configure CORS so the web origin can fetch style JSON, glyphs, sprites, and
   PMTiles ranges.
5. Ensure the CDN/object store preserves `GET`, `HEAD`, and `Range` requests.
6. Use cache headers appropriate to versioned assets, for example:

   ```text
   Cache-Control: public, max-age=31536000, immutable
   ```

7. Use a short-lived cache only for any unversioned manifest pointer, such as
   `basemaps/current.json`.

Cloudflare R2 is acceptable, but evaluate latency. If R2 latency is high for
Taiwan users, use a custom domain with caching, a different S3-compatible
object store, or a hosted style provider whose terms permit this service.

## Range Request Smoke

Run these checks against the public CDN URL before changing the web runtime:

```powershell
$pmtilesUrl = "https://tiles.example.org/basemaps/taiwan/2026-05-04/taiwan.pmtiles"
curl.exe -I $pmtilesUrl
curl.exe -I -H "Range: bytes=0-16383" $pmtilesUrl
```

Expected evidence:

- `HEAD` returns `200`.
- Range request returns `206 Partial Content`.
- `Content-Range` is present.
- `Accept-Ranges: bytes` is present or the object store/CDN is otherwise
  verified to honor byte ranges.
- CORS allows the web app origin.
- CDN cache headers match the asset versioning strategy.

If the range request is downgraded to a full-file response, do not promote the
PMTiles URL. Browser clients would be forced toward large downloads or broken
tile reads.

## Machine-Readable CDN Evidence

Use the validator to keep basemap/CDN launch evidence separate from narrative
runbook notes:

```powershell
python infra/scripts/validate_basemap_cdn_evidence.py
```

The default evidence file
`docs/runbooks/basemap-cdn-evidence.example.yaml` is a demo/template record with
`production_complete: false`. It may reference public sample PMTiles URLs only
to exercise the schema; it is not evidence that the project's production CDN is
live.

For a production acceptance record, the operator must provide the real style
URL, PMTiles URL, provider/license/cadence owners, browser network log, desktop
and mobile screenshots, and CDN header proof in a private evidence file. Validate
that record with:

```powershell
python infra/scripts/validate_basemap_cdn_evidence.py --production-complete <private-basemap-evidence.yaml>
```

Production-complete mode fails if:

- `production_complete` is not `true`.
- `style_url` or `pmtiles_url` is a placeholder, localhost, or known demo/sample
  URL instead of operator-provided production infrastructure.
- `range_request.status` is not `206` or `Content-Range` evidence is missing.
- CORS or cache-control header evidence is missing or not marked validated.
- Browser network log, desktop screenshot, or mobile screenshot references are
  missing.
- `tile.openstreetmap.org` appears in the captured production request log.
- Provider, license, or cadence owner fields still contain template owners.

To collect a machine-readable header fragment from the candidate PMTiles object
using only Python stdlib networking, run:

```powershell
python infra/scripts/validate_basemap_cdn_evidence.py --probe $pmtilesUrl --origin https://<production-web-origin>
```

Copy the resulting JSON fragment into the private evidence record, then add the
browser artifacts that prove the web app loaded the same production URLs and did
not request the public OSM community tile endpoint.

## Browser Smoke

Before accepting a release:

1. Load the web app with TGOS-related configuration unset or disabled.
2. Verify the basemap style JSON loads without console errors.
3. Pan and zoom across Taiwan; tiles should load progressively.
4. Confirm attribution is visible on desktop and mobile.
5. Run one risk query and confirm risk overlay behavior is unchanged.
6. Toggle existing project overlays, including seeded MVT/query heat paths when
   available.
7. Confirm no request is made to `tile.openstreetmap.org` in production mode.

## Attribution and ODbL Notes

Every public map using OSM-derived data must display visible OpenStreetMap
attribution and make the ODbL basis clear. The attribution must remain visible
when panels, drawers, legends, or mobile controls are open.

Maintain an attribution manifest for each published basemap version. Include
the PMTiles/style URL, source extract, generation date, upstream provider,
license notes, and required attribution. Keep this manifest with release
evidence and public documentation.

Do not relicense OSM-derived databases, PMTiles archives, or exports as pure
project-owned data. When exporting project data, separate project-generated risk
summaries, government open data, OSM-derived data, and source metadata so each
layer's obligations remain clear.

## Cache and Rollback

Use immutable versioned assets for PMTiles, styles, glyphs, and sprites. Promote
a new basemap by updating only the runtime style URL or a small manifest
pointer.

Rollback steps:

1. Point the runtime style URL or manifest pointer back to the previous
   known-good style version.
2. Purge the manifest or style JSON cache if it is not versioned.
3. Keep PMTiles object versions in storage until the next release is accepted.
4. Re-run range request smoke and browser smoke.
5. Record the rollback reason, affected style/PMTiles versions, and whether any
   attribution text changed.

## Future Tile Server Upgrade

Move to OpenMapTiles, Tegola, PostGIS/ST_AsMVT, Martin, or another tile server
only when a specific need justifies the cost, such as:

- Frequent custom basemap regeneration.
- Dynamic vector layers that cannot be shipped as static PMTiles.
- Accepted service-level goals that object storage/CDN cannot meet.
- Need for internal-only layers with strict access control.

That upgrade requires a separate implementation plan covering generation jobs,
source extracts, storage, cache invalidation, monitoring, backup/restore,
rollback, and ODbL attribution.

## References

- OpenStreetMap copyright and ODbL attribution:
  https://www.openstreetmap.org/copyright
- OpenStreetMap tile usage policy:
  https://operations.osmfoundation.org/policies/tiles/
- Protomaps documentation:
  https://docs.protomaps.com/
- PMTiles concepts:
  https://docs.protomaps.com/pmtiles/
- Protomaps Cloudflare deployment notes:
  https://docs.protomaps.com/deploy/cloudflare
