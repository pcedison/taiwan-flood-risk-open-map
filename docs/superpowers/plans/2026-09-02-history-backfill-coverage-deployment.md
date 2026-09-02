# 歷史回補、330 格覆蓋與部署執行計畫

日期：2026-09-02（Asia/Taipei）

狀態：執行中

## 目標與不可跨越的界線

本計畫依 M0 至 M5 執行，目標是把近 15 年歷史資料與 Civil IoT 即時來源從
「程式可用」推進到「資料可稽核、部署可回滾、正式環境可持續驗證」。

- `audit_complete` 與 `data_coverage_complete` 必須分開；330 格離開
  `unassessed` 不代表政府已公開完整淹水事件。
- migration 只改 schema／契約；歷史資料只可由有 run ID、raw snapshot、checksum、
  dry-run 與對帳結果的 backfill job 寫入。
- `not_published` 表示經審核後找不到合格公開來源，不表示當年沒有淹水。
- 單一外部來源故障不得阻擋其他來源，但不得被轉譯成零筆或低風險。
- 不在 production 首次執行未於 production snapshot clone 驗證過的資料命令。

## 已確認基線

- 正式站 2026-09-02 回報 deployment SHA
  `2f5d36820f10733294a0d846c7ed2a8064feb773`，`/health` 與 `/ready` 為 `ok`。
- 正式 coverage 仍是 2018–2026：198 格中 110 `partial`、88 `unassessed`。
- migration 0059／0060 與 2012–2026 動態窗口尚未部署。
- 凍結 NSTC CSV 共 5,923 列；年份 2018–2022；SHA-256
  `9919ed734ca8cca4d0541ac88148f4909d47e1939d56199da34af7964ef72f5d`；
  5,919 列正規化成功、4 列因座標在臺灣合理範圍外而拒收。5,919 列形成
  5,018 個穩定事件鍵，901 筆為保留 revision 但公開查詢需去重的重複事件列。
- 2026-09-02 WRA historical live run：1,224 fetched、1,075 normalized、157
  rejected；事件年份止於 2016，沒有 2017。
- 同日 Civil IoT live smoke：sewer 1,947 normalized／21 縣市；flood sensor、
  pump、gate 的目前查詢皆為 HTTP 500。

## M0：收斂目前的 15 年歷史契約修繕

交付：

1. 將 migration 0059／0060、歷史 API、coverage 契約、Web lazy history 與稽核文件
   收斂為可 review 的 commit／PR。
2. rebase 最新 `origin/main`，不覆蓋主線的 monitoring 修正。
3. 執行 API、Worker、Web、PostGIS、OpenAPI、migration、lint、typecheck 與 E2E。
4. PR 只合併程式契約，不在 merge 階段寫入 production 歷史資料。

退出門檻：PR checks 全綠、review 無未處理 P0/P1、合併後正式站仍維持舊行為直到
受控 migration rollout。

## M1：NSTC 2018–2022 可稽核 backfill

新增專用 CLI，預設 dry-run，必須顯式提供：

- 輸入 CSV 路徑與預期 SHA-256；
- 允許年份 2018–2022；
- operator／review ref；
- `--persist` 才可寫入；
- production 必須另加明確確認旗標。

每次執行輸出 immutable manifest：輸入列數、逐年筆數、normalized／rejected、穩定鍵
碰撞、縣市歸屬、raw ref、ingestion/promotion run ID、前後 evidence 與 coverage 計數。

回補可保存 2018–2022 revision，但 coverage 權威只補 2018–2020；2021–2022 已有較新
live snapshot。必須有測試證明舊 snapshot 不會覆蓋新版 source check。

退出門檻：5,923 列全部可對帳、沒有靜默遺失、重跑冪等、rollback 可依 run/raw ref
隔離且 profile 重建結果一致。

## M2：2012–2026 年度查核與 330 格

來源處理矩陣：

