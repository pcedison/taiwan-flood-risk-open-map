# Risk Scoring

Phase 3 starts with a pure scoring service in `apps/api/app/domain/risk/`. The first version is deliberately simple and fixture-locked:

- `risk-v0.1.0` combines normalized evidence signals into realtime, historical, and confidence levels.
- `risk_factor` lets fixtures represent weak or normal observations without treating every evidence item as equally risky.
- Query heat remains separate and is not an input to risk scoring.
- Missing live rainfall or water-level evidence caps confidence until official adapters are connected end to end.
- Golden fixtures live under `apps/api/tests/fixtures/scoring/` and protect expected public levels.

The current scoring service is a v0 rule baseline, not a scientific hydrology model. Future changes to thresholds, source weights, or public output levels must update golden fixtures and should record a scoring-version change.
