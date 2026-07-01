# Hosted Monitoring Schedule Readiness

- repository: `pcedison/taiwan-flood-risk-open-map`
- workflow: `Hosted Monitoring`
- captured_at: `2026-07-01T06:17:26Z`
- status: `failed`
- expected_head_sha: `2d86ca32718ae4ef65a8e30c59c84028b0000a1b`
- latest schedule run found: `True`
- latest conclusion: `failure`
- age_minutes: `110` / max `90`
- completion evidence ready: `False`

## Latest Schedule Run

- run: [28493475510](https://github.com/pcedison/taiwan-flood-risk-open-map/actions/runs/28493475510)
- head_sha: `9d671d2a4a63ec30ff8a79204b7346304404f15f`
- status: `completed`
- conclusion: `failure`
- updated_at: `2026-07-01T04:26:42Z`

## Failures

- `latest_schedule_run_failed`: Latest Hosted Monitoring schedule run did not conclude successfully.
- `latest_schedule_run_wrong_head_sha`: Latest Hosted Monitoring schedule run did not execute on the expected main SHA.
- `latest_schedule_run_stale`: Latest Hosted Monitoring schedule run is older than the accepted freshness window.

This report can only cover `scheduled_freshness_checks`. It does not satisfy hosted alert routing or worker/scheduler ownership.
