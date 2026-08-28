# NCDR 鄉鎮警戒邊界審核與啟用

本流程只接受 NCDR CAP `Taiwan_Geocode_103` 的 368 筆官方鄉鎮界。它與
22 縣市的 `realtime_jurisdiction_boundaries` 完全分離，避免把單一鄉鎮警戒
錯誤放大成整個縣市。沒有唯一、完整、checksum 相符且已審的 active snapshot
時，worker 會保留 raw／rejection audit，但不發布 public evidence。

## 已審來源

- 官方文件：<https://alerts.ncdr.nat.gov.tw/web/developer/cap-docs>
- 官方壓縮檔：<https://alerts.ncdr.nat.gov.tw/web/StaticFile/Document/town_103.shp(utf8).zip>
- geocode profile：`Taiwan_Geocode_103`
- source revision：`town_103cap-v2`
- 筆數：`368`
- archive SHA-256：`26a0e1d3496847905a5d4956cf29369a932febba546bf165d9923085aa3ed9bb`
- canonical manifest SHA-256：`e8a80808dcb4203a545e44b0707c85c2dbe9d8db3f57f556a883cc9864d8d3cb`

manifest 由 PostgreSQL `jsonb_agg` 依 geocode 排序，每筆內容為
`[geocode, county, town, English name, geometry SHA-256]`，再對 UTF-8 JSONB
文字取 SHA-256。正式環境仍必須自行重算並與審核值逐字相符，不能直接信任
文件中的值。

## 匯入候選 snapshot

先由受控環境下載官方檔案至暫存路徑。資料庫 URL 必須由 secret store 注入，
不得貼入 issue、PR、log 或 shell history。

```bash
python infra/scripts/import_ncdr_alert_area_boundaries.py /tmp/ncdr-town-103.zip \
  --database-url "$WORKER_DATABASE_URL" \
  --source-revision town_103cap-v2 \
  --dry-run
```

dry run 必須輸出 368 筆與上述兩個 checksum。確認後移除 `--dry-run`；腳本會
建立 `is_active=false`、`is_complete=false` 的候選 snapshot，且不會改變線上
查詢。

## 審核與啟用

以匯入輸出的 snapshot UUID 執行：

```bash
python infra/scripts/activate_ncdr_alert_area_boundary_snapshot.py \
  --database-url "$WORKER_DATABASE_URL" \
  --snapshot-id "<candidate-uuid>" \
  --approved-archive-sha256 "26a0e1d3496847905a5d4956cf29369a932febba546bf165d9923085aa3ed9bb" \
  --approved-manifest-sha256 "e8a80808dcb4203a545e44b0707c85c2dbe9d8db3f57f556a883cc9864d8d3cb" \
  --review-ref "<merged PR and CI evidence URL>"
```

activation 會在同一交易內鎖定候選、重算 368 筆唯一 geocode、幾何有效性、
每筆 EWKB checksum 與整份 manifest，然後先停用舊 snapshot，再啟用新
snapshot。任一證據不符即 rollback。已完成的 snapshot 與其邊界不可原地改寫；
更新官方資料時必須建立並審核新 snapshot。

## 上線驗證

1. `/ready` 必須回報 database healthy，且 schema migration 為 `0046`。
2. active snapshot 必須恰好一筆，`imported_count=368`，邊界與唯一 geocode
   都是 368。
3. 下一次 NCDR poll 若有有效淹水 CAP，只有無 Polygon／Circle、且 exact
   geocode 可命中 active snapshot 的 Alert／Update 才能進 latest。
4. NCDR public latest 的 `quality_flags.active_snapshot_raw_ref` 必須等於
   `data_sources.metadata.active_snapshot_raw_ref`；完整 feed 已移除的舊警報不可
   繼續出現在 API。
5. Circle、來源自帶 Polygon、衝突 geocode、缺失邊界與 checksum 不符都必須
   維持 rejection-only，不可用中心點或父縣市替代。

啟用 geometry 不等於開啟來源。`SOURCE_NCDR_CAP_*` gates、來源目錄與正式監控
仍需各自保持已審且健康。
