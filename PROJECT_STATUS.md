# Taiwan Flood Risk Open Map — Current Project Status

Last verified: 2026-08-31 14:28 Asia/Taipei (06:28 UTC)

This file is the operational handoff for the current repository and production
state. The SDD and work plan remain the product and implementation contracts;
when an older phase checkpoint conflicts with current production evidence, use
the live verification sources listed below.

## Live truth sources

- Canonical repository: <https://github.com/pcedison/taiwan-flood-risk-open-map>
- Main branch: `main`
- Production URL: <https://floodrisk.cc/>
- Deployment identity: `/health` and `/ready` must both report the full current
  `origin/main` SHA.
- Dependency readiness: `/ready` must report healthy PostgreSQL and Redis.
- Source monitoring: `.github/workflows/hosted-monitoring.yml`; a successful
  `workflow_dispatch` is useful diagnosis, but only a real `schedule` run proves
  scheduled operation.
- User-facing acceptance: `scripts/hosted_deployment_smoke.py` plus
  `scripts/hosted_public_risk_evidence_smoke.py --data-source-mode strict`.
- Work queue: open GitHub issues and pull requests. Do not infer completion from
  an old roadmap checkbox.

## Active nationwide data debt plan

- The current engineering correction plan is
  `docs/superpowers/plans/2026-08-31-nationwide-flood-data-debt-remediation.md`.
  It replaces location-by-location history repair as the completion model with
  22-county realtime signal coverage, a 2018–2026 county/year coverage ledger,
  scheduled durable ingestion, DB-only public queries, and production evidence.
- The plan is a read-only audit and implementation contract. Its presence does
  not prove the listed source gates, credentials, backfill, scheduler cadence,
  or production acceptance checks are complete.
- The first implementation slice adds migration `0056`, the fail-closed
  2018–2026 county/year ledger, and public-safe `GET /v1/history-coverage`.
  All 198 cells start as `unassessed`; the schema and endpoint make the work
  visible but do not by themselves backfill events or complete any cell.
- The second PR 1 implementation slice adds `config/source-registry.yaml` as the canonical
  enablement-decision ledger for all worker, API-only, and catalog-only sources.
  CI compares it with the 57 worker adapters, 51 V1 runtime keys, 11 hosted
  deployment defaults, source-contract files, and 58 migrated catalog rows.
  This prevents silent source drift; it does not activate a disabled source.

## Recorded production checkpoint

- Recent-history recovery is no longer a Tainan-only exception. The hosted API
  now applies one nationwide rule to Taiwan query points whose newest observed
  flood history is over 30 days old: search the current and previous six
  calendar years, accept only direct HTTPS Taiwan government citation URLs,
  retain citation metadata rather than article bodies, and label road versus
  administrative-area precision. Google News index URLs are accepted only when
  signed redirect metadata resolves to the direct government page; unresolved
  aggregators remain rejected. Preparedness and drainage-planning pages do not
  pass the observed-event language gate. The canonical district/town is searched
  before road aliases and accepted candidates are sorted newest-first, so an
  exact road query cannot spend its deadline before reaching the recent district
  event. Retained positive official flood-depth observations use the scorer's
  one-kilometre historical support radius. Search coverage is explicitly
  incomplete; no result must never be presented as evidence that flooding did
  not occur.
- A separate `official.wra.flood_incident` adapter can accumulate successive
  all-county latest-event responses into durable cross-year history. It is
  intentionally disabled until the official API credential, contract review,
  and all three runtime gates are present. The upstream `Depth` schema has no
  declared unit, so its raw value is not converted to centimetres.
