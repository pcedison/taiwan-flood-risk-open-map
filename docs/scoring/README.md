# Risk Scoring

Phase 3 starts with a pure scoring service in `apps/api/app/domain/risk/`. The first version is deliberately simple and fixture-locked:

- `risk-v0.1.0` combines normalized evidence signals into realtime, historical, and confidence levels.
- `risk_factor` lets fixtures represent weak or normal observations without treating every evidence item as equally risky.
- Query heat remains separate and is not an input to risk scoring.
- Missing live rainfall or water-level evidence caps confidence until official adapters are connected end to end.
- Golden fixtures live under `apps/api/tests/fixtures/scoring/` and protect expected public levels.
- The calibration manifest lives at `docs/scoring/risk-calibration-manifest.example.yaml` and is validated by `python infra/scripts/validate_risk_calibration_manifest.py`.

The current scoring service is a v0 rule baseline, not a scientific hydrology model. Future changes to thresholds, source weights, or public output levels must update golden fixtures and should record a scoring-version change.

## Calibration Boundary

The checked-in manifest is `production_complete: false`. It proves scenario
coverage for the baseline fixture set, including high risk, low risk, stale
official realtime data, missing data, and conflicting signals. It does not
claim that weights or thresholds are statistically calibrated.

Production calibration requires private replay evidence from accepted P1-04
`source_launch_gates`. Before changing scoring weights or public thresholds for
production beta, copy the manifest shape into private ops evidence, replace all
fixture-only refs with accepted replay/source refs, clear `coverage_gaps`, set
`production_complete: true`, and run:

```powershell
python infra/scripts/validate_risk_calibration_manifest.py --production-complete <private-manifest.yaml>
```

The full private evidence sequence is summarized in
`docs/runbooks/private-production-evidence-handoff.md`.

## Event Public-Value Smoke

The 2026-06-08 to 2026-06-09 Taiwan Meiyu/southwest-flow heavy-rain event is
tracked as a public-value smoke scenario. It samples 100 deterministic public
search locations across all 22 Taiwan counties/cities and checks two separate
claims:

- `no-network`: the local candidate remains honest when production sources are
  unavailable. It should not present high-concern event areas as confidently low
  risk without evidence.
- `simulated-heavy-rain`: when recent official CWA rainfall and WRA water-level
  signals are present near the query point, the public risk response should
  surface official evidence and produce high realtime risk.

Run:

```powershell
python scripts/event_public_value_smoke.py --sample-size 100 --mode no-network
python scripts/event_public_value_smoke.py --sample-size 100 --mode simulated-heavy-rain
```

When regenerating checked-in review artifacts, add `--generated-at <ISO-8601>`
with a timezone offset so the Markdown timestamp is reproducible.

The generated Markdown reports live in `docs/reviews/`. These smokes prove API
flow, public copy honesty, and official-signal propagation; they do not replace
the private production calibration manifest or accepted source replay evidence.
