# Phase 4/5 Public Discussion and User Report Gates

Status: draft gate checklist for future Phase 4/5 implementation.

This document turns the legal, privacy, and abuse risks for public discussion
sources and user-submitted reports into acceptance gates. It is intentionally
blocking: PTT, Dcard, generic forum adapters, expanded public-web discussion
collection, and user_report ingestion must remain disabled until the relevant
source row below is reviewed and accepted.

These gates cannot be used to satisfy Phase 2 acceptance. Phase 2 may use only
the existing legally reviewed L2 news/public-web sample path and official
sources. Forum adapters and user reports are Phase 4/5 prerequisites, not
Phase 2 substitutes.

## Global Gates

Every public discussion or user report implementation must satisfy these gates
before development starts:

- [ ] Source owner, URL family, access method, and intended fields are listed in
  the PR description.
- [ ] Legal source review confirms the source can be used for this product
  purpose without login bypass, bot evasion, paywall bypass, anti-scraping
  circumvention, or private-group access.
- [ ] Robots.txt, terms of service, API terms, and community rules are linked
  and reviewed for the exact host, endpoint, or API.
- [ ] Data minimization is explicit: store only URL, timestamp, source type,
  location hints, confidence, short derived summary, and moderation metadata
  unless a later approved checklist row permits more.
- [ ] Raw HTML, full post text, user profile pages, avatars, direct contact
  fields, and private-message content are out of scope.
- [ ] Username handling is specified as no-storage, one-way salted hash, or
  short-lived moderation-only storage with a retention limit.
- [ ] Retention windows are defined for raw snapshots, derived evidence,
  moderation records, audit logs, and deletion tombstones.
- [ ] Moderation workflow exists for false positives, harassment, doxxing,
  self-harm, hate, explicit imagery, and non-flood reports.
- [ ] Abuse prevention covers rate limits, duplicate detection, source-level
  throttling, blocklists, and emergency disable flags.
- [ ] Audit logs record source enablement, source policy changes, moderation
  decisions, deletes, opt-outs, exports, and admin access without storing
  unnecessary personal data.
- [ ] Opt-out/delete handling has an owner, SLA, public contact path, and test
  fixture proving evidence can be hidden or removed by source URL/report ID.
- [ ] UI/API labels identify non-official evidence, source type, timestamp,
  confidence, and moderation state; non-official evidence cannot be the sole
  basis for a high-confidence flood assertion.
- [ ] Feature flags default to disabled in all environments except an explicit
  review sandbox.

Before production launch:

- [ ] A PR reviewer can trace every stored field to this checklist and the
  migration/schema/API contract.
- [ ] Source freshness, error rate, moderation backlog, ingestion volume, and
  opt-out/delete metrics are observable.
- [ ] Load, retry, and backoff behavior proves the implementation will not
  hammer source sites or APIs.
- [ ] Seed/test data contains no real usernames, phone numbers, emails, precise
  home addresses, license plates, or faces unless explicitly synthetic.
- [ ] A dry-run or sandbox ingestion report shows accepted, rejected, redacted,
  and deleted examples.
- [ ] Rollback and source-disable commands are documented and tested.

## Source-Specific Gates

Current forum/social approval manifest:
`docs/data-sources/forum/source-approval-manifest.yaml`.

PTT and Dcard are currently `blocked` / non-accepted. Registry enablement is
still disabled by default, and even an explicit adapter key must be accompanied
by all three gates: `SOURCE_FORUM_ENABLED=true`, the source-specific flag
(`SOURCE_PTT_ENABLED=true` or `SOURCE_DCARD_ENABLED=true`), and
`SOURCE_TERMS_REVIEW_ACK=true`. These flags are only configuration gates; they
do not approve crawling, scraping, HTTP fetching, login bypass, anti-bot
circumvention, raw content storage, or identity storage.

### Public Web / News-Like Public Pages

- [ ] Legal source: page is public without login, scraping ban, paywall bypass,
  or private/closed-group content; RSS, sitemap, official API, or publisher
  permission is preferred.
