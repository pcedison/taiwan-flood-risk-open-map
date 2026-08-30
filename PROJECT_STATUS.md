# Taiwan Flood Risk Open Map — Current Project Status

Last verified: 2026-08-30 16:34 Asia/Taipei (08:34 UTC)

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

## Recorded production checkpoint

- Latest functional release verified before this documentation edit:
  `62ccb2bef63f7c9d263a39bef3781a9864e54497` (PR
  [#262](https://github.com/pcedison/taiwan-flood-risk-open-map/pull/262)).
  This is an auditable historical checkpoint, not a permanent claim about the
  current SHA. Always derive the live expected SHA with `git rev-parse
  origin/main`, then compare it with `/health` and `/ready`.
- At 2026-08-30 16:34 Asia/Taipei, `origin/main`, `/health`, and `/ready` all
  reported that functional-release SHA; PostgreSQL and Redis were healthy. CI
  and CodeQL completed successfully, with no open pull requests.
- Hosted Monitoring run
  [#33293621016](https://github.com/pcedison/taiwan-flood-risk-open-map/actions/runs/33293621016)
  was a real `schedule` event and completed successfully. It closed the resolved
  schedule watchdog issue [#199](https://github.com/pcedison/taiwan-flood-risk-open-map/issues/199).
- Open pull requests: zero at the checkpoint.
- The deployment-identity smoke and strict hosted public-risk smoke both passed
  against the current deployed SHA.
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
  aligns tide freshness with the reviewed hourly source cadence.
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
