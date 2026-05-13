# News and Public Web Sources

Phase 2 allows only L2 public web, news, RSS, or public API sources for non-official evidence. L3 forum sources such as PTT and Dcard are Phase 4/V2 work only, default disabled, and cannot satisfy Phase 2 acceptance.

The current `news.public_web.sample` adapter is a fixture-based contract implementation. It does not redistribute full text; normalized evidence stores source URL, timestamp, short summary, source type, location text, confidence, attribution, and tags.

Production source allowlist requirements:

- source is publicly reachable without login, anti-bot bypass, or private tokens;
- terms, robots policy, citation, and cache policy are reviewed;
- ingestion frequency is documented and conservative;
- full article or post text is not exposed by default;
- takedown and disablement path is documented before enabling.

The machine-checkable Phase 2 allowlist is `l2-source-allowlist.yaml`. CI validates that it stays L2-only, excludes forum/social sources, and requires terms/robots review before any production source is enabled by default.

## Historical flood-news backfill

The project must not rely on manually adding one road segment after a user finds a miss. Historical home-buying risk requires a repeatable backfill pipeline:

- query reviewed L2 public-news/search sources for Taiwan flood keywords across multi-year windows;
- keep only metadata, URL, title, timestamp, short summary, extracted location terms, and attribution;
- store raw snapshots before normalization and promotion;
- deduplicate by canonical URL and event time;
- extract road, lane, district, and city terms, then geocode them before promotion to spatial evidence;
- record coverage gaps clearly in the public API so "not imported yet" is never presented as "safe."

`news.public_web.gdelt_backfill` is the first candidate adapter for this shape. It is disabled by default until terms review, source QA, rate limiting, and geocoding promotion are completed.

The backfill query plan is no longer a single-city or single-road list. Worker defaults now cover all 22 Taiwan county/city names, and `app.jobs.taiwan_news_query_plan` can build bounded GDELT query batches from the bundled national village and road open-data geocoder files:

- `villages.normalized.jsonl.gz` from NLSC village boundary centroids for village/neighborhood terms;
- `roads-114.normalized.jsonl.gz` from MOI national road names for road-level terms;
- chunked `sourcecountry:TW` GDELT DOC queries with shared Taiwan flood keywords.

This produces an operator-reviewed nationwide query plan for staged backfill. It still must run behind the same source, terms, cadence, metadata-only, staging, and promotion gates below.

## On-demand enrichment at public API time

The public risk API now has a bounded local-preview enrichment path for Taiwan-wide misses. When accepted DB evidence is empty or only contains flood-potential reference polygons, the API can:

- extract the likely Taiwan location from mixed text such as `2024 高雄岡山嘉新東路 豪雨淹水新聞`;
- derive a nearby village/neighborhood term from bundled national village centroids when the user queried by map click and did not provide text;
- query GDELT DOC ArtList for citation metadata only, using multiple bounded location terms, flood wording variants, and recent plus annual time windows so older events are not hidden by a single broad 10-year query;
- keep only URL, title, timestamp, domain, query metadata, confidence, and query-point geometry;
- compare the candidate title together with public metadata snippets returned by the search index, while still not storing full article text;
- query public news RSS/search metadata sources such as Google News RSS and Bing News RSS/search result feeds before GDELT so a slow or rate-limited single index does not hide available public citations; query ordering now includes older year terms such as 2023 instead of only the most recent one or two years;
- query public wiki/encyclopedia metadata from zh.wikipedia.org and zh.wikinews.org as citation-only fallback when disaster events are documented there but do not appear in ordinary news indexes;
- RSS/search fallback still stores only citation metadata. Exact road matches require road plus administrative context when the road name is common, while broader same-admin-area matches are downgraded to admin-area evidence instead of being treated as precise road evidence;
- upsert accepted metadata into `evidence` through the same `source_id`/`raw_ref` idempotency constraint used by promotion;
- return an explicit `on-demand-public-news` freshness row when the lookup succeeds, returns no results, or is rate-limited.

