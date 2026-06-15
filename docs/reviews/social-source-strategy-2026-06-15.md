# 社群來源策略建議書（FB / IG / Threads / PTT / Dcard）

狀態：決策建議草案，待使用者最終拍板
日期：2026-06-15
對應決策：記憶檔「社群來源規格衝突仍待使用者決策」
相關規格：`docs/PROJECT_SDD.md` 2.3 / 4.7、`docs/privacy/public-discussion-user-report-gates.md`、
`docs/data-sources/forum/source-approval-manifest.yaml`

---

## 0. 一頁摘要與建議

本專案口頭規格希望納入社群來源（FB/IG/Threads/PTT/Dcard）。深入評估後，這**不是**「規格 vs 使用者」的硬衝突——SDD 2.3 禁止的是「未授權爬取」與「個資畫像」，而 SDD 4.7 已保留授權路徑。真正的問題是：**每個平台的合法路徑，與「對外即時供查的 evidence pipeline」這個產品需求是否相容。**

結論分軌：

| 來源 | 合法路徑 | 與本產品 pipeline 相容性 | 建議 |
|---|---|---|---|
| **FB / IG / Threads** | Meta Content Library（唯一合規路徑） | ✗ enclave 內分析、原則不可匯出，**無法**灌進 PostGIS 對外供查 | **遞延**。MCL 適合離線研究/校準，不適合當產品 evidence 來源。爬蟲 repo 全部違反 SDD 2.3，不採用。 |
| **PTT** | 公開 web，可合法取得 | ✓ 可正常 ingestion 並存成 evidence row | **走合規前置**：先補完 gate，再啟用 |
| **Dcard** | API v2 / 公開頁，但反爬已強化 | △ 技術可行但脆弱、ToS 需審 | **次於 PTT**，gate＋ToS 審查後評估 |

**一句話建議**：FB/IG/Threads 此階段遞延（沒有可對外供查的合規路徑）；把社群佐證的投入集中在 **PTT（優先）＋ Dcard（次之）**，走完 per-source 法遵 gate 後啟用。這完全落在 SDD 4.7 既定的優先序內，不需修改 SDD 或新增 ADR。

---

## 1. 決策背景與規格約束

- **SDD 2.3 明確不做**（`PROJECT_SDD.md:99-101`）：不以未授權方式大量爬取 FB/IG/Threads；不儲存社群帳號個人檔案／行為資料庫；不將單一貼文直接判定為淹水事實。
  - 約束的是**手段（未授權爬取）與隱私（個資畫像）**，不是全面封殺平台。
- **SDD 4.7 合法分層**（`PROJECT_SDD.md:285-286`）：優先序 `news/RSS/public web → PTT → Dcard → 授權的 Meta 來源`；FB/IG/Threads「需官方 API、Meta Content Library、研究存取、明確授權或後續 ADR」。
- **Phase 4/5 gate**（`docs/privacy/public-discussion-user-report-gates.md`）：PTT/Dcard/generic forum 與 user_report 在通過 per-source 法遵/隱私 gate 前一律 disabled，目前只允許 synthetic fixture，不准真的爬取。

---

## 2. FB / IG / Threads 軌：Meta Content Library 可行性評估

### 2.1 為何只剩這條路

GitHub 上的 FB/IG/Threads 爬蟲（instaloader、instagrapi、drawrowfly/instagram-scraper、kevinzg/facebook-scraper、Zeeshanahmad4/Threads-Scraper 等）**全部靠打內部端點或繞過反爬**，正是 SDD 2.3 定義的「未授權方式」。無論美國判例（Meta v. Bright Data 2024、hiQ v. LinkedIn）是否認定公開資料爬取不違反 CFAA，**都不解除本專案自訂的 SDD 2.3 限制，也不適用台灣法域，更不抵銷平台 ToS 契約主張**。故這些 repo 一律不採用。

