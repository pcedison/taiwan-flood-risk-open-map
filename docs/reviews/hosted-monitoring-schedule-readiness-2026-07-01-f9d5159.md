# Hosted Monitoring Schedule Readiness

- repository: `pcedison/taiwan-flood-risk-open-map`
- workflow: `Hosted Monitoring`
- captured_at: `2026-07-01T10:12:39Z`
- status: `failed`
- expected_head_sha: `f9d5159ec0c156b2ca302d4e076a3e3310ebf5a5`
- latest schedule run found: `True`
- latest conclusion: `failure`
- age_minutes: `91` / max `90`
- completion evidence ready: `False`

## Latest Schedule Run

- run: [28504711491](https://github.com/pcedison/taiwan-flood-risk-open-map/actions/runs/28504711491)
- head_sha: `4ee414807a0230cb44462bdc91f64d39f5b303c9`
- status: `completed`
- conclusion: `failure`
- updated_at: `2026-07-01T08:41:25Z`

## Failures

- `latest_schedule_run_failed`: Latest Hosted Monitoring schedule run did not conclude successfully.
- `latest_schedule_run_wrong_head_sha`: Latest Hosted Monitoring schedule run did not execute on the expected main SHA.
- `latest_schedule_run_stale`: Latest Hosted Monitoring schedule run is older than the accepted freshness window.

This report can only cover `scheduled_freshness_checks`. It does not satisfy hosted alert routing or worker/scheduler ownership.
