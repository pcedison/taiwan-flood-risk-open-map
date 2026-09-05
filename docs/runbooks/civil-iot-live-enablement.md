# Civil IoT / Official Realtime Source Live Enablement Runbook

Purpose: a step-by-step, source-at-a-time procedure to turn the official realtime
adapters (CWA rainfall, WRA/Civil IoT water levels, flood sensors) from
fixture-backed/disabled into live ingestion, with smoke checks and rollback. It
is intentionally incremental so a small node is never flooded all at once.

Pair this with:

- `docs/data-sources/official/civil-iot-sensorthings-integration.md` (what each
  adapter is and the modeling decisions).
- `docs/runbooks/deploy-zeabur.md` (deploy + pod-replace mechanics).
- `scripts/runtime-smoke.ps1`, `scripts/ops-source-freshness-check.ps1` (smoke).

## Prerequisites (do not skip)

1. **Node capacity.** Do not live-enable the full sensor networks on the current
   2 GB node. Target at least **4 GB RAM / 2 vCPU** with retention on (below), or
   **8 GB / 4 vCPU** for comfort. See the capacity table in
   `civil-iot-sensorthings-integration.md`.
2. **Retention is on.** `EVIDENCE_REALTIME_RETENTION_HOURS` (default 48) must be
   set and the scheduler maintenance loop must be running, so rainfall/water_level
   evidence stays bounded. Verify a maintenance cycle logs
   `scheduler.maintenance.completed` with an `evidence_rows_pruned` field.
3. **API keys / access.** CWA needs a free `opendata.cwa.gov.tw` key
   (`CWA_API_AUTHORIZATION`). Civil IoT STA endpoints are public. WRA's IoT
   platform (if used instead of the public dataset) needs membership. Keys are
   set via env, never committed.
4. **Civil IoT endpoint baseline.** Built-in STA defaults use
   `https://sta.colife.org.tw/STA_WaterResource_v2/v1.0/` for water-resource
   sources and `https://sta.colife.org.tw/STA_RainSewer/v1.0/` for storm-sewer
   levels. Keep the `CIVIL_IOT_*_URL` env overrides empty unless a smoke check
   proves the official endpoint has moved.
   Civil IoT `@iot.nextLink` URLs are emitted as already-encoded OData URLs; live
   smoke should include at least one multi-page source so pagination keeps `+`
   spacing intact and does not fail with HTTP 400 on page 2.
   Flood depth is the exception to the shared `Things` query shape: follow the
   official Civil IoT tutorial and query `Datastreams`, expanding `Thing`,
   `Thing/Locations`, and the newest `Observations` row while filtering both
   `Datastream_Category_type=淹水感測器` and
   `Datastream_Category=淹水深度` from `description`. A broad `Things` name
   filter also selects camera/photo streams and overstates the usable inventory.
   On 2026-08-28 the two-page production probe returned 1,806 matching flood-
   depth Datastreams, 1,777 unique station IDs (29 duplicates), and zero
   Observations. The station manifest therefore also remains unapproved. Keep
   that source fail-closed with `upstream_observations_empty`; do not interpret
   it as zero flooding. The working WRA IoW flood-depth source remains the
   current observed-depth path.
5. **Baseline.** Record current RSS per container (`kubectl top pods` or
   `docker stats`) and the current `/health` `deployment_sha` before enabling.

## Source → enablement env vars

Each source needs BOTH its gate flag and its `*_API_ENABLED` live flag, and the
adapter key must be in `WORKER_ENABLED_ADAPTER_KEYS` (or that var unset).

| Source | Adapter key | Gate flag | Live flag | Extra |
|---|---|---|---|---|
| CWA rainfall (full network) | `official.cwa.rainfall` | `SOURCE_CWA_ENABLED=true` | `SOURCE_CWA_API_ENABLED=true` | `CWA_API_AUTHORIZATION=CWA-...` |
| CWA coastal tide level | `official.cwa.tide_level` | `SOURCE_CWA_ENABLED=true` | `SOURCE_CWA_API_ENABLED=true` | `CWA_API_AUTHORIZATION=CWA-...`; coastal context only |
| WRA water level (opendata) | `official.wra.water_level` | `SOURCE_WRA_ENABLED=true` | `SOURCE_WRA_API_ENABLED=true` | — |
| Flood sensors | `official.civil_iot.flood_sensor` | `SOURCE_FLOOD_SENSOR_ENABLED=true` | `SOURCE_FLOOD_SENSOR_API_ENABLED=true` | optional `CIVIL_IOT_FLOOD_SENSOR_URL` |
| River level (STA) | `official.civil_iot.river_water_level` | `SOURCE_CIVIL_IOT_RIVER_ENABLED=true` | `SOURCE_CIVIL_IOT_RIVER_API_ENABLED=true` | overlaps WRA water level — pick one |
| Pond level | `official.civil_iot.pond_water_level` | `SOURCE_CIVIL_IOT_POND_ENABLED=true` | `SOURCE_CIVIL_IOT_POND_API_ENABLED=true` | — |
| Sewer level | `official.civil_iot.sewer_water_level` | `SOURCE_CIVIL_IOT_SEWER_ENABLED=true` | `SOURCE_CIVIL_IOT_SEWER_API_ENABLED=true` | — |
| Pump external level | `official.civil_iot.pump_water_level` | `SOURCE_CIVIL_IOT_PUMP_ENABLED=true` | `SOURCE_CIVIL_IOT_PUMP_API_ENABLED=true` | confirm `外水位` datastream name |

