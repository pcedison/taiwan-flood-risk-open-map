# Flood Risk Contracts

This package holds shared API contract artifacts for agents working on the Flood Risk project.

## Source of truth

- `docs/api/openapi.yaml` is the current OpenAPI 3.1 draft for public and admin API boundaries.
- The draft is derived from `docs/PROJECT_SDD.md` sections 7 Domain Model, 9 Risk Scoring Design, and 10 API Contract Draft.
- `docs/PROJECT_WORK_PLAN.md` A3 Contract skeleton defines the current Definition of Done for this contract pass.

## Contract rules

- Public flood risk levels must be exactly `低`, `中`, `高`, `極高`, and `未知`.
- `query_heat` represents public attention only. It must not directly increase `realtime` or `historical` risk levels.
- Public API responses should include human-readable `explanation`, source `data_freshness`, and evidence references.
- Source and job shapes should stay aligned with the SDD DataSource and Job contract fields.

## Fixtures

Minimal JSON examples live in `packages/contracts/fixtures/`. They are intentionally small and should be used as contract examples or seeds for future contract tests, not as fake production data.

Current fixture:

- `fixtures/risk-assess-response.json`: minimal `/v1/risk/assess` success response using the Traditional Chinese risk labels.

## Validation

From the repository root:

```sh
npx --yes @redocly/cli lint docs/api/openapi.yaml
```

Future backend and frontend contract tests should validate fixture payloads against `docs/api/openapi.yaml` before using them in mocks.
