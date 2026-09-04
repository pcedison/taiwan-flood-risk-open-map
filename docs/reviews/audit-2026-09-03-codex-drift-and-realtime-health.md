# 專案總體檢：Codex 一週偏移與全台即時感測器健康度（2026-09-03）

稽核者：Claude（fresh session，唯讀，未改動任何程式碼與 Zeabur 設定）
稽核對象：`origin/main@c75c114`（= 正式站 `/health` 的 `deployment_sha`）、正式站 floodrisk.cc 實測、GitHub PR/issue、本機測試套件。
實測時間：2026-09-03 10:54Z–11:12Z（台北 18:54–19:12）。

---

## 0. 一句話結論

產品的核心流程（輸入地址或點地圖 → 查半徑內感測器 → 顯示即時與歷史風險）**是通的、測試全綠、22 縣市都查得到 CWA 雨量**；
但 Codex 在 8/27 之後的一週內合併了約 110 個 PR、+23,320 行、20 支 migration，把三個嚴重問題帶進正式站：

1. **每次查詢 4–13 秒、回應快取 0 命中**（SDD 目標 1.5 秒 / 快取 0.5 秒）。根因是路由改走新寫的 `AssessmentService`，沒有接快取，而且在請求路徑上即時去 Google News／Bing 搜 `site:gov.tw` 網頁。
2. **歷史「極高」被垃圾證據撐起**：臺北的極高來自基隆市衛生局的登革熱防蚊公告，高雄／南投／澎湖來自疾管署「娜莉颱風水災後」衛教頁，桃園來自水務局 FAQ 頁。評分完全不看地點精度。
3. **「即時資料都不健康」是判定規則造成的，不是資料真的壞**：規則要求「全部測站都在時效內」才算 healthy，1,357 個雨量站永遠有幾個遲到，所以永遠 degraded；WRA IoW 淹水感測器全國停更 30 小時，**經上游 API 直接驗證是水利署那端停更**，卻被標成「最近一次背景更新僅部分完成」，讓監控連續 11 次紅燈，Codex 再花一週去「修監控」。

---

## 1. 初衷與規格（SDD）對照

| SDD 條文 | 規格要求 | 現況（實測／程式） | 判定 |
|---|---|---|---|
| 2.1 US-001/002/003 | 地址／點地圖／半徑查詢 | 前端流程可用：輸入「高雄市前鎮區中山二路2號」→ 候選清單 → 自動查詢 → 顯示結果（截圖見附件） | ✅ |
| 2.2 MVP 必做 | 官方氣象／水利 adapter、L2 新聞、風險 v0、證據列表、查詢熱度、admin dashboard、compose | 皆存在 | ✅ |
| 3.3 效能 `docs/PROJECT_SDD.md:122-131` | 單點查詢 P95 < 1.5 s；快取 P95 < 500 ms | 22 縣市實測 0.9–13.6 s，中位數約 8 s；同點連續兩次 `assessment_id` 不同、各 9.2 s（快取未命中） | ❌ 差 5–9 倍 |
| 3.3 策略 | 「長時間資料擷取改由 background jobs 執行」 | 請求路徑同步呼叫 Google News RSS／Bing RSS／gov.tw 頁面（`apps/api/app/domain/history/news_enrichment.py:38-43`、`:1129-1131`，經 `apps/api/app/api/services/official_history.py:33-41`） | ❌ |
| 8.1 Adapter rules `docs/PROJECT_SDD.md:612-618` | 先 raw snapshot → staging → 驗證後 promote，不直接寫正式 evidence | `OfficialRecentHistoryLookup` 在請求中搜到就 `upsert_public_evidence`（`official_history.py:44-47`） | ❌ |
| 9.3 歷史因子 `docs/PROJECT_SDD.md:664-672` | 官方災害紀錄、**重複**新聞證據、recency decay | 單筆 `admin_area` 精度的衛教頁即可讓歷史＝極高；`HISTORICAL_WEIGHTS["flood_report"]=35`（`apps/api/app/domain/risk/scoring.py:19-23`），評分器沒有任何 `location_precision` 邏輯 | ❌ |
| 2.3 明確不做 | 不將單一貼文直接判定為淹水事實 | 單一政府公告（甚至非淹水主題）直接成為 flood_report 證據 | ❌（精神上） |
| 12 前端 | 第一屏簡潔、狀態清楚 | 運維診斷（「對應版本：2026-08-24-v1-baseline…」「清冊校驗：981a36c7…」「分頁證明：5 頁」）已放在預設收合的 `<details>` 內（`apps/web/app/components/diagnostics-section.tsx`），但抽屜標題只寫「診斷資訊／技術明細」，沒說明是維運用；風險摘要區的「資料限制」直接顯示來源健康的內部訊息（見 §4）。**更正：本報告初稿誤判為直接展示，無頭瀏覽器的 `text` 指令會連收合內容一起抓出。** | ⚠️ |
| 18 開發階段 | Phase 0–6 逐階段驗收 | `PROJECT_STATUS.md` 已改用「全台資料債補救計畫」，Phase 架構不再被引用；`ROADMAP.md:12-13` 仍寫「not yet hosted production-beta-ready」但站台已對外營運 | ⚠️ 文件三角失真 |

