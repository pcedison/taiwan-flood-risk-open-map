# 下一個 Agent 的完整接手指令

> **2026-08-25 更新：** 下列「第一個工作：完成 Core Task 8」已完成，僅保留
> 作歷史稽核。新的接手起點是 `codex/v1-official-community` HEAD `49fbb79`，
> 下一個工作為 Core Task 9。請先讀取
> `docs/reviews/task-9-readiness-2026-08-25.md`，不得重做、rebase 或覆寫已核准
> 的 Task 8。

你現在接手 Flood Risk v1 專案。使用者正承受政府時程壓力，目標是盡快得到可上線測試的版本，但不得以略過資料完整性、真實 PostGIS、隱私或獨立審查換取表面完成。

## 必須採用的工作方式

1. 使用 Subagent-Driven Development。
2. 每個 implementation task 使用 TDD：先重現 RED，再做最小 GREEN，再重構。
3. 實作者不得自行核准；每個 task完成後必須交給獨立 reviewer。
4. 發現 bug/test failure 時先做 systematic debugging，不猜修。
5. 宣稱完成前執行 verification-before-completion；只引用本回合新鮮輸出。
6. 保留使用者既有變更，不使用 `git reset --hard`、`git checkout --`、`git clean` 或粗暴 `ours/theirs`。
7. 工具執行期間每 60 秒內提供一次簡短繁體中文進度更新。
8. 未經使用者另行要求，不 push、不開 PR、不 merge main、不 deploy、不啟用任何 production source。

## 第一優先閱讀

完整讀取：

1. `/Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-official-community/docs/reviews/handoff-2026-08-24-v1-official-community.md`
2. `/Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-official-community/docs/superpowers/specs/2026-08-24-v1-flood-risk-community-signals-design.md`
3. `/Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-official-community/docs/superpowers/plans/2026-08-24-v1-core-official-baseline.md`
4. `/Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-official-community/docs/superpowers/plans/2026-08-24-v1-community-signals.md`
5. `/Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-task8/.superpowers/sdd/task-8-spec-review.md`
6. `/Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-task8/.superpowers/sdd/task-8-spec-rereview.md`
7. `/Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-task8/.superpowers/sdd/task-8-report.md`
8. `/Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-official-community/.superpowers/sdd/progress.md`

`.superpowers/sdd` 是本機 ignored資料；不要假設它已被 git追蹤或會存在於另一台機器。

## 不可改錯工作樹

- Root/main：`/Users/marcus/Documents/ChatGPT/flood-risk`，HEAD `ce61edb`。
- Integration：`/Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-official-community`，branch `codex/v1-official-community`，HEAD `124a59d`。
- Current Task 8：`/Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-task8`，branch `codex/v1-task8`，HEAD `684468a`，有必須保留的未提交修改。
- Reserved Task 10：`/Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-task10`，HEAD `ec396e6`，尚未實作。
- `codex/v2-risk-engine-rebuild` 與 v1無關，不合併、不修正。

## 第一個工作：完成 Core Task 8

不要先做 Task 9、Task 10、社群功能、UI或部署。

### 先凍結與確認狀態

在 Task 8 worktree執行：

```bash
cd /Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-task8
git status --short
git rev-parse HEAD
git diff --check
git diff --stat 684468a
git diff 684468a -- apps/workers/app/pipelines/promotion.py
```

必須看到 HEAD `684468abda8f8ad69caa441c5a84b4eefd183ac5`，以及以下三個 modified files：

```text
apps/workers/app/pipelines/promotion.py
apps/workers/tests/test_promotion_monotonicity_postgres.py
apps/workers/tests/test_promotion_pipeline.py
```

若狀態不同，先調查，不要 reset。

### 目前未提交修正的四個契約

