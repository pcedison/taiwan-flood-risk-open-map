# Backup and Restore Drill Runbook

## Purpose

This runbook defines a safe backup/restore drill for Flood Risk PostgreSQL and
PostGIS data. The default path is non-destructive and suitable for local or CI
smoke checks.

## Scope

Covered:

- Backup planning checklist.
- `pg_dump` custom-format backup creation.
- Backup archive inspection with `pg_restore --list`.
- Optional PostgreSQL client fallback through Docker.
- Explicit restore verification into a clearly named scratch database only.

Not covered:

- Zeabur managed snapshot automation.
- Object-storage raw snapshot lifecycle cleanup.
- Destructive production restore.

## Safety Rules

- Never restore into the production database during a drill.
- Use a scratch database with a name that clearly includes `scratch`,
  `restore`, or `drill` in the database name itself.
- Do not use `--clean`, `--if-exists`, or `--create` for drill restores.
  The drill script intentionally restores into a pre-created scratch database
  and refuses source and restore URLs that are identical.
- Treat restore as optional when a safe scratch database is not available. In
  that case, complete backup creation plus `pg_restore --list` verification and
  record that scratch restore was skipped.
- Stop scheduler and worker before production rollback or emergency restore.
- Keep raw snapshots immutable during rollback.
- Record every restore drill result in the release or ops notes.

## Dry Run

From the repository root:

```powershell
.\scripts\backup-restore-drill.ps1
```

The default dry-run checks for common tools, prints the planned steps, and does
not connect to any database.

To also verify that the selected client path can start without touching data:

```powershell
.\scripts\backup-restore-drill.ps1 -VerifyClient
```

`-VerifyClient` runs only `pg_dump --version` and `pg_restore --version`.

## PostgreSQL Client Selection

The script defaults to `-ClientMode Auto`:

- Use local `pg_dump` / `pg_restore` when both are installed.
- Fall back to Docker when a local PostgreSQL client is missing and Docker is
  available.

Force either path when you need deterministic behavior:

```powershell
.\scripts\backup-restore-drill.ps1 -ClientMode Local -VerifyClient
.\scripts\backup-restore-drill.ps1 -ClientMode Docker -VerifyClient
```

The Docker path uses `postgis/postgis:16-3.4` by default. Override it with
`-DockerImage` if the source server requires a different compatible client:

```powershell
.\scripts\backup-restore-drill.ps1 `
  -ClientMode Docker `
  -DockerImage "postgis/postgis:16-3.4" `
  -VerifyClient
```

When Docker is used, the backup file's parent directory is mounted at
`/backup`. `pg_restore --list` and scratch restore mount it read-only. Backup
creation mounts it read/write so `pg_dump` can create the archive. If the
database URL points at a database on the host machine, use a Docker-reachable
host such as `host.docker.internal` instead of `localhost`.

## Create a Backup

Set `DATABASE_URL` for the source database, then run:

```powershell
.\scripts\backup-restore-drill.ps1 `
  -DatabaseUrl $env:DATABASE_URL `
  -BackupPath ".\artifacts\backups\flood-risk-drill.dump" `
  -ExecuteBackup
```

This runs `pg_dump --format=custom` and writes the archive to `BackupPath`.
The script creates the backup directory if needed. It does not delete or rotate
older backup files.

To force Dockerized `pg_dump`:

```powershell
.\scripts\backup-restore-drill.ps1 `
  -ClientMode Docker `
  -DatabaseUrl $env:DATABASE_URL `
  -BackupPath ".\artifacts\backups\flood-risk-drill.dump" `
  -ExecuteBackup
```

## Inspect a Backup Archive

```powershell
.\scripts\backup-restore-drill.ps1 `
  -BackupPath ".\artifacts\backups\flood-risk-drill.dump" `
  -InspectBackup
```

This runs `pg_restore --list` and does not connect to a database.

The Docker fallback is safe for archive inspection because the backup directory
is mounted read-only and no database URL is used.

## Restore to Scratch

Restore checks must target a scratch database, not the source database:

```powershell
.\scripts\backup-restore-drill.ps1 `
  -BackupPath ".\artifacts\backups\flood-risk-drill.dump" `
  -RestoreDatabaseUrl $env:RESTORE_DRILL_DATABASE_URL `
  -ExecuteRestoreToScratch `
  -ConfirmScratchRestore
```

The script refuses restore execution unless `-ConfirmScratchRestore` is present
and the restore URL database name includes `scratch`, `restore`, or `drill`.

Scratch restore uses:

- `--single-transaction`
- `--exit-on-error`
- `--no-owner`
- `--no-privileges`

It intentionally does not pass destructive flags such as `--clean` or
`--create`. Provision an empty scratch database first. If the scratch database
is not empty, the restore should fail and roll back instead of partially loading
objects.

To run the same scratch restore through Docker:

```powershell
.\scripts\backup-restore-drill.ps1 `
  -ClientMode Docker `
  -BackupPath ".\artifacts\backups\flood-risk-drill.dump" `
  -RestoreDatabaseUrl $env:RESTORE_DRILL_DATABASE_URL `
  -ExecuteRestoreToScratch `
  -ConfirmScratchRestore
```

If Docker cannot reach the scratch database network, skip restore and complete
the backup plus `pg_restore --list` steps. Record the network limitation in the
drill notes.

## Acceptance Criteria

A successful drill records:

- Backup file path and size.
- Source environment and commit SHA.
- `pg_restore --list` success.
- Scratch restore command success.
- Post-restore smoke query result, when a scratch API environment exists.
- Any skipped services or disabled adapters.

## Private Evidence Attachment

Do not commit hosted backup paths, database URLs, or restore transcripts that
include connection details. Store the drill transcript and artifacts in private
ops storage, then reference them from the private production readiness evidence:

- Set `drill_preflight.backup_restore_ref` to the private backup inspection and
  scratch restore evidence bundle.
- Set the `runbook_drills` entry named `backup restore drill` to
  `result: passed` or `result: succeeded` and include the same private ref in
  `evidence_refs`.
- Include the runtime smoke or post-restore API smoke ref when a scratch API
  environment was available.
- Record skipped restore execution as a blocker; production-complete evidence
  must have no backup restore blockers.

## Incident Restore Outline

Use this only during a real incident:

1. Freeze deploys and record the failing commit.
2. Stop scheduler first, then stop or drain workers.
3. Roll back application services if a known good deployment exists.
4. Prefer forward data fixes when possible.
5. If data restore is required, restore the verified backup into a replacement
   database or a new managed database instance.
6. Point API, worker, and scheduler to the restored database.
7. Run `/health`, `/ready`, runtime smoke, and source freshness checks.
8. Restart scheduler last with exactly one replica.

## CI Smoke

The minimum CI-safe check is:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\backup-restore-drill.ps1
```

This validates the script entrypoint without touching data.
