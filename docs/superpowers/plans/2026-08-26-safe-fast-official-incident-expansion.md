# Flood Risk v1 Safe-Fast Official Incident Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four independently disabled official incident sources—CWA heavy-rain CAP, corrected NCDR datastore/dump CAP, police-radio flood road incidents, and bounded WRA warning KML—while keeping unresolved geometry out of accepted staging and keeping recent context completely outside risk scoring.

**Architecture:** Workers fetch and audit each upstream source behind source/API/contract gates. CWA township rows and NCDR Circle or otherwise unresolved rows stop before accepted staging through a shared source-rejection audit contract; police and WRA events persist only as `status_only` context. The API reads recent context from PostgreSQL through a dedicated six-hour query and uses it only for evidence display, never for current/historical scorer inputs, coverage, or the low-risk safety gate.

**Tech Stack:** Python 3.12, defusedxml, FastAPI, Pydantic v2, PostgreSQL/PostGIS, psycopg 3, pytest, Ruff, mypy, YAML, SQL migrations, Next.js 16/React 19 acceptance checks.

## Global Constraints

- The approved design is `docs/superpowers/specs/2026-08-26-safe-fast-official-incident-expansion-design.md`; it overrides stale Task 11/12 transport and scoring assumptions in `docs/superpowers/plans/2026-08-24-v1-core-official-baseline.md`.
- Start every production change with a focused failing test and record the expected failure before implementation. Commit only after the focused regression set is green.
- Preserve the three user-owned untracked files under `docs/reviews/`; never stage, edit, delete, or rename them.
- Public `/v1/risk/assess` reads persisted PostgreSQL data only. No CWA, NCDR, police-radio, WRA, data.gov.tw, social, browser, or other upstream fetch may occur on the request path.
- Keep `score_risk(signals: tuple[RiskEvidenceSignal, ...], *, now: datetime) -> RiskScoringResult`, its weights, thresholds, score version, and existing golden fixtures unchanged.
- CWA township/admin rows without exact reviewed geometry and NCDR Circle/admin rows without exact reviewed geometry persist only a bounded raw snapshot, safe source-rejection code, and ingestion-run audit. They do not enter accepted staging, `evidence`, `official_realtime_latest`, nearby coverage, or scoring.
- Never replace a CWA township with its parent county polygon, never create a city/area centroid, and never score an NCDR Circle by its center point.
- NCDR index requests use lowercase `format=json`; dump requests use lowercase `format=xml`. Both use `apikey`; dump additionally uses `capid`. `/api/dump`, query key `key`, and the legacy Atom URL are forbidden from the production runtime builder.
- CWA/NCDR secrets exist only in memory or the deployment secret store. URLs, exceptions, logs, snapshots, reports, fixtures, and committed files may contain only `REDACTED` or a non-secret key identifier.
- Police-radio rows require an explicit flood/waterlogging keyword, a source event time, a valid Taiwan-bounded WGS84 point, and `evidence_scope="context"`. Rain-only text is not a flood incident.
- Police-radio and WRA incident rows use `EventType.STATUS_ONLY`; they never enter `official_realtime_latest`, rainfall/hydrology coverage, required-source satisfaction, low-risk safety eligibility, or either scorer call.
- Recent police/WRA context is visible only when its source time is between `as_of - 6 hours` and `as_of + 5 minutes`, its latest source state is not resolved/excluded, and its geometry intersects the selected radius.
- WRA fetches only the four exact HTTPS paths ending in `NewstFloodWarm.kml`, `NewstWaterWarm.kml`, `NewstReservoirWarm.kml`, and `AnnounceFlood.kml` under `fhy.wra.gov.tw/pub_web_2011/kml/KmlShare/`. Userinfo, query, fragment, non-default port, cross-host redirect, arbitrary path, and arbitrary/recursive NetworkLink are rejected.
- Every new source has independent source, API, and reviewed-contract gates; all settings defaults, `.env.example` values, checked-in source catalog entries, and database rows remain false/disabled.
- `WORKER_ENABLED_ADAPTER_KEYS` cannot bypass source, API, credential, reviewed-contract, or persisted catalog gates.
- Healthy valid empty is distinct from partial, failed, stale, and disabled. Missing/failed/empty data never means low risk.
- A 429 response is attempted only once in the current cycle. Parse an integer or HTTP-date `Retry-After`, cap the recorded cooldown to 3,600 seconds, redact request secrets, and surface the cooldown in the failed/partial run audit; never loop or sleep indefinitely inside an adapter.
- External request packets are static, public-safe, manual-only artifacts. No task may send mail, submit forms, use a signed-in browser session, or include secrets/private evidence URLs.
- Do not push, merge, deploy, enable a source, send an external request, or mutate hosted infrastructure in this plan.

---

## File and Responsibility Map

### Shared worker audit and CAP parsing

- Modify `apps/workers/app/adapters/contracts.py` — add bounded `SourceRejection` records while retaining the existing `rejected: tuple[str, ...]` compatibility field.
- Modify `apps/workers/app/pipelines/staging.py` — copy safe source-rejection details into raw-snapshot metadata without creating accepted or rejected staging evidence for a non-normalized raw row.
- Create `apps/workers/app/adapters/cap_xml.py` — parse bounded CAP 1.2 messages, areas, references, polygons, Circles, and geocodes without inventing geometry.
- Modify `apps/workers/app/jobs/ingestion.py` — retain source-specific partial audit semantics and treat reviewed warning-context feeds' valid empty results distinctly from failures.

### Source adapters and runtime wiring

- Create `apps/workers/app/jobs/source_catalog.py` — enforce the persisted
  `data_sources.is_enabled` gate before any new incident adapter is built or run.
- Create `apps/workers/app/adapters/cwa/heavy_rain_warning.py` and `apps/workers/tests/test_cwa_heavy_rain_warning_adapter.py`.
- Rewrite the runtime portion of `apps/workers/app/adapters/ncdr/cap_alerts.py` and its tests while retaining `parse_ncdr_cap_payload()` only for legacy parser regression coverage.
- Create `apps/workers/app/adapters/police_radio_traffic/__init__.py`, `road_incidents.py`, and `apps/workers/tests/test_police_radio_traffic_adapter.py`.
- Create `apps/workers/app/adapters/wra/flood_warning.py` and `apps/workers/tests/test_wra_flood_warning_adapter.py`.
- Modify `apps/workers/app/adapters/cwa/__init__.py`, `ncdr/__init__.py`, `wra/__init__.py`, `adapters/registry.py`, `jobs/runtime.py`, `config.py`, `.env.example`, and focused registry/catalog/runtime tests.
- Add fixture files under `apps/workers/tests/fixtures/` only; fixtures contain synthetic or public-safe data and no live credential.

### Persisted recent-context read path

- Modify `apps/workers/app/pipelines/staging.py` — pass through reviewed context properties and limitations.
- Modify `apps/api/app/domain/evidence/repository.py` — add a bounded PostGIS recent-context query with latest-state and time-window filtering.
- Modify `apps/api/app/domain/assessment/models.py` and `repository.py` — keep recent context separate from current and historical scoring collections.
- Modify `apps/api/app/api/services/assessment.py` — display/persist selected context evidence without converting it to `RiskEvidenceSignal`.
- Add focused API unit and mandatory PostGIS coverage without adding a new public response field.

### Catalog, migration, operator artifacts, and acceptance

- Modify `docs/data-sources/official/official-source-catalog.yaml` and `docs/data-sources/official/README.md`.
- Create `infra/migrations/0038_official_incident_context_sources.sql`; update `infra/migrations/README.md`. The later Core Task 14 baseline replacement must use migration 0039, so update its plan references in the same reviewed task before 0038 is committed.
- Create `apps/api/app/ops/official_incident_request_packets.py`, `scripts/official-incident-request-packets.py`, their unit/CLI tests, and `docs/data-sources/official/official-incident-request-packets.md`.
- Create `docs/runbooks/safe-fast-official-incident-activation.md` and a release-contract test that proves every new source remains disabled.

---

### Task 1: Add source-specific pre-staging rejection audit

**Files:**

- Modify: `apps/workers/app/adapters/contracts.py`
- Modify: `apps/workers/app/pipelines/staging.py`
- Modify: `apps/workers/tests/test_adapter_contracts.py`
- Modify: `apps/workers/tests/test_staging_pipeline.py`
- Modify: `apps/workers/tests/test_ingestion_job_runner.py`

**Interfaces:**

- Consumes: existing `AdapterRunResult.rejected: tuple[str, ...]`, `build_staging_batch(...)`, and `RawSnapshotUpsert.metadata`.
- Produces:

```python
@dataclass(frozen=True)
class SourceRejection:
    source_id: str
    reason_code: str


@dataclass(frozen=True)
class AdapterRunResult:
    adapter_key: str
    fetched: tuple[RawSourceItem, ...]
    normalized: tuple[NormalizedEvidence, ...]
    rejected: tuple[str, ...] = field(default_factory=tuple)
    source_rejections: tuple[SourceRejection, ...] = field(default_factory=tuple)
    station_inventory_proof: StationInventoryProof | None = None
    no_active_event: bool = False
```