**開放資料／政府資源取得是否正確：**

| 來源 | 端點／方式 | 授權與金鑰 | 正式站狀態 | 評語 |
|---|---|---|---|---|
| CWA 自動雨量站 O-A0002-001 | opendata.cwa.gov.tw（需 `CWA_API_AUTHORIZATION`） | GODL；Zeabur 已設金鑰 | 1,357 站、觀測 10:40Z–10:50Z，新鮮 | ✅ 正確 |
| WRA 河川水位（data.gov.tw 25768） | opendata.wra.gov.tw | GODL、免金鑰 | 361 站、新鮮 | ✅ 正確 |
| WRA IoW 淹水深度（142980） | `opendata.wra.gov.tw/api/v2/1b991bbb-…`（`apps/workers/app/adapters/wra_iow/flood_depth.py:31-33`） | GODL、免金鑰 | 1,355 站，全部停在 09-02 04:29Z | ✅ 端點正確；**上游停更**（見 §3） |
| NCDR CAP 警報 | 公開 active feed（#229 改為免會員金鑰） | GODL | healthy、目前無事件 | ✅ |
| Civil IoT STA 下水道水位 | sta.colife.org.tw RainSewer | 免金鑰 | 2,033/2,046 站、新鮮 | ✅ |
| Civil IoT STA 淹水感測／抽水站／閘門 | sta.colife.org.tw WaterResource | 免金鑰 | **自 2026-07-01 起 `run_failed`**（`/v1/ingestion-readiness`），上游回 HTTP 500 | ❌ 上游故障兩個月，無人處理 |
| CWA 豪雨警戒 W-C0033-003 | — | — | `disabled`（刻意） | — |
| 14 個地方政府 adapter（`apps/workers/app/adapters/local_*`） | 各縣市 API | `docs/data-sources/local/LICENSE_TERMS.md` 記載 8+ 來源授權衝突 | 全部未啟用；高雄／屏東回應中直接寫「地方政府機器介面尚未核准」（`apps/api/app/domain/assessment/repository.py:39-40`） | ⚠️ 合規未解 |
| NSTC 近五年淹水災點（130016） | 檔案匯入 | GODL | 進入歷史證據（point 精度） | ✅ |
| 「全臺政府機關淹水引註」`official.gov_tw.flood_citation` | **Google News RSS／Bing RSS 二手索引**＋抓 gov.tw 頁面驗證，另用 Google 未公開的 `batchexecute` 端點解碼轉址（`news_enrichment.py:39-41`、`:1404`） | 非開放資料；Google/Bing 未授權自動查詢 | hosted 預設啟用（`apps/api/app/core/config.py:168-171`） | ❌ 接近 SDD 8.2 的 L5「規避」灰區，且是延遲與垃圾證據的來源 |

---

## 2. 正式站 22 縣市實測（預設半徑 500 m，`time_context=now`）