1. Mixed CAP references可完整保留作 audit，但只有 `reference.sent < candidate.cap_sent` 的 canonical earlier subset可以 retire、tombstone或影響 lifecycle。
2. Current CAP explicit Point/Polygon/MultiPolygon必須在任何 lock/retire/insert/latest前通過 finite、WGS84、結構與 PostGIS topology驗證。
3. Generic `INSERT ... DO NOTHING RETURNING` 的 distinct authorized staging loser必須 terminalize為 `idempotent_existing_evidence`並 commit；不能永久保持 accepted。
4. Supplied staging UUID必須在 locked accepted row上比對所有 persisted scalar及 exact canonical JSONB payload，只移除 writer-owned `staging_evidence_id`和`raw_snapshot_id`；不得冒用 UUID改 metrics、geometry或CAP lifecycle。

不得弱化上述四項以讓測試通過。

### 先重現現在的測試狀態

Worker Python：

```text
/Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-official-community/.venv/workers/bin/python
```

Focused unit：

```bash
cd /Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-task8/apps/workers
/Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-official-community/.venv/workers/bin/python \
  -m pytest tests/test_promotion_pipeline.py -q
```

交接時新鮮結果：`77 passed, 3 failed`。三個 failures是 NaN/Inf geometry案例期待 terminal rejection，但新的 exact payload authorization使用 `allow_nan=False`，在 authorization階段即 fail closed。

Required live DB：

```bash
cd /Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-task8/apps/workers
PROMOTION_TEST_DATABASE_URL='postgresql://flood_risk:change-me-local@127.0.0.1:5432/flood_risk' \
OFFICIAL_DB_ACCEPTANCE_REQUIRED=1 \
/Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-official-community/.venv/workers/bin/python \
  -m pytest tests/test_promotion_monotonicity_postgres.py -q -rs
```

交接時新鮮結果：`49 passed, 0 skipped`。

PostGIS container `flood-risk-postgres-1` 已 healthy；不要刪除預設資料庫或改用 broad destructive command。

### 正確處理三個 NaN/Inf failures

先閱讀失敗測試與 production flow，再用 TDD決定 exact contract。預設建議：

- 保留 `json.dumps(..., allow_nan=False)`；NaN/Inf不是合法 JSON/JSONB，不可為測試而放寬。
- 合法 persisted staging不可能含 NaN/Inf JSONB；帶 staging UUID的 non-JSON forged payload應 authorization fail closed，不得修改不相干 staging row。
- 使用 finite但out-of-range、malformed ring、自交 polygon等可實際存在於 JSONB的fixture，證明 authorized staging會 terminal reject且不產生 lifecycle effect。
- Direct writer沒有 staging metadata時，NaN/Inf仍必須 fail closed、不insert、不retire、不overwrite latest；沒有 authorized row就不要假造 terminal mutation。
- 若選擇其他語意，必須先以真 PostgreSQL證明該 staging state可存在，並由 independent reviewer同意。

不得只修改 fake cursor讓不可能的狀態看似通過。

### Task 8 完成閘門

Focused全綠後，依序執行：

```bash
cd /Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-task8/apps/workers
/Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-official-community/.venv/workers/bin/python -m pytest -q
/Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-official-community/.venv/workers/bin/python -m ruff check app tests
/Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-official-community/.venv/api/bin/python -m mypy app

cd /Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-task8/apps/api
/Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-official-community/.venv/api/bin/python -m pytest -q
/Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-official-community/.venv/api/bin/python -m ruff check app tests
/Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-official-community/.venv/api/bin/python -m mypy app

cd /Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-task8
git diff --check
```

另外重跑 required live DB，必須 0 skips。不要把 ordinary full-suite中的 environment-gated skips當作 live acceptance。

更新 `.superpowers/sdd/task-8-report.md`，然後建立新 commit：

```text
fix: bind promotion to validated staging content
```

不要 amend `f70b34e`或`684468a`。

### Task 8 必須獨立複審

新開 read-only reviewer，交付：

- cumulative diff `8a0bcb0..新HEAD`
- follow-up diff `684468a..新HEAD`
- 兩份 Task 8 spec review
- updated report

Reviewer必須特別用真 DB驗證：

