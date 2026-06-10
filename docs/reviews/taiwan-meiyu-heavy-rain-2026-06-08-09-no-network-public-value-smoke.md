# 2026-06-08 to 2026-06-09 Taiwan Heavy-Rain Public-Value Smoke

Generated: `2026-06-10T02:00:00+00:00`

## Event Baseline

- [CWA Rain Warning Product](https://www.cwa.gov.tw/V8/C/P/Warning/W26.html): Official rain-warning product and rainfall warning threshold context for Meiyu fronts and southwest-flow heavy-rain events.
- [PTS 2026-06-08](https://news.pts.org.tw/article/811953): CWA said southern Taiwan had short-duration heavy rain around 40 mm/hr and issued heavy-rain advisories from Chiayi southward; 2026-06-09 front plus stronger southwest flow would raise heavy-rain risk nationwide, especially central/southern mountains.
- [PTS 2026-06-09](https://news.pts.org.tw/article/812170): Stationary front and southwest flow affected Taiwan; CWA heavy-rain advisory highlighted short-duration heavy rain, with local torrential rain or extremely heavy rain possible in Kaohsiung/Pingtung mountain areas.
- [UDN 2026-06-09](https://udn.com/news/story/7266/9554160): Reported CWA advisory counties including Kaohsiung/Pingtung mountain areas and local heavy/torrential rain risk in western Taiwan, Penghu, and Taitung mountains.

## Result

- Mode: `no-network`
- Checked locations: `100`
- Counties covered: `22`
- Geocode successes: `100`
- Risk successes: `100`
- Failure count: `0`
- Warning count: `145`
- Public-value readiness: `local_candidate_honest_but_not_event_complete`

## Takeaways

- Search and assessment API flow works for the sampled Taiwan locations.
- High-concern event areas are not presented as confident low risk without evidence.
- 61 sampled locations lack location-specific evidence in no-network mode; this confirms production source/replay evidence is still required.
- 0 sampled locations do not expose both live CWA/WRA runtime source statuses in this mode; hosted public launch still needs accepted realtime source gates.

## Distribution

- Event focus: `{"core-alert": 35, "high-concern": 35, "nationwide-context": 30}`
- Source mix: `{"admin-area": 3, "road": 68, "shelter": 16, "village": 13}`
- Geocode precision: `{"admin_area": 16, "poi": 16, "road_or_lane": 68}`
- Realtime levels: `{"未知": 100}`
- Source health: `{"cwa-rainfall": {"degraded": 100}, "historical-flood-records": {"healthy": 39, "unknown": 61}, "official-flood-disaster-points": {"degraded": 100}, "on-demand-public-news": {"disabled": 100}, "wra-water-level": {"degraded": 100}}`

## Highest-Signal Warnings

- `68` x geocode precision is road_or_lane; UI must keep confirmation/limitations visible
- `61` x risk response has no location-specific evidence
- `16` x geocode precision is admin_area; UI must keep confirmation/limitations visible

## Failures

- None.

## Evidence Artifact

- Local JSON details, gitignored: `test-results\taiwan-meiyu-heavy-rain-2026-06-08-09-no-network-public-value-smoke.json`
