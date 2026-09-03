# Explicit Migration Release

## Purpose

This runbook is the only hosted path for applying Flood Risk schema migrations.
Application containers never migrate on startup. A migration release is a
private, one-off `SERVICE_ROLE=migrate` deployment that is pinned to an exact
database state, target migration, environment, and full application SHA.

Migration SQL is trusted code and can lock or rewrite data. Do not treat green
application CI as database release approval.

## Non-Negotiable Gates

Before `MIGRATION_RELEASE_MODE=apply`:

1. Confirm the target is `staging` or `production-beta` without displaying the
   database URL.
2. Record the full 40-character release SHA and verify its required CI checks.
3. Confirm a fresh backup artifact exists. Production also requires a verified
   provider-managed backup and scratch restore evidence.
4. Stop the scheduler and drain any active ingestion job that writes affected
   tables.
5. Run plan mode against the same database binding and save its output.
6. Confirm the current and target versions exactly match the reviewed release.
7. Run the release on a production-backup staging clone before production.

The history rollout target is `0059 -> 0062`. It must first pass the M4 clone
rehearsal and 48-hour sewer soak. Production apply remains prohibited until
those artifacts are accepted.

## Application Contract

Every API or combined application service must set:

```text
RUN_DATABASE_MIGRATIONS_ON_START=false
```

Leaving the value unset is also non-migrating. Setting it to a truthy value
causes the application entrypoint to stop with a public-safe error; it does not
apply SQL.

## Create the Private Release Job

Create a private service from the same repository, branch, and Docker image as
the release candidate. Do not attach a public domain. Bind it to the target
PostgreSQL service and set:

```text
SERVICE_ROLE=migrate
APP_ENV=staging
DEPLOYMENT_SHA=<full 40-character release SHA>
MIGRATION_RELEASE_MODE=plan
MIGRATION_RELEASE_EXPECTED_CURRENT_VERSION=59
MIGRATION_RELEASE_TARGET_VERSION=62
MIGRATION_LOCK_TIMEOUT_MS=10000
MIGRATION_STATEMENT_TIMEOUT_MS=300000
```

Use `APP_ENV=production-beta` only during M5. `DATABASE_URL` or
`WORKER_DATABASE_URL` must come from the platform binding or secret manager;
never paste it into logs or release notes.

## Plan Mode

Deploy the job with `MIGRATION_RELEASE_MODE=plan`. Plan mode takes the migration
advisory lock, checks the recorded filename/checksum manifest, verifies the
exact current version, and lists pending files through the bounded target. It
does not create the manifest table or execute migration SQL.

For the M4 rollout, the accepted plan is:

```text
current=0059 target=0062 pending=3
Pending: 0060_historical_event_semantics.sql, 0061_staging_snapshot_idempotency.sql, 0062_quarantine_civil_iot_water_resource.sql
```

Any different current version, pending set, checksum drift, or target stops the
release. Investigate it; do not adjust the expected version merely to make the
gate pass.

## Apply Mode

After accepting the plan, set:

```text
MIGRATION_RELEASE_MODE=apply
MIGRATION_RELEASE_ACK=apply:staging:0059->0062:<full 40-character release SHA>
```

For production, the acknowledgement must instead start with
`apply:production-beta:`. The job refuses shortened SHAs, a mismatched
environment, current/target versions, or acknowledgement.

Run exactly one migration job. A PostgreSQL session advisory lock serializes a
mistaken concurrent invocation. Each SQL file and its manifest row commit in
one transaction; already committed earlier files remain recorded if a later
file fails.

## Verification

After apply, change back to plan mode with both expected current and target set
to `62`. Accepted output is:

```text
current=0062 target=0062 pending=0
```

Then record, without credentials:

- environment and full release SHA;
- migration job/deployment ID;
- start/end timestamps and duration per migration from private logs;
- before/after schema version;
- reviewed row-count and null-semantics queries;
- backup and scratch-restore evidence refs;
- scheduler stop/drain and restart evidence;
- API/Web smoke and rollback target.

Delete or pause the one-off job after its private log artifact is stored. Do
not leave it as a continuously restarting service.

## Failure and Rollback

If plan fails, make no database change. If apply fails:

1. Keep scheduler and ingestion stopped.
2. Record which migration versions committed; do not rerun blindly.
3. Keep the application on the last schema-compatible SHA.
4. Prefer a reviewed forward fix. The history migrations are additive and a
   down migration is not the default rollback.
5. Quarantine backfill rows by run/raw reference and rebuild profiles when the
   failure is data-only.
6. Restore only into a replacement or scratch database unless a production
   restore has explicit owner approval.

An application rollback cannot undo a committed database migration.