| 縣市 | 即時/信心 | 歷史 | 雨量（站數@最近距離/最新觀測） | 河川水位 | IoW 淹水感測 | 秒數 |
|---|---|---|---|---|---|---|
| 基隆市 | 低/中 | 高 | 1@0.6km/10:40Z | 1@1.8km | 7@0.3km/**09-02 04:20Z** | 11.4 |
| 臺北市 | 低/中 | 極高 | 7@0.5km/10:40Z | 1@2.7km | 1@5.0km/09-02 03:56Z | 8.9 |
| 新北市 | 低/中 | 高 | 1@1.6km | 1@2.6km | 7@0.1km/09-02 04:25Z | 5.3 |
| 桃園市 | 低/中 | 極高 | 1@1.6km | — | 8@0.4km/09-02 | 8.7 |
| 新竹市 | 低/中 | 未知 | 1@2.6km | — | 9@0.7km/09-02 | 7.5 |
| 新竹縣 | 低/中 | 低 | 3@0.7km | 3@2.0km | 3@3.7km/09-02 | 8.0 |
| 苗栗縣 | 低/中 | 未知 | 3@0.6km | 1@1.8km | 6@0.4km/09-02 | 7.3 |
| 臺中市 | 低/中 | 中 | 1@1.1km | — | 8@0.9km/09-02 | 9.1 |
| 彰化縣 | 低/中 | 低 | 3@1.5km | — | 6@1.8km/09-02 | 9.5 |
| 南投縣 | 低/中 | 中 | 1@0.5km | 4@0.9km | 4@1.0km/09-02 | 7.1 |
| 雲林縣 | 低/中 | 中 | 2@1.6km | 1@3.3km | 6@0.1km/09-02 | 8.0 |
| 嘉義市 | 低/中 | 極高 | 1@2.4km/10:50Z | — | 8@0.2km/09-02 | 11.5 |
| 嘉義縣 | 低/中 | 極高 | 2@2.0km | — | 7@0.4km/09-02 | 11.4 |
| 臺南市 | 低/中 | 中 | 1@2.4km | 1@2.4km | 7@1.0km/**09-03 10:37Z**（臺南市府自有來源） | 12.3 |
| 高雄市 | 低/中 | 極高 | 1@0.3km | — | 8@1.3km/09-02 | 13.0 |
| 屏東縣 | 低/中 | 中 | 4@1.7km | — | — | 13.6 |
| 宜蘭縣 | 低/中 | 低 | 1@0.9km | 2@0.9km | 6@1.0km/09-02 | 7.4 |
| 花蓮縣 | 低/中 | 未知 | 2@2.1km | — | 1@3.4km/09-02 | 8.9 |
| 臺東縣 | 低/中 | 低 | 2@1.2km | 1@3.7km | 1@2.7km/09-02 | 7.3 |
| 澎湖縣 | 低/中 | 低 | 1@2.3km | — | — | 7.1 |
| 金門縣 | 低/中 | 未知 | 1@4.4km | — | — | 2.7 |
| 連江縣 | **未知**/中 | 未知 | 1@2.3km | — | — | 0.9 |

摘要：
- 雨量 22/22 有站且新鮮；河川水位 10/22 在 3 km 相關半徑內有站；IoW 感測器 18/22 有站但 17 個縣市全部停在 09-02 03:45Z–04:29Z。
- 22 個回應的 `data_freshness` 一致：`cwa.rainfall`／`wra.water_level`／`civil_iot.sewer_water_level` 皆 `degraded`（「目前已觀測站點僅部分在預期時間內更新」）、`wra_iow.flood_depth` `degraded`（「最近一次背景更新僅部分完成」）、`cwa.heavy_rain_warning` `disabled`、`ncdr.cap` `healthy`。
- 原始回應檔：`scratchpad/probe/<縣市>.json`（session scratchpad）。

---

## 3. 為什麼「每個縣市的即時感測器」無法正確查詢：分層根因

實測證明「查不到」不是單一原因，而是五層疊加：

