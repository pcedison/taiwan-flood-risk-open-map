# Forum/social ingestion boundary

PTT and Dcard are not approved live ingestion sources. The checked-in manifest is
an approval boundary and fixture contract, not a crawl allowlist.

Current engineering state:

- Registry keys `ptt` and `dcard` are disabled by default.
- Enabled-key selection requires `SOURCE_FORUM_ENABLED=true`, the source-specific
  flag, `SOURCE_TERMS_REVIEW_ACK=true`, and the source-specific candidate
  approval ack flag documented in `source-approval-manifest.yaml`.
- Runtime live mode does not construct PTT or Dcard adapters.
- Runtime fixture mode may construct candidate adapters after all gates pass, but
  those adapters only normalize synthetic local fixture records.
- Candidate adapters must not fetch HTTP, crawl, scrape, bypass login/anti-bot
  controls, store raw forum content, or store user identity.

Moving either source beyond this boundary requires a reviewed approval request
with accepted terms, privacy, retention, moderation, opt-out, and rate-limit
evidence. Until then, tests may verify only governance metadata and synthetic
fixture-normalized records.
