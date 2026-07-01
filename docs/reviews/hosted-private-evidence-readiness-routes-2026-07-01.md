# Hosted Private Evidence Readiness Routes - 2026-07-01

This review records the next Hosted Monitoring readiness improvement after PR
#55. The workflow can now accept a separate
`HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64` secret for the hosted worker policy
requirements instead of requiring every hosted worker requirement to arrive in
one all-in-one manifest.

Generated artifact:

```text
docs/reviews/hosted-private-evidence-readiness-routes-2026-07-01.json
```

Current public-safe result with all relevant environment variables empty:

- `configured_secret_count`: 0
- `missing_secret_count`: 5
- `completion_gate_blocker_count`: 2
- `missing_completion_gate_secret_count`: 4

Route status:

- `hosted_worker_full_manifest`: missing
  `HOSTED_WORKER_EVIDENCE_MANIFEST_B64`.
- `hosted_worker_admin_freshness_plus_policy_manifest`: missing
  `ADMIN_BEARER_TOKEN` and `HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64`.
- `hosted_monitoring_manifest`: missing
  `HOSTED_MONITORING_EVIDENCE_MANIFEST_B64`.

Why this helps:

- Operators can satisfy `hosted_worker_persisted_evidence` through the existing
  full worker manifest route, or through the split route where admin source
  freshness proves `freshness_policy` and `worker_persisted_evidence_path`,
  while worker policy evidence proves `raw_snapshot_retention_policy`,
  `monitored_scheduler_cadence`, and `hosted_egress_review`.
- Hosted Monitoring will upload
  `hosted-worker-policy-evidence.json` and
  `hosted-worker-policy-completion-evidence.json` when the new secret is
  configured and the decoded manifest passes validation.
- The artifact remains public-safe: it records configured/missing state and
  route blockers only; it does not print, decode, hash, or preview secret
  values.

This does not complete the project. The private manifests still need to be
reviewed, stored as GitHub secrets, and proven through Hosted Monitoring before
the completion audit can mark the affected gates satisfied.