`SourceRejection.source_id` is trimmed, 1–512 characters. `reason_code` matches
`[a-z][a-z0-9_]{0,63}`. Source rejection IDs are unique and must be a subset of
`AdapterRunResult.rejected`; legacy adapters may continue to provide no detailed
records. At most 256 detailed records are accepted per run. `build_raw_snapshot()`
stores them as sorted objects under `metadata["source_rejections"]` and stores
`source_rejection_count`. A concrete entry is
`{"source_id": "cap:unreviewed-town", "reason_code": "cwa_unreviewed_admin_geometry"}`.

- [ ] **Step 1: Write the failing contract and staging tests**

Add tests equivalent to:

```python
def test_source_rejection_is_audited_without_staging_evidence() -> None:
    raw = RawSourceItem(
        source_id="cap:unreviewed-town",
        source_url="https://example.test/cap",
        fetched_at=FETCHED_AT,
        payload={"admin_code": "67037000", "areaDesc": "安南區"},
    )
    result = AdapterRunResult(
        adapter_key="official.cwa.heavy_rain_warning",
        fetched=(raw,),
        normalized=(),
        rejected=(raw.source_id,),
        source_rejections=(
            SourceRejection(raw.source_id, "cwa_unreviewed_admin_geometry"),
        ),
    )

    batch = build_staging_batch(result)

    assert batch.accepted == ()
    assert batch.rejected == ()
    assert batch.rejected_raw_source_ids == (raw.source_id,)
    assert batch.raw_snapshot.metadata["source_rejections"] == [
        {
            "source_id": "cap:unreviewed-town",
            "reason_code": "cwa_unreviewed_admin_geometry",
        }
    ]
```

Also assert duplicate IDs, non-canonical reason codes, reason IDs absent from
`rejected`, and more than 256 records raise `ValueError`. Add a run-summary test
asserting one fetched/one rejected row is `partial`, not `no_active_event` or
`failed`.

- [ ] **Step 2: Run the focused tests and record RED**

Run:

```bash
cd apps/workers
../../.venv/workers/bin/python -m pytest \
  tests/test_adapter_contracts.py \
  tests/test_staging_pipeline.py \
  tests/test_ingestion_job_runner.py -q
```

Expected: FAIL because `SourceRejection` and `AdapterRunResult.source_rejections`
do not exist.

- [ ] **Step 3: Implement the bounded compatibility-safe contract**

Add `SourceRejection` and `AdapterRunResult.__post_init__()` validation. Extend
`build_raw_snapshot()` metadata exactly as defined above. Do not synthesize
`StagingEvidenceUpsert` rows for source rejections and do not change existing
adapter status calculations.

- [ ] **Step 4: Verify GREEN and static quality**

Run:

```bash
cd apps/workers
../../.venv/workers/bin/python -m pytest \
  tests/test_adapter_contracts.py \
  tests/test_staging_pipeline.py \
  tests/test_ingestion_job_runner.py -q
../../.venv/workers/bin/ruff check \
  app/adapters/contracts.py app/pipelines/staging.py \
  tests/test_adapter_contracts.py tests/test_staging_pipeline.py \
  tests/test_ingestion_job_runner.py
```

Expected: all selected tests pass and Ruff exits 0.

- [ ] **Step 5: Commit the audit contract**

```bash
git add apps/workers/app/adapters/contracts.py \
  apps/workers/app/pipelines/staging.py \
  apps/workers/tests/test_adapter_contracts.py \
  apps/workers/tests/test_staging_pipeline.py \
  apps/workers/tests/test_ingestion_job_runner.py
git commit -m "feat: audit source-specific ingestion rejections"
```

### Task 2: Enforce the persisted source catalog before upstream work

**Files:**

- Create: `apps/workers/app/jobs/source_catalog.py`
- Create: `apps/workers/tests/test_source_catalog_gate.py`
- Modify: `apps/workers/app/jobs/runtime_managed.py`
- Modify: `apps/workers/app/jobs/runtime.py`
- Modify: `apps/workers/tests/test_runtime_managed_ingestion.py`
- Modify: `apps/workers/tests/test_runtime_queue.py`

**Interfaces:**

- Consumes: `data_sources(adapter_key, is_enabled)`, the selected worker adapter
  keys, and the existing optional PostgreSQL connection-factory pattern.
- Produces:

```python
OFFICIAL_INCIDENT_CATALOG_GATED_KEYS: Final[frozenset[str]] = frozenset(
    {
        "official.cwa.heavy_rain_warning",
        "official.ncdr.cap",
        "official.npa.police_radio_traffic",
        "official.wra.flood_warning",
    }
)


class SourceCatalogReader(Protocol):
    def enabled_keys(self, adapter_keys: tuple[str, ...]) -> frozenset[str]: ...


class PostgresSourceCatalogReader:
    def __init__(
        self,
        *,
        database_url: str | None = None,
        connection_factory: ConnectionFactory | None = None,
    ) -> None: ...

    def enabled_keys(self, adapter_keys: tuple[str, ...]) -> frozenset[str]: ...
```

`PostgresSourceCatalogReader.enabled_keys()` performs one parameterized query:

```sql
SELECT adapter_key
FROM data_sources
WHERE adapter_key = ANY(%s) AND is_enabled IS TRUE
ORDER BY adapter_key ASC
```

Only the four new source keys are subject to this compatibility-scoped gate in
this task. Missing rows and `is_enabled=false` are both disabled. A real runtime
resolves the reader from the same `database_url` used for persistence; injected
unit-test queue/writer paths that select one of these four keys must inject an
explicit reader. No permissive default is allowed for a gated key.

- [ ] **Step 1: Write failing reader and orchestration tests**

Add tests proving:

```python
def test_disabled_catalog_key_never_builds_or_runs_managed_adapter() -> None:
    calls = {"build": 0, "run": 0}
    result = _execute_managed_runtime_ingestion_cycle(
        settings=_incident_settings("official.cwa.heavy_rain_warning"),
        staging_writer=_MemoryStagingWriter(),
        run_writer=_MemoryRunWriter(),
        source_catalog_reader=_StaticCatalogReader(enabled=frozenset()),
        adapter_builder=_counting_builder(calls),
    )

    assert result.status == "skipped"
    assert result.reason == "source_catalog_disabled"
    assert calls == {"build": 0, "run": 0}
```

Also cover an absent row, an enabled row, a catalog-query exception, a mixed
queue-producer selection, and a pre-existing queue job dequeued after rollback.
The producer must enqueue no disabled key and must not call
`build_runtime_adapters`. The worker must acknowledge a disabled pre-existing
job as a terminal no-op, return `status="skipped"` with
`reason="source_catalog_disabled"`, and call neither adapter construction nor
`run()`. Catalog unavailability is fail-closed: managed runtime reports failed,
the producer creates no job, and a dequeued job follows the existing bounded
failure/retry path; none reaches upstream code.

For the PostgreSQL reader, assert missing/false rows are excluded, duplicate
input keys are normalized deterministically, the SQL is parameterized, and a
zero-key call avoids opening a connection.

- [ ] **Step 2: Run the focused tests and record RED**

Run:

```bash
cd apps/workers
../../.venv/workers/bin/python -m pytest \
  tests/test_source_catalog_gate.py \
  tests/test_runtime_managed_ingestion.py \
  tests/test_runtime_queue.py -q
```

Expected: FAIL because the reader and orchestration gate do not exist.

- [ ] **Step 3: Implement the fail-closed pre-fetch gate**

Implement the bounded reader and a shared selection helper. Add an optional
`source_catalog_reader` injection seam to
`_execute_managed_runtime_ingestion_cycle()`,
`produce_enabled_runtime_adapter_jobs()`, and `work_runtime_queue_once()`.
Resolve the PostgreSQL reader automatically when a real `database_url` is
present. Apply the gate before `adapter_builder`, `build_runtime_adapters()`,
`run_adapter_batch()`, queue enqueue, staging, or promotion.

For a catalog-disabled queued job, use the existing queue completion primitive
to consume the already-leased job, emit a safe structured
`runtime.source_catalog.disabled` event containing only the adapter key, and
return a skipped result. Do not classify the disabled source as a successful
ingestion run. Preserve existing behavior for adapter keys outside
`OFFICIAL_INCIDENT_CATALOG_GATED_KEYS`.

- [ ] **Step 4: Verify GREEN and static quality**

Run:

```bash
cd apps/workers
../../.venv/workers/bin/python -m pytest \
  tests/test_source_catalog_gate.py \
  tests/test_runtime_managed_ingestion.py \
  tests/test_runtime_queue.py \
  tests/test_worker_entrypoints.py -q
../../.venv/workers/bin/ruff check \
  app/jobs/source_catalog.py app/jobs/runtime_managed.py app/jobs/runtime.py \
  tests/test_source_catalog_gate.py tests/test_runtime_managed_ingestion.py \
  tests/test_runtime_queue.py
```

