## Summary 摘要

<!-- 這個 PR 做什麼、為什麼。關聯 issue 用 "Fixes #123"。 -->

## Changes 變更內容

-

## Contract impact 契約影響（勾選所有適用項）

- [ ] 不影響任何對外契約（純內部／文件變更）
- [ ] 公開 API schema 變更 → 已更新 OpenAPI 與 `packages/contracts/` fixtures
- [ ] 資料庫 schema 變更 → 已新增 migration 並通過 `python infra/scripts/validate_migrations.py`
- [ ] 評分規則／隱私政策／資料來源變更 → 已更新 SDD 章節或新增 ADR（見 CONTRIBUTING.md）

## Verification 驗證

<!-- 貼上實際跑過的指令與結果數字，例如：
python -m pytest apps/api/tests -q   → 336 passed
npm test --prefix apps/web           → 45 passed
-->

- [ ] 相關測試通過（附數字）
- [ ] lint / typecheck 通過（`ruff` / `mypy` / `npm run lint` / `npm run typecheck`，依改動範圍）