- Latest functional release verified before this documentation edit:
  `19bbaf6849713594d20dca7dc047af17368ad69d` (PRs
  [#283](https://github.com/pcedison/taiwan-flood-risk-open-map/pull/283) and
  [#284](https://github.com/pcedison/taiwan-flood-risk-open-map/pull/284), built
  on the nationwide historical-evidence work in PRs
  [#279](https://github.com/pcedison/taiwan-flood-risk-open-map/pull/279),
  [#280](https://github.com/pcedison/taiwan-flood-risk-open-map/pull/280), and
  [#281](https://github.com/pcedison/taiwan-flood-risk-open-map/pull/281)).
  This is an auditable historical checkpoint, not a permanent claim about the
  current SHA. Always derive the live expected SHA with `git rev-parse
  origin/main`, then compare it with `/health` and `/ready`.
- At 2026-08-31 14:28 Asia/Taipei, `origin/main`, `/health`, and `/ready` all
  reported that functional-release SHA; PostgreSQL and Redis were healthy. CI
  and CodeQL completed successfully, with no open pull requests.
- Hosted Monitoring run
  [#33293621016](https://github.com/pcedison/taiwan-flood-risk-open-map/actions/runs/33293621016)
  was a real `schedule` event and completed successfully. It closed the resolved
  schedule watchdog issue [#199](https://github.com/pcedison/taiwan-flood-risk-open-map/issues/199).
- The later real-schedule run
  [#33309605618](https://github.com/pcedison/taiwan-flood-risk-open-map/actions/runs/33309605618)
  failed on older SHA `bb9ea482242214790580422743a9e0127ba7f4c9`
  because an NCDR `Cancel`-only snapshot left no current warning row. PRs
  [#265](https://github.com/pcedison/taiwan-flood-risk-open-map/pull/265) and
  [#266](https://github.com/pcedison/taiwan-flood-risk-open-map/pull/266)
  now evaluate CAP active windows and recognize a fully accepted `Cancel`-only
  poll as a successful no-active-warning lifecycle. Diagnostic dispatch
  [#33312524320](https://github.com/pcedison/taiwan-flood-risk-open-map/actions/runs/33312524320)
  passed after deployment and auto-closed the repair issue; it is not recorded
  as a substitute for the next real schedule.
- The subsequent real-schedule Hosted Monitoring run
  [#33359153356](https://github.com/pcedison/taiwan-flood-risk-open-map/actions/runs/33359153356)
  completed successfully on 2026-08-31 13:06 Asia/Taipei against the
  then-current `1dd018ab13755fa077312f57b9cdeb98d4904010` release. This is the
  latest genuine schedule evidence; it supersedes the earlier failed lifecycle
  run without treating a manual dispatch as schedule proof. The later PR #283
  and #284 releases passed CI, CodeQL, deployment-identity smoke, and strict
  public-risk smoke; their next real schedule remains future evidence.
- The next real-schedule Hosted Monitoring run
  [#33396475311](https://github.com/pcedison/taiwan-flood-risk-open-map/actions/runs/33396475311)
  failed on 2026-08-31 21:23 Asia/Taipei because the required
  `official.civil_iot.sewer_water_level` source could not refresh. The official
  Civil IoT SensorThings service returned HTTP 500 and timed out from both the
  hosted worker and an independent public probe; issue
  [#289](https://github.com/pcedison/taiwan-flood-risk-open-map/issues/289)
  tracks the incident. Deployment identity, PostgreSQL, Redis, and strict
  public-risk smoke still passed, but retained sewer rows remain fail-closed
  rather than being represented as current. The Civil IoT client retries one
  transient HTTP 5xx or transport failure; a sustained upstream outage still
  fails freshness monitoring.
- Open pull requests: zero at the checkpoint.
- The deployment-identity smoke and strict hosted public-risk smoke both passed
  against the current deployed SHA.
- Desktop and 390-pixel mobile browser checks against production resolved
  `台南市北區北安路一段` to `23.01655, 120.21063` and returned a complete result:
  current risk `低`, historical context `中`, and three traceable evidence
  sources. Neither viewport had horizontal overflow or browser console errors.
- A browser-driven production query for `臺南市安南區安中路一段` at a 2-kilometre
  radius returned current risk `低`, historical context `極高`, and the recent
  2026-08-24 Tainan City Government flood-inspection record with its official
  source link. Because that record is matched only at `admin_area` precision,
  the UI now shows its distance as `未提供`; the persisted evidence endpoint
  likewise returns a null distance plus the explicit limitation that this is
  not an address-level flood-depth observation.
- A browser-driven production query for `高雄市仁武區` exposed an unreadable
  Google News RSS article URL even though its publisher metadata named an
  official agency. PR #284 now requires the user-facing citation URL itself to
  be a direct approved Taiwan government HTTPS URL. Migration 0055 retained
  previous aggregator-only rows for audit but changed them to `rejected` so
  they cannot appear as public evidence. After deployment, the same query
  exposed only direct `data.gov.tw` links; the historical flood dataset page
  `https://data.gov.tw/dataset/25770` rendered with readable metadata and CSV,
  JSON, and XML resource links in the production browser check.
- PR [#270](https://github.com/pcedison/taiwan-flood-risk-open-map/pull/270)
  prevents a transient failure of one redundant WRA hydrology adapter from
  forcing an otherwise supported query-local result to `未知`. The exception is
  deliberately narrow: an independent healthy/degraded hydrology source and
  usable nearby hydrology coverage must both exist. Rainfall, pipeline-stall,
  jurisdiction, and coverage failures remain fail-closed. Deployment and strict
  public-risk smokes passed on both the functional SHA and the later dependency
  checkpoint.
- Dependabot PR
  [#272](https://github.com/pcedison/taiwan-flood-risk-open-map/pull/272)
  upgraded MapLibre to 6.6.0 and passed the existing unit/E2E checks, but a
  production browser check showed the PMTiles map stuck at `底圖載入中` and
  rendered as a distorted polygon/grid. PR
  [#273](https://github.com/pcedison/taiwan-flood-risk-open-map/pull/273)
  restored the verified MapLibre 5 dependency set; the deployed Taiwan map and
  labels then rendered normally. Major MapLibre and ESLint updates are now
  excluded from automatic Dependabot PRs until an explicit migration review.
  Hosted Monitoring now runs real desktop and mobile browser checks for the
  production basemap transition and a public location query, so this class of
  client-only regression is no longer invisible to HTTP-only smokes.
- The required hosted backbone is CWA rainfall, WRA water level, NCDR CAP, WRA
  IoW flood depth, and Civil IoT sewer water level. Advisory sources remain
  distinguishable from required sources and cannot silently weaken the gate.
  PR [#260](https://github.com/pcedison/taiwan-flood-risk-open-map/pull/260)
  applies that required/advisory distinction consistently to both the direct
  live smoke and the aggregate realtime-source gate while retaining advisory
  failures in serialized diagnostics.
- At 2026-08-30 16:16 Asia/Taipei the public NCDR Atom feed contained 54 flood
  warnings, exceeding the worker's former 50-document default even though the
  official endpoint returned HTTP 200. PR
  [#262](https://github.com/pcedison/taiwan-flood-risk-open-map/pull/262)
  raises the default to the existing hard ceiling of 200 while retaining the
  256 audited-row bound and explicit lower operator limits. After deployment,
  the automatic worker cycle returned NCDR to `healthy` / `operational`, the
  realtime result returned from `未知` to `低`, and the strict hosted public-risk
  smoke passed without a manual ingestion dispatch.
- The Tainan direct flood-sensor adapter is operational. PR
  [#249](https://github.com/pcedison/taiwan-flood-risk-open-map/pull/249)
  preserves the adapter-provided official dataset URL and presents current
  Tainan flood-depth evidence as current evidence instead of substituting a
  generic or historical provenance URL.
- PR [#253](https://github.com/pcedison/taiwan-flood-risk-open-map/pull/253)
  makes the CWA tide adapter select the newest valid observation instead of
  trusting response order. PR
  [#254](https://github.com/pcedison/taiwan-flood-risk-open-map/pull/254)
  aligns worker freshness with the reviewed hourly source cadence. PR
  [#267](https://github.com/pcedison/taiwan-flood-risk-open-map/pull/267)
  applies the same 90-minute fresh threshold to API monitoring and public
  evidence coverage, persists that threshold in source metadata, and labels the
  production catalog row `hourly`.
- PR [#256](https://github.com/pcedison/taiwan-flood-risk-open-map/pull/256)
  distinguishes delayed, incomplete, and regional-only observations instead of
  collapsing every partial state into a generic source error.
- PR [#257](https://github.com/pcedison/taiwan-flood-risk-open-map/pull/257)
  rejects external geocodes that conflict with an explicit Taiwan county or
  district and adds a scheduled hosted canary for the reproduced Tainan-to-
  Taipei error. PR
  [#258](https://github.com/pcedison/taiwan-flood-risk-open-map/pull/258)
  keeps coarse road fallbacks from displaying an unrelated nearby POI name.

The earlier schedule-recovery baseline was
`5f31ff1b317d551ae026fbb8191cdeaada47c3d8` (PR
[#250](https://github.com/pcedison/taiwan-flood-risk-open-map/pull/250)). It is
retained as historical evidence, not a permanent deployment pin. After any
merge, the new full `origin/main` SHA becomes the expected deployment SHA and
the deployment plus strict public-risk smokes must be rerun.

## Remaining open work

Issue [#71](https://github.com/pcedison/taiwan-flood-risk-open-map/issues/71)
is the only open issue at this checkpoint. It no longer represents a broken
central or Tainan ingestion path. Its audited queue contains nine grouped
external items and 21 completion targets:

- 15 county/signal targets: pump or gate status (11), flood depth (3: Lienchiang,
  Penghu, and Taipei), and sewer water level (1: Lienchiang).
- 6 source-contract targets: 2 authorization requests, 1 metadata-release
  monitor, and 3 public API contract reviews.

Request packets are handoff material, not evidence that an official request was
sent. Keep #71 open until each applicable target has an accepted official reply,
a production or authorization-gated adapter, or a reviewed
`official-unavailable` record. Static maps, annual datasets, search snippets,
and invented correspondence are not realtime API evidence and cannot close the
issue.

## Continuation and completion rule

One issue, pull request, deployment, or monitoring run completing does not mean
the project is complete. Continue to reconcile production behavior, monitoring,
documentation, and the open queue. A project-wide follow-up may stop only when:

1. all open items, including external-source contracts, have auditable completion
   evidence or the operator explicitly pauses the work;
2. there are no pending pull requests or unresolved required checks;
3. production reports the current full `origin/main` SHA with healthy
   dependencies; and
4. deployment and strict public-risk smokes pass against that SHA.

## Operator verification

```powershell
git fetch origin --prune
$expectedSha = git rev-parse origin/main
python scripts/hosted_deployment_smoke.py --expected-deployment-sha $expectedSha
python scripts/hosted_public_risk_evidence_smoke.py --data-source-mode strict
gh run list --workflow hosted-monitoring.yml --limit 5
gh pr list --state open
gh issue list --state open
```
