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
- `local-source-dispatch-coverage-checklist.json`

This is still not completion evidence: the dispatch templates contain
placeholders, and the coverage checklist intentionally excludes private
evidence refs. Dispatch records must be filled only inside private evidence
handling after actual official dispatch or accepted replies.

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

Follow-up hardening: the schedule completion evidence step now runs after the
hosted deployment smoke, public risk smoke, admin freshness check, private
hosted evidence validation, and local-source follow-up handling. A failing
non-`always()` monitoring check therefore prevents
`hosted-monitoring-schedule-completion-evidence.json` from being emitted for
that run. This keeps `scheduled_freshness_checks` evidence aligned with a
successful scheduled monitor rather than merely with the presence of a
`schedule` event.

The schedule itself is now checked by a separate public-safe watchdog artifact:

- `docs/reviews/hosted-monitoring-schedule-readiness-2026-07-01.json`
- `docs/reviews/hosted-monitoring-schedule-readiness-2026-07-01.md`

The watchdog is also wired into
`.github/workflows/hosted-monitoring-schedule-watchdog.yml`, scheduled at
`17,47 * * * *`. That workflow uses the same public-safe schedule metadata
check and routes failures to
`[hosted-schedule-watchdog] Hosted Monitoring schedule not ready`. This closes
the observability gap where manual Hosted Monitoring runs can pass while the
real GitHub `schedule` path remains failed, stale, or on an older SHA. It still
does not satisfy `scheduled_freshness_checks`; only a recent successful real
Hosted Monitoring `schedule` run on the expected main SHA can emit that
completion evidence.
When a later schedule-readiness watchdog run passes, it now comments on and
closes that same issue automatically, keeping stale GitHub alerts from
lingering after recovery.

The 2026-07-01 live watchdog run checked the current expected main SHA
`2d86ca32718ae4ef65a8e30c59c84028b0000a1b`. The latest real GitHub
`schedule` event was still run `28493475510`, which failed on older SHA
`9d671d2a4a63ec30ff8a79204b7346304404f15f` and was stale relative to the
90-minute readiness window. No `scheduled_freshness_checks` completion overlay
was produced from that watchdog run.

Hosted Monitoring failures now also have a public-safe issue route:
`[hosted-monitoring-alert] Hosted Monitoring failure`. The workflow creates the
issue once and comments on later failures with only the run URL, workflow,
event, and SHA. This is alert-route infrastructure, not accepted completion
evidence; the `hosted_alert_routing` requirement still needs reviewed owner and
evidence refs through the private hosted monitoring manifest.

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

After PR #65 merged, hosted deployment and public risk smoke were refreshed for
main merge SHA `fd3a4598ca8f72f32a0ce768ab3c8a8fb69874f0`.

Artifacts:

- `docs/reviews/hosted-deployment-smoke-2026-07-01-fd3a459.json`
- `docs/reviews/hosted-deployment-completion-evidence-2026-07-01-fd3a459.json`
- `docs/reviews/hosted-public-risk-evidence-smoke-2026-07-01-fd3a459.json`
- `docs/reviews/hosted-public-risk-completion-evidence-2026-07-01-fd3a459.json`
- `docs/reviews/hosted-monitoring-schedule-readiness-2026-07-01-fd3a459.json`
- `docs/reviews/hosted-monitoring-schedule-readiness-2026-07-01-fd3a459.md`
- `docs/reviews/completion-audit-2026-07-01-fd3a459.json`
- `docs/reviews/completion-audit-2026-07-01-fd3a459.md`

The refreshed completion audit still reports `overall_status: incomplete`.
`production_deployment_evidence` and `public_risk_worker_evidence_path` are
satisfied for this deployed SHA, while the source-family, official
authorization/contract, hosted worker, and monitoring gates remain blocked. The
schedule readiness refresh still reports `status: failed`: the latest real
Hosted Monitoring schedule run is failed, stale, and on older SHA
`9d671d2a4a63ec30ff8a79204b7346304404f15f`, so no
`scheduled_freshness_checks` completion evidence was emitted for
`fd3a4598ca8f72f32a0ce768ab3c8a8fb69874f0`.

## Current Main Evidence Refresh After Schedule Watchdog

After PR #67 merged, hosted deployment and public risk smoke were refreshed for
main merge SHA `a2c6e3a6d5f6819a2d3b5c1ffa0805c655eb4838`.

