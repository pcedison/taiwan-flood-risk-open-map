# Public Reports Governance Runbook

Status: pre-launch API and operations groundwork. Keep `USER_REPORTS_ENABLED`
disabled by default until all launch gates are approved.

## Current API Groundwork

- Public report intake is feature-flagged behind `USER_REPORTS_ENABLED`; the
  default remains disabled.
- `USER_REPORTS_ENABLED=false` disables public intake only. Admin moderation
  and cleanup endpoints remain available behind `ADMIN_BEARER_TOKEN` so
  operators can review or close already-stored reports during rollback,
  privacy review, or cleanup.
- Pending user reports can be reviewed through the admin-protected moderation
  API:
  - `GET /admin/v1/reports/pending`
  - `PATCH /admin/v1/reports/{report_id}/moderation`
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

## Operator Checklist

Before using the moderation API in a sandbox:

- [ ] Confirm `ADMIN_BEARER_TOKEN` is set only for operators who need admin
  access.
- [ ] Confirm `USER_REPORTS_ENABLED=true` is set only in the reviewed sandbox.
- [ ] Verify `GET /admin/v1/reports/pending` returns only redacted fields.
- [ ] Verify invalid moderation status/reason pairs return a clear `400`
  validation error before storage is touched.
- [ ] Verify missing reports return `404`, storage failures return `503`, and
  unauthenticated requests return `401` or `403`.
- [ ] Review the audit log after each moderation smoke test.

## Production Launch Blockers

Do not launch public user reports until these items are complete and reviewed:

- [ ] CAPTCHA or equivalent challenge is implemented and reviewed.
- [ ] Rate limiting by IP/session/device signal is implemented and observable.
- [ ] Deletion request handling exists for report ID, approximate submission
  details, affected-person requests, derived evidence, media, and tombstones.
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