1. stale mixed Update與Cancel不能刪later/equal warning，也不能建立later replay tombstone。
2. invalid/out-of-range/self-intersecting CAP area geometry不能retire舊Alert、insert evidence或overwrite latest。
3. 兩個distinct authorized staging同natural key時，loser terminal，且不再被accepted query抓到。
4. 合法 staging UUID不能修改title/summary/url/confidence/metric/geometry/CAP lifecycle。
5. same-staging retry仍返回None但不把已成功的同一 staging row改成rejected。
6. 既有30項 live concurrency、central/local、boundary與CAP identity matrix沒有退化。

只有 reviewer明確 `APPROVED` 才能整合。

## Task 8 整合方式

Task 8 branch基礎是 `8a0bcb0`，Integration已前進到Task 7 final `124a59d`。不要在dirty狀態rebase。

Task 8 clean、commit、review APPROVED後：

1. 建立非破壞性備份branch指向Task 8 final HEAD。
2. 在 integration worktree確認只有交接文件等已知變更；不要覆寫使用者檔案。
3. 將 `f70b34e`、`684468a`與新修正commit依序cherry-pick到`codex/v1-official-community`，或採等價可審核整合。
4. 逐一解 conflict；禁止直接 `--ours`/`--theirs`。
5. Task 7的frozen generic facades、exact v1 scoped seam與URL boundary必須保留。
6. 跑完整 integrated API、workers、OpenAPI、Ruff、mypy與required PostGIS。
7. 只有整合結果全綠才更新 `.superpowers/sdd/progress.md` 將Task 8標成complete。

不要把本交接報告或ignored SDD檔案意外遺失；是否提交兩份handoff docs由使用者決定。

## Task 8 後的執行順序

1. Core Task 9：`no_active_event`、generation anti-resurrection、source-specific health。
2. Task 10/11/12：WRA historical KML、CWA CAP、NCDR dump CAP；可在不衝突的隔離worktree平行，但都應以整合後Task 8/9為基礎。
3. Task 13：flood-potential measured production manifest；真artifact/toolchain不可用時保持gates off，不捏造完成。
4. Task 14：唯一 per-source v1 managed wrapper與migration 0038；所有catalog row預設disabled。
5. Task 15：Web additive model + complete legacy fallback；unknown永不變low。
6. Task 16：完整API/worker/web/E2E/empty+upgrade DB/source activation acceptance及operator docs。
7. Core Task 16通過後再執行Community Task 1–11。

Reserved Task 10 worktree目前只在`ec396e6`，缺Task 8/9。不要直接在舊base開始；先更新到已核准integration HEAD。

## 社群與 Browser Agent 不可越界

- Production自動來源只用正式API或明確授權介面。
- Threads未通過App/permission/review/token/contract artifact時維持disabled。
- Browser Agent只做quarantined discovery/人工複核，不直接寫confirmed event或改risk。
- 不登入、不用個人session、不繞CAPTCHA/反爬/付費牆。
- 不保存完整文章、作者、留言、HTML、Cookie、截圖、原始媒體。
- 單篇不改分；只有獨立來源交叉佐證才可最多uplift一級。
- 社群永不降低官方risk，官方unknown仍保持unknown並揭露data gap。

## 上線邊界

目前不允許deploy或宣稱production ready。最快安全路徑仍是：Task 8 → 9 → 10/11/12/13 → 14 → 15 → 16。

Task 14後部署到staging時仍須：

- migration先完成；
- 所有source catalog row與runtime gates先保持disabled；
- 每次只做一個source的isolated proof；
- 由operator transaction明確enable該catalog row；
- 驗證health與適用jurisdiction assessment；
- rollback先disable catalog row，再關runtime/API gates。

若因政府時程先做technical preview，必須明確顯示disabled sources與data gaps；不得稱為完整production baseline。

## 每回合回報格式

向使用者用繁體中文簡短回報：

1. 剛完成的可驗證結果。
2. 現在執行的單一重點。
3. 新發現的阻擋與是否影響上線。
4. 不報虛假的完成百分比；以Task/review/test gate為準。

最終交付需列出commit、review verdict、fresh test counts、剩餘外部blockers與是否可部署。