Artifacts:

- `docs/reviews/hosted-deployment-smoke-2026-07-01-a2c6e3a.json`
- `docs/reviews/hosted-deployment-completion-evidence-2026-07-01-a2c6e3a.json`
- `docs/reviews/hosted-public-risk-evidence-smoke-2026-07-01-a2c6e3a.json`
- `docs/reviews/hosted-public-risk-completion-evidence-2026-07-01-a2c6e3a.json`
- `docs/reviews/hosted-monitoring-schedule-readiness-2026-07-01-a2c6e3a.json`
- `docs/reviews/hosted-monitoring-schedule-readiness-2026-07-01-a2c6e3a.md`
- `docs/reviews/completion-audit-2026-07-01-a2c6e3a.json`
- `docs/reviews/completion-audit-2026-07-01-a2c6e3a.md`

The hosted deployment smoke passed for the current Zeabur deployment SHA, and
the public risk evidence smoke passed against the Tainan query-point scenario.
The refreshed completion audit still reports `overall_status: incomplete`:
`production_deployment_evidence` and `public_risk_worker_evidence_path` are
satisfied for this deployed SHA, while the source-family,
official authorization/contract, hosted worker, and monitoring gates remain
blocked.

The schedule readiness refresh still reports `status: failed`. The latest real
Hosted Monitoring `schedule` run is run `28493475510`, failed on older SHA
`9d671d2a4a63ec30ff8a79204b7346304404f15f`, and was stale relative to the
90-minute readiness window when checked. No `scheduled_freshness_checks`
completion evidence was emitted for
`a2c6e3a6d5f6819a2d3b5c1ffa0805c655eb4838`.

## Local Source Dispatch Watchdog

The remaining local-source dispatch work now has its own public-safe watchdog:

- `.github/workflows/local-source-dispatch-watchdog.yml`
- `scripts/local-source-dispatch-watchdog.py`

The workflow refreshes signal-gap discovery, signal-gap dispatch readiness,
source-contract dispatch readiness, and the request packet bundle. It then
produces a `local-source-dispatch-watchdog/v1` JSON/Markdown artifact and, by
default, fails when official dispatch work remains. Failure routes to the stable
issue `[local-source-dispatch-watchdog] Local source dispatch required`.
When a later watchdog run reports no remaining dispatch work, the workflow now
comments on and closes that same issue automatically.

The current local run reports `status: dispatch_required` with 17 signal-gap
county-items, 3 signal-gap groups, 11 metadata-only candidates, 0 live read API
candidates, and 6 source-contract items needing dispatch. This does not satisfy
`required_signal_families` or `official_authorization_and_contracts`; it makes
the remaining official request path visible in GitHub until accepted evidence is
recorded.

## GitHub Actions Secret Readiness Watchdog

The hosted/private evidence secret path now has its own public-safe watchdog:

- `.github/workflows/github-actions-secret-readiness-watchdog.yml`
- `scripts/github-actions-secret-readiness.py`

The workflow writes a presence-only secret input file from GitHub expression
booleans, then emits `github-actions-secret-readiness.json` and `.md` artifacts.
It does not call the Actions secrets-list API, because `GITHUB_TOKEN` cannot
list repository secrets. It fails by default when required secret routes still
block completion gates. Failure routes to the stable issue
`[secret-readiness-watchdog] GitHub Actions required secrets missing`.
When a later watchdog run no longer sees completion-blocking missing inputs,
the workflow now comments on and closes that same issue automatically.

The current local run found 0 of 5 tracked secret inputs configured, 4
required-for-completion secret inputs missing, and 2 completion-gate blockers:

- `hosted_worker_persisted_evidence`: missing `ADMIN_BEARER_TOKEN`,
  `HOSTED_WORKER_EVIDENCE_MANIFEST_B64`, and
  `HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64`.
- `production_monitoring_and_alerting`: missing
  `HOSTED_MONITORING_EVIDENCE_MANIFEST_B64`.

`LOCAL_SOURCE_REQUEST_DISPATCH_EVIDENCE_B64` is also missing, but it is a
follow-up visibility input rather than a direct completion-gate input. This
watchdog does not satisfy any gate; it makes missing hosted/private evidence
inputs visible in GitHub until reviewed manifests and accepted evidence are
provided.

