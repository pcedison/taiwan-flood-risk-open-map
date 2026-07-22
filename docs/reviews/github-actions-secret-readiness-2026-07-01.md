# GitHub Actions Secret Readiness

- repository: `pcedison/taiwan-flood-risk-open-map`
- captured_at: `2026-07-01T13:59:38.2155572+08:00`
- source: `gh_cli` / `actions`
- Configured tracked secrets: 0/5
- Missing required-for-completion secrets: 4
- Completion gate blockers: 2

## Tracked Secrets

| Secret | Configured | Updated At | Blocks |
|---|---:|---|---|
| `ADMIN_BEARER_TOKEN` | no |  | hosted_worker_persisted_evidence |
| `HOSTED_WORKER_EVIDENCE_MANIFEST_B64` | no |  | hosted_worker_persisted_evidence |
| `HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64` | no |  | hosted_worker_persisted_evidence |
| `HOSTED_MONITORING_EVIDENCE_MANIFEST_B64` | no |  | production_monitoring_and_alerting |
| `LOCAL_SOURCE_REQUEST_DISPATCH_EVIDENCE_B64` | no |  |  |

## Blocked Completion Gates

- `hosted_worker_persisted_evidence`: missing `ADMIN_BEARER_TOKEN`, `HOSTED_WORKER_EVIDENCE_MANIFEST_B64`, `HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64`
- `production_monitoring_and_alerting`: missing `HOSTED_MONITORING_EVIDENCE_MANIFEST_B64`

This artifact records only presence/absence metadata for known secret names. It is not private evidence and does not satisfy completion gates by itself.
