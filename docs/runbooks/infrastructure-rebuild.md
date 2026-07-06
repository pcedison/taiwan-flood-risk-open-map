# 從零重建正式環境 Runbook

## 目的

這份 runbook 假設讀者**從未接觸過本專案**，原作者（pcedison）已無法聯絡，且手上只有這份 GitHub repo。目標是把 `floodrisk.cc` 背後的正式服務從零重建起來。

它不重複既有 runbook 的內容，只補「從零開始」缺的前段——帳號怎麼申請、專案怎麼建立。實際的部署設定細節、環境變數清單、資料庫還原指令，全部連結到既有 runbook。

配套文件：[SUCCESSION.md](../../SUCCESSION.md)（哪些帳號目前只有原作者持有、中斷後的影響）、
[docs/runbooks/github-actions-secrets.md](github-actions-secrets.md)（GitHub Actions secrets 現況）。

**重要提醒**：以下涉及外部網站（Zeabur、CWA、Civil IoT、Cloudflare、網域註冊商）的操作步驟，只寫到「入口網址＋要取得的東西」這個層級，不假裝知道對方網站目前確切的按鈕位置或表單欄位——外部網站的介面會隨時間改版。凡標示「以官方網站現況為準（2026-07 撰寫）」的地方，表示本文撰寫時尚未實際重跑過這個流程，接手者應以當下的官方網站畫面為準。

---

## (a) 前置帳號註冊

在建立 Zeabur 專案之前，先準備好以下帳號。全部可由任何人自助申請，不需要原作者協助。

### Zeabur（託管平台）

- 入口：`zeabur.com`
- 取得：使用 GitHub 帳號登入即可建立新帳號，不需要額外審核。
- 以官方網站現況為準（2026-07 撰寫）。

### CWA 中央氣象署開放資料平台（氣象觀測金鑰）

- 入口：`opendata.cwa.gov.tw`
- 取得：註冊一個免費會員帳號後，在會員後台申請 API 授權碼（對應 `.env.example` 的 `CWA_API_AUTHORIZATION`）。免費，審核通常是自動或短時間內完成。
- 用途：雨量、潮位等即時觀測資料（見
  [docs/runbooks/civil-iot-live-enablement.md](civil-iot-live-enablement.md) 的「API keys / access」段落）。
- 以官方網站現況為準（2026-07 撰寫）。

### Civil IoT（水利署/國網中心 SensorThings 平台）

- 入口：`ci.taiwan.gov.tw`
- 取得：註冊會員帳號。多數 SensorThings（STA）端點本身為公開存取，不一定需要 token；WRA 開放資料平台的 `WRA_API_TOKEN`（`.env.example`）目前是選填欄位。
- 用途：水位、感測器、抽水站等即時資料來源（見
  [docs/runbooks/civil-iot-live-enablement.md](civil-iot-live-enablement.md)）。
- 以官方網站現況為準（2026-07 撰寫）。

### Cloudflare（Turnstile，公民回報防機器人挑戰）

- 入口：`dash.cloudflare.com`
- 取得：註冊/登入 Cloudflare 帳號後，進入 Turnstile 產品頁面，建立一個新的 site，會拿到一組 sitekey（前端用）與 secret key（後端驗證用，對應 `.env.example` 的 `USER_REPORTS_CHALLENGE_SECRET_KEY`）。免費。
- 現況提醒：截至本文撰寫時，`USER_REPORTS_ENABLED=false`（`.env.example`），公民回報功能尚未對外開放，前端也還沒有整合 Turnstile 小工具（sitekey 尚未接進 `apps/web`）。除非要開放這個功能，否則這一步可以先跳過。
- 以官方網站現況為準（2026-07 撰寫）。

### 網域註冊商（任選）

- 若要延續使用 `floodrisk.cc`：需要取得該網域現有註冊商帳號的存取權（見
  [SUCCESSION.md](../../SUCCESSION.md) 第 3 項，目前無文件化的註冊商資訊，這是本清單最大的未知數）。
- 若改用新網域：任何主流網域註冊商皆可，註冊後把 DNS 指向新的 Zeabur 服務（見下方「(d) 網域與 DNS」）。

---

## (b) Zeabur 專案建立

先完整讀過這兩份既有 runbook 再動手，本節只補它們沒寫的「從零建立專案」前段，不重複其部署細節：

- [docs/runbooks/deploy-zeabur.md](deploy-zeabur.md) — 完整的服務設定、環境變數矩陣、health check、rollback。
- [docs/runbooks/zeabur-single-service-env.md](zeabur-single-service-env.md) — 單容器 Preview 模式的環境變數複製清單。

從零開始的前段步驟：

