# Flood Risk v1 Community Signals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a privacy-preserving community-signal pipeline that uses only the approved Threads official API and approved first-party user reports, corroborates independent origins, applies one bounded community decision seam, prioritizes bounded background searches, and keeps supervised browser discovery quarantined from public risk.

**Architecture:** Community data uses dedicated metadata-only tables and never enters `RawSourceItem`, `raw_snapshots`, `staging_evidence`, generic `evidence`, or `worker_runtime_jobs`. Worker code holds source text only in short-lived memory, persists keyed derived fingerprints and bounded summaries, and produces stable event clusters. The existing two-argument `AssessmentService(repository, scorer)` reads sanitized community records through its repository, persists assessment-to-community associations, and uses one pure uplift seam. Threads live mode requires both environment gates and the database kill switch; browser discovery has a separate exact-schema validator and no signal/event/scoring writer.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, PostgreSQL/PostGIS, psycopg 3, pytest, Ruff, mypy, YAML, Next.js 16, React 19, TypeScript 6, Node test runner, Playwright.

## Global Constraints

- Production community automation is allowed only through an official API, public RSS/Atom/CAP/SensorThings interface, authorized bulk/repository release, written machine-access authorization, or the existing first-party user-report endpoint.
- Threads live mode requires `SOURCE_THREADS_ENABLED`, `SOURCE_THREADS_API_ENABLED`, approved App Review, approved keyword-search permission, a passing real-App contract smoke recorded by `THREADS_API_CONTRACT_VERIFIED`, a secret access token, a secret fingerprint key, and `data_sources.is_enabled=true`; any missing gate disables egress.
- PTT and Dcard remain fixture-only and no-network. This plan adds no PTT/Dcard fetcher, crawler, HTML parser, login, or scraping path.
- Browser Agent work is supervised discovery/verification only: no personal login/session, Cookie, CAPTCHA/anti-bot/paywall/access-control bypass, raw page/body/comments/media storage, or direct event/signal/risk write.
- Social text and tags live only inside one adapter call. Persisted rows, SQL parameters outside the dedicated metadata fields, logs, fixtures derived from real users, API responses, and assessment snapshots contain no identity or raw content.
- A single original community origin never changes realtime, historical, or overall risk.
- Two independent community origins, or one community origin plus a compatible qualifying official anomaly, produce corroboration. Reposts, quotes with the same resolved origin, identical canonical/reference URLs, exact keyed content, and keyed near-duplicate content count once.
- Community never changes realtime or historical. With known official realtime it can raise overall by at most one level across all clusters and never lowers it; the separately approved unknown-realtime rule below takes precedence over a historical-only base.
- Without official confirmation, community-caused overall confidence is capped at `中`.
- When official realtime is `未知` and community is corroborated, realtime remains `未知`; overall is exactly `中`, dominant mode is `community_warning`, and official gaps remain visible. Historical risk remains separately visible and does not replace this current-warning summary.
- Threads permalinks and structured reference objects exist only in short-lived adapter memory; an authenticated suppression URL likewise exists only for that request's in-memory canonicalization/HMAC step. Persist only keyed HMAC identifiers; never persist a URL containing a handle, account name, or post identity.
- `COMMUNITY_DEDUPE_HMAC_KEY` is immutable while any retained Threads signal,
  cluster link, assessment association, or active Threads suppression exists. Store only
  its operator-supplied key ID and one-way SHA-256 fingerprint in both community
  source rows' `data_sources.metadata`; every Threads egress and every new
  user-report promotion fails closed when the configured ID/fingerprint differs.
  Rotation is a fail-closed drain operation with no v1 force flag: an operator
  first disables both community catalog rows, then the command takes the shared
  mutation lock and refuses before deletion if any non-expired or permanent
  Threads suppression exists. With no active suppression, it deletes retained
  community signals, links, cluster links, assessment associations, requests,
  private report links, and expired suppression rows while retaining audit records
  allowed by policy, verifies zero retained derived rows, updates both metadata
  fingerprints, deploys the new secret/ID, and only then permits a separately
  reviewed re-enable. If suppression continuity cannot be proven, both sources
  stay disabled on the old binding. Old- and new-key origins may never coexist.
- Sanitized signals expire no later than 30 days after first ingestion. A shorter reviewed source policy wins, and an idempotent replay never extends first ingestion or retention.
- Suppressed, rejected, deleted, complained-about, false, or expired signals are excluded immediately from clusters, uplift, public evidence, and assessment associations.
- Public assessment never calls Threads or browser work. It performs at most one local database priority upsert after scoring and still returns when community storage is unavailable.
- A priority row anchors only to a server-selected public
  `geocoder_open_data_entries.id`; it never stores the submitted point. The
  worker must resolve that exact anchor and apply `radius_m` with PostGIS
  geography before any location context can match a returned post. Same-named
  roads are never resolved by UUID ordering alone.
- Normal/event cadence defaults to 30/5 minutes, query-triggered work expires in 15 minutes, and event cooldown lasts 2 hours. Source quota and Retry-After may lengthen cadence but never trigger browser fallback.
- Event and cooldown cycles never append nationwide normal-rotation queries.
  Cooldown is the union of every provably cleared official context in the prior
  two hours, not only the most recently cleared event.
- No SSE, WebSocket, continuous client polling, generalized agent platform/crawler/queue, vector store, or raw-content moderation system is added.
- The complete `docs/superpowers/plans/2026-08-24-v1-core-official-baseline.md`
  plan must land and pass its completion gate before Community Task 1 starts.
  In particular, migration/sentinel 0038 must exist before Task 1 creates 0039;
  no community task may later cause the schema sentinel to move backward. Core
  Task 15's Web interface must therefore also exist before Community Task 10.

---

## File and Responsibility Map

### Schema and contracts

- `infra/migrations/0039_v1_community_signals.sql` — six metadata-only tables, exact constraints/indexes, both fail-closed source seeds, and assessment association.
- `tests/test_v1_community_schema.py` — exact table-column allowlists, forbidden-token regression, seed/TTL/kill-switch contract.
- `tests/fixtures/community_fingerprint_vectors.json` — synthetic cross-package HMAC and keyed-LSH vectors; no real post or identity.
- `apps/workers/app/community/contracts.py` — worker-only in-memory raw post plus persistable sanitized/search/cluster DTOs.
- `apps/api/app/domain/community/models.py` — API signal/cluster/snapshot/draft DTOs.

### Worker pipeline

- `apps/workers/app/community/fingerprints.py` — keyed exact-content HMAC and keyed 64-bit locality-sensitive signature.
- `apps/workers/app/community/matching.py` — longest-term flood matching, compatible administrative/location matching, URL canonicalization, template summary.
- `apps/workers/app/community/repository.py` — metadata-only writes, database kill switch, TTL work claiming/recovery, suppression, clusters, retention.
- `apps/workers/app/adapters/threads/keyword_search.py` — strict official Threads bearer-auth client/parser and in-memory adapter.
- `apps/workers/app/community/corroboration.py` — origin equivalence, stable clusters, official compatibility.
- `apps/workers/app/community/search_requests.py` — canonical worklist inputs and bounded in-memory query plans.
- `apps/workers/app/community/scheduler.py` — advisory-lock cycle, successful-request completion, retry/backoff, corroboration, and real adaptive loop.
- `apps/workers/app/cli/community_cli.py` — dedicated community entry point; no generic queue integration.

### API, assessment, and moderation

- `apps/api/app/domain/community/fingerprints.py` — same keyed algorithm, locked by shared synthetic vectors.
- `apps/api/app/domain/community/user_reports.py` — template-only report draft builder.
- `apps/api/app/domain/community/repository.py` — active signal/cluster reads, priority upsert, suppression, association/evidence union helpers.
- `apps/api/app/domain/community/uplift.py` — the only community uplift seam.
- `apps/api/app/domain/reports/repository.py` — one-transaction moderation, signal promotion, and suppression.
- Core assessment repository/service/models/safety — sanitized reads, base overall composition, one uplift call, non-blocking priority upsert, persisted community IDs.

### Public presentation and governance

- `apps/api/app/api/schemas.py`, `apps/api/app/api/services/public_evidence.py`, `apps/api/app/api/routes/admin.py`, `docs/api/openapi.yaml` — sanitized contracts and operator suppression.
- `apps/web/app/lib/page-types.ts`, `apps/web/app/lib/risk-display/*`, `apps/web/app/lib/ui-text.ts`, `apps/web/app/components/*`, `apps/web/app/page.tsx` — authoritative overall/community labels and evidence metadata.
- `docs/data-sources/community/source-policy.yaml`, `docs/data-sources/community/browser-discovery.example.yaml`, `infra/scripts/validate_community_source_policy.py` — exact kind-dispatched allowlists and quarantined discovery.

---

### Task 1: Add Exact Metadata-Only Schema, Seeds, and Contracts

**Files:**

- Create: `infra/migrations/0039_v1_community_signals.sql`
- Create: `tests/test_v1_community_schema.py`
- Create: `tests/fixtures/community_fingerprint_vectors.json`
- Create: `apps/workers/app/community/__init__.py`
- Create: `apps/workers/app/community/contracts.py`
- Create: `apps/api/app/domain/community/__init__.py`
- Create: `apps/api/app/domain/community/models.py`
- Modify: `infra/migrations/README.md`
- Modify: `apps/api/app/api/routes/health.py`
- Modify: `apps/api/tests/test_public_contract.py`

**Interfaces:**

- Consumes: existing `data_sources(adapter_key)`, `risk_assessments(id)`, stable
  UUIDv5 `geocoder_open_data_entries(id)`, and PostGIS.
- Produces: `event_clusters`, `community_signals`, private `community_user_report_links`, `suppressed_sources`, `community_search_requests`, `risk_assessment_community_signals`, worker DTOs, API DTOs, and two disabled source rows.

- [ ] **Step 1: Write exact schema and seed tests**

Use a top-level SQL-entry splitter so constraints cannot be mistaken for columns:

```python
# tests/test_v1_community_schema.py
from __future__ import annotations

import re
from pathlib import Path

MIGRATION = Path("infra/migrations/0039_v1_community_signals.sql")

ALLOWED_COLUMNS = {
    "event_clusters": {
        "id", "cluster_key", "canonical_location", "admin_code", "geom",
        "window_started_at", "window_ended_at", "flood_term_classes",
        "distinct_original_source_count", "official_evidence_ids",
        "corroboration_state", "first_observed_at", "last_observed_at", "updated_at",
    },
    "community_signals": {
        "id", "source_key", "source_url", "canonical_url_hash", "referenced_url_hash",
        "channel", "published_at", "ingested_at", "matched_flood_terms",
        "derived_summary", "canonical_location", "admin_code", "geom",
        "location_precision", "match_basis", "exact_content_hmac", "content_lsh",
        "origin_hmac", "confidence", "moderation_state", "event_cluster_id",
        "retention_expires_at", "created_at", "updated_at",
    },
    "community_user_report_links": {
        "report_id", "community_signal_id", "linked_at",
    },
    "suppressed_sources": {
        "source_key", "canonical_url_hash", "suppression_reason", "suppressed_at", "expires_at",
    },
    "community_search_requests": {
        "normalized_query_key", "anchor_geocoder_entry_id", "county", "district", "road_or_landmark",
        "radius_m", "priority", "requested_at", "expires_at", "status",
    },
    "risk_assessment_community_signals": {
        "risk_assessment_id", "community_signal_id", "relevance_score",
        "corroboration_state", "reason", "created_at",
    },
}

FORBIDDEN_TOKENS = {
    "author", "account", "handle", "user_id", "username", "avatar", "profile",
    "body", "raw_body", "html", "cookie", "screenshot", "media", "contact",
    "private_address", "raw_payload", "raw_ref", "claimed_at", "raw_query", "ip_address",
}


def _split_top_level(value: str) -> list[str]:
    entries: list[str] = []
    start = depth = 0
    for index, character in enumerate(value):
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        elif character == "," and depth == 0:
            entries.append(value[start:index].strip())
            start = index + 1
    entries.append(value[start:].strip())
    return entries


def _columns(sql: str, table: str) -> set[str]:
    match = re.search(
        rf"CREATE TABLE IF NOT EXISTS {table}\s*\((.*?)\n\);",
        sql,
        flags=re.DOTALL,
    )
    assert match is not None
    ignored = {"PRIMARY", "UNIQUE", "CHECK", "CONSTRAINT", "FOREIGN"}
    return {
        entry.split()[0].strip('"')
        for entry in _split_top_level(match.group(1))
        if entry and entry.split()[0].upper() not in ignored
    }


def test_community_tables_have_exact_metadata_only_columns() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert {table: _columns(sql, table) for table in ALLOWED_COLUMNS} == ALLOWED_COLUMNS
    lowered = sql.lower()
    for token in FORBIDDEN_TOKENS:
        assert not re.search(rf"\b{re.escape(token)}\b", lowered)


def test_retention_worklist_and_fail_closed_seeds() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "retention_expires_at <= ingested_at + interval '30 days'" in sql
    assert "expires_at <= requested_at + interval '15 minutes'" in sql
    request_sql = sql.split("CREATE TABLE IF NOT EXISTS community_search_requests", 1)[1].split(";", 1)[0]
    assert "anchor_geocoder_entry_id uuid NOT NULL" in request_sql
    assert " latitude " not in f" {request_sql.lower()} "
    assert " longitude " not in f" {request_sql.lower()} "
    assert " lat " not in f" {request_sql.lower()} "
    assert " lng " not in f" {request_sql.lower()} "
    assert "'social.threads.keyword_search'" in sql
    assert "'community.user_report'" in sql
    assert sql.count("false") >= 2
    assert "is_enabled = false" in sql
    assert "CHECK (source_url IS NULL)" in sql
    assert sql.count("'dedupe_hmac_key_id', NULL") == 2
    assert sql.count("'dedupe_hmac_key_sha256', NULL") == 2
    assert "'COMMUNITY_DEDUPE_HMAC_KEY_ID'" in sql


def test_signal_and_cluster_geometry_typmods_are_point_4326() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    for table in ("event_clusters", "community_signals"):
        body = re.search(
            rf"CREATE TABLE IF NOT EXISTS {table}\s*\((.*?)\n\);",
            sql,
            flags=re.DOTALL,
        )
        assert body is not None
        assert re.search(r"\bgeom\s+geometry\(Point,\s*4326\)\s+NOT NULL\b", body.group(1))
```

- [ ] **Step 2: Run the tests and verify the missing-file failure**

Run: `python -m pytest tests/test_v1_community_schema.py -v`

Expected: FAIL because migration 0039 does not exist.

- [ ] **Step 3: Create the complete migration once; never edit it in later tasks**

```sql
CREATE TABLE IF NOT EXISTS event_clusters (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cluster_key text NOT NULL UNIQUE CHECK (cluster_key ~ '^[0-9a-f]{64}$'),
    canonical_location text NOT NULL CHECK (char_length(canonical_location) BETWEEN 1 AND 300),
    admin_code text CHECK (admin_code IS NULL OR admin_code ~ '^[0-9]{8}$'),
    geom geometry(Point, 4326) NOT NULL,
    window_started_at timestamptz NOT NULL,
    window_ended_at timestamptz NOT NULL,
    flood_term_classes text[] NOT NULL CHECK (cardinality(flood_term_classes) BETWEEN 1 AND 10),
    distinct_original_source_count integer NOT NULL CHECK (distinct_original_source_count >= 0),
    official_evidence_ids uuid[] NOT NULL DEFAULT '{}'::uuid[],
    corroboration_state text NOT NULL CHECK (
        corroboration_state IN ('unverified', 'community_corroborated', 'officially_corroborated')
    ),
    first_observed_at timestamptz NOT NULL,
    last_observed_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (window_ended_at >= window_started_at),
    CHECK (last_observed_at >= first_observed_at)
);

CREATE TABLE IF NOT EXISTS community_signals (
    id text PRIMARY KEY CHECK (id ~ '^[0-9a-f]{64}$'),
    source_key text NOT NULL REFERENCES data_sources(adapter_key) ON DELETE RESTRICT,
    source_url text,
    canonical_url_hash text NOT NULL CHECK (canonical_url_hash ~ '^[0-9a-f]{64}$'),
    referenced_url_hash text CHECK (referenced_url_hash IS NULL OR referenced_url_hash ~ '^[0-9a-f]{64}$'),
    channel text NOT NULL CHECK (channel IN ('threads', 'user_report')),
    published_at timestamptz NOT NULL,
    ingested_at timestamptz NOT NULL,
    matched_flood_terms text[] NOT NULL CHECK (cardinality(matched_flood_terms) BETWEEN 1 AND 10),
    derived_summary text NOT NULL CHECK (char_length(derived_summary) BETWEEN 1 AND 280),
    canonical_location text NOT NULL CHECK (char_length(canonical_location) BETWEEN 1 AND 300),
    admin_code text CHECK (admin_code IS NULL OR admin_code ~ '^[0-9]{8}$'),
    geom geometry(Point, 4326) NOT NULL,
    location_precision text NOT NULL CHECK (
        location_precision IN ('road_or_lane', 'poi', 'admin_area', 'map_click')
    ),
    match_basis text[] NOT NULL CHECK (
        cardinality(match_basis) BETWEEN 1 AND 7
        AND match_basis <@ ARRAY[
            'flood_term', 'tag', 'county', 'district', 'road', 'landmark', 'map_click'
        ]::text[]
    ),
    exact_content_hmac text NOT NULL CHECK (exact_content_hmac ~ '^[0-9a-f]{64}$'),
    content_lsh text NOT NULL CHECK (content_lsh ~ '^[0-9a-f]{16}$'),
    origin_hmac text NOT NULL CHECK (origin_hmac ~ '^[0-9a-f]{64}$'),
    confidence numeric(6, 3) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    moderation_state text NOT NULL CHECK (
        moderation_state IN ('unverified', 'accepted', 'rejected', 'suppressed')
    ),
    event_cluster_id uuid REFERENCES event_clusters(id) ON DELETE SET NULL,
    retention_expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_key, canonical_url_hash),
    CHECK (retention_expires_at > ingested_at),
    CHECK (retention_expires_at <= ingested_at + interval '30 days'),
    CHECK (source_url IS NULL)
);

CREATE TABLE IF NOT EXISTS community_user_report_links (
    report_id uuid PRIMARY KEY REFERENCES user_reports(id) ON DELETE CASCADE,
    community_signal_id text NOT NULL UNIQUE
        REFERENCES community_signals(id) ON DELETE CASCADE,
    linked_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS suppressed_sources (
    source_key text NOT NULL REFERENCES data_sources(adapter_key) ON DELETE RESTRICT,
    canonical_url_hash text NOT NULL CHECK (canonical_url_hash ~ '^[0-9a-f]{64}$'),
    suppression_reason text NOT NULL CHECK (char_length(suppression_reason) BETWEEN 1 AND 120),
    suppressed_at timestamptz NOT NULL,
    expires_at timestamptz,
    PRIMARY KEY (source_key, canonical_url_hash),
    CHECK (expires_at IS NULL OR expires_at > suppressed_at)
);

CREATE TABLE IF NOT EXISTS community_search_requests (
    normalized_query_key text PRIMARY KEY CHECK (normalized_query_key ~ '^[0-9a-f]{64}$'),
    anchor_geocoder_entry_id uuid NOT NULL CHECK (
        substring(anchor_geocoder_entry_id::text from 15 for 1) = '5'
    ),
    county text CHECK (county IS NULL OR char_length(county) BETWEEN 1 AND 20),
    district text CHECK (district IS NULL OR char_length(district) BETWEEN 1 AND 30),
    road_or_landmark text CHECK (road_or_landmark IS NULL OR char_length(road_or_landmark) BETWEEN 1 AND 100),
    radius_m integer NOT NULL CHECK (radius_m BETWEEN 50 AND 2000),
    priority integer NOT NULL CHECK (priority BETWEEN 1 AND 100),
    requested_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    status text NOT NULL CHECK (status IN ('pending', 'claimed')),
    CHECK (county IS NOT NULL OR district IS NOT NULL OR road_or_landmark IS NOT NULL),
    CHECK (expires_at > requested_at),
    CHECK (expires_at <= requested_at + interval '15 minutes')
);

CREATE TABLE IF NOT EXISTS risk_assessment_community_signals (
    risk_assessment_id uuid NOT NULL REFERENCES risk_assessments(id) ON DELETE CASCADE,
    community_signal_id text NOT NULL REFERENCES community_signals(id) ON DELETE CASCADE,
    relevance_score numeric(6, 3) NOT NULL CHECK (relevance_score BETWEEN 0 AND 1),
    corroboration_state text NOT NULL CHECK (
        corroboration_state IN (
            'unverified', 'community_corroborated', 'officially_corroborated'
        )
    ),
    reason text NOT NULL CHECK (char_length(reason) BETWEEN 1 AND 120),
    created_at timestamptz NOT NULL,
    PRIMARY KEY (risk_assessment_id, community_signal_id)
);

CREATE INDEX IF NOT EXISTS idx_community_signals_geom_active
    ON community_signals USING gist (geom)
    WHERE moderation_state IN ('unverified', 'accepted');
CREATE INDEX IF NOT EXISTS idx_community_signals_active_time
    ON community_signals (published_at DESC, retention_expires_at);
CREATE INDEX IF NOT EXISTS idx_event_clusters_geom ON event_clusters USING gist (geom);
CREATE INDEX IF NOT EXISTS idx_community_search_pending
    ON community_search_requests (priority DESC, requested_at ASC)
    WHERE status = 'pending';

INSERT INTO data_sources (
    name, adapter_key, source_type, license, update_frequency,
    health_status, legal_basis, is_enabled, metadata
)
VALUES
    (
        'Threads keyword search API', 'social.threads.keyword_search', 'social',
        'Meta platform terms and approved app permissions', 'adaptive',
        'disabled', 'L3', false,
        jsonb_build_object(
            'access_mode', 'official_api',
            'review_status', 'requires_app_review_and_keyword_permission',
            'required_gates', jsonb_build_array(
                'SOURCE_THREADS_ENABLED', 'SOURCE_THREADS_API_ENABLED',
                'THREADS_APP_REVIEW_APPROVED',
                'THREADS_KEYWORD_SEARCH_PERMISSION_APPROVED',
                'THREADS_API_CONTRACT_VERIFIED',
                'THREADS_ACCESS_TOKEN', 'COMMUNITY_DEDUPE_HMAC_KEY_ID',
                'COMMUNITY_DEDUPE_HMAC_KEY'
            ),
            'dedupe_hmac_key_id', NULL,
            'dedupe_hmac_key_sha256', NULL,
            'retention_days', 30,
            'raw_content_storage', false,
            'identity_storage', false,
            'config_version', 'v1-community-2026-08-24'
        )
    ),
    (
        'Approved first-party user reports', 'community.user_report', 'user_report',
        'First-party report privacy and moderation policy', 'on_approved_report',
        'disabled', 'L4', false,
        jsonb_build_object(
            'access_mode', 'first_party_user_report',
            'review_status', 'requires_user_report_and_moderation_gates',
            'required_gates', jsonb_build_array(
                'USER_REPORTS_ENABLED', 'COMMUNITY_DEDUPE_HMAC_KEY_ID',
                'COMMUNITY_DEDUPE_HMAC_KEY'
            ),
            'dedupe_hmac_key_id', NULL,
            'dedupe_hmac_key_sha256', NULL,
            'retention_days', 30,
            'raw_content_storage', false,
            'identity_storage', false,
            'config_version', 'v1-community-2026-08-24'
        )
    )
ON CONFLICT (adapter_key) DO UPDATE SET
    name = EXCLUDED.name,
    source_type = EXCLUDED.source_type,
    license = EXCLUDED.license,
    update_frequency = EXCLUDED.update_frequency,
    health_status = 'disabled',
    legal_basis = EXCLUDED.legal_basis,
    is_enabled = false,
    metadata = data_sources.metadata || EXCLUDED.metadata,
    updated_at = now();
```

- [ ] **Step 4: Add complete worker contracts**

```python
# apps/workers/app/community/contracts.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

LocationPrecision = Literal["road_or_lane", "poi", "admin_area", "map_click"]
ModerationState = Literal["unverified", "accepted", "rejected", "suppressed"]
CorroborationState = Literal[
    "unverified", "community_corroborated", "officially_corroborated"
]


@dataclass(frozen=True, repr=False)
class RawCommunityPost:
    source_key: str
    source_id: str
    permalink: str
    text: str
    published_at: datetime
    tags: tuple[str, ...]
    is_quote_post: bool
    referenced_source_id: str | None = None
    referenced_url: str | None = None


@dataclass(frozen=True)
class LocationContext:
    canonical_location: str
    admin_code: str | None
    county: str | None
    district: str | None
    road_or_landmark: str | None
    aliases: tuple[str, ...]
    lat: float
    lng: float
    precision: LocationPrecision


@dataclass(frozen=True)
class CommunitySignalCandidate:
    id: str
    source_key: str
    source_url: str | None
    canonical_url_hash: str
    referenced_url_hash: str | None
    channel: Literal["threads", "user_report"]
    published_at: datetime
    ingested_at: datetime
    matched_flood_terms: tuple[str, ...]
    derived_summary: str
    canonical_location: str
    admin_code: str | None
    lat: float
    lng: float
    location_precision: LocationPrecision
    match_basis: tuple[str, ...]
    exact_content_hmac: str
    content_lsh: str
    origin_hmac: str
    confidence: float
    moderation_state: Literal["unverified", "accepted"]
    retention_expires_at: datetime


@dataclass(frozen=True)
class CommunitySearchRequest:
    normalized_query_key: str
    anchor_geocoder_entry_id: UUID
    county: str | None
    district: str | None
    road_or_landmark: str | None
    radius_m: int
    priority: int
    requested_at: datetime
    expires_at: datetime
```

- [ ] **Step 5: Add complete API models**

```python
# apps/api/app/domain/community/models.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

CommunityState = Literal[
    "none", "unverified", "community_corroborated", "officially_corroborated"
]
CorroborationState = Literal[
    "unverified", "community_corroborated", "officially_corroborated"
]


@dataclass(frozen=True)
class CommunitySignalDraft:
    id: str
    source_key: str
    source_url: str | None
    canonical_url_hash: str
    referenced_url_hash: str | None
    channel: Literal["threads", "user_report"]
    published_at: datetime
    ingested_at: datetime
    matched_flood_terms: tuple[str, ...]
    derived_summary: str
    canonical_location: str
    admin_code: str | None
    lat: float
    lng: float
    location_precision: Literal["road_or_lane", "poi", "admin_area", "map_click"]
    match_basis: tuple[str, ...]
    exact_content_hmac: str
    content_lsh: str
    origin_hmac: str
    confidence: float
    retention_expires_at: datetime


@dataclass(frozen=True)
class CommunitySignalRecord:
    id: str
    source_key: str
    source_url: str | None
    channel: Literal["threads", "user_report"]
    published_at: datetime
    ingested_at: datetime
    derived_summary: str
    canonical_location: str
    admin_code: str | None
    lat: float
    lng: float
    distance_to_query_m: float
    location_precision: Literal["road_or_lane", "poi", "admin_area", "map_click"]
    confidence: float
    cluster_id: str | None
    corroboration_state: CorroborationState


@dataclass(frozen=True)
class CommunityClusterRecord:
    id: str
    canonical_location: str
    admin_code: str | None
    distance_to_query_m: float
    corroboration_state: CorroborationState
    distinct_original_source_count: int
    official_evidence_ids: tuple[str, ...]
    first_observed_at: datetime
    last_observed_at: datetime
    signal_ids: tuple[str, ...]


@dataclass(frozen=True)
class CommunitySnapshot:
    signals: tuple[CommunitySignalRecord, ...]
    clusters: tuple[CommunityClusterRecord, ...]
    repository_available: bool
    last_completed_at: datetime | None
```

- [ ] **Step 6: Update migration health exactly**

Set `REQUIRED_SCHEMA_FILENAME = "0039_v1_community_signals.sql"` in `apps/api/app/api/routes/health.py`; replace the expected filename in `apps/api/tests/test_public_contract.py`; add one migration README entry naming all six tables and both disabled seeds.

- [ ] **Step 7: Run schema, migration, and health tests**

Run: `python infra/scripts/validate_migrations.py && python -m pytest tests/test_v1_community_schema.py tests/test_apply_migrations_script.py -q`

Run: `(cd apps/api && python -m pytest tests/test_public_contract.py -q)`

Expected: both commands PASS without sharing pytest roots or importing one package as another.

- [ ] **Step 8: Commit the immutable foundation**

```bash
git add infra/migrations/0039_v1_community_signals.sql infra/migrations/README.md tests/test_v1_community_schema.py tests/fixtures/community_fingerprint_vectors.json apps/workers/app/community/__init__.py apps/workers/app/community/contracts.py apps/api/app/domain/community/__init__.py apps/api/app/domain/community/models.py apps/api/app/api/routes/health.py apps/api/tests/test_public_contract.py
git commit -m "feat: add exact metadata-only community schema"
```

---

### Task 2: Add Keyed Fingerprints and Controlled Matching

**Files:**

- Create: `apps/workers/app/community/fingerprints.py`
- Create: `apps/workers/app/community/matching.py`
- Create: `apps/workers/tests/test_community_fingerprints.py`
- Create: `apps/workers/tests/test_community_matching.py`
- Create: `apps/workers/tests/test_community_privacy.py`

**Interfaces:**

- Consumes: synthetic vector fixture, `RawCommunityPost`, `LocationContext`, a non-empty secret key, reviewed retention days, and current time.
- Produces: `normalize_content`, `exact_content_hmac`, `content_lsh`, `hamming_distance`, `canonicalize_public_url`, and `match_community_post(...) -> CommunitySignalCandidate | None`.

- [ ] **Step 1: Add deterministic synthetic vectors and RED tests**

`tests/fixtures/community_fingerprint_vectors.json` contains only invented `example.test` values and a test key:

```json
{
  "key_hex": "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f",
  "cases": [
    {
      "text": "臺南東區中華東路道路積水",
      "equivalent": "台南 東區 中華東路 道路積水！",
      "expected_exact_hmac": "63aea8a01499dd501dc3119e9ce5dac0f5b3e8cc8ef8c4d75ae49fade43dc50e",
      "expected_content_lsh": "46c5eb467e1f4b2f"
    },
    {
      "text": "高雄前鎮區積水",
      "different": "臺北士林區晴天",
      "expected_exact_hmac": "a4b7a010f4c15cc5889100699198cf9b367feba4e3420f32475750b6c2b28486",
      "expected_content_lsh": "5d59c220ab55ccf8"
    }
  ],
  "url_cases": [
    {
      "input": "https://EXAMPLE.TEST/threads/post/ABC?utm_source=fixture#ignored",
      "canonical": "https://example.test/threads/post/ABC",
      "expected_canonical_hmac": "e545c7474332ba87cea3c6ddf00b6175d937ea2abb35bc26d406da6eec1d4cbc"
    }
  ]
}
```

