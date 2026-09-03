# 即時淹水與近 15 年歷史查核稽核（2026-09-01）

## 結論

專案的基本方向正確：它把即時觀測、歷史事件、潛勢圖資、來源健康與附近感測覆蓋分開，
且對來源失敗採 fail-closed，不把「查不到」描述成「沒有淹水」。但 2026-09-01 的正式環境仍不能
宣稱全台即時與近 15 年歷史資料完整：歷史 coverage ledger 原先只有 2018–2026，198 格全部未
resolved；Civil IoT 四類來源失敗；WRA 與 NSTC 歷史匯入 degraded。

本次修改把產品契約統一為「依 assessment 建立時間、Asia/Taipei 曆年計算的動態 15 年窗口」；
在本稽核日即為 2012–2026。NSTC 滾動快照的歷史版本仍保留供稽核，公開查詢則依穩定事件鍵只
顯示最新 revision。歷史事件按年度、事件時間與 UUID 穩定降冪排列，預設只顯示最新一筆，其餘
由使用者展開後才分頁載入。這些修改不會把尚未回補的年份假裝成完整。

## 正式環境與來源實測

檢查時間約為 2026-09-01 22:00–23:00（Asia/Taipei）。正式站部署 SHA 為
`14ffc808af31ef5ecc281917160a4aa8af667348`；資料庫與 Redis readiness healthy。

| 類別 | 來源與實測 | 能回答什麼 | 主要限制 |
| --- | --- | --- | --- |
| 雨量 | CWA 自動雨量；正式環境 operational；官方資料每 10 分鐘更新 | 附近近期降雨壓力 | 不是淹水深度，也不能單獨證明現地淹水 |
| 河川水位 | WRA 水位 API HTTP 200，最新觀測 `2026-09-01T22:50:00+08:00` | 河川測站水位與警戒距離 | 官方說明為未品管原始值，傳輸或儀器可能異常 |
| 淹水深度 | WRA IoW API HTTP 200，最新觀測 `2026-09-01T22:25:00+08:00` | 測站附近淹水深度 | 測站點值不代表整個查詢半徑；正式匯入狀態 degraded |
| 官方警戒 | NCDR active CAP HTTP 200，共 147 entries，最新 `2026-09-01T22:34:00+08:00` | 作用中官方災防警示 | 警示範圍不等於查詢點已有量測淹水 |
| 下水道／設施 | Civil IoT flood sensor、pump、gate API HTTP 500；RainSewer Things HTTP 200，但抽樣 streams 無 observations | 現階段不能提供可依賴的即時證據 | 必須維持 unavailable／degraded，不能用零筆推論安全 |
| 近期歷史點位 | NSTC dataset 130016 HTTP 200，8,838 rows，年份 2021–2025 | 年度與座標層級的官方災點 | 僅滾動近 5 年；無精確日期、深度、地址；不定期更新 |
| 大規模歷史淹水 | WRA historical KML：1,224 fetched、1,075 normalized、157 rejected，涵蓋 2004–2016 | 官方調查過的大規模淹水範圍 | 不涵蓋所有局部、都市道路、低窪農漁區事件；不定期更新 |
| 官方網頁補查 | 台灣政府 HTTPS 直接來源 citation lookup | 補充地點相關的官方事件頁 | 搜尋索引不是完整事件登錄；無結果不能推論未淹水 |

官方來源說明：

- CWA 自動雨量：https://data.gov.tw/dataset/9177
- WRA 即時水位：https://data.gov.tw/dataset/25768
- WRA IoW 淹水深度：https://data.gov.tw/dataset/142980
- NSTC 近 5 年淹水災點：https://data.gov.tw/dataset/130016
- WRA 歷史淹水範圍：https://data.gov.tw/dataset/25770

## 近 15 年完整性

產品窗口以查詢建立時間的臺灣曆年為準，涵蓋當年與前 14 個完整／進行中曆年；在 2026-09-01
為 2012–2026。現有官方機器來源可形成的已知拼圖：

- WRA historical KML：2012–2016 有資料。
- 專案保存的舊 NSTC 快照：2018–2022。
- 2026-09-01 的 NSTC live snapshot：2021–2025。
- 2017 尚無已核准的全台機器資料來源；2026 的歷史事件也不能在年度尚未結束時宣稱完整。

因此目前不能宣稱 15 年全時段完整。migration 0059 將 coverage ledger 擴為 `22 × 15 = 330` 格，
所有新增格維持 `unassessed`，直到來源檢查產生可追溯結果。專案內舊 NSTC 2018–2022 快照仍需
透過受控 backfill 匯入正式 evidence 與 coverage source checks；本次 migration 不暗中寫入事件。

## 已修正的結構性問題

1. 歷史窗口改成以 assessment 建立時間與 `Asia/Taipei` 計算的動態 15 個曆年；2027 元旦會自動
   切換為 2013–2027，worker 同步補出新年度 coverage cells。