| 年份 | 主要證據 | 目標狀態 |
| --- | --- | --- |
| 2012–2016 | WRA historical KML | 來源已查核；保留大尺度調查限制 |
| 2017 | 全國與 22 縣市官方來源 review | `partial` 或有 review ref 的 `not_published` |
| 2018–2020 | 凍結 NSTC snapshot | 受控 backfill 後 `partial` |
| 2021–2025 | NSTC live revisions | 維持較新 snapshot 權威 |
| 2026 | 當年度持續 ingestion／來源 review | `partial`，不得宣稱年度完整 |

新增受控 coverage assessment 命令，禁止直接手改 330 格。每個非 `unassessed` cell
必須能追到 source check 或 immutable review ref。

退出門檻：恰好 22 × 15 = 330 格、每年 22 格、`unassessed=0`、
`missing_persisted=0`；known gaps 繼續存在且 `data_coverage_complete` 不得被誤設為 true。

## M3：Civil IoT 分流恢復

### Sewer

先於 staging 單獨啟用 sewer，驗證 upstream total、完整分頁、station manifest、
座標、同一 run promotion、freshness、retention、記憶體與磁碟；連續觀察至少 48 小時。

### Flood sensor／pump／gate

用最小查詢矩陣定位 HTTP 500：base entity、`$top=1`、`$count`、filter、expand、
latest observation、nextLink。只有能證明是查詢形狀造成時才修改 adapter；必要時改成
兩階段抓取與較小分頁。若最小官方查詢仍 500，留下 incident evidence 並維持
failed/disabled，不將 upstream 事故包裝成程式修復。

退出門檻：sewer staging 48 小時穩定；另外三類來源要嘛通過相同門檻，要嘛有正式
unavailable/incident 證據與不影響 WRA IoW 骨幹的降級行為。

## M4：Staging migration 與驗收

1. 從 production backup 建立隔離 staging clone，完成 scratch restore drill。
2. 停 staging scheduler，執行 0059／0060／0061並記錄鎖定時間與 row counts。
3. 部署 worker，執行 M1/M2 dry-run，再執行受控 persist 與 profile rebuild。
4. 驗證 NSTC 年度列的 exact timestamps 為 NULL、穩定鍵無異常碰撞、歷史分頁固定於
   assessment 建立時間。
5. 執行 22 縣市各 3 個 canary（都市、低窪／沿海、偏遠）共 66 點，以及 desktop/mobile
   E2E、410、cursor、文字溢出與來源連結。
6. 演練 app SHA rollback、backfill quarantine 與 profile rebuild；schema 為 additive，
   不以 down migration 作首選回滾。

退出門檻：所有驗證證據有 timestamp、SHA、run ID 與 operator；沒有資料對帳差異或未解釋
效能退化。

## M5：正式部署與觀察

部署順序：

1. 確認合併後 `origin/main`、CI/checks 與 production backup。
2. 暫停 scheduler；套用 0059／0060／0061。
3. 先部署 worker，執行已在 staging 驗證的資料命令與 330 格對帳。
4. 部署 API，再部署 Web；恢復 scheduler。
5. `/health`、`/ready`、ingestion readiness 必須回報同一完整 SHA。
6. 執行 deployment smoke、strict public-risk smoke、66 canary 與 desktop/mobile browser
   smoke。
7. 觀察七天來源 cadence、retention、queue、PostGIS、Redis 與真正 `schedule` 事件；manual
   dispatch 只能作診斷，不能取代 scheduled evidence。

退出門檻：七天內沒有未處理 required-source freshness／pipeline 事故；若外部來源仍不可用，
公開結果持續明示缺口且不誤判安全。

## 每次進度回報格式

- 程式：commit、PR、checks、merged SHA。
- 資料：raw ref、run ID、input/output counts、reject reasons、checksum。
- Coverage：總格數、各 status 數、audit completion、data completion、known gaps。
- 即時來源：adapter、upstream total、normalized、freshness、manifest checksum、soak 時數。
- 部署：staging/prod SHA、migration version、smoke、rollback evidence、觀察期。
