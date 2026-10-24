# ADR-0014: Preserve safe database readiness failure evidence

- Status: Proposed; local validation only
- Date: 2026-10-24
- Work package: WP-012 monitoring and runbooks
- Tracking: Refs #428

## Context

Natural Hosted Monitoring run 40086949194 observed database readiness failure
while Redis and process liveness remained healthy at release
44f616a0b8f6477abc9041119bca9041949cd43d. Both database readiness and ingestion
readiness discard the underlying failure details when returning public 503
responses. Existing application logs cannot distinguish connection failure,
query failure, schema mismatch and transaction cleanup failure. The incident's
infrastructure root cause has not been established.

## Decision

Use the existing JSON logger to record `database.operation.failed`: operation,
fixed stage name, exception class, validated five-character SQLSTATE or null,
and elapsed milliseconds. Never log exception text, traceback, DSN, hostname,
SQL text/parameters, database content or user query. Keep public responses
generic and preserve all current checks and HTTP statuses. The internal
ingestion wrapper also uses a generic message, retaining its exception cause.

Do not change pool sizing, timeout policy, schema requirements or source
freshness thresholds without evidence identifying a defect there.

## Consequences

New events only exist after an approved deployment; this cannot recover missing
historic evidence or repair an unavailable database. OperationalError without
SQLSTATE cannot distinguish DNS, TLS, authentication and network faults;
provider logs remain necessary. Both readiness paths open fresh connections,
bypassing the API request pool. Pool exhaustion alone therefore does not prove
the cause of simultaneous readiness failures. `connect_timeout=2` bounds
connection establishment, not SQL execution.
