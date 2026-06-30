# Private Production Evidence Handoff

## Purpose

This handoff turns the remaining ROADMAP `P1-04` and `P2-01` blockers into an
operator checklist. The checked-in repository can validate schemas, local
runtime behavior, and event smokes, but hosted production beta still requires
private evidence that must not be committed here.

Use this document when preparing an ops-controlled evidence bundle for a
production-beta go/no-go review.

## Current Boundary

Repo-local evidence is green:

- `scripts/public-beta-local-gate.ps1` passes and covers the no-secret local
  candidate gate: Docker Compose config, API tests/mypy,
  worker/repository tests, validators, web audit/unit/lint/typecheck/build/E2E,
  unknown-address smoke, event smokes, and the realtime source gate for official
  backbone health plus unresolved 金門/連江 discovery monitoring. Use
  `-SkipRealtimeSourceGate` only for explicitly offline local runs.
- `docs/reviews/roadmap-execution-audit-2026-06-10.md` records the latest
  repo-local acceptance boundary and remaining private evidence blockers.
- `python infra/scripts/validate_production_readiness_evidence.py` passes for
  the checked-in example template.
- `python infra/scripts/validate_risk_calibration_manifest.py` passes for the
  checked-in baseline manifest.
- `python scripts/event_public_value_smoke.py --sample-size 100 --mode no-network`
  passes and proves the local candidate does not present missing evidence as
  confident low risk.
- `python scripts/event_public_value_smoke.py --sample-size 100 --mode simulated-heavy-rain`
  passes and proves recent official CWA/WRA signals propagate to high realtime
  risk and visible public evidence.

These checks do not prove production completeness. They are supporting
artifacts for private source launch and calibration evidence.

## Required Private Artifacts

Store these artifacts in a private ops-controlled location such as
`private-ops://`, `vault://`, `op://`, or the selected internal evidence
system. Do not paste secrets, token previews, private pager routes, production
URLs with embedded credentials, or screenshots that reveal values into this
repository.

| Artifact | Blocks | Source template | Production validator |
|---|---|---|---|
| Production readiness evidence | `P1-04` | `docs/runbooks/production-readiness-evidence.example.yaml` | `python infra/scripts/validate_production_readiness_evidence.py --production-complete <private-evidence.yaml>` |
| Basemap CDN evidence | hosted launch gate | `docs/runbooks/basemap-cdn-evidence.example.yaml` | `python infra/scripts/validate_basemap_cdn_evidence.py --production-complete <private-basemap-evidence.yaml>` |
| Public reports launch evidence, only if reports are enabled | public report gate | `docs/runbooks/public-reports-launch-evidence.example.yaml` | `python infra/scripts/validate_public_reports_launch_evidence.py --production-complete <private-public-reports-evidence.yaml>` |
| Risk calibration manifest | `P2-01` | `docs/scoring/risk-calibration-manifest.example.yaml` | `python infra/scripts/validate_risk_calibration_manifest.py --production-complete <private-calibration.yaml>` |

## Source Launch Gates

The private production readiness evidence must include a `source_launch_gates`
entry for every source category:

- `official.cwa.realtime`
- `official.wra.realtime`
- `official.flood_potential.geojson`
- `news.gdelt`
- `community.forum`
- `public_reports`
- `sample_data`

Enabled sources must be `accepted` or `reviewed` and include private refs for:

- License or terms review.
- Credential storage and rotation review.
- Egress, upstream cadence, and rate-limit review.
- Source health expectations and alert routing.
- Rollback or kill-switch drill.
- Source-specific evidence, such as CWA/WRA/flood-potential import probes or
  GDELT live acceptance evidence.

Deferred or disabled sources must name:

- A real owner.
- The disabled reason.
- The kill switch that keeps the source off.
- The evidence ref that records the deferral decision.

`sample_data` must remain disabled for production-complete readiness.

## Calibration Evidence

The private calibration manifest should reference the accepted `P1-04`
`source_launch_gates` and replace fixture-only refs with production replay or
source evidence. It must:

- Set `production_complete: true`.
- Set `readiness_state: production-complete`.
- Set `calibration_status: calibrated` or `accepted`.
- Clear `coverage_gaps`.
- Cover at least high-risk, low-risk, stale-source, and missing-data scenarios.
- Include accepted source evidence refs for each fixture.
- Record the public decision for keeping or changing `risk-v0.1.0` thresholds.

