# Canonical source registry

`source-registry.yaml` is the single machine-readable decision ledger for every
worker, API-only, and catalog-only flood-data source known to the repository.
It records the reviewed contract, worker runtime scope, worker default,
persisted catalog state, hosted deployment default, and explicit enablement
decision separately.

Being present in the registry is not proof that a source is enabled, fresh, or
complete. In particular, `eligible_default_off`, pending, candidate, blocked,
and superseded decisions remain fail-closed.

Run the static drift gate with:

```powershell
python infra/scripts/validate_source_registry.py
```

After applying migrations, also compare the registry with the real
`data_sources` catalog:

```powershell
python infra/scripts/validate_source_registry.py `
  --catalog-only `
  --database-url $env:DATABASE_URL
```

The validator never prints the database URL. CI runs both modes and fails when
an adapter, V1 scope decision, deployment default, source contract, or catalog
enablement state drifts.
