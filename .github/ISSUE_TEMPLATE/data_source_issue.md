---
name: 資料來源問題 Data source issue
about: 回報資料來源失效、資料錯誤、授權疑慮，或提議新增來源
title: "[data] "
labels: data-source
---

## 類型

- [ ] 既有來源失效（API 掛掉／改版）
- [ ] 資料內容錯誤（站點位置、數值、時間）
- [ ] 授權／法遵疑慮
- [ ] 提議新增來源

## 來源識別

<!-- 例如 official.cwa.rainfall、official.civil_iot.flood_sensor，或 /admin/v1/sources 顯示的 source id；新來源請附官方網址與資料集頁面。 -->

## 說明

<!-- 失效：從何時開始、錯誤訊息。資料錯誤：哪個站點、預期值 vs 顯示值。
     新來源：資料涵蓋範圍、更新頻率、授權條款連結（政府資料開放授權條款？）。 -->

## 注意事項

新增來源必須通過 `infra/source-allowlist/` 的 per-source gate（授權、隱私、
robots/ToS 審查），詳見 `docs/data-sources/`。PTT/Dcard/社群來源目前為
blocked 狀態，未完成法遵審查前請勿提交相關 adapter。
