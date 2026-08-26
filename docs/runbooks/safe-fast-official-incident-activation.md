# Safe-fast official incident source activation runbook

**Release status: code landed/default off; not production activated.**

Nothing in this document reports a deployment, an enabled source, or a live
credential. It is the checklist an operator follows *later*, one source at a
time, if and when they decide to turn one of these sources on.

## Scope

Four catalog rows are registered by migration
`0038_official_incident_context_sources.sql`, all disabled:

| adapter key | role | may affect the score? |
|---|---|---|
| `official.cwa.heavy_rain_warning` | bounded CAP snapshots and rejection audits | no — audit-only until exact administrative geometry is reviewed |
| `official.ncdr.cap` | bounded CAP datastore/dump snapshots and rejection audits | no — audit-only until administrative and Circle geometry is reviewed |
| `official.npa.police_radio_traffic` | reported flood road incidents | no — non-scoring display context |
| `official.wra.flood_warning` | official warning KML placemarks | no — non-scoring display context |

Each source has three independent, fail-closed gates plus its persisted catalog
row. All four must be on before the source runs, and any one of them turns it
off.

## Activation procedure

Do exactly one source per activation. Do not batch.

1. **Apply the migration with every new row disabled.** Run
   `infra/scripts/apply_migrations.py`. Confirm all four rows exist with
   `is_enabled = false`. Re-running the migration re-asserts `false`, so a row
   someone enabled by hand is forced back off on the next apply.
2. **Enable one catalog row only after persisted proof.** Before flipping a row,
   collect real evidence for that one source: a persisted raw snapshot, a
   staging batch, an ingestion run record, and the resulting evidence rows.
   Without all four, do not proceed.
3. **Enable that source's source, API, and reviewed-contract gates only.** Leave
   every other source's gates untouched. Do not set a gate for a source whose
   contract review is not complete.
4. **Run isolated worker ingestion and a public assessment smoke check.** Run one
   ingestion cycle for that source alone, then query the public assessment for a
   point inside its coverage. Confirm freshness, attribution, and limitations
   render, and confirm the risk level did not move for a context source.
5. **Record the deploy SHA, freshness, row count, attribution, limitations, and
   rollback proof.** Store the record with the change ticket. A rollback that has
   never been rehearsed is not a rollback.
6. **Roll back in fence order.** Disable the catalog row first, then the runtime, API, and contract gates.
   The catalog row is the outermost fence, so it comes off first and goes on
   last. Keep the audit rows; do not delete evidence to "clean up" a failed
   activation.
7. **Keep the boundaries.** `official.cwa.heavy_rain_warning` and
   `official.ncdr.cap` unresolved geometry stays audit-only and never enters
   staging, latest, promotion, or scoring.
   `official.npa.police_radio_traffic` and `official.wra.flood_warning` stay
   non-scoring display context: they never write `official_realtime_latest`,
   never become a scorer signal, and never raise or lower an official level.

## What this release does not do

- It does not enable any source in any environment.
- It does not store an API key or any other credential; the migration metadata is
  public-safe provenance only.
- It does not create a `realtime_source_jurisdictions` mapping, so none of these
  sources can become a required realtime coverage signal.
- It does not claim nearby safety from a healthy empty warning poll. A valid empty
  poll means the source answered correctly with no active event; it is not
  evidence that the area is safe.

## The outermost fence: managed v1 baseline scope

`official.npa.police_radio_traffic` and `official.wra.flood_warning` are
deliberately **absent** from `V1_BASELINE_ADAPTER_KEYS` in
`apps/workers/app/jobs/runtime_managed.py`. The managed cycle refuses them with
`invalid_v1_baseline_scope` before any adapter work runs.

The practical consequence: turning on their three runtime gates is **not** enough
to make them ingest under the managed runner. That is intentional for v1. Adding a
key to the baseline scope is a separate, reviewed decision — do not treat it as
part of a routine activation.

## Known follow-up before any activation

`apps/jobs/freshness.py` does not yet treat a valid-empty
`official.wra.flood_warning` poll as fresh. While the source is disabled this is
inert, but once enabled the poll would be reported `stale` and raise a false
alert. Resolve this before step 3 for that source.
