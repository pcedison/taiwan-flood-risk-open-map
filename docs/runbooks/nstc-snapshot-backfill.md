# NSTC 2018–2022 凍結快照回填

本 runbook 只處理已審核的 data.gov.tw dataset 130016 凍結 CSV。工具預設
`dry-run`、不連網、不連資料庫；任何寫入都需要明確環境、review reference 與
兩道 ack。`target-environment` 只是稽核標籤，不能驗證 database URL 的身分，
因此 staging 與 production 寫入都必須提供 fail-safe production ack。

## 固定輸入契約

- 檔案：`apps/api/app/data/official/flood_disaster_points_130016.csv`
- 原始 bytes：216,986
- SHA-256：
  `9919ed734ca8cca4d0541ac88148f4909d47e1939d56199da34af7964ef72f5d`
- 原始列數：5,923（2018: 1,923；2019: 1,267；2020: 489；
  2021: 1,812；2022: 432）
- 正規化：5,919；拒收 4 筆，固定原因為
  `nstc_outside_taiwan_bounds`
- 穩定事件鍵：5,018；重複事件列 901 筆、529 組 key
- coverage 權威範圍：只允許 2018–2020。2021–2022 可保留 evidence revision，
  但不得覆寫較新的 live NSTC coverage check。

任一數字或 checksum 不同都必須停止。不可更新常數來迎合未知檔案；先建立新
revision、來源審查與獨立變更。

## 1. 無寫入 preflight

從 repository root 執行：

```powershell
$env:PYTHONPATH='apps/workers'
python -m app.main `
  --run-nstc-snapshot-backfill `
  --nstc-backfill-input apps/api/app/data/official/flood_disaster_points_130016.csv `
  --nstc-backfill-expected-sha256 9919ed734ca8cca4d0541ac88148f4909d47e1939d56199da34af7964ef72f5d
```

必須回傳 `status=succeeded`、`mode=dry-run`，並與上方固定契約完全相符。

## 2. Staging migration 與回填

先備份並確認 staging 部署 SHA、資料庫連線目標、恰好一份已審核且 active 的
22 縣市 boundary snapshot。依正常 migration runner 套用到 0061；`/ready`
必須仍為 healthy。

```powershell
$env:PYTHONPATH='apps/workers'
python -m app.main `
  --run-nstc-snapshot-backfill `
  --nstc-backfill-input apps/api/app/data/official/flood_disaster_points_130016.csv `
  --nstc-backfill-expected-sha256 9919ed734ca8cca4d0541ac88148f4909d47e1939d56199da34af7964ef72f5d `
  --persist `
  --nstc-backfill-target-environment staging `
  --nstc-backfill-review-ref <approved-change-ref> `
  --nstc-backfill-approval-ack `
  --nstc-backfill-production-ack `
  --database-url <staging-database-url>
```

保存 stdout JSON 作為 deployment evidence。不可保存或貼出完整 database URL。
寫入後的 reviewed raw snapshot 必須為 `retention_expires_at IS NULL`，metadata 的
`retention_policy` 必須是 `non_expiring_reviewed_frozen_snapshot`；不得由一般
180 天 raw retention job 清除。

## 3. Staging 驗證

以受控 SQL client 執行下列唯讀查詢；`<raw-ref>` 必須是 preflight 輸出的完整
content-addressed reference。

```sql
SELECT count(*) AS raw_revisions
FROM raw_snapshots
WHERE raw_ref = '<raw-ref>';

SELECT
    count(*) AS staging_rows,
    count(*) FILTER (WHERE validation_status = 'accepted') AS accepted_rows
FROM staging_evidence staging
JOIN raw_snapshots raw ON raw.id = staging.raw_snapshot_id
WHERE raw.raw_ref = '<raw-ref>';

SELECT
    count(*) AS evidence_rows,
    count(*) FILTER (
        WHERE occurred_at IS NULL AND observed_at IS NULL
    ) AS annual_null_timestamps,
    count(DISTINCT properties->>'source_record_key') AS stable_keys
FROM evidence
WHERE raw_ref = '<raw-ref>'
  AND ingestion_status = 'accepted';

SELECT coverage_year, status, count(*) AS cells, sum(record_count) AS records
FROM historical_coverage_cells
WHERE coverage_year BETWEEN 2018 AND 2022
GROUP BY coverage_year, status
ORDER BY coverage_year, status;

SELECT min(coverage_year), max(coverage_year), count(*)
FROM historical_coverage_source_checks
WHERE adapter_key = 'official.nstc.flood_disaster_points'
  AND review_ref LIKE 'nstc-backfill:v1:%';

SELECT adapter_key, status, items_promoted,
       parameters->>'audit_state' AS audit_state,
       parameters->>'terminal_phase' AS terminal_phase,
       parameters->>'promotion_count_complete' AS promotion_count_complete
FROM ingestion_jobs
WHERE job_key = 'worker.nstc_snapshot.backfill'
ORDER BY created_at DESC
LIMIT 1;
```

