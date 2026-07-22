# Hosted Signal-Gap Discovery Refresh - 2026-07-01

## Summary

This review records the first automated signal-gap discovery refresh generated
by `scripts/local-source-signal-gap-discovery-refresh.py`.

The script reads the current local-source action plan, discovers all current
`signal_gap_priority_groups`, fetches the data.gov.tw dataset export once, and
writes one discovery artifact per unresolved signal family plus a summary.

## Artifacts

Artifacts are stored under:

```text
docs/reviews/hosted-signal-gap-discovery-refresh-2026-07-01/
```

Files:

- `signal-gap-discovery-refresh-summary.json`
- `signal-gap-discovery-refresh-pump-or-gate-status.json`
- `signal-gap-discovery-refresh-flood-depth.json`
- `signal-gap-discovery-refresh-sewer-water-level.json`

## Result

- `pump_or_gate_status`: 13 target counties, 9 metadata-only candidates,
  0 live read API candidates.
- `flood_depth`: 3 target counties, 2 metadata-only candidates,
  0 live read API candidates.
- `sewer_water_level`: 1 target county, 0 candidates.

Overall:

- `signal_gap_group_count`: 3
- `total_candidate_count`: 11
- `total_metadata_only_count`: 11
- `total_candidate_live_read_api_count`: 0

## Completion Boundary

This refresh does not satisfy `required_signal_families`. Metadata-only
candidate records are useful for official follow-up and station/source review,
but they do not provide latest observation reads. The completion gate still
requires accepted evidence for each remaining county/signal item through a
production adapter, an authorization-gated adapter, or an official
unavailable-source decision.

Hosted Monitoring now runs this refresh on every scheduled/manual run, so future
official catalog changes can be detected without relying on ad hoc manual
searches.