| 層 | 現象 | 根因 | 證據 |
|---|---|---|---|
| A. 河川水位站稀疏 | 12 縣市顯示「本次查詢未取得可採用的即時水位或淹水感測觀測」 | 水位相關半徑 3 km（修法 B），河川站本來就稀；規則只要 `water_level` 不在半徑內、又沒有**新鮮**的官方 `flood_report`，就出這句 | `apps/api/app/domain/risk/scoring.py:286-310` |
| B. IoW 淹水感測器全國停更 | 17 縣市 IoW 停在 09-02 04:29Z，被 6 小時窗排除，於是 A 層條件也不成立 | **上游停更**：直接呼叫 `opendata.wra.gov.tw/api/v2/1b991bbb-…?format=JSON&limit=5000` 得 1,366 筆，`timestamp` 最大值 = `2026-09-02T12:29:42+08:00`（= 04:29:42Z），最小值 2026-04-07（有感測器 5 個月未回報） | 本次 curl 實測；adapter URL `apps/workers/app/adapters/wra_iow/flood_depth.py:31-33` |
| C. Civil IoT 淹水／抽水站／閘門 | 全國無「抽水站/水門狀態」訊號 | 三個來源自 2026-07-01 15:05Z 之後 `last_succeeded_at` 再無更新，`reason_code=run_failed`；PR #316 想把它們隔離，但 #316 是 merge 進 `codex/history-staging-rollout` 分支，**沒進 main** | `/v1/ingestion-readiness` 實測；`gh pr view 316 --json baseRefName` |
| D. 離島與地方介面 | 澎湖／金門／連江無任何淹水感測；連江即時直接「未知」；高雄／屏東多一句「地方政府機器介面尚未核准」 | 沒有感測器＋fail-closed 安全規則（`apps/api/app/domain/assessment/safety.py:64`）；地方 adapter 全部卡授權審查 | issue #71 亦列：淹水深度缺連江／澎湖／臺北 |
| E. 半徑與相關性 | 500 m 內幾乎永遠沒有站（22 縣市 500 m 內雨量站數皆 0） | 2026-06-15 已知的老問題（最近站 540 m > 500 m），修法 B 用相關半徑補救，但 UI 的「風險圈 500 公尺」與「感測站搜尋至 15 公里」並存，使用者難以理解 | 結果面板文字 |

結論：**沒有任何一層是「擷取程式寫壞」**。CWA、WRA 水位、下水道水位三條主幹都在正常擷取。

---

## 4. 為什麼「查得到的即時資訊都不健康」

### 4.1 健康判定規則本身保證永遠 degraded

`apps/api/app/domain/realtime/nearby_coverage.py:1131-1145`：

- `fresh_station_count >= station_count` → healthy（**全部**站都要在時效內）
- 否則只要有任何一站 fresh 或 delayed → `degraded`「目前已觀測站點僅部分在預期時間內更新」

1,357 個雨量站、361 個水位站、2,033 個下水道站，任何時刻都有幾站遲到或離線，這條規則在真實世界不可能成立。**這就是使用者看到的「每個來源都不健康」**，而資料本身（`observed_at` 10:40Z–10:50Z）是新鮮的。

### 4.2 上游停更被翻譯成「我方背景更新沒做完」

IoW 來源被標 `degraded/delayed`「最近一次背景更新僅部分完成」（`nearby_coverage.py:1021`，來自 worker 回報 `status == "partial"`）。實際上 worker 每輪都有跑，是水利署的 API 沒有新資料。訊息讓維護者去查自己的 pipeline，而不是去看上游。同時 `station_count` 把 4 月起就死掉的感測器也算進分母，使 4.1 的規則更不可能通過。

### 4.3 監控紅燈迴圈

- Hosted Monitoring 自 8/31 起每次排程都失敗（issue #289，11 次），唯一失敗項：`required source official.wra_iow.flood_depth freshness_state is failed`。
- Codex 的回應是 #318／#319「handle connection resets」、#320–#323 四個 `docs(status)` commit 記錄故障，以及 #311「include freshness failures in hosted alerts」——**把上游停更當成自家事故在寫狀態文件**，沒有一個 PR 去驗證上游。
- 8/27 我留下的記憶就警告過：`degraded-ok` 模式會遮蔽真正問題；這週證明監控語意仍然分不清「上游停更」「我方 pipeline 壞」「刻意停用」。

---

## 5. 效能：4–13 秒的來源

