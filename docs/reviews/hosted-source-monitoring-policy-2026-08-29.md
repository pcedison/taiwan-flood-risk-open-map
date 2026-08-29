# Hosted source monitoring policy review — 2026-08-29

## Decision

Hosted Monitoring separates the official sources into two explicit classes:

- **Required query backbone** — a failed, stale, disabled, or empty source fails
  the hosted source-freshness smoke.
- **Advisory context** — the source is still queried, returned by
  `/admin/v1/sources`, written to `checked_sources`, and reported through
  `advisory_findings`, but it does not turn an upstream publication gap into an
  application deployment failure.

This is a monitoring classification only. It does not convert stale data into
fresh data, suppress an unavailable source in the public diagnostics, or allow
an advisory observation to prove a low-risk result.

## Required query backbone

| Adapter | Required role |
| --- | --- |
| `official.cwa.rainfall` | Current rainfall |
| `official.wra.water_level` | River/water-level observation |
| `official.ncdr.cap` | Active official flood warning or proven empty active-event poll |
| `official.wra_iow.flood_depth` | National road flood-depth telemetry |
| `official.civil_iot.sewer_water_level` | Urban drainage loading context |

The Tainan direct sensor source remains independently enabled in production and
is not replaced by this classification. Exact-address verification at
`臺南市安南區海佃路二段461巷` returned the nearby Tainan station `編號153`
at about 92.7 metres with a 0 cm reading on deployed SHA
`0ef8ff03399497d439dd2a44fdbfaa3eacf5ce67`.

## Advisory context and evidence

The evidence below was captured from production Hosted Monitoring run
`33219142807` at `2026-08-28T23:05:32Z` and independently replayed against the
public upstream APIs on `2026-08-29`.

| Adapter | Evidence | Classification reason |
| --- | --- | --- |
| `official.cwa.tide_level` | Fetch succeeded with 46 rows, but the newest usable observation was `2026-08-27T02:00:00Z`. | Coastal/marine context, not an inland flood absence signal. The official 48-hour marine observation feed was stalled and remains visible as an advisory failure. |
| `official.civil_iot.flood_sensor` | The official service exposed 1,806 matching datastreams, while a complete adapter replay produced 0 usable observations. | The active national road-depth role is covered by WRA IoW; local direct sources such as Tainan remain separate. The legacy feed is retained for recovery detection. |
| `official.civil_iot.pump_water_level` | The service exposed matching pump metadata (11 Things in the adapter query; 30 category datastreams in the migrated catalog query) but returned no observations. | Pump water level is infrastructure context, not a direct flood warning or low-risk proof. |
| `official.civil_iot.gate_water_level` | The service exposed matching gate metadata (44 Things in the adapter query; 114 category datastreams in the migrated catalog query) but returned no observations. | Gate water level is infrastructure context, not a direct flood warning or low-risk proof. |

Official references:

- Civil IoT announced that the project ended on 2025-12-31 and moved the
  SensorThings host to `sta.colife.org.tw`:
  <https://ci.taiwan.gov.tw/dsp/>
- The migrated NCHC catalog still publishes the WRA/local-government resource
  inventory and its SensorThings URLs:
  <https://scidm.nchc.org.tw/dataset/wra02>
- WRA IoW latest flood-depth dataset 142980:
  <https://data.gov.tw/dataset/142980>
- CWA 48-hour marine observation dataset O-B0075-001:
  <https://opendata.cwa.gov.tw/dataset/observation/O-B0075-001>

## Cadence correction

Dataset 142980 is evaluated with the already-reviewed worker thresholds of 90
minutes fresh, 120 minutes degraded, and 180 minutes stale. The admin endpoint
previously used the generic 10/30/60-minute thresholds, so the same 31-minute-old
observation was healthy in the worker and stale in Hosted Monitoring. Admin and
worker now use the same source-specific policy.

## Fail-closed guarantees

- Every default artifact must cover all nine classified adapters in
  `checked_sources`.
- The completion-evidence validator requires the exact required/advisory split
  and rejects missing sources or overlap between classes.
- Required sources retain the existing health, freshness, timestamp, row-count,
  ingestion timestamp, and enabled-gate checks.
- Advisory problems are serialized in `advisory_findings`; missing advisory
  sources are findings rather than being silently ignored.
- NCDR only deduplicates a byte-for-byte transport identity pair (same public ID
  and same official CAP URL). Reusing an ID for another URL, or a URL for another
  ID, still fails closed as a conflict.

## Promotion back to required

An advisory source can return to the required class after its official upstream
provides usable observations across two consecutive scheduled monitoring runs,
its role is necessary for the public risk decision, and a reviewed change updates
the policy plus regression tests. A temporary upstream recovery alone does not
silently change the risk contract.