```python
def test_worker_fingerprints_match_fixed_vectors() -> None:
    for case in load_vectors()["cases"]:
        assert exact_content_hmac(TEST_KEY, case["text"]) == case["expected_exact_hmac"]
        assert content_lsh(TEST_KEY, case["text"]) == case["expected_content_lsh"]
        if "equivalent" in case:
            assert exact_content_hmac(TEST_KEY, case["equivalent"]) == case["expected_exact_hmac"]
            assert content_lsh(TEST_KEY, case["equivalent"]) == case["expected_content_lsh"]
    for case in load_vectors()["url_cases"]:
        canonical = canonicalize_public_url(case["input"])
        assert canonical == case["canonical"]
        assert keyed_hmac(
            TEST_KEY, "community-canonical-url-v1", canonical
        ) == case["expected_canonical_hmac"]


def test_original_and_reference_use_the_same_url_hmac_namespace() -> None:
    canonical = canonicalize_public_url(load_vectors()["url_cases"][0]["input"])
    original = keyed_hmac(TEST_KEY, "community-canonical-url-v1", canonical)
    reference = keyed_hmac(TEST_KEY, "community-canonical-url-v1", canonical)
    assert original == reference


def test_longest_term_wins_without_nested_duplicate() -> None:
    signal = match_community_post(
        raw_post(text="台南東區中華東路道路積水，請改道"),
        contexts=(tainan_zhonghua_east_road(),),
        fingerprint_key=TEST_KEY,
        retention_days=30,
        now=NOW,
    )
    assert signal is not None
    assert signal.matched_flood_terms == ("道路積水",)


def test_wrong_county_same_road_is_rejected() -> None:
    assert match_community_post(
        raw_post(text="高雄中華路積水"),
        contexts=(tainan_zhonghua_road(),),
        fingerprint_key=TEST_KEY,
        retention_days=30,
        now=NOW,
    ) is None


@pytest.mark.parametrize("context", [tainan_east_district(), tainan_shared_name_poi()])
def test_explicit_other_county_rejects_same_named_district_or_poi(context) -> None:
    assert match_community_post(
        raw_post(text="高雄東區同名地標淹水"),
        contexts=(context,), fingerprint_key=TEST_KEY,
        retention_days=30, now=NOW,
    ) is None


@pytest.mark.parametrize(("text", "context"), [
    ("台南東區道路積水", tainan_east_district()),
    ("高雄三民區淹水", kaohsiung_sanmin_district()),
    ("屏東萬丹道路積水", pingtung_wandan_context()),
])
def test_controlled_county_suffix_omission_matches_unambiguous_county(text, context) -> None:
    assert match_community_post(
        raw_post(text=text), contexts=(context,), fingerprint_key=TEST_KEY,
        retention_days=30, now=NOW,
    ) is not None


@pytest.mark.parametrize("text", ["新竹中山路淹水", "嘉義中山路淹水"])
def test_ambiguous_bare_county_name_fails_closed(text: str) -> None:
    assert match_community_post(
        raw_post(text=text),
        contexts=(hsinchu_city_road(), hsinchu_county_road(),
                  chiayi_city_road(), chiayi_county_road()),
        fingerprint_key=TEST_KEY, retention_days=30, now=NOW,
    ) is None


def test_unresolved_quote_cannot_be_counted_as_a_new_origin() -> None:
    assert match_community_post(
        raw_post(
            text="臺南積水",
            is_quote_post=True,
            referenced_source_id=None,
            referenced_url=None,
        ),
        contexts=(tainan_admin_context(),),
        fingerprint_key=TEST_KEY,
        retention_days=30,
        now=NOW,
    ) is None


def test_persistable_candidate_has_no_raw_text_identity_or_private_address() -> None:
    post = raw_post(text="台南東區中華東路淹水 @fixture 0912345678")
    signal = match_community_post(
        post,
        contexts=(tainan_zhonghua_east_road(),),
        fingerprint_key=TEST_KEY,
        retention_days=14,
        now=NOW,
    )
    serialized = json.dumps(asdict(signal), ensure_ascii=False)
    assert post.text not in serialized
    assert "@fixture" not in serialized
    assert "0912345678" not in serialized
    assert signal.source_url is None
    assert signal.retention_expires_at == NOW + timedelta(days=14)
```

- [ ] **Step 2: Run tests and verify missing modules**

Run: `(cd apps/workers && python -m pytest tests/test_community_fingerprints.py tests/test_community_matching.py tests/test_community_privacy.py -v)`

Expected: FAIL during import.

- [ ] **Step 3: Implement the keyed algorithms exactly**

```python
# apps/workers/app/community/fingerprints.py
import hashlib
import hmac
import unicodedata
import re


def normalize_content(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).replace("台", "臺").lower()
    normalized = re.sub(r"https://\S+|@\w+|\b09\d{8}\b", " ", normalized)
    return re.sub(r"[\W_]+", "", normalized, flags=re.UNICODE)


def _require_key(key: bytes) -> None:
    if len(key) < 32:
        raise ValueError("community fingerprint key must contain at least 32 bytes")


def keyed_hmac(key: bytes, namespace: str, value: str) -> str:
    _require_key(key)
    return hmac.new(key, f"{namespace}\0{value}".encode(), hashlib.sha256).hexdigest()


def exact_content_hmac(key: bytes, value: str) -> str:
    return keyed_hmac(key, "community-content-v1", normalize_content(value))


def content_lsh(key: bytes, value: str) -> str:
    normalized = normalize_content(value)
    tokens = (
        (normalized,)
        if 0 < len(normalized) <= 3
        else tuple(dict.fromkeys(
            normalized[index:index + 3]
            for index in range(max(0, len(normalized) - 2))
        ))
    )
    if not tokens:
        return "0" * 16
    totals = [0] * 64
    for token in tokens[:128]:
        bits = int(keyed_hmac(key, "community-token-v1", token)[:16], 16)
        for index in range(64):
            totals[index] += 1 if bits & (1 << index) else -1
    packed = sum(1 << index for index, total in enumerate(totals) if total >= 0)
    return f"{packed:016x}"


def hamming_distance(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()
```

The API implementation in Task 5 must pass the same JSON vectors byte-for-byte; the production key never appears in the fixture.

- [ ] **Step 4: Implement fail-closed semantic/location matching**

```python
# apps/workers/app/community/matching.py
import re
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.community.contracts import (
    CommunitySignalCandidate,
    LocationContext,
    RawCommunityPost,
)
from app.community.fingerprints import (
    content_lsh,
    exact_content_hmac,
    keyed_hmac,
    normalize_content,
)

FLOOD_TERM_CLASSES = (
    "地下道積水", "道路積水", "排水不及", "淹水", "積水", "水災"
)
_TRACKING_KEYS = {"fbclid", "gclid", "ref", "ref_src"}
REVIEWED_TAIWAN_JURISDICTION_NAMES: tuple[str, ...] = (
    "臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市",
    "基隆市", "新竹市", "嘉義市", "新竹縣", "苗栗縣", "彰化縣",
    "南投縣", "雲林縣", "嘉義縣", "屏東縣", "宜蘭縣", "花蓮縣",
    "臺東縣", "澎湖縣", "金門縣", "連江縣",
)

COUNTY_ALIASES: dict[str, tuple[str, ...]] = {
    "臺北市": ("臺北市", "臺北"),
    "新北市": ("新北市", "新北"),
    "桃園市": ("桃園市", "桃園"),
    "臺中市": ("臺中市", "臺中"),
    "臺南市": ("臺南市", "臺南"),
    "高雄市": ("高雄市", "高雄"),
    "基隆市": ("基隆市", "基隆"),
    "新竹市": ("新竹市",),
    "嘉義市": ("嘉義市",),
    "新竹縣": ("新竹縣",),
    "苗栗縣": ("苗栗縣", "苗栗"),
    "彰化縣": ("彰化縣", "彰化"),
    "南投縣": ("南投縣", "南投"),
    "雲林縣": ("雲林縣", "雲林"),
    "嘉義縣": ("嘉義縣",),
    "屏東縣": ("屏東縣", "屏東"),
    "宜蘭縣": ("宜蘭縣", "宜蘭"),
    "花蓮縣": ("花蓮縣", "花蓮"),
    "臺東縣": ("臺東縣", "臺東"),
    "澎湖縣": ("澎湖縣", "澎湖"),
    "金門縣": ("金門縣", "金門"),
    "連江縣": ("連江縣", "連江"),
}
assert tuple(COUNTY_ALIASES) == REVIEWED_TAIWAN_JURISDICTION_NAMES


def _place_text(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.replace("台", "臺").lower())


def canonicalize_public_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("community source URL must be public HTTPS")
    query = urlencode([
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_KEYS
    ])
    host = parsed.hostname.lower()
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunsplit(("https", host, parsed.path or "/", query, ""))


def best_compatible_location(
    text: str,
    tags: tuple[str, ...],
    contexts: tuple[LocationContext, ...],
) -> tuple[LocationContext | None, tuple[str, ...]]:
    haystack = _place_text(" ".join((text, *tags)))
    explicit_counties = tuple(
        county for county, aliases in COUNTY_ALIASES.items()
        if any(_place_text(alias) in haystack for alias in aliases)
    )
    ambiguous_bare = any(
        bare in haystack and not any(
            _place_text(full) in haystack for full in pair
        )
        for bare, pair in {
            "新竹": ("新竹市", "新竹縣"),
            "嘉義": ("嘉義市", "嘉義縣"),
        }.items()
    )
    if ambiguous_bare or len(set(explicit_counties)) > 1:
        return None, ()
    matches: list[tuple[int, LocationContext, tuple[str, ...]]] = []
    for context in contexts:
        county_hit = bool(context.county and context.county in explicit_counties)
        district_hit = bool(context.district and _place_text(context.district) in haystack)
        place_terms = tuple(
            item for item in (context.road_or_landmark, *context.aliases) if item
        )
        place_hit = any(_place_text(item) in haystack for item in place_terms)
        if context.precision == "road_or_lane" and not (county_hit and place_hit):
            continue
        if context.precision == "poi" and not (place_hit and county_hit):
            continue
        if context.precision == "admin_area" and not county_hit:
            continue
        if explicit_counties and not county_hit:
            continue
        basis = tuple(
            item for item, hit in (
                ("county", county_hit),
                ("district", district_hit),
                ("road" if context.precision == "road_or_lane" else "landmark", place_hit),
            )
            if hit
        )
        score = 3 if context.precision == "road_or_lane" else 2 if context.precision == "poi" else 1
        matches.append((score, context, ("flood_term", *basis)))
    if not matches:
        return None, ()
    matches.sort(key=lambda item: (-item[0], item[1].canonical_location))
    top_score = matches[0][0]
    top_locations = {
        (item[1].admin_code, item[1].canonical_location)
        for item in matches if item[0] == top_score
    }
    if len(top_locations) != 1:
        return None, ()
    best = matches[0]
    return best[1], best[2]


def match_confidence(basis: tuple[str, ...], precision: str) -> float:
    base = {"road_or_lane": 0.8, "poi": 0.75, "admin_area": 0.6}.get(precision, 0.55)
    return min(base + (0.05 if "district" in basis else 0.0), 0.9)


def _longest_flood_terms(text: str, tags: tuple[str, ...]) -> tuple[str, ...]:
    haystack = normalize_content(" ".join((text, *tags)))
    matches = [term for term in FLOOD_TERM_CLASSES if term in haystack]
    return tuple(
        term for term in matches
        if not any(term != longer and term in longer for longer in matches)
    )[:10]


def match_community_post(
    post: RawCommunityPost,
    *,
    contexts: tuple[LocationContext, ...],
    fingerprint_key: bytes,
    retention_days: int,
    now: datetime,
) -> CommunitySignalCandidate | None:
    terms = _longest_flood_terms(post.text, post.tags)
    if not terms:
        return None
    context, basis = best_compatible_location(post.text, post.tags, contexts)
    if context is None or context.precision not in {
        "road_or_lane", "poi", "admin_area"
    }:
        return None
    canonical_url = canonicalize_public_url(post.permalink)
    referenced_url = (
        canonicalize_public_url(post.referenced_url) if post.referenced_url else None
    )
    if post.is_quote_post and post.referenced_source_id is None and referenced_url is None:
        return None
    canonical_hash = keyed_hmac(
        fingerprint_key, "community-canonical-url-v1", canonical_url
    )
    referenced_hash = (
        keyed_hmac(fingerprint_key, "community-canonical-url-v1", referenced_url)
        if referenced_url else None
    )
    if post.referenced_source_id is not None:
        origin_hmac = keyed_hmac(
            fingerprint_key, "community-origin-source-id-v1", post.referenced_source_id
        )
    elif referenced_url is not None:
        origin_hmac = keyed_hmac(
            fingerprint_key, "community-origin-url-v1", referenced_url
        )
    else:
        origin_hmac = keyed_hmac(
            fingerprint_key, "community-origin-source-id-v1", post.source_id
        )
    bounded_days = min(max(retention_days, 1), 30)
    return CommunitySignalCandidate(
        id=keyed_hmac(
            fingerprint_key,
            "community-signal-id-v1",
            f"{post.source_key}|{post.source_id}",
        ),
        source_key=post.source_key,
        source_url=None,
        canonical_url_hash=canonical_hash,
        referenced_url_hash=referenced_hash,
        channel="threads",
        published_at=post.published_at,
        ingested_at=now,
        matched_flood_terms=terms,
        derived_summary=f"{context.canonical_location}出現{terms[0]}群眾訊號，尚待交叉佐證。",
        canonical_location=context.canonical_location,
        admin_code=context.admin_code,
        lat=context.lat,
        lng=context.lng,
        location_precision=context.precision,
        match_basis=basis,
        exact_content_hmac=exact_content_hmac(fingerprint_key, post.text),
        content_lsh=content_lsh(fingerprint_key, post.text),
        origin_hmac=origin_hmac,
        confidence=match_confidence(basis, context.precision),
        moderation_state="unverified",
        retention_expires_at=now + timedelta(days=bounded_days),
    )
```

`best_compatible_location` normalizes `台/臺` and uses the exact reviewed
22-jurisdiction name lexicon. Every public social match requires its context's
county/city token; a district or POI token alone is ambiguous and fails closed,
and any explicit different county rejects the match even when district/POI names
collide. It rejects two equally precise distinct locations and prefers
road/landmark over district over county. Threads accepts only
`road_or_lane|poi|admin_area`; `map_click` is reserved for the first-party report
builder. It returns only controlled basis values. `canonicalize_public_url`
accepts HTTPS, lowercases host, removes fragments and tracking parameters, and
rejects credentials/non-public schemes. Canonical and referenced URLs both use
the same `community-canonical-url-v1` HMAC namespace so an original URL equals a
quote/reference URL during dedupe and suppression; other identifier kinds
retain separate namespaces. The candidate always carries `source_url=None`, so
a Threads permalink containing a handle never enters SQL, logs, API output, or
snapshots.

- [ ] **Step 5: Run focused tests**

Run: `(cd apps/workers && python -m pytest tests/test_community_fingerprints.py tests/test_community_matching.py tests/test_community_privacy.py -q)`

Expected: PASS.

- [ ] **Step 6: Commit matching and fingerprints**

```bash
git add apps/workers/app/community/fingerprints.py apps/workers/app/community/matching.py apps/workers/tests/test_community_fingerprints.py apps/workers/tests/test_community_matching.py apps/workers/tests/test_community_privacy.py
git commit -m "feat: match and fingerprint sanitized community signals"
```

---

### Task 3: Add the Metadata-Only Repository, Kill Switch, Work Recovery, and Suppression

**Files:**

- Create: `apps/workers/app/community/repository.py`
- Create: `apps/workers/tests/test_community_repository.py`
- Modify: `apps/workers/app/community/__init__.py`

**Interfaces:**

- Consumes: `CommunitySignalCandidate`, `CommunitySearchRequest`, a database connection, and current time.
- Produces: `PostgresCommunityRepository`, `CommunityRetentionSummary`, an advisory-lock context, fail-closed source enablement, atomic work claiming/recovery, suppression, and retention.

- [ ] **Step 1: Write SQL-shape, kill-switch, idempotency, claim-recovery, and immediate-suppression tests**

```python
def test_disabled_catalog_source_cannot_insert_signal() -> None:
    repository = PostgresCommunityRepository(connection_factory=lambda: connection)
    cursor.source_enabled = False
    assert repository.upsert_signals((SANITIZED_SIGNAL,)) == ()
    assert "raw_snapshots" not in cursor.all_sql
    assert "staging_evidence" not in cursor.all_sql
    assert RAW_THREADS_TEXT not in repr(cursor.all_params)


@pytest.mark.parametrize("mismatch", ["key_id", "key_fingerprint"])
def test_source_key_binding_mismatch_fails_closed_without_egress_or_write(
    mismatch: str,
) -> None:
    cursor.source_enabled = True
    cursor.key_binding = DB_KEY_BINDING.with_mismatch(mismatch)
    assert repository.source_key_binding_matches(
        SOURCE_KEY,
        key_id=CONFIGURED_KEY_ID,
        key_sha256=CONFIGURED_KEY_SHA256,
    ) is False
    assert upstream_calls == []
    assert cursor.community_signal_inserts == 0


def test_idempotent_replay_preserves_first_ingestion_and_shorter_expiry() -> None:
    repository.upsert_signals((FIRST_SIGNAL,))
    repository.upsert_signals((LATER_REPLAY_WITH_LONGER_EXPIRY,))
    assert cursor.persisted_ingested_at == FIRST_SIGNAL.ingested_at
    assert cursor.persisted_expiry == FIRST_SIGNAL.retention_expires_at


def test_cycle_lock_recovers_unexpired_claimed_rows_after_crash() -> None:
    cursor.requests = [claimed_request(expires_at=NOW + timedelta(minutes=5))]
    with repository.community_cycle_lock() as acquired:
        assert acquired is True
        claimed = repository.claim_search_requests(now=NOW, limit=5)
    assert [item.normalized_query_key for item in claimed] == [REQUEST_KEY]


def test_stale_claim_completion_or_release_cannot_mutate_fresh_replacement() -> None:
    old = claim_request(requested_at=NOW, expires_at=NOW + timedelta(minutes=1))
    replace_after_expiry(
        old.normalized_query_key,
        requested_at=NOW + timedelta(minutes=2),
        expires_at=NOW + timedelta(minutes=10),
    )
    repository.complete_search_request(
        normalized_query_key=old.normalized_query_key,
        requested_at=old.requested_at,
        expires_at=old.expires_at,
        completed_at=NOW + timedelta(minutes=3),
    )
    repository.release_search_request(
        normalized_query_key=old.normalized_query_key,
        requested_at=old.requested_at,
        expires_at=old.expires_at,
    )
    assert cursor.fresh_replacement.status == "pending"
    assert repository.claim_search_requests(
        now=NOW + timedelta(minutes=3), limit=1
    ) == (cursor.fresh_replacement,)


def test_suppression_recomputes_cluster_before_commit() -> None:
    repository.suppress_source(
        source_key=SOURCE_KEY,
        canonical_url_hash=URL_HASH,
        reason="source_deleted",
        now=NOW,
    )
    assert cursor.signal_state == "suppressed"
    assert cursor.cluster_origin_count == 1
    assert cursor.cluster_state == "unverified"


@pytest.mark.parametrize("mutation", ["upsert_signals", "suppress_source", "prune"])
def test_cluster_affecting_mutation_takes_shared_xact_lock_first(mutation) -> None:
    invoke_repository_mutation(repository, mutation, now=NOW)
    lock_index = next(
        i for i, sql in enumerate(cursor.all_sql) if "pg_advisory_xact_lock" in sql
    )
    write_index = next(i for i, sql in enumerate(cursor.all_sql) if is_mutating_sql(sql))
    assert lock_index < write_index
    assert cursor.all_params[lock_index] == ("flood-risk:v1:community-mutation",)
```

- [ ] **Step 2: Run tests and verify the missing repository**

Run: `(cd apps/workers && python -m pytest tests/test_community_repository.py -v)`

Expected: FAIL during import.

- [ ] **Step 3: Define the complete repository surface**

```python
# apps/workers/app/community/repository.py
from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol

ConnectionFactory = Callable[[], Any]
_CYCLE_LOCK_KEY = 847_224_001
COMMUNITY_MUTATION_LOCK_NAME = "flood-risk:v1:community-mutation"


def _lock_community_mutation(cursor: Any) -> None:
    cursor.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (COMMUNITY_MUTATION_LOCK_NAME,),
    )


@dataclass(frozen=True)
class CommunityRetentionSummary:
    expired_signals: int
    expired_requests: int
    removed_clusters: int


class CommunityRepositoryUnavailable(RuntimeError):
    pass


class PostgresCommunityRepository:
    def __init__(
        self,
        *,
        database_url: str | None = None,
        connection_factory: ConnectionFactory | None = None,
        dedupe_key_id: str | None = None,
        dedupe_key_sha256: str | None = None,
    ) -> None:
        if database_url is None and connection_factory is None:
            raise ValueError("database_url or connection_factory is required")
        self._database_url = database_url
        self._connection_factory = connection_factory
        self._dedupe_key_id = dedupe_key_id
        self._dedupe_key_sha256 = dedupe_key_sha256


class CommunityRepository(Protocol):
    def is_source_enabled(self, source_key: str) -> bool:
        ...

    def source_key_binding_matches(
        self, source_key: str, *, key_id: str, key_sha256: str
    ) -> bool:
        ...

    def upsert_signals(
        self, signals: tuple[CommunitySignalCandidate, ...]
    ) -> tuple[str, ...]:
        ...

    def upsert_search_request(self, request: CommunitySearchRequest) -> bool:
        ...

    def community_cycle_lock(self) -> AbstractContextManager[bool]:
        ...

    def claim_search_requests(
        self, *, now: datetime, limit: int
    ) -> tuple[CommunitySearchRequest, ...]:
        ...

    def complete_search_request(
        self, *, normalized_query_key: str, requested_at: datetime,
        expires_at: datetime, completed_at: datetime
    ) -> None:
        ...

    def release_search_request(
        self, *, normalized_query_key: str, requested_at: datetime,
        expires_at: datetime
    ) -> None:
        ...

    def mark_source_success(self, *, source_key: str, completed_at: datetime) -> None:
        ...

    def suppress_source(
        self, *, source_key: str, canonical_url_hash: str,
        reason: str, now: datetime
    ) -> None:
        ...

    def prune(self, *, now: datetime) -> CommunityRetentionSummary:
        ...
```

`CommunityRepository` is the typing surface only. `PostgresCommunityRepository` implements every method in Steps 4–6 before this task is committed; the concrete class must contain no placeholder body. The signatures above and the following transaction/SQL requirements define the finished implementation.

- [ ] **Step 4: Implement fail-closed signal and priority upserts**

`upsert_signals` first calls `_lock_community_mutation(cursor)`, then reads
`data_sources.is_enabled` in the same transaction. A disabled/missing source
returns `()` with no writes so local retention/clustering can continue; actively
suppressed candidates are skipped. The conflict clause never changes first
ingestion and can only shorten retention:

`source_key_binding_matches` returns true only when the row is enabled and its
metadata contains exact constant-time-equal `dedupe_hmac_key_id` and lowercase
SHA-256 fingerprint values. Callers compute the fingerprint from decoded secret
bytes in memory; neither repository SQL nor logs receive the secret. Missing,
null, malformed, or mismatched metadata is false. `upsert_signals` repeats this
binding check inside its transaction for community sources using the binding
carried by the repository instance, so a gate checked before HTTP cannot
authorize a write after an operator disables or rotates the key.

```sql
INSERT INTO community_signals (
    id, source_key, source_url, canonical_url_hash, referenced_url_hash,
    channel, published_at, ingested_at, matched_flood_terms, derived_summary,
    canonical_location, admin_code, geom, location_precision, match_basis,
    exact_content_hmac, content_lsh, origin_hmac, confidence,
    moderation_state, retention_expires_at
)
SELECT
    %(id)s, %(source_key)s, %(source_url)s, %(canonical_url_hash)s,
    %(referenced_url_hash)s, %(channel)s, %(published_at)s, %(ingested_at)s,
    %(matched_flood_terms)s, %(derived_summary)s, %(canonical_location)s,
    %(admin_code)s, ST_SetSRID(ST_MakePoint(%(lng)s, %(lat)s), 4326),
    %(location_precision)s, %(match_basis)s, %(exact_content_hmac)s,
    %(content_lsh)s, %(origin_hmac)s, %(confidence)s,
    %(moderation_state)s, %(retention_expires_at)s
WHERE EXISTS (
    SELECT 1 FROM data_sources
    WHERE adapter_key = %(source_key)s AND is_enabled = true
)
AND NOT EXISTS (
    SELECT 1 FROM suppressed_sources
    WHERE source_key = %(source_key)s
      AND canonical_url_hash IN (
          %(canonical_url_hash)s, %(referenced_url_hash)s
      )
      AND (expires_at IS NULL OR expires_at > %(ingested_at)s)
)
ON CONFLICT (source_key, canonical_url_hash) DO UPDATE SET
    matched_flood_terms = EXCLUDED.matched_flood_terms,
    confidence = GREATEST(community_signals.confidence, EXCLUDED.confidence),
    retention_expires_at = LEAST(
        community_signals.retention_expires_at,
        EXCLUDED.retention_expires_at
    ),
    updated_at = EXCLUDED.ingested_at
RETURNING id;
```

`upsert_search_request` stores only already-canonical fields plus the UUID of the
server-selected public gazetteer anchor; it never stores the submitted point. In
one transaction,
it deletes that exact key when `expires_at <= incoming.requested_at`, inserts the
fresh pending row, and on conflict with an unexpired row changes only
`priority = GREATEST(existing, incoming)`. It preserves the active row's
anchor UUID, canonical fields, `requested_at`, `expires_at`, and `status`;
repeated requests
cannot extend a claim lease indefinitely. It never stores query text or request
identity. A regression proves an expired primary-key row is replaced—not
reported prioritized and then immediately deleted by the claim cleanup.

- [ ] **Step 5: Implement advisory-lock claim recovery and exact completion**

`community_cycle_lock` holds a dedicated PostgreSQL session and calls `pg_try_advisory_lock(_CYCLE_LOCK_KEY)`; it always unlocks/closes in `finally`. Only while that lock is held, `claim_search_requests` atomically recovers all unexpired `claimed` rows from a prior crashed process and claims the bounded batch:

The cycle-owner key is deliberately distinct from
`COMMUNITY_MUTATION_LOCK_NAME`: it prevents two worker cycles, while the shared
transaction key serializes cluster-affecting writes across worker and API
processes without self-deadlocking a cycle's dedicated lock session.

```sql
DELETE FROM community_search_requests WHERE expires_at <= %(now)s;
UPDATE community_search_requests
SET status = 'pending'
WHERE status = 'claimed' AND expires_at > %(now)s;

WITH picked AS (
    SELECT normalized_query_key
    FROM community_search_requests
    WHERE status = 'pending' AND expires_at > %(now)s
    ORDER BY priority DESC, requested_at ASC
    FOR UPDATE SKIP LOCKED
    LIMIT %(limit)s
)
UPDATE community_search_requests AS request
SET status = 'claimed'
FROM picked
WHERE request.normalized_query_key = picked.normalized_query_key
RETURNING request.normalized_query_key, request.anchor_geocoder_entry_id,
          request.county, request.district, request.road_or_landmark,
          request.radius_m, request.priority, request.requested_at,
          request.expires_at;
```

The immutable `(normalized_query_key, requested_at, expires_at)` triple is the
claim generation token. `complete_search_request` deletes only a successfully
executed row whose key and both timestamps still match and whose status is
`claimed`; `release_search_request` changes only that exact, still-unexpired
`claimed` generation back to pending. A stale worker can therefore neither
delete nor release a fresh row that reused the primary key after expiry. Return
the two timestamps from claiming and pass the full claimed object through the
cycle; do not reduce completed work to a bare key set. `mark_source_success`
updates `data_sources.last_success_at` only for an enabled matching source and
only after signal persistence plus cluster replacement succeed. There is no
claim timestamp or retained completion history.

- [ ] **Step 6: Implement immediate suppression and pruning**

In one transaction, `suppress_source` first acquires
`COMMUNITY_MUTATION_LOCK_NAME`, then locks the source-key rows whose
`canonical_url_hash` **or** `referenced_url_hash` equals the requested hash and
locks their cluster IDs, upserts `suppressed_sources`, sets those signals to
`suppressed`, clears links, and calls the same
`_recompute_locked_clusters(cursor, cluster_ids, now)` used after report
redaction. This makes a deleted original suppress same-source quotes that
resolve to it. The helper updates distinct active origins/corroboration or
deletes an empty cluster before commit. `prune` and any signal-affecting
retention path acquire the same transaction lock before deleting/recomputing.
No public query can observe a stale corroborated state after suppression
commits.

- [ ] **Step 7: Run repository and privacy tests**

Run: `(cd apps/workers && python -m pytest tests/test_community_repository.py tests/test_community_privacy.py -q)`

Expected: PASS.

- [ ] **Step 8: Commit the repository**

```bash
git add apps/workers/app/community/repository.py apps/workers/app/community/__init__.py apps/workers/tests/test_community_repository.py apps/workers/tests/test_community_privacy.py
git commit -m "feat: persist and suppress community metadata safely"
```

---

### Task 4: Add the Strict Official Threads Adapter and Hard Gates

**Files:**

- Create: `apps/workers/app/adapters/threads/__init__.py`
- Create: `apps/workers/app/adapters/threads/keyword_search.py`
- Create: `apps/workers/tests/fixtures/threads_keyword_search_synthetic.json`
- Create: `apps/workers/tests/fixtures/threads_contract_verified_test_only.json`
- Create: `apps/workers/tests/test_threads_keyword_search_adapter.py`
- Create: `apps/workers/tests/test_threads_contract_artifact_smoke.py`
- Create: `apps/workers/app/adapters/threads/contract.json`
- Create: `apps/workers/app/ops/threads_contract_artifact_smoke.py`
- Modify: `apps/workers/pyproject.toml`
- Modify: `apps/workers/app/config.py`
- Modify: `.env.example`
- Modify: `apps/workers/tests/test_adapter_registry_config.py`
- Modify: `apps/workers/tests/test_adapter_contracts.py`

**Interfaces:**

- Consumes: the currently published Meta Threads endpoint
  `https://graph.threads.net/keyword_search`, the checked expected-contract
  artifact, bearer token, injected HTTP
  function, strict settings, database `is_enabled`, matcher, contexts, and time.
- Produces: `ThreadsKeywordSearchClient.search(...) -> ThreadsSearchPage`, `ThreadsKeywordSearchAdapter.search(...)`, `ThreadsRateLimited`, and `build_threads_adapter(...) -> adapter | None`.

- [ ] **Step 1: Write endpoint, bearer, parser, bound, backoff, no-log, and PTT/Dcard RED tests**