1. 用上一節取得的 Zeabur 帳號登入 `zeabur.com`。
2. 建立一個新專案（`deploy-zeabur.md` 的「GitHub Connection」一節建議命名 `flood-risk-staging` 或 `flood-risk-production-beta`；正式環境不強制要求延用原本的 `flood_risk` 專案名稱，那只是原作者當初的命名）。
3. 依 [docs/runbooks/deploy-zeabur.md](deploy-zeabur.md) 的「Quick Path: Single Zeabur Service」一節，從 GitHub repo（本 repo 的 fork 或原 repo）新增服務，設定 Dockerfile 部署、Root Directory 留在 repo 根目錄。
4. 依 [docs/runbooks/zeabur-single-service-env.md](zeabur-single-service-env.md) 逐一填入環境變數，把上一節取得的 `CWA_API_AUTHORIZATION`（與選用的 `WRA_API_TOKEN`、`USER_REPORTS_CHALLENGE_SECRET_KEY`）填進去。
5. 若要啟用正式資料庫/排程/背景擷取，依 [docs/runbooks/deploy-zeabur.md](deploy-zeabur.md) 的「Environment Variables」與「Future Service Split」一節逐步加上 PostgreSQL、Redis、MinIO 等服務。

不要把 `.env.example` 裡的預留空白值直接複製進 Zeabur——空白值代表「等到有權限的維運者核准後才在 Zeabur 或密鑰管理系統中設定」，這是既有 runbook 已經明確寫過的規則，不要繞過。

---

## (c) 資料還原

若手上有既有的正式資料備份（或需要在新環境驗證資料庫可以正常運作），完整流程見既有的
[docs/runbooks/backup-restore-drill.md](backup-restore-drill.md)，涵蓋：

- `pg_dump`/`pg_restore` 的備份建立與封存檢查。
- scratch 資料庫的還原驗證（不可直接還原進正式資料庫）。
- Zeabur 平台代管離站備份的私有證據欄位（`artifact_ref`、`download_metadata_ref` 等）。
- 事故還原大綱（Incident Restore Outline）。

若沒有任何既有備份（例如原作者的 Zeabur 帳號完全無法存取，見
[SUCCESSION.md](../../SUCCESSION.md) 第 2、8 項），代表資料需要從零開始重新累積——資料庫 schema 由 `infra/migrations/*.sql` 重建，但歷史觀測資料與公民回報資料無法復原。這是本文件誠實記載的限制，不假裝有魔法救援路徑。

---

## (d) 網域與 DNS

1. 部署完成後，Zeabur 會提供一個預設網域，例如 `https://your-service.zeabur.app`（見
   [docs/runbooks/deploy-zeabur.md](deploy-zeabur.md) 的「Create The Zeabur Service」一節）。
2. 若要延續使用 `floodrisk.cc`：在該網域的 DNS 設定中，新增一筆 CNAME（或依 Zeabur 當下要求的記錄型別）指向 Zeabur 提供的端點。具體記錄型別與主機名稱以 Zeabur 專案的「網域」設定頁面當下顯示的指示為準（以官方網站現況為準，2026-07 撰寫）。
3. TLS 憑證由 Zeabur 平台自動簽發與更新，不需要手動申請或上傳憑證。
4. DNS 生效通常需要數分鐘到數小時（視 TTL 與註冊商而定），生效後用 `curl -fsS https://floodrisk.cc/health` 確認新環境已經接手。

---

## (e) 驗證清單

部署完成後，依序確認：

1. **`/health` 的 `deployment_sha`**：
   ```bash
   curl -fsS "https://<你的網域>/health"
   ```
   確認回傳的 `deployment_sha` 對應你剛部署的 commit，且 `status` 為 `ok`。

2. **`/v1/risk/assess` 冒煙**：對一個已知座標送出風險查詢，確認回傳合理的風險等級與 `score_version`，且沒有 500 錯誤。可參考
   [docs/runbooks/zeabur-single-service-env.md](zeabur-single-service-env.md) 與
   [docs/runbooks/deploy-zeabur.md](deploy-zeabur.md) 的「Smoke checks after deploy」一節。

3. **admin sources 新鮮度**：若已設定 `ADMIN_BEARER_TOKEN`，呼叫 `/admin/v1/sources` 確認來源新鮮度狀態；操作方式見
   [docs/runbooks/monitoring-freshness-alerts.md](monitoring-freshness-alerts.md) 與 `scripts/ops-source-freshness-check.ps1`。

4. **資料庫 migration**：確認 `infra/migrations/*.sql` 已套用（單容器模式下，設定 `DATABASE_URL` 後啟動腳本會自動套用未紀錄的 migration；細節見
   [docs/runbooks/zeabur-single-service-env.md](zeabur-single-service-env.md)）。

5. **GitHub Actions 監控是否連動**：確認
   [docs/runbooks/github-actions-secrets.md](github-actions-secrets.md) 中列出的 workflow 現況，決定是否需要設定對應的 repo secrets 才能讓 hosted monitoring 正常運作。

完成以上五項，代表新環境已經具備最低限度的「可服務、可觀測」狀態；正式上線前仍應完整跑過
[docs/runbooks/production-readiness.md](production-readiness.md) 的完整檢核清單。
