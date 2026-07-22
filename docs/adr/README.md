# Architecture Decision Records

此目錄保存 Flood Risk 專案的架構決策紀錄。`docs/PROJECT_SDD.md` 仍是最高設計契約，ADR 用來補充、具體化或修訂 SDD 中需要長期追蹤的決策。

## ADR Format

每份 ADR 必須使用下列一致段落：

- Title
- Status
- Date
- Context
- Decision
- Consequences

可選段落：`Alternatives Considered`（記錄放棄了哪些方案與原因，讓未來要抽換元件的人不必從頭重估——見 ADR-0003），以及 addendum/enforcement note（決策上線後發現落差時補記，見 ADR-0006、ADR-0010）。

## 如何新增一份 ADR

1. **判斷是否需要 ADR。** 會長期影響架構、資料契約、資料庫 schema、評分規則、隱私政策、授權或部署策略的決策才需要（與 `CONTRIBUTING.md` 的規則一致）。純實作細節不需要。
2. **取編號。** 用下方索引表最大編號 +1，四位數零填充（例如 `0011`）。檔名格式 `NNNN-kebab-case-title.md`。
3. **寫內容。** 複製任一份既有 ADR 的段落結構；Status 一律從 `Proposed` 開始（若要立即定案再寫 `Accepted`），Date 用 ISO `YYYY-MM-DD`。
4. **更新索引。** 在本檔的 Index 表末尾加一列。
5. **審核與定案。** 透過 Pull Request 提出（見 `.github/PULL_REQUEST_TEMPLATE.md` 的 contract-impact 勾選）。合併後將 Status 改為 `Accepted`；被後續 ADR 取代時改為 `Superseded by ADR-NNNN` 並在新 ADR 標明取代關係。決策上線後若發現與實作有落差，不要改寫原決策，改在該 ADR 末尾加 addendum/enforcement note 記錄落差與修正。

## Index

| ADR | Title | Status | Date |
|---|---|---|---|
| [0001](0001-sdd-as-source-of-truth.md) | SDD as Source of Truth | Accepted | 2026-04-28 |
| [0002](0002-maplibre-self-hosted-osm-tiles.md) | MapLibre and Open PMTiles Basemap | Accepted | 2026-04-28 |
| [0003](0003-fastapi-postgis-backend.md) | FastAPI and PostGIS Backend | Accepted | 2026-04-28 |
| [0004](0004-adapter-based-data-ingestion.md) | Adapter-Based Data Ingestion | Accepted | 2026-04-28 |
| [0005](0005-dual-risk-score-model.md) | Dual Risk Score Model | Accepted | 2026-04-28 |
| [0006](0006-privacy-preserving-query-heat.md) | Privacy-Preserving Query Heat | Accepted | 2026-04-28 |
| [0007](0007-official-and-public-evidence-strategy.md) | Official and Public Evidence Strategy | Accepted | 2026-04-28 |
| [0008](0008-score-versioning-and-explainability.md) | Score Versioning and Explainability | Accepted | 2026-04-28 |
| [0009](0009-precomputed-risk-profiles-and-vector-assisted-evidence.md) | Precomputed Risk Profiles and Vector-Assisted Evidence | Accepted | 2026-05-08 |
| [0010](0010-realtime-bridge-as-local-diagnostic.md) | Realtime Official Bridge as Local Diagnostic Tool | Accepted | 2026-06-11 |