Optional URL overrides:

- `CIVIL_IOT_FLOOD_SENSOR_URL`, `CIVIL_IOT_RIVER_URL`,
  `CIVIL_IOT_POND_URL`, `CIVIL_IOT_SEWER_URL`, `CIVIL_IOT_PUMP_URL`.
- Use overrides only for an official endpoint migration or emergency rollback.
  The old `sta.ci.taiwan.gov.tw` host is not the default.

Recommended enablement order (highest realtime-water value first, lightest load
first): CWA rainfall/tide-level → flood sensors → river level → sewer → pond → pump.

### Kinmen KWIS Local Read Adapter

Kinmen KWIS is not a public no-token source. The ASMX/WSDL exposes
`KWIS_Get_Pump_Basic_Unit_Data`, but blank-token smoke returns HTTP 200 with
`ErrMsg: (7) invalid Token` and `Data: []`. Treat it as authorization-gated until
Kinmen County / the KWIS maintainer grants a read-side Token and confirms the
response schema, license, rate limit, freshness policy, and production use.

After authorization, enable it explicitly:

```env
WORKER_ENABLED_ADAPTER_KEYS=local.kinmen.kwis_pump_station
SOURCE_KINMEN_KWIS_PUMP_STATION_ENABLED=true
SOURCE_KINMEN_KWIS_PUMP_STATION_API_ENABLED=true
KINMEN_KWIS_API_TOKEN=<private read-side token>
```

Leave `KINMEN_KWIS_PUMP_STATION_API_URL` empty unless the official ASMX method
moves. The worker uses the Taiwan government TLS compatibility context that
keeps CA and hostname verification and only clears `VERIFY_X509_STRICT`.

Do not use KWIS upload-only credentials or blank-token smoke output as proof of
production readiness. Kinmen remains incomplete until an authorized hosted
worker-persisted evidence smoke normalizes real rows.

## Procedure (repeat per source)

1. **Dry validation locally** before touching hosted:
   ```powershell
   .\scripts\runtime-smoke.ps1 -StopOnExit
   ```
   and confirm the adapter appears enabled with the flags set in a local `.env`.
2. **Enable one source** by setting its gate + live flags (and key) in the hosted
   environment. Leave the others off.
3. **Deploy / restart the worker** (and API if env changed). On Zeabur, use the
   pod-replace path in `deploy-zeabur.md` if a rolling deploy will not fit.
4. **Run the smoke checks** below.
5. **Watch memory for one full retention window-ish** (or at least 30-60 min):
   `kubectl top pods` / `docker stats`. PostGIS RSS and disk should plateau, not
   climb without bound (retention should cap it).
6. If healthy, proceed to the next source. If not, roll back (below).

## Per-source smoke checks

For a direct official-source backbone smoke outside Docker Compose, run:

```bash
PYTHONPATH=apps/workers python scripts/official-realtime-live-smoke.py --env-file .env
```

The command emits JSON for CWA, WRA water level, WRA IoW flood depth, NCDR CAP,
and Civil IoT flood/sewer/pump/gate water-level sources. It marks CWA as
`skipped` when `CWA_API_AUTHORIZATION` is not available in the selected env file
or process environment; use `--fail-on-skipped` in CI or hosted readiness checks
when all credentials must be loaded.

WRA open-data and NCDR CAP endpoints have been observed to fail under Python /
OpenSSL contexts that enable `VERIFY_X509_STRICT` because their certificate
chain omits a Subject Key Identifier. The worker fetchers for those official
endpoints use a Taiwan government open-data TLS compatibility context that
removes only that strict-chain flag while keeping CA verification and hostname
verification enabled. Treat any remaining certificate error as a hosted egress
or upstream certificate incident, not as permission to disable TLS verification.

