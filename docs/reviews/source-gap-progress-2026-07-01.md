# Source Gap Progress - 2026-07-01

## Status

The nationwide local-source completion audit remains incomplete. This review
records the next progress step after hosted monitoring evidence wiring: public
data.gov.tw discovery was refreshed for the current signal-family gaps, and the
hosted monitoring workflow can now track private official-request dispatch
follow-ups without uploading private correspondence refs.

## Discovery Refresh

Commands were run on 2026-07-01 against the data.gov.tw dataset export through
`scripts/local-source-discovery-monitor.py`.

Artifacts:

- `docs/reviews/signal-gap-discovery-refresh-2026-07-01-pump-or-gate.json`
- `docs/reviews/signal-gap-discovery-refresh-2026-07-01-flood-depth.json`
- `docs/reviews/signal-gap-discovery-refresh-2026-07-01-sewer-water-level.json`

Results:

- `pump_or_gate_status`: 9 metadata-only candidates, 0 live read API
  candidates. Metadata-only candidates were found for New Taipei, Taoyuan, and
  Taichung. Lienchiang, Kinmen, Taitung, Miaoli, Penghu, Nantou, Chiayi City,
  Keelung, Yilan, and Hsinchu County still had no matching candidate in this
  refresh.
- `flood_depth`: 2 metadata-only candidates, 0 live read API candidates.
  Metadata-only candidates were found for Taipei. Lienchiang and Penghu still
  had no matching candidate.
- `sewer_water_level`: 0 candidates for Lienchiang.

Conclusion: this refresh does not satisfy `required_signal_families`. The next
accepted evidence must still come from a production adapter, an
authorization-gated adapter, or an official unavailable-source decision for each
remaining county/signal item.

## Workflow Progress

Hosted Monitoring now supports an optional
`LOCAL_SOURCE_REQUEST_DISPATCH_EVIDENCE_B64` repository secret. When present, it
decodes the private dispatch overlay only into runner temp storage, writes a
public-safe `local-source-request-followups.json` artifact, and emits a
sanitized `local-source-request-dispatch-completion-evidence.json` overlay with
private evidence refs replaced by
`private-ops://redacted/local-source-request-dispatch`.

Manual workflow dispatch can set `fail_on_overdue_local_source_followups=true`
for release/completion reviews where overdue official follow-ups should fail
the run. Scheduled monitoring remains non-strict by default.

## Still Unfinished

- `required_signal_families`: `pump_or_gate_status:13`, `flood_depth:3`,
  `sewer_water_level:1`.
- `official_authorization_and_contracts`: `authorization_requests:2`,
  `metadata_release_monitors:1`, `public_api_contract_reviews:3`.
- `hosted_worker_persisted_evidence`: freshness policy, raw snapshot retention,
  monitored scheduler cadence, hosted egress review, and worker persisted
  evidence path still require accepted hosted/private evidence.
- `production_monitoring_and_alerting`: alert routing, scheduled freshness
  checks, and worker/scheduler alert ownership still require accepted evidence.
- `ADMIN_BEARER_TOKEN` and the optional private evidence secrets are not proven
  configured from this local run.