The 2026-06-08/09 event smoke can be attached as supporting evidence for API
flow and official-signal propagation, but it is not a replacement for private
replay evidence.

## Recommended Review Order

1. Run the local gate on the candidate commit:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\public-beta-local-gate.ps1
   ```

2. Run the public-value event smokes and store their Markdown/JSON outputs as
   supporting evidence:

   ```powershell
   python scripts/event_public_value_smoke.py --sample-size 100 --mode no-network
   python scripts/event_public_value_smoke.py --sample-size 100 --mode simulated-heavy-rain
   ```

   Add `--generated-at <ISO-8601>` with a timezone offset when regenerating a
   checked-in or ops-bundled Markdown artifact that must be reproducible.

3. Fill private production readiness evidence and validate it:

   ```powershell
   python infra/scripts/validate_production_readiness_evidence.py --production-complete <private-evidence.yaml>
   ```

4. Fill and validate private basemap CDN evidence:

   ```powershell
   python infra/scripts/validate_basemap_cdn_evidence.py --production-complete <private-basemap-evidence.yaml>
   ```

5. If public report intake is enabled, fill and validate private report launch
   evidence:

   ```powershell
   python infra/scripts/validate_public_reports_launch_evidence.py --production-complete <private-public-reports-evidence.yaml>
   ```

6. Fill and validate private risk calibration evidence:

   ```powershell
   python infra/scripts/validate_risk_calibration_manifest.py --production-complete <private-calibration.yaml>
   ```

7. Record the go/no-go decision, accepted risks, owner handoff, and next drill
   date in the private ops bundle.

## Local-Source Completion Audit Evidence

Nationwide local-source completion is audited by:

```powershell
python scripts\local-source-completion-audit.py `
  --completion-evidence-json docs\reviews\hosted-deployment-completion-evidence-YYYY-MM-DD-<sha>.json `
  --completion-evidence-json docs\reviews\hosted-public-risk-completion-evidence-YYYY-MM-DD-<sha>.json `
  --completion-evidence-json <private-source-contract-evidence.json> `
  --completion-evidence-json <private-hosted-worker-evidence.json> `
  --completion-evidence-json <private-monitoring-evidence.json> `
  --fail-on-incomplete
```

Repeat `--completion-evidence-json` for each independent evidence bundle. The
CLI merges signal-family, source-contract, and production-gate evidence before
running the audit, so public smoke artifacts and private official replies do
not need to be hand-merged into one JSON file.

The command still prints only aggregate evidence counts and gate status. It
does not echo `evidence_ref` values, and it must remain incomplete until every
required signal family, official contract/authorization item, hosted worker
requirement, monitoring requirement, and public-risk requirement has accepted
evidence.
Accepted production-gate evidence must include both `satisfied_requirements`
and matching `requirement_evidence` entries. Each requirement-level entry needs
its own `evidence_ref` plus `observed_at` for runtime observations or
`reviewed_at` for policy and ownership approvals.

For public/local evidence refs such as
`docs/reviews/hosted-public-risk-evidence-smoke-YYYY-MM-DD-<sha>.json#/risk_assessment/worker_evidence`,
the audit CLI resolves the JSON file, requires `status: passed` when the
artifact has a status field, and verifies the JSON pointer exists. Private refs
such as `private-ops://...` remain opaque indexes to private ops storage and
are not read by the public CLI.

Before asking operators to fill private refs, regenerate the public request
artifacts that describe the remaining official local-source gaps:

```powershell
python scripts\local-source-request-packets.py `
  --format signal-gap-batches-json `
  --output docs\data-sources\local\generated-signal-gap-request-batches.json

python scripts\local-source-request-packets.py `
  --format signal-gap-batches-markdown `
  --output docs\data-sources\local\generated-signal-gap-request-batches.md
```

These generated batch files group unresolved `pump_or_gate_status`,
`flood_depth`, and `sewer_water_level` requirements by signal family. Each
batch starts with `dispatch_status: not_sent` and a `private-ops://` evidence
hint. The public files are safe to commit because they contain only request
metadata, not official replies, tokens, contact transcripts, or screenshots.

After an operator sends a batch request or receives an official answer, record
the real dispatch status, reply reference, and county-level decision in the
private completion evidence bundle. The public audit is accepted only when the
private bundle turns every listed `completion_evidence_targets` entry into an
accepted `signal_family_gap_evidence` item or an accepted official-unavailable
record.

When a batch has been sent but the official reply has not yet been accepted,
generate a private dispatch overlay instead of marking the signal gap complete:

