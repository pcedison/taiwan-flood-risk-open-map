# Tainan City official disaster news

`official.tainan.disaster_news` is an L1, citation-only recovery source for
recent flood incidents that have not yet reached the national spatial history
datasets.

- Owner: Tainan City Government.
- Public index: `https://www.tainan.gov.tw/News.aspx?PageSize=200&n=13370&page=1&sms=9748`.
- Official RSS entry point: `https://www.tainan.gov.tw/OpenData.aspx?SN=24474215983F6554`.
- License: Government Open Data License, version 1.0, with attribution to
  Tainan City Government.
- Stored fields: title, official URL, publication date, and location-match
  metadata only. Article bodies, images, and personal data are not stored.
- Cadence: request-time only when the newest nearby observed flood event is
  more than one year old; the official index payload is cached for ten minutes
  per API process.
- Egress fallback: a small, version-reviewed citation catalog may retain the
  official title, publication date, and URL for a current major incident when
  the official index rejects hosted data-center egress. The 2026-08-24 An-Nan
  flood inspection is the initial bootstrap entry; it expires from lookup after
  the same two-year event window and never includes article body text.
- Spatial rule: a road match may be road-level evidence; a district-only match
  is labelled `admin_area`, has no point distance, and explicitly says it does
  not prove flooding or depth at the queried address.
- Kill switch: `OFFICIAL_TAINAN_HISTORY_NEWS_ENABLED=false`.

The source is historical context only. It cannot change realtime flood status.