必要結果：1 個 raw revision、5,919 staging rows、5,919 accepted evidence rows、
5,919 筆 exact timestamps 皆為 NULL、5,018 個 stable keys、source checks 只涵蓋
2018–2020 且共 66 格。2018–2020 應為 `partial`；不得由此快照改動
2021–2022。

使用相同命令再執行一次：`new_evidence_count` 必須為 0，staging 仍為 5,919，
coverage counts 不變。這是進入 production gate 前的冪等驗收。

backfill audit 在 promotion 與 coverage 前必須先是 `running/pending`，所有下游完成
後才可成為 terminal；失敗則必須記錄已確認的 promotion count 與失敗 phase。
terminal row 的 `adapter_key` 必須為 NULL、linked `adapter_runs.adapter_key` 保留原
NSTC adapter，確保 backfill audit 可追溯但不會被 live ingestion readiness 選為
最新營運週期。正常命令返回後不得殘留該次 `running` audit。

## 4. Production gate

只有 staging migration、兩次回填與 API/history smoke 全部通過後才能執行。
production 命令必須將 target 改為 `production`，並保留：

```text
--nstc-backfill-production-ack
```

正式執行後重跑第 3 節所有唯讀查詢，並抽查 history API 最新優先排序、預設只
顯示最新一筆、展開後年份降冪，以及 `/health`、`/ready`、ingestion readiness。

## 5. 隔離／回復

不要刪除 raw snapshot 或 evidence。若驗證失敗，以 exact raw ref 隔離公開資料、
保留稽核列，並將 2018–2020 source check 標為 failed 後重算 coverage。下列
transaction 中的 `<rollback-review-ref>` 必須指向 incident/change record；commit
前先檢查每段 `RETURNING`/row count。

```sql
BEGIN;

UPDATE evidence
SET ingestion_status = 'rejected',
    properties = properties || jsonb_build_object(
        'backfill_quarantined', true,
        'backfill_quarantine_ref', '<rollback-review-ref>'
    ),
    updated_at = now()
WHERE raw_ref = '<raw-ref>'
  AND ingestion_status = 'accepted';

UPDATE staging_evidence staging
SET validation_status = 'quarantined',
    rejection_reason = 'operator_backfill_quarantine:<rollback-review-ref>'
FROM raw_snapshots raw
WHERE raw.id = staging.raw_snapshot_id
  AND raw.raw_ref = '<raw-ref>'
  AND staging.validation_status = 'accepted';

UPDATE historical_coverage_source_checks
SET status = 'failed',
    record_count = 0,
    attempted_at = now(),
    succeeded_at = NULL,
    review_ref = '<rollback-review-ref>',
    updated_at = now()
WHERE adapter_key = 'official.nstc.flood_disaster_points'
  AND coverage_year BETWEEN 2018 AND 2020
  AND review_ref LIKE 'nstc-backfill:v1:%';

WITH aggregate_checks AS (
    SELECT
        jurisdiction_code,
        coverage_year,
        COALESCE(
            sum(record_count) FILTER (WHERE status = 'succeeded'),
            0
        )::integer AS record_count,
        count(*)::integer AS checked_source_count,
        count(*) FILTER (WHERE status = 'succeeded')::integer
            AS successful_source_count,
        array_agg(adapter_key ORDER BY adapter_key) AS source_adapter_keys,
        max(attempted_at) AS last_attempted_at,
        max(succeeded_at) FILTER (WHERE status = 'succeeded')
            AS last_succeeded_at,
        max(review_ref) AS review_ref
    FROM historical_coverage_source_checks
    WHERE coverage_year BETWEEN 2018 AND 2020
    GROUP BY jurisdiction_code, coverage_year
)
UPDATE historical_coverage_cells coverage
SET status = CASE
        WHEN aggregate.successful_source_count > 0 THEN 'partial'
        ELSE 'failed'
    END,
    record_count = aggregate.record_count,
    checked_source_count = aggregate.checked_source_count,
    successful_source_count = aggregate.successful_source_count,
    source_adapter_keys = aggregate.source_adapter_keys,
    assessed_at = aggregate.last_attempted_at,
    last_attempted_at = aggregate.last_attempted_at,
    last_succeeded_at = aggregate.last_succeeded_at,
    review_ref = aggregate.review_ref,
    status_reason = CASE
        WHEN aggregate.successful_source_count > 0 THEN
            'Approved official source snapshots were checked; coverage remains partial until all reviewed sources are complete.'
        ELSE 'All attempted official historical source checks failed.'
    END,
    updated_at = now()
FROM aggregate_checks aggregate
WHERE coverage.jurisdiction_code = aggregate.jurisdiction_code
  AND coverage.coverage_year = aggregate.coverage_year;

COMMIT;
```

隔離後再次確認該 raw ref 的 accepted evidence 為 0，API 不再引用它，coverage
沒有 `complete`/`resolved_empty` 誤判，raw/staging/evidence 稽核列仍存在。