Expected: all selected tests pass and Ruff exits 0.

- [ ] **Step 5: Commit the catalog gate**

```bash
git add apps/workers/app/jobs/source_catalog.py \
  apps/workers/app/jobs/runtime_managed.py \
  apps/workers/app/jobs/runtime.py \
  apps/workers/tests/test_source_catalog_gate.py \
  apps/workers/tests/test_runtime_managed_ingestion.py \
  apps/workers/tests/test_runtime_queue.py
git commit -m "feat: enforce official incident catalog gate"
```

### Task 3: Implement CWA CAP transport, parser, and audit-only geometry gate

**Files:**

- Create: `apps/workers/app/adapters/cap_xml.py`
- Create: `apps/workers/app/adapters/cwa/heavy_rain_warning.py`
- Create: `apps/workers/tests/fixtures/cwa_heavy_rain_warning_cap.xml`
- Create: `apps/workers/tests/fixtures/cwa_heavy_rain_warning_empty.xml`
- Create: `apps/workers/tests/test_cwa_heavy_rain_warning_adapter.py`
- Modify: `apps/workers/app/adapters/cwa/__init__.py`
- Modify: `apps/workers/app/adapters/registry.py`
- Modify: `apps/workers/app/jobs/runtime.py`
- Modify: `apps/workers/app/config.py`
- Modify: `.env.example`
- Modify: `docs/data-sources/official/official-source-catalog.yaml`
- Modify: `apps/workers/tests/test_adapter_registry_config.py`
- Modify: `apps/workers/tests/test_official_source_catalog.py`

**Interfaces:**

- Consumes: Task 1 `SourceRejection`, `cap_source_id(...)`, existing Core Task
  8/9 lifecycle field names, and the existing source/API/contract gate pattern.
- Produces:

```python
CWA_HEAVY_RAIN_CAP_URL = (
    "https://opendata.cwa.gov.tw/fileapi/v1/opendataapi/"
    "W-C0033-003?format=CAP"
)
CwaFetchCap = Callable[[str, str, int], str]


@dataclass(frozen=True)
class ParsedCapReference:
    sender: str
    identifier: str
    sent: datetime


@dataclass(frozen=True)
class ParsedCapArea:
    area_desc: str
    geocodes: tuple[tuple[str, str], ...]
    polygon: tuple[tuple[float, float], ...] | None
    circle: tuple[float, float, float] | None


@dataclass(frozen=True)
class ParsedCapMessage:
    sender: str
    identifier: str
    sent: datetime
    status: str
    message_type: str
    scope: str
    event: str
    headline: str | None
    description: str | None
    effective: datetime | None
    onset: datetime | None
    expires: datetime | None
    references: tuple[ParsedCapReference, ...]
    areas: tuple[ParsedCapArea, ...]


ParseCapDocument = Callable[[str], tuple[ParsedCapMessage, ...]]
```

For an unresolved area that cannot call `cap_source_id()` with a canonical
reviewed admin code, use this exact deterministic identity contract:

```python
def unresolved_cap_area_source_id(message: ParsedCapMessage, area: ParsedCapArea) -> str:
    message_id = cap_message_digest(
        sender=message.sender,
        identifier=message.identifier,
        sent=message.sent,
    )
    area_json = json.dumps(
        [
            area.area_desc,
            sorted(area.geocodes),
            area.polygon,
            area.circle,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    area_id = hashlib.sha256(area_json.encode("utf-8")).hexdigest()[:24]
    return f"cap:{message_id}:unresolved-area:{area_id}"
```

Area-less messages use the existing `cap_source_id(..., message_level=True)`.
Neither identity contains an API credential or a datastore `capid`.

`parse_cap_document()` uses `defusedxml`, caps input at 2 MiB, XML depth at 32,
elements at 20,000, messages at 256, areas per message at 128, references at 64,
and polygon coordinates at 4,096. CAP coordinate text is preserved as source
semantics; the shared parser never computes a centroid.

`CwaHeavyRainWarningAdapter` accepts `authorization`, `cap_url`,
`timeout_seconds`, `fetched_at`, injected `fetch_cap`, and `raw_snapshot_key`.
The runtime builder supplies no reviewed township geometry in this task, so
every active area becomes a fetched raw item plus
`cwa_unreviewed_admin_geometry`; it is not normalized. An area-less lifecycle
message uses `cwa_unreviewed_message_geometry`. A valid empty CAP collection
returns `no_active_event=True`; transport/schema/auth failure raises an adapter
error and is never converted to empty.

- [ ] **Step 1: Write RED parser, lifecycle, redaction, and geometry-fence tests**

Tests must cover:

```python
def test_cwa_town_warning_is_raw_audited_but_not_staged() -> None:
    result = _adapter_for_fixture("cwa_heavy_rain_warning_cap.xml").run()
    assert len(result.fetched) == 2
    assert result.normalized == ()
    assert {item.reason_code for item in result.source_rejections} == {
        "cwa_unreviewed_admin_geometry"
    }

    batch = build_staging_batch(result, ingestion_generation_started_at=FETCHED_AT)
    assert batch.accepted == ()
    assert batch.rejected == ()
    assert "geometry" not in result.fetched[0].payload
    assert "parent_county_geometry" not in result.fetched[0].payload
```

Also pin `Actual`/`Public`, Alert/Update/Cancel, structured reference triples,
effective-or-onset/expires, multi-area identity, future/expired rejection,
malformed XML, oversize/deep/entity XML, valid empty, separate authorization
argument, bounded 429 `Retry-After`, and `[REDACTED]` errors. Assert the URL
saved in raw/evidence metadata contains no authorization value.

- [ ] **Step 2: Run focused tests and record RED**

Run:

```bash
cd apps/workers
../../.venv/workers/bin/python -m pytest \
  tests/test_cwa_heavy_rain_warning_adapter.py \
  tests/test_adapter_registry_config.py \
  tests/test_official_source_catalog.py -q
```

Expected: FAIL with missing `app.adapters.cwa.heavy_rain_warning` and missing
settings/registry/catalog entries.

- [ ] **Step 3: Implement bounded CAP parsing and CWA transport**

Use a request builder that receives the secret as its own argument, removes any
existing `Authorization` query item, inserts the in-memory value only for the
actual request, and renders all errors with `Authorization=REDACTED`. Emit raw
payload fields named exactly:

```python
{
    "evidence_scope": "current",
    "location_precision": "admin_area",
    "cap_sender": message.sender,
    "cap_identifier": message.identifier,
    "cap_sent": message.sent.isoformat(),
    "cap_references": [
        {"sender": ref.sender, "identifier": ref.identifier, "sent": ref.sent.isoformat()}
        for ref in message.references
    ],
    "cap_status": message.status,
    "cap_message_type": message.message_type,
    "active_from": (message.onset or message.effective).isoformat(),
    "active_until": message.expires.isoformat(),
    "areaDesc": area.area_desc,
    "source_geocodes": [
        {"valueName": name, "value": value} for name, value in area.geocodes
    ],
}
```

Do not add `geometry`, `latest_point_geometry`, a parent county code, or a
centroid. Use Task 1 rejection audit for every unresolved row.

- [ ] **Step 4: Add independent disabled gates and checked-in catalog metadata**

Add these exact environment settings, all false/empty by default:

```text
SOURCE_CWA_HEAVY_RAIN_WARNING_ENABLED=false
SOURCE_CWA_HEAVY_RAIN_WARNING_API_ENABLED=false
SOURCE_CWA_HEAVY_RAIN_WARNING_CONTRACT_ENABLED=false
CWA_HEAVY_RAIN_WARNING_CAP_URL=
CWA_HEAVY_RAIN_WARNING_TIMEOUT_SECONDS=8
```

Reuse only `CWA_API_AUTHORIZATION` as the credential. Register adapter key
`official.cwa.heavy_rain_warning`; catalog license is
`中央氣象署開放資料平臺使用規範` with `https://opendata.cwa.gov.tw/about/rules`.
The runtime builder requires source + API + contract + non-empty credential;
an explicit worker allowlist cannot bypass any gate.

- [ ] **Step 5: Verify GREEN and regressions**

Run:

```bash
cd apps/workers
../../.venv/workers/bin/python -m pytest \
  tests/test_cwa_heavy_rain_warning_adapter.py \
  tests/test_adapter_registry_config.py \
  tests/test_official_source_catalog.py \
  tests/test_staging_pipeline.py \
  tests/test_ingestion_job_runner.py \
  tests/test_promotion_pipeline.py -q
../../.venv/workers/bin/ruff check \
  app/adapters/cap_xml.py app/adapters/cwa app/adapters/registry.py \
  app/jobs/runtime.py app/config.py \
  tests/test_cwa_heavy_rain_warning_adapter.py \
  tests/test_adapter_registry_config.py tests/test_official_source_catalog.py
```

Expected: all selected tests pass; no CWA unresolved row becomes an accepted
staging or promotion candidate; Ruff exits 0.

- [ ] **Step 6: Commit CWA CAP audit support**