After each official live smoke, compare the observed county distribution with
the unresolved local-source signal gaps:

```bash
PYTHONPATH=apps/api python scripts/local-source-signal-gap-evidence.py \
  --official-live-smoke-json docs/reviews/official-realtime-live-smoke-YYYY-MM-DD.json \
  --output docs/reviews/local-source-signal-gap-evidence-YYYY-MM-DD.json
```

Use `--fail-on-unresolved` only in a completion rehearsal where every remaining
signal-gap item is expected to be covered. The output is diagnostic evidence:
`official_smoke_observed` means a source should be reviewed for catalog,
adapter, source-contract, and production-evidence work; it does not satisfy the
completion gate by itself.

For a broader gate that also scans unresolved local-source discovery for 金門縣
and 連江縣, run:

```bash
PYTHONPATH=apps/workers python scripts/realtime-source-gate.py --env-file .env
```

Use `--fail-on-skipped-smoke` in hosted readiness checks when CWA credentials
must be loaded, and `--fail-on-live-candidate` when a newly published data.gov.tw
candidate should stop the pipeline until it is reviewed and either implemented
or documented as unsuitable.

The gate output also includes `production_readiness`. Treat
`production_readiness.readiness_state: not_production_complete` as the expected
state until all required gates have private evidence: credential review, source
license review, raw snapshot retention policy, hosted scheduler cadence, hosted
egress review, alert routing ownership, and worker-persisted evidence smoke.
Green official live smoke proves current upstream reachability only; it does not
prove the hosted production evidence set is complete.

For hosted readiness rehearsals, pass a private evidence JSON and fail closed
when any gate is missing:

```bash
PYTHONPATH=apps/workers python scripts/realtime-source-gate.py \
  --env-file .env \
  --production-gate-evidence-json private-production-gates.json \
  --fail-on-missing-production-gates
```

1. **Ingestion ran**: worker logs show
   `scheduler.ingestion_cycle.completed` and the adapter's batch summary with
   `normalized > 0` (and `fetched > 0`). No repeated adapter errors.
2. **Freshness healthy**:
   ```powershell
   .\scripts\ops-source-freshness-check.ps1 -BaseUrl "https://<api>" -AdminToken "<token>" -MaxAgeMinutes 60
   ```
   The source shows `healthy` with a recent `source_timestamp_max`.
3. **Risk response surfaces it**: POST `/v1/risk/assess` (`time_context:"now"`,
   `radius_m<=2000`) near a known station and confirm the new source appears in
   `data_freshness` and, for rainfall/water, contributes to `realtime` rather
   than "即時資料不足".
4. **Retention is pruning**: after the next maintenance cycle, confirm
   `scheduler.maintenance.completed` logs a non-zero `evidence_rows_pruned` once
   data is older than the window, and the evidence row count is stable.
5. **Memory bounded**: PostGIS RSS/disk plateaus across a few cycles.

## Endpoint migration monitoring

Civil IoT has moved public STA access to `sta.colife.org.tw` for the sources in
this project. Before and after 2026-12-01, run a short live probe for each
enabled source during deploy:

```powershell
curl.exe -f 'https://sta.colife.org.tw/STA_WaterResource_v2/v1.0/Things?$top=1'
curl.exe -f 'https://sta.colife.org.tw/STA_RainSewer/v1.0/Things?$top=1'
curl.exe -f 'https://sta.colife.org.tw/STA_WaterResource_v2/v1.0/Datastreams?$filter=substringof(%27Datastream_Category_type=%E6%B7%B9%E6%B0%B4%E6%84%9F%E6%B8%AC%E5%99%A8%27,description)%20and%20substringof(%27Datastream_Category=%E6%B7%B9%E6%B0%B4%E6%B7%B1%E5%BA%A6%27,description)&$top=1&$count=true'
```

If either probe fails while the official data portal announces a replacement
host, set the matching `CIVIL_IOT_*_URL` override to the new full `Things?...`
query (or the documented flood-sensor `Datastreams?...` query), redeploy one
source at a time, and record the incident in the source matrix.

## 上游 500 通報流程 (upstream outage escalation)

Since 2026-07-01 15:05Z the `STA_WaterResource_v2` service has returned HTTP 500
on every request, while `STA_RainSewer` on the same host stays healthy. Three
production backbone sources depend on it and fail every cycle:
`official.civil_iot.flood_sensor`, `official.civil_iot.pump_water_level`, and
`official.civil_iot.gate_water_level`. This is an upstream outage, not a
regression in this project, so `/v1/ingestion-readiness` reports those sources as
`status=failed` with `reason_code=upstream_unavailable` and counts them in
`source_summary.upstream_unavailable_source_count` instead of
`failed_source_count`. Do not roll back or "fix" the adapters on this signal
alone — confirm the upstream first.