This path is intentionally not article scraping. It does not store full text, images, comments, or paywalled content. It is a miss-recovery and preview path, not a substitute for scheduled backfill.

Local preview controls:

- `HISTORICAL_NEWS_ON_DEMAND_ENABLED=true`
- `HISTORICAL_NEWS_ON_DEMAND_WRITEBACK_ENABLED=true`
- `HISTORICAL_NEWS_ON_DEMAND_MAX_RECORDS=5`
- `HISTORICAL_NEWS_ON_DEMAND_TIMEOUT_SECONDS=4`

`HISTORICAL_NEWS_ON_DEMAND_MAX_RECORDS` caps returned candidates. The live
lookup may request a larger bounded page from the public index, currently up to
20 records per query, then filters and deduplicates locally before returning the
configured maximum. This improves recall for cases where a real flood article is
present but not ranked in the first few raw search-index results.

Production/staging still requires `SOURCE_NEWS_ENABLED=true` and `SOURCE_TERMS_REVIEW_ACK=true`; `HISTORICAL_NEWS_ON_DEMAND_ENABLED=false` remains the kill switch. Because GDELT may return `429`, user-facing responses must keep the historical gap visible instead of implying safety when enrichment cannot complete.

Current GDELT acceptance boundary:

- candidate enablement requires both `SOURCE_NEWS_ENABLED=true` and `SOURCE_TERMS_REVIEW_ACK=true`; an explicit `WORKER_ENABLED_ADAPTER_KEYS=news.public_web.gdelt_backfill` does not bypass those gates;
- the backfill helper is separately disabled by default and refuses to fetch unless its explicit GDELT source, backfill, news, and terms gates are all true;
- the worker CLI exposes a bounded live-egress rehearsal only through `python -m app.main --rehearse-gdelt-news-backfill --gdelt-start <iso> --gdelt-end <iso>`; missing any gate returns a no-network `skipped` payload;
- the rehearsal gates are `GDELT_SOURCE_ENABLED=true`, `GDELT_BACKFILL_ENABLED=true`, `SOURCE_NEWS_ENABLED=true`, and `SOURCE_TERMS_REVIEW_ACK=true`. These are operator rehearsal controls, not proof that production legal/source approval is complete;
- rehearsal defaults to fetch/normalize `dry-run`; `--gdelt-rehearsal-mode staging-batch` builds an in-memory staging batch but does not persist or promote evidence;
- rehearsal fetches are bounded by explicit start/end timestamps, per-query `maxrecords` default `10` with adapter clamp `250`, and a request cadence default of `60` seconds between queries;
- a separate production-candidate CLI path exists for controlled persistence/promotion testing:
  `python -m app.main --run-gdelt-news-production-candidate --persist --database-url <postgres-url> --gdelt-start <iso> --gdelt-end <iso>`.
  It still uses bounded GDELT DOC egress, injected/mockable fetches in tests, metadata-only staging, and conservative cadence/maxrecords controls. Production-candidate env overrides use `GDELT_PRODUCTION_QUERIES`, `GDELT_PRODUCTION_MAX_RECORDS_PER_QUERY`, and `GDELT_PRODUCTION_CADENCE_SECONDS` rather than the rehearsal env names;
- production-candidate persistence requires the rehearsal/source gates plus `GDELT_PRODUCTION_INGESTION_ENABLED=true`, explicit persist intent, a database URL, `GDELT_PRODUCTION_APPROVAL_EVIDENCE_PATH=<path>`, and `GDELT_PRODUCTION_APPROVAL_EVIDENCE_ACK=true`. ACK cannot replace the concrete external evidence path, and the path cannot replace the human ACK. Missing any gate returns a `skipped` payload with `network_allowed=false`;
- the production-candidate path writes the staging batch, ingestion run summary, and bounded promotion evidence for `news.public_web.gdelt_backfill`. This is engineering evidence that the controlled path can persist and promote; it is not legal/source approval and does not define hosted live cadence;
- tests cover deterministic GDELT DOC URL construction, `maxrecords` clamping to 250, URL-level dedupe, source country/domain/location extraction, metadata-only raw payloads, no normalized full-text redistribution, and rejection of missing titles or invalid dates;
- runtime adapter construction still does not expose a scheduled GDELT live fetch path, so the verified boundary is adapter/backfill preflight, injected-fetcher fixture execution, explicit operator rehearsal, and the gated production-candidate persistence command.