```bash
git add .env.example \
  apps/workers/app/adapters/cap_xml.py \
  apps/workers/app/adapters/cwa/heavy_rain_warning.py \
  apps/workers/app/adapters/cwa/__init__.py \
  apps/workers/app/adapters/registry.py \
  apps/workers/app/jobs/runtime.py apps/workers/app/config.py \
  apps/workers/tests/fixtures/cwa_heavy_rain_warning_cap.xml \
  apps/workers/tests/fixtures/cwa_heavy_rain_warning_empty.xml \
  apps/workers/tests/test_cwa_heavy_rain_warning_adapter.py \
  apps/workers/tests/test_adapter_registry_config.py \
  apps/workers/tests/test_official_source_catalog.py \
  docs/data-sources/official/official-source-catalog.yaml
git commit -m "feat: audit CWA heavy rain CAP warnings"
```

### Task 4: Replace NCDR Atom runtime with datastore to dump CAP

**Files:**

- Modify: `apps/workers/app/adapters/ncdr/cap_alerts.py`
- Modify: `apps/workers/app/adapters/ncdr/__init__.py`
- Create: `apps/workers/tests/fixtures/ncdr_datastore_active.json`
- Create: `apps/workers/tests/fixtures/ncdr_datastore_empty.json`
- Create: `apps/workers/tests/fixtures/ncdr_dump_flood_cap.xml`
- Create: `apps/workers/tests/fixtures/ncdr_dump_circle_cap.xml`
- Modify: `apps/workers/tests/test_ncdr_cap_adapter.py`
- Modify: `apps/workers/app/adapters/registry.py`
- Modify: `apps/workers/app/jobs/runtime.py`
- Modify: `apps/workers/app/config.py`
- Modify: `.env.example`
- Modify: `docs/data-sources/official/official-source-catalog.yaml`
- Modify: `apps/workers/tests/test_adapter_registry_config.py`
- Modify: `apps/workers/tests/test_official_source_catalog.py`
- Modify: `apps/workers/tests/test_staging_pipeline.py`
- Modify: `apps/workers/tests/test_ingestion_job_runner.py`

**Interfaces:**

- Consumes: Task 1 `SourceRejection`, Task 3 `parse_cap_document`, and existing
  CAP identity/lifecycle functions. The old `parse_ncdr_cap_payload()` remains
  callable only by explicit parser-regression tests.
- Produces:

```python
NCDR_DATASTORE_API_URL = "https://alerts.ncdr.nat.gov.tw/api/datastore"
NCDR_DUMP_API_URL = "https://alerts.ncdr.nat.gov.tw/api/dump/datastore"
DEFAULT_NCDR_MAX_CAP_IDS_PER_RUN = 50

NcdrFetchJson = Callable[[str, Mapping[str, str], int], object]
NcdrFetchText = Callable[[str, Mapping[str, str], int], str]
```

`NcdrCapAlertAdapter` requires `api_key`, `datastore_url`, `dump_url`,
`max_cap_ids_per_run`, `timeout_seconds`, `fetch_json`, and `fetch_text`.
Datastore IDs are trimmed, bounded to 256 characters, deduplicated, sorted, and
then sliced to `max_cap_ids_per_run` in the inclusive range 1–200. The adapter
never uses a datastore `capid` as `NormalizedEvidence.source_id`.

- [ ] **Step 1: Rewrite tests RED around the exact two-stage request contract**

The injected fetchers must observe these exact parameter dictionaries:

```python
assert index_calls == [
    (
        "https://alerts.ncdr.nat.gov.tw/api/datastore",
        {"apikey": "test-secret", "format": "json", "limit": "50"},
        8,
    )
]
assert dump_calls == [
    (
        "https://alerts.ncdr.nat.gov.tw/api/dump/datastore",
        {"apikey": "test-secret", "capid": "CAP-001", "format": "xml"},
        8,
    )
]
```

Add cases for deterministic bounded duplicate IDs, empty datastore, malformed
index JSON, one failed dump plus one successful dump, all dump failures,
malformed CAP XML, secret-redacted errors, bounded 429 `Retry-After`, and default
runtime construction. Assert neither `/api/dump` nor query parameter `key` nor
`RssAtomFeed.ashx` appears in production runtime configuration. A 429 index or
dump response is not retried in the same cycle.

For an individual failed dump in a mixed run, the raw transport ID is
`ncdr-transport:` plus the first 24 hex characters of SHA-256 over the public
`capid`; the error text never includes query parameters. If every selected dump
fails, raise `NcdrCapAlertFetchError("all selected NCDR CAP dumps failed")` so
the run is `failed`, not `partial` or healthy empty.

- [ ] **Step 2: Add RED Circle and unresolved-admin audit tests**

Use the CAP fixture to prove original Circle semantics survive raw ingestion:

```python
def test_ncdr_circle_is_raw_audited_without_center_point() -> None:
    result = _circle_adapter().run()
    assert result.normalized == ()
    assert result.source_rejections[0].reason_code == "ncdr_circle_geometry_unreviewed"
    payload = result.fetched[0].payload
    assert payload["circle"] == {
        "latitude": 22.9997,
        "longitude": 120.2270,
        "radius_km": 1.5,
    }
    assert "geometry" not in payload
    assert "latest_point_geometry" not in payload
    assert build_staging_batch(result).accepted == ()
```

Geocode-only areas use `ncdr_unreviewed_admin_geometry`. A failed individual
dump uses a digest-based, secret-free transport source ID plus
`ncdr_dump_fetch_failed`; a mixed run is `partial`, and a valid empty index is
`succeeded/no_active_event`.

- [ ] **Step 3: Run the focused suite and record RED**

Run:

```bash
cd apps/workers
../../.venv/workers/bin/python -m pytest \
  tests/test_ncdr_cap_adapter.py \
  tests/test_staging_pipeline.py \
  tests/test_ingestion_job_runner.py \
  tests/test_adapter_registry_config.py \
  tests/test_official_source_catalog.py -q
```

Expected: FAIL because the adapter still calls the legacy Atom path, converts
Circle/polygon/area metadata into points, and lacks the datastore/dump settings.

- [ ] **Step 4: Implement datastore/dump transport and fail-closed normalization**

Use these payload rules:

```python
index_params = {
    "apikey": api_key,
    "format": "json",
    "limit": str(max_cap_ids_per_run),
}
dump_params = {
    "apikey": api_key,
    "capid": cap_id,
    "format": "xml",
}
```

Call `parse_cap_document()` for every successful dump. Preserve sender,
identifier, sent, references, status, message type, active window, all areas,
all source geocodes, original polygon coordinates, and original Circle
center/radius. Do not call `_resolve_geometry()`, `_circle_center()`,
`_fallback_centroid()`, or `_polygon_centroid()` from runtime code. Use the
canonical CAP triple to derive all message identities; keep `capid` only as
bounded `transport_capid` raw metadata.

The legacy Atom fixture test must call `parse_ncdr_cap_payload()` directly. It
must no longer instantiate the runtime adapter or assert a centroid.

- [ ] **Step 5: Replace configuration and add independent gates**

Add exact defaults:

```text
SOURCE_NCDR_CAP_ENABLED=false
SOURCE_NCDR_CAP_API_ENABLED=false
SOURCE_NCDR_CAP_CONTRACT_ENABLED=false
NCDR_ALERTS_API_KEY=
NCDR_DATASTORE_API_URL=
NCDR_DUMP_API_URL=
NCDR_MAX_CAP_IDS_PER_RUN=50
NCDR_CAP_TIMEOUT_SECONDS=8
```

Remove `NCDR_CAP_API_URL` from `.env.example` and the default runtime builder.
Registry selection requires source + contract gates. Runtime construction also
requires the API gate and a non-empty key. Catalog metadata names the two-stage
contract and keeps the source disabled.

- [ ] **Step 6: Verify GREEN, lifecycle regressions, and static quality**

Run:

```bash
cd apps/workers
../../.venv/workers/bin/python -m pytest \
  tests/test_ncdr_cap_adapter.py \
  tests/test_staging_pipeline.py \
  tests/test_ingestion_job_runner.py \
  tests/test_adapter_registry_config.py \
  tests/test_official_source_catalog.py \
  tests/test_promotion_pipeline.py \
  tests/test_runtime_managed_ingestion.py -q
../../.venv/workers/bin/ruff check \
  app/adapters/ncdr app/adapters/cap_xml.py app/adapters/registry.py \
  app/jobs/runtime.py app/config.py \
  tests/test_ncdr_cap_adapter.py tests/test_staging_pipeline.py \
  tests/test_ingestion_job_runner.py
```

Expected: selected tests pass; valid empty and partial dump audits are distinct;
no unresolved NCDR row enters accepted staging; Ruff exits 0.

- [ ] **Step 7: Commit the NCDR correction**