Only transport failures are excused this way. If a source instead reports
`reason_code=upstream_contract_changed`, the upstream answered but the payload no
longer matches our parser: that stays inside `failed_source_count` because the
fix is an adapter change here, not a wait. Likewise, readiness stays `down`
whenever anything other than an upstream outage is keeping sources from
`operational` — the outage only excuses the sources it actually took out.

### 1. Minimal reproduction

Run both probes from an ordinary network (no VPN, no proxy). One failing while
the other succeeds is the signature of a service-side outage:

```powershell
curl.exe -sS -o NUL -w "%{http_code}`n" 'https://sta.colife.org.tw/STA_WaterResource_v2/v1.0/Things?$top=1'
curl.exe -sS -o NUL -w "%{http_code}`n" 'https://sta.colife.org.tw/STA_RainSewer/v1.0/Things?$top=1'
```

Expected during this incident: `500` for the first, `200` for the second. Keep
the raw output — the response body and the timestamp are what the operator asks
for. Repeat once per day so the report carries a duration, not a single sample.

### 2. What to send Civil IoT Taiwan support

Report through the Civil IoT Taiwan portal (<https://ci.taiwan.gov.tw/>) contact
form. Include, and nothing beyond, these public facts:

- Affected service base: `https://sta.colife.org.tw/STA_WaterResource_v2/v1.0/`
- The exact failing request above (`Things?$top=1`) and the HTTP 500 response
  body verbatim.
- First observed UTC timestamp and the latest confirmation timestamp, plus the
  fact that the failure is continuous rather than intermittent.
- The contrast probe: `STA_RainSewer` on the same host returns 200, so the
  problem is scoped to `STA_WaterResource_v2`, not DNS, TLS, or the caller.
- Client details: plain `GET`, `Accept: application/json`, User-Agent
  `FloodRiskTaiwan/0.1 worker-civil-iot-sta`, no authentication required by the
  published contract, request rate one poll per source per cycle.
- Which public datasets this blocks (flood sensors, pump station outer water
  level, gate water level) and that this is a public-interest flood risk map.

Never send credentials, internal hostnames, database details, or worker logs.

### 3. Verification after recovery

1. Both probes in step 1 return `200`.
2. Let one scheduler cycle complete (or run the adapters once manually per the
   Procedure section above).
3. `GET /v1/ingestion-readiness` shows all three sources back at
   `status=operational`, `reason_code=operational`, and
   `source_summary.upstream_unavailable_source_count` back to `0`:

   ```powershell
   curl.exe -sS "$env:API_BASE_URL/v1/ingestion-readiness" | python -c "import json,sys; p=json.load(sys.stdin); print(p['status'], p['source_summary']['upstream_unavailable_source_count']); print([(s['source_id'], s['status'], s['reason_code']) for s in p['sources'] if 'civil-iot' in s['source_id']])"
   ```

4. Remove the `upstream_incident` note from the three entries in
   `config/source-registry.yaml`, update the adapter keys hard-coded in
   `tests/test_source_registry_validator.py`
   (`test_registry_records_the_open_civil_iot_upstream_incident`) to match, and
   record the recovery in the source matrix.

## Rollback (per source)

1. Set the source's gate flag to `false` (e.g. `SOURCE_FLOOD_SENSOR_ENABLED=false`)
   — this stops ingestion immediately on the next cycle.
2. Redeploy / restart the worker.
3. Existing rows age out via retention; to reclaim space immediately, lower
   `EVIDENCE_REALTIME_RETENTION_HOURS` temporarily and let maintenance prune, or
   prune manually in a maintenance window.
4. Record the incident: source, first/last enabled time, observed RSS, reason.

## Notes

- River level via Civil IoT (`official.civil_iot.river_water_level`) overlaps the
  opendata WRA adapter (`official.wra.water_level`). Enable only one to avoid
  double-counting water-level evidence.
- Sewer level uses Civil IoT / National Land Management Agency `STA_RainSewer`
  (`nlma1`), not the `STA_WaterResource` service.
- The full CWA rainfall network is `official.cwa.rainfall` (`O-A0002-001`); there
  is no separate "full network" adapter to enable.
- Retention prunes only official `rainfall`/`water_level` evidence. Flood-sensor
  `flood_report` rows (genuine flooding) and historical evidence are kept.