## Hosted Public API Contract Probe

Hosted Monitoring now runs `scripts/public-api-contract-probe.py` before hosted
deployment smoke. This keeps the `public_api_contract_review` portion of
`official_authorization_and_contracts` refreshed even if Zeabur is still serving
an older SHA and the hosted deployment smoke fails.

The current local live probe used `--allow-insecure-tls` to match the existing
operator runbook for these public government pages. The artifact records
`tls_verification=disabled`; no secrets or private refs are used. The 2026-07-01
result remains:

- 3 public API contract-review counties probed: Miaoli, Pingtung, and Taitung.
- 8 candidate URLs probed.
- 0 `candidate_live_read_api` results.
- Miaoli and Taitung remain public HTML contract blockers.
- Pingtung has public HTML plus non-measurement CCTV/context pages.

This does not satisfy `official_authorization_and_contracts`. It prevents the
public API contract-review queue from going stale and will expose a future live
candidate if one appears.

## Current Main Evidence Refresh After Secret Readiness Next Steps

After PR #82 merged, hosted deployment and public risk smoke were refreshed for
main merge SHA `f9d5159ec0c156b2ca302d4e076a3e3310ebf5a5`.

Artifacts:

- `docs/reviews/hosted-deployment-smoke-2026-07-01-f9d5159.json`
- `docs/reviews/hosted-deployment-completion-evidence-2026-07-01-f9d5159.json`
- `docs/reviews/hosted-public-risk-evidence-smoke-2026-07-01-f9d5159.json`
- `docs/reviews/hosted-public-risk-completion-evidence-2026-07-01-f9d5159.json`
- `docs/reviews/hosted-monitoring-schedule-readiness-2026-07-01-f9d5159.json`
- `docs/reviews/hosted-monitoring-schedule-readiness-2026-07-01-f9d5159.md`
- `docs/reviews/completion-audit-2026-07-01-f9d5159.json`
- `docs/reviews/completion-audit-2026-07-01-f9d5159.md`

The hosted deployment smoke passed: `/health` and `/ready` both reported
deployment SHA `f9d5159ec0c156b2ca302d4e076a3e3310ebf5a5`, and `/ready`
reported healthy database and Redis dependencies. The public risk evidence
smoke also passed for the Tainan query-point scenario, with worker-style
official evidence and query-point nearby coverage still present in the public
risk response.

The refreshed completion audit still reports `overall_status: incomplete`.
`production_deployment_evidence` and `public_risk_worker_evidence_path` are
satisfied for this deployed SHA, while the source-family, official
authorization/contract, hosted worker, and monitoring gates remain blocked.

The schedule readiness refresh still reports `status: failed`. The latest real
Hosted Monitoring `schedule` run is run `28504711491`, failed on older SHA
`4ee414807a0230cb44462bdc91f64d39f5b303c9`, and did not execute on
`f9d5159ec0c156b2ca302d4e076a3e3310ebf5a5`. No
`scheduled_freshness_checks` completion evidence was emitted for
`f9d5159ec0c156b2ca302d4e076a3e3310ebf5a5`.

## Local Source Dispatch Next Steps

The local-source dispatch watchdog now writes public-safe `operator_next_steps`
into `local-source-dispatch-watchdog.json`, the Markdown artifact, and the
stable GitHub issue
`[local-source-dispatch-watchdog] Local source dispatch required`.

The next steps tell operators to review the request packet bundle, send the
remaining signal-family read API requests, send the source-contract follow-up
requests, and store reviewed dispatch progress in
`LOCAL_SOURCE_REQUEST_DISPATCH_EVIDENCE_B64` after private review. The issue
route still omits tokens, private evidence refs, manifests, and official
correspondence.

This improves the handoff for the remaining `required_signal_families` and
`official_authorization_and_contracts` work, but it does not satisfy either
gate. Accepted official reply, production adapter, authorization-gated adapter,
or official-unavailable evidence is still required.

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
  sub-requirement remains unaccepted for the current deployed SHA. GitHub Issue
  routing now exists for Hosted Monitoring failures and schedule-watchdog
  failures, but `hosted_alert_routing` remains unaccepted until ownership and
  evidence refs are reviewed.
- `ADMIN_BEARER_TOKEN` and the optional private evidence secrets are not proven
  configured from this local run.