2. 年度型資料新增 `event_year`、`temporal_precision=year`；NSTC 不再製造 12 月 31 日事件時間，
   raw、staging、promotion、repository、API 與 UI 均保留年度精度。
3. 感測器歷史由「每站只取最新正值」改為 query-time episode aggregation：低於 3 cm 或超過 6
   小時間隔會切開事件，並回傳開始／結束、最高深度、觀測數與演算法版本。
4. NSTC raw revisions 仍留存，但 public query 與 profile scoring 依 `source_record_key` 去重，
   明確優先採用 `snapshot_authority=live`，再於同一 authority 內取最新 revision；較晚執行的
   reviewed frozen backfill 不會遮蔽 live provenance。連續 sensor cycles 也不再重複灌高
   profile 歷史分數。
5. 新增 `/v1/history/{assessment_id}`，直接依 assessment 地點與半徑查完整歷史，不受 scorer
   preview 上限限制；資料與 15 年窗口凍結在 assessment 建立時間，採 assessment-bound opaque
   keyset cursor，且區分 404、410 與 503。
6. 歷史 repository／API 故障不再回空陣列冒充「查無紀錄」。
7. coverage summary 新增 `audit_complete`、`data_coverage_complete` 與
   `known_gap_cell_count`；`not_published` 可表示稽核完成，但不會被說成資料完整。
8. risk response 的附近涵蓋新增 `home_jurisdiction_code`，前端用 canonical code 取得該縣市 15 年
   coverage，不再以縣市名稱猜測。
9. 前端未展開時只顯示最新一筆；展開後才逐頁載入、依 ID 去重，可重試，且新搜尋會取消舊請求。
   年度資料只顯示「某年（年度資料，來源未提供確切日期）」。
10. readiness schema gate 升到 migration 0060，避免新版程式連上缺少事件語意欄位的資料庫。

## 本次實作驗證

- API unit／contract：795 passed，19 skipped。
- Worker unit：1,208 passed，61 skipped。
- PostGIS acceptance：歷史 repository 19 passed；coverage writer／ledger 3 passed。
- 舊資料語意回填 acceptance：1 passed；0060 可重跑，年度型資料不再保留合成日期。
- Migration：空 PostGIS 成功套用 60 個 migration；第二次執行 `applied=0, skipped=60`。
- OpenAPI、migration manifest、Ruff、API／Worker mypy：通過。
- Web：75 unit passed；typecheck、lint、production build 通過；desktop 與 Pixel 7 的目標 E2E 共
  12 passed，涵蓋 lazy load、cursor、重試、coverage、年度精度與 overflow。
- 上述為本地修繕驗證；尚未 commit、push 或部署，因此不代表正式站已套用。

## 安全與可靠性

- 公開 geocode 與 risk assessment 皆有 Redis-backed rate limit；hosted Redis 不可用時 fail closed。
- 外部 evidence URL 在前端只接受 HTTP/HTTPS，避免危險 URI scheme。
- API 與 worker 依賴的 `pip-audit`、web production `npm audit` 均未發現已知漏洞；GitHub code
  scanning、Dependabot、secret scanning alerts 均為 0（2026-09-01 檢查）。
- Python dependency 使用版本範圍而非完整 lock，仍有可重現建置風險；這是供應鏈改善項，不是本次
  發現的可直接利用漏洞。
- Civil IoT 與歷史 coverage 不完整時，結果必須繼續顯示資料缺口，不得降低成「低風險」或
  「沒有淹水」。

## 仍需完成的工作

1. 對保存的 2018–2022 NSTC 快照執行一次可稽核 backfill，並以年度、來源、座標穩定鍵去重。
2. 為 2017 尋找可合法、自動化、可驗證的官方來源；若不存在，將 22 個縣市格標成有 review
   evidence 的 `not_published`，而不是 `complete` 或零事件。
3. 修復或正式停用 Civil IoT 四類來源；在此之前維持 degraded/failed。
4. 讓目前窗口的 330 個 coverage cells 逐格離開 `unassessed`，並為每格保留來源、檢查時間與
   review ref；跨年後只更新 active 15 年窗口，不刪除較舊稽核紀錄。
5. 部署前先在 staging 執行 0060 並抽查既有 NSTC 年度列的 timestamp 為 NULL、穩定鍵沒有異常
   碰撞，再進行正式資料庫備份與 rollout。
6. 部署後以真實地點做 desktop/mobile smoke test，確認最新一筆、展開順序、410 過期流程、文字
   溢出及來源連結。
7. 若 production explain/metrics 顯示歷史感測 episode 的 query-time 聚合成本過高，再以有 watermark
   與演算法版本的物化表取代；在完成對帳前不得刪除 raw cycles。