1. **回應快取是死碼**。路由 `apps/api/app/api/routes/public.py:573` 現在呼叫 `AssessmentService.assess`（`apps/api/app/api/services/assessment.py:64-94`，Codex 8/28 #243 起引入）。該類別完全沒有 `cache` 字樣；原本含 Redis 回應快取、profile fast-path 的 `public_risk.assess_risk`（`public_risk.py:244-250`）**已無任何呼叫者**（`grep -rn "assess_risk\b" apps/api/app` 只剩定義）。`RISK_ASSESSMENT_RESPONSE_CACHE_SECONDS` hosted 預設 120 秒（`config.py:172-176`）形同虛設。
2. **每次查詢即時搜尋網路**。`AssessmentService.assess` 在 `_history_needs_refresh` 為真時（DB 內沒有 `flood_report`/`road_closure` 事件就是真，`assessment.py:232-245`，也就是大多數地點）呼叫 `OfficialRecentHistoryLookup` → `search_taiwan_official_flood_citations`：對多組關鍵字打 Google News RSS 與 Bing RSS（`site:gov.tw`），對候選頁面再逐一抓取驗證，總預算 `min(HISTORICAL_NEWS_ON_DEMAND_TIMEOUT_SECONDS, 4.0)` 秒（`public.py:588-591`），每個 feed 最多 1.5 秒。加上 realtime bundle、nearby coverage 的多段 DB 查詢，就是 4–13 秒。
3. 金門 2.7 s、連江 0.9 s 反證：沒有行政區定位脈絡或沒東西可搜時就很快。

---

## 6. 歷史證據品質

22 縣市共回傳 18 筆歷史證據：`admin_area` 12、`polygon` 2、`point` 4。`admin_area` 的 12 筆全部來自 §5 的即時網路搜尋，例如：

| 縣市 | 歷史等級 | 證據標題（來源主機） | 問題 |
|---|---|---|---|
| 臺北市 | 極高 | 「大雨過後記得整理戶內外環境，確實清除積水容器，提醒民眾做好防蚊措施」（klchb.klcg.gov.tw，基隆市衛生局） | 登革熱防蚊公告；而且是基隆不是臺北 |
| 高雄市／南投縣／澎湖縣 | 極高／中／低 | 「娜莉颱風水災後」（at.cdc.gov.tw） | 疾管署衛教頁，娜莉颱風是 2001 年 |
| 嘉義縣 | 極高 | 「南部地區豪雨影響造成多處積水或淹水，疾管署表示全國消毒劑儲備量充足」（mohw.gov.tw） | 全國性新聞稿，非地點事件 |
| 桃園市 | 極高 | 「豪大雨造成一般道路積淹水時，應向哪個單位通報?」（wrb.tycg.gov.tw） | FAQ 頁 |
| 新竹縣 | 低 | 「迎戰巴威颱風！楊文科坐鎮防颱整備」（travel.hsinchu.gov.tw） | 防颱整備，非災情 |
| 彰化縣 | 低 | 「改善板本排水及護岸橋梁 解決大村、秀水淹水問題」（chcg.gov.tw） | 工程新聞 |

同一筆證據會被不同縣市重複引用（娜莉頁出現在 3 個縣市），代表地點比對只到縣市層級。這些證據以 `flood_report` 權重 35 進入評分，且評分不區分 `admin_area` 與 `point`。**使用者在高雄前鎮區看到「綜合風險：極高、地圖罩色深紅」，依據是一篇衛教頁。**這是購屋參考產品最不能犯的錯。

---

## 7. Codex 一週的行為模式（8/27 e4d8205 → 9/3 c75c114）

| 指標 | 數值 |
|---|---|
| commits | 160 |
| merged PR | #213–#323（約 110 個，全部 author = pcedison 帳號，codex bot 產出） |
| 變更 | 219 檔，+23,320 / −1,570 行 |
| 新增 migration | 20 支（0040–0059；8/28 一天 6 支） |
| 殘留 worktree | 22 個（`.worktrees/`，加主目錄共 23），本機分支 106、遠端分支 90 |
| 文件 | `docs/` 39,705 行；`PROJECT_STATUS.md` 396 行；`docs/superpowers/plans/` 新增 3 份計畫（899／380 行） |
| 程式碼規模 | api 46.8k、workers 73.7k、web 9.1k、scripts 10.5k、infra 13.5k、tests 15.1k 行 |