```python
def test_client_requires_exact_official_keyword_path() -> None:
    for url in (
        "http://graph.threads.net/keyword_search",
        "https://example.test/keyword_search",
        "https://token@graph.threads.net/keyword_search",
        "https://graph.threads.net:443/keyword_search",
        "https://graph.threads.net/v1.0/keyword_search",
        "https://graph.threads.net/v2.0/keyword_search",
        "https://graph.threads.net/me",
    ):
        with pytest.raises(ThreadsConfigurationError):
            ThreadsKeywordSearchClient(
                endpoint=url,
                access_token="fixture-token",
                timeout_seconds=8,
                fetch_json=NO_NETWORK_FETCH,
            )


def test_client_uses_bearer_and_exact_keyword_fields() -> None:
    client = fixture_client()
    client.search(
        query="臺南 淹水", since=NOW - timedelta(hours=6), until=NOW,
        limit=25, after=None,
    )
    request = fetch_spy.calls[0]
    assert request.headers == {"Authorization": "Bearer fixture-token"}
    assert "access_token" not in request.params
    assert request.params["search_mode"] == "KEYWORD"
    assert request.params["fields"] == (
        "id,permalink,text,timestamp,is_quote_post,quoted_post,reposted_post,has_replies"
    )


def test_parser_discards_unknown_identity_fields() -> None:
    page = parse_threads_search_page(
        SYNTHETIC_PAGE,
        source_key=SOURCE_KEY,
        window_start=NOW - timedelta(hours=6),
        window_end=NOW,
    )
    assert page.posts[0].source_id == "synthetic-post-1"
    assert not hasattr(page.posts[0], "username")
    assert "username" not in repr(page)
    assert page.posts[0].text not in repr(page)
    assert page.posts[0].permalink not in repr(page)


def test_parser_conservatively_skips_quote_and_repost_rows() -> None:
    page = parse_threads_search_page(
        SYNTHETIC_QUOTE_AND_REPOST_PAGE,
        source_key=SOURCE_KEY,
        window_start=NOW - timedelta(hours=6),
        window_end=NOW,
    )
    assert page.posts == ()
    assert "fixture-author" not in repr(page)


def test_429_becomes_bounded_retryable_error() -> None:
    with pytest.raises(ThreadsRateLimited) as raised:
        rate_limited_client(retry_after="99999").search(
            query="臺南 淹水",
            since=NOW - timedelta(hours=6),
            until=NOW,
            limit=25,
            after=None,
        )
    assert raised.value.retry_after == timedelta(minutes=30)


def test_concrete_transport_uses_bearer_without_token_in_url_or_error() -> None:
    response = fetch_threads_json(
        "https://graph.threads.net/keyword_search",
        headers={"Authorization": "Bearer fixture-token"},
        params={"q": "臺南 淹水", "limit": 25},
        timeout_seconds=8,
        open_fn=open_spy,
    )
    assert response == SYNTHETIC_PAGE
    assert "fixture-token" not in open_spy.request.full_url
    assert open_spy.request.get_header("Authorization") == "Bearer fixture-token"


@pytest.mark.parametrize("response", [WRONG_CONTENT_TYPE, OVERSIZED_JSON])
def test_concrete_transport_rejects_unbounded_or_non_json_response(response) -> None:
    with pytest.raises(ThreadsHttpError) as raised:
        fetch_with_response(response)
    assert "fixture-token" not in repr(raised.value)
    assert SYNTHETIC_FULL_TEXT not in repr(raised.value)


def test_cross_host_redirect_is_rejected_without_a_second_request() -> None:
    with pytest.raises(ThreadsHttpError) as raised:
        fetch_with_redirect("https://attacker.example/collect")
    assert raised.value.status_code == 302
    assert redirect_spy.request_count == 1
    assert redirect_spy.second_request_authorization is None


def test_threads_enablement_does_not_enable_forum_network_paths() -> None:
    settings = threads_live_settings()
    assert adapter_is_enabled(PTT_METADATA, settings) is False
    assert adapter_is_enabled(DCARD_METADATA, settings) is False
    assert PttCandidateAdapter.governance_metadata["candidate_contract"]["http_fetch"] is False
    assert DcardCandidateAdapter.governance_metadata["candidate_contract"]["http_fetch"] is False


def test_live_adapter_requires_recorded_real_app_contract_smoke() -> None:
    settings = replace(threads_live_settings(), threads_api_contract_verified=False)
    assert build_threads_adapter(
        settings, catalog_enabled=True, catalog_key_binding_matches=True,
        fetch_json=NO_NETWORK_FETCH
    ) is None


def test_explicit_contract_smoke_uses_one_result_and_persists_nothing() -> None:
    result = verify_threads_keyword_contract(
        client=real_app_sandbox_client(),
        query="淹水",
        now=NOW,
    )
    assert result.status == "verified"
    assert result.request_count == 1
    assert result.result_count == 1
    assert result.observed_schema_sha256 == EXPECTED_SCHEMA_SHA256
    assert RAW_THREADS_TEXT not in repr(result)
    assert verifier_application_table_writes == []


def test_checked_contract_artifact_matches_client_and_verifier() -> None:
    contract = load_threads_contract_artifact(CONTRACT_PATH)
    assert contract.artifact_version == 1
    assert contract.official_reference_url == OFFICIAL_REFERENCE_URL
    assert contract.endpoint == OFFICIAL_KEYWORD_ENDPOINT
    assert contract.requested_fields == ALLOWED_FIELDS
    assert contract.search_mode == "KEYWORD"
    assert contract.search_type == "RECENT"


def test_adapter_exposes_only_safe_readonly_key_binding_metadata() -> None:
    adapter = ThreadsKeywordSearchAdapter(
        client=fixture_client(),
        fingerprint_key=bytes.fromhex(TEST_KEY_HEX),
        fingerprint_key_id="fixture-key-v1",
        fingerprint_key_sha256=TEST_KEY_SHA256,
        retention_days=30,
    )
    assert adapter.fingerprint_key_id == "fixture-key-v1"
    assert adapter.fingerprint_key_sha256 == TEST_KEY_SHA256
    with pytest.raises(AttributeError):
        adapter.fingerprint_key_id = "changed"


def test_adapter_rejects_mismatched_key_binding_metadata() -> None:
    with pytest.raises(ValueError, match="fingerprint key binding mismatch"):
        ThreadsKeywordSearchAdapter(
            client=fixture_client(),
            fingerprint_key=bytes.fromhex(TEST_KEY_HEX),
            fingerprint_key_id="fixture-key-v1",
            fingerprint_key_sha256="0" * 64,
            retention_days=30,
        )
```

The test fixture is explicitly synthetic, uses only `https://example.test/threads/...` permalinks, and contains no real author, handle, ID, media, comment, or copied post.

- [ ] **Step 2: Run tests and verify missing settings/client**

Run: `(cd apps/workers && python -m pytest tests/test_threads_keyword_search_adapter.py tests/test_adapter_registry_config.py tests/test_adapter_contracts.py -v)`

Expected: FAIL during import or on missing settings.

- [ ] **Step 3: Define the complete transport and errors**

```python
# apps/workers/app/adapters/threads/keyword_search.py
from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.community.contracts import (
    CommunitySignalCandidate,
    LocationContext,
    RawCommunityPost,
)
from app.community.matching import canonicalize_public_url, match_community_post

SOURCE_KEY = "social.threads.keyword_search"
OFFICIAL_KEYWORD_ENDPOINT = "https://graph.threads.net/keyword_search"
_ENDPOINT_PATH = re.compile(r"^/keyword_search$")
ALLOWED_FIELDS = (
    "id", "permalink", "text", "timestamp", "is_quote_post",
    "quoted_post", "reposted_post", "has_replies",
)
MAX_QUERY_LENGTH = 100
MAX_PAGE_SIZE = 25
MAX_WINDOW = timedelta(hours=24)
MAX_RETRY_AFTER = timedelta(minutes=30)
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class ThreadsConfigurationError(ValueError):
    pass


class ThreadsHttpError(RuntimeError):
    def __init__(self, status_code: int, headers: Mapping[str, str]) -> None:
        super().__init__(f"Threads HTTP status {status_code}")
        self.status_code = status_code
        self.headers = headers


class ThreadsRateLimited(RuntimeError):
    def __init__(self, retry_after: timedelta) -> None:
        super().__init__("Threads keyword search rate limited")
        self.retry_after = retry_after


class ThreadsSourceDisabled(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Threads source disabled")


class FetchJson(Protocol):
    def __call__(
        self, url: str, *, headers: Mapping[str, str],
        params: Mapping[str, str | int], timeout_seconds: int
    ) -> Mapping[str, Any]:
        ...


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open_without_redirects(request: Request, *, timeout: int):
    return build_opener(_RejectRedirects()).open(request, timeout=timeout)


def fetch_threads_json(
    url: str,
    *,
    headers: Mapping[str, str],
    params: Mapping[str, str | int],
    timeout_seconds: int,
    open_fn: Callable[..., Any] = _open_without_redirects,
) -> Mapping[str, Any]:
    request_url = f"{url}?{urlencode(params)}"
    request = Request(
        request_url,
        headers={**headers, "Accept": "application/json"},
        method="GET",
    )
    try:
        with open_fn(request, timeout=timeout_seconds) as response:
            content_type = response.headers.get_content_type()
            declared = response.headers.get("Content-Length")
            if content_type != "application/json":
                raise ThreadsHttpError(502, {})
            if declared is not None and int(declared) > MAX_RESPONSE_BYTES:
                raise ThreadsHttpError(502, {})
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise ThreadsHttpError(502, {})
    except HTTPError as exc:
        retry_after = exc.headers.get("Retry-After")
        safe_headers = {"Retry-After": retry_after} if retry_after is not None else {}
        raise ThreadsHttpError(exc.code, safe_headers) from exc
    except ThreadsHttpError:
        raise
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise ThreadsHttpError(0, {}) from exc
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ThreadsHttpError(502, {}) from exc
    if not isinstance(payload, Mapping):
        raise ThreadsHttpError(502, {})
    return payload


@dataclass(frozen=True)
class ThreadsSearchPage:
    posts: tuple[RawCommunityPost, ...]
    after: str | None


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Threads timestamp must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Threads timestamp must include timezone")
    return parsed


def _extract_tags(text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(re.findall(r"#[\w\u3400-\u9fff]{1,30}", text)))[:20]


def _extract_reference(text: str, permalink: str) -> str | None:
    for candidate in re.findall(r"https://[^\s<>'\"]+", text):
        try:
            canonical = canonicalize_public_url(candidate.rstrip("。,.!！?？)）"))
        except ValueError:
            continue
        if canonical != canonicalize_public_url(permalink):
            return canonical
    return None


def parse_threads_search_page(
    payload: Mapping[str, Any],
    *,
    source_key: str,
    window_start: datetime,
    window_end: datetime,
) -> ThreadsSearchPage:
    rows = payload.get("data")
    if not isinstance(rows, list) or len(rows) > MAX_PAGE_SIZE:
        raise ValueError("Threads data must be a bounded list")
    posts: list[RawCommunityPost] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("Threads post must be an object")
        source_id = row.get("id")
        permalink = row.get("permalink")
        text = row.get("text")
        is_quote = row.get("is_quote_post")
        quoted_post = row.get("quoted_post")
        reposted_post = row.get("reposted_post")
        has_replies = row.get("has_replies")
        if not isinstance(source_id, str) or not source_id:
            raise ValueError("Threads id is required")
        if not isinstance(permalink, str):
            raise ValueError("Threads permalink is required")
        canonical_permalink = canonicalize_public_url(permalink)
        if (
            not isinstance(text, str)
            or not isinstance(is_quote, bool)
            or not isinstance(has_replies, bool)
        ):
            raise ValueError("Threads text/quote/reply-summary fields have invalid types")
        for reference in (quoted_post, reposted_post):
            if reference is not None and (
                not isinstance(reference, Mapping)
                or not isinstance(reference.get("id"), str)
                or not reference["id"]
            ):
                raise ValueError("Threads origin reference has an unreviewed shape")
        published_at = _parse_timestamp(row.get("timestamp"))
        if not (window_start <= published_at <= window_end + timedelta(minutes=5)):
            continue
        # Derivative rows are not independent eyewitness origins in v1.
        if is_quote or quoted_post is not None or reposted_post is not None:
            continue
        posts.append(RawCommunityPost(
            source_key=source_key,
            source_id=source_id,
            permalink=canonical_permalink,
            text=text,
            published_at=published_at,
            tags=_extract_tags(text),
            is_quote_post=False,
            referenced_source_id=None,
            referenced_url=_extract_reference(text, canonical_permalink),
        ))
    paging = payload.get("paging")
    if paging is None:
        after = None
    else:
        if not isinstance(paging, Mapping):
            raise ValueError("Threads paging must be an object")
        cursors = paging.get("cursors")
        if cursors is None:
            after = None
        else:
            if not isinstance(cursors, Mapping):
                raise ValueError("Threads paging cursors must be an object")
            after = cursors.get("after")
            if after is not None and (
                not isinstance(after, str) or not (1 <= len(after) <= 500)
            ):
                raise ValueError("Threads after cursor must be a bounded string")
    return ThreadsSearchPage(tuple(posts), after)
```

- [ ] **Step 4: Implement strict parsing and bearer-auth search**

`parse_threads_search_page(payload, source_key, window_start, window_end)`
requires `data` to be a list no longer than `MAX_PAGE_SIZE`; each accepted row
requires non-empty string `id`, canonical public HTTPS `permalink`, string
`text`, parseable timezone-aware `timestamp`, and booleans `is_quote_post` and
`has_replies`. The current Meta collection publishes the unversioned
`/keyword_search` request and includes structured `quoted_post` and
`reposted_post` fields; `is_reply` is not part of the Keyword Search contract and
must not be required. Reference fields must be absent/null or match the exact
artifact-approved object-with-ID shape. Quote/repost rows are conservatively
skipped instead of being counted as new origins; `has_replies` does not mean the
row itself is a reply. A canonical URL
found in an ordinary post's text may remain an in-memory same-origin hint.
Optional paging/cursors must be mappings and `after` must be absent or a 1–500
character string. It ignores all identity/media fields before constructing
`RawCommunityPost`; raw text, source IDs, permalinks, and reference URLs are
never logged or persisted.

Implement `fetch_threads_json` in this same module with the bounded stdlib HTTPS
transport above. It URL-encodes only search params, sends the token only as a
Bearer header, requires JSON content type, enforces both declared and actual
2 MiB response limits, requires a top-level mapping, and uses the configured
1–30 second timeout. Its opener disables redirects entirely; every 3xx is a
terminal safe error, so `Authorization` can never be copied to a second origin
or path. `HTTPError` becomes `ThreadsHttpError` retaining only status
and the single `Retry-After` value needed for 429 handling. Transport/JSON/schema
errors expose no URL, token, response body, post text, or response headers in
their message/repr. Never read or log an HTTP error body.

```python
class ThreadsKeywordSearchClient:
    def __init__(
        self, *, endpoint: str, access_token: str,
        timeout_seconds: int, fetch_json: FetchJson
    ) -> None:
        parsed = urlparse(endpoint)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "graph.threads.net"
            or parsed.netloc != "graph.threads.net"
            or parsed.query
            or parsed.fragment
            or not _ENDPOINT_PATH.fullmatch(parsed.path)
        ):
            raise ThreadsConfigurationError("exact official Threads keyword endpoint required")
        if not access_token:
            raise ThreadsConfigurationError("Threads access token is required")
        if endpoint != OFFICIAL_KEYWORD_ENDPOINT:
            raise ThreadsConfigurationError("reviewed Threads keyword endpoint required")
        self._endpoint = endpoint
        self._token = access_token
        self._timeout = min(max(timeout_seconds, 1), 30)
        self._fetch_json = fetch_json

    def search(
        self, *, query: str, since: datetime, until: datetime,
        limit: int, after: str | None = None
    ) -> ThreadsSearchPage:
        normalized = " ".join(query.split())
        if not normalized or len(normalized) > MAX_QUERY_LENGTH:
            raise ValueError("query length must be between 1 and 100")
        if until <= since or until - since > MAX_WINDOW:
            raise ValueError("search window must be positive and at most 24 hours")
        params: dict[str, str | int] = {
            "q": normalized,
            "search_type": "RECENT",
            "search_mode": "KEYWORD",
            "fields": ",".join(ALLOWED_FIELDS),
            "since": since.isoformat(),
            "until": until.isoformat(),
            "limit": min(max(limit, 1), MAX_PAGE_SIZE),
        }
        if after is not None:
            if not (1 <= len(after) <= 500):
                raise ValueError("after cursor must be between 1 and 500 characters")
            params["after"] = after
        try:
            payload = self._fetch_json(
                self._endpoint,
                headers={"Authorization": f"Bearer {self._token}"},
                params=params,
                timeout_seconds=self._timeout,
            )
        except ThreadsHttpError as exc:
            if exc.status_code != 429:
                raise
            raw_retry = exc.headers.get("Retry-After", "60")
            seconds = int(raw_retry) if raw_retry.isdecimal() else 60
            seconds = min(max(seconds, 1), 1800)
            raise ThreadsRateLimited(timedelta(seconds=seconds)) from exc
        return parse_threads_search_page(
            payload,
            source_key=SOURCE_KEY,
            window_start=since,
            window_end=until,
        )
```

`OFFICIAL_KEYWORD_ENDPOINT` is a code-reviewed constant, not a freely
configurable egress URL. Meta endpoint or field changes require updating the
constant, the strict fixture, the expected contract, and a new real-App smoke
artifact in one reviewed commit while all live gates remain off. Do not prepend
a guessed Graph version.

- [ ] **Step 5: Implement the bounded in-memory adapter**

```python
class ThreadsKeywordSearchAdapter:
    source_key = SOURCE_KEY

    def __init__(
        self, *, client: ThreadsKeywordSearchClient,
        fingerprint_key: bytes, fingerprint_key_id: str,
        fingerprint_key_sha256: str, retention_days: int, max_pages: int = 4
    ) -> None:
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", fingerprint_key_id):
            raise ValueError("invalid fingerprint key ID")
        if not hmac.compare_digest(
            hashlib.sha256(fingerprint_key).hexdigest(), fingerprint_key_sha256
        ):
            raise ValueError("fingerprint key binding mismatch")
        self._client = client
        self._fingerprint_key = fingerprint_key
        self._fingerprint_key_id = fingerprint_key_id
        self._fingerprint_key_sha256 = fingerprint_key_sha256
        self._retention_days = min(max(retention_days, 1), 30)
        self._max_pages = min(max(max_pages, 1), 4)

    @property
    def fingerprint_key_id(self) -> str:
        return self._fingerprint_key_id

    @property
    def fingerprint_key_sha256(self) -> str:
        return self._fingerprint_key_sha256

    def search(
        self, *, query: str, contexts: tuple[LocationContext, ...],
        since: datetime, until: datetime, now: datetime,
        egress_allowed: Callable[[], bool] = lambda: True,
    ) -> tuple[CommunitySignalCandidate, ...]:
        output: list[CommunitySignalCandidate] = []
        after: str | None = None
        for _ in range(self._max_pages):
            if not egress_allowed():
                raise ThreadsSourceDisabled()
            page = self._client.search(
                query=query, since=since, until=until,
                limit=MAX_PAGE_SIZE, after=after,
            )
            for post in page.posts:
                signal = match_community_post(
                    post,
                    contexts=contexts,
                    fingerprint_key=self._fingerprint_key,
                    retention_days=self._retention_days,
                    now=now,
                )
                if signal is not None:
                    output.append(signal)
            after = page.after
            if after is None:
                break
        return tuple(output)
```

The constructor requires the safe binding ID and the SHA-256 of the supplied
secret bytes, compares that digest in constant time, and exposes only
`fingerprint_key_id` and `fingerprint_key_sha256` as getter-only properties.
The secret bytes remain private. Task 8 reads those two properties before every
page to perform the repository binding check; no scheduler code reaches into a
private attribute or recomputes the secret digest.

The callback is checked immediately before every paginated HTTP request, not
once per logical query. Production always injects a fresh database kill-switch
read; the default exists only for isolated fixture/unit use. Add a test whose
answers are `True, False` across two pages: exactly one HTTP request occurs, the
adapter raises `ThreadsSourceDisabled`, and the scheduler performs no signal
write from the discarded partial in-memory result.

- [ ] **Step 6: Add fail-closed settings and constructor**

Add these exact `WorkerSettings` fields and env parsing. The token and HMAC strings use `dataclasses.field(repr=False)` and no settings dump is logged:

```text
SOURCE_THREADS_ENABLED=false
SOURCE_THREADS_API_ENABLED=false
THREADS_APP_REVIEW_APPROVED=false
THREADS_KEYWORD_SEARCH_PERMISSION_APPROVED=false
THREADS_API_CONTRACT_VERIFIED=false
THREADS_API_CONTRACT_ARTIFACT_PATH=
THREADS_ACCESS_TOKEN=
THREADS_API_TIMEOUT_SECONDS=8
THREADS_MAX_PAGES=4
THREADS_RETENTION_DAYS=30
COMMUNITY_DEDUPE_HMAC_KEY_ID=
COMMUNITY_DEDUPE_HMAC_KEY=
```

```python
OFFICIAL_REFERENCE_URL = (
    "https://www.postman.com/meta/threads/request/"
    "34203612-b3b2c12a-7ce6-4d86-a3c6-6d31e3b66ea1"
)
EXPECTED_SCHEMA_SHA256 = (
    "0fa67846d3973d130498917d15aa9b9d5d889a894a7c6836c2fab0a5fe26520f"
)


@dataclass(frozen=True)
class ThreadsContractArtifact:
    artifact_version: int
    status: Literal["pending", "verified", "failed"]
    official_reference_url: str
    endpoint: str
    search_mode: str
    search_type: str
    requested_fields: tuple[str, ...]
    expected_schema_sha256: str
    observed_schema_sha256: str | None
    verified_at: datetime | None
    request_count: int
    result_count: int


def validate_threads_contract_artifact(
    artifact: ThreadsContractArtifact | None, *, now: datetime
) -> bool:
    verified_at = artifact.verified_at if artifact is not None else None
    return bool(
        artifact is not None
        and type(artifact.artifact_version) is int
        and artifact.artifact_version == 1
        and artifact.status == "verified"
        and artifact.official_reference_url == OFFICIAL_REFERENCE_URL
        and artifact.endpoint == OFFICIAL_KEYWORD_ENDPOINT
        and artifact.search_mode == "KEYWORD"
        and artifact.search_type == "RECENT"
        and artifact.requested_fields == ALLOWED_FIELDS
        and artifact.expected_schema_sha256 == EXPECTED_SCHEMA_SHA256
        and artifact.observed_schema_sha256 == EXPECTED_SCHEMA_SHA256
        and now.tzinfo is not None
        and verified_at is not None
        and verified_at.tzinfo is not None
        and now - timedelta(days=30) <= verified_at <= now + timedelta(minutes=5)
        and type(artifact.request_count) is int
        and artifact.request_count == 1
        and type(artifact.result_count) is int
        and artifact.result_count == 1
    )


def build_threads_adapter(
    settings: WorkerSettings,
    *,
    catalog_enabled: bool,
    catalog_key_binding_matches: bool,
    fetch_json: FetchJson,
    contract_artifact: ThreadsContractArtifact | None = None,
    now: datetime | None = None,
) -> ThreadsKeywordSearchAdapter | None:
    artifact = contract_artifact or load_threads_contract_artifact(
        settings.threads_api_contract_artifact_path
    )
    contract_verified = validate_threads_contract_artifact(
        artifact, now=now or datetime.now(UTC)
    )
    gates = (
        settings.source_threads_enabled is True,
        settings.source_threads_api_enabled,
        settings.threads_app_review_approved,
        settings.threads_keyword_search_permission_approved,
        settings.threads_api_contract_verified,
        bool(settings.threads_access_token),
        bool(settings.community_dedupe_hmac_key_id),
        bool(settings.community_dedupe_hmac_key),
        catalog_enabled,
        catalog_key_binding_matches,
        contract_verified,
    )
    if not all(gates):
        return None
    try:
        fingerprint_key = bytes.fromhex(settings.community_dedupe_hmac_key)
    except ValueError:
        return None
    if len(fingerprint_key) < 32:
        return None
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", settings.community_dedupe_hmac_key_id):
        return None
    return ThreadsKeywordSearchAdapter(
        client=ThreadsKeywordSearchClient(
            endpoint=OFFICIAL_KEYWORD_ENDPOINT,
            access_token=settings.threads_access_token,
            timeout_seconds=settings.threads_api_timeout_seconds,
            fetch_json=fetch_json,
        ),
        fingerprint_key=fingerprint_key,
        fingerprint_key_id=settings.community_dedupe_hmac_key_id,
        fingerprint_key_sha256=hashlib.sha256(fingerprint_key).hexdigest(),
        retention_days=settings.threads_retention_days,
        max_pages=settings.threads_max_pages,
    )
```

`load_threads_contract_artifact(path)` accepts a local regular file no larger
than 32 KiB, rejects symlinks/non-JSON/unknown keys, returns `None` for a missing
or invalid file, and otherwise parses a metadata-only DTO (including a legitimate
pending DTO). Every injected or file-loaded DTO then passes through the same
`validate_threads_contract_artifact(artifact, *, now) -> bool`; injection cannot
bypass validation. It requires artifact version `1`, `status="verified"`, exact
`official_reference_url=OFFICIAL_REFERENCE_URL`, endpoint, `KEYWORD`/`RECENT`,
exact ordered fields, both expected and observed
schema digests equal to the compiled digest, timezone-aware
`now - 30 days <= verified_at <= now + 5 minutes`, `request_count == 1`, and
`result_count == 1`. Naive or farther-future timestamps fail closed. Its DTO/repr
contains metadata only. The compiled schema descriptor is canonical JSON with
`sort_keys=True`, `ensure_ascii=False`, separators `(',', ':')`:

```json
{"data":"list","item":{"has_replies":"boolean","id":"string","is_quote_post":"boolean","permalink":"https_url","quoted_post":"object_or_null_or_absent","reposted_post":"object_or_null_or_absent","text":"string","timestamp":"rfc3339"},"paging":"object_or_absent"}
```

`EXPECTED_SCHEMA_SHA256` is exactly
`0fa67846d3973d130498917d15aa9b9d5d889a894a7c6836c2fab0a5fe26520f`.
`OFFICIAL_REFERENCE_URL` is exactly
`https://www.postman.com/meta/threads/request/34203612-b3b2c12a-7ce6-4d86-a3c6-6d31e3b66ea1`.
The `ThreadsContractArtifact` DTO and verifier candidate use exactly the twelve
keys shown in the JSON below; there is no separate `contract_revision` field.
Add tests for missing, pending, stale, wrong official reference URL, wrong
endpoint, wrong fields, wrong digest, unknown keys, and verified artifacts; the
boolean setting alone can never open egress.

`build_threads_adapter` receives both catalog booleans from the repository's
fresh source/binding reads. The adapter retains only the safe key ID and
fingerprint alongside the secret bytes. Before every page, its egress callback
rechecks `source_key_binding_matches` with those safe values. Tests change key
bytes while retaining the ID and change the ID while retaining the bytes; both
must prevent construction/egress and must not reuse a prior verified gate.

Create `apps/workers/app/adapters/threads/contract.json` in this safe
initial state (it intentionally disables live mode until the real-App smoke):

```json
{
  "artifact_version": 1,
  "status": "pending",
  "official_reference_url": "https://www.postman.com/meta/threads/request/34203612-b3b2c12a-7ce6-4d86-a3c6-6d31e3b66ea1",
  "endpoint": "https://graph.threads.net/keyword_search",
  "search_mode": "KEYWORD",
  "search_type": "RECENT",
  "requested_fields": ["id", "permalink", "text", "timestamp", "is_quote_post", "quoted_post", "reposted_post", "has_replies"],
  "expected_schema_sha256": "0fa67846d3973d130498917d15aa9b9d5d889a894a7c6836c2fab0a5fe26520f",
  "observed_schema_sha256": null,
  "verified_at": null,
  "request_count": 0,
  "result_count": 0
}
```

Include `contract.json` as setuptools package data and resolve an empty setting
with `importlib.resources.files("app.adapters.threads").joinpath("contract.json")`.
The shipped artifact stays pending and therefore fail-closed. Production
activation installs the reviewed verified artifact as a read-only secret/config
mount and sets `THREADS_API_CONTRACT_ARTIFACT_PATH` to that explicit container
path; it never edits the packaged pending file. Add a built-worker image smoke
proving it can load both the packaged pending artifact (adapter disabled) and a
read-only mounted verified fixture (all other gates remain injected/test-only).

The constructor is called only by the dedicated community CLI after `repository.is_source_enabled(SOURCE_KEY)`. It is never registered in `build_runtime_adapters` and never returns `RawSourceItem`.

Define the operator-only `verify_threads_keyword_contract` function in this
adapter task. It requires the real approved App/token and keyword-search
permission, but deliberately does **not** require the not-yet-set
`THREADS_API_CONTRACT_VERIFIED` flag, verified artifact, or database source enablement (avoiding
a circular activation gate). It sends one `RECENT` request with `limit=1` to the
constant endpoint, validates the strict fields/paging contract, persists
nothing to application tables, logs no result/body/URL/token, requires exactly
one validated result, and returns a candidate metadata-only artifact
using the same exact DTO (`artifact_version=1`, `verified|failed`, the exact
official reference URL, request/result counts, endpoint/mode/type/fields,
expected/observed schema digests, and verification time). Task 8 exposes it
through the dedicated community CLI and writes a candidate only to an explicit
operator path using exclusive create with mode `0600`; reject symlinks and any
existing target, fsync the completed file, and remove a partial candidate on
write failure. Never replace an installed artifact. The candidate contains no
token, app/user/post ID, text, permalink, handle, cursor, or media. A reviewer
must compare and install the verified artifact, then set
`THREADS_API_CONTRACT_VERIFIED=true`; both gates default closed. A synthetic
fixture cannot produce an installable verified artifact or satisfy deployment
acceptance.

- [ ] **Step 7: Run adapter, matcher, privacy, and gate tests**

Run: `(cd apps/workers && python -m pytest tests/test_threads_keyword_search_adapter.py tests/test_threads_contract_artifact_smoke.py tests/test_community_matching.py tests/test_community_privacy.py tests/test_adapter_registry_config.py tests/test_adapter_contracts.py -q)`

Expected: PASS with injected egress only and no token/body in captured logs.

Create `apps/workers/tests/fixtures/threads_contract_verified_test_only.json`
with this exact metadata-only test artifact:

```json
{
  "artifact_version": 1,
  "status": "verified",
  "official_reference_url": "https://www.postman.com/meta/threads/request/34203612-b3b2c12a-7ce6-4d86-a3c6-6d31e3b66ea1",
  "endpoint": "https://graph.threads.net/keyword_search",
  "search_mode": "KEYWORD",
  "search_type": "RECENT",
  "requested_fields": ["id", "permalink", "text", "timestamp", "is_quote_post", "quoted_post", "reposted_post", "has_replies"],
  "expected_schema_sha256": "0fa67846d3973d130498917d15aa9b9d5d889a894a7c6836c2fab0a5fe26520f",
  "observed_schema_sha256": "0fa67846d3973d130498917d15aa9b9d5d889a894a7c6836c2fab0a5fe26520f",
  "verified_at": "2026-08-24T00:00:00.000000Z",
  "request_count": 1,
  "result_count": 1
}
```

`app.ops.threads_contract_artifact_smoke` constructs the adapter with all other
gates and key-binding values injected from fixed test-only constants and a
network function that raises if called. `--expect-packaged-pending-disabled`
loads no explicit path and succeeds only when the packaged artifact keeps the
adapter disabled. `--artifact-path PATH --expect-mounted-verified --now VALUE`
succeeds only when the exact mounted DTO validates and constructs the adapter;
neither mode performs HTTP or application-table I/O. The script prints only the
expected safe state. Its unit test covers both modes and proves the verified
fixture is explicitly test-only and cannot be copied as a production acceptance
artifact.

Run these exact built-image gates from the repository root:

```bash
docker build -t flood-risk-threads-contract-smoke:local .
docker run --rm --network none --read-only --workdir /app/apps/workers \
  --entrypoint python flood-risk-threads-contract-smoke:local \
  -m app.ops.threads_contract_artifact_smoke \
  --expect-packaged-pending-disabled
docker run --rm --network none --read-only --workdir /app/apps/workers \
  --mount type=bind,src="$PWD/apps/workers/tests/fixtures/threads_contract_verified_test_only.json",dst=/run/secrets/threads-contract.json,readonly \
  --entrypoint python flood-risk-threads-contract-smoke:local \
  -m app.ops.threads_contract_artifact_smoke \
  --artifact-path /run/secrets/threads-contract.json \
  --expect-mounted-verified --now 2026-08-24T00:00:00.000000Z
```

Expected: both containers exit zero without network access or a writable root
filesystem. The second command proves packaging/mount mechanics only; it does
not satisfy the real-App deployment gate.

- [ ] **Step 8: Commit the official adapter**

```bash
git add apps/workers/app/adapters/threads/__init__.py apps/workers/app/adapters/threads/keyword_search.py apps/workers/app/adapters/threads/contract.json apps/workers/app/ops/threads_contract_artifact_smoke.py apps/workers/app/config.py apps/workers/pyproject.toml apps/workers/tests/fixtures/threads_keyword_search_synthetic.json apps/workers/tests/fixtures/threads_contract_verified_test_only.json apps/workers/tests/test_threads_keyword_search_adapter.py apps/workers/tests/test_threads_contract_artifact_smoke.py apps/workers/tests/test_adapter_registry_config.py apps/workers/tests/test_adapter_contracts.py .env.example
git commit -m "feat: add strictly gated Threads official API adapter"
```

---

### Task 5: Promote User Reports in One Transaction and Suppress Immediately

**Files:**

- Create: `apps/api/app/domain/community/fingerprints.py`
- Create: `apps/api/app/domain/community/user_reports.py`
- Modify: `apps/api/app/core/config.py`
- Modify: `apps/api/app/api/routes/admin.py`
- Modify: `apps/api/app/domain/reports/repository.py`
- Modify: `apps/api/tests/test_admin_contract.py`
- Modify: `apps/api/tests/test_reports_repository.py`
- Modify: `apps/api/tests/test_reports_admin_governance_contract.py`
- Modify: `apps/api/tests/test_reports_contract.py`
- Create: `apps/api/tests/test_community_fingerprints.py`
- Modify: `.env.example`

