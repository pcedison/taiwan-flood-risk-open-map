# Web Tests

Web tests include Node unit coverage for frontend data-shaping/display helpers
and Playwright E2E smoke coverage for the map-first risk query flow.

Key files:

- `unit/risk-display.test.ts`
- `e2e/map-risk.spec.ts`

Run unit tests with:

```bash
npm test
```

Run the browser smoke suite with:

```bash
npm run e2e
```