事故鏈：
- #312（9/2 08:09Z）merge 後正式站 502 超過 30 分鐘：migration 0060 在啟動交易內做整表改寫＋三個索引；#317 revert 並刪 0060。
- #314／#315／#316 隨後 merge 進 `codex/history-staging-rollout` 而非 main；#324（open，115 檔、+9,488）要把整套 15 年歷史功能再帶回來，PR 內文自列 5 個尚未完成的 release gate。
- #320–#323 四個 `docs(status)` commit 只是把 502 時間軸寫進 `PROJECT_STATUS.md`。

模式：**監控紅燈 → 改監控或寫狀態文件 → 再開新功能（全台 15 年歷史、ledger、readiness、registry）→ 新功能弄壞正式站 → revert → 再嘗試**。一週內沒有任何 PR 回到 SDD 的 Phase 驗收或效能目標。

本機驗證：API 779 passed／18 skipped、workers 1,205 passed／61 skipped、web 73 passed。**測試全綠，但測試沒有守住效能、快取、證據品質這三件事。**

---

## 8. 文件三角失真（scout 摘要）

- `docs/data-sources/official/official-source-catalog.yaml` 停在 2026-05-12；`config/source-registry.yaml`（63 個 adapter key，8/31 新增）另立一套 `enablement_decision`；`PROJECT_STATUS.md` 又是第三套說法（NCDR CAP 在 catalog 是 `disabled_by_default`，在 STATUS 是必要主幹）。
- `ROADMAP.md:12-13` 仍寫「not yet hosted production-beta-ready」，站台已對外營運三個月。
- `docs/PROJECT_WORK_PLAN.md:13-35` 自承其 Phase 敘述「不應取代 STATUS」，等於承認 Phase 架構已被放棄。

---

## 9. 建議（依優先序，全部可逆）

**P0 — 今天，不需改程式碼**
1. Zeabur 設 `OFFICIAL_NATIONWIDE_HISTORY_CITATIONS_ENABLED=false`。效果：請求路徑不再打 Google/Bing，延遲預期降到 2–5 秒，§6 的垃圾 `admin_area` 證據停止產生（已寫進 DB 的舊筆需另外清）。
2. 不要 merge #324；暫停 Codex 自動開 PR；`git worktree prune` 前先確認 22 個 worktree 沒有未提交的東西。

**P1 — 一週內，各自一個小 PR、可獨立驗證**
3. 把 `AssessmentService.assess` 接回 `public_response_cache`（或刪掉 `public_risk.assess_risk` 死碼，二擇一）。驗收：同點 120 秒內第二次查詢 `assessment_id` 相同、< 500 ms。
4. 健康判定改為「最近 N 站的新鮮比例」或「最近可用站新鮮即 healthy」，並把 `latest_observed_at` 超過 7 天的站排除在 `station_count` 之外（`nearby_coverage.py:1131-1145`）。驗收：CWA 雨量在正常日顯示 healthy。
5. IoW 停更：worker 比對上游最新 `timestamp` 與本地最新值，一致即回報 `upstream_stale`（新 cause），訊息改為「水利署尚未更新」，Hosted Monitoring 對此不紅燈。順帶把 Civil IoT flood/pump/gate 兩個月的 500 列為需向水利署反映的事項。
6. 歷史評分加入精度權重：`admin_area` 單筆上限「中」，且必須通過標題含災情關鍵字（排除「防蚊」「衛教」「FAQ」「整備」「改善」）；同一 URL 不得跨縣市重複計分。

**P2 — 回到規格**
7. 恢復 SDD Phase 驗收：以 §1 的表格為 checklist，每個 ❌ 各開一張 issue，Codex 只能領 issue 不能自創功能。
8. 合併 catalog／registry／STATUS 為單一真相來源，其餘改為產生物。
9. 前端診斷抽屜（已是預設收合）的標題改為明示「維運診斷，一般查詢不需要展開」；「資料限制」改用使用者語言（隨 P1 健康語意一起改善）。

---

## 附件

- 22 縣市原始回應：session scratchpad `probe/*.json`
- 上游 IoW 原始回應：scratchpad `iow_depth.json`（1,366 筆）
- 前端截圖：scratchpad `ui-home.png`、`ui-kaohsiung-result.png`
- 測試輸出：scratchpad `pytest-api.txt`、`pytest-workers.txt`、`web-test.txt`
- 文件摘要（scout）：本報告 §8
