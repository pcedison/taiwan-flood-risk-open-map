# 開源永續性稽核報告 — Taiwan Flood Risk Open Map

稽核對象：`pcedison/taiwan-flood-risk-open-map`，分支 `audit/sustainability-2026-07-06`（= `origin/main` @ `62f008d`，2026-07-06）
稽核視角：三年後第一次接觸此 repo 的陌生接手者，且原作者已無法聯絡。
稽核方法：直接讀取 repo 內檔案、`git log` 統計、GitHub API（協作者、分支保護、secrets、repo 功能開關）；ADR/SDD、runbooks、資料來源授權文件由三個獨立 subagent 全文讀取後彙整。

---

## 總結回答（驗收條件要求的明確結論）

**今天 fork 這個 repo 的陌生人，能否在不聯絡原作者的情況下把服務完整跑起來？**

- **本機開發環境（docker compose）：勉強可以，但有摩擦。** `docker-compose.yml` 與 `.env.example` 相當完整（400+ 行環境變數含註解），可以拉起 postgres/redis/minio/api/web。但「必須先跑資料庫 migration」這個關鍵步驟只寫在 `.github/workflows/ci.yml:150`（`docker compose --profile tools run --rm migrate`），README 和 CONTRIBUTING 都沒提——陌生人若只照 README 做，會卡在 API 因資料表不存在而炸掉，且不知道要去哪裡找答案。
- **正式環境（公開服務）：不行。** 現有服務綁在原作者名下的 Zeabur 專案 `flood_risk`（`docs/runbooks/production-beta-ops-evidence-2026-05-06.md:4`），repo 內沒有任何文件教「如何從零申請 Zeabur 帳號、重建這個專案」；也沒有任何文件教「如何向氣象署（CWA）/水利署（WRA）申請 API 金鑰」（只說「CWA 金鑰是免費的」卻沒給申請網址與流程，見 `docs/runbooks/civil-iot-live-enablement.md:25`）；沒有網域/DNS 交接記錄；沒有 Cloudflare Turnstile 帳號註冊說明。這些都是「必須聯絡原作者，或自己從頭摸索政府網站」才能取得的東西。
- **法律面：本機開發不會有事，但若要重新對外提供服務，35+ 個地方政府資料來源完全沒有授權條款文件**，陌生人無法判斷能不能快取/轉發這些資料。

---

## 缺口清單（按致命度排序）

### 致命（會讓專案死掉 / 陌生人直接放棄）

**F1. Bus factor = 1，且沒有任何治理備援。**
- `git log`：377 個 commit，100% 來自同一人（Marcus Hseih / `pcedison@gmail.com`，含一個別名 email，仍是同一人）。
- GitHub API 確認：repo 唯一 collaborator 是 `pcedison`（admin 權限）；0 forks、0 stargazers、Discussions 未啟用、僅 5 個 open issues。
- `main` 分支**沒有開任何分支保護**（`gh api .../branches/main/protection` → 404 Not protected）：沒有必要審核、沒有 required status checks，任何有 push 權限的人可直接推到 main。
- 缺少 `CODEOWNERS`、`SECURITY.md`、`CODE_OF_CONDUCT.md`、`.github/ISSUE_TEMPLATE/`、`PULL_REQUEST_TEMPLATE.md`（皆確認不存在，只在 `node_modules` 第三方套件裡找到同名檔案，與本專案治理無關）。
- 接手者情境：想貢獻的人不知道找誰審 PR、遇到安全漏洞不知道通報管道、沒有行為準則可循——這是「有志者想接手也無從加入」的結構性障礙。
- 建議：立即建立 CODEOWNERS/SECURITY.md/CODE_OF_CONDUCT.md/PR 模板；main 開啟分支保護（至少 required PR review + CI 綠燈）；主動找第二個 collaborator 做備援 admin。

