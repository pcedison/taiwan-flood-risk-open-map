# Official Realtime Source Of Truth

Reviewed: 2026-06-09

Production and production-beta risk assessment must treat worker-promoted official
evidence in Postgres as the source of truth for CWA rainfall and WRA water-level
signals. The API must not depend on unmanaged on-demand official realtime calls
in hosted runtime by default.

## Runtime Policy

- `APP_ENV=local`, `development`, or `test`: on-demand official realtime calls are
  allowed as a diagnostic fallback by default.
- `APP_ENV=staging`, `production-beta`, or `production`: on-demand official
  realtime calls are disabled by default.
- Hosted operators may explicitly enable the diagnostic fallback with
  `REALTIME_OFFICIAL_DIAGNOSTIC_FALLBACK_ENABLED=true` only for controlled
  diagnosis or an accepted launch exception.

## Public Risk Semantics

- Fresh worker-promoted `official` evidence with `event_type=rainfall` contributes
  to realtime scoring and reports `data_freshness.source_id=cwa-rainfall`.
- Fresh worker-promoted `official` evidence with `event_type=water_level`
  contributes to realtime scoring and reports
  `data_freshness.source_id=wra-water-level`.
- If persisted official realtime evidence is stale or missing, the API reports a
  degraded freshness item and the public result must be read as data-limited.
- A degraded or missing realtime source does not mean the queried location is
  safe; it means current official realtime evidence is unavailable or stale.
- Historical evidence, flood-potential evidence, public news, and query heat are
  separate signals. They must not be presented as live rainfall or live water
  level.

## Operator Checks

- Confirm worker adapters for `official.cwa.rainfall` and
  `official.wra.water_level` are enabled only after source readiness approval.
- Confirm promoted evidence appears in the `evidence` table with
  `ingestion_status=accepted`, `privacy_level` of `public` or `aggregated`, and
  current `observed_at` timestamps.
- Confirm API responses include healthy `cwa-rainfall` or `wra-water-level`
  freshness before describing realtime official data as available.

## Hosted Public-Risk Smoke

After each production deploy, run the hosted public-risk evidence smoke to prove
that the public `/v1/risk/assess` response exposes both worker-style official
evidence and query-point nearby coverage:

```powershell
python scripts\hosted_public_risk_evidence_smoke.py `
  --base-url https://floodrisk.cc `
  --lat 23.01929 `
  --lng 120.18726 `
  --radius-m 500 `
  --location-text "Tainan hosted public risk evidence smoke" `
  --evidence-output docs\reviews\hosted-public-risk-evidence-smoke-YYYY-MM-DD-<sha>.json `
  --completion-evidence-output docs\reviews\hosted-public-risk-completion-evidence-YYYY-MM-DD-<sha>.json
```

This smoke checks the public contract only: `data_freshness` for CWA/WRA
official realtime sources, `official` rainfall or water-level evidence with
`observed_at` and `ingested_at`, and a populated
`nearby_realtime_coverage` block. It can satisfy the
`public_risk_worker_evidence_path` completion requirements when the artifact is
accepted, but it does not prove raw snapshot retention, scheduler cadence,
hosted egress approval, or alert routing.
