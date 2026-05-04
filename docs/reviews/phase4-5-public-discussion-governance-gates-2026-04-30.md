# Phase 4/5 Public Discussion Governance Gate Review - 2026-04-30

Branch: `codex/phase2-runtime-demo`

This review artifact is the PR acceptance checklist for future Phase 4/5 public
discussion, forum adapter, and user report work. The canonical policy checklist
is `docs/privacy/public-discussion-user-report-gates.md`.

## Review Boundary

- PTT, Dcard, generic forum/public discussion, expanded public web discussion,
  and user_report ingestion are phase-delayed.
- They cannot be used to satisfy Phase 2 acceptance.
- They are Phase 4/5 prerequisites and must remain disabled until the relevant
  checklist rows are accepted in the implementation PR.
- A placeholder package, empty adapter module, fixture, or sample parser is not
  acceptance evidence unless the legal/privacy gates and disable controls are
  also present.

## PR Reviewer Checklist

For every source or report flow in the PR:

- [ ] The PR links `docs/privacy/public-discussion-user-report-gates.md` and
  identifies the source row being satisfied: public_web, ptt, dcard, forum, or
  user_report.
- [ ] The implementation is default-disabled and can be enabled only by explicit
  config or feature flag.
- [ ] The PR includes source/legal review evidence: source owner, access path,
  robots.txt or ToS/API terms, allowed cadence, and disallowed content.
- [ ] Stored fields match the approved data-minimization list.
- [ ] Username, user ID, handle, avatar, profile, email, phone, precise private
  address, EXIF, and raw full text are absent unless the checklist explicitly
  permits a bounded exception.
- [ ] Retention windows are implemented or blocked by a tracked migration/API
  task before launch.
- [ ] Moderation states and rejection reasons exist before public display.
- [ ] Abuse prevention exists: rate limit, duplicate detection, source throttle,
  suspicious-content quarantine, and kill switch.
- [ ] Audit logs cover enablement, source policy changes, moderation, admin
  access, opt-out/delete, and emergency disable.
- [ ] Opt-out/delete can suppress by URL/report ID and prevents re-promotion.
- [ ] UI/API labels non-official evidence with source type, timestamp,
  confidence, and moderation state.
- [ ] Scoring cannot treat public discussion or user reports as the sole basis
  for a high-confidence flood assertion.
- [ ] Tests include accepted, rejected, redacted, duplicate, opt-out/delete, and
  disabled-source cases.

## Source Rows

| Source | Phase | Must remain disabled until | Minimum reviewer evidence |
|---|---:|---|---|
| public_web | 4 | domain allowlist, robots/ToS review, PII exclusion, retention, moderation, audit, opt-out/delete | reviewed URL family and dry-run summary |
| ptt | 4 | board allowlist, legal/source review, username no-store or hash policy, retention, moderation, abuse controls, audit, opt-out/delete | approved boards and crawl cadence |
| dcard | 4 | authorized public/API access, ToS/API review, no account/profile storage, retention, moderation, abuse controls, audit, opt-out/delete | approved forum/category list and quota policy |
| forum | 4 | per-host legal review, per-host robots/ToS review, no blanket domain approval, retention, moderation, abuse controls, audit, opt-out/delete | host allowlist entry and parser fixture |
| user_report | 5 | consent text, anonymous default, EXIF cleanup, moderation, abuse prevention, audit, opt-out/delete, media retention | submission and moderation test report |

## Development Gate

Before development starts:

- [ ] A source owner and reviewer are named.
- [ ] The source row above has an issue or PR checklist.
- [ ] No production adapter key or public route is enabled by default.
- [ ] Test fixtures are synthetic, licensed, or created from approved samples.
- [ ] Schema/API design shows data minimization and deletion behavior.

## Launch Gate

Before production launch:

- [ ] The global and source-specific gates are all checked.
- [ ] A sandbox/dry-run report shows volume, accepted/rejected examples,
  redaction behavior, delete behavior, and source error behavior.
- [ ] Monitoring covers source freshness, error rates, moderation backlog,
  abuse rate, opt-out/delete requests, and adapter disable state.
- [ ] Runbook documents how to disable the source and remove public evidence.
- [ ] Legal/privacy reviewer and code reviewer both approve the launch PR.

## Rollback / Disable Gate

Disable the source immediately if any condition from the privacy gate document
occurs, including ToS/robots changes, platform complaint, PII leakage, broken
audit/delete flow, moderation SLA breach, quota abuse, or scoring over-reliance.

Rollback is accepted only when:

- [ ] Adapter key or feature flag is disabled.
- [ ] Jobs stop fetching new source data or accepting new reports.
- [ ] UI/API no longer returns affected evidence.
- [ ] Raw and derived records are deleted, hidden, or held only under approved
  legal hold.
- [ ] Audit log records who disabled the source and why.
- [ ] Re-enable criteria are documented in a follow-up issue.

## Remaining Risks

- Final legal review still must happen per source and may reject a source even
  if the technical checklist is complete.
- The exact retention windows need implementation-specific confirmation once
  database tables and object storage paths exist.
- User report media redaction quality depends on the chosen moderation tooling
  and must be tested with synthetic edge cases before launch.