**F2. 正式環境的帳號/憑證取得流程完全沒有文件。**
- Zeabur：`docs/runbooks/deploy-zeabur.md:65-66` 假設「你已經在 Zeabur 建好專案」，`production-readiness.md:208` 只說「每個 Zeabur 專案要有一個 named owner」卻沒說新人怎麼拿到這個 owner 身份。`production-beta-ops-evidence-2026-05-06.md:4` 直接寫死專案名 `flood_risk`，等於明示「這是原作者的個人專案」，沒有任何「專案被刪除後如何重建」的復原程序。
- CWA API 金鑰：`deploy-zeabur.md:132`、`zeabur-single-service-env.md:91`、`civil-iot-live-enablement.md:25-28` 都只寫「填入你的 CWA token」或「CWA 是免費金鑰」，沒有申請網址（`opendata.cwa.gov.tw`）、註冊步驟、審核時間。
- WRA API 金鑰：`production-readiness.md:156` 只寫「source owner 才需要」，完全沒說如何判斷或如何申請——比 CWA 更沒有文件。
- 網域/DNS：全 repo 沒有任何檔案提到網域註冊商、DNS 供應商、或網域續約/轉移安排。`deploy-zeabur.md:79` 只提到 Zeabur 自動配的 `*.zeabur.app` 網域。
- Cloudflare Turnstile（公民回報功能要用）：`public-reports-governance.md:29-30` 規定要設定 `USER_REPORTS_CHALLENGE_SECRET_KEY`，但沒有註冊 Turnstile、取得 secret key 的步驟。
- 接手者情境：陌生人拿到 repo 原始碼與 `.env.example`，但完全無法把「公開服務」重新架起來，因為所有金鑰與帳號的取得路徑都要自己重新摸索或聯絡原作者。
- 建議：新增一份「從零建立基礎設施」runbook，涵蓋 Zeabur 帳號/專案建立、CWA/WRA 金鑰申請網址與流程、網域註冊與 DNS 設定、Turnstile 註冊。

**F3. GitHub Actions secrets 目前是空的，與 README 聲稱的「hosted monitoring」現況矛盾。**
- `gh secret list --app actions` 回傳空清單，但 `.github/workflows/` 內有 `hosted-monitoring.yml`、`hosted-monitoring-schedule-watchdog.yml`、`github-actions-secret-readiness-watchdog.yml` 等明顯依賴 hosted 憑證的 workflow。
- 接手者情境：陌生人無法判斷這些 workflow 現在到底是真的在跑（用什麼憑證？）還是名存實亡；`github-actions-secret-readiness-watchdog.yml` 這個「檢查 secret 是否就緒」的 workflow 本身存在，暗示團隊知道這個風險，但沒有文件說明目前 secrets 實際存放位置（環境層級？外部 secret manager？）。
- 建議：在 `docs/runbooks/` 明確記載目前 Actions secrets 的存放位置與交接方式，或若真的尚未設定，在 README 的 Production Status 表中誠實反映。

**F4. 35+ 個地方政府資料來源完全沒有授權條款文件。**
- 中央政府資料（CWA/WRA/Civil IoT/地理編碼）授權文件完整：明確引用「政府資料開放授權條款 1.0」與 data.gov.tw 資料集編號（`docs/data-sources/official/official-source-catalog.yaml:9-159`）。
- 但新北、基隆、桃園、台中、高雄、宜蘭、金門 KWIS 等 35+ 個地方政府 API adapter（見 `docs/data-sources/local/taiwan-local-realtime-water-source-matrix.md:51-87`）**完全沒有對應的授權/使用條款文件**——只有技術端點說明，沒有法律面的再散布/快取權利記載。
- 接手者情境：新維護者不知道能不能繼續快取/轉發這些地方政府資料，一旦某個地方政府要求下架或提告，接手者毫無準備依據可查。
- 建議：逐一盤點 35+ 個地方來源的使用條款，建立 `docs/data-sources/local/LICENSE_TERMS.md` 索引；在此之前應視為法律未審閱狀態。

### 嚴重（大幅提高接手成本）

**S1. README 沒有可執行的「Quick Start」步驟，關鍵的 migration 指令只藏在 CI 設定裡。**
- `README.md` 全文 274 行，開頭直接進入「Core Decisions」「Planned Runtime」與一大段落落落長的狀態說明，從未出現「1. clone 2. cp .env.example .env 3. docker compose up 4. 跑 migration」這種新人可以照抄的步驟。
- 唯一完整寫出 `docker compose --profile tools run --rm migrate` 指令的地方是 `.github/workflows/ci.yml:150`（CI 用途），一般開發者不會去讀 CI YAML 找開發步驟。
- `CONTRIBUTING.md` 僅 21 行，只講 SDD/work package 流程，完全沒有「如何啟動本機環境、如何跑測試、程式風格」等新人真正需要的內容。
- 建議：在 README 加入明確 Quick Start 段落，含 migrate 步驟；CONTRIBUTING.md 補上本機開發指引。