```powershell
python scripts\local-source-request-packets.py `
  --format signal-gap-dispatch-evidence `
  --signal-type flood_depth `
  --dispatch-evidence-ref private-ops://local-source/dispatch/flood-depth-YYYY-MM-DD `
  --dispatched-at 2026-06-30T15:20:00+08:00 `
  --follow-up-due-at 2026-07-07T09:00:00+08:00 `
  --output <private-signal-gap-dispatch-evidence.json>
```

The audit will report `request_dispatched` as dispatch progress, but it will
keep `required_signal_families` incomplete until each county/signal entry is
replaced with `accepted`, `authorization_gated_adapter`,
`production_adapter`, or `official_unavailable` evidence. Do not commit a
filled dispatch overlay; keep it with the private official correspondence or
ticketing record. `--follow-up-due-at` is optional, but including it lets the
audit expose the number of dispatch items with scheduled follow-up and the next
follow-up timestamp without treating the request as accepted evidence.

After official replies, authorization-gated adapter evidence, production
adapter evidence, or official-unavailable decisions are accepted, normalize the
private signal-family manifest into a completion overlay:

```powershell
python scripts\signal_family_evidence.py `
  --manifest-json <private-signal-family-manifest.json> `
  --evidence-output <private-signal-family-evidence.json> `
  --completion-evidence-output <private-signal-family-completion-evidence.json>
```

The manifest schema is `signal-family-evidence-input/v1`. Each
`signal_family_gap_evidence` entry must include `county`, `signal_type`,
accepted `status`, `evidence_ref`, and `reviewed_at`. Accepted completion
statuses are `accepted`, `authorization_gated_adapter`, `production_adapter`,
and `official_unavailable`. `request_dispatched` is intentionally rejected by
this CLI because it is progress evidence, not completion evidence. The CLI
compares the manifest against the current `signal_gap_priority_groups` and
fails closed if any required county/signal entry is missing, pending,
duplicated, or no longer required.

For the `official_authorization_and_contracts` gate, fill a private source
contract manifest with accepted evidence for every current
`authorization_request`, `metadata_release_monitor`, and
`public_api_contract_review` item:

When authorization or contract requests have been sent but the official reply
has not yet been accepted, generate a private source-contract dispatch overlay
instead of marking the gate complete:

```powershell
python scripts\local-source-request-packets.py `
  --format source-contract-dispatch-evidence `
  --dispatch-evidence-ref private-ops://local-source/source-contract-dispatch/YYYY-MM-DD `
  --dispatched-at 2026-06-30T18:10:00+08:00 `
  --follow-up-due-at 2026-07-07T09:00:00+08:00 `
  --output <private-source-contract-dispatch-evidence.json>
```

The audit will report `request_dispatched` as source-contract dispatch
progress, but it will keep `official_authorization_and_contracts` incomplete
until each current county/gate item is replaced with `accepted`, `authorized`,
`contract_verified`, `released`, or `official_unavailable` evidence. Do not
commit a filled dispatch overlay; keep it with the private official
correspondence or ticketing record. `--follow-up-due-at` has the same
non-completion meaning here: it only schedules follow-up visibility in the
audit overlay.

```powershell
python scripts\source_contract_evidence.py `
  --manifest-json <private-source-contract-manifest.json> `
  --evidence-output <private-source-contract-evidence.json> `
  --completion-evidence-output <private-source-contract-completion-evidence.json>
```

The manifest schema is `source-contract-evidence-input/v1`. Each
`source_contract_evidence` entry must include `county`, `gate`, accepted
`status`, `evidence_ref`, and `reviewed_at`. Accepted statuses are
`accepted`, `authorized`, `contract_verified`, `official_unavailable`, and
`released`. The CLI compares the manifest against the current action plan and
fails closed if any required county/gate is missing, pending, duplicated, or no
longer required. Keep filled manifests and normalized outputs private if they
contain official reply refs, contract links, reviewer names, or ticket IDs.

For the `hosted_worker_persisted_evidence` gate, fill a private hosted worker
manifest with verified evidence for all five required requirements:

- `freshness_policy`: verified max-lag policy, evidence ref, and `observed_at`.
- `raw_snapshot_retention_policy`: verified raw snapshot retention days,
  evidence ref, and `reviewed_at`.
- `monitored_scheduler_cadence`: verified scheduler cadence, evidence ref, and
  `observed_at`.
- `hosted_egress_review`: verified hosted egress review, reviewer, evidence
  ref, and `reviewed_at`.
