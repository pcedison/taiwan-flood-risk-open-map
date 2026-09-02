# 2017 與 2026 歷史 coverage 來源缺口查核

日期：2026-09-02（Asia/Taipei）

## 結論

2026-09-02 的兩個核准全國官方快照都沒有 2017 資料；NSTC 當前滾動快照也沒有
2026 資料。2017 可標記為「已審核全國來源未發布」的 `not_published`，但這只描述
目前核准來源的發布缺口，不代表 2017 沒有局部淹水，也不是 22 縣市個別網站的完整
事件盤點。2026 是尚未結束的當年度，維持 `failed` 並要求日後重新查核。

這兩類狀態都屬已知缺口；`absence_is_safety_evidence` 與
`data_coverage_complete` 必須保持 `false`。

## 實測證據

| 來源 | 官方頁面／資源 | 實測結果 | 年份 |
| --- | --- | --- | --- |
| WRA 歷年淹水範圍 | [dataset 25770](https://data.gov.tw/dataset/25770)／官方 KML | fetched 1,224；normalized 1,075；rejected 157；revision `2018-06-08T16:26:00` | 2004、2005、2007–2016；無 2017 |
| NSTC 近年淹水災點 | [dataset 130016](https://data.gov.tw/dataset/130016)／官方 CSV | fetched 8,838；normalized 8,646；rejected 192；revision SHA-256 `7c4a0fe0d05f1fa372886aacccfbff1601e13a8335264fde8be1add813dbf6895` | 2021–2025；無 2017、2026 |

WRA 資料集只涵蓋大規模淹水調查，官方說明明確排除部分局部積淹水、道路排水與低窪
農漁區情境。NSTC 是不定期更新的近五年滾動快照，只提供年度與點位。兩者都不是所有
淹水事件的完整登錄。

## 可稽核寫入規則

review manifest 固定於
`docs/data-sources/official/historical-coverage-gap-review-2026-09-02.json`。命令必須
驗證檔案 SHA-256；預設 dry-run、完全不連外。只有 `--persist`、目標環境與明確確認旗標
齊備時才可寫入。

writer 只更新 `unassessed` 格，保留任何來源 ingestion 已產生的 `partial`、`complete`、
`official_checked_empty`、`failed` 或較新 review。重跑同一 manifest 不改狀態，也不能用
gap review 覆蓋後續補到的官方事件。

## 仍未完成的查核

- 2017 的 22 縣市個別公開資料與可合法自動化的地方事件來源尚未逐一耗盡；若找到合格
  來源，必須走 raw snapshot、source check 與 coverage refresh，不得直接改 ledger。
- 2026 應隨 NSTC 後續 revision 或其他核准歷史來源重新評估。
- `not_published` 只代表被列入 manifest 的來源沒有發布該年資料，不得翻譯成「沒有淹水」。