```bash
git add .env.example \
  apps/workers/app/adapters/ncdr/cap_alerts.py \
  apps/workers/app/adapters/ncdr/__init__.py \
  apps/workers/app/adapters/registry.py \
  apps/workers/app/jobs/runtime.py apps/workers/app/config.py \
  apps/workers/tests/fixtures/ncdr_datastore_active.json \
  apps/workers/tests/fixtures/ncdr_datastore_empty.json \
  apps/workers/tests/fixtures/ncdr_dump_flood_cap.xml \
  apps/workers/tests/fixtures/ncdr_dump_circle_cap.xml \
  apps/workers/tests/test_ncdr_cap_adapter.py \
  apps/workers/tests/test_staging_pipeline.py \
  apps/workers/tests/test_ingestion_job_runner.py \
  apps/workers/tests/test_adapter_registry_config.py \
  apps/workers/tests/test_official_source_catalog.py \
  docs/data-sources/official/official-source-catalog.yaml
git commit -m "fix: use NCDR datastore and dump CAP"
```

### Task 5: Add police-radio flood road incidents as non-scoring context

**Files:**

- Create: `apps/workers/app/adapters/police_radio_traffic/__init__.py`
- Create: `apps/workers/app/adapters/police_radio_traffic/road_incidents.py`
- Create: `apps/workers/tests/fixtures/police_radio_traffic_flood.json`
- Create: `apps/workers/tests/test_police_radio_traffic_adapter.py`
- Modify: `apps/workers/app/adapters/registry.py`
- Modify: `apps/workers/app/jobs/runtime.py`
- Modify: `apps/workers/app/config.py`
- Modify: `apps/workers/app/pipelines/staging.py`
- Modify: `.env.example`
- Modify: `docs/data-sources/official/official-source-catalog.yaml`
- Modify: `apps/workers/tests/test_adapter_registry_config.py`
- Modify: `apps/workers/tests/test_official_source_catalog.py`
- Modify: `apps/workers/tests/test_promotion_pipeline.py`

**Interfaces:**

- Consumes: `EventType.STATUS_ONLY`, Task 1 source rejection audit, existing
  raw/staging/promotion contracts, and injected JSON fetchers.
- Produces:

```python
POLICE_RADIO_TRAFFIC_URL = (
    "https://rtr.pbs.gov.tw/NMP103_PbsWS/resources/roadData/opendata"
)
PoliceRadioFetchJson = Callable[[str, int], object]


class PoliceRadioTrafficAdapter:
    metadata: AdapterMetadata
```

Constructor arguments are `endpoint_url`, `timeout_seconds`, `fetched_at`,
optional fixture `payload`, injected `fetch_json`, and `raw_snapshot_key`.
The parser accepts only explicit keywords `淹水`, `積水`, `水淹`, or `道路淹水`.
It rejects text that contains only `大雨`, `豪雨`, or `下雨`.

- [ ] **Step 1: Write RED parsing, time, coordinate, and keyword tests**

Pin these normalized properties:

```python
assert raw.source_id == "UID-001"
assert raw.payload["evidence_scope"] == "context"
assert raw.payload["location_precision"] == "road_or_lane"
assert raw.payload["context_kind"] == "reported_flood_road_incident"
assert raw.payload["verification_status"] == "reported_unverified"
assert raw.payload["incident_state"] == "active"
assert evidence.event_type is EventType.STATUS_ONLY
assert evidence.source_timestamp == datetime(2026, 8, 26, 2, 15, tzinfo=UTC)
```

Parse `happendate + happentime` in Asia/Taipei and convert to UTC. Preserve
`modDttm` separately as `upstream_updated_at`. Reject missing/invalid source
time, more than five minutes in the future, more than six hours old, missing or
invalid coordinates, and coordinates outside longitude 117.0–123.5 / latitude
20.0–27.5. Never substitute `fetched_at` and never call a geocoder.

Recognize source updates containing `解除`, `排除`, `恢復通行`, or `已排除` as
`incident_state="resolved"`; retain them as context audit rows so the API can
exclude an older active version of the same UID. A 429 response is not retried
inside the cycle and carries only its bounded, secret-free cooldown audit.

- [ ] **Step 2: Run the adapter tests and record RED**

Run:

```bash
cd apps/workers
../../.venv/workers/bin/python -m pytest \
  tests/test_police_radio_traffic_adapter.py -q
```

Expected: FAIL with missing `app.adapters.police_radio_traffic`.

- [ ] **Step 3: Implement the minimal adapter and staging passthrough**

Every accepted raw payload includes the point geometry, event/update times,
UID, state, context kind, verification status, and these exact limitations:

```python
POLICE_RADIO_LIMITATIONS = (
    "警廣即時路況通報，尚未由淹水感測器確認。",
    "路況通報可能由民眾或勤務單位提供，位置與狀態可能延遲更新。",
)
```

Add `context_kind`, `verification_status`, `incident_state`, and
`upstream_updated_at` to the staging passthrough allowlist. Do not add the
source/event pair to `_should_upsert_official_realtime_latest()`.

- [ ] **Step 4: Add independent disabled gates and catalog metadata**

Add exact defaults:

```text
SOURCE_NPA_POLICE_RADIO_ENABLED=false
SOURCE_NPA_POLICE_RADIO_API_ENABLED=false
SOURCE_NPA_POLICE_RADIO_CONTRACT_ENABLED=false
NPA_POLICE_RADIO_TRAFFIC_URL=
NPA_POLICE_RADIO_TIMEOUT_SECONDS=8
```

Register key `official.npa.police_radio_traffic`. The builder requires all
three gates. Keep the checked-in catalog disabled and attribute the official
dataset landing page `https://data.gov.tw/dataset/15221`.

- [ ] **Step 5: Verify GREEN and the latest/scoring fence**

Run:

```bash
cd apps/workers
../../.venv/workers/bin/python -m pytest \
  tests/test_police_radio_traffic_adapter.py \
  tests/test_adapter_registry_config.py \
  tests/test_official_source_catalog.py \
  tests/test_staging_pipeline.py \
  tests/test_promotion_pipeline.py -q
../../.venv/workers/bin/ruff check \
  app/adapters/police_radio_traffic app/adapters/registry.py \
  app/jobs/runtime.py app/config.py app/pipelines/staging.py \
  tests/test_police_radio_traffic_adapter.py
```

Expected: selected tests pass; context persists to evidence audit only and no
SQL insert targets `official_realtime_latest`; Ruff exits 0.

- [ ] **Step 6: Commit police-radio context support**

```bash
git add .env.example \
  apps/workers/app/adapters/police_radio_traffic \
  apps/workers/app/adapters/registry.py \
  apps/workers/app/jobs/runtime.py apps/workers/app/config.py \
  apps/workers/app/pipelines/staging.py \
  apps/workers/tests/fixtures/police_radio_traffic_flood.json \
  apps/workers/tests/test_police_radio_traffic_adapter.py \
  apps/workers/tests/test_adapter_registry_config.py \
  apps/workers/tests/test_official_source_catalog.py \
  apps/workers/tests/test_promotion_pipeline.py \
  docs/data-sources/official/official-source-catalog.yaml
git commit -m "feat: ingest police-radio flood incident context"
```

### Task 6: Add bounded WRA warning KML as non-scoring context

**Files:**

- Create: `apps/workers/app/adapters/wra/flood_warning.py`
- Create: `apps/workers/tests/fixtures/wra_flood_warning_index.json`
- Create: `apps/workers/tests/fixtures/wra_flood_warning_empty.kml`
- Create: `apps/workers/tests/fixtures/wra_flood_warning_synthetic_active.kml`
- Create: `apps/workers/tests/fixtures/wra_flood_warning_wrapper.kml`
- Create: `apps/workers/tests/test_wra_flood_warning_adapter.py`
- Modify: `apps/workers/app/adapters/wra/__init__.py`
- Modify: `apps/workers/app/adapters/registry.py`
- Modify: `apps/workers/app/jobs/runtime.py`
- Modify: `apps/workers/app/jobs/ingestion.py`
- Modify: `apps/workers/app/config.py`
- Modify: `apps/workers/app/pipelines/staging.py`
- Modify: `.env.example`
- Modify: `docs/data-sources/official/official-source-catalog.yaml`
- Modify: `apps/workers/tests/test_adapter_registry_config.py`
- Modify: `apps/workers/tests/test_official_source_catalog.py`
- Modify: `apps/workers/tests/test_promotion_pipeline.py`

**Interfaces:**

- Consumes: the defensive `defusedxml`/bounded-read style in
  `apps/workers/app/adapters/wra/historical_flood.py`, without reusing or
  widening that module's URL policy.
- Produces:

```python
WRA_FLOOD_WARNING_KML_URLS = (
    "https://fhy.wra.gov.tw/pub_web_2011/kml/KmlShare/NewstFloodWarm.kml",
    "https://fhy.wra.gov.tw/pub_web_2011/kml/KmlShare/NewstWaterWarm.kml",
    "https://fhy.wra.gov.tw/pub_web_2011/kml/KmlShare/NewstReservoirWarm.kml",
    "https://fhy.wra.gov.tw/pub_web_2011/kml/KmlShare/AnnounceFlood.kml",
)
WRA_FLOOD_WARNING_INDEX_URL = (
    "https://opendata.wra.gov.tw/api/v2/"
    "301c0b62-8736-4e03-95ef-55309c1a5e74"
)
WraFloodWarningFetchJson = Callable[[str, int], object]
WraFloodWarningFetchText = Callable[[str, int], str]
```