**Interfaces:**

- Consumes: locked `UserReportModerationRecord`, shared synthetic fingerprint vectors, `community.user_report` DB kill switch, a secret HMAC key, moderation decision, and current time.
- Produces: `build_user_report_signal(...) -> CommunitySignalDraft | None`; one-transaction moderation/audit/promotion; one-transaction redaction/rejection/suppression/recluster; admin-route propagation of one decoded configuration key.

- [ ] **Step 1: Write cross-package vector, duplicate, expiry, transaction, and suppression RED tests**

```python
def test_api_fingerprints_match_shared_vectors() -> None:
    for case in load_vectors()["cases"]:
        assert exact_content_hmac(TEST_KEY, case["text"]) == case["expected_exact_hmac"]
        assert content_lsh(TEST_KEY, case["text"]) == case["expected_content_lsh"]
        if "equivalent" in case:
            assert exact_content_hmac(TEST_KEY, case["equivalent"]) == case["expected_exact_hmac"]
            assert content_lsh(TEST_KEY, case["equivalent"]) == case["expected_content_lsh"]


def test_two_duplicate_reports_share_one_origin_without_identity() -> None:
    first = build_user_report_signal(REPORT_A, now=NOW, fingerprint_key=TEST_KEY)
    second = build_user_report_signal(REPORT_B_SAME_TEXT_AND_POINT, now=NOW, fingerprint_key=TEST_KEY)
    assert first is not None and second is not None
    assert first.origin_hmac == second.origin_hmac
    assert first.id != second.id


def test_report_older_than_retention_is_not_promoted() -> None:
    assert build_user_report_signal(
        old_report(created_at=NOW - timedelta(days=31)),
        now=NOW,
        fingerprint_key=TEST_KEY,
    ) is None


def test_approval_audit_and_signal_share_one_commit() -> None:
    connection.fail_on_signal_insert = True
    with pytest.raises(UserReportRepositoryUnavailable):
        moderate_user_report(
            database_url=URL,
            report_id=REPORT_ID,
            status="approved",
            reason_code="verified_flood_signal",
            actor_ref="moderator",
            promotion_enabled=True,
            community_fingerprint_key=TEST_KEY,
            community_fingerprint_key_id=TEST_KEY_ID,
            connection_factory=lambda: connection,
        )
    assert connection.commits == 0
    assert cursor.report_status == "pending"


@pytest.mark.parametrize(
    ("env_enabled", "db_enabled", "key", "key_id"),
    [
        (False, True, TEST_KEY, TEST_KEY_ID),
        (True, False, TEST_KEY, TEST_KEY_ID),
        (True, True, None, TEST_KEY_ID),
        (True, True, TEST_KEY, None),
    ],
)
def test_report_approval_never_promotes_when_any_gate_is_closed(
    env_enabled, db_enabled, key, key_id
) -> None:
    cursor.source_enabled = db_enabled
    result = moderate_user_report(
        database_url=URL, report_id=REPORT_ID, status="approved",
        reason_code="verified_flood_signal", actor_ref="moderator",
        promotion_enabled=env_enabled, community_fingerprint_key=key,
        community_fingerprint_key_id=key_id,
        connection_factory=lambda: connection,
    )
    assert result.status == "approved"
    assert cursor.community_signal_inserts == 0


@pytest.mark.parametrize("binding", [SAME_ID_NEW_BYTES, NEW_ID_SAME_BYTES])
def test_report_promotion_fails_closed_on_catalog_key_binding_mismatch(
    binding,
) -> None:
    cursor.catalog_key_binding = ACTIVE_DB_BINDING
    moderate_user_report(
        database_url=URL, report_id=REPORT_ID, status="approved",
        reason_code="verified_flood_signal", actor_ref="moderator",
        promotion_enabled=True,
        community_fingerprint_key=binding.key,
        community_fingerprint_key_id=binding.key_id,
        connection_factory=lambda: connection,
    )
    assert cursor.community_signal_inserts == 0


def test_redaction_recomputes_cluster_before_commit() -> None:
    redact_user_report_privacy(
        database_url=URL,
        report_id=REPORT_ID,
        reason_code="reporter_request",
        actor_ref="privacy-operator",
        connection_factory=lambda: connection,
    )
    assert cursor.community_signal_state == "suppressed"
    assert cursor.cluster_state == "unverified"
    assert connection.commits == 1


def test_approved_report_then_rejection_suppresses_derived_id_atomically() -> None:
    promoted_id = approve_report(REPORT_ID, community_fingerprint_key=TEST_KEY)
    reject_report(REPORT_ID, community_fingerprint_key=None)
    assert cursor.suppressed_signal_id == promoted_id
    assert cursor.linked_signal_id_for(REPORT_ID) == promoted_id
    assert cursor.cluster_state == "unverified"


def test_approved_report_redaction_without_or_after_key_rotation_still_suppresses() -> None:
    approve_report(REPORT_ID, community_fingerprint_key=TEST_KEY)
    rotate_or_remove_runtime_key()
    redact_user_report_privacy(
        database_url=URL, report_id=REPORT_ID,
        reason_code="reporter_request", actor_ref="privacy-operator",
        connection_factory=lambda: connection,
    )
    assert connection.commits == 2
    assert cursor.community_signal_state == "suppressed"
    assert cursor.cluster_state == "unverified"


def test_rejection_after_key_rotation_uses_private_persisted_link() -> None:
    promoted_id = approve_report(REPORT_ID, community_fingerprint_key=OLD_KEY)
    reject_report(REPORT_ID, community_fingerprint_key=NEW_KEY)
    assert cursor.linked_signal_id_for(REPORT_ID) == promoted_id
    assert cursor.suppressed_signal_id == promoted_id


def test_repeated_approval_reuses_private_link_and_never_mints_second_id() -> None:
    promoted_id = approve_report(REPORT_ID, community_fingerprint_key=OLD_KEY)
    approve_report(REPORT_ID, community_fingerprint_key=NEW_KEY)
    assert cursor.linked_signal_id_for(REPORT_ID) == promoted_id
    assert cursor.community_signal_ids_for_report(REPORT_ID) == (promoted_id,)


def test_suppressed_link_is_not_resurrected_by_reapproval() -> None:
    promoted_id = approve_then_reject(REPORT_ID)
    approve_report(REPORT_ID, community_fingerprint_key=TEST_KEY)
    assert cursor.linked_signal_id_for(REPORT_ID) == promoted_id
    assert cursor.signal_state(promoted_id) == "suppressed"


monkeypatch.setenv("COMMUNITY_DEDUPE_HMAC_KEY", TEST_KEY.hex())
monkeypatch.setenv("COMMUNITY_DEDUPE_HMAC_KEY_ID", "community-v1")
get_settings.cache_clear()
moderation_response = client.patch(
    "/admin/v1/reports/0d51d545-dc6a-4e4b-8f8e-0e42d454d050/moderation",
    json={"status": "approved", "reason_code": "verified_flood_signal"},
    headers={"Authorization": "Bearer test-admin-token"},
)
redaction_response = client.post(
    "/admin/v1/reports/0d51d545-dc6a-4e4b-8f8e-0e42d454d050/privacy-redaction",
    json={"reason_code": "private_data_exposure"},
    headers={"Authorization": "Bearer test-admin-token"},
)
assert moderation_response.status_code == 200
assert redaction_response.status_code == 200
assert moderation_calls[0]["community_fingerprint_key"] == TEST_KEY
assert moderation_calls[0]["community_fingerprint_key_id"] == "community-v1"
assert "community_fingerprint_key" not in redaction_calls[0]
assert isinstance(get_settings().community_dedupe_hmac_key, bytes)
assert TEST_KEY.hex() not in repr(get_settings())
```

Apply those assertions to both existing admin route tests, and add the absent-env
case proving moderation receives `community_fingerprint_key=None` while
redaction's signature remains key-independent.

- [ ] **Step 2: Run tests and verify missing implementation**

Run: `(cd apps/api && python -m pytest tests/test_community_fingerprints.py tests/test_reports_repository.py tests/test_reports_admin_governance_contract.py tests/test_admin_contract.py -v)`

Expected: FAIL on missing fingerprint/promotion behavior.

- [ ] **Step 3: Implement the API fingerprint module from the same exact algorithm**

Copy the small pure `normalize_content`, `keyed_hmac`, `exact_content_hmac`,
`content_lsh`, `hamming_distance`, and `canonicalize_public_url` implementations
from Task 2 into `apps/api/app/domain/community/fingerprints.py`; do not import
the worker `app` package. Both test suites read every content and `url_cases`
entry in `tests/fixtures/community_fingerprint_vectors.json`, including the
canonical URL HMAC namespace. Add
`community_dedupe_hmac_key: bytes | None = field(repr=False)` and
`community_dedupe_hmac_key_id: str | None` to API settings and import `field`
from `dataclasses`. Accept the ID only when it matches
`[A-Za-z0-9._-]{1,64}`. Retain and reuse the repository's existing
`user_reports_enabled` field and `USER_REPORTS_ENABLED` parsing; do not declare
either a second time. A small config helper decodes
`COMMUNITY_DEDUPE_HMAC_KEY` from hex once while constructing the cached
`Settings`, returns `None` unless the result is at least 32 bytes, and never
includes the secret in validation errors, logs, repr output, or responses.
Treat the ID/key as one binding: if either is missing or invalid, expose both as
`None` to promotion. Compute only `sha256(decoded_key).hexdigest()` for catalog
comparison; never persist the secret.
Keep `USER_REPORTS_ENABLED=false` in `.env.example`; it gates only promotion of
an approved report into `community_signals`, not moderation,
redaction, complaint handling, or suppression of an already-promoted signal.

- [ ] **Step 4: Implement the template-only report builder**

```python
def build_user_report_signal(
    report: UserReportModerationRecord,
    *,
    now: datetime,
    fingerprint_key: bytes,
) -> CommunitySignalDraft | None:
    source_deadline = report.created_at + timedelta(days=30)
    if source_deadline <= now:
        return None
    stable_id = keyed_hmac(
        fingerprint_key, "community-user-report-id-v1", str(report.id)
    )
    location_key = f"{report.lat:.5f}|{report.lng:.5f}"
    exact = exact_content_hmac(fingerprint_key, report.summary)
    origin = keyed_hmac(
        fingerprint_key,
        "community-user-report-origin-v1",
        f"{exact}|{location_key}",
    )
    return CommunitySignalDraft(
        id=stable_id,
        source_key="community.user_report",
        source_url=None,
        canonical_url_hash=stable_id,
        referenced_url_hash=None,
        channel="user_report",
        published_at=report.created_at,
        ingested_at=now,
        matched_flood_terms=("淹水回報",),
        derived_summary="使用者回報此位置可能有積淹水，尚待獨立來源交叉佐證。",
        canonical_location="使用者回報位置",
        admin_code=None,
        lat=report.lat,
        lng=report.lng,
        location_precision="map_click",
        match_basis=("flood_term", "map_click"),
        exact_content_hmac=exact,
        content_lsh=content_lsh(fingerprint_key, report.summary),
        origin_hmac=origin,
        confidence=0.55,
        retention_expires_at=source_deadline,
    )
```

The report summary is used only during this function call. It is never copied to a community row, audit record, log, or response.

Use one shared helper only for initial promotion identity:

```python
def user_report_signal_id(report_id: str, *, fingerprint_key: bytes) -> str:
    return keyed_hmac(
        fingerprint_key, "community-user-report-id-v1", str(report_id)
    )
```

`build_user_report_signal` calls this exact helper/namespace. Rejection,
redaction, complaints, and Task 7 operator suppression must not rederive the ID
from the current key; they use migration 0039's private persisted report link.

- [ ] **Step 5: Replace the single CTE with one explicit transaction**

Retain the public `moderate_user_report` parameters and add the key explicitly:

```python
def moderate_user_report(
    *,
    database_url: str,
    report_id: str,
    status: UserReportModerationStatus,
    reason_code: UserReportModerationReason,
    actor_ref: str,
    promotion_enabled: bool = False,
    community_fingerprint_key: bytes | None = None,
    community_fingerprint_key_id: str | None = None,
    connection_factory: ConnectionFactory | None = None,
) -> UserReportModerationRecord | None:
    with _connect(database_url, connection_factory) as connection:
        with connection.cursor() as cursor:
            _lock_community_mutation(cursor)
            locked = _lock_report(cursor, report_id)
            if locked is None:
                return None
            updated = _update_report_and_insert_audit(
                cursor, locked=locked, status=status,
                reason_code=reason_code, actor_ref=actor_ref,
            )
            if updated.reviewed_at is None:
                raise UserReportRepositoryUnavailable("moderation timestamp was not persisted")
            if status == "approved" and reason_code == "verified_flood_signal":
                enabled = (
                    community_fingerprint_key is not None
                    and community_fingerprint_key_id is not None
                    and _source_enabled_and_key_bound(
                        cursor,
                        "community.user_report",
                        key_id=community_fingerprint_key_id,
                        key_sha256=hashlib.sha256(
                            community_fingerprint_key
                        ).hexdigest(),
                    )
                )
                existing_signal_id = _linked_signal_id_or_none(
                    cursor, report_id=report_id
                )
                if existing_signal_id is None and promotion_enabled and enabled:
                    draft = build_user_report_signal(
                        updated, now=updated.reviewed_at, fingerprint_key=community_fingerprint_key
                    )
                    if draft is not None:
                        _insert_community_signal(cursor, draft)
                        _insert_user_report_link(
                            cursor, report_id=updated.id,
                            community_signal_id=draft.id,
                            linked_at=updated.reviewed_at,
                        )
            else:
                signal_id = _linked_signal_id_or_none(cursor, report_id=report_id)
                _suppress_report_signal_and_recompute(
                    cursor, signal_id=signal_id, reason=reason_code,
                    now=updated.reviewed_at,
                )
        connection.commit()
    return updated
```

Decode `COMMUNITY_DEDUPE_HMAC_KEY` as hex at the API configuration boundary and
pass `None` unless it is at least 32 bytes; never hash a report identifier with
an unkeyed digest. `_source_enabled_and_key_bound` also requires the configured
key ID and derived fingerprint to equal the enabled catalog row metadata in the
same promotion transaction; a byte change under the same ID or an ID change
without the drain protocol creates no signal. Initial promotion inserts
`community_signals` and exactly one
`community_user_report_links(report_id, community_signal_id, linked_at)` row in
the same transaction. `_linked_signal_id_or_none` reads that private FK under
the report/transaction lock. An existing link makes approval idempotently reuse
that identity; it never derives a second ID with a changed key and never
implicitly unsuppresses a rejected signal. It returns `None` only when no public
signal was ever promoted or it has already expired/cascaded. It is never exposed
through API, evidence, snapshots, or logs.

Keep `redact_user_report_privacy`'s existing public signature; it does not need
the current HMAC key. It uses the same connection/cursor pattern: lock
the exact shared transaction advisory key
`"flood-risk:v1:community-mutation"` before any report/signal write, lock the
report, read the private persisted link, redact the report, insert audit,
suppress the linked
community signal by that ID, recompute or
delete the affected cluster, then one commit. Failure rolls back every change.
Pending reports never create links or signals. A false `USER_REPORTS_ENABLED`,
disabled DB source, or missing key leaves ordinary moderation functional and
creates no new public signal. It never blocks rejection/redaction/suppression of
a previously promoted signal because that path uses the persisted link.

Define the API-side `_lock_community_mutation` with the same literal and
`pg_advisory_xact_lock(hashtextextended(%s, 0))` SQL as Task 3; API code does not
import the worker package. A cross-package contract test reads both constants
and fails if they diverge. Approval promotion, rejection, and privacy redaction
all take this lock before locking rows or changing moderation/audit/signal
state.

Wire the decoded key through both production admin callers in
`apps/api/app/api/routes/admin.py`:

```python
report = moderate_user_report(
    database_url=settings.database_url,
    report_id=str(report_id),
    status=request.status,
    reason_code=request.reason_code,
    actor_ref=admin_actor,
    promotion_enabled=settings.user_reports_enabled,
    community_fingerprint_key=settings.community_dedupe_hmac_key,
    community_fingerprint_key_id=settings.community_dedupe_hmac_key_id,
)
redaction = redact_user_report_privacy(
    database_url=settings.database_url,
    report_id=str(report_id),
    reason_code=request.reason_code,
    actor_ref=admin_actor,
)
```

Update the exact-call assertions in `test_admin_contract.py` and
`test_reports_admin_governance_contract.py`; moderation passes decoded bytes
when configured and `None` when absent plus the existing parsed
`USER_REPORTS_ENABLED` boolean, while redaction retains its old signature and
receives no key. Redaction/rejection suppression remains
available even when that promotion gate is false. The route must not call
`bytes.fromhex` or read the environment directly.

- [ ] **Step 6: Run report and privacy suites**

Run: `(cd apps/api && python -m pytest tests/test_community_fingerprints.py tests/test_reports_repository.py tests/test_reports_admin_governance_contract.py tests/test_admin_contract.py tests/test_reports_contract.py -q)`

Expected: PASS.

- [ ] **Step 7: Commit report promotion without touching migration 0039**

```bash
git add apps/api/app/domain/community/fingerprints.py apps/api/app/domain/community/user_reports.py apps/api/app/core/config.py apps/api/app/api/routes/admin.py apps/api/app/domain/reports/repository.py apps/api/tests/test_community_fingerprints.py apps/api/tests/test_reports_repository.py apps/api/tests/test_reports_admin_governance_contract.py apps/api/tests/test_admin_contract.py apps/api/tests/test_reports_contract.py .env.example
git commit -m "feat: promote and suppress sanitized user reports atomically"
```

---

### Task 6: Build Stable Origin Groups, Clusters, Corroboration, and Fixture Integration

**Files:**

- Create: `apps/workers/app/community/corroboration.py`
- Create: `apps/workers/app/official_signal_policy.py`
- Create: `apps/workers/tests/test_community_corroboration.py`
- Create: `apps/workers/tests/test_community_repository_postgres.py`
- Create: `apps/workers/tests/test_community_fixture_integration.py`
- Modify: `apps/workers/app/community/contracts.py`
- Modify: `apps/workers/app/community/repository.py`
- Modify: `apps/workers/app/pipelines/promotion.py`
- Modify: `apps/workers/tests/test_promotion_pipeline.py`

**Interfaces:**

- Consumes: active unsuppressed signal fingerprints/URLs, compatible official anomalies, current time, and repository transactions.
- Produces: complete cluster DTOs, deterministic origin equivalence, stable anchor-based `cluster_key`, official compatibility, `replace_active_clusters`, and immediate recomputation.

- [ ] **Step 1: Add complete cluster contracts**

```python
# append to apps/workers/app/community/contracts.py
@dataclass(frozen=True)
class ClusterInputSignal:
    signal_id: str
    source_key: str
    canonical_url_hash: str
    referenced_url_hash: str | None
    exact_content_hmac: str
    content_lsh: str
    origin_hmac: str
    published_at: datetime
    lat: float
    lng: float
    admin_code: str | None
    canonical_location: str
    matched_flood_terms: tuple[str, ...]
    moderation_state: ModerationState
    retention_expires_at: datetime


@dataclass(frozen=True)
class OfficialAnomalyRef:
    evidence_id: str
    source_key: str
    event_type: Literal["rainfall", "water_level", "flood_warning", "flood_report"]
    observed_at: datetime
    geometry: dict[str, Any]
    location_precision: Literal["point", "admin_area", "polygon"]
    admin_code: str | None
    active_from: datetime
    active_until: datetime
    compatible_cluster_keys: tuple[str, ...]


@dataclass(frozen=True)
class OfficialEvidenceRecord:
    id: str
    source_key: str
    source_type: str
    event_type: Literal["rainfall", "water_level", "flood_warning", "flood_report"] | str
    observed_at: datetime | None
    geometry: dict[str, Any] | None
    location_precision: str
    admin_code: str | None
    freshness_threshold_seconds: int | None
    realtime_risk_factor: float | None
    rainfall_mm_1h: float | None
    water_level_m: float | None
    warning_level_m: float | None
    flood_depth_cm: float | None
    effective_at: datetime | None
    expires_at: datetime | None
    cap_status: str | None


@dataclass(frozen=True)
class ClusterDecision:
    cluster_key: str
    signal_ids: tuple[str, ...]
    canonical_location: str
    admin_code: str | None
    lat: float
    lng: float
    window_started_at: datetime
    window_ended_at: datetime
    flood_term_classes: tuple[str, ...]
    distinct_original_source_count: int
    corroboration_state: CorroborationState
    official_evidence_ids: tuple[str, ...]
    first_observed_at: datetime
    last_observed_at: datetime


@dataclass(frozen=True)
class CorroborationDecision:
    state: CorroborationState
    official_evidence_ids: tuple[str, ...]
```

- [ ] **Step 2: Write truth-table, stable-key, split/merge, official, suppression, and integration RED tests**

```python
def test_repost_reference_exact_and_near_duplicate_count_once() -> None:
    decision = cluster_signals(
        (ORIGINAL, SAME_REFERENCE, SAME_EXACT_HMAC, NEAR_DUPLICATE), now=NOW
    )[0]
    assert decision.distinct_original_source_count == 1
    assert decision.corroboration_state == "unverified"


def test_two_independent_origins_are_community_corroborated() -> None:
    decision = cluster_signals((THREADS_ORIGINAL, USER_REPORT), now=NOW)[0]
    assert decision.distinct_original_source_count == 2
    assert decision.corroboration_state == "community_corroborated"


def test_cluster_key_uses_stable_smallest_signal_anchor() -> None:
    first = cluster_signals((SIGNAL_B, SIGNAL_C), now=NOW)[0]
    second = cluster_signals((SIGNAL_A, SIGNAL_B, SIGNAL_C), now=NOW)[0]
    assert first.cluster_key == cluster_key(min(SIGNAL_B.signal_id, SIGNAL_C.signal_id))
    assert second.cluster_key == cluster_key(SIGNAL_A.signal_id)


def test_only_fresh_qualifying_official_anomaly_corroborates() -> None:
    cluster = cluster_signals((THREADS_ORIGINAL,), now=NOW)[0]
    decision = corroborate_cluster(
        cluster,
        (NEARBY_FRESH_FLOOD_ANOMALY, HISTORICAL_EVENT, STATUS_ONLY_EVENT, STALE_EVENT),
        now=NOW,
    )
    assert decision.state == "officially_corroborated"
    assert decision.official_evidence_ids == (NEARBY_FRESH_FLOOD_ANOMALY.evidence_id,)


def test_cap_polygon_intersecting_cluster_radius_does_not_use_centroid() -> None:
    # The reviewed CAP polygon reaches the cluster radius while its point on
    # surface/centroid is more than 1 km away.
    official = repository.load_qualifying_official_anomalies(
        clusters=(EDGE_CLUSTER,), now=NOW
    )
    assert official[0].compatible_cluster_keys == (EDGE_CLUSTER.cluster_key,)
    assert corroborate_cluster(EDGE_CLUSTER, official, now=NOW).state == "officially_corroborated"


def test_source_freshness_and_persisted_metrics_fail_closed() -> None:
    assert official_anomaly_from_evidence(STALE_RAIN, now=NOW) is None
    assert official_anomaly_from_evidence(FRESH_DRY_RAIN, now=NOW) is None
    assert official_anomaly_from_evidence(MISMATCHED_PERSISTED_FACTOR, now=NOW) is None


def test_active_old_cap_qualifies_until_expiry_but_expired_cap_does_not() -> None:
    assert official_anomaly_from_evidence(ACTIVE_CAP, now=NOW) is not None
    assert official_anomaly_from_evidence(EXPIRED_CAP, now=NOW) is None


def test_suppressed_or_expired_signals_never_enter_components() -> None:
    assert cluster_signals((SUPPRESSED, EXPIRED), now=NOW) == ()


def test_synthetic_threads_fixture_reaches_sanitized_cluster_without_raw_text() -> None:
    page = parse_threads_search_page(
        load_synthetic_page(),
        source_key=SOURCE_KEY,
        window_start=NOW - timedelta(hours=6),
        window_end=NOW,
    )
    signals = fixture_adapter(page).search(
        query="臺南 淹水",
        contexts=(tainan_admin_context(),),
        since=NOW - timedelta(hours=6),
        until=NOW,
        now=NOW,
    )
    repository.upsert_signals(signals)
    with repository.cluster_mutation(now=NOW) as mutation:
        scope = mutation.load_active_cluster_inputs(now=NOW)
        decisions = cluster_signals(scope.signals, now=NOW)
        mutation.replace_active_clusters(decisions, scope=scope, now=NOW)
    assert repository.cluster_count == 1
    assert SYNTHETIC_FULL_TEXT not in repr(repository.all_params)


def test_recompute_keyset_pages_past_500_without_deleting_unseen_links() -> None:
    seed_active_signals(501)
    seed_unrelated_cluster_link()
    with repository.community_cycle_lock() as acquired:
        assert acquired
        with repository.cluster_mutation(now=NOW) as mutation:
            scope = mutation.load_active_cluster_inputs(now=NOW, page_size=500)
            assert len(scope.signals) == 501
            assert scope.complete is True
            decisions = cluster_signals(scope.signals, now=NOW)
            mutation.replace_active_clusters(decisions, scope=scope, now=NOW)
    assert repository.signal_link(SIGNAL_501) is not None
    assert repository.unrelated_cluster_link_exists()
```

- [ ] **Step 3: Run tests and verify missing types/module**

Run: `(cd apps/workers && python -m pytest tests/test_community_corroboration.py tests/test_community_fixture_integration.py -v)`

Expected: FAIL during import.

- [ ] **Step 4: Implement origin equivalence and stable grouping**

```python
# apps/workers/app/community/corroboration.py
import dataclasses
import hashlib
import math
from collections.abc import Callable
from datetime import datetime, timedelta

from app.community.contracts import (
    ClusterDecision,
    ClusterInputSignal,
    CorroborationDecision,
    CorroborationState,
    OfficialAnomalyRef,
    OfficialEvidenceRecord,
)
from app.community.fingerprints import hamming_distance
from app.official_signal_policy import official_realtime_risk_factor

NEAR_DUPLICATE_HAMMING_MAX = 8


def haversine_m(left_lat: float, left_lng: float, right_lat: float, right_lng: float) -> float:
    lat1, lat2 = math.radians(left_lat), math.radians(right_lat)
    delta_lat = lat2 - lat1
    delta_lng = math.radians(right_lng - left_lng)
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lng / 2) ** 2
    )
    return 6_371_000 * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def same_origin(left: ClusterInputSignal, right: ClusterInputSignal) -> bool:
    if left.origin_hmac == right.origin_hmac:
        return True
    left_urls = {left.canonical_url_hash}
    right_urls = {right.canonical_url_hash}
    if left.referenced_url_hash is not None:
        left_urls.add(left.referenced_url_hash)
    if right.referenced_url_hash is not None:
        right_urls.add(right.referenced_url_hash)
    if left_urls & right_urls:
        return True
    if left.exact_content_hmac == right.exact_content_hmac:
        return True
    return hamming_distance(left.content_lsh, right.content_lsh) <= NEAR_DUPLICATE_HAMMING_MAX


def cluster_key(anchor_signal_id: str) -> str:
    return hashlib.sha256(f"community-cluster-v1|{anchor_signal_id}".encode()).hexdigest()


def _distance_m(left: ClusterInputSignal, right: ClusterInputSignal) -> float:
    return haversine_m(left.lat, left.lng, right.lat, right.lng)


def _can_share_event(
    left: ClusterInputSignal,
    right: ClusterInputSignal,
    *,
    time_window: timedelta,
    distance_m: int,
) -> bool:
    if abs(left.published_at - right.published_at) > time_window:
        return False
    if left.admin_code and right.admin_code and left.admin_code != right.admin_code:
        return False
    return _distance_m(left, right) <= distance_m


def _components(
    signals: tuple[ClusterInputSignal, ...],
    *,
    equivalent: Callable[[ClusterInputSignal, ClusterInputSignal], bool],
) -> tuple[tuple[ClusterInputSignal, ...], ...]:
    ordered = tuple(sorted(signals, key=lambda item: item.signal_id))
    parent = list(range(len(ordered)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    for left in range(len(ordered)):
        for right in range(left + 1, len(ordered)):
            if equivalent(ordered[left], ordered[right]):
                union(left, right)
    groups: dict[int, list[ClusterInputSignal]] = {}
    for index, signal in enumerate(ordered):
        groups.setdefault(find(index), []).append(signal)
    return tuple(tuple(groups[key]) for key in sorted(groups))


def connected_spatiotemporal_components(
    signals: tuple[ClusterInputSignal, ...],
    *,
    time_window: timedelta,
    distance_m: int,
) -> tuple[tuple[ClusterInputSignal, ...], ...]:
    return _components(
        signals,
        equivalent=lambda left, right: _can_share_event(
            left, right, time_window=time_window, distance_m=distance_m
        ),
    )


def deterministic_origin_groups(
    signals: tuple[ClusterInputSignal, ...],
    *,
    equivalent: Callable[[ClusterInputSignal, ClusterInputSignal], bool],
) -> tuple[tuple[ClusterInputSignal, ...], ...]:
    return _components(signals, equivalent=equivalent)


def build_cluster_decision(
    component: tuple[ClusterInputSignal, ...],
    *,
    cluster_key: str,
    distinct_origins: int,
) -> ClusterDecision:
    ordered = tuple(sorted(component, key=lambda item: (item.published_at, item.signal_id)))
    anchor = ordered[0]
    terms = tuple(sorted({term for signal in component for term in signal.matched_flood_terms}))
    state: CorroborationState = (
        "community_corroborated" if distinct_origins >= 2 else "unverified"
    )
    return ClusterDecision(
        cluster_key=cluster_key,
        signal_ids=tuple(sorted(signal.signal_id for signal in component)),
        canonical_location=anchor.canonical_location,
        admin_code=anchor.admin_code,
        lat=sum(signal.lat for signal in component) / len(component),
        lng=sum(signal.lng for signal in component) / len(component),
        window_started_at=min(signal.published_at for signal in component),
        window_ended_at=max(signal.published_at for signal in component),
        flood_term_classes=terms[:10],
        distinct_original_source_count=distinct_origins,
        corroboration_state=state,
        official_evidence_ids=(),
        first_observed_at=min(signal.published_at for signal in component),
        last_observed_at=max(signal.published_at for signal in component),
    )


def cluster_signals(
    signals: tuple[ClusterInputSignal, ...],
    *,
    now: datetime,
    time_window: timedelta = timedelta(hours=6),
    distance_m: int = 1000,
) -> tuple[ClusterDecision, ...]:
    active = tuple(
        signal for signal in signals
        if signal.moderation_state in {"unverified", "accepted"}
        and signal.retention_expires_at > now
    )
    components = connected_spatiotemporal_components(
        active, time_window=time_window, distance_m=distance_m
    )
    decisions: list[ClusterDecision] = []
    for component in components:
        origins = deterministic_origin_groups(component, equivalent=same_origin)
        anchor = min(signal.signal_id for signal in component)
        decisions.append(build_cluster_decision(
            component,
            cluster_key=cluster_key(anchor),
            distinct_origins=len(origins),
        ))
    return tuple(sorted(decisions, key=lambda item: item.cluster_key))
```

`connected_spatiotemporal_components` requires overlapping time windows and compatible admin codes plus either compatible canonical area or Haversine distance within the bound. It iterates signals sorted by ID and returns sorted components. `deterministic_origin_groups` uses union-find with roots selected by smallest signal ID, making exact/near-duplicate decisions reproducible.

- [ ] **Step 5: Implement a source-fresh, geometry-aware official anomaly factory**

