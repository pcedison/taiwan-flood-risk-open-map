# 永續性總體檢與 10~15 年傳承路線圖（2026-07-06）

- 稽核基準：`origin/main` @ `62f008d`（PR #115），分支 `audit/sustainability-2026-07-06`
- 稽核方法：五個獨立平行深度稽核（安全、架構/程式碼品質、效能、UI/UX、開源永續治理），每項 finding 皆附 `檔案:行號` 與具體失敗情境
- 目標：讓本服務（台灣淹水風險開放地圖，floodrisk.cc）能在原作者離開後，被有志者與企業從 GitHub fork/接手並持續維運 10~15 年
- 詳細報告（本文件的證據來源，均在 `docs/reviews/`）：
  - [安全稽核](audit-2026-07-06-security.md)（9 findings：High 2 / Medium 2 / Low 5，Critical 0）
  - [架構與程式碼品質](audit-2026-07-06-architecture.md)（問題 11 項，其中 1 項併案處理 + 4 正面聲明）
  - [效能稽核](audit-2026-07-06-performance.md)（5 findings + 6 面向乾淨）
  - [UI/UX 與易用性](audit-2026-07-06-uiux.md)（21 findings：阻斷 3 / 摩擦 11 / 打磨 7）
  - [開源永續治理](audit-2026-07-06-open-source-sustainability.md)（致命 4 / 嚴重 6 / 建議 5）

---

## 一、執行摘要

**這個專案的程式碼體質良好，但「傳承結構」是目前最大的生存風險。**

好消息（五路稽核交叉確認的資產）：

1. **零 Critical 安全漏洞**：無 hardcoded secrets、admin 驗證實作正確（`secrets.compare_digest`、fail-closed）、SQL 全面參數化、無 SSRF 面、無 XSS 面。
2. **文件紀律是強項**：抽查 ADR-0010/README/程式碼五個關鍵聲明全部同步；技術債（CWA/WRA 雙軌解析）是「寫在 ADR 裡的明債」而非隱性地雷。
3. **依賴健康**：Python/Node 全部現代主線、無 EOL 套件；workers 刻意極簡（stdlib urllib），供應鏈面積小，十年好維護。
4. **早期的 async 阻塞與巨型檔案問題已修**：路由全為 sync `def` 走 threadpool、空間索引與查詢對齊、前端 bundle 精簡。
5. **誠實的降級設計**：四態新鮮度模型（fresh/degraded/stale/failed）、來源 gate、no-network 誠實性 smoke——這是風險溝通產品最難得的底子。

壞消息（會讓專案死掉或傷害公眾信任的結構性缺口）：

1. **Bus factor = 1**：377 commits 100% 同一人、唯一 collaborator、main 無分支保護、無 SECURITY.md/CODEOWNERS/行為準則——有志者想接手也無門可入。
2. **正式環境無法被任何其他人重建**：Zeabur 專案、CWA/WRA 金鑰、網域 DNS、Turnstile 的取得/交接流程零文件。
3. **隱私實作違反自家已核可的 ADR-0006**：精確座標＋原始搜尋文字被無限期落地（`location_queries`），對公益服務是重大信任風險。
4. **限流設計會在淹水尖峰自我 DoS**：所有公開流量被 hash 進同一個 bucket（全站共用 30 次/分），服務最被需要的時刻最容易失效。
5. **風險溝通有阻斷級缺陷**：免責聲明英文標題且預設收合、無官方災防出口連結、時間戳不顯年份、紅綠風險色對色盲者幾乎不可辨。

---

## 二、整合優先序（去重後的行動清單）

各項標註來源報告代號：SEC=安全、ARCH=架構、PERF=效能、UX=介面、SUS=永續。

### P0 — 生存與信任（目標：2 週內完成）

| # | 行動 | 來源 | 規模 |
|---|---|---|---|
| P0-1 | `location_queries` 停存 `raw_input` 與精確座標，只留粗化桶；加入 retention 清理 | SEC H-2 | S/M |
| P0-2 | 限流改真實客端 IP：uvicorn `--proxy-headers --forwarded-allow-ips=127.0.0.1`＋XFF 取最右不可信段 | SEC H-1 | S |
| P0-3 | 免責聲明改純中文標題、預設展開；風險結果卡重複一行警語；加「緊急請撥 119／水利署防災資訊」出口連結 | UX B1+F11 | S |
| P0-4 | 治理五件套：`SECURITY.md`、`CODE_OF_CONDUCT.md`、`CODEOWNERS`、Issue/PR 模板；main 開分支保護（required review + CI 綠燈） | SUS F1 | S |
| P0-5 | Python lockfile（uv/pip-tools）＋ CI 強制檢查（比照 Node 側既有標準） | SUS S3 | S |
| P0-6 | README 加可照抄的 Quick Start（含 `docker compose --profile tools run --rm migrate`）；CONTRIBUTING 補本機開發指引 | SUS S1 | S |

