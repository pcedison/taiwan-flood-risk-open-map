# ADR-0012: Redacted Civil IoT fetch diagnostics

- Status: Proposed (local implementation; not deployed)
- Date: 2026-10-21
- Issue: Refs #421

## Context

The 2026-10-21 hosted monitoring incident failed required sewer source health
and freshness and later recovered on the same deployment SHA. Public artifacts
show the failed state but do not contain the failing adapter's fetch exception.
They do not establish a publisher outage or identify the transport/root cause.
Existing Civil IoT transport error messages interpolate arbitrary exception text,
while HTTP failures omit service, attempts, timeout, and pagination progress.

Read-only evidence checked on 2026-10-21:

- [Incident #421](https://github.com/pcedison/taiwan-flood-risk-open-map/issues/421)
  is closed by recovery run `39592878439` at 11:36:24 UTC.
- Artifact `12320527263` (`hosted-monitoring-39543169566`) retains 2,034 sewer
  rows, latest observation `03:54:51Z`, fetch `04:03:21.733874Z`, ingestion
  `04:03:37.619480Z`, and 1,476-second lag. Pump/gate also failed while flood
  sensor remained healthy. These are retained rows, not a successful latest run.
- Latest listed monitoring run `39639843999` (17:00:15 UTC) succeeded on main
  `0a2aa5916ec45cdbe6c873e1c2f531203129d8c8`. No new deployment explains recovery.
- The artifact has no underlying failed fetch exception. No private DB evidence
  was queried. Request/response cause and any correlated infrastructure fault
  remain unknown; no live official-source probing was performed.

## Decision

Keep existing fail-closed ingestion and freshness policy. Record bounded service,
attempt count, timeout, and HTTP status or failure category in Civil IoT fetch
errors. Strip free-form transport reasons and next-link URLs from error messages.
Retain completed-page/source-item counts for fetch failures during pagination.
Use the existing summary/log persistence path without schema changes. Keep retry
limits and request cadence unchanged. Do not publish raw exception tracebacks.

## Consequences

Future worker error summaries can distinguish HTTP, timeout, transport, and JSON
failures and show where pagination stopped. Transport remains a broad category;
private worker evidence may still be needed. Hosted monitoring alone cannot
recover historical fetch exceptions. This diagnoses future failures and fixes
unsafe/incomplete error recording; it does not claim to fix incident #421's
unproven underlying collection fault.