```python
QUALIFYING_OFFICIAL_EVENTS = {"rainfall", "water_level", "flood_warning", "flood_report"}
DEFAULT_STATION_FRESHNESS_SECONDS = 600
MAX_FUTURE_SKEW = timedelta(minutes=5)


def official_anomaly_from_evidence(
    record: OfficialEvidenceRecord,
    *,
    now: datetime,
    compatible_cluster_keys: tuple[str, ...] = (),
) -> OfficialAnomalyRef | None:
    if record.source_type != "official":
        return None
    if record.event_type not in QUALIFYING_OFFICIAL_EVENTS:
        return None
    if record.observed_at is None or record.observed_at > now + MAX_FUTURE_SKEW:
        return None
    if record.geometry is None or record.location_precision not in {
        "point", "admin_area", "polygon"
    }:
        return None

    computed = official_realtime_risk_factor(
        event_type=record.event_type,
        rainfall_mm_1h=record.rainfall_mm_1h,
        water_level_m=record.water_level_m,
        warning_level_m=record.warning_level_m,
        flood_depth_cm=record.flood_depth_cm,
    )
    if (
        computed is None
        or computed <= 0
        or record.realtime_risk_factor is None
        or not math.isclose(record.realtime_risk_factor, computed, abs_tol=1e-6)
    ):
        return None

    if record.event_type == "flood_warning":
        if (
            (record.cap_status or "").casefold() != "actual"
            or record.effective_at is None
            or record.expires_at is None
            or not (record.effective_at <= now < record.expires_at)
        ):
            return None
        active_from, active_until = record.effective_at, record.expires_at
    else:
        threshold = record.freshness_threshold_seconds or DEFAULT_STATION_FRESHNESS_SECONDS
        if threshold <= 0:
            return None
        active_from = record.observed_at
        active_until = record.observed_at + timedelta(seconds=threshold)
        if now >= active_until:
            return None

    return OfficialAnomalyRef(
        evidence_id=record.id,
        source_key=record.source_key,
        event_type=record.event_type,
        observed_at=record.observed_at,
        geometry=record.geometry,
        location_precision=record.location_precision,
        admin_code=record.admin_code,
        active_from=active_from,
        active_until=active_until,
        compatible_cluster_keys=compatible_cluster_keys,
    )


def corroborate_cluster(
    cluster: ClusterDecision,
    official: tuple[OfficialAnomalyRef, ...],
    *,
    now: datetime,
) -> CorroborationDecision:
    compatible = tuple(
        item for item in official
        if time_location_event_compatible(item, cluster, now=now)
    )
    if compatible:
        return CorroborationDecision(
            state="officially_corroborated",
            official_evidence_ids=tuple(dict.fromkeys(item.evidence_id for item in compatible)),
        )
    if cluster.distinct_original_source_count >= 2:
        return CorroborationDecision("community_corroborated", ())
    return CorroborationDecision("unverified", ())


def time_location_event_compatible(
    item: OfficialAnomalyRef,
    cluster: ClusterDecision,
    *,
    now: datetime,
) -> bool:
    if not (item.active_from <= now < item.active_until):
        return False
    if item.admin_code and cluster.admin_code and item.admin_code != cluster.admin_code:
        return False
    if item.active_from > cluster.window_ended_at + timedelta(hours=1):
        return False
    if item.active_until < cluster.window_started_at - timedelta(hours=1):
        return False
    return (
        item.event_type in QUALIFYING_OFFICIAL_EVENTS
        and cluster.cluster_key in item.compatible_cluster_keys
    )


def attach_corroboration(
    cluster: ClusterDecision,
    corroboration: CorroborationDecision,
) -> ClusterDecision:
    return dataclasses.replace(
        cluster,
        corroboration_state=corroboration.state,
        official_evidence_ids=corroboration.official_evidence_ids,
    )
```

Historical, flood-potential, news, derived, stale, future, status-only, malformed, and non-anomalous rows always return `None` from the factory.

Move the exact rainfall/water/flood-depth/warning factor calculation currently
inside promotion into `app.official_signal_policy.official_realtime_risk_factor`
without changing thresholds. Promotion and community qualification both import
that pure helper. Community requires the persisted latest factor to equal the
factor recomputed from persisted metrics; missing or inconsistent values fail
closed rather than trusting an undefined `is_qualifying_anomaly` label.

`load_qualifying_official_anomalies` accepts the base cluster decisions. Its
bounded SQL joins enabled `data_sources`, `official_realtime_latest`, and linked
`evidence`; selects source-specific `freshness_threshold_seconds`, CAP
effective/expiry/status, metrics, factor, admin code, precision, and
`ST_AsGeoJSON(COALESCE(evidence.geom, latest.geom))`; and rejects invalid/empty
geometry. It cross-joins only the bounded cluster values and computes compatible
keys with `ST_DWithin(COALESCE(evidence.geom, latest.geom)::geography,
cluster_point::geography, 1000)`, plus compatible admin codes. Thus a reviewed
CAP/admin polygon that contains or intersects the cluster radius matches even
when its point-on-surface is distant; point evidence still uses the same exact
metre rule. It then calls the factory above—never a database boolean—to produce
refs.

- [ ] **Step 6: Persist stable clusters and one link per signal**

Extend the repository protocol and implement these exact concrete methods:

```python
@dataclass(frozen=True)
class ClusterInputScope:
    signals: tuple[ClusterInputSignal, ...]
    locked_signal_ids: tuple[str, ...]
    complete: bool


class CommunityClusterMutation(Protocol):
    def load_active_cluster_inputs(
        self, *, now: datetime, page_size: int = 500,
        max_active_signals: int = 10_000,
    ) -> ClusterInputScope: ...

    def load_qualifying_official_anomalies(
        self, *, clusters: tuple[ClusterDecision, ...], now: datetime,
        limit: int = 200,
    ) -> tuple[OfficialAnomalyRef, ...]: ...

    def replace_active_clusters(
        self, decisions: tuple[ClusterDecision, ...], *,
        scope: ClusterInputScope, now: datetime,
    ) -> None: ...


def cluster_mutation(
    self, *, now: datetime
) -> AbstractContextManager[CommunityClusterMutation]: ...
```

The ellipses above belong only to the protocol excerpt. The concrete methods are
complete in this step. `cluster_mutation` opens one connection/transaction,
acquires `COMMUNITY_MUTATION_LOCK_NAME`, and yields methods bound to that same
cursor; it commits only after replacement succeeds and otherwise rolls back.
Within that context, `load_active_cluster_inputs` rechecks enabled source,
moderation, expiry, and active suppression, reads every qualifying row with
`signal.id > after_id`
keyset pages (never OFFSET or a single LIMIT), and adds currently linked but now
inactive IDs to `locked_signal_ids` so their obsolete links can be cleared. It
sets `complete=True` only after a terminal empty page. More than
`max_active_signals` raises `CommunityClusterCapacityExceeded` before any
replacement and leaves existing clusters untouched; it never silently truncates.
Load, official qualification, and replacement therefore share one snapshot and
one mutation lock. Worker suppression/retention and API user-report
moderation/redaction/operator suppression acquire the identical transaction lock
in their own transactions.

`load_qualifying_official_anomalies` uses the geometry query and calls
`official_anomaly_from_evidence` instead of trusting a row label.
`replace_active_clusters` rejects an incomplete scope, locks exactly
`scope.locked_signal_ids` in ID order, rejects any decision ID outside that
scope or one ID in two clusters, upserts cluster keys, clears obsolete links
only for scoped IDs, applies one link per scoped active signal, and deletes only
clusters left with zero links. It never clears a row merely because it was not
present in one page. Suppression/retention use this same full-keyset helper; API
query-scoped corroboration in Task 7 additionally prevents an over-capacity
stale global cluster from affecting public risk.

Add a two-connection race regression with a barrier between cluster-input load
and replacement. If replacement owns the mutation lock first, suppression waits
then unlinks/recomputes after replacement; if suppression owns it first, the
cluster transaction loads only the suppressed state. In both orders the final
signal is suppressed, has no cluster link, and the cluster is unverified or
deleted. The exact global topology is: `community_cycle_lock` holds the
session-level owner lock on dedicated connection A for the whole worker cycle;
that cycle may later open transaction connection B and acquire
`COMMUNITY_MUTATION_LOCK_NAME`. The keys differ and the sole permitted order is
owner lock → mutation lock. No path holding the mutation lock may request the
owner lock; API paths request only the mutation lock; suppression, retention,
and clustering reuse their one mutation transaction/cursor after acquiring it.
Add a topology regression that asserts the two connections, this acquisition
order, absence of every inverse path, and unconditional release of both on
exceptions. Do not collapse the session owner into the transaction, which
would release ownership between fetch and replacement.

Put the two-connection mutation/suppression race and cycle-owner topology tests
in `test_community_repository_postgres.py`. They may skip during a focused
developer run only when `COMMUNITY_TEST_DATABASE_URL` is absent and
`COMMUNITY_DB_ACCEPTANCE_REQUIRED` is not `1`; when that completion sentinel is
`1`, absence of the URL is an assertion failure, never a skip.

- [ ] **Step 7: Run clustering, repository, promotion, and fixture integration tests**

Run: `(cd apps/workers && python -m pytest tests/test_community_corroboration.py tests/test_community_repository.py tests/test_community_repository_postgres.py tests/test_community_fixture_integration.py tests/test_promotion_pipeline.py -q)`

Run: `(cd apps/workers && python -m ruff check app/community/corroboration.py app/community/repository.py app/official_signal_policy.py app/pipelines/promotion.py tests/test_community_corroboration.py tests/test_promotion_pipeline.py)`

Expected: PASS.

- [ ] **Step 8: Commit stable corroboration**

```bash
git add apps/workers/app/community/contracts.py apps/workers/app/community/corroboration.py apps/workers/app/community/repository.py apps/workers/app/official_signal_policy.py apps/workers/app/pipelines/promotion.py apps/workers/tests/test_community_corroboration.py apps/workers/tests/test_community_repository_postgres.py apps/workers/tests/test_community_fixture_integration.py apps/workers/tests/test_promotion_pipeline.py
git commit -m "feat: build stable corroborated community clusters"
```

---

### Task 7: Add Sanitized Reads, Assessment Association, One Uplift Seam, and Operator Suppression

**Files:**

- Create: `apps/api/app/domain/community/repository.py`
- Create: `apps/api/app/domain/community/uplift.py`
- Create: `apps/api/tests/test_community_repository.py`
- Create: `apps/api/tests/test_community_repository_postgres.py`
- Create: `apps/api/tests/test_community_uplift.py`
- Create: `apps/api/tests/test_community_assessment_integration.py`
- Modify: `apps/api/app/domain/community/models.py`
- Modify: `apps/api/app/domain/assessment/repository.py`
- Modify: `apps/api/app/api/services/assessment.py`
- Modify: `apps/api/app/domain/evidence/repository.py`
- Modify: `apps/api/app/api/services/public_evidence.py`
- Modify: `apps/api/app/api/routes/admin.py`
- Modify: `apps/api/app/main.py`
- Modify: `apps/api/app/api/schemas.py`
- Modify: `docs/api/openapi.yaml`
- Modify: `apps/api/tests/test_assessment_repository.py`
- Modify: `apps/api/tests/test_assessment_service.py`
- Modify: `apps/api/tests/test_public_contract.py`
- Modify: `apps/api/tests/test_public_evidence_cache.py`
- Modify: `apps/api/tests/test_main.py`

**Interfaces:**

- Consumes: active metadata-only signals/clusters, core `RiskScoringResult`, core `OverallDecision`, core two-argument `AssessmentService`, and operator-authenticated suppression requests.
- Produces: `query_active_community_snapshot`, a separate repository community read (without changing core `AssessmentData`), priority/suppression/association helpers, assessment evidence union, the additive static API contract, and the sole `apply_community_uplift` call after core `compose_base_overall(realtime_scoring, historical_scoring)`.

- [ ] **Step 1: Complete API decision and persistence models**

```python
# append to apps/api/app/domain/community/models.py
from app.domain.assessment.models import OverallDecision, RiskLevel


@dataclass(frozen=True)
class CommunityDecision:
    state: CommunityState
    level: RiskLevel
    reasons: tuple[str, ...]

    @classmethod
    def none(cls) -> "CommunityDecision":
        return cls(state="none", level="未知", reasons=())


@dataclass(frozen=True)
class CommunityUpliftDecision:
    overall: OverallDecision
    community: CommunityDecision


@dataclass(frozen=True)
class CommunityPriorityResult:
    state: Literal["prioritized", "idle", "not_available"]
    last_completed_at: datetime | None


@dataclass(frozen=True)
class CommunityAssessmentBinding:
    signal_id: str
    corroboration_state: Literal[
        "unverified", "community_corroborated", "officially_corroborated"
    ]
```

Do **not** add community fields to core `AssessmentData` or change its official/current/history read. Add `AssessmentRepository.load_community_snapshot(*, lat, lng, radius_m, as_of, eligible_official_evidence_ids) -> CommunitySnapshot` as a separate method on the existing repository object. The ID set comes only from the already radius/as-of/catalog-filtered `data.current_official`; it is empty when that core read is unavailable. Add defaulted `community_signal_bindings: tuple[CommunityAssessmentBinding, ...] = ()` to `RiskAssessmentPersistence` and update all constructors explicitly. There is no parallel `community_signal_ids` field.

Append constructor-compatible defaults to the core evidence contracts in this
task, because both assessment previews and the already-live detail route need a
single typed conversion before Task 10 renders them:

```python
# EvidenceRecord
published_at: datetime | None = None
source_label: str | None = None
community_state: CorroborationState | None = None

# EvidencePreview / Evidence
published_at: datetime | None = None
source_label: str | None = None
community_state: CorroborationState | None = None
```

Retain existing `raw_ref`, `location_precision`, and `limitations` fields; do not
duplicate them. Generic SQL branches select typed `NULL` for these three new
columns. The community UNION selects them in the identical position/order, and
`_record_from_row` handles both mapping and positional rows.

Publish these additive properties in both static `EvidencePreview` and
`Evidence` schemas in this task, because both endpoints can return community
records before Task 10 changes their visual rendering. Replace the static
`id: {type: string, format: uuid}` in both schemas with this exact output union:

```yaml
id:
  oneOf:
    - type: string
      format: uuid
    - type: string
      pattern: "^[0-9a-f]{64}$"
```

Keep the constructor-compatible Pydantic `id: str` during the rolling migration
but require `evidence_from_community_signal` to reject any community ID that is
not lowercase 64-hex. Add static-schema tests proving an existing UUID evidence
item and a 64-hex community item both validate, while any other community ID
does not. Run `infra/scripts/validate_openapi.py` in this task; Task 10 consumes
and re-verifies this contract rather than introducing it later.

- [ ] **Step 2: Write visibility, association, evidence-union, suppression, and non-blocking RED tests**

```python
def test_snapshot_excludes_suppressed_rejected_expired_and_disabled_sources() -> None:
    snapshot = query_active_community_snapshot(
        database_url=URL, lat=22.9997, lng=120.2270,
        radius_m=1000, now=NOW, eligible_official_evidence_ids=frozenset(),
        connection_factory=lambda: connection,
    )
    assert [item.id for item in snapshot.signals] == [ACTIVE_SIGNAL_ID]
    assert [item.id for item in snapshot.clusters] == [ACTIVE_CLUSTER_ID]
    assert "suppressed_sources" in cursor.all_sql
    assert "data_sources" in cursor.all_sql


def test_snapshot_uses_exact_metres_and_clusters_only_in_radius_signals() -> None:
    snapshot = query_active_community_snapshot(
        database_url=POSTGIS_URL, lat=QUERY_LAT, lng=QUERY_LNG,
        radius_m=1000, now=NOW, eligible_official_evidence_ids=frozenset(),
        connection_factory=postgres_fixture,
    )
    assert JUST_INSIDE_SIGNAL_ID in {item.id for item in snapshot.signals}
    assert JUST_OUTSIDE_SIGNAL_ID not in {item.id for item in snapshot.signals}
    assert OUTSIDE_ONLY_CLUSTER_ID not in {item.id for item in snapshot.clusters}


def test_cluster_corroboration_is_recomputed_inside_selected_radius() -> None:
    snapshot = query_active_community_snapshot(
        database_url=POSTGIS_URL,
        lat=QUERY_LAT,
        lng=QUERY_LNG,
        radius_m=50,
        now=NOW,
        eligible_official_evidence_ids=frozenset({INSIDE_OFFICIAL_ID}),
        connection_factory=mixed_cluster_fixture,
    )
    cluster = snapshot.clusters[0]
    assert {item.id for item in snapshot.signals} == {INSIDE_SINGLE_ORIGIN_ID}
    assert OUTSIDE_SECOND_ORIGIN_ID not in {item.id for item in snapshot.signals}
    assert OUTSIDE_OFFICIAL_ID not in cluster.official_evidence_ids
    assert cluster.distinct_original_source_count == 1
    assert cluster.corroboration_state == "unverified"
    inside_signal = next(item for item in snapshot.signals if item.id == INSIDE_SINGLE_ORIGIN_ID)
    assert inside_signal.corroboration_state == "unverified"
    assert evidence_from_community_signal(inside_signal).community_state == "unverified"


def test_assessment_persistence_links_sanitized_signal_ids() -> None:
    repository.persist(ASSESSMENT_WITH_COMMUNITY)
    assert cursor.assessment_community_ids == (ACTIVE_SIGNAL_ID,)
    assert RAW_THREADS_TEXT not in repr(cursor.all_params)


def test_community_association_failure_rolls_back_whole_assessment_write() -> None:
    connection.fail_on_community_association = True
    with pytest.raises(EvidenceRepositoryUnavailable):
        repository.persist(ASSESSMENT_WITH_COMMUNITY)
    assert connection.commits == 0
    assert cursor.inserted_assessment_ids == ()
    assert cursor.generic_association_ids == ()


def test_preview_and_detail_share_the_same_query_scoped_state() -> None:
    response = service_with_mixed_inside_outside_global_cluster().assess(REQUEST_50M, now=NOW)
    preview = next(item for item in response.evidence if item.id == INSIDE_SINGLE_ORIGIN_ID)
    detail = next(
        item for item in client.get(f"/v1/evidence/{response.assessment_id}").json()["items"]
        if item["id"] == INSIDE_SINGLE_ORIGIN_ID
    )
    assert preview.community_state == "unverified"
    assert detail["community_state"] == preview.community_state


def test_expanded_evidence_unions_sanitized_community_rows() -> None:
    items = fetch_assessment_evidence(
        database_url=URL,
        assessment_id=ASSESSMENT_ID,
        page_size=20,
        connection_factory=lambda: connection,
    )
    community = next(item for item in items if item.source_type == "social")
    assert community.raw_ref is None
    assert community.summary == TEMPLATE_SUMMARY
    assert community.published_at == SIGNAL_PUBLISHED_AT
    assert community.source_label == "Threads 正式 API"
    assert community.community_state == "community_corroborated"


def test_community_repository_outage_is_typed_and_assessment_is_not_available() -> None:
    with pytest.raises(CommunityRepositoryUnavailable) as raised:
        query_active_community_snapshot(
            database_url=URL, lat=22.9997, lng=120.2270,
            radius_m=1000, now=NOW,
            eligible_official_evidence_ids=frozenset(),
            connection_factory=raise_operational_error,
        )
    response = service_with_failed_community_repository().assess(REQUEST, now=NOW)
    assert response.community_refresh.state == "not_available"
    combined = repr(raised.value) + response.model_dump_json() + caplog.text
    assert DATABASE_URL_WITH_PASSWORD not in combined
    assert f"{REQUEST.point.lat},{REQUEST.point.lng}" not in combined
    assert DRIVER_DIAGNOSTIC_MARKER not in combined


def test_suppression_after_legacy_cache_seed_is_immediately_hidden() -> None:
    cache_assessment_evidence(ASSESSMENT_ID, [OFFICIAL_ITEM, SOCIAL_ITEM])
    suppress_signal(SOCIAL_SIGNAL_ID)
    response = client.get(f"/v1/evidence/{ASSESSMENT_ID}")
    assert response.status_code == 200
    assert SOCIAL_SIGNAL_ID not in {item["id"] for item in response.json()["items"]}
    assert database_fetch_spy.calls == [ASSESSMENT_ID]


def test_admin_suppression_removes_uplift_before_response() -> None:
    response = admin_client.post(
        "/v1/admin/community/suppressions",
        json={
            "source_key": "social.threads.keyword_search",
            "source_url": "https://example.test/threads/synthetic-post-1",
            "reason": "source_deleted",
            "expires_at": None,
        },
    )
    assert response.status_code == 200
    assert cursor.cluster_state == "unverified"


@pytest.mark.parametrize(
    ("base", "realtime", "community", "expected"),
    [
        (overall("低", "高"), "低", CommunityDecision.none(), ("低", "高")),
        (overall("低", "高"), "低", UNVERIFIED_COMMUNITY, ("低", "高")),
        (overall("低", "高"), "低", COMMUNITY_CORROBORATED, ("中", "中")),
        (overall("高", "高"), "高", MANY_COMMUNITY_CLUSTERS, ("極高", "中")),
        (overall("極高", "高"), "極高", COMMUNITY_CORROBORATED, ("極高", "中")),
        (historical_overall("高", "高"), "未知", COMMUNITY_CORROBORATED, ("中", "中")),
        (overall("中", "高"), "中", OFFICIALLY_CORROBORATED, ("高", "高")),
        (overall("中", "高"), "中", OFFICIAL_REFS_REPEATED, ("高", "高")),
    ],
)
def test_only_community_seam_is_bounded_and_handles_unknown_realtime(
    base, realtime, community, expected
) -> None:
    decision = apply_community_uplift(
        base=base, realtime_level=realtime, community=community
    )
    assert (decision.overall.level, decision.overall.confidence) == expected
```

- [ ] **Step 3: Implement bounded active signal/cluster reads**

```python
class CommunityRepositoryUnavailable(RuntimeError):
    pass


def query_active_community_snapshot(
    *,
    database_url: str,
    lat: float,
    lng: float,
    radius_m: int,
    now: datetime,
    eligible_official_evidence_ids: frozenset[str],
    signal_limit: int = 20,
    cluster_limit: int = 20,
    connection_factory: ConnectionFactory | None = None,
) -> CommunitySnapshot:
    bounded_radius = min(max(radius_m, 50), 2000)
    try:
        with _connect(database_url, connection_factory) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                signals = _query_active_signals(
                    cursor,
                    lat=lat,
                    lng=lng,
                    radius_m=bounded_radius,
                    now=now,
                    limit=min(max(signal_limit, 1), 20),
                )
                clusters = _query_active_clusters_for_signals(
                    cursor,
                    signal_ids=tuple(item.id for item in signals),
                    eligible_official_evidence_ids=eligible_official_evidence_ids,
                    query_lat=lat,
                    query_lng=lng,
                    radius_m=bounded_radius,
                    now=now,
                    limit=min(max(cluster_limit, 1), 20),
                )
                scoped_state_by_signal_id = {
                    signal_id: cluster.corroboration_state
                    for cluster in clusters
                    for signal_id in cluster.signal_ids
                }
                signals = tuple(
                    replace(
                        signal,
                        corroboration_state=scoped_state_by_signal_id.get(
                            signal.id, "unverified"
                        ),
                    )
                    for signal in signals
                )
                last_completed_at = _query_enabled_source_last_success(
                    cursor, source_key="social.threads.keyword_search"
                )
    except (OSError, psycopg.Error) as exc:
        log_event("community.repository.unavailable", error_code=exc.__class__.__name__)
        raise CommunityRepositoryUnavailable("community repository unavailable") from None
    return CommunitySnapshot(
        signals=signals,
        clusters=clusters,
        repository_available=True,
        last_completed_at=last_completed_at,
    )
```

Run `_query_enabled_source_last_success` inside the same repeatable-read transaction as the signal/cluster queries. Both SQL queries require `data_sources.is_enabled=true`, active moderation, unexpired retention, and no active suppression matching either canonical or referenced URL hash. Public records never carry fingerprint values, text, identity, or raw refs.

`_query_active_signals` must create a PostGIS geography query point, include rows
only with `ST_DWithin(signal.geom::geography, query_point, bounded_radius)`, and
report `ST_Distance` over the same geographies. It also selects
`ST_Y(signal.geom)` and `ST_X(signal.geom)` into the sanitized `lat`/`lng`
fields of `CommunitySignalRecord`; `geom` is constrained to Point in migration
0039. A degree approximation may be a conservative index prefilter only. Never
substitute a cluster centroid or expand the selected radius.
`_query_active_clusters_for_signals` accepts only the IDs from that in-radius
result, so an otherwise nearby-looking cluster with no selected signal cannot
appear. It must not copy global `event_clusters.corroboration_state`,
`distinct_original_source_count`, or `official_evidence_ids` into the assessment.
Instead, in the same read transaction it loads a private metadata-only
projection for only those selected signals (origin/canonical/reference HMAC,
exact HMAC, keyed LSH, times, and Point geometry), applies the Task 2
same-origin rule, and returns only the derived query-scoped count/state. Those
private hashes never leave the repository or enter a response/log.

The `CommunitySignalRecord.corroboration_state` initially selected from storage
is never public authority. Before returning the snapshot, annotate every
selected signal from the query-scoped cluster map as shown above; a selected
signal with no scoped cluster is `unverified`. Both preview and expanded
converters consume this replaced record, so a globally corroborated cluster
cannot make a one-origin in-radius evidence card claim corroboration. Import
`replace` from `dataclasses` in the concrete repository.

An official ref can make the scoped state `officially_corroborated` only when
its ID is in `eligible_official_evidence_ids`, its enabled linked geometry itself
intersects the user-selected radius, it is within the cluster compatibility
distance of at least one selected in-radius signal, and its active window
overlaps that selected signal. Otherwise two in-radius independent origins are
required for `community_corroborated`; one inside plus any number of outside
origins/official refs remains `unverified`. Add the real-PostGIS
just-inside/just-outside and mixed-cluster regressions above, skipped only when
`COMMUNITY_TEST_DATABASE_URL` is absent during a focused developer run. If
`COMMUNITY_DB_ACCEPTANCE_REQUIRED=1`, missing database configuration is an
assertion failure and no database-marked test may skip.

- [ ] **Step 4: Add atomic assessment association and evidence union**

Before binding, build `CommunityAssessmentBinding(signal_id,
corroboration_state)` from the query-scoped replaced records, deduplicate by
signal ID in stable order, validate the lowercase 64-hex ID and exact three-value
state enum, and cap bindings to 20. Append the binding tuple—not naked IDs—to
`RiskAssessmentPersistence`; it is SQL input only and never enters
`result_snapshot`. Restructure the existing single
`persist_risk_assessment` data-modifying CTE; do not issue a second statement
that tries to reference an out-of-scope `inserted_assessment` CTE. The exact
shape is:

```sql
WITH inserted_query AS (
    -- retain the existing privacy-safe location-query INSERT ... RETURNING id
),
inserted_assessment AS (
    -- retain the existing risk-assessment INSERT ... RETURNING id
),
inserted_generic_associations AS (
    INSERT INTO risk_assessment_evidence (...)
    SELECT ... FROM inserted_assessment ...
    ON CONFLICT DO NOTHING
    RETURNING evidence_id
),
inserted_community_associations AS (
    INSERT INTO risk_assessment_community_signals (
        risk_assessment_id, community_signal_id,
        relevance_score, corroboration_state, reason, created_at
    )
    SELECT inserted_assessment.id, signal.id, 1.0,
           binding.corroboration_state,
           'selected_for_assessment', %(created_at)s
    FROM inserted_assessment
    JOIN unnest(
        %(community_signal_ids)s::text[],
        %(community_corroboration_states)s::text[]
    ) AS binding(signal_id, corroboration_state) ON true
    JOIN community_signals AS signal
      ON signal.id = binding.signal_id
    JOIN data_sources AS source
      ON source.adapter_key = signal.source_key
     AND source.is_enabled = true
    WHERE signal.moderation_state IN ('unverified', 'accepted')
      AND signal.retention_expires_at > %(created_at)s
      AND binding.corroboration_state IN (
          'unverified', 'community_corroborated', 'officially_corroborated'
      )
      AND NOT EXISTS (
          SELECT 1 FROM suppressed_sources AS suppressed
          WHERE suppressed.source_key = signal.source_key
            AND suppressed.canonical_url_hash IN (
                signal.canonical_url_hash, signal.referenced_url_hash
            )
            AND (
                suppressed.expires_at IS NULL
                OR suppressed.expires_at > %(created_at)s
            )
      )
    ON CONFLICT DO NOTHING
    RETURNING community_signal_id
)
SELECT id FROM inserted_assessment;
```

Require the ID/state arrays to have equal lengths before SQL. Both association
inserts and the assessment are one SQL statement in one
transaction and commit once. Any generic/community association error rolls back
the query, assessment, and both association sets. Tests cover empty bindings,
more than 20, malformed IDs, invalid/mismatched states or array lengths, one
successful commit, and injected community-insert failure with zero persisted
rows.

Extend the existing exported `fetch_assessment_evidence` function—used by
`app.api.services.public_evidence.assessment_db_evidence`—rather than inventing a
parallel query name. It unions the existing generic evidence query with
associated community signals and maps them to `EvidenceRecord` with a template
summary, an identity-free source label, public `url=None`, published/ingested
times, geometry, precision, confidence, the association's persisted
query-scoped corroboration state, and `raw_ref=None`. It never reads
`event_clusters.corroboration_state` for assessment detail. Its
community branch joins `data_sources` with `is_enabled=true` and rechecks active
moderation, retention, and `suppressed_sources` at read time, so a later
kill/suppression disappears immediately even from an older assessment
association. It never inserts community rows into generic `evidence`; retain the
existing export and production call path.

Add two API-only converters in `public_evidence.py`:

```python
def evidence_from_community_signal(signal: CommunitySignalRecord) -> Evidence: ...
def evidence_from_record(record: EvidenceRecord) -> Evidence: ...  # extend existing
```

The first rejects any ID outside lowercase 64-hex and constructs a normal
`Evidence` with the bounded template summary, identity-free source label,
`point=LatLng(lat=signal.lat, lng=signal.lng)`, a GeoJSON Point in `[lng, lat]`
order, published/ingested time,
precision, confidence, cluster state, public `url=None`, and `raw_ref=None`.
The second copies the three defaulted metadata fields for the expanded-detail
UNION. Neither accepts fingerprints, URL hashes, raw text, account data, or raw
refs. In the assessment service, convert `snapshot.signals` with
`evidence_from_community_signal` before concatenating with current/history
`Evidence`; never concatenate `CommunitySignalRecord` and `Evidence` directly.
Use those same replaced records to construct the persisted
`CommunityAssessmentBinding` values, guaranteeing preview and detail use one
query-scoped state.

Community associations and official source enablement are mutable read-time
authorization predicates, so they cannot use the existing assessment-evidence
cache. Preserve the core plan's DB-authoritative v1 detail route: the service
does not write this cache and `/v1/evidence` ignores any legacy memory/Redis
entry, always re-reading the enabled, unsuppressed association UNION. Add a
legacy-cache-seed→suppression→detail-read regression proving the endpoint hits
the database and immediately omits the signal. The cache module remains only
for rollback/serialization characterization and never becomes the community
authority path.

- [ ] **Step 5: Preserve the core base composer and establish one later uplift seam**

Import and call the already-landed core function exactly as `compose_base_overall(current_scoring, historical_scoring)`. Do not redefine it, change `AssessmentData`, combine the two scorer calls, or add community behavior to `assessment/safety.py`. `apply_community_uplift` below is the only function that may change the returned base `OverallDecision` because of community.

- [ ] **Step 6: Implement the single bounded decision seam**