## GDELT live acceptance

True GDELT live ingestion is not complete in this repository. The checked-in
evidence template
`docs/data-sources/news/gdelt-live-acceptance.example.yaml` is intentionally
`production_complete: false` and may contain placeholder owners or references.
It is useful for CI/docs shape checks, but it is not launch evidence.

Validate GDELT live acceptance evidence without network access:

```powershell
python -m app.main --validate-gdelt-live-acceptance ..\..\docs\data-sources\news\gdelt-live-acceptance.example.yaml
```

The command prints JSON with `network_allowed=false`. A complete private
evidence record must provide legal/source approval, source owner, egress owner,
rate-limit policy, cadence seconds at or above the configured minimum, alert
owner and route, production persistence promotion evidence, rollback/kill-switch
reference, and the latest dry-run or production-candidate evidence reference.
When `production_complete: true`, placeholder owners and placeholder evidence
refs are rejected.

Without private approval and promotion evidence outside this repository, do not
claim that true GDELT live ingestion is production complete.

Still pending before production approval:

- legal/source terms approval for GDELT and any downstream publisher citation/cache policy;
- production egress/rate-limit verification and hosted cadence ownership;
- canonical URL and event-time dedupe beyond the adapter batch boundary;
- geocoding QA and promotion rules for extracted Taiwan locations;
- operator runbook, monitoring, alert routing, takedown, and disablement procedure.

## Scheduled backfill to profile refresh contract

Scheduled public-news backfill and public API on-demand enrichment must both feed
the same promotion path before they can affect risk profiles. The contract is:

- backfill fetches metadata-only candidate records from reviewed L2 sources;
- staging stores URL, title, timestamp, short summary, source metadata, query
  metadata, extracted location terms, and attribution, not full article text;
- promotion deduplicates, geocodes, attaches PostGIS geometry or explicit
  uncertainty, and writes accepted evidence;
- profile refresh jobs recompute affected `admin_area_profiles` and
  `risk_grid_profiles` after accepted evidence changes;
- public beta aggregation starts with village/town and H3/geohash profiles,
  using a 2km preview radius or an accepted polygon/buffer rule;
- query heat may raise refresh, backfill, cache-warming, or review priority, but
  must not directly raise realtime, historical, or confidence risk scores.

On-demand enrichment at API time remains a miss-recovery preview. Its writeback
must still pass source gates, metadata-only limits, idempotency, geocoding, and
promotion before profile summaries or public risk levels change.

## Vector-assisted public-news intelligence

Embeddings may be added as an auxiliary intelligence layer for public-news
coverage, but they are not the primary risk store. The allowed uses are:

- near-duplicate clustering across titles, short summaries, and source metadata;
- semantic relevance ranking for flood-related candidate records;
- ambiguous road, village, and town location-text ranking;
- reviewer triage and queue prioritization.

The embedding payload should use title, short summary, source metadata, and
normalized tags only. It must not require raw full article text, comments, images,
or paywalled content. Each embedding record must link back to an evidence or
staging evidence ID, model name/version, created timestamp, and deletion status.

Vector similarity alone cannot create accepted evidence, raise a flood-risk
score, or satisfy a public explanation. A vector-ranked candidate becomes usable
only after it has source URL/metadata, geospatial confidence, and accepted
evidence linkage. Takedown, hiding, or deletion of source evidence must also hide
or delete the associated embedding.
