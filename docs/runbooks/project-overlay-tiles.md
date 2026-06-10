# Project Overlay Tile Operations

Reviewed: 2026-06-09

This runbook covers project-owned overlay tiles such as flood-potential and
query-heat. Basemap PMTiles/CDN readiness is tracked separately.

## Public API Contract

- `/v1/layers` is the source of layer availability. Layers without accepted
  production tile metadata must return `status: disabled` or `status: degraded`.
- `/v1/layers/{layer_id}/tilejson` must never return placeholder hosts such as
  `tiles.placeholder.flood-risk.local` or `tiles.example.test`.
- When a layer record has no accepted production tile template, hosted
  TileJSON returns `503 tiles_unavailable` for enabled layers and `404
  layer_disabled` for disabled layers.
- Local/test environments can opt into the runtime vector tile endpoint:
  `/v1/tiles/{layer_id}/{z}/{x}/{y}.mvt`.
- TileJSON exposes `status`, `tile_url_source`, `cache_control`, and
  `updated_at` so operators and clients can distinguish metadata-backed CDN
  tiles from local runtime tiles.

## Cache And Expiry

- Local runtime MVT endpoint cache header: `public, max-age=60`.
- Cached runtime tiles are stored in `tile_cache_entries`; entries with
  `expires_at <= now()` are ignored.
- Production CDN/object-storage overlays should use immutable object paths:
  `overlays/{layer_id}/{release_id}/{z}/{x}/{y}.mvt`.
- Recommended CDN policy for accepted release objects: immutable cache for the
  release path, plus a short-lived manifest or layer metadata pointer that can
  be rolled back.

## Refresh

Use a scheduler or one-off worker job after accepted source data changes:

```powershell
docker compose run --rm worker sh -c "pip install -e . && python -m app.main --refresh-tile-features --tile-layer-id flood-potential --tile-feature-limit 25"
```

For hosted production, run the same worker entrypoint with the production
database and object storage credentials, then update `map_layers.metadata.tiles`
only after validation confirms the uploaded release path is reachable.

## Rollback

1. Keep the previous accepted release path in the deployment record.
2. Update `map_layers.metadata.tiles` back to the previous release template.
3. Set `map_layers.updated_at` to the rollback time and mark the replacement
   release in the incident log.
4. Purge only the short-lived layer metadata or manifest cache. Immutable tile
   objects should remain addressable for audit and rollback.
5. If no accepted release remains, set the layer `status` to `disabled`; the API
   will return `404 layer_disabled` for TileJSON in hosted environments instead
   of a fake production host. Local/test operators can still enable
   `TILE_DYNAMIC_FALLBACK_ENABLED=true` for runtime tile debugging.