```python
_LEVELS = ("低", "中", "高", "極高")
_CONFIDENCE = ("未知", "低", "中", "高")


def _cap_confidence(value: ConfidenceLevel, maximum: ConfidenceLevel) -> ConfidenceLevel:
    return _CONFIDENCE[min(_CONFIDENCE.index(value), _CONFIDENCE.index(maximum))]


def _cap_confidence_at_medium(value: ConfidenceLevel) -> ConfidenceLevel:
    return _cap_confidence(value, "中")


def _cap_at_high(value: ConfidenceLevel) -> ConfidenceLevel:
    return _cap_confidence(value, "高")


def community_decision_from_clusters(
    clusters: tuple[CommunityClusterRecord, ...],
) -> CommunityDecision:
    corroborated = tuple(
        item for item in clusters
        if item.corroboration_state in {
            "community_corroborated", "officially_corroborated"
        }
    )
    if not corroborated:
        state = "unverified" if clusters else "none"
        return CommunityDecision(state=state, level="未知", reasons=())
    confirmed = any(
        item.corroboration_state == "officially_corroborated"
        for item in corroborated
    )
    return CommunityDecision(
        state=("officially_corroborated" if confirmed else "community_corroborated"),
        level="中",
        reasons=("附近有經獨立來源交叉佐證的群眾淹水訊號。",),
    )


def apply_community_uplift(
    *,
    base: OverallDecision,
    realtime_level: RiskLevel,
    community: CommunityDecision,
) -> CommunityUpliftDecision:
    if community.state not in {"community_corroborated", "officially_corroborated"}:
        return CommunityUpliftDecision(overall=base, community=community)
    officially_confirmed = community.state == "officially_corroborated"
    if realtime_level == "未知":
        overall = OverallDecision(
            "中",
            "中" if not officially_confirmed else _cap_at_high(base.confidence),
            "community_warning",
            community.reasons,
        )
        return CommunityUpliftDecision(overall=overall, community=community)
    if base.level not in _LEVELS:
        return CommunityUpliftDecision(overall=base, community=community)
    raised = _LEVELS[min(_LEVELS.index(base.level) + 1, len(_LEVELS) - 1)]
    confidence = (
        base.confidence
        if officially_confirmed
        else _cap_confidence_at_medium(base.confidence)
    )
    return CommunityUpliftDecision(
        overall=OverallDecision(raised, confidence, base.dominant_mode, community.reasons),
        community=community,
    )
```

Official evidence references determine confirmation only. They are never turned into a second risk signal; one or twenty official refs and one or twenty clusters still cause zero or one level increment when official realtime is known. If official realtime is `未知`, the approved precedence rule returns overall `中`/`community_warning` even when the separate historical block is `高`; it never rewrites that historical block. Add truth-table rows for unverified single origin, duplicate origins, multiple clusters, already-`極高`, historical `高` plus unknown realtime, and repeated base official IDs.

- [ ] **Step 7: Integrate through the existing two-argument AssessmentService**

Keep `AssessmentRepository.load` and core `AssessmentData` unchanged. Add the separate community read to the same repository object, not a third service dependency:

```python
def load_community_snapshot(
    self, *, lat: float, lng: float, radius_m: int, as_of: datetime,
    eligible_official_evidence_ids: frozenset[str],
) -> CommunitySnapshot:
    return query_active_community_snapshot(
        database_url=self._database_url,
        lat=lat,
        lng=lng,
        radius_m=radius_m,
        now=as_of,
        eligible_official_evidence_ids=eligible_official_evidence_ids,
    )
```

Do not reference a repository `_connection_factory`: core Task 3 intentionally
constructs `PostgresAssessmentRepository(database_url, *, enabled=True)` with
only `_database_url` and `_enabled`. Unit tests monkeypatch the module-level
query function; the standalone query's optional factory remains available only
to its own focused repository tests.

Task 7 deliberately leaves `community_refresh.state="idle"`. Task 8 adds and tests the canonical gazetteer priority method and only then calls it from the service, so every task can finish GREEN without a temporary concrete-method stub.

Retain the core service's two scorer calls exactly. Insert the separate community read only after realtime safety and base composition; the resulting order is exact:

```python
data = self._repository.load(
    lat=request.point.lat,
    lng=request.point.lng,
    radius_m=request.radius_m,
    as_of=now,
)
current_items = tuple(evidence_from_record(item) for item in data.current_official)
historical_items = tuple(evidence_from_record(item) for item in data.historical)
current_scoring = self._scorer(
    tuple(signal_from_evidence(item) for item in current_items), now=now
)
historical_scoring = self._scorer(
    tuple(signal_from_evidence(item) for item in historical_items), now=now
)
current_scoring = apply_realtime_safety(current_scoring, data)
base = compose_base_overall(current_scoring, historical_scoring)
try:
    snapshot = self._repository.load_community_snapshot(
        lat=request.point.lat,
        lng=request.point.lng,
        radius_m=request.radius_m,
        as_of=now,
        eligible_official_evidence_ids=frozenset(
            item.id for item in data.current_official
        ) if data.current_available else frozenset(),
    )
except CommunityRepositoryUnavailable:
    snapshot = CommunitySnapshot(
        signals=(), clusters=(), repository_available=False, last_completed_at=None
    )
community = community_decision_from_clusters(snapshot.clusters)
uplift = apply_community_uplift(
    base=base,
    realtime_level=current_scoring.realtime_level,
    community=community,
)
priority = CommunityPriorityResult(
    state=("idle" if snapshot.repository_available else "not_available"),
    last_completed_at=snapshot.last_completed_at,
)
```

Keep every other core response-constructor argument unchanged. Replace only `community` with `CommunityRiskBlock(state=uplift.community.state, level=uplift.community.level, reasons=list(uplift.community.reasons))`, `overall`/`dominant_mode` with `uplift.overall`, and `community_refresh` with the priority state plus `snapshot.last_completed_at`. Add active `snapshot.signals` to the current-first display-evidence union, then apply the existing dedupe/5–10 preview bound. Add exactly their ID/query-scoped-state bindings to `RiskAssessmentPersistence.community_signal_bindings`; do not put signal objects, states, or fingerprints in `result_snapshot`. Update the core guard test to assert one textual call to `apply_community_uplift` and no second community-aware composer.

Catch only `CommunityRepositoryUnavailable` around each local community repository call and map it to an empty snapshot/`not_available`; no Threads/browser object exists in the API process. Preserve realtime/historical blocks and both scorer inputs exactly.

Every concrete API community-repository method catches only `OSError` and
`psycopg.Error`, rolls back any open transaction before translation, and raises
`CommunityRepositoryUnavailable("community repository unavailable") from None`.
Internal logs retain only a fixed event name and exception class/error code—no
`str(exc)`, repr, SQL, connection URL, parameters, coordinates, or driver
diagnostics. This applies to the
snapshot, assessment-evidence union, priority upsert, and suppression paths so
transport/database failures never leak as untyped 500s or partially commit.

- [ ] **Step 8: Add authenticated operator suppression**

Add schemas:

```python
class CommunitySuppressionRequest(ContractModel):
    source_key: Literal["social.threads.keyword_search", "community.user_report"]
    source_url: str | None = Field(default=None, max_length=2048)
    report_id: UUID | None = None
    reason: Literal["source_deleted", "complaint", "false_report", "privacy_request"]
    expires_at: datetime | None = None


class CommunitySuppressionResponse(ContractModel):
    suppressed: bool
```

The existing admin authentication protects `POST
/v1/admin/community/suppressions`. Add exact cross-field validation:

- `social.threads.keyword_search` requires canonical HTTPS `source_url` and
  forbids `report_id`;
- `community.user_report` requires `report_id` and forbids `source_url`;
- every missing, dual, or mismatched source/input combination preserves the
  existing application-wide HTTP 400 validation contract and
  performs no repository call.

The existing `RequestValidationError` handler in `apps/api/app/main.py` must
also stop serializing `exc.errors()` verbatim. Return a bounded allowlist per
error (`type`, a sanitized string/integer `loc`, and a fixed generic `msg`) and
drop `input`, `ctx`, `url`, exception repr, and request body. Custom cross-field
validators use fixed messages that never interpolate a submitted value. Logs
may contain only method, route template, status, and safe validation type/count;
they contain no body, source URL, report UUID, token, or exception text. Publish
400—not 422—in the suppression OpenAPI response.

Sanitize `loc` component-by-component: keep integers and only the fixed strings
`body`, `source_key`, `source_url`, `report_id`, `reason`, and `expires_at`;
replace every unknown string (including an attacker-controlled extra JSON key)
with `body`, cap depth at three components, and cap each rendered component at
32 characters. Never echo the unknown key. Add a payload whose extra key itself
contains the submitted URL/UUID/handle marker and prove that marker is absent
from response and logs.

```python
@pytest.mark.parametrize(
    "payload",
    [
        THREADS_WITH_REPORT_UUID,
        USER_REPORT_WITH_THREADS_URL,
        DUAL_INPUTS,
        MISSING_INPUT,
        INVALID_THREADS_URL,
    ],
)
def test_suppression_validation_is_400_and_scrubs_submitted_markers(
    payload, caplog
) -> None:
    response = admin_client.post("/v1/admin/community/suppressions", json=payload)
    assert response.status_code == 400
    combined = response.text + caplog.text
    assert SUBMITTED_THREADS_URL not in combined
    assert SUBMITTED_REPORT_UUID not in combined
    assert "input" not in response.text
    assert repository_suppress_spy.calls == []
```

For Threads, canonicalize the URL in memory and derive `keyed_hmac(key,
"community-canonical-url-v1", canonical_url)`. The user-report branch never
rederives an ID: after locking the report it reads
`community_user_report_links` by `report_id` and suppresses that exact linked
signal, so deletion still works when the key is missing or has rotated. The
Threads branch requires the current decoded key; the report branch is
key-independent. Neither submitted URL nor report UUID is persisted or logged
by this endpoint. Add regressions for missing and rotated keys on report
suppression and prove the originally linked signal—not a newly derived ID—is
suppressed. The repository first acquires the exact shared
`"flood-risk:v1:community-mutation"` transaction advisory lock, then locks
matching signals/clusters, suppresses and recomputes in that one transaction,
and never accepts body text or author identity. Add positive vector
tests for both branches plus every mismatch case.

- [ ] **Step 9: Run API repository, uplift, report, assessment, evidence, and admin tests**

Run: `(cd apps/api && python -m pytest tests/test_community_repository.py tests/test_community_repository_postgres.py tests/test_community_uplift.py tests/test_community_assessment_integration.py tests/test_reports_repository.py tests/test_assessment_repository.py tests/test_assessment_service.py tests/test_public_contract.py tests/test_public_evidence_cache.py tests/test_main.py -q)`

Run: `python infra/scripts/validate_openapi.py`

Expected: PASS; core scorer golden fixtures remain unchanged.

- [ ] **Step 10: Commit the single assessment seam**

```bash
git add apps/api/app/domain/community/models.py apps/api/app/domain/community/repository.py apps/api/app/domain/community/uplift.py apps/api/app/domain/assessment/repository.py apps/api/app/api/services/assessment.py apps/api/app/api/services/public_evidence.py apps/api/app/domain/evidence/repository.py apps/api/app/api/routes/admin.py apps/api/app/main.py apps/api/app/api/schemas.py docs/api/openapi.yaml apps/api/tests/test_community_repository.py apps/api/tests/test_community_repository_postgres.py apps/api/tests/test_community_uplift.py apps/api/tests/test_community_assessment_integration.py apps/api/tests/test_assessment_repository.py apps/api/tests/test_assessment_service.py apps/api/tests/test_public_contract.py apps/api/tests/test_public_evidence_cache.py apps/api/tests/test_main.py
git commit -m "feat: associate and uplift sanitized community evidence"
```

---

### Task 8: Add Canonical Search Requests and a Real Adaptive Loop

**Files:**

- Create: `apps/workers/app/community/search_requests.py`
- Create: `apps/workers/app/community/scheduler.py`
- Create: `apps/workers/app/community/triggers.py`
- Create: `apps/workers/app/cli/community_cli.py`
- Create: `apps/workers/tests/test_community_search_requests.py`
- Create: `apps/workers/tests/test_community_scheduler.py`
- Create: `apps/workers/tests/test_community_triggers.py`
- Modify: `apps/workers/app/community/repository.py`
- Modify: `apps/workers/app/cli/parser.py`
- Modify: `apps/workers/app/main.py`
- Modify: `apps/workers/tests/test_worker_entrypoints.py`
- Modify: `apps/api/app/domain/community/repository.py`
- Modify: `apps/api/app/api/services/assessment.py`
- Modify: `apps/api/tests/test_assessment_service.py`
- Modify: `apps/api/tests/test_community_repository.py`
- Create: `tests/fixtures/community_request_key_vectors.json`
- Modify: `apps/workers/app/community/contracts.py`

**Interfaces:**

- Consumes: canonical geocoder context, pending work rows, controlled term/location rotation, fresh official triggers/anomalies, Threads adapter, repository advisory lock, source retry errors, injected clock/sleep.
- Produces: bounded in-memory `CommunitySearchQuery`, non-identifying priority upsert, normal/event/cooldown modes, one safe cycle, and a loop that actually observes cadence/backoff.

- [ ] **Step 1: Define exact query/scheduler contracts**

```python
# apps/workers/app/community/search_requests.py
@dataclass(frozen=True)
class CommunitySearchQuery:
    request_key: str | None
    text: str
    contexts: tuple[LocationContext, ...]
    priority: int


@dataclass(frozen=True)
class OfficialTrigger:
    source_key: str
    event_type: Literal["flood_warning", "rainfall", "water_level", "flood_report"]
    observed_at: datetime
    active_from: datetime
    active_until: datetime
    affected_contexts: tuple[LocationContext, ...]
    neighboring_contexts: tuple[LocationContext, ...]


@dataclass(frozen=True)
class CooldownContext:
    window_started_at: datetime
    latest_cleared_at: datetime
    affected_contexts: tuple[LocationContext, ...]
    neighboring_contexts: tuple[LocationContext, ...]


@dataclass(frozen=True)
class RequestLocationContext:
    request_key: str
    anchor: LocationContext
    matching_contexts: tuple[LocationContext, ...]


class OfficialTriggerRepository(Protocol):
    def active_triggers(self, *, now: datetime) -> tuple[OfficialTrigger, ...]:
        ...

    def aggregate_cooldown_context(
        self, *, now: datetime, horizon: timedelta
    ) -> CooldownContext | None:
        ...

    def normal_contexts(
        self, *, now: datetime, limit: int = 22
    ) -> tuple[LocationContext, ...]:
        ...

    def contexts_for_requests(
        self,
        requests: tuple[CommunitySearchRequest, ...],
        *,
        limit: int = 10,
    ) -> tuple[RequestLocationContext, ...]:
        ...


@dataclass(frozen=True)
class SchedulerMode:
    name: Literal["normal", "event", "cooldown"]
    cadence: timedelta


@dataclass(frozen=True)
class CommunitySchedulerConfig:
    max_priority_queries: int = 10
    max_queries_per_cycle: int = 20
    search_window: timedelta = timedelta(hours=6)
    normal_cadence: timedelta = timedelta(minutes=30)
    event_cadence: timedelta = timedelta(minutes=5)
    cooldown: timedelta = timedelta(hours=2)


@dataclass(frozen=True)
class CommunityCycleResult:
    mode: Literal["normal", "event", "cooldown", "locked"]
    threads_egress_enabled: bool
    executed_query_count: int
    inserted_signal_count: int
    completed_request_count: int
    retry_after: timedelta | None
```

- [ ] **Step 2: Write canonical-storage, crash recovery, cadence, partial success, rate-limit, and no-egress API RED tests**

```python
def test_request_stores_only_canonical_geocoder_parts() -> None:
    request = build_search_request(
        anchor_geocoder_entry_id=TAINAN_ZHONGHUA_ROAD_ID,
        county="台南市", district=" 東區 ", road_or_landmark="中華東路",
        radius_m=1000, requested_at=NOW,
    )
    assert request.county == "臺南市"
    assert request.district == "東區"
    assert request.road_or_landmark == "中華東路"
    assert not hasattr(request, "raw_query")
    assert request.expires_at == NOW + timedelta(minutes=15)


def test_private_house_number_is_not_persisted() -> None:
    with pytest.raises(ValueError, match="road or landmark, not a private address"):
        build_search_request(
            anchor_geocoder_entry_id=TAINAN_ZHONGHUA_ROAD_ID,
            county="臺南市", district="東區", road_or_landmark="中華東路123號4樓",
            radius_m=1000, requested_at=NOW,
        )


def test_request_key_preserves_field_and_null_boundaries() -> None:
    vectors = load_request_key_vectors(ROOT_VECTOR_PATH)
    assert_request_key_vectors(vectors, community_search_request_key)
    keys = {item.expected_sha256 for item in vectors}
    assert len(keys) == len(vectors)


def test_expired_same_key_is_replaced_and_claimable() -> None:
    repository.seed_request(EXPIRED_REQUEST)
    repository.upsert_search_request(FRESH_SAME_KEY_REQUEST)
    claimed = repository.claim_search_requests(now=NOW, limit=1)
    assert claimed == (FRESH_SAME_KEY_REQUEST,)


def test_rate_limit_releases_unexecuted_requests_and_keeps_earlier_success() -> None:
    result = run_community_cycle(
        repository=repository,
        adapter=success_then_rate_limited_adapter(),
        trigger_repository=NO_ACTIVE_TRIGGERS_WITH_TAINAN_CONTEXT,
        now=NOW,
        config=TEST_CONFIG,
    )
    assert repository.inserted_ids == (FIRST_SUCCESS_ID,)
    assert repository.completed_keys == (FIRST_REQUEST_KEY,)
    assert repository.released_keys == (SECOND_REQUEST_KEY,)
    assert result.retry_after == timedelta(minutes=10)


def test_disabled_threads_still_prunes_and_reclusters_user_reports() -> None:
    result = run_community_cycle(
        repository=repository_with_active_user_reports(),
        adapter=None,
        trigger_repository=NO_ACTIVE_TRIGGERS_NO_NORMAL_CONTEXTS,
        now=NOW,
        config=TEST_CONFIG,
    )
    assert result.mode == "normal"
    assert result.threads_egress_enabled is False
    assert repository.prune_calls == [NOW]
    assert repository.replaced_cluster_ids == (USER_REPORT_CLUSTER_ID,)


def test_database_kill_switch_is_rechecked_before_every_egress() -> None:
    repository.source_enabled_answers = [True, True, True, False]
    result = run_community_cycle(
        repository=repository,
        adapter=search_spy,
        trigger_repository=NO_ACTIVE_TRIGGERS_WITH_SOUTH_CONTEXTS,
        now=NOW,
        config=TEST_CONFIG,
    )
    assert search_spy.call_count == 1
    assert result.mode == "normal"
    assert result.threads_egress_enabled is False
    assert repository.released_keys == repository.claimed_keys
    assert repository.reclustered is True


def test_disabled_threads_with_active_trigger_reclusters_on_event_cadence() -> None:
    result = run_community_cycle(
        repository=repository_with_expired_official_link(),
        adapter=None,
        trigger_repository=ACTIVE_CAP_TRIGGER_REPOSITORY,
        now=NOW,
        config=TEST_CONFIG,
    )
    assert result.mode == "event"
    assert result.threads_egress_enabled is False
    assert repository.cluster_state == "unverified"  # expired old ref removed
    run_community_loop(
        cycle=lambda _now: result, clock=lambda: NOW,
        max_ticks=2, sleep=sleep_spy, config=TEST_CONFIG,
    )
    assert sleep_spy.calls == [timedelta(minutes=5)]


def test_kill_switch_between_pages_stops_second_http_call_and_discards_partial() -> None:
    repository.source_enabled_answers = [True, True, True, False]
    result = run_community_cycle(
        repository=repository,
        adapter=two_page_adapter,
        trigger_repository=NO_ACTIVE_TRIGGERS_WITH_TAINAN_CONTEXT,
        now=NOW,
        config=TEST_CONFIG,
    )
    assert two_page_adapter.http_call_count == 1
    assert repository.inserted_ids == ()
    assert repository.completed_keys == ()
    assert set(repository.released_keys) == set(repository.claimed_keys)
    assert result.threads_egress_enabled is False


def test_loop_uses_event_then_retry_after_cadence() -> None:
    run_community_loop(
        cycle=event_cycle_with_ten_minute_retry,
        clock=lambda: NOW,
        max_ticks=2,
        sleep=sleep_spy,
        config=TEST_CONFIG,
    )
    assert sleep_spy.calls == [timedelta(minutes=10)]


def test_active_cap_uses_polygon_and_expiry_not_global_six_hour_age() -> None:
    triggers = trigger_repository.active_triggers(now=NOW)
    cap = next(item for item in triggers if item.event_type == "flood_warning")
    assert cap.observed_at < NOW - timedelta(hours=6)
    assert cap.active_from <= NOW < cap.active_until
    assert cap.affected_contexts == (TAINAN_CONTEXT,)
    assert cap.neighboring_contexts == tuple(
        sorted((KAOHSIUNG_CONTEXT, CHIAYI_COUNTY_CONTEXT), key=lambda item: item.admin_code)
    )


def test_event_queries_cover_affected_area_then_reviewed_boundary_neighbors() -> None:
    queries = build_cycle_queries(
        requests=(), request_contexts=(), triggers=(TAINAN_CAP_TRIGGER,),
        cooldown_context=None, normal_contexts=(), mode=EVENT_MODE,
        config=TEST_CONFIG, now=NOW,
    )
    assert [item.contexts[0].admin_code for item in queries] == [
        "67000000", KAOHSIUNG_CODE, CHIAYI_COUNTY_CODE
    ]
    assert [item.priority for item in queries] == [90, 80, 80]


@pytest.mark.parametrize("mode", (EVENT_MODE, COOLDOWN_MODE))
def test_event_and_cooldown_never_append_normal_rotation_queries(mode: SchedulerMode) -> None:
    queries = build_cycle_queries(
        requests=(), request_contexts=(),
        triggers=(TAINAN_CAP_TRIGGER,) if mode.name == "event" else (),
        cooldown_context=AGGREGATED_COOLDOWN_CONTEXT if mode.name == "cooldown" else None,
        normal_contexts=(UNRELATED_NORMAL_CONTEXT,), mode=mode,
        config=TEST_CONFIG, now=NOW,
    )
    assert UNRELATED_NORMAL_CONTEXT.admin_code not in {
        item.contexts[0].admin_code for item in queries
    }
    assert all(item.priority != 20 for item in queries)


@pytest.mark.parametrize("trigger_repo", (event_trigger_repository, cooldown_trigger_repository))
def test_event_or_cooldown_cycle_does_not_even_load_normal_rotation_contexts(
    trigger_repo: FakeOfficialTriggerRepository,
) -> None:
    run_community_cycle(
        repository=repository,
        trigger_repository=trigger_repo,
        adapter=fixture_adapter,
        config=TEST_CONFIG,
        now=NOW,
    )
    assert trigger_repo.normal_context_calls == 0


def test_cooldown_aggregates_every_cleared_context_in_two_hour_window() -> None:
    cooldown = trigger_repository.aggregate_cooldown_context(
        now=NOW, horizon=timedelta(hours=2)
    )
    assert cooldown is not None
    assert cooldown.window_started_at == NOW - timedelta(hours=2)
    assert cooldown.latest_cleared_at == NOW - timedelta(minutes=10)
    assert {item.admin_code for item in cooldown.affected_contexts} == {
        TAINAN_CODE, PINGTUNG_CODE,
    }
    queries = build_cycle_queries(
        requests=(), request_contexts=(), triggers=(),
        cooldown_context=cooldown, normal_contexts=(), mode=COOLDOWN_MODE,
        config=TEST_CONFIG, now=NOW,
    )
    assert {item.contexts[0].admin_code for item in queries} == EXPECTED_ALL_CLEARED_AND_NEIGHBOR_CODES
    assert cursor.clearance_query_has_limit_one is False


def test_expired_cooldown_context_does_not_enter_normal_queries() -> None:
    cooldown = replace(
        AGGREGATED_COOLDOWN_CONTEXT,
        window_started_at=NOW - timedelta(hours=4, seconds=1),
        latest_cleared_at=NOW - timedelta(hours=2, seconds=1),
    )
    mode = resolve_mode(triggers=(), cooldown_context=cooldown, now=NOW, config=TEST_CONFIG)
    assert mode.name == "normal"


def test_normal_contexts_come_only_from_active_reviewed_nationwide_boundaries() -> None:
    contexts = trigger_repository.normal_contexts(now=NOW)
    assert len(contexts) == 22
    assert {item.admin_code for item in contexts} == CANONICAL_JURISDICTION_CODES
    assert all(item.precision == "admin_area" for item in contexts)


def test_claimed_road_request_uses_exact_anchor_and_radius_in_metres() -> None:
    contexts = trigger_repository.contexts_for_requests((ROAD_REQUEST,))
    assert contexts[0].request_key == ROAD_REQUEST.normalized_query_key
    assert contexts[0].anchor == ROAD_CONTEXT
    assert ROAD_CONTEXT in contexts[0].matching_contexts
    assert all(item.precision in {"road_or_lane", "poi"} for item in contexts[0].matching_contexts)
    assert cursor.anchor_id == ROAD_REQUEST.anchor_geocoder_entry_id
    assert cursor.radius_m == ROAD_REQUEST.radius_m
    assert cursor.used_st_dwithin_geography is True
    assert RAW_LOCATION_TEXT not in repr(cursor.all_params)


def test_missing_or_drifted_anchor_fails_closed_instead_of_uuid_ordering() -> None:
    assert trigger_repository.contexts_for_requests((MISSING_ANCHOR_REQUEST,)) == ()
    assert trigger_repository.contexts_for_requests((DRIFTED_ANCHOR_REQUEST,)) == ()
    assert cursor.used_order_by_uuid_as_resolution is False


def test_priority_is_idle_without_server_resolved_admin() -> None:
    result = repository.prioritize_community_search(
        lat=QUERY_LAT, lng=QUERY_LNG, location_text="中山路",
        resolved_admin_code=None, resolved_admin_name=None,
        radius_m=500, requested_at=NOW,
    )
    assert result.state == "idle"
    assert cursor.search_request_inserts == 0


def test_same_named_road_is_selected_only_in_resolved_county() -> None:
    result = repository.prioritize_community_search(
        lat=TAINAN_LAT, lng=TAINAN_LNG, location_text="中山路",
        resolved_admin_code="67000000", resolved_admin_name="臺南市",
        radius_m=500, requested_at=NOW,
    )
    assert result.state == "prioritized"
    assert cursor.persisted_county == "臺南市"
    assert cursor.selected_gazetteer_admin_code == "67000000"
    assert cursor.persisted_anchor_geocoder_entry_id == TAINAN_ZHONGSHAN_ROAD_ID
    assert cursor.anchor_distance_m <= 500


def test_same_admin_name_and_precision_is_idle_when_two_geometries_match() -> None:
    cursor.gazetteer_candidates = (
        road_candidate(name="中山路", admin_code="67000000", distance_m=25),
        road_candidate(name="中山路", admin_code="67000000", distance_m=320),
    )
    result = repository.prioritize_community_search(
        lat=TAINAN_LAT, lng=TAINAN_LNG, location_text="中山路",
        resolved_admin_code="67000000", resolved_admin_name="臺南市",
        radius_m=500, requested_at=NOW,
    )
    assert result.state == "idle"
    assert cursor.search_request_inserts == 0
    assert cursor.checked_same_name_precision_group_before_anchor_selection is True


def test_api_priority_path_has_no_threads_dependency() -> None:
    signature = inspect.signature(AssessmentService)
    assert tuple(signature.parameters) == ("repository", "scorer")
```

- [ ] **Step 3: Run tests and verify missing modules**

Run: `(cd apps/workers && python -m pytest tests/test_community_search_requests.py tests/test_community_scheduler.py tests/test_worker_entrypoints.py -v)`

Expected: FAIL during import.

- [ ] **Step 4: Implement canonical request creation and controlled query planning**

```python
FLOOD_QUERY_TERMS = ("道路積水", "地下道積水", "淹水")
_HOUSE_NUMBER = re.compile(r"\d+號(?:\d+樓)?")


def canonical_place_part(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = unicodedata.normalize("NFKC", value).replace("台", "臺").strip()
    normalized = " ".join(normalized.split())
    if not normalized or len(normalized) > 100:
        return None
    if re.search(r"https?://|@|\b09\d{8}\b", normalized, flags=re.IGNORECASE):
        raise ValueError("canonical place contains prohibited raw or identity data")
    return normalized


def build_search_request(
    *, anchor_geocoder_entry_id: UUID,
    county: str | None, district: str | None,
    road_or_landmark: str | None, radius_m: int,
    requested_at: datetime,
) -> CommunitySearchRequest:
    if anchor_geocoder_entry_id.version != 5:
        raise ValueError("anchor must be a stable public gazetteer UUIDv5")
    canonical_county = canonical_place_part(county)
    canonical_district = canonical_place_part(district)
    canonical_place = canonical_place_part(road_or_landmark)
    if canonical_place and _HOUSE_NUMBER.search(canonical_place):
        raise ValueError("store a road or landmark, not a private address")
    if not any((canonical_county, canonical_district, canonical_place)):
        raise ValueError("canonical county, district, road, or landmark is required")
    bounded_radius = min(max(radius_m, 50), 2000)
    key = community_search_request_key(
        anchor_geocoder_entry_id=anchor_geocoder_entry_id,
        county=canonical_county,
        district=canonical_district,
        road_or_landmark=canonical_place,
        radius_m=bounded_radius,
    )
    return CommunitySearchRequest(
        normalized_query_key=key,
        anchor_geocoder_entry_id=anchor_geocoder_entry_id,
        county=canonical_county,
        district=canonical_district,
        road_or_landmark=canonical_place,
        radius_m=bounded_radius,
        priority=100,
        requested_at=requested_at,
        expires_at=requested_at + timedelta(minutes=15),
)
```

Define the helper before `build_search_request` and use this byte contract in
both packages:

```python
def community_search_request_key(
    *, anchor_geocoder_entry_id: UUID,
    county: str | None, district: str | None,
    road_or_landmark: str | None, radius_m: int,
) -> str:
    if anchor_geocoder_entry_id.version != 5:
        raise ValueError("anchor must be a stable public gazetteer UUIDv5")
    canonical = json.dumps(
        {
            "v": 1,
            "anchor_geocoder_entry_id": str(anchor_geocoder_entry_id),
            "county": county,
            "district": district,
            "road_or_landmark": road_or_landmark,
            "radius_m": radius_m,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

The API cannot import the worker package, so it implements the same small pure
helper locally. Both packages load the following exact root fixture and must
produce every digest byte-for-byte:

```json
{
  "version": 1,
  "cases": [
    {"anchor_geocoder_entry_id":"11111111-1111-5111-8111-111111111111","county":"臺南市","district":"東區","road_or_landmark":"中華東路","radius_m":1000,"expected_sha256":"6be6987831397b9a63f879d34461bd3af1d5d15ab17f7a430f0b26bc51665546"},
    {"anchor_geocoder_entry_id":"22222222-2222-5222-8222-222222222222","county":"甲|乙","district":null,"road_or_landmark":null,"radius_m":500,"expected_sha256":"93fac0db8e77ed780647e37f775238d9d4857fba0ef3dcb637732d8bf2a56f86"},
    {"anchor_geocoder_entry_id":"22222222-2222-5222-8222-222222222222","county":"甲","district":"乙","road_or_landmark":null,"radius_m":500,"expected_sha256":"badcc25d564819153dd628adc713b2e6da249dc416537a350f2ebcd0adf27fba"},
    {"anchor_geocoder_entry_id":"22222222-2222-5222-8222-222222222222","county":"甲","district":null,"road_or_landmark":"乙","radius_m":500,"expected_sha256":"52a4ae2f73533f6ec0908476b39407d03da6802a9cc19893096e25232e8d1bae"},
    {"anchor_geocoder_entry_id":"22222222-2222-5222-8222-222222222222","county":null,"district":"甲","road_or_landmark":"乙","radius_m":500,"expected_sha256":"c9bebbfa4787bd56946ba70368924b5443e952325da3dac5748a237cc0abb9d3"},
    {"anchor_geocoder_entry_id":"33333333-3333-5333-8333-333333333333","county":"臺南市","district":"東區","road_or_landmark":"中山路","radius_m":500,"expected_sha256":"4db6c2fd7c80bcf41b6d69530f69d758d13d0e4c104a85db7b2522686eb1bc33"},
    {"anchor_geocoder_entry_id":"44444444-4444-5444-8444-444444444444","county":"臺南市","district":"東區","road_or_landmark":"中山路","radius_m":500,"expected_sha256":"79377ebe00e54c089e2681e8041a494c99ea4c67972c23b189871f375b55ccad"}
  ]
}
```

The last two vectors prove identical canonical names/radius with different
stable public anchors cannot collide. The UUID is the existing deterministic
UUIDv5 `geocoder_open_data_entries.id`, not a client value or user identifier.

`build_cycle_queries` creates only in-memory text from `FLOOD_QUERY_TERMS` and
canonical fields. Each claimed request produces exactly one query whose match
contexts are the exact anchor plus bounded reviewed road/POI contexts inside its
PostGIS geography radius, so one successful execution is sufficient to complete
that request. Event/cooldown and normal work rotate controlled terms, but only
their resolved mode contributes background queries in a cycle:

```python
def _query_for_context(
    context: LocationContext,
    *,
    term: str,
    request_key: str | None,
    priority: int,
    matching_contexts: tuple[LocationContext, ...] | None = None,
) -> CommunitySearchQuery:
    place = " ".join(
        item for item in (context.county, context.district, context.road_or_landmark) if item
    )
    return CommunitySearchQuery(
        request_key=request_key,
        text=f"{place} {term}",
        contexts=matching_contexts or (context,),
        priority=priority,
    )