### P1 — 韌性與可接手性（目標：1~2 個月）

| # | 行動 | 來源 | 規模 |
|---|---|---|---|
| P1-1 | API 導入 `psycopg_pool.ConnectionPool`（共用池，5~10 連線），一請求復用連線 | PERF 1 | M |
| P1-2 | 「從零重建基礎設施」runbook：Zeabur 專案建立、CWA/WRA 金鑰申請網址與步驟、網域/DNS、Turnstile 註冊 | SUS F2 | M |
| P1-3 | 拆分單容器三程序拓撲：依既有 Phase 1 計畫把 ingestion scheduler 與 API/Web 分服務 | PERF 4 | M |
| P1-4 | Web 安全標頭（CSP、frame-ancestors、nosniff、HSTS）＋容器非 root 使用者 | SEC M-1+M-2 | S |
| P1-5 | 無障礙阻斷修復：form-error 加 `role="alert"`、section 標題改語意 `<h2>`、radius 選項補 focus 樣式 | UX B2+B3+P5 | S |
| P1-6 | 色盲可辨性：地圖圈選依等級改邊框線型/圖示；側欄風險值文字上色；時間戳一律含年份 | UX F3+F4+F2 | S/M |
| P1-7 | GitHub Actions secrets 現況文件化（或誠實反映未設定）；actions 釘 commit SHA | SUS F3 + SEC L-3 | S |
| P1-8 | Dockerfile 內嵌 100+ 行 entrypoint 抽成獨立 `entrypoint.sh`；做一次非 Zeabur 平台部署 dry-run 並记錄 | SUS S4 | M |

### P2 — 結構健康（目標：3~6 個月）

| # | 行動 | 來源 | 規模 |
|---|---|---|---|
| P2-1 | 治理三件套（`local_source_action_plan/coverage/request_packets.py` 約 3500 行）移出 `domain/`、切模組、dict 換 TypedDict/dataclass | ARCH F1-A | L |
| P2-2 | CWA/WRA 雙軌解析加共用 fixture 契約測試（同一原始回應餵兩邊、斷言關鍵欄位一致，schema drift 在 CI 爆） | ARCH F2-A | M |
| P2-3 | `RiskAssessmentDependencies` 40 欄位 DI 瘦身至 <10 個真 seam（DB/網路/時鐘/快取） | ARCH F4-A | M |
| P2-4 | geocoder 非索引化 OR 子句改 pg_trgm 或移除 substring fallback（開放資料表將成長至數十萬列） | PERF 2 | M |
| P2-5 | retention 擴充 `flood_report`/`flood_warning`（目前無限成長）；staging 寫入改批次 | PERF 3+5 | S |
| P2-6 | 35+ 地方政府資料來源授權盤點，建立 `docs/data-sources/local/LICENSE_TERMS.md` | SUS F4 | M |
| P2-7 | UX 摩擦批次修：geocode 候選清單（limit 5）、限流訊息帶秒數、載入回饋、白話文案、手機版搜尋框前置 | UX F5~F9 | M |
| P2-8 | 肥路由下沉（public.py/admin.py）、web `risk-display.ts` god-module 拆檔、adapter 範式統一＋「新增縣市來源」教學 | ARCH F1-C/E+F3-B | M |

### P3 — 錦上添花（機會出現時做）

dark mode（UX P2）、MapLibre 控制項在地化（UX P3）、`--muted` 對比加深（UX F10）、ADR-0003 補決策理由（SUS S5）、ADR 新增流程指引（SUS S6）、`packages/` 空殼降級或補實（ARCH F3-A）、defusedxml 縱深防禦（SEC L-5）、FastAPI docs 生產環境關閉（SEC L-4）。

---

## 三、10~15 年永續路線圖

永續的本質不是「程式碼永遠不壞」，而是**任何一個環節壞掉時，都有人有權限、有知識、有文件可以修**。

### 第 0~3 個月：把門打開（P0＋P1）

- 完成上表 P0/P1。核心成果：**陌生人能上手、服務能扛尖峰、隱私與警語對得起公眾信任**。
- 邀請至少一位第二 collaborator（備援 admin），啟用 GitHub Discussions，標記 3~5 個 `good first issue`。

### 第 3~12 個月：結構健康與社群基礎（P2）