- [ ] Robots/ToS: robots.txt and ToS allow the selected crawl path and cadence;
  crawl-delay or noindex/nofollow signals are respected.
- [ ] PII/username: do not store article comments, author profile pages, emails,
  phone numbers, faces, or raw bystander details; publisher names and article
  URLs are acceptable attribution fields.
- [ ] Retention: raw fetch snapshots are short-lived and used only for parser
  debugging; derived evidence keeps URL, title/reference, timestamp, summary,
  location hints, and confidence.
- [ ] Moderation: reject pages that are unrelated, rumor-only, copied forum
  dumps, harassment/doxxing, or contain unredacted private-person details.
- [ ] Abuse prevention: domain allowlist, per-domain throttles, backoff on 4xx
  and 5xx, duplicate URL canonicalization, and emergency domain disable.
- [ ] Audit log: source allowlist changes, parser releases, crawl job runs,
  rejection reasons, and delete/opt-out actions are logged.
- [ ] Opt-out/delete: publisher or affected person can request removal by URL;
  deletion hides derived evidence and prevents re-ingestion unless reviewed.

### PTT

- [ ] Legal source: board, access path, and post classes are approved; no login
  bypass, over18 bypass automation, private content, deleted content recovery,
  or anti-bot circumvention.
- [ ] Robots/ToS: PTT host rules, robots.txt, and board norms are reviewed; any
  board that disallows automated collection is excluded.
- [ ] PII/username: do not store username by default. If deduplication needs an
  actor key, use a per-environment salted hash with no public display and a
  defined rotation/deletion path.
- [ ] Retention: raw post snapshots are disabled by default or capped to a
  short debugging window; derived evidence stores URL, board, timestamp,
  location hints, short summary, confidence, and moderation state.
- [ ] Moderation: reject gossip, naming private persons, doxxing, harassment,
  screenshots with visible accounts, and posts without flood relevance.
- [ ] Abuse prevention: board allowlist, crawl throttles, duplicate post
  handling, quote-chain truncation, and immediate adapter disable flag.
- [ ] Audit log: board allowlist changes, crawler configuration, moderation
  decisions, hash-salt rotations, and deletion requests are logged.
- [ ] Opt-out/delete: source URL or hashed actor reference can be suppressed;
  deleted/suppressed posts are not re-promoted.

### Dcard

- [ ] Legal source: use only approved public access paths or official/authorized
  APIs; no login-only forum content, account scraping, hidden comments, or
  anti-bot circumvention.
- [ ] Robots/ToS: Dcard terms, robots.txt, API rules, and rate limits are linked
  and accepted before adapter implementation.
- [ ] PII/username: do not store user IDs, handles, avatars, school/workplace
  profile hints, or comment identities. Keep only source URL, forum/category,
  timestamp, derived summary, and location hints.
- [ ] Retention: raw body/comment data is not retained beyond a short parser
  debug window; derived evidence retention is bounded and removable.
- [ ] Moderation: reject personal disputes, identifiable individuals,
  screenshots, minors, medical/safety speculation, and unrelated local chatter.
- [ ] Abuse prevention: forum allowlist, rate limits, API quota monitoring,
  duplicate URL canonicalization, and adapter kill switch.
- [ ] Audit log: source approval, API credential use, quota breaches, moderation
  actions, and delete/opt-out processing are logged.
- [ ] Opt-out/delete: URL-based suppression is supported, and API-backed deletes
  or content removals are honored on the next sync.

### Generic Forum / Public Discussion Adapter

- [ ] Legal source: each host is individually approved; "forum adapter" is not
  a blanket approval for new domains.
- [ ] Robots/ToS: robots.txt, ToS, API terms, and community rules are reviewed
  per domain before the domain is added to the allowlist.
- [ ] PII/username: default to no username storage. Domain-specific exceptions
  require a checklist update and reviewer approval.