唯一合規路徑為 [Meta Content Library and API](https://transparency.meta.com/researchtools/meta-content-library/)（官方研究工具）。

### 2.2 Meta Content Library 事實摘要（2026-06 查證）

- **涵蓋平台**：Facebook、Instagram、Threads（含 WhatsApp Channels）公開內容，可程式化（Python/R）查詢，近即時。
- **資格**：須隸屬學術機構**或核心活動為科學／公益研究的非營利組織**；個人若符合機構條件可申請，無學位門檻。本專案「公益、開源優先」定位方向吻合，但**需要一個合格的機構/非營利實體掛名**。
- **申請**：透過 Meta Research Tools Manager 提交，由獨立審查（CASD/ICPSR-SOMAR 體系）核准。
- **費用**：Meta 對存取本身不收費；但第三方 **SOMAR 虛擬資料區（VDE）自 2026 年起約 US$371/團隊/月** 的運算費。
- **致命限制（架構不相容）**：資料只能在**受控 enclave**（Meta Secure Research Environment 或 SOMAR VDE）內分析，**原則上不可匯出**；僅 15,000–25,000+ 追蹤者的大型帳號、第三方申請者才有「有限下載」。

### 2.3 可行性結論

- **不適合當產品 evidence 來源**：本專案需要把佐證存成 PostGIS evidence row、即時對外供查。MCL 的 no-export enclave 模型與此**根本相容性不足**——你無法把 Threads/IG 的淹水貼文搬出來進 ingestion pipeline。
- **有限的合理用途**：MCL 可作為**離線研究/模型校準**工具（例如評估某次淹水事件社群討論的覆蓋率、驗證 PTT/Dcard 訊號是否與更大平台一致），但這是研究性質，不是產品功能。
- **建議**：FB/IG/Threads **此階段遞延**。若未來要做，路徑是「找合格非營利機構掛名→申請 MCL→僅作離線研究」，而非進產品 pipeline。要把社群貼文真正納入對外風險佐證，PTT/Dcard 才是務實標的。

---

## 3. PTT / Dcard 軌：法遵 gate 缺口盤點

兩者在 `source-approval-manifest.yaml` 現況皆為 `acceptance_status: blocked` / `accepted: false`，只允許 `local_fixture_only` 的 synthetic 合約測試（`network_access: disabled`）。要從 blocked 推進到可啟用，需補齊以下欄位（直接取自 manifest `missing_acceptance_fields`）：

### 3.1 PTT 缺口
- `approved_board_allowlist`：核准的看板白名單（淹水相關，且**排除 Gossiping 等需 over18 cookie 的板**——gate 禁止 over18 bypass 自動化）
- `approved_access_method`：存取方式（PTT web 公開頁）
- `robots_and_terms_review_links`：robots.txt／站規／看板規範審查連結
- `no_login_or_over18_bypass_attestation`：不繞登入/over18 的具結
- `stored_field_inventory`：只存 URL/board/timestamp/location hints/summary/confidence/moderation state
- `username_handling_policy`：預設不存 username；若去重需 actor key，用 per-env 加鹽雜湊＋輪替/刪除路徑
- `raw_snapshot_retention_limit`：raw 快照預設關閉或短期 debug 上限
- `moderation_rejection_rules`：拒收八卦/指名私人/doxxing/騷擾/無淹水關聯
- `rate_limit_and_backoff_policy`、`audit_log_events`、`opt_out_delete_workflow`、`emergency_disable_owner`

### 3.2 Dcard 缺口
- `approved_forum_allowlist`、`approved_access_method_or_authorized_api`（優先用官方/授權 API，非登入限定內容）
- `robots_terms_api_review_links`：Dcard ToS／API 條款／rate limit 審查
- `no_login_hidden_content_or_antibot_bypass_attestation`：**不繞反爬**的具結（Dcard 已上 Cloudflare，這條是關鍵風險）
- `stored_field_inventory`、`user_identity_exclusion_policy`（不存 user id/handle/avatar/學校工作）
- `raw_body_retention_limit`、`moderation_rejection_rules`、`rate_limit_quota_and_backoff_policy`、`audit_log_events`、`opt_out_delete_workflow`、`emergency_disable_owner`

### 3.3 全域 gate（兩者共通，來自 checklist「Global Gates」與「Before production launch」）
- 法律來源審查具結、資料最小化、無 raw HTML/全文/個資、retention 窗、moderation 工作流、濫用防護（rate limit/去重/blocklist/kill switch）、audit log、opt-out/delete owner+SLA+公開聯絡管道、UI/API 標示非官方來源且不得作為高信心淹水斷言的唯一依據、feature flag 預設關閉。

### 3.4 工作量量級（相對估計，非承諾工時）
- **合規前置（不爬取）**：撰寫 approval request、補齊上述欄位、moderation 規則與 fixture、opt-out/delete 流程設計、audit log 事件定義。量級：中。風險低，可現在就做。
- **PTT adapter 實作**：PTT web 結構穩定、已有成熟參考（jwlin/ptt-web-crawler），加上 raw→staging→promote、location 抽取、去重、rate limit。量級：中。
- **Dcard adapter 實作**：受 Cloudflare 反爬影響，合規取得不穩定；若無授權 API，技術與法遵風險都高於 PTT。量級：中—高，且**結果可能不穩**。建議 PTT 先行、Dcard 視 ToS 審查結論再定。

---

## 4. 與本專案 evidence schema 的契合

SDD `Evidence`（`PROJECT_SDD.md:457-475`）已內建 `source_type: ... | forum | social | ...`、`privacy_level`、`source_weight`、`confidence`、`raw_ref` 等欄位，**schema 層面已能容納 PTT/Dcard 佐證**，且 `source_weight`/`confidence` 機制天然支援「非官方來源不得作為唯一高信心依據」（SDD 2.3 第三條）。亦即啟用 PTT/Dcard 不需改 schema，只需走 gate＋adapter。

---

## 5. 法律與法域注意（非法律意見）

- 美國判例（Meta v. Bright Data 2024、hiQ v. LinkedIn）認定爬取登出可見公開資料不違反 CFAA，**但**：不推翻平台 ToS 契約主張、不適用台灣法域、不解除 SDD 2.3 自訂限制。
- 台灣場景另需考量個資法（去識別化、最小化）、著作權（只輸出摘要與連結、不散布全文——已是 SDD OQ-003 決議）。
- 任何「accepted: true」的 manifest 變更，都必須附 terms/privacy/retention/moderation/opt-out/rate-limit 的審查證據，validator 才會通過。

---

## 6. 建議的決策方案

**方案 A（推薦）— 聚焦 PTT/Dcard，FB/IG/Threads 遞延**
1. FB/IG/Threads：標記為「遞延，需 MCL 機構掛名且僅限離線研究」，不進產品 pipeline。更新 SDD 4.7 註記即可，**不需新增 ADR**。
2. PTT：立即啟動「合規前置」（補 gate，不爬取）→ 審查通過 → 實作 adapter → 啟用。
3. Dcard：完成 ToS/API 審查後再定；若反爬導致無法合規穩定取得，維持遞延。

**方案 B — 全部維持現狀**：社群佐證續靠已審查的 L2 news/public web；PTT/Dcard 續留空 stub。適合不想增加法遵負擔時。

**方案 C — 推翻 SDD 2.3 對 FB/IG/Threads 的立場**：技術上需採用 🚫 類爬蟲，**不建議**——違反專案自訂規格、ToS、台灣法域風險，且需新增 ADR＋法律審查背書。

---

## 7. 若採方案 A，後續執行順序（待拍板後啟動）

1. 更新 SDD 4.7 / 記憶檔，記錄 FB/IG/Threads 遞延決策與理由（MCL no-export 不相容）。
2. 為 PTT 撰寫 `source-approval-request`（依 manifest schema），逐條補 `missing_acceptance_fields`。
3. 設計 PTT moderation 規則 + false-positive fixtures（淹水關聯、地名抽取、排除八卦/指名）。
4. 設計 opt-out/delete 工作流與 audit log 事件，指定 emergency disable owner。
5. 法律/ToS 審查通過後，manifest 改 `accepted: true`（附審查證據），實作 PTT adapter（raw→staging→promote）。
6. Dcard：完成 ToS/API 審查，視結論決定啟用或維持遞延。

---

## 附錄：GitHub 工具生態盤點（2026-06 查證，僅供了解，🚫 類不採用）

- **PTT（⚠️ 需 gate）**：jwlin/ptt-web-crawler（最常引用，lib+CLI）、zake7749/PTT-Crawler、NaiveRed/PTT-Crawler、WayneChang65/ptt-crawler（Node）。
- **Dcard（⚠️ 需 gate＋ToS）**：DouglasWu/dcard-crawler（Scrapy，走 API v2）、leVirve/dcard-spider（pip）、sweslo17/dcard_crawler。多數受 Cloudflare 反爬影響部分失效。
- **IG（🚫 違反 SDD 2.3）**：instaloader（12.1k★，打內部 GraphQL）、subzeroid/instagrapi、drawrowfly/instagram-scraper、chris-greening/instascrape。
- **FB（🚫）**：kevinzg/facebook-scraper（多已失效）、harismuneer/Ultimate-Social-Scrapers。
- **Threads（🚫）**：Zeeshanahmad4/Threads-Scraper 及各瀏覽器自動化方案。
- **合規替代（✅）**：Meta Content Library（FB/IG/Threads，enclave 內、不可匯出）。