- `worker_persisted_evidence_path`: verified worker-persisted evidence path,
  adapter keys, evidence ref, and `observed_at`.

Then validate and normalize that private manifest into a completion overlay:

```powershell
python scripts\hosted_worker_evidence.py `
  --manifest-json <private-hosted-worker-manifest.json> `
  --evidence-output <private-hosted-worker-evidence.json> `
  --completion-evidence-output <private-hosted-worker-completion-evidence.json>
```

The CLI fails closed: `hosted_worker_persisted_evidence` is accepted only when
`freshness_policy`, `raw_snapshot_retention_policy`,
`monitored_scheduler_cadence`, `hosted_egress_review`, and
`worker_persisted_evidence_path` all have verified status plus requirement
level evidence. The admin-only `hosted_source_freshness_smoke.py` can prove
`freshness_policy` and `worker_persisted_evidence_path`; the private hosted
worker manifest remains the place to record raw snapshot retention, scheduler
cadence, hosted egress review, and any private storage/adapter evidence.
The public-safe smoke defaults to the full hosted realtime backbone
(`official.cwa.rainfall`, `official.cwa.tide_level`, `official.wra.water_level`,
`official.ncdr.cap`, `official.wra_iow.flood_depth`,
`official.civil_iot.flood_sensor`, `official.civil_iot.sewer_water_level`,
`official.civil_iot.pump_water_level`, and
`official.civil_iot.gate_water_level`). Use repeated `--required-adapter-key`
arguments only for a documented, narrower incident or staged rollout check; do
not use a narrowed run as completion evidence for the full hosted worker path.
The local completion audit enforces this for public-safe local
`hosted-source-freshness-smoke/v1` artifacts by rejecting evidence whose
`required_adapter_keys` or `checked_sources` omit any hosted realtime backbone
adapter.

If `hosted_source_freshness_smoke.py` is used for the public-safe admin
freshness and worker-persisted path requirements, operators can keep the
remaining private policy/ops proof in a smaller
`hosted-worker-policy-evidence-input/v1` manifest:

```powershell
python scripts\hosted_worker_policy_evidence.py `
  --manifest-json <private-hosted-worker-policy-manifest.json> `
  --evidence-output <private-hosted-worker-policy-evidence.json> `
  --completion-evidence-output <private-hosted-worker-policy-completion-evidence.json>
```

This policy manifest covers only `raw_snapshot_retention_policy`,
`monitored_scheduler_cadence`, and `hosted_egress_review`. Merge its completion
overlay with the hosted source-freshness overlay in
`local-source-completion-audit.py`; the hosted worker gate is satisfied only
when all five requirement-level evidence entries are present across the merged
overlays.

For the `production_monitoring_and_alerting` gate, fill a private monitoring
manifest with one reviewed evidence block per required requirement:

- `hosted_alert_routing`: verified alert route, owner, evidence ref, and
  `reviewed_at`.
- `scheduled_freshness_checks`: verified hosted freshness monitor or scheduled
  job, cadence, evidence ref, and `observed_at`.
- `worker_scheduler_alert_ownership`: verified worker/scheduler owner, evidence
  ref, and `reviewed_at`.

Then validate and normalize that private manifest into a completion overlay:

```powershell
python scripts\hosted_monitoring_evidence.py `
  --manifest-json <private-monitoring-manifest.json> `
  --evidence-output <private-hosted-monitoring-evidence.json> `
  --completion-evidence-output <private-monitoring-evidence.json>
```

The CLI fails closed: `production_monitoring_and_alerting` is accepted only
when `hosted_alert_routing`, `scheduled_freshness_checks`, and
`worker_scheduler_alert_ownership` all have verified status plus requirement
level evidence. Keep the filled outputs private if they contain routing names,
ticket links, incident channels, or on-call ownership.

## Acceptance Mapping

`P1-04` can move from `In Progress` to `Accepted` only when:

- The private production readiness evidence validates with
  `--production-complete`.
- Every enabled production source has reviewed launch evidence.
- Disabled or deferred sources are explicitly documented and fail closed by
  default.

`P2-01` can move from `In Progress` to `Accepted` only when:

- `P1-04` source evidence is accepted.
- The private calibration manifest validates with `--production-complete`.
- Replay evidence covers the required scenarios and supports the public scoring
  decision.

Until then, the correct public claim is: the local candidate and propagation
architecture are validated, but hosted production-beta readiness remains
blocked on private production evidence.