- [ ] Retention: raw content is off or short-lived; derived evidence keeps only
  source URL, host, timestamp, short summary, location hints, confidence, and
  moderation state.
- [ ] Moderation: source-specific false-positive fixtures cover local slang,
  sarcasm, historical flood references, and non-flood water mentions.
- [ ] Abuse prevention: host allowlist, per-host throttles, duplicate detection,
  parser quarantine, and host-level disable.
- [ ] Audit log: domain approval, parser deployment, moderation decision,
  opt-out/delete, and emergency disable events are logged.
- [ ] Opt-out/delete: domain owner or affected person can request removal by URL
  or host; the host can be disabled pending review.

### User Report

- [x] API moderation groundwork: admin-protected pending-list and moderation
  decision endpoints exist for review workflows, with schema-limited statuses
  and reason codes, redacted response fields, audit logging, and
  `USER_REPORTS_ENABLED` still disabled by default.
- [x] Public intake kill switch semantics are explicit:
  `USER_REPORTS_ENABLED=false` blocks public submissions, while
  admin-protected moderation/cleanup endpoints remain available for existing
  records behind `ADMIN_BEARER_TOKEN`.
- [ ] Legal source: reporter consent text explains purpose, public visibility,
  retention, moderation, deletion, and limits of emergency response.
- [ ] Robots/ToS: not applicable to submitted first-party reports, but upload
  provider, map tile, geocoding, CAPTCHA, and notification services must have
  reviewed terms and data-processing behavior.
- [ ] PII/username: anonymous by default. Do not require name, account, email,
  phone, exact home address, or social handle. Strip EXIF and media metadata
  before storage; redact faces, license plates, and private interiors where
  feasible before public display.
- [ ] Retention: separate limits for pending reports, rejected reports,
  approved derived evidence, media, abuse signals, audit logs, and deletion
  tombstones.
- [ ] Moderation: reports stay pending until reviewed or until an approved
  low-risk auto-triage rule marks them low confidence; suspicious reports
  cannot directly become high-weight evidence.
- [ ] Abuse prevention: rate limits by IP/session/device signal, CAPTCHA or
  equivalent challenge, duplicate media/report detection, spam scoring, ban or
  cooldown workflow, and emergency report intake disable flag.
- [ ] Audit log: submission, metadata stripping, moderation decision, media
  redaction, promotion to evidence, admin access, abuse action, and deletion
  are logged.
- [ ] Opt-out/delete: reporter or affected person can request deletion by report
  ID, URL, or approximate submission details; deletion hides media and derived
  evidence while preserving minimal abuse/audit tombstones.
- [ ] Launch blockers remain: CAPTCHA/equivalent challenge, rate limits,
  deletion request workflow, media redaction/EXIF stripping, and media deletion
  must be implemented and reviewed before formal launch.

## Rollback and Disable Conditions

Disable the affected source or feature flag immediately when any of these occur:

- Source ToS, robots.txt, API policy, or permission changes invalidate the
  approved access path.
- Source owner, platform, or affected person sends a credible removal, abuse,
  or automated-access complaint.
- Adapter stores username, raw body, media metadata, precise private location,
  or other PII outside the approved schema.
- Moderation backlog exceeds the documented SLA or high-risk content appears in
  public UI/API.
- Rate limits, crawl delays, or API quotas are repeatedly exceeded.
- Evidence from a public discussion or user report is promoted as the sole basis
  for a high-confidence flood assertion.
- Audit logging, opt-out/delete, or source kill switch is broken.

Rollback acceptance:

- [ ] Feature flag or adapter key is disabled.
- [ ] In-flight jobs are stopped or drained without new fetches/submissions.
- [ ] Public UI/API no longer returns the affected evidence.
- [ ] Previously stored raw or derived records are deleted, hidden, or retained
  only under an approved legal hold.
- [ ] Audit log records who disabled the source, when, why, and what data action
  was taken.
- [ ] Follow-up issue records the fix, reviewer, and re-enable criteria.
