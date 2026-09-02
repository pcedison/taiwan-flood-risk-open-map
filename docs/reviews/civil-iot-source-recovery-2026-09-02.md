# Civil IoT source recovery review — 2026-09-02

Reviewed at: 2026-09-02 13:45 Asia/Taipei

Decision: keep `STA_RainSewer`; quarantine the three production sources that
depend on `STA_WaterResource_v2` entity queries.

## Official service context

The [Civil IoT data service portal](https://ci.taiwan.gov.tw/dsp/) states that
the original project ended on 2025-12-31 and directs public SensorThings access
to `sta.colife.org.tw`. The [official water-resource dataset page](https://ci.taiwan.gov.tw/dsp/Views/dataset/water.aspx)
continues to advertise water-sensor services. The old
`sta.ci.taiwan.gov.tw` host was therefore not treated as a valid fallback.

This review records current endpoint behavior. It is not evidence that the
affected sensors read zero, that no flooding exists, or that their historical
observations are complete.

## Minimal query matrix

Base: `https://sta.colife.org.tw/STA_WaterResource_v2/v1.0/`

| Query | Result | Approx. latency |
| --- | --- | ---: |
| Service root | HTTP 200 | 0.35 s |
| `Things?$top=1` | HTTP 500 | 10.59 s |
| `Things?$top=1&$count=true` | HTTP 500 | 10.07 s |
| `Datastreams?$top=1` | HTTP 500 | 10.99 s |
| Flood-depth query with one description filter | HTTP 500 | 10.07 s |
| Flood-depth query with both official description filters | HTTP 500 | 10.10 s |
| Flood-depth query expanding Thing and latest Observation | HTTP 500 | 12.03 s |
| `Observations?$top=1` | HTTP 500 | 10.08 s |
| `Sensors?$top=1` | HTTP 500 | 10.07 s |

The service root alone is not a health proof. Independent entity sets fail with
the same upstream response, so narrowing filters or changing the adapter query
cannot currently recover a trustworthy inventory. The old host was unreachable;
an unreviewed guessed `STA_WaterResource` route returned HTTP 404.

Affected production adapter keys:

- `official.civil_iot.flood_sensor`
- `official.civil_iot.pump_water_level`
- `official.civil_iot.gate_water_level`

Migration `0062_quarantine_civil_iot_water_resource.sql` disables those catalog
rows and removes them from the production readiness profile. Adapter code and
prior evidence remain for audit and a future controlled recovery. WRA IoW
remains the production flood-depth path.

## RainSewer result

Base: `https://sta.colife.org.tw/STA_RainSewer/v1.0/`

The official [RainSewer SensorThings dataset guide](https://ci.taiwan.gov.tw/dsp/Files/docs/%E5%9C%8B%E5%9C%9F%E7%AE%A1%E7%90%86%E7%BD%B2%E9%9B%A8%E6%B0%B4%E4%B8%8B%E6%B0%B4%E9%81%93SensorThingsAPI%E8%B3%87%E6%96%99%E9%9B%86%E8%AA%AA%E6%98%8E.pdf)
matches the adapter's service and query shape.

| Check | Observed |
| --- | ---: |
| Upstream `@iot.count` | 2,046 |
| Pages fetched | 5 |
| Source items / unique station IDs | 2,046 / 2,046 |
| Missing or duplicate inventory IDs | 0 |
| Rows with a usable latest observation | 1,950 |
| Stations with no usable latest observation | 96 |
| Adapter parse rejections | 0 |
| Counties represented | 21 |
| Observations older than 24 hours | 0 |

One upstream observation reported `2027-06-19T03:07:00Z`, which was in the
future relative to this run. The shared promotion quality gate must reject it;
it must not be persisted as current evidence. Consequently, a staging run is
expected to promote at most 1,949 of these 1,950 parsed rows unless the upstream
record is corrected.

`official.civil_iot.sewer_water_level` remains enabled and required. This live
probe is discovery evidence only; M4 still requires a worker-persisted 48-hour
staging soak with freshness, rejection, retention, resource, and public-query
checks.

## Re-enable gate for WaterResource sources

A future reviewed migration may re-enable any affected adapter only after all of
the following exist:

1. an official replacement endpoint or restored entity service;
2. HTTP 200 for service root and minimal `Things`, `Datastreams`, and relevant
   Observation queries;
3. complete pagination and station-manifest reconciliation;
4. explicit stale, future-timestamp, missing-observation, and duplicate handling;
5. worker-persisted staging evidence and a continuous 48-hour soak;
6. a reviewed source-registry and readiness-profile migration with rollback.