`approved_wra_flood_warning_url(value, *, allow_http_upgrade)` returns one of
the exact HTTPS constants or raises `WraFloodWarningPayloadError`. HTTP upgrade
is permitted only when scheme, host, path, empty query/fragment/userinfo, and
default port exactly match one of the constants. Redirect handling validates
the target before following it.

- [ ] **Step 1: Write RED URL-policy and parser-bound tests**

Test the exact index URL, selection of only the four allowlisted KML resources,
all four exact files, exact HTTP-to-HTTPS upgrade, bounded 429 cooldown without
an in-cycle retry, and rejection of:

```text
cross-host redirect
same host with an unlisted path
userinfo
query or fragment
non-default port
relative path traversal
unlisted or nested NetworkLink
DTD/entity XML
response larger than 2 MiB
depth over 32
more than 20,000 elements
more than 2,000 Placemarks
more than 100,000 total coordinates
```

The wrapper fixture may contain one level of exact allowlisted NetworkLinks;
the adapter never recursively follows a fetched child NetworkLink.

- [ ] **Step 2: Write RED context/empty/audit tests**

A valid empty set of four KML documents returns `no_active_event=True`.
Transport, schema, URL, or bound failures do not. A synthetic active Placemark
with an explicit source time and exact geometry produces:

```python
assert evidence.event_type is EventType.STATUS_ONLY
assert raw.payload["evidence_scope"] == "context"
assert raw.payload["context_kind"] == "official_wra_warning_context"
assert raw.payload["verification_status"] == "official_reported"
assert raw.payload["incident_state"] == "active"
assert raw.payload["location_precision"] in {"point", "polygon"}
```

A Placemark without a parseable source event time is source-rejected and never
uses fetch time. Context evidence must not enter `official_realtime_latest`.

- [ ] **Step 3: Run focused tests and record RED**

Run:

```bash
cd apps/workers
../../.venv/workers/bin/python -m pytest \
  tests/test_wra_flood_warning_adapter.py \
  tests/test_ingestion_job_runner.py \
  tests/test_promotion_pipeline.py -q
```

Expected: FAIL with missing `app.adapters.wra.flood_warning` and no WRA valid
empty capability.

- [ ] **Step 4: Implement isolated bounded KML transport and normalization**

Fetch only the exact metadata index, then intersect its resolved resources with
the four immutable HTTPS constants. Use source-specific constants for response
bytes, depth, elements, Placemark, and coordinate counts. Parse only `Point`,
`Polygon`, and `MultiGeometry`
containing points/polygons. Preserve `warning_kind`, source time, active window,
resolved/active state, geometry, source filename, and exact provenance. Pass
`warning_kind` and `network_link_source_url` through staging.

If one of four child KML reads fails while another succeeds, emit a safe
source-rejection record and a partial run. If all selected child reads fail,
raise a fetch error so the run is failed rather than healthy empty.

Extend the valid-empty warning adapter set with
`official.wra.flood_warning`; do not turn arbitrary empty adapters into healthy
warning polls.

- [ ] **Step 5: Add independent disabled gates and catalog metadata**

Add exact defaults:

```text
SOURCE_WRA_FLOOD_WARNING_ENABLED=false
SOURCE_WRA_FLOOD_WARNING_API_ENABLED=false
SOURCE_WRA_FLOOD_WARNING_CONTRACT_ENABLED=false
WRA_FLOOD_WARNING_TIMEOUT_SECONDS=8
```

Register key `official.wra.flood_warning`; no configurable arbitrary URL is
accepted. Catalog metadata references data.gov.tw datasets 5982, 5983, and
5984, all four exact KML URLs, and an explicit `active_fixture_reviewed=false`
limitation. Runtime construction requires all three gates.

- [ ] **Step 6: Verify GREEN and security regressions**

Run:

```bash
cd apps/workers
../../.venv/workers/bin/python -m pytest \
  tests/test_wra_flood_warning_adapter.py \
  tests/test_adapter_registry_config.py \
  tests/test_official_source_catalog.py \
  tests/test_ingestion_job_runner.py \
  tests/test_staging_pipeline.py \
  tests/test_promotion_pipeline.py \
  tests/test_wra_historical_flood_adapter.py -q
../../.venv/workers/bin/ruff check \
  app/adapters/wra/flood_warning.py app/adapters/wra/__init__.py \
  app/adapters/registry.py app/jobs/runtime.py app/jobs/ingestion.py \
  app/config.py app/pipelines/staging.py \
  tests/test_wra_flood_warning_adapter.py
```

Expected: selected tests pass, the historical WRA adapter remains unchanged in
behavior, context never enters latest, and Ruff exits 0.

- [ ] **Step 7: Commit WRA warning context support**

```bash
git add .env.example \
  apps/workers/app/adapters/wra/flood_warning.py \
  apps/workers/app/adapters/wra/__init__.py \
  apps/workers/app/adapters/registry.py \
  apps/workers/app/jobs/runtime.py apps/workers/app/jobs/ingestion.py \
  apps/workers/app/config.py apps/workers/app/pipelines/staging.py \
  apps/workers/tests/fixtures/wra_flood_warning_index.json \
  apps/workers/tests/fixtures/wra_flood_warning_empty.kml \
  apps/workers/tests/fixtures/wra_flood_warning_synthetic_active.kml \
  apps/workers/tests/fixtures/wra_flood_warning_wrapper.kml \
  apps/workers/tests/test_wra_flood_warning_adapter.py \
  apps/workers/tests/test_adapter_registry_config.py \
  apps/workers/tests/test_official_source_catalog.py \
  apps/workers/tests/test_promotion_pipeline.py \
  docs/data-sources/official/official-source-catalog.yaml
git commit -m "feat: ingest bounded WRA warning context"
```

### Task 7: Add a persisted recent-context display path with scoring invariance

**Files:**

- Modify: `apps/api/app/domain/evidence/repository.py`
- Modify: `apps/api/app/domain/evidence/__init__.py`
- Modify: `apps/api/app/domain/assessment/models.py`
- Modify: `apps/api/app/domain/assessment/repository.py`
- Modify: `apps/api/app/api/services/assessment.py`
- Modify: `apps/api/tests/test_evidence_repository.py`
- Modify: `apps/api/tests/test_evidence_repository_postgres.py`
- Modify: `apps/api/tests/test_assessment_repository.py`
- Modify: `apps/api/tests/test_assessment_service.py`
- Modify: `apps/api/tests/test_scoring.py`
- Modify: `apps/api/tests/test_public_contract.py`

**Interfaces:**

- Consumes: persisted `evidence` rows from Tasks 5–6, existing
  `EvidencePreview.limitations`, and the unchanged scorer.
- Produces:

```python
RECENT_INCIDENT_CONTEXT_WINDOW = timedelta(hours=6)
RECENT_INCIDENT_CONTEXT_FUTURE_TOLERANCE = timedelta(minutes=5)


def query_nearby_recent_context(
    *,
    database_url: str,
    lat: float,
    lng: float,
    radius_m: int,
    as_of: datetime,
    limit: int = 50,
    statement_timeout_ms: int = 0,
    connection_factory: ConnectionFactory | None = None,
) -> tuple[EvidenceRecord, ...]:
    """Return latest active, nearby, display-only official context rows."""
```

Add `recent_incident_context: tuple[EvidenceRecord, ...] = ()` as the final
field of `AssessmentData` so existing explicit constructors remain compatible.

- [ ] **Step 1: Write RED repository query tests**

The SQL tests must prove the query:

```text
requires data_sources.is_enabled = true
requires source_type = official
requires event_type = status_only
requires properties.evidence_scope = context
allows only official.npa.police_radio_traffic and official.wra.flood_warning
ranks latest version by adapter_key + source_id
uses valid upstream_updated_at, then observed_at, then created_at
keeps observed_at within as_of - 6 hours and as_of + 5 minutes
excludes latest incident_state resolved or excluded
requires a non-null geometry intersecting the selected radius
bounds limit to 1..100
```

The mandatory PostGIS test inserts active, stale, future, resolved, duplicate
UID, disabled-source, and out-of-radius rows and asserts only the latest active
recent in-radius rows return.

- [ ] **Step 2: Run repository tests and record RED**

Run:

```bash
cd apps/api
../../.venv/api/bin/python -m pytest \
  tests/test_evidence_repository.py \
  tests/test_evidence_repository_postgres.py -q
```

Expected: FAIL because `query_nearby_recent_context` does not exist.

- [ ] **Step 3: Implement the bounded PostGIS query**

Validate `radius_m` in 50–2000 and require timezone-aware `as_of`. Use
`pg_input_is_valid(properties->>'upstream_updated_at', 'timestamptz')` before
casting it. Rank source versions first, then apply `incident_state` and time
filters to the rank-1 row so a resolved update suppresses its older active row.
Return standard `EvidenceRecord` values; do not add a second public model.