**S2. 專案極年輕、由 AI subagent 高速產出，人類複審深度未知。**
- `git log`：第一個 commit 2026-04-28，稽核日 2026-07-06，即整個專案只存在約 9 週，377 個 commit 全部一人所寫。
- 大量分支命名為 `codex/*`（超過 40 個），`CONTRIBUTING.md:17-20` 明文寫「Subagent Rule」；`docs/PROJECT_SDD.md` 第 19 節「Subagent Work Package Matrix」大量使用「work package」「integration owner」等 AI 協作框架術語（非一般人類貢獻者慣用語彙）。
- 接手者情境：文件品質看起來詳盡（ADR/SDD/runbook 齊全），但這種產出速度（9 週 377 commits）意味著實際程式碼是否被人類逐行理解過存疑；文件與程式碼行為之間可能存在原作者自己都沒發現的落差。這不是文件缺失的問題，而是「文件詳盡度」與「人類實際理解深度」可能脫鉤的隱性風險。
- 建議：對關鍵路徑（risk scoring、evidence pipeline、資料庫 migration 順序）安排一次由非原作者的人類進行的獨立程式碼審查，驗證文件與實作一致。

**S3. Python 依賴沒有 lockfile，長期可重現性風險。**
- `apps/api/pyproject.toml`、`apps/workers/pyproject.toml` 全部用 `>=` 浮動下限（如 `fastapi>=0.115`、`psycopg[binary]>=3.2`），沒有 `requirements.txt` 鎖檔、沒有 `uv.lock`/`poetry.lock`。
- 對比之下 Node 側 (`apps/web`) 有 `package-lock.json`，且 `ci.yml:78-84` 明確要求「Require frontend dependency lockfile」否則 CI 失敗——這個嚴謹度沒有同等套用到 Python 側。
- 接手者情境：10-15 年後重新 build 這個 image，`pip install -e` 會抓到當時最新的 fastapi/psycopg 主版本，很可能與現有程式碼不相容，而且沒有任何鎖定版本可回退比對。
- 建議：導入 `uv`/`pip-tools` 產生 lockfile，並在 CI 加入等同 Node 側的「lockfile 必須存在」檢查。

**S4. Zeabur 專案綁死具體帳號，但容器化路徑本身尚稱可攜。**
- 好消息：`Dockerfile` 是標準多階段 Dockerfile（node builder + python:3.12-slim runtime），沒有使用任何 Zeabur 專屬語法，理論上可搬到任何支援 Dockerfile 部署的平台（Render/Railway/Fly.io/自架 VPS + Docker）。
- 但入口腳本以 100+ 行 `printf` 內嵌方式寫在 `Dockerfile:88-179+`，而非獨立可測試的 `entrypoint.sh`，對新人除錯/修改的難度偏高。
- 建議：把內嵌腳本抽成獨立 `entrypoint.sh` 檔案並加測試；在 runbook 中明確驗證一次「部署到非 Zeabur 平台」的 dry-run，把可攜性從「理論上可以」變成「有證據可以」。

**S5. ADR-0003（FastAPI + PostGIS + Redis + MinIO 選型）幾乎沒有決策理由。**
- 相較其他 9 份 ADR 都清楚寫出「為什麼選這個、放棄了什麼替代方案」，`docs/adr/0003-fastapi-postgis-backend.md` 的 Context 只有約 5 行，純粹陳述選型結果，沒有比較 Django/Flask/Node backend 或其他空間資料庫的取捨過程。
- 接手者情境：若未來要評估是否換掉某個核心元件（例如 MinIO 換成純 S3/R2），無法從 ADR 得知當初排除其他方案的原因，只能重新從頭評估。
- 建議：補寫 ADR-0003 的 Context/Alternatives 段落。

**S6. `docs/adr/README.md` 沒有教「如何新增一份 ADR」。**
- 只列出 ADR 索引表與格式欄位，沒有說明新 ADR 的審核流程、編號規則、由誰核准。
- 建議：補上「如何提出新 ADR」的簡短指引。

### 建議（錦上添花）

