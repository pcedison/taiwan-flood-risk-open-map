# Public Reports Governance Runbook

Status: pre-launch API and operations groundwork. Keep `USER_REPORTS_ENABLED`
disabled by default until all launch gates are approved.

## Current API Groundwork

- Public report intake is feature-flagged behind `USER_REPORTS_ENABLED`; the
  default remains disabled.
- When intake is enabled, `POST /v1/reports` also applies an API-level
  sliding-window abuse guard before storage. The guard is enabled by default
  through `USER_REPORTS_RATE_LIMIT_ENABLED=true`, uses the shared Redis backend
  by default through `USER_REPORTS_RATE_LIMIT_BACKEND=redis`, and is tuned with
  `USER_REPORTS_RATE_LIMIT_MAX_REQUESTS` and
  `USER_REPORTS_RATE_LIMIT_WINDOW_SECONDS`.
- `USER_REPORTS_RATE_LIMIT_BACKEND=memory` is local/test-only. It must not be
  used for multi-replica production launch because each process has separate
  counters.
- The rate-limit client signal defaults to the request client address. Set
  `USER_REPORTS_RATE_LIMIT_CLIENT_HEADER` only when the deployment has a
  trusted edge proxy that overwrites the configured header; the stored limiter
  key is hashed with `ABUSE_HASH_SALT` when provided.
- Rate-limited submissions return `429 rate_limited` with `Retry-After` and do
  not create user-report or audit rows.
- Public intake now has an API-side bot-defense gate. Set
  `USER_REPORTS_CHALLENGE_REQUIRED=true` to require `challenge_token` on
  `POST /v1/reports`; missing, invalid, or unavailable challenge verification
  rejects before user-report storage is touched. The verifier abstraction
  supports `USER_REPORTS_CHALLENGE_PROVIDER=turnstile` for production-style
  siteverify and `static` for sandbox/test only.
- `USER_REPORTS_ENABLED=false` disables public intake only. Admin moderation
  and cleanup endpoints remain available behind `ADMIN_BEARER_TOKEN` so
  operators can review or close already-stored reports during rollback,
  privacy review, or cleanup.
- Pending user reports can be reviewed through the admin-protected moderation
  API:
  - `GET /admin/v1/reports/pending`
  - `PATCH /admin/v1/reports/{report_id}/moderation`
- Privacy deletion/redaction handling is available through
  `POST /admin/v1/reports/{report_id}/privacy-redaction`. It clears stored
  media references, replaces the submitted summary with a redaction marker,
  tombstones the report as `deleted`, records `redacted_at`/reason metadata,
  and writes an audit event. The response is a minimal tombstone and does not
  expose point, summary, media references, contact fields, or reporter data.
- Admin moderation endpoints require `ADMIN_BEARER_TOKEN`. Missing or invalid
  credentials must not expose report data.
- Pending and moderated admin responses expose only report ID, status, point,
  summary, created timestamp, and reviewed timestamp. They must not expose
  email, media references, raw payloads, private reporter fields, EXIF data, or
  abuse signals.
- Moderation status and reason codes are contract-limited:
  - `approved`: `verified_flood_signal`
  - `rejected`: `duplicate`, `not_flood_related`, `insufficient_detail`,
    `out_of_scope`
  - `spam`: `abuse_or_spam`
- Moderation writes an audit event with the previous status, new status,
  reason code, and admin actor reference.

## Production Launch Evidence

Public reports must remain disabled until a private evidence record passes the
launch validator in production-complete mode. The checked-in template is safe
for CI and docs only:

```powershell
python infra/scripts/validate_public_reports_launch_evidence.py
```

For an external launch decision, copy
`docs/runbooks/public-reports-launch-evidence.example.yaml` to a private ops
location, replace all template owners and refs with real evidence, and run:

```powershell
python infra/scripts/validate_public_reports_launch_evidence.py --production-complete <private-evidence.yaml>
```

Production-complete evidence must include a real launch owner, challenge
provider and secret storage ref, rate-limit policy, abuse salt owner and secret
storage ref, moderation owner/backup/SLA, deletion and redaction procedure,
retention policy, opt-out/takedown path, media/EXIF policy or disabled-media
confirmation, audit-log review, dashboard/alert evidence, and abuse metrics.
Docs-only refs and placeholder owners are intentionally rejected.

## Moderation SLA

