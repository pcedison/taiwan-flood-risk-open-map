# GDELT Controlled Backfill Approval Evidence - 2026-05-07

Scope: controlled public beta backfill of Taiwan flood-related public news metadata from
the GDELT DOC API.

Operator authorization: the project owner explicitly authorized Codex in this workspace
thread on 2026-05-07 to run a controlled nationwide GDELT/public-news backfill, covering
Taiwan village and road query batches, review/staging, and promotion into the project
database.

Operational safeguards:

- Metadata only: store article title, URL, domain, timestamp, GDELT query metadata, and
  derived geocoder match metadata. Do not store article body, full-text excerpts, or
  redistributed article content.
- Controlled geocoder match: when running the nationwide village/road plan, require
  `--gdelt-require-geocoder-match` so only article titles that match a loaded Taiwan
  village or road term are normalized for promotion.
- Source coverage: generate query terms from the bundled open-data geocoder files for
  NLSC village centroids and MOI national road names.
- Rate limiting: use bounded GDELT DOC requests with an operator-selected cadence of at
  least one second between generated query batches.
- Promotion path: persist through raw snapshot, staging evidence, ingestion run summary,
  and accepted-staging promotion. Do not bypass staging for this controlled run.
- Public beta caveat: this evidence authorizes the controlled beta run. It is not a
  final production-complete legal/source approval record for always-on live ingestion.

Rollback / kill switch:

- Stop the one-off worker process or restart the Zeabur service.
- Remove or disable `GDELT_PRODUCTION_INGESTION_ENABLED`, `GDELT_SOURCE_ENABLED`, or
  `GDELT_BACKFILL_ENABLED` before any future scheduled production ingestion.
- Re-run promotion only after reviewing ingestion summaries and promoted evidence counts.