- **R1.** 在 `docs/runbooks/` 新增「基礎設施重建」runbook：Zeabur 帳號/專案建立、資料庫/Redis/MinIO/R2 設定、Turnstile 註冊，一次涵蓋 F2 提到的所有取得流程。
- **R2.** README 的「Production pending checklist」已自陳「Converge the duplicated CWA/WRA parsing logic... between the API realtime bridge and worker adapters」（README.md:255-259）——這是原作者自己承認的技術債，建議列入下一個接手者的優先待辦，而非等它繼續累積。
- **R3.** 建立 `docs/data-sources/local/LICENSE_TERMS.md`，逐一盤點 35+ 地方政府來源授權條款（呼應 F4）。
- **R4.** 若未來預期多人維護，及早在 GitHub Settings 開啟 Discussions、補齊 Issue/PR 模板，降低外部貢獻者的參與門檻（目前 0 forks/0 stars/Discussions 未開，社群基礎幾乎是零，treaty 前的「先把門打開」工作都還沒做）。
- **R5.** LICENSE 為標準 Apache-2.0（完整、未經竄改），NOTICE 檔案內容正確但簡短（僅提及 OSM/ODbL 與政府資料開放授權條款，未附具體版權年份/持有人行），非致命，但可補上標準 Apache NOTICE 格式的版權聲明行以求形式完整。

---

## 各檢查面向覆蓋說明

1. **上手體驗**：本機 docker compose 路徑技術上可行，但 README/CONTRIBUTING 未寫出含 migration 的完整步驟（見 S1）；`.env.example` 本身品質良好，變數皆有註解。
2. **授權與法律**：軟體授權（Apache-2.0）與中央政府資料授權完整；地方政府資料授權是最大缺口（F4）；GDELT/PTT/Dcard/使用者回報等來源皆被程式碼層面的 flag 正確擋在 disabled 狀態，且文件承認「法律審閱中」，這部分處理得宜。
3. **治理結構**：CODE_OF_CONDUCT/SECURITY.md/CODEOWNERS/Issue-PR 模板全數缺席；bus factor 明確為 1（F1）。
4. **知識保存**：11 份 ADR 中 10 份理由清楚，僅 ADR-0003 偏薄弱；`docs/PROJECT_SDD.md`（1748 行）涵蓋資料庫/API/評分模型設計理由完整，但沒有「若原作者離開」的明文情境規劃；24 份 runbook 對「怎麼操作」寫得很細，但對「怎麼從零取得帳號/憑證」完全空白（F2）。
5. **廠商鎖定**：容器化路徑本身可攜（標準 Dockerfile），但 Zeabur 專案/帳號本身無交接文件；MinIO 本機/R2 正式環境的替換路徑在 ADR-0002 有記載，算是處理得較好的一項。
6. **外部依賴壽命**：中央政府 API 有明確的四態新鮮度模型（fresh/degraded/stale/failed）與降級行為設計（README.md:77-87），但金鑰申請流程本身沒有文件（見 F2）。
7. **長期技術風險**：Node 側鎖檔嚴謹（CI 強制要求），Python 側完全沒有鎖檔（S3）；Python/Node 版本散落在 Dockerfile/docker-compose.yml/ci.yml 三處硬編碼（3.12 / node 22），未集中管理，但目前尚一致，非致命。
8. **傳承機制缺口**：Zeabur 專案、CWA/WRA 憑證、網域/DNS、GitHub repo admin 權限、Turnstile 帳號——全部是原作者一人持有且無交接文件的單點；`git log`/GitHub API 均證實目前無第二人有任何層級的存取權。

---

## 附錄：關鍵佐證數據

- Commits: 377 筆，100% 同一作者（`pcedison@gmail.com` + 同一人的別名 email）。
- 專案存在時間：2026-04-28 至 2026-07-06（稽核日），約 9 週。
- GitHub collaborators：僅 `pcedison`（admin）。Forks: 0。Stars: 0。Discussions: 未啟用。Open issues: 5。
- `main` 分支保護：未設定（404 Not protected）。
- GitHub Actions secrets（`gh secret list --app actions`）：空清單。
- 缺少檔案：`CODE_OF_CONDUCT.md`、`SECURITY.md`、`CODEOWNERS`、`.github/ISSUE_TEMPLATE/*`、`PULL_REQUEST_TEMPLATE.md`（repo 根目錄與 `.github/` 皆確認不存在）。
- `docs/adr/` 共 11 個檔案（10 份決策 ADR + 1 份 README 索引）；`docs/runbooks/` 共 24 個檔案。