- [ ] **Step 4: Write RED assessment separation and invariance tests**

Change the repository tests to require three disjoint collections:

```python
assert data.current_official == (rainfall,)
assert data.historical == (historical_flood,)
assert data.recent_incident_context == (police_context, wra_context)
```

`_historical_only()` must retain `evidence_scope="historical"` and
`event_type="flood_potential"`, but it must no longer accept arbitrary
`status_only/context` rows.

In `test_assessment_service.py`, call the service once without context and once
with the same current/historical data plus context. Assert equality of:

```python
assert with_context.realtime == without_context.realtime
assert with_context.historical == without_context.historical
assert with_context.overall == without_context.overall
assert with_context.confidence == without_context.confidence
assert with_context.explanation == without_context.explanation
assert with_context.nearby_realtime_coverage == without_context.nearby_realtime_coverage
```

Also assert police/WRA items appear in `with_context.evidence`, the police item
contains `警廣即時路況通報，尚未由淹水感測器確認。`, and the scorer spy receives
exactly the same two signal tuples in both calls.

- [ ] **Step 5: Run assessment tests and record RED**

Run:

```bash
cd apps/api
../../.venv/api/bin/python -m pytest \
  tests/test_assessment_repository.py \
  tests/test_assessment_service.py \
  tests/test_scoring.py \
  tests/test_public_contract.py -q
```

Expected: FAIL because context is currently folded into `historical` and passed
to the historical scorer/confidence calculation.

- [ ] **Step 6: Implement display-only assessment composition**

Load recent context independently and fail that read independently. Score only
`current_official` and `historical`. Compose display evidence in this order:

```python
display_items = display_evidence_items(
    list(
        _deduplicate_evidence(
            (*current_items, *context_items, *historical_items)
        )
    )
)
```

Continue to bound the public preview to 10 and persist only UUID evidence IDs.
Do not alter `RiskAssessmentResponse` keys, the OpenAPI schema shape, weights,
coverage, safety, or overall-decision functions.

- [ ] **Step 7: Verify GREEN, mandatory PostGIS, and static quality**

Run unit tests:

```bash
cd apps/api
../../.venv/api/bin/python -m pytest \
  tests/test_evidence_repository.py \
  tests/test_assessment_repository.py \
  tests/test_assessment_service.py \
  tests/test_scoring.py \
  tests/test_public_contract.py -q
../../.venv/api/bin/ruff check \
  app/domain/evidence/repository.py app/domain/evidence/__init__.py \
  app/domain/assessment app/api/services/assessment.py \
  tests/test_evidence_repository.py tests/test_assessment_repository.py \
  tests/test_assessment_service.py tests/test_scoring.py
```

Run mandatory database acceptance with the operator-provided test database:

```bash
cd apps/api
OFFICIAL_DB_ACCEPTANCE_REQUIRED=1 \
EVIDENCE_TEST_DATABASE_URL="postgresql://flood_risk:change-me-local@127.0.0.1:5432/flood_risk" \
../../.venv/api/bin/python -m pytest \
  tests/test_evidence_repository_postgres.py -q -rs
```

Expected: focused unit tests pass, mandatory PostGIS has zero skips/failures,
and Ruff exits 0. If the test database is not available, this task is blocked;
do not convert the mandatory test to a skip.

- [ ] **Step 8: Commit the recent-context read path**

```bash
git add apps/api/app/domain/evidence/repository.py \
  apps/api/app/domain/evidence/__init__.py \
  apps/api/app/domain/assessment/models.py \
  apps/api/app/domain/assessment/repository.py \
  apps/api/app/api/services/assessment.py \
  apps/api/tests/test_evidence_repository.py \
  apps/api/tests/test_evidence_repository_postgres.py \
  apps/api/tests/test_assessment_repository.py \
  apps/api/tests/test_assessment_service.py \
  apps/api/tests/test_scoring.py apps/api/tests/test_public_contract.py
git commit -m "feat: display recent official incident context"
```

### Task 8: Register disabled catalog rows in migration 0038

**Files:**

- Create: `infra/migrations/0038_official_incident_context_sources.sql`
- Create: `tests/test_official_incident_source_migration.py`
- Create: `tests/test_official_incident_source_migration_postgres.py`
- Modify: `infra/migrations/README.md`
- Modify: `apps/api/app/api/routes/health.py`
- Modify: `apps/api/tests/test_public_contract.py`
- Modify: `tests/test_apply_migrations_script.py`
- Modify: `apps/workers/tests/test_official_source_catalog.py`
- Modify: `docs/superpowers/plans/2026-08-24-v1-core-official-baseline.md`

**Interfaces:**

- Consumes: `data_sources` from migration 0002, the existing NCDR row from
  migration 0018, and source metadata from Tasks 3–6.
- Produces: four exact `data_sources` rows with `is_enabled=false` and a schema
  sentinel of `0038_official_incident_context_sources.sql`.

- [ ] **Step 1: Write RED static migration contract tests**

The test reads the SQL and requires these keys exactly once:

```python
EXPECTED_KEYS = {
    "official.cwa.heavy_rain_warning",
    "official.ncdr.cap",
    "official.npa.police_radio_traffic",
    "official.wra.flood_warning",
}
```

It asserts every row is `official`, `unknown`, and `false`; the migration stores
no token/key value; police/WRA rows are context-only; CWA/NCDR spatial review is
unapproved; and no context source is inserted into required realtime coverage
mappings. Add a health test expecting the new filename.

- [ ] **Step 2: Run migration contract tests and record RED**

Run:

```bash
../../.venv/api/bin/python -m pytest \
  tests/test_official_incident_source_migration.py \
  tests/test_apply_migrations_script.py \
  apps/api/tests/test_public_contract.py \
  apps/workers/tests/test_official_source_catalog.py -q
```

Expected: FAIL because migration 0038 and its schema sentinel do not exist.

- [ ] **Step 3: Implement idempotent disabled rows and update the sentinel**

Use one idempotent `INSERT INTO data_sources` statement with
`ON CONFLICT (adapter_key) DO UPDATE` and explicitly set `is_enabled = false`
on every insert/update. Metadata must include public-safe
owner, landing/resource URLs, license, limitation, review status, and phase.
Update `REQUIRED_SCHEMA_FILENAME` in health to
`0038_official_incident_context_sources.sql` and update its exact tests.

Because migration number 0038 is now consumed, replace every planned `0038`
reference in `docs/superpowers/plans/2026-08-24-v1-core-official-baseline.md`
with `0039` and rename its future filename to
`0039_v1_official_baseline_sources.sql`. This is a plan-document correction;
do not create migration 0039 in this task.

- [ ] **Step 4: Verify static and real PostgreSQL migration behavior**

Run static checks:

```bash
../../.venv/api/bin/python infra/scripts/validate_migrations.py
../../.venv/api/bin/python -m pytest \
  tests/test_official_incident_source_migration.py \
  tests/test_apply_migrations_script.py \
  apps/api/tests/test_public_contract.py \
  apps/workers/tests/test_official_source_catalog.py -q
```

Run the mandatory database test with the operator-provided database:

```bash
OFFICIAL_DB_ACCEPTANCE_REQUIRED=1 \
EVIDENCE_TEST_DATABASE_URL="postgresql://flood_risk:change-me-local@127.0.0.1:5432/flood_risk" \
../../.venv/api/bin/python -m pytest \
  tests/test_official_incident_source_migration_postgres.py -q -rs
```

Expected: empty-schema and 0037→0038 upgrade paths both leave all four rows
disabled, retain no credential, and have zero mandatory skips/failures.

- [ ] **Step 5: Commit migration 0038 and the plan renumbering**

```bash
git add infra/migrations/0038_official_incident_context_sources.sql \
  infra/migrations/README.md \
  apps/api/app/api/routes/health.py apps/api/tests/test_public_contract.py \
  tests/test_official_incident_source_migration.py \
  tests/test_official_incident_source_migration_postgres.py \
  tests/test_apply_migrations_script.py \
  apps/workers/tests/test_official_source_catalog.py \
  docs/superpowers/plans/2026-08-24-v1-core-official-baseline.md
git commit -m "feat: register disabled official incident sources"
```

### Task 9: Generate public-safe manual external request packets

**Files:**

- Create: `apps/api/app/ops/official_incident_request_packets.py`
- Create: `apps/api/tests/test_official_incident_request_packets.py`
- Create: `scripts/official-incident-request-packets.py`
- Create: `tests/test_official_incident_request_packets_cli.py`
- Create: `docs/data-sources/official/official-incident-request-packets.md`
- Modify: `docs/data-sources/official/README.md`

**Interfaces:**

- Consumes: no network, browser, mail, credential, or existing local-source
  completion workflow.
- Produces:

```python
def build_official_incident_request_packets() -> tuple[dict[str, object], ...]:
    """Return the fixed public-safe set of manual application packets."""


def render_official_incident_request_packets_markdown(
    packets: tuple[dict[str, object], ...],
) -> str:
    """Render reviewable packets without sending them."""
```

