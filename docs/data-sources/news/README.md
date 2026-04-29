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