def build_cycle_queries(
    *,
    requests: tuple[CommunitySearchRequest, ...],
    request_contexts: tuple[RequestLocationContext, ...],
    triggers: tuple[OfficialTrigger, ...],
    cooldown_context: CooldownContext | None,
    normal_contexts: tuple[LocationContext, ...],
    mode: SchedulerMode,
    config: CommunitySchedulerConfig,
    now: datetime,
) -> tuple[CommunitySearchQuery, ...]:
    output: list[CommunitySearchQuery] = []
    contexts_by_request = {item.request_key: item for item in request_contexts}
    for request in requests:
        resolved = contexts_by_request.get(request.normalized_query_key)
        if resolved is not None and resolved.matching_contexts:
            output.append(_query_for_context(
                resolved.anchor, term="淹水",
                request_key=request.normalized_query_key,
                priority=request.priority,
                matching_contexts=resolved.matching_contexts,
            ))
    if mode.name in {"event", "cooldown"}:
        if mode.name == "event":
            affected = tuple(dict.fromkeys(
                context for trigger in triggers for context in trigger.affected_contexts
            ))
            neighbors = tuple(dict.fromkeys(
                context for trigger in triggers for context in trigger.neighboring_contexts
            ))
        else:
            affected = cooldown_context.affected_contexts if cooldown_context else ()
            neighbors = cooldown_context.neighboring_contexts if cooldown_context else ()
        affected_codes = {item.admin_code for item in affected}
        neighbors = tuple(item for item in neighbors if item.admin_code not in affected_codes)
        for index, context in enumerate((*affected, *neighbors)):
            output.append(_query_for_context(
                context,
                term=FLOOD_QUERY_TERMS[index % len(FLOOD_QUERY_TERMS)],
                request_key=None,
                priority=90 if index < len(affected) else 80,
            ))
    rotation = int(now.timestamp() // int(config.normal_cadence.total_seconds()))
    if mode.name == "normal" and normal_contexts:
        for offset in range(min(len(normal_contexts), 5)):
            context = normal_contexts[(rotation + offset) % len(normal_contexts)]
            output.append(_query_for_context(
                context,
                term=FLOOD_QUERY_TERMS[(rotation + offset) % len(FLOOD_QUERY_TERMS)],
                request_key=None,
                priority=20,
            ))
    deduped: dict[tuple[str, str | None], CommunitySearchQuery] = {}
    for query in sorted(output, key=lambda item: (
        -item.priority,
        item.contexts[0].admin_code or "",
        item.text,
        item.request_key or "",
    )):
        deduped.setdefault((query.text, query.request_key), query)
    return tuple(deduped.values())[:config.max_queries_per_cycle]
```

Every `RequestLocationContext` is produced from the exact persisted stable anchor
UUID. `build_cycle_queries` never reconstructs an anchor by matching names and
never picks the first UUID from ambiguous same-name rows. Its matching-context
tuple is already radius-filtered and contains only canonical reviewed road/POI
rows; no fuzzy/substring match, arbitrary URL/query, client coordinate, or
generative expansion is accepted. Priority requests may run in every mode, but
the nationwide priority-20 rotation runs only in `normal`; event and cooldown
output is therefore never diluted by normal work before the 20-query cap.

- [ ] **Step 5: Implement concrete persisted trigger and context reads**

Create `PostgresOfficialTriggerRepository` in `community/triggers.py`. It has the
four complete methods in the protocol and wraps `OSError`/`psycopg.Error` in a
typed `OfficialTriggerRepositoryUnavailable`.

`active_triggers` reads only enabled official `official_realtime_latest` rows,
their linked `evidence` geometry/properties, source catalog freshness, and the
active reviewed `realtime_jurisdiction_boundary_snapshots`/boundaries. It calls
Task 6's `official_anomaly_from_evidence`; no SQL or caller-supplied anomaly
boolean is trusted. Map point evidence to the reviewed jurisdiction containing
it and CAP/polygon evidence to every reviewed jurisdiction it intersects. Build
county/city `LocationContext` values from `realtime_jurisdictions`, with actual
boundary point-on-surface only as query text location metadata—not as evidence
compatibility. An active CAP remains a trigger until its persisted expiry even
when its original observation is older than six hours; station triggers use
their source-specific freshness deadline.

For each trigger, `affected_contexts` are the exact canonical boundaries that
contain the point or intersect the CAP geometry. `neighboring_contexts` are all
other canonical boundaries in that same active, complete, checksum-approved
22-jurisdiction snapshot for which `ST_Touches(neighbor.geom, affected.geom)`
is true. Exclude affected codes, dedupe by jurisdiction code, and order both
tuples by code. The reviewed 22-row snapshot is the hard bound; do not infer
adjacency from centroids, place-name text, client input, or an unreviewed
distance threshold.

`normal_contexts` joins the one active, complete, checksum-approved boundary
snapshot to all 22 `realtime_jurisdictions`, orders by jurisdiction code, and
returns at most 22 canonical county/city admin contexts. If that proof is absent
or incomplete, it returns no normal contexts; it never falls back to hard-coded
centroids or client values.

`contexts_for_requests` resolves each claimed request by
`geocoder_open_data_entries.id = request.anchor_geocoder_entry_id` exactly. The
anchor must still be a `road_or_lane|poi` row, have the persisted canonical name
and compatible admin code, and come from the approved open-data import; a
missing, changed, admin-only, map-click, exact-address, or mismatched row returns
no context and the request is released. Re-run the same bounded-radius ambiguity
check used by the API: if another approved row has the same admin code, canonical
name, and precision inside the selected radius, return no context even when the
two distances differ; never let UUID ordering preserve a now-ambiguous anchor.
It then selects at most 64 approved
`road_or_lane|poi` rows with
`ST_DWithin(candidate.geom::geography, anchor.geom::geography,
request.radius_m)`, ordered by exact geography distance, precision, canonical
name, then UUID. Collapse duplicate `(admin_code, canonical name, precision)`
rows to the nearest geometry before applying the 64-context bound; UUID breaks
only an otherwise identical open-data duplicate, never a geographic choice. The
exact anchor is always first and included. This is the only
request match-context tuple passed to the adapter; therefore a returned post
must explicitly match a canonical road/POI inside the selected radius. No
name-only anchor reconstruction, fuzzy/substring choice, external geocoder, raw
query, submitted point, house number, or client administrative code is accepted.

`aggregate_cooldown_context` is also persisted-only. Within the exact
`[now - horizon, now]` window, reconstruct **every** cleared event from retained
audit evidence plus: a successful warning run with
`error_code='no_active_event'`; a CAP Cancel/expiry; a station positive reading's
source-specific freshness deadline; or a real positive→zero transition derived
with `official_realtime_risk_factor` from the newest two accepted rows per
natural station key. Map that retained event geometry through the same reviewed
boundary snapshot, union affected contexts by jurisdiction code, then union exact
`ST_Touches` neighbors after excluding every affected code. Return
`window_started_at=now-horizon`, the maximum clearance time only as
`latest_cleared_at`, and both code-sorted unions. Do not use `ORDER BY ... LIMIT
1`: an older Tainan clearance and a newer Pingtung clearance inside the same
two-hour window must both remain searched. Ignore a steady stream of
never-anomalous dry rows, use indexed/time-bounded lineage reads and the reviewed
22-jurisdiction snapshot as the finite output bound, and fail closed to `None`
on incomplete lineage or boundary proof for the affected source rather than
silently substituting a different place.

- [ ] **Step 6: Implement exact mode resolution**

```python
def resolve_mode(
    *, triggers: tuple[OfficialTrigger, ...],
    cooldown_context: CooldownContext | None,
    now: datetime,
    config: CommunitySchedulerConfig,
) -> SchedulerMode:
    active = tuple(
        item for item in triggers
        if item.active_from <= now < item.active_until
        and item.event_type in {"flood_warning", "rainfall", "water_level", "flood_report"}
    )
    if active:
        return SchedulerMode("event", config.event_cadence)
    if (
        cooldown_context is not None
        and cooldown_context.window_started_at == now - config.cooldown
        and timedelta(0) <= now - cooldown_context.latest_cleared_at <= config.cooldown
    ):
        return SchedulerMode("cooldown", config.event_cadence)
    return SchedulerMode("normal", config.normal_cadence)
```

- [ ] **Step 7: Implement one advisory-locked cycle with partial success and corroboration**

```python
def run_community_cycle(
    *,
    repository: PostgresCommunityRepository,
    adapter: ThreadsKeywordSearchAdapter | None,
    trigger_repository: OfficialTriggerRepository,
    now: datetime,
    config: CommunitySchedulerConfig,
) -> CommunityCycleResult:
    with repository.community_cycle_lock() as acquired:
        if not acquired:
            return CommunityCycleResult("locked", False, 0, 0, 0, None)
        repository.prune(now=now)
        threads_enabled = (
            adapter is not None
            and repository.source_key_binding_matches(
                SOURCE_KEY,
                key_id=adapter.fingerprint_key_id,
                key_sha256=adapter.fingerprint_key_sha256,
            )
        )
        requests = (
            repository.claim_search_requests(
                now=now, limit=config.max_priority_queries
            )
            if threads_enabled else ()
        )
        triggers = trigger_repository.active_triggers(now=now)
        cooldown_context = trigger_repository.aggregate_cooldown_context(
            now=now, horizon=config.cooldown
        )
        mode = resolve_mode(
            triggers=triggers,
            cooldown_context=cooldown_context,
            now=now,
            config=config,
        )
        normal_contexts = (
            trigger_repository.normal_contexts(now=now, limit=22)
            if mode.name == "normal" else ()
        )
        request_contexts = trigger_repository.contexts_for_requests(
            requests, limit=config.max_priority_queries
        )
        queries = (
            build_cycle_queries(
                requests=requests,
                request_contexts=request_contexts,
                triggers=triggers,
                cooldown_context=cooldown_context,
                normal_contexts=normal_contexts,
                mode=mode,
                config=config,
                now=now,
            )
            if threads_enabled else ()
        )
        threads_egress_enabled = threads_enabled
        signals: list[CommunitySignalCandidate] = []
        completed: dict[str, CommunitySearchRequest] = {}
        retry_after: timedelta | None = None
        executed_count = 0
        successful_count = 0
        for query in queries:
            if not repository.source_key_binding_matches(
                SOURCE_KEY,
                key_id=adapter.fingerprint_key_id,
                key_sha256=adapter.fingerprint_key_sha256,
            ):
                threads_egress_enabled = False
                signals.clear()
                completed.clear()
                successful_count = 0
                break
            try:
                executed_count += 1
                assert adapter is not None
                signals.extend(adapter.search(
                    query=query.text,
                    contexts=query.contexts,
                    since=now - config.search_window,
                    until=now,
                    now=now,
                    egress_allowed=lambda: repository.source_key_binding_matches(
                        SOURCE_KEY,
                        key_id=adapter.fingerprint_key_id,
                        key_sha256=adapter.fingerprint_key_sha256,
                    ),
                ))
                successful_count += 1
                if query.request_key is not None:
                    completed[query.request_key] = next(
                        request for request in requests
                        if request.normalized_query_key == query.request_key
                    )
            except ThreadsRateLimited as exc:
                retry_after = exc.retry_after
                break
            except ThreadsSourceDisabled:
                threads_egress_enabled = False
                signals.clear()
                completed.clear()
                successful_count = 0
                break
            except (ThreadsHttpError, TimeoutError, ValueError):
                continue
        inserted = repository.upsert_signals(tuple(signals)) if signals else ()
        for request in requests:
            if request.normalized_query_key in completed:
                repository.complete_search_request(
                    normalized_query_key=request.normalized_query_key,
                    requested_at=request.requested_at,
                    expires_at=request.expires_at,
                    completed_at=now,
                )
            else:
                repository.release_search_request(
                    normalized_query_key=request.normalized_query_key,
                    requested_at=request.requested_at,
                    expires_at=request.expires_at,
                )
        with repository.cluster_mutation(now=now) as mutation:
            scope = mutation.load_active_cluster_inputs(now=now)
            base_decisions = cluster_signals(scope.signals, now=now)
            official = mutation.load_qualifying_official_anomalies(
                clusters=base_decisions, now=now
            )
            decisions = tuple(
                attach_corroboration(item, corroborate_cluster(item, official, now=now))
                for item in base_decisions
            )
            mutation.replace_active_clusters(decisions, scope=scope, now=now)
        if successful_count and adapter is not None and repository.source_key_binding_matches(
            SOURCE_KEY,
            key_id=adapter.fingerprint_key_id,
            key_sha256=adapter.fingerprint_key_sha256,
        ):
            repository.mark_source_success(source_key=SOURCE_KEY, completed_at=now)
        return CommunityCycleResult(
            mode.name,
            threads_egress_enabled,
            executed_count,
            len(inserted),
            len(completed),
            retry_after,
        )
```

`upsert_signals` performs its own in-transaction source-enabled and exact
key-binding read and returns an empty tuple, without writing or aborting the
cycle, if the source was disabled or rebound after the last pre-egress check.
`prune`, user-report clustering, official
corroboration, suppression effects, and cluster replacement therefore run on
every acquired cycle even when Threads is absent, revoked, rate-limited, or
disabled. No cached constructor-time database decision authorizes later egress.
The resolved `normal|event|cooldown` mode is independent from
`threads_egress_enabled`; disabled egress still reclusters first-party reports
and refreshes/withdraws official corroboration on the approved 5-minute event or
cooldown cadence.

- [ ] **Step 8: Implement the actual adaptive loop and dedicated CLI**

```python
def run_community_loop(
    *,
    cycle: Callable[[datetime], CommunityCycleResult],
    clock: Callable[[], datetime],
    sleep: Callable[[timedelta], None],
    config: CommunitySchedulerConfig,
    max_ticks: int | None = None,
) -> tuple[CommunityCycleResult, ...]:
    results: list[CommunityCycleResult] = []
    while max_ticks is None or len(results) < max_ticks:
        result = cycle(clock())
        results.append(result)
        if max_ticks is not None and len(results) >= max_ticks:
            break
        base = config.event_cadence if result.mode in {"event", "cooldown"} else config.normal_cadence
        sleep(max(base, result.retry_after or timedelta(0)))
    return tuple(results)
```

Add only `--run-community`, `--verify-threads-contract`,
`--threads-contract-output PATH`, and `--community-max-queries`; reuse the
parser's existing `--once` and `--max-ticks` options and do not register them a
second time. Parse `--community-max-queries` as an integer in the closed range
`1..20`, matching `CommunitySchedulerConfig.max_queries_per_cycle=20`; reject
zero, negative, and values above 20 before constructing a repository or making
egress. Make run/verify mutually exclusive, require the output path only
with verification, and dispatch both new branches in `app/main.py` before the
existing generic `if args.once: run_sample_job(...)` branch. The verification branch calls Task 4's
`verify_threads_keyword_contract` before constructing either repository; it
requires the approved App/token/permission gates but not
`THREADS_API_CONTRACT_VERIFIED` or `data_sources.is_enabled`, performs exactly
one non-persisting request, prints only the safe metadata result, writes the
metadata-only candidate to the explicit path with exclusive create/mode `0600`,
rejects a symlink or existing target, and exits. It never overwrites an installed
artifact.
The run branch decodes the configured key once, computes its SHA-256 in memory,
and constructs `PostgresCommunityRepository(database_url=...,
dedupe_key_id=settings.community_dedupe_hmac_key_id,
dedupe_key_sha256=key_sha256)`; raw key bytes never enter that repository, SQL,
or logs. It constructs `PostgresOfficialTriggerRepository` from the same local
database URL, then reads both
`catalog_enabled=repository.is_source_enabled(SOURCE_KEY)` and
`catalog_key_binding_matches=repository.source_key_binding_matches(
SOURCE_KEY, key_id=..., key_sha256=...)` and passes both named booleans to
`build_threads_adapter(..., fetch_json=fetch_threads_json)`. Invalid/missing
ID/key makes those values false without constructing the HTTP client. It passes
both concrete repositories
to every `run_community_cycle`; there is no fixture `normal_contexts` argument in
production. That construction check is only an initial fail-closed gate, while
every cycle and every egress rechecks the database as specified above. `--once`
calls one cycle; otherwise it calls `run_community_loop`, injecting
`sleep=lambda delay: time.sleep(delay.total_seconds())`. It never accepts an
arbitrary endpoint and never writes `worker_runtime_jobs`.

Add entrypoint regressions proving `main(["--run-community", "--once"])` invokes
exactly one community cycle and never `run_sample_job`, `--max-ticks 2` reaches
the community loop, and the verify branch performs one client request without
constructing either repository. Cover missing output, existing output, and
symlink targets as safe non-zero failures. Cover `--community-max-queries` at
1 and 20 plus parser rejection at 0, -1, and 21. For community mode, reject
`--max-ticks 0` and negative values with a parser error instead of reporting a
successful zero-cycle run; update the existing flag's help text to mention the
community loop without changing its behavior for other commands.
An entrypoint test captures repository construction, binding lookup, adapter
construction, SQL parameters, and logs: it must observe only the safe key ID and
SHA-256, never decoded bytes or hex secret, and a binding mismatch must make
zero HTTP calls.

- [ ] **Step 9: Implement non-blocking API priority upsert**

Add this API-side concrete method without importing the worker package. Its exact
signature is:

```text
prioritize_community_search(
    *,
    lat: float,
    lng: float,
    location_text: str | None,
    resolved_admin_code: str | None,
    resolved_admin_name: str | None,
    radius_m: int,
    requested_at: datetime,
) -> CommunityPriorityResult
```

The concrete body opens one local transaction and performs these exact bounded operations:

1. Require both server-resolved canonical `resolved_admin_code` and
   `resolved_admin_name`; otherwise return `idle` before alias lookup or write.
   Never substitute request/client administrative data.
2. Build transient aliases with the existing API `normalized_aliases(location_text, limit=24)` only when `location_text` is non-empty. Never insert that input or include it in logs/errors.
3. Bound radius to `50..2000` and create the query point only as a transient SQL
   parameter. A materialized `eligible` CTE reads approved
   `geocoder_open_data_entries` rows with `precision IN
   ('road_or_lane','poi')`, `row.admin_code = resolved_admin_code`, exact overlap
   with the transient aliases, and
   `ST_DWithin(row.geom::geography, query_point::geography, bounded_radius)`.
   Before selecting an anchor, the same statement checks for any eligible group
   with more than one row under `(admin_code, canonical_name, precision)`; if one
   exists, return `idle` even when the geometries are 1 metre or hundreds of
   metres apart. With no ambiguous group, select one nearest row by exact alias
   rank, `ST_Distance(...::geography)`, precision, then UUID. UUID is only stable
   ordering after uniqueness is proven and never resolves geographic ambiguity.
   Require `row.id` to be the deterministic UUIDv5 produced by the reviewed
   open-data importer. Do not accept an admin-area fallback, `exact_address`,
   `map_click`, a null-admin row, or arbitrary client `admin_code`.
4. Construct only canonical parts from the trusted pair/row:
   `anchor_geocoder_entry_id=row.id`, `county=resolved_admin_name`, and
   `road_or_landmark=row.name`; use a reviewed canonical district from that row
   only when present, otherwise explicit `null`. Reapply the same length,
   identity-token, URL, phone, and house-number rejection rules as
   `build_search_request`; a private address, county-only input, missing anchor,
   or ambiguity returns `idle`, never a partial stored value. The submitted
   point is neither inserted nor logged.
5. Compute the same canonical-JSON request key over the stable public anchor UUID,
   explicit county/district/road-or-landmark null slots, and bounded radius. In
   that transaction first
   `DELETE FROM community_search_requests WHERE normalized_query_key=%(key)s
   AND expires_at <= %(requested_at)s`, then insert a fresh `pending` row with
   `expires_at=requested_at + interval '15 minutes'`. On an unexpired conflict,
   update only maximum bounded priority and preserve canonical fields,
   `requested_at`, `expires_at`, and status. The worker/API vector suites load
   the same root fixture; delimiter, null-boundary, field-swap, and identical
   name/different-anchor cases cannot collide. The insert stores
   `anchor_geocoder_entry_id` but no submitted coordinates. The expired-key
   regression must claim the newly inserted row with the same anchor UUID.

After Task 7's base response is complete, replace its fixed `idle` block with exactly one fail-soft call:

```python
try:
    priority = self._repository.prioritize_community_search(
        lat=request.point.lat,
        lng=request.point.lng,
        location_text=request.location_text,
        resolved_admin_code=data.resolved_admin_code,
        resolved_admin_name=data.resolved_admin_name,
        radius_m=request.radius_m,
        requested_at=now,
    )
except CommunityRepositoryUnavailable:
    priority = CommunityPriorityResult(
        state="not_available",
        last_completed_at=snapshot.last_completed_at,
    )
```

It returns `idle` when no unique canonical road/POI anchor is available,
`prioritized` after the local upsert, and `not_available` only on repository
failure. Add API tests proving client text, coordinates, and client-supplied
administrative codes are never persisted or trusted; missing server admin and
county-only/ambiguous matches are idle; same-named roads cannot cross counties
or use UUID as a geographic tie-break; exact addresses fall back only to a
unique canonical road/POI inside the selected radius or `idle`; and a DB failure
does not change the completed assessment. The service never calls worker or
upstream code.

- [ ] **Step 10: Run worker scheduler and API tests separately**

Run: `(cd apps/workers && python -m pytest tests/test_community_search_requests.py tests/test_community_scheduler.py tests/test_community_triggers.py tests/test_worker_entrypoints.py tests/test_community_fixture_integration.py tests/test_threads_keyword_search_adapter.py -q)`

Run: `(cd apps/api && python -m pytest tests/test_assessment_service.py tests/test_community_repository.py -q)`

Expected: both commands PASS; API tests import no worker `app` package.

- [ ] **Step 11: Commit the real background loop**

```bash
git add apps/workers/app/community/contracts.py apps/workers/app/community/search_requests.py apps/workers/app/community/scheduler.py apps/workers/app/community/triggers.py apps/workers/app/community/repository.py apps/workers/app/cli/community_cli.py apps/workers/app/cli/parser.py apps/workers/app/main.py apps/workers/tests/test_community_search_requests.py apps/workers/tests/test_community_scheduler.py apps/workers/tests/test_community_triggers.py apps/workers/tests/test_worker_entrypoints.py apps/api/app/domain/community/repository.py apps/api/app/api/services/assessment.py apps/api/tests/test_assessment_service.py apps/api/tests/test_community_repository.py tests/fixtures/community_request_key_vectors.json
git commit -m "feat: run bounded adaptive community searches"
```

---

### Task 9: Enforce Exact Source Policy and Quarantined Browser Discovery

**Files:**

- Create: `docs/data-sources/community/source-policy.yaml`
- Create: `docs/data-sources/community/browser-discovery.example.yaml`
- Create: `docs/runbooks/community-browser-discovery.md`
- Create: `infra/scripts/validate_community_source_policy.py`
- Create: `infra/scripts/rotate_community_dedupe_key.py`
- Create: `tests/test_community_source_policy_validator.py`
- Create: `tests/test_rotate_community_dedupe_key.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `docs/PROJECT_SDD.md`
- Modify: `docs/adr/0007-official-and-public-evidence-strategy.md`

**Interfaces:**

- Consumes: YAML documents with `kind=community_source_policy` or `kind=community_source_discovery`.
- Produces: `validate_document(payload: Mapping[str, object]) -> list[str]`; exact recursive allowlists; Threads/user-report/PTT/Dcard invariants; a discovery shape that can never approve automation or write runtime data.

- [ ] **Step 1: Write exact allowlist and cross-policy RED tests**

```python
@pytest.mark.parametrize(
    "unknown_key",
    [
        "raw_text", "body", "comments", "author", "handle", "personal_account",
        "session", "cookie", "captcha_bypass", "anti_bot_bypass", "paywall_bypass",
        "screenshot", "media", "contact", "private_address", "writes_event",
        "writes_community_signal", "risk_effect", "production_enabled",
    ],
)
def test_discovery_rejects_every_unknown_or_forbidden_key(unknown_key: str) -> None:
    payload = valid_discovery()
    payload[unknown_key] = True
    assert validate_document(payload) == [f"unknown discovery key: {unknown_key}"]


def test_source_policy_and_discovery_have_different_valid_shapes() -> None:
    assert validate_document(valid_source_policy()) == []
    assert validate_document(valid_discovery()) == []


def test_threads_policy_requires_official_api_all_gates_and_disabled_default() -> None:
    payload = valid_source_policy()
    threads = source(payload, "social.threads.keyword_search")
    threads["required_gates"].remove("THREADS_APP_REVIEW_APPROVED")
    assert "Threads policy missing required gate: THREADS_APP_REVIEW_APPROVED" in validate_document(payload)


@pytest.mark.parametrize("source_key", [
    "social.threads.keyword_search", "community.user_report",
])
def test_key_id_gate_is_mandatory_for_both_keyed_sources(source_key: str) -> None:
    payload = valid_source_policy()
    source(payload, source_key)["required_gates"].remove(
        "COMMUNITY_DEDUPE_HMAC_KEY_ID"
    )
    assert any(
        "missing required gate: COMMUNITY_DEDUPE_HMAC_KEY_ID" in error
        for error in validate_document(payload)
    )


def test_ptt_and_dcard_are_blocked_no_network() -> None:
    payload = valid_source_policy()
    for key in ("forum.ptt.candidate", "forum.dcard.candidate"):
        item = source(payload, key)
        assert item["enabled"] is False
        assert item["access_mode"] == "blocked_no_network"


def test_recursive_policy_shape_rejects_nested_payloads_and_extra_sources() -> None:
    payload = valid_source_policy()
    source(payload, "community.user_report")["required_gates"] = [
        "USER_REPORTS_ENABLED", {"hidden": "raw_text"}
    ]
    payload["sources"].append({**source(payload, "forum.ptt.candidate"), "source_key": "forum.other"})
    errors = validate_document(payload)
    assert "community.user_report.required_gates must contain strings only" in errors
    assert "unapproved source_key: forum.other" in errors


def test_discovery_known_scalar_cannot_hide_nested_data() -> None:
    payload = valid_discovery()
    payload["reviewer"] = {"handle": "fixture"}
    assert "browser discovery reviewer must be supervised-operator" in validate_document(payload)


@pytest.mark.parametrize("url", [
    "https://www.threads.net/@real_handle/post/123456",
    "https://social.example/users/person/status/123456",
    "https://social.example/profile/person",
    "https://127.0.0.1/source",
    "https://169.254.1.1/source",
    "https://localhost/source",
])
def test_discovery_rejects_identity_permalink_and_non_public_hosts(url: str) -> None:
    payload = valid_discovery()
    payload["discovered_url"] = url
    assert (
        "browser discovery URL must be a public source landing/API/docs URL"
        in validate_document(payload)
    )
```

- [ ] **Step 2: Run tests and verify missing validator**

Run: `python -m pytest tests/test_community_source_policy_validator.py -v`

Expected: FAIL during import.

- [ ] **Step 3: Create the complete reviewed source policy**

```yaml
version: 1
kind: community_source_policy
config_version: v1-community-2026-08-24
sources:
  - source_key: social.threads.keyword_search
    source_type: social
    access_mode: official_api
    endpoint_host: graph.threads.net
    enabled: false
    required_gates:
      - SOURCE_THREADS_ENABLED
      - SOURCE_THREADS_API_ENABLED
      - THREADS_APP_REVIEW_APPROVED
      - THREADS_KEYWORD_SEARCH_PERMISSION_APPROVED
      - THREADS_API_CONTRACT_VERIFIED
      - THREADS_ACCESS_TOKEN
      - COMMUNITY_DEDUPE_HMAC_KEY_ID
      - COMMUNITY_DEDUPE_HMAC_KEY
    terms_review: required
    permission_review: required
    retention_days: 30
    deletion_sync: operator_suppression_or_supervised_public_deletion_check
  - source_key: community.user_report
    source_type: user_report
    access_mode: first_party_user_report
    endpoint_host: null
    enabled: false
    required_gates:
      - USER_REPORTS_ENABLED
      - COMMUNITY_DEDUPE_HMAC_KEY_ID
      - COMMUNITY_DEDUPE_HMAC_KEY
    terms_review: not_applicable
    permission_review: moderation_required
    retention_days: 30
    deletion_sync: privacy_redaction_and_operator_suppression
  - source_key: forum.ptt.candidate
    source_type: forum
    access_mode: blocked_no_network
    endpoint_host: null
    enabled: false
    required_gates: []
    terms_review: pending_formal_feed_approval
    permission_review: pending
    retention_days: 0
    deletion_sync: not_applicable
  - source_key: forum.dcard.candidate
    source_type: forum
    access_mode: blocked_no_network
    endpoint_host: null
    enabled: false
    required_gates: []
    terms_review: written_permission_required
    permission_review: pending
    retention_days: 0
    deletion_sync: not_applicable
```

- [ ] **Step 4: Create the exact quarantined discovery shape**

```yaml
version: 1
kind: community_source_discovery
status: quarantined
discovered_url: https://example.test/public-source-page
source_kind: public_social_or_official_page
access_observation: public_page_only
discovered_at: "2026-08-24T00:00:00Z"
reviewer: supervised-operator
stores_raw_content: false
stores_identity: false
automated_access_approved: false
```

The example uses a reserved synthetic domain and contains no event, person, post body, query, screenshot, or media.

- [ ] **Step 5: Implement kind-dispatched exact recursive validation**

```python
# infra/scripts/validate_community_source_policy.py
from __future__ import annotations

import ipaddress
from collections.abc import Mapping, Sequence
from datetime import datetime
from urllib.parse import SplitResult, unquote, urlsplit

DISCOVERY_KEYS = frozenset({
    "version", "kind", "status", "discovered_url", "source_kind",
    "access_observation", "discovered_at", "reviewer", "stores_raw_content",
    "stores_identity", "automated_access_approved",
})
POLICY_KEYS = frozenset({"version", "kind", "config_version", "sources"})
SOURCE_KEYS = frozenset({
    "source_key", "source_type", "access_mode", "endpoint_host", "enabled",
    "required_gates", "terms_review", "permission_review", "retention_days",
    "deletion_sync",
})
THREADS_GATES = frozenset({
    "SOURCE_THREADS_ENABLED", "SOURCE_THREADS_API_ENABLED",
    "THREADS_APP_REVIEW_APPROVED",
    "THREADS_KEYWORD_SEARCH_PERMISSION_APPROVED",
    "THREADS_API_CONTRACT_VERIFIED",
    "THREADS_ACCESS_TOKEN", "COMMUNITY_DEDUPE_HMAC_KEY_ID",
    "COMMUNITY_DEDUPE_HMAC_KEY",
})
USER_REPORT_GATES = frozenset({
    "USER_REPORTS_ENABLED", "COMMUNITY_DEDUPE_HMAC_KEY_ID",
    "COMMUNITY_DEDUPE_HMAC_KEY",
})
EXPECTED_SOURCE_KEYS = frozenset({
    "social.threads.keyword_search", "community.user_report",
    "forum.ptt.candidate", "forum.dcard.candidate",
})
SOURCE_RULES: dict[str, Mapping[str, object]] = {
    "social.threads.keyword_search": {
        "source_type": "social", "access_mode": "official_api",
        "endpoint_host": "graph.threads.net", "enabled": False,
        "terms_review": "required", "permission_review": "required",
        "retention_days": 30,
        "deletion_sync": "operator_suppression_or_supervised_public_deletion_check",
    },
    "community.user_report": {
        "source_type": "user_report", "access_mode": "first_party_user_report",
        "endpoint_host": None, "enabled": False,
        "terms_review": "not_applicable", "permission_review": "moderation_required",
        "retention_days": 30,
        "deletion_sync": "privacy_redaction_and_operator_suppression",
    },
    "forum.ptt.candidate": {
        "source_type": "forum", "access_mode": "blocked_no_network",
        "endpoint_host": None, "enabled": False,
        "terms_review": "pending_formal_feed_approval", "permission_review": "pending",
        "retention_days": 0, "deletion_sync": "not_applicable",
    },
    "forum.dcard.candidate": {
        "source_type": "forum", "access_mode": "blocked_no_network",
        "endpoint_host": None, "enabled": False,
        "terms_review": "written_permission_required", "permission_review": "pending",
        "retention_days": 0, "deletion_sync": "not_applicable",
    },
}


def _unknown_keys(payload: Mapping[str, object], allowed: frozenset[str]) -> list[str]:
    return sorted(
        str(key) for key in payload
        if not isinstance(key, str) or key not in allowed
    )


def _missing_keys(payload: Mapping[str, object], required: frozenset[str]) -> list[str]:
    return sorted(required - set(payload))


def _string_list(value: object, *, path: str, errors: list[str]) -> tuple[str, ...] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        errors.append(f"{path} must be a list of strings")
        return None
    if any(not isinstance(item, str) for item in value):
        errors.append(f"{path} must contain strings only")
        return None
    result = tuple(value)
    if len(result) != len(set(result)):
        errors.append(f"{path} must not contain duplicates")
        return None
    return result


def _is_public_source_level_url(parsed: SplitResult) -> bool:
    host = (parsed.hostname or "").lower().rstrip(".")
    if host == "example.test":
        return parsed.path == "/public-source-page"
    if host == "localhost" or host.endswith((".localhost", ".local")):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        return False

    path = unquote(parsed.path or "/")
    segments = tuple(segment.lower() for segment in path.split("/") if segment)
    identity_segments = {
        "post", "posts", "status", "statuses", "profile", "profiles",
        "user", "users",
    }
    if "@" in path or any(segment in identity_segments for segment in segments):
        return False
    if host in {"threads.net", "www.threads.net"}:
        return path == "/"
    if host == "graph.threads.net":
        return path == "/keyword_search"

    source_path_roots = {
        "api", "apis", "data", "developer", "developers", "docs",
        "documentation", "open-data", "opendata", "openapi", "source",
        "sources",
    }
    return not segments or segments[0] in source_path_roots


def validate_discovery(payload: Mapping[str, object]) -> list[str]:
    errors = [f"unknown discovery key: {key}" for key in _unknown_keys(payload, DISCOVERY_KEYS)]
    errors.extend(
        f"missing discovery key: {key}" for key in _missing_keys(payload, DISCOVERY_KEYS)
    )
    if payload.get("version") != 1 or payload.get("kind") != "community_source_discovery":
        errors.append("browser discovery version/kind must be exact")
    if payload.get("status") != "quarantined":
        errors.append("browser discovery status must be quarantined")
    if payload.get("source_kind") != "public_social_or_official_page":
        errors.append("browser discovery source_kind is not allowed")
    if payload.get("access_observation") != "public_page_only":
        errors.append("browser discovery access_observation must be public_page_only")
    if payload.get("reviewer") != "supervised-operator":
        errors.append("browser discovery reviewer must be supervised-operator")
    url = payload.get("discovered_url")
    if not isinstance(url, str):
        errors.append("browser discovery discovered_url must be a string")
    else:
        try:
            parsed = urlsplit(url)
            valid_url = bool(
                parsed.scheme == "https" and parsed.hostname
                and not parsed.username and not parsed.password
                and not parsed.query and not parsed.fragment
            )
        except ValueError:
            valid_url = False
        if not valid_url:
            errors.append("browser discovery URL must be public canonical HTTPS without credentials, query, or fragment")
        elif not _is_public_source_level_url(parsed):
            errors.append("browser discovery URL must be a public source landing/API/docs URL")
    discovered_at = payload.get("discovered_at")
    if not isinstance(discovered_at, str):
        errors.append("browser discovery discovered_at must be an RFC3339 string")
    else:
        try:
            parsed_at = datetime.fromisoformat(discovered_at.replace("Z", "+00:00"))
        except ValueError:
            parsed_at = None
        if parsed_at is None or parsed_at.tzinfo is None:
            errors.append("browser discovery discovered_at must be timezone-aware RFC3339")
    if payload.get("stores_raw_content") is not False:
        errors.append("browser discovery must not store raw content")
    if payload.get("stores_identity") is not False:
        errors.append("browser discovery must not store identity")
    if payload.get("automated_access_approved") is not False:
        errors.append("browser discovery cannot approve automated access")
    return errors


def validate_source_policy(payload: Mapping[str, object]) -> list[str]:
    errors = [f"unknown policy key: {key}" for key in _unknown_keys(payload, POLICY_KEYS)]
    errors.extend(f"missing policy key: {key}" for key in _missing_keys(payload, POLICY_KEYS))
    if payload.get("version") != 1 or payload.get("kind") != "community_source_policy":
        errors.append("source policy version/kind must be exact")
    if payload.get("config_version") != "v1-community-2026-08-24":
        errors.append("source policy config_version must be exact")
    sources = payload.get("sources")
    if not isinstance(sources, Sequence) or isinstance(sources, (str, bytes)):
        return [*errors, "source policy sources must be a list"]
    by_key: dict[str, Mapping[str, object]] = {}
    for index, item in enumerate(sources):
        if not isinstance(item, Mapping):
            errors.append(f"source[{index}] must be an object")
            continue
        errors.extend(
            f"source[{index}] unknown key: {key}"
            for key in _unknown_keys(item, SOURCE_KEYS)
        )
        errors.extend(
            f"source[{index}] missing key: {key}"
            for key in _missing_keys(item, SOURCE_KEYS)
        )
        key = item.get("source_key")
        if not isinstance(key, str):
            errors.append(f"source[{index}].source_key must be a string")
            continue
        if key in by_key:
            errors.append(f"duplicate source_key: {key}")
            continue
        by_key[key] = item
        rules = SOURCE_RULES.get(key)
        if rules is None:
            errors.append(f"unapproved source_key: {key}")
            continue
        for field, expected in rules.items():
            if item.get(field) != expected or type(item.get(field)) is not type(expected):
                errors.append(f"{key}.{field} must equal {expected!r}")
        gates = _string_list(
            item.get("required_gates"), path=f"{key}.required_gates", errors=errors
        )
        expected_gates = (
            THREADS_GATES if key == "social.threads.keyword_search"
            else USER_REPORT_GATES if key == "community.user_report"
            else frozenset()
        )
        if gates is not None:
            actual_gates = frozenset(gates)
            errors.extend(
                f"{key} missing required gate: {gate}"
                for gate in sorted(expected_gates - actual_gates)
            )
            errors.extend(
                f"{key} has unapproved gate: {gate}"
                for gate in sorted(actual_gates - expected_gates)
            )
    errors.extend(
        f"missing required source: {key}" for key in sorted(EXPECTED_SOURCE_KEYS - set(by_key))
    )
    threads = by_key.get("social.threads.keyword_search")
    if threads is None:
        errors.append("Threads policy is required")
    else:
        if threads.get("access_mode") != "official_api" or threads.get("enabled") is not False:
            errors.append("Threads must be disabled-by-default official_api")
        gates = _string_list(threads.get("required_gates"), path="Threads required_gates", errors=[])
        if gates is not None:
            errors.extend(
                f"Threads policy missing required gate: {gate}"
                for gate in sorted(THREADS_GATES - frozenset(gates))
            )
    for blocked in ("forum.ptt.candidate", "forum.dcard.candidate"):
        item = by_key.get(blocked)
        if item is None or item.get("access_mode") != "blocked_no_network" or item.get("enabled") is not False:
            errors.append(f"{blocked} must remain blocked_no_network and disabled")
    return errors


def validate_document(payload: Mapping[str, object]) -> list[str]:
    kind = payload.get("kind")
    if kind == "community_source_discovery":
        return validate_discovery(payload)
    if kind == "community_source_policy":
        return validate_source_policy(payload)
    return ["kind must be community_source_discovery or community_source_policy"]
```

The URL rule treats `example.test` as the one synthetic-fixture exception. It
rejects local/non-global IP destinations, identity-bearing post/profile paths,
and arbitrary deep links; Threads discovery is origin-only and the Threads API
is limited to the documented keyword-search path. `stores_identity=false` is a
validated consequence of that URL shape, never a declaration that can make an
identity permalink safe.

This is recursively exact because the only nested containers are `sources[*]` and `required_gates[*]`: source-object keys are allowlisted, gates must be duplicate-free strings, and every other known field is checked against an exact scalar type/value. Thus a mapping/list hidden under any known scalar or gate is rejected rather than ignored. The CLI loads YAML with `yaml.safe_load`, requires one mapping, prints every error to stderr, and exits 1 on any error. It never imports database, browser, adapter, or assessment code.

- [ ] **Step 6: Implement the fail-closed key-drain rotation command**

`rotate_community_dedupe_key.py --new-key-id ID` reads the new hex secret only
from `COMMUNITY_DEDUPE_HMAC_KEY`, validates ID/key exactly as the API/worker do,
and reads the database URL from the existing server setting; the secret is
never a command-line argument, SQL parameter, log field, or output. There is no
`--force` option. A separately authenticated operator transaction must first
disable both community source rows. The command then uses one transaction to:

1. acquire `pg_advisory_xact_lock(hashtextextended('flood-risk:v1:community-mutation', 0))`;
2. lock both source rows, require both to exist and already be disabled, then
   count Threads suppressions with `expires_at IS NULL OR expires_at > now()`;
   if the count is nonzero, raise before any delete or metadata update so the
   old binding and suppression set remain intact and both sources stay disabled;
3. with zero active Threads suppressions, delete all
   `community_search_requests`, all community assessment links, private report
   links, all community signals and their cluster links, all now-empty community
   clusters, and only expired suppression rows; preserve first-party
   moderation/audit records;
4. assert zero retained community signals, links, clusters, associations,
   requests, and suppressions;
5. replace (not merge) `dedupe_hmac_key_id` and
   `dedupe_hmac_key_sha256=sha256(decoded_key)` in both source metadata rows,
   leaving both disabled, then commits.

The command refuses to run if either source row is missing or enabled, if an
unexpected source owns a community row, if any active/permanent Threads
suppression exists, or if a zero-count postcondition fails. It prints only safe
row counts and the new key ID. A two-connection regression pauses an old-key
writer around the shared lock and proves either ordering ends with zero old-key
rows; subsequent old-key Threads egress and user-report promotion fail their
metadata binding. Additional tests prove same ID/new bytes and new ID/same bytes
fail closed, an active or permanent Threads suppression causes a rollback with
zero deletions and unchanged metadata, an expired suppression is drained, the
same synthetic post cannot appear as two concurrent origins, and no CLI option
can bypass the suppression precondition. Re-enable either source only in a
separate reviewed operator transaction after the new deployment proves the
matching ID/fingerprint and zero retained old-key state. If an emergency key
change is required while an active suppression exists, keep both sources
disabled; a future reviewed suppression re-key workflow is outside v1.

- [ ] **Step 7: Document the supervised workflow and CI commands**

The runbook permits only source discovery, manual existence/deletion/layout checks, and an explicitly requested public-event verification. Findings remain YAML-only and quarantined. A source can become an adapter only through a separate reviewed policy/config change satisfying official API/feed/authorization. Browser event observations have no importer in v1; they cannot enter `community_signals`, `event_clusters`, generic `evidence`, or risk.

Add CI commands:

```bash
python infra/scripts/validate_community_source_policy.py docs/data-sources/community/source-policy.yaml
python infra/scripts/validate_community_source_policy.py docs/data-sources/community/browser-discovery.example.yaml
python -m pytest tests/test_community_source_policy_validator.py tests/test_rotate_community_dedupe_key.py -q
```

- [ ] **Step 8: Run policy, rotation, and documentation tests**

Run: `python infra/scripts/validate_community_source_policy.py docs/data-sources/community/source-policy.yaml && python infra/scripts/validate_community_source_policy.py docs/data-sources/community/browser-discovery.example.yaml && python -m pytest tests/test_community_source_policy_validator.py tests/test_rotate_community_dedupe_key.py -q`

Expected: PASS.

- [ ] **Step 9: Commit the quarantined boundary and key lifecycle**

```bash
git add docs/data-sources/community/source-policy.yaml docs/data-sources/community/browser-discovery.example.yaml docs/runbooks/community-browser-discovery.md infra/scripts/validate_community_source_policy.py infra/scripts/rotate_community_dedupe_key.py tests/test_community_source_policy_validator.py tests/test_rotate_community_dedupe_key.py .github/workflows/ci.yml docs/PROJECT_SDD.md docs/adr/0007-official-and-public-evidence-strategy.md
git commit -m "docs: enforce exact community source and browser policy"
```

---

### Task 10: Render Sanitized Community State and Authoritative Labels in Web

**Files:**

- Modify: `apps/api/app/api/schemas.py`
- Modify: `apps/api/app/api/services/public_evidence.py`
- Modify: `docs/api/openapi.yaml`
- Modify: `apps/api/tests/test_public_contract.py`
- Modify: `apps/api/tests/test_community_assessment_integration.py`
- Modify: `apps/web/app/lib/page-types.ts`
- Modify: `apps/web/app/lib/risk-display/types.ts`
- Modify: `apps/web/app/lib/risk-display/risk.ts`
- Modify: `apps/web/app/lib/risk-display/evidence.ts`
- Modify: `apps/web/app/lib/ui-text.ts`
- Modify: `apps/web/app/components/risk-summary-section.tsx`
- Modify: `apps/web/app/components/evidence-section.tsx`
- Modify: `apps/web/app/page.tsx`
- Modify: `apps/web/tests/unit/risk-display.test.ts`
- Modify: `apps/web/tests/e2e/map-risk.spec.ts`

**Interfaces:**

- Consumes: core additive response, `CommunitySignalRecord`, `CommunityDecision`, uplifted `OverallDecision`, `CommunityPriorityResult`, assessment association/evidence union.
- Produces: exact API/OpenAPI/TypeScript fields, null community `raw_ref`, source/community label helpers, server-authoritative overall rendering, and reload-only refresh messaging.

- [ ] **Step 1: Write API contract, privacy, expanded-evidence, and no-worker-import RED tests**

```python
def test_community_preview_is_template_only_and_raw_ref_is_null() -> None:
    response = service_with_persisted_community().assess(COMMUNITY_REQUEST, now=NOW)
    social = next(item for item in response.evidence if item.source_type == "social")
    assert social.raw_ref is None
    assert social.url is None
    assert social.published_at == SIGNAL_PUBLISHED_AT
    assert social.community_state == "community_corroborated"
    assert social.location_precision in {"road_or_lane", "poi", "admin_area", "map_click"}
    serialized = social.model_dump_json()
    assert RAW_THREADS_TEXT not in serialized
    assert "author" not in serialized.lower()


def test_expanded_evidence_keeps_community_raw_ref_null() -> None:
    response = client.get(f"/v1/evidence/{ASSESSMENT_ID}")
    social = next(item for item in response.json()["items"] if item["source_type"] == "social")
    assert social["raw_ref"] is None


def test_api_service_has_no_worker_or_upstream_dependency() -> None:
    signature = inspect.signature(AssessmentService)
    assert tuple(signature.parameters) == ("repository", "scorer")
    assert "apps.workers" not in inspect.getsource(AssessmentService)
```

- [ ] **Step 2: Re-verify Task 7's additive API metadata before presentation**

Task 7 already added these defaulted fields so its assessment/detail paths are
green and published the static schema. Do not redeclare them or widen the
identifier union; verify their exact shape, retain the OpenAPI contract, and
update only response examples needed by the presentation tests:

```python
published_at: datetime | None = None
source_label: str | None = None
community_state: Literal[
    "unverified", "community_corroborated", "officially_corroborated"
] | None = None
raw_ref: str | None = None
```

Retain the core plan's shared `EvidenceLocationPrecision` and existing
`limitations`; do not redefine either field or reuse the broader geocoder type.
`Evidence` inherits `raw_ref`; remove its duplicate declaration. Community
conversion emits only `road_or_lane|poi|admin_area|map_click`, sets source label
`Threads 正式 API` or `使用者回報`, uses the template summary, preserves cluster
state as `unverified|community_corroborated|officially_corroborated`, includes
`群眾訊號可能早於官方確認，請查看官方警報與現地狀況。`, forces
persisted `source_url=None`, emits public `url=None`, and forces `raw_ref=None`. Generic evidence behavior remains
additive.

Keep the core response fields exactly:

```python
community: CommunityRiskBlock
overall: RiskLevelBlock
dominant_mode: DominantMode
data_status: DataStatus
community_refresh: CommunityRefresh
```

`community_refresh.last_completed_at` comes from `CommunitySnapshot.last_completed_at`; state is `prioritized`, `idle`, or `not_available`. Update the OpenAPI schemas/examples and validator expectations in the same step.

- [ ] **Step 3: Extend TypeScript contracts and label helpers**

```typescript
export type CommunityState =
  | "none"
  | "unverified"
  | "community_corroborated"
  | "officially_corroborated";

export type EvidencePreview = {
  id: string;
  source_type: string;
  event_type: string;
  title: string;
  summary: string;
  confidence: number;
  occurred_at?: string | null;
  observed_at: string | null;
  published_at?: string | null;
  ingested_at: string | null;
  url?: string | null;
  distance_to_query_m: number | null;
  source_label?: string | null;
  location_precision?: EvidenceLocationPrecision;
  community_state?:
    | "unverified"
    | "community_corroborated"
    | "officially_corroborated"
    | null;
  limitations?: string[];
  raw_ref?: string | null;
};
```

Add `social: "群眾社群訊號"` to `sourceTypeLabels` in `apps/web/app/lib/ui-text.ts`. Keep `EvidenceDisplayText` unchanged and add these helpers in that same file (import `EvidencePreview` with `import type`; do not create an `evidence.ts` ↔ `ui-text.ts` cycle):

```typescript
export function evidenceSourceLabel(item: EvidencePreview) {
  return item.source_label ?? sourceTypeLabel(item.source_type);
}

export function communityEvidenceLabel(item: EvidencePreview) {
  if (item.community_state === "officially_corroborated") return "官方已佐證群眾訊號";
  if (item.community_state === "community_corroborated") return "群眾已交叉佐證";
  if (item.community_state === "unverified") return "群眾未驗證";
  return null;
}
```

The shared `EvidencePreview.raw_ref` remains `string | null` for existing official evidence. The API converter and tests enforce the narrower runtime rule `raw_ref === null` for every community item.

`assessmentRiskPresentation` keeps the core interface exactly: `riskLevel` is
the existing display-value mapping of `assessment.overall.level`, and
`contextLabel` maps `dominant_mode="community_warning"` to
`群眾交叉佐證警戒`. It never adds `level`/`heading` fields or takes a
realtime/historical maximum.

- [ ] **Step 4: Write Web unit tests for authoritative overall and labels**

```typescript
test("community warning uses server overall and explicit labels", () => {
  const assessment = communityWarningAssessment();
  const state = assessmentRiskPresentation(assessment);
  assert.equal(state.riskLevel, "中");
  assert.equal(state.dominantMode, "community_warning");
  assert.equal(state.contextLabel, "群眾交叉佐證警戒");
  assert.equal(evidenceSourceLabel(CORROBORATED_THREADS), "Threads 正式 API");
  assert.equal(communityEvidenceLabel(CORROBORATED_THREADS), "群眾已交叉佐證");
});


test("single origin remains unverified and does not change overall", () => {
  const assessment = singleOriginAssessment();
  assert.equal(assessment.community.state, "unverified");
  assert.equal(assessment.overall.level, assessment.realtime.level);
  assert.equal(communityEvidenceLabel(UNVERIFIED_THREADS), "群眾未驗證");
});
```

- [ ] **Step 5: Render summary, evidence metadata, limitations, and refresh**

`risk-summary-section.tsx` renders `無`, `群眾未驗證`, or `群眾已交叉佐證`. `evidence-section.tsx` renders `evidenceSourceLabel`, `communityEvidenceLabel`, published/observed time, distance, precision via `geocodePrecisionLabel`, confidence, and every limitation. `page.tsx` shows `已排入更新；目前結果更新於 {last_completed_at ?? as_of}` only for `prioritized`; it does not poll or invoke refresh automatically.

- [ ] **Step 6: Add E2E fixtures/assertions for unverified, corroborated, expanded, and non-blocking states**

```typescript
await expect(page.getByTestId("risk-summary")).toContainText("群眾已交叉佐證");
await expect(page.getByTestId("risk-summary")).toContainText("整體警戒：中");
await expect(page.getByTestId("community-refresh")).toContainText("已排入更新");
await expect(page.getByTestId("evidence-panel")).toContainText("Threads 正式 API");
await expect(page.getByTestId("evidence-panel")).toContainText("位置精度");
```

Add a separate single-origin API fixture whose realtime/overall remain unchanged and card reads `群眾未驗證`. Expanding evidence must return the same sanitized signal and null raw ref. No fixture imports or calls worker code.

- [ ] **Step 7: Run API and Web verification separately**

Run: `(cd apps/api && python -m pytest tests/test_public_contract.py tests/test_assessment_service.py tests/test_community_assessment_integration.py -q)`

Run: `python infra/scripts/validate_openapi.py`

Run: `npm test --prefix apps/web && npm run typecheck --prefix apps/web && npm run lint --prefix apps/web && npm run e2e --prefix apps/web -- --grep "community|群眾"`

Expected: all commands PASS.

- [ ] **Step 8: Commit public presentation**

```bash
git add apps/api/app/api/schemas.py apps/api/app/api/services/public_evidence.py apps/api/tests/test_public_contract.py apps/api/tests/test_community_assessment_integration.py docs/api/openapi.yaml apps/web/app/lib/page-types.ts apps/web/app/lib/risk-display/types.ts apps/web/app/lib/risk-display/risk.ts apps/web/app/lib/risk-display/evidence.ts apps/web/app/lib/ui-text.ts apps/web/app/components/risk-summary-section.tsx apps/web/app/components/evidence-section.tsx apps/web/app/page.tsx apps/web/tests/unit/risk-display.test.ts apps/web/tests/e2e/map-risk.spec.ts
git commit -m "feat: present sanitized corroborated community evidence"
```

---

### Task 11: Full Privacy, Fixture, Integration, and Operational Acceptance

**Files:**

- Modify: `README.md`
- Modify: `apps/api/README.md`
- Modify: `apps/workers/README.md`
- Modify: `docs/PROJECT_SDD.md`
- Modify: `docs/PROJECT_WORK_PLAN.md`
- Modify: `docs/runbooks/runtime-smoke.md`

**Interfaces:**

- Consumes: all prior tasks and the completed core/official plan.
- Produces: repeatable no-egress fixture acceptance, disabled/live gate smoke commands, privacy audits, and operator instructions.

- [ ] **Step 1: Add cross-stack synthetic privacy assertions to both integration suites**

```python
SENSITIVE_MARKERS = (
    "author-fixture-123",
    "@fixture_handle",
    "fixture-user-id-456",
    "fixture full post body",
    "<html>fixture</html>",
    "session-cookie-fixture",
    "https://media.example.test/fixture.jpg",
)


def assert_no_sensitive_markers(value: object) -> None:
    serialized = json.dumps(value, ensure_ascii=False, default=str)
    for marker in SENSITIVE_MARKERS:
        assert marker not in serialized
```

Worker integration applies this to SQL params/logs/cluster results. API integration applies it to assessment persistence, previews, expanded evidence, and JSON snapshots.

- [ ] **Step 2: Run root migration and both exact policy validations**

Run: `python infra/scripts/validate_migrations.py && python infra/scripts/validate_community_source_policy.py docs/data-sources/community/source-policy.yaml && python infra/scripts/validate_community_source_policy.py docs/data-sources/community/browser-discovery.example.yaml && python -m pytest tests/test_v1_community_schema.py tests/test_community_source_policy_validator.py -q`

Expected: PASS.

- [ ] **Step 3: Run mandatory migrated-PostGIS concurrency acceptance**

```bash
docker compose up -d postgres
docker compose --profile tools run --rm migrate
(cd apps/workers && COMMUNITY_DB_ACCEPTANCE_REQUIRED=1 COMMUNITY_TEST_DATABASE_URL="postgresql://flood_risk:change-me-local@127.0.0.1:${POSTGRES_PORT:-5432}/flood_risk" python -m pytest tests/test_community_repository_postgres.py -q -rs)
(cd apps/api && COMMUNITY_DB_ACCEPTANCE_REQUIRED=1 COMMUNITY_TEST_DATABASE_URL="postgresql://flood_risk:change-me-local@127.0.0.1:${POSTGRES_PORT:-5432}/flood_risk" python -m pytest tests/test_community_repository_postgres.py -q -rs)
```

Expected: both suites PASS against migration 0039 and report zero skipped tests.
The sentinel makes either test module fail during collection/setup if the URL is
missing or PostGIS is unavailable; completion must not accept a skip-only run.

- [ ] **Step 4: Run the complete worker suite from its package root**

Run: `(cd apps/workers && python -m pytest tests -q && python -m ruff check app tests)`

Expected: PASS.

- [ ] **Step 5: Run the complete API suite from its package root**

Run: `(cd apps/api && python -m pytest tests -q && python -m ruff check app tests && python -m mypy app)`

Expected: PASS.

- [ ] **Step 6: Run Web unit, type, lint, build, and E2E suites**

Run: `npm test --prefix apps/web && npm run typecheck --prefix apps/web && npm run lint --prefix apps/web && npm run build --prefix apps/web && npm run e2e --prefix apps/web`

Expected: PASS.

- [ ] **Step 7: Run the no-legacy-pipeline/no-generic-queue audit**

Run: `! rg -n "RawSourceItem|raw_snapshots|staging_evidence|worker_runtime_jobs" apps/workers/app/community apps/workers/app/adapters/threads apps/api/app/domain/community`

Expected: exit 0 and no output.

- [ ] **Step 8: Run the synthetic fixture integrations without cross-package imports**

Run: `(cd apps/workers && python -m pytest tests/test_community_fixture_integration.py -q)`

Run: `(cd apps/api && python -m pytest tests/test_community_assessment_integration.py -q)`

Expected: the worker command proves synthetic Threads page → sanitized signal → stable cluster with no raw persistence; the API command proves persisted sanitized records → one uplift → assessment association → preview/expanded evidence.

- [ ] **Step 9: Run a disabled/no-egress container smoke**

Run: `docker compose --profile tools run --rm migrate && docker compose run --rm -e SOURCE_THREADS_ENABLED=true -e SOURCE_THREADS_API_ENABLED=false worker sh -c "pip install -e . && python -m app.main --run-community --once --community-max-queries 5"`

Expected: `mode=normal`, `threads_egress_enabled=false`, zero Threads egress,
and no token/body output. The cycle may still recluster eligible first-party
reports; cadence mode and source egress are independent. This command
intentionally tests the disabled egress gate and is not described as fixture
ingestion.

- [ ] **Step 10: Document activation, kill, retention, deletion, and browser boundaries**

Add these exact operator facts:

```markdown
- Bootstrap and every key rotation run `COMMUNITY_DEDUPE_HMAC_KEY=<secret> python infra/scripts/rotate_community_dedupe_key.py --new-key-id <reviewed-id>` only after a separate operator transaction disables both source rows. The command takes the shared mutation lock and has no force flag: any active/permanent Threads suppression aborts before deletion with the old binding intact. Otherwise it drains old-key derived state plus expired suppressions, proves zero, writes only the ID/SHA-256 binding, and leaves both rows disabled. Deploy that same secret/ID, prove the binding, then enable one reviewed source at a time; never edit metadata or rotate an environment secret in place.
- `python -m app.main --run-community --once` runs one bounded cycle; omitting `--once` runs the 30/5-minute adaptive loop.
- Threads egress requires every environment gate, `data_sources.is_enabled=true`, and an exact catalog key-ID/SHA-256 binding; setting either source/API gate false, changing the ID/key, or setting the database row false is an immediate fail-closed kill switch. The cycle keeps its `normal|event|cooldown|locked` cadence state and may still recluster eligible first-party reports.
- `community.user_report` promotion also requires its database row enabled and the same exact key binding; pending reports remain private moderation records. Redaction/deletion uses the private persisted link and remains available without the key.
- Priority rows contain canonical place fields only, recover after a crashed claimed cycle, expire within 15 minutes, and are deleted after successful completion.
- Sanitized signals expire within the reviewed maximum of 30 days. Source deletion, complaint, false-report moderation, or privacy redaction suppresses and recomputes clusters in one transaction.
- Browser discovery is quarantined YAML source research. It has no production fetch, signal, event, evidence, assessment, or scoring writer.
```

- [ ] **Step 11: Commit verified operations documentation**

```bash
git add README.md apps/api/README.md apps/workers/README.md docs/PROJECT_SDD.md docs/PROJECT_WORK_PLAN.md docs/runbooks/runtime-smoke.md
git commit -m "docs: describe verified community signal operations"
```

---

## Completion Gate

This plan is complete only when all of the following are true:

- Migration tests prove exact metadata-only column allowlists, both fail-closed seeds, narrow persisted precision, no claim metadata, 15-minute work TTL, 30-day maximum retention, and assessment association.
- Threads uses only strict official HTTPS keyword endpoint, bearer auth, approved fields, injected bounded timeout/pages, source Retry-After, all environment gates, a secret fingerprint key, and the database kill switch.
- PTT/Dcard remain fixture-only/no-network and no browser fallback exists.
- Social text/tags are memory-only; identifiers, body/comments/HTML/media/contact/private address/raw refs and synthetic sensitive markers are absent from persistence/logs/responses/snapshots.
- Exact keyed HMAC plus keyed near-duplicate LSH, canonical/reference URLs, and resolved quote origin prevent duplicate-origin counting; unresolved quotes do not become new origins.
- Catalog key ID/SHA-256 binding is enforced before each Threads page, inside signal/report writes, and at activation. Bootstrap/rotation drains old-key state under the shared lock and leaves both sources disabled; active/permanent Threads suppression blocks rotation before deletion, so suppression continuity is never silently discarded and old/new origins never coexist.
- Approved user-report promotion and all report deletion/rejection/redaction paths are single transactions; duplicate reports share an origin and old reports do not violate retention.
- Stable anchor-based clusters link each signal at most once; suppression/rejection/expiry recomputes or deletes affected clusters before commit.
- Only active enabled unsuppressed metadata is read. Assessment persistence links sanitized signal IDs, and preview plus expanded evidence union always returns community `raw_ref=null`.
- There is exactly one community decision function. One origin causes none; with known realtime all clusters together cause at most one non-decreasing step; realtime/historical are unchanged; unconfirmed confidence is at most `中`.
- Official realtime `未知` plus corroborated community retains realtime `未知`, keeps the separate historical block and official gaps, uses `community_warning`, and produces overall exactly `中` even when historical context is higher.
- The API keeps `AssessmentService(repository, scorer)`, performs only a local priority upsert, imports no worker package, and returns when community storage/Threads/browser is unavailable.
- Search rows contain only canonical approved fields. Advisory-lock recovery, successful-key completion, partial-result persistence, rate-limit release, and the actual 30/5-minute loop are tested.
- Source policy and browser discovery use different exact schemas; unknown recursive keys fail; Threads/user-report gates and PTT/Dcard blocks are validated; browser findings remain quarantined.
- API/OpenAPI/TypeScript agree on community/overall/refresh/evidence fields; Web uses server overall and shows source, time, distance, precision, confidence, limits, and unverified/corroborated labels without polling.
- Root, worker, API, Web, OpenAPI, build, E2E, disabled smoke, and both synthetic fixture-integration commands pass independently.