The CLI accepts only `--format json|markdown` and optional `--output PATH`.
It has no send, dispatch, login, token, evidence-ref, browser, or webhook flag.

- [ ] **Step 1: Write RED generator and CLI tests**

Require exactly nine packet IDs:

```python
EXPECTED_PACKET_IDS = (
    "ncdr-citizen-disaster-report",
    "ncdr-edxl-sitrep",
    "kinmen-kwis-read-api",
    "hualien-senslink-read-api",
    "miaoli-drainage-read-api",
    "pingtung-pteoc-read-api",
    "taitung-water-read-api",
    "lienchiang-live-water-feed",
    "waze-for-cities-flood-incidents",
)
```

Each packet has `requires_human_intervention=true`,
`submission_mode="manual_only"`, purpose, requested fields, cadence,
retention/deletion policy, public source URL, and `contact_name=null` /
`contact_email=null`. Assert serialized output contains none of `token`,
`password`, `cookie`, `Authorization`, `private-ops://`, or a non-null contact.
Assert importing/running the module performs no network call.

- [ ] **Step 2: Run tests and record RED**

Run:

```bash
../../.venv/api/bin/python -m pytest \
  apps/api/tests/test_official_incident_request_packets.py \
  tests/test_official_incident_request_packets_cli.py -q
```

Expected: FAIL because the module and CLI do not exist.

- [ ] **Step 3: Implement deterministic packets and renderer**

Use immutable in-module packet definitions. Sort by the `EXPECTED_PACKET_IDS`
order, render UTF-8 without secrets, and write only when `--output` is supplied.
The script must never import `requests`, `httpx`, `urllib.request`, `smtplib`, a
browser driver, or a connector SDK.

- [ ] **Step 4: Generate the checked-in review artifact and verify**

Run:

```bash
../../.venv/api/bin/python scripts/official-incident-request-packets.py \
  --format markdown \
  --output docs/data-sources/official/official-incident-request-packets.md
../../.venv/api/bin/python -m pytest \
  apps/api/tests/test_official_incident_request_packets.py \
  tests/test_official_incident_request_packets_cli.py \
  tests/test_local_source_request_packets_cli.py -q
../../.venv/api/bin/ruff check \
  apps/api/app/ops/official_incident_request_packets.py \
  apps/api/tests/test_official_incident_request_packets.py \
  scripts/official-incident-request-packets.py \
  tests/test_official_incident_request_packets_cli.py
```

Expected: all selected tests pass, existing local request packets are unchanged,
the artifact contains nine manual-only packets, and Ruff exits 0.

- [ ] **Step 5: Commit the request packet generator**

```bash
git add apps/api/app/ops/official_incident_request_packets.py \
  apps/api/tests/test_official_incident_request_packets.py \
  scripts/official-incident-request-packets.py \
  tests/test_official_incident_request_packets_cli.py \
  docs/data-sources/official/official-incident-request-packets.md \
  docs/data-sources/official/README.md
git commit -m "docs: generate official incident request packets"
```

### Task 10: Lock default-off release contracts and run full acceptance

**Files:**

- Create: `tests/test_safe_fast_official_incident_release_contract.py`
- Create: `docs/runbooks/safe-fast-official-incident-activation.md`
- Modify: `apps/workers/tests/test_adapter_registry_config.py`
- Modify: `apps/workers/tests/test_runtime_managed_ingestion.py`
- Modify: `docs/data-sources/official/README.md`

**Interfaces:**

- Consumes: Tasks 1–9 and the existing per-source managed runner.
- Produces: one operator checklist proving code landed/default off, with no
  deployment or activation claim.

- [ ] **Step 1: Write the failing aggregate release-contract test**

The test reads checked-in settings, registry, catalog YAML, migration SQL, and
the runbook. It requires all four adapter keys, all source/API/contract defaults
false, NCDR exact endpoint/format names, WRA exact allowlist, police limitation,
`is_enabled=false`, rollback order, and the statement
`code landed/default off; not production activated`.

- [ ] **Step 2: Run aggregate tests and record RED**

Run:

```bash
../../.venv/api/bin/python -m pytest \
  tests/test_safe_fast_official_incident_release_contract.py \
  apps/workers/tests/test_adapter_registry_config.py \
  apps/workers/tests/test_runtime_managed_ingestion.py -q
```

Expected: FAIL until the activation/rollback runbook and aggregate contract are
complete.

- [ ] **Step 3: Write the operator runbook and close only documented gaps**

The runbook must state:

```text
1. Apply migration with every new row disabled.
2. Enable one catalog row only after persisted raw/staging/run/evidence proof.
3. Enable that source's source, API, and reviewed-contract gates only.
4. Run isolated worker ingestion and public assessment smoke checks.
5. Record deploy SHA, freshness, count, attribution, limitations, and rollback proof.
6. Roll back by disabling the catalog row first, then runtime/API/contract gates.
7. CWA/NCDR unresolved geometry remains audit-only; police/WRA context remains non-scoring.
```

Do not include a live credential, production command execution result, or claim
that any source was enabled.

- [ ] **Step 4: Run complete verification**

Worker suite:

```bash
cd apps/workers
../../.venv/workers/bin/python -m pytest -q
../../.venv/workers/bin/ruff check \
  app/adapters/contracts.py app/adapters/cap_xml.py app/adapters/cwa \
  app/adapters/ncdr app/adapters/police_radio_traffic app/adapters/wra \
  app/adapters/registry.py app/jobs/source_catalog.py app/jobs/runtime.py \
  app/jobs/runtime_managed.py app/jobs/ingestion.py \
  app/config.py app/pipelines/staging.py
../../.venv/api/bin/python -m mypy app
cd ../..
```

The repository's API virtual environment is the established shared mypy
environment and currently checks the Worker package independently from inside
`apps/workers`; do not import the API package in that process.

API and repository suite:

```bash
cd apps/api
../../.venv/api/bin/python -m pytest -q
../../.venv/api/bin/ruff check \
  app/domain/evidence/repository.py app/domain/evidence/__init__.py \
  app/domain/assessment app/api/services/assessment.py \
  app/ops/official_incident_request_packets.py
../../.venv/api/bin/mypy app
cd ../..
```

Repository contracts:

```bash
../../.venv/api/bin/python -m pytest tests -q
../../.venv/api/bin/python infra/scripts/validate_openapi.py
../../.venv/api/bin/python infra/scripts/validate_contract_fixtures.py
../../.venv/api/bin/python infra/scripts/validate_migrations.py
git diff --check
```

Web rolling-compatibility acceptance:

```bash
cd apps/web
npm ci
npm test
npm run lint
npm run typecheck
npm run build
npm run e2e
cd ../..
```

Mandatory PostgreSQL acceptance:

```bash
OFFICIAL_DB_ACCEPTANCE_REQUIRED=1 \
EVIDENCE_TEST_DATABASE_URL="postgresql://flood_risk:change-me-local@127.0.0.1:5432/flood_risk" \
../../.venv/api/bin/python -m pytest \
  apps/api/tests/test_evidence_repository_postgres.py \
  tests/test_official_incident_source_migration_postgres.py -q -rs
```

Expected: every command exits 0; mandatory PostgreSQL has zero skips; no new
source is enabled. If any command fails, report the exact failure and keep this
task incomplete.

- [ ] **Step 5: Commit the release contract and runbook**

```bash
git add tests/test_safe_fast_official_incident_release_contract.py \
  docs/runbooks/safe-fast-official-incident-activation.md \
  apps/workers/tests/test_adapter_registry_config.py \
  apps/workers/tests/test_runtime_managed_ingestion.py \
  docs/data-sources/official/README.md
git commit -m "test: lock official incident release gates"
```

- [ ] **Step 6: Request whole-branch review**

Generate a review package from the branch merge base through HEAD and request
an independent review of spec compliance, source security, scoring invariance,
secret handling, migration default-off behavior, and rollback documentation.
Resolve every Critical/Important finding with a tested fix and re-review before
using `superpowers:finishing-a-development-branch`.

## Execution Order and Checkpoints

Execute Tasks 1–10 in order. Task 1 is a hard prerequisite for CWA/NCDR audit
semantics, and Task 2 is a hard prerequisite for every new runtime adapter.
Tasks 5 and 6 depend on Task 1 but not on each other; Subagent-Driven Development
still uses one implementer at a time to avoid shared registry/config conflicts.
Task 7 starts only after both context adapters exist. Task 8 starts after all
four source keys are final. Task 10 is the only full-acceptance gate.

For every task:

1. record the pre-task commit;
2. generate a task brief with `scripts/task-brief` from the
   `subagent-driven-development` skill;
3. dispatch one fresh implementer using TDD;
4. verify the implementer report and changed files;
5. generate a review package from the recorded base to task head;
6. dispatch a fresh task reviewer for both spec compliance and code quality;
7. resolve Critical/Important findings and re-review;
8. append the clean task result and commit range to
   `.superpowers/sdd/progress.md` before starting the next task.
