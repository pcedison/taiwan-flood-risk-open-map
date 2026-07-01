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

## Dispatch Readiness

The hosted discovery refresh is now converted into a public-safe dispatch
readiness artifact:

- `docs/reviews/hosted-signal-gap-dispatch-readiness-2026-07-01.json`

The artifact does not include `private-ops://` refs and does not prove requests
were sent. It records that all three unresolved signal groups still need
official read API dispatch:

- `pump_or_gate_status`: 13 target counties, 9 metadata-only candidates,
  0 live read API candidates.
- `flood_depth`: 3 target counties, 2 metadata-only candidates,
  0 live read API candidates.
- `sewer_water_level`: 1 target county, 0 candidates.

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

Hosted Monitoring also now uploads `signal-gap-dispatch-readiness.json` on every
scheduled/manual run after the data.gov.tw discovery refresh.

## Source Contract Dispatch Readiness

Hosted Monitoring now also uploads `source-contract-dispatch-readiness.json`.
The local 2026-07-01 review artifact is:

- `docs/reviews/source-contract-dispatch-readiness-2026-07-01.json`

It records that all six current `official_authorization_and_contracts` items
still need dispatch/follow-up:

- `authorization_request`: 2
- `metadata_release_monitor`: 1
- `public_api_contract_review`: 3

This remains progress tracking only. The gate is still incomplete until private
source-contract evidence is accepted for each county/gate item.

## Request Packet Bundle

Hosted Monitoring now also writes a `local-source-request-packet-bundle`
artifact set. This moves the remaining request work one step closer to
operation by publishing the exact generated official request packets,
signal-gap batches, and placeholder dispatch/completion templates on every
scheduled/manual monitoring run.

The bundle includes:

- `local-source-request-packet-bundle-manifest.json`
- `local-source-request-packet-bundle.md`
- `local-source-official-request-packets.json`
- `local-source-official-request-packets.md`
- `local-source-official-request-completion-template.json`
- `local-source-signal-gap-request-batches.json`
- `local-source-signal-gap-request-batches.md`
- `local-source-signal-gap-dispatch-template.json`
- `local-source-source-contract-dispatch-template.json`

This is still not completion evidence: the dispatch templates contain
placeholders and must be replaced only inside private evidence handling after
actual official dispatch or accepted replies.

## Hosted Private Evidence Readiness

Hosted Monitoring also uploads `hosted-private-evidence-readiness.json`. The
latest route-aware local 2026-07-01 no-secret review artifacts are:

- `docs/reviews/hosted-private-evidence-readiness-2026-07-01.json`
- `docs/reviews/hosted-private-evidence-readiness-routes-2026-07-01.json`

It records the configured/missing state for the admin token and private evidence
manifest inputs without printing secret values. The route-aware review now
tracks two acceptable paths for `hosted_worker_persisted_evidence`:

- `hosted_worker_full_manifest`: one all-in-one
  `HOSTED_WORKER_EVIDENCE_MANIFEST_B64` manifest can satisfy all five hosted
  worker requirements.
- `hosted_worker_admin_freshness_plus_policy_manifest`: `ADMIN_BEARER_TOKEN`
  plus `HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64` can split the same gate
  between hosted source freshness evidence and hosted worker policy evidence.

The current no-secret review shows these completion-gate blockers:

- `hosted_worker_persisted_evidence`: `ADMIN_BEARER_TOKEN`,
  `HOSTED_WORKER_EVIDENCE_MANIFEST_B64`,
  `HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64`
- `production_monitoring_and_alerting`:
  `HOSTED_MONITORING_EVIDENCE_MANIFEST_B64`

`LOCAL_SOURCE_REQUEST_DISPATCH_EVIDENCE_B64` is also missing, but it remains
progress/follow-up visibility rather than accepted completion evidence.

## Hosted Schedule Evidence

Hosted Monitoring now emits `hosted-monitoring-schedule-evidence.json` on every
run. For real GitHub `schedule` events only, it also emits
`hosted-monitoring-schedule-completion-evidence.json`, satisfying the
`scheduled_freshness_checks` requirement inside
`production_monitoring_and_alerting`.

This is intentionally partial evidence. Manual workflow dispatches are recorded
as `skipped` and do not produce completion evidence, and the monitoring gate
still needs accepted evidence for `hosted_alert_routing` and
`worker_scheduler_alert_ownership`.

The schedule itself is now checked by a separate public-safe watchdog artifact:

- `docs/reviews/hosted-monitoring-schedule-readiness-2026-07-01.json`
- `docs/reviews/hosted-monitoring-schedule-readiness-2026-07-01.md`

The 2026-07-01 live watchdog run checked the current expected main SHA
`2d86ca32718ae4ef65a8e30c59c84028b0000a1b`. The latest real GitHub
`schedule` event was still run `28493475510`, which failed on older SHA
`9d671d2a4a63ec30ff8a79204b7346304404f15f` and was stale relative to the
90-minute readiness window. No `scheduled_freshness_checks` completion overlay
was produced from that watchdog run.

## Hosted Private Evidence Template Bundle

Hosted Monitoring now also publishes a public-safe private evidence template
bundle. It includes pending manifest templates for:

- `HOSTED_WORKER_EVIDENCE_MANIFEST_B64`
- `HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64`
- `HOSTED_MONITORING_EVIDENCE_MANIFEST_B64`

The bundle does not satisfy any completion gate by itself. Its value is making
the remaining hosted/private evidence path explicit in every monitoring
artifact so operators can fill, review, encode, and set the correct secret
without reconstructing schema requirements from scattered runbooks.

## Current Main Evidence Refresh

After PR #59 merged, hosted deployment and public risk smoke were refreshed for
main merge SHA `e717fde5e157be8c1762730a9b790269112c5cbd`.

Artifacts:

- `docs/reviews/hosted-deployment-smoke-2026-07-01-e717fde.json`
- `docs/reviews/hosted-deployment-completion-evidence-2026-07-01-e717fde.json`
- `docs/reviews/hosted-public-risk-evidence-smoke-2026-07-01-e717fde.json`
- `docs/reviews/hosted-public-risk-completion-evidence-2026-07-01-e717fde.json`
- `docs/reviews/completion-audit-2026-07-01-e717fde.json`
- `docs/reviews/completion-audit-2026-07-01-e717fde.md`

The refreshed completion audit still reports `overall_status: incomplete`.
`production_deployment_evidence` and `public_risk_worker_evidence_path` are
satisfied for this deployed SHA, while the source-family, official
authorization/contract, hosted worker, and monitoring gates remain blocked.

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
  The schedule watchdog currently shows the latest real scheduled run is failed,
  stale, and not on the current main SHA, so even the `scheduled_freshness_checks`
  sub-requirement remains unaccepted for the current deployed SHA.
- `ADMIN_BEARER_TOKEN` and the optional private evidence secrets are not proven
  configured from this local run.
