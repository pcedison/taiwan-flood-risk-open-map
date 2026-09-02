# 2017／2026 歷史 coverage 缺口寫入

本 runbook 只處理 2026-09-02 已固化的 WRA／NSTC 全國官方來源查核。它不下載資料、
不建立事件，也不宣稱沒有淹水；2017 `not_published` 只代表列入 manifest 的全國來源
未發布該年資料，2026 `failed` 代表當年度資料尚不可用。

## 固定輸入契約

- manifest：
  `docs/data-sources/official/historical-coverage-gap-review-2026-09-02.json`
- SHA-256：
  `01ca620ee29d8a8815ff00fffb7894ef02e1acf36a01960b00e2d625b1598d3c`
- 目標：2017 × 22 格為 `not_published`；2026 × 22 格為 `failed`
- 寫入保護：只更新 `unassessed`；既有來源或人工查核結果一律保留
- 不變條件：`absence_is_safety_evidence=false`、
  `data_coverage_complete=false`

任何 byte、checksum、來源 revision 或實測數量改變都必須建立新的 manifest 與 code
review；不可直接修改 checksum 常數以接受未知輸入。

## 1. 無資料庫 dry-run

從 repository root 執行：

```powershell
$env:PYTHONPATH='apps/workers'
python -m app.main `
  --run-historical-coverage-gap-review `
  --historical-coverage-review-manifest docs/data-sources/official/historical-coverage-gap-review-2026-09-02.json `
  --historical-coverage-review-expected-sha256 01ca620ee29d8a8815ff00fffb7894ef02e1acf36a01960b00e2d625b1598d3c
```

必要輸出：`status=succeeded`、`mode=dry-run`、`network_allowed=false`、
`database_checked=false`、`target_cell_count=44`。
即使 worker runtime 已注入 `WORKER_DATABASE_URL` 或 `DATABASE_URL`，此命令也不得連線；
dry-run 只有明確傳入 `--database-url` 才進入唯讀對帳。

## 2. Staging 唯讀對帳

先確認 staging 已套用到 migration 0061，並已存在恰好 2012–2026 × 22 = 330 格。
加入 database URL 但不要加入 `--persist`：

```powershell
$env:PYTHONPATH='apps/workers'
python -m app.main `
  --run-historical-coverage-gap-review `
  --historical-coverage-review-manifest docs/data-sources/official/historical-coverage-gap-review-2026-09-02.json `
  --historical-coverage-review-expected-sha256 01ca620ee29d8a8815ff00fffb7894ef02e1acf36a01960b00e2d625b1598d3c `
  --database-url <staging-database-url>
```

保存 stdout JSON。`would_update_cell_count` 是仍為 `unassessed` 的目標格；
`preserved_cell_count` 必須等於已有來源結果、先前 review 或其他非 `unassessed` 狀態數。
唯讀對帳會使用 `REPEATABLE READ READ ONLY` transaction 取得一致快照，不要求 row-lock
權限；只有 `--persist` 才會鎖定 44 個目標格，避免來源刷新與 review 寫入競態。
此 operator workflow 的 database connect、transaction lock 與 statement 上限分別為
10 秒、5 秒與 30 秒；逾時必須回傳去敏感化的 structured failure，不可無限等待。

## 3. Staging 寫入

只有 manifest 與唯讀對帳經批准後才可執行：

```powershell
$env:PYTHONPATH='apps/workers'
python -m app.main `
  --run-historical-coverage-gap-review `
  --historical-coverage-review-manifest docs/data-sources/official/historical-coverage-gap-review-2026-09-02.json `
  --historical-coverage-review-expected-sha256 01ca620ee29d8a8815ff00fffb7894ef02e1acf36a01960b00e2d625b1598d3c `
  --persist `
  --historical-coverage-review-target-environment staging `
  --historical-coverage-review-approval-ack `
  --historical-coverage-review-production-ack `
  --database-url <staging-database-url>
```

用相同命令重跑一次，第二次的 `applied_cell_count` 必須為 0。不得把 database URL、
token 或其他 secret 放進稽核文件。target environment 只是稽核標籤，不能驗證
database URL 的身分，因此 staging 與 production 寫入都必須保留兩道 ack。

## 4. Coverage 對帳

```sql
SELECT
    count(*) AS cells,
    count(DISTINCT jurisdiction_code) AS jurisdictions,
    count(DISTINCT coverage_year) AS years,
    min(coverage_year) AS start_year,
    max(coverage_year) AS end_year
FROM historical_coverage_cells;

SELECT coverage_year, status, count(*) AS cells
FROM historical_coverage_cells
GROUP BY coverage_year, status
ORDER BY coverage_year, status;

SELECT status, count(*) AS cells
FROM historical_coverage_cells
GROUP BY status
ORDER BY status;

SELECT jurisdiction_code, coverage_year, status, source_adapter_keys,
       review_ref, status_reason
FROM historical_coverage_cells
WHERE coverage_year IN (2017, 2026)
ORDER BY coverage_year, jurisdiction_code;
```

矩陣必須是 `(330, 22, 15, 2012, 2026)`。2017／2026 合計 44 格都必須有來源 key、
review ref 與明確限制；若某格先前已有 `partial` 或其他非 `unassessed` 狀態，該格必須
原樣保留。完成 WRA 2012–2016、NSTC 2018–2020 凍結快照與 2021–2025 live snapshot
後，目標拼圖為 286 `partial`、22 `not_published`、22 `failed`；這仍代表 330 格資料
不完整，不是 330 格完整淹水事件登錄。

## 5. Production gate

只有 staging migration、來源 backfill、gap review 重跑冪等、API coverage/history smoke
與 rollback rehearsal 全通過後才能執行。production 命令改用 production database，
目標環境改為 `production`，並保留：

```text
--historical-coverage-review-production-ack
```

## 6. 錯誤分類隔離

若 manifest 之後被證明錯誤，不刪除 review 檔或稽核資訊。先停止 rollout，再以 exact
`review_ref` 把受影響格降級為 `failed`，保留來源 keys，並在 incident ref 說明原因。
transaction 提交前必須檢查目標數與 `RETURNING`：

```sql
BEGIN;

UPDATE historical_coverage_cells
SET status = 'failed',
    last_succeeded_at = NULL,
    review_ref = '<incident-or-change-ref>',
    status_reason = 'The prior gap classification was quarantined; re-review is required.',
    updated_at = now()
WHERE review_ref = '<exact-coverage-gap-review-ref>'
RETURNING jurisdiction_code, coverage_year, status;

COMMIT;
```

隔離後 API 必須繼續顯示 known gap，不得把 `failed` 解讀為零事件或低風險。
