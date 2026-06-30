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