Before launch, the moderation owner and backup owner must record the target SLA
in minutes, the queue review evidence, and the escalation path for breaching
that SLA. Backlog alerting must page or notify the named owner before the SLA is
missed, and the launch evidence must reference the tested alert route.

## Deletion and Privacy Flow

Before launch, privacy/governance must approve a procedure that covers direct
report ID requests, approximate submission detail requests, affected-person
requests, media/object cleanup if media is enabled, derived evidence handling,
audit logging, and legal-hold exceptions. The existing admin redaction endpoint
is only one step in that procedure; the production evidence must point to the
reviewed end-to-end workflow.

## Retention and Takedown

Before launch, the retention policy must name how long pending, approved,
rejected, spam, and redacted reports are retained. The opt-out/takedown path
must describe the requester-facing contact path, operator triage owner,
identity or report matching approach, response target, and audit record.

## Media and EXIF Policy

Media must remain disabled unless the evidence record points to a reviewed
media policy that covers EXIF stripping, face/license-plate/private-interior
redaction, storage access, retention, and deletion. If media is disabled, the
launch evidence must include an explicit disabled-media confirmation.

## Operational Measurement

Before launch, operations must verify dashboards and alerts for intake volume,
rate-limit rejections, challenge failures, moderation backlog age, moderation
outcomes, privacy redactions, audit-log writes, and intake disable events. These
measurements are launch evidence, not a substitute for the fail-closed runtime
gates.

## Operator Checklist

Before using the moderation API in a sandbox:

- [ ] Confirm `ADMIN_BEARER_TOKEN` is set only for operators who need admin
  access.
- [ ] Confirm `USER_REPORTS_ENABLED=true` is set only in the reviewed sandbox.
- [ ] If `USER_REPORTS_CHALLENGE_REQUIRED=true`, confirm the provider secret
  and frontend challenge token wiring are configured, then verify missing and
  invalid challenge tokens fail before storage is touched.
- [ ] Confirm the default rate-limit guard is enabled, tune the allowed
  request count/window for the sandbox, and verify a `429 rate_limited`
  response before storage is touched.
- [ ] Verify `GET /admin/v1/reports/pending` returns only redacted fields.
- [ ] Verify invalid moderation status/reason pairs return a clear `400`
  validation error before storage is touched.
- [ ] Verify missing reports return `404`, storage failures return `503`, and
  unauthenticated requests return `401` or `403`.
- [ ] Review the audit log after each moderation smoke test.
- [ ] Exercise `POST /admin/v1/reports/{report_id}/privacy-redaction` for a
  sandbox report and verify the audit log and tombstone response.

## Production Launch Blockers

Do not launch public user reports until these items are complete and reviewed:

- [ ] CAPTCHA or equivalent challenge is reviewed with production provider keys,
  frontend token issuance, and abuse metrics. API-side required gate and
  verifier abstraction are implemented, but review remains a launch blocker.
- [x] API-level rate limiting is implemented and enabled by default for intake.
- [x] Rate limiting is backed by shared Redis infrastructure by default rather
  than per-process memory.
- [ ] Rate limiting metrics and dashboards are observable in production.
- [ ] Complete deletion request handling for report ID lookup, approximate
  submission details, affected-person requests, derived evidence, and media
  object deletion. Admin report tombstoning/redaction and audit logging are
  implemented, but the full request workflow remains a launch blocker.
- [ ] Media ingestion, EXIF stripping, face/license-plate/private-interior
  redaction, and media deletion are implemented or media remains disabled.
- [ ] Reporter consent copy covers purpose, retention, moderation, public
  visibility, deletion path, and emergency-response limits.
- [ ] Moderation SLA, backlog alerts, and emergency intake disable procedures
  are documented and tested.
- [ ] Approved reports cannot become sole high-confidence flood evidence
  without official or otherwise reviewed corroboration.

## Rollback

If private data is exposed, moderation backlog exceeds SLA, audit logging is
broken, abuse spikes, or deletion handling fails:

- [ ] Set `USER_REPORTS_ENABLED=false`.
- [ ] Stop or drain any report promotion jobs.
- [ ] Confirm public APIs no longer expose affected user-report evidence.
- [ ] Hide or delete affected records according to the privacy checklist and
  legal hold status.
- [ ] Record who disabled the feature, when, why, and what data action was
  taken.