- 完成上表 P2。核心成果：**新貢獻者的邊際成本下降**（domain 乾淨、DI 輕、契約測試護欄、縣市 adapter 有樣板可抄）。
- 建立 `SUCCESSION.md`（傳承檔案，見第四節）並每年演練一次。
- 考慮將 repo 從個人帳號轉移到 GitHub organization（例如 `taiwan-flood-risk`），organization 有多 owner 機制，天然解 bus factor；個人 repo 轉 org 保留 stars/issues/redirect。

### 第 1~3 年：治理成熟

- **多維護者**：目標 2~3 位有 merge 權的維護者，關鍵路徑（scoring、evidence pipeline、migrations）由非原作者完成一次獨立審查（回應 SUS S2 對 AI 高速產出的人類複審疑慮）。
- **年度節奏**（寫進 runbook，設 GitHub Actions 排程提醒）：
  - 每年一次依賴大版本升級窗（Python/Node/Next/PostGIS），配合 lockfile 與 CI。
  - 每年一次備份還原演練（既有 `backup-restore-drill.ps1`）與「非 Zeabur 平台部署」演練。
  - 每年一次資料來源健檢：35+ 地方 API 是否還活著、授權是否變更、金鑰是否臨期。
  - 每年一次 `SUCCESSION.md` 更新與傳承演練（讓第二維護者實際操作一次部署）。
- **財務透明**：在 README 記載月度營運成本（節點、網域、儲存），讓潛在接手者/贊助者能評估承接負擔。可考慮 GitHub Sponsors 或 OpenCollective 承接社會資源。

### 第 3~15 年：低頻穩態

- 專案進入「維運為主、演進為輔」：靠 CI 護欄（契約測試、validator、smoke）讓低頻維護仍然安全。
- 技術選型的長壽假設已經良好：PostgreSQL/PostGIS、FastAPI、標準 Dockerfile、stdlib HTTP——全是 10 年尺度上最不易消失的選擇。最大變數是**外部資料源**與**託管平台**，兩者的對策都是「文件化的可替換路徑」（P1-2、P1-8、每年演練）。
- 若社群成形，逐步把「決策權」也交出去：ADR 流程開放提案（SUS S6）、roadmap 公開討論、原作者退居 emeritus。

### 里程碑檢核（每階段的機械可查驗收）

| 時間 | 驗收條件 |
|---|---|
| 3 個月 | 陌生人照 README 30 分鐘內本機跑起來；`gh api branches/main/protection` 非 404；ADR-0006 合規（DB 抽查無精確座標）；壓測 40 req/min 不會全站 429 |
| 12 個月 | 第二 collaborator 完成一次獨立部署；CWA/WRA 契約測試在 CI；`domain/` 下無 ops 治理模組；非 Zeabur 部署演練有紀錄 |
| 3 年 | ≥2 位活躍維護者；連續兩年完成年度節奏四項演練；外部貢獻者 PR 曾被合併 |
| 10 年+ | 任一維護者可在不聯絡原作者的情況下完成：部署、金鑰輪替、依賴升級、資料源替換 |

---

## 四、SUCCESSION.md 應涵蓋的傳承單點（待建）

→ 已落地為 [SUCCESSION.md](../../SUCCESSION.md)（2026-07-06）

以下每一項目前都只存在原作者一人手上，是「原作者明天消失，服務就斷」的單點。`SUCCESSION.md` 不放機密值，只放「這個東西是什麼、在哪裡、如何重新取得、誰有備援權限」：

1. GitHub repo admin 權限（解法：org 化或第二 admin）
2. Zeabur 帳號與專案 `flood_risk`（解法：重建 runbook＋團隊帳號）
3. 網域 floodrisk.cc 的註冊商、續約、DNS（解法：文件化＋自動續約＋備援聯絡人）
4. CWA 開放資料平台金鑰（申請流程：opendata.cwa.gov.tw，免費）
5. WRA / Civil IoT 會員金鑰（申請流程待文件化）
6. Cloudflare Turnstile secret（公民回報功能）
7. GitHub Actions secrets（現況待釐清，見 SUS F3）
8. 資料庫備份的存放位置與還原程序（既有 runbook，需確認接手者可執行）

---

## 五、本次稽核統計

- Findings 總計 **61 項**（去重前）：SEC 9、ARCH 11、PERF 5、UX 21、SUS 15
- 正面確認 **10+ 項**：零 Critical、零 hardcoded secret、SQL/SSRF/XSS 乾淨、文件同步、依賴健康、async 已修、索引對齊、快取 fail-open、tmp/test-results 未進 repo、產碼零 TODO/stub
- 主要交叉印證：單容器三程序拓撲（PERF 4 = SUS S4 的部署面）、CWA/WRA 雙軌（ARCH F2-A = SUS R2，ADR-0010 已承認）、Dockerfile 內嵌腳本（PERF 4 註 = SUS S4）
