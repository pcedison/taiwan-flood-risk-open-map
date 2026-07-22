# GitHub Actions Secrets 現況文件

## 目的

這份文件回答兩個問題：

1. `.github/workflows/` 底下依賴 hosted 憑證的 workflow，各自實際引用哪些 `secrets.*`、用途是什麼？
2. 2026-07-06 稽核時 repo 的 Actions secrets 是空清單，這代表什麼——哪些 workflow 因此實際上不會成功、哪些會被跳過、哪些完全不受影響？

來源稽核：`docs/reviews/audit-2026-07-06-open-source-sustainability.md` finding F3、
`docs/reviews/sustainability-master-plan-2026-07-06.md` P1-7。

配套文件：[SUCCESSION.md](../../SUCCESSION.md) 第 7 項（GitHub Actions secrets 傳承單點）、
[docs/runbooks/monitoring-freshness-alerts.md](monitoring-freshness-alerts.md)（`GitHub Actions Secret Readiness Watchdog` 一節，說明 `github-actions-secret-readiness-watchdog.yml` 的告警邏輯）。

---

## 盤點方法

本節內容是直接讀取以下四個 workflow 檔案得出，逐一列出其中 `secrets.*` 引用與觸發條件，不依賴外部記憶或猜測：

- `.github/workflows/hosted-monitoring.yml`
- `.github/workflows/hosted-monitoring-schedule-watchdog.yml`
- `.github/workflows/github-actions-secret-readiness-watchdog.yml`
- `.github/workflows/local-source-dispatch-watchdog.yml`

---

## 逐 workflow 盤點

### `hosted-monitoring.yml`（Hosted Monitoring，排程 `7,37 * * * *`，每小時兩次）

引用的 secrets：

| Secret 名稱 | 用途 |
|---|---|
| `ADMIN_BEARER_TOKEN` | 呼叫 `/admin/v1/sources` 取得來源新鮮度證據（`hosted_source_freshness_smoke.py`）。 |
| `HOSTED_WORKER_EVIDENCE_MANIFEST_B64` | base64 編碼的私有 manifest，餵給 `hosted_worker_evidence.py` 產生 worker 已落地證據。 |
| `HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64` | base64 編碼的私有 manifest，餵給 `hosted_worker_policy_evidence.py`，涵蓋 raw snapshot 保留政策、排程節奏、hosted egress 政策證據。 |
| `HOSTED_MONITORING_EVIDENCE_MANIFEST_B64` | base64 編碼的私有 manifest，餵給 `hosted_monitoring_evidence.py`，涵蓋告警路由與 worker/scheduler ownership 證據。 |
| `LOCAL_SOURCE_REQUEST_DISPATCH_EVIDENCE_B64` | base64 編碼的私有 manifest，餵給 `local-source-request-followups.py`，追蹤向地方政府/官方單位申請資料來源的後續進度。 |

**這些 secrets 目前全部未設定時的行為**：workflow 設計為優雅降級（graceful degradation），不是硬性失敗。

- 不需要任何 secret 的步驟（公開 API 冒煙、hosted deployment smoke、hosted 公開風險證據冒煙、signal-gap 探索/派工就緒檢查、request packet bundle、hosted 私有證據就緒/範本 bundle）**仍會照常執行**，因為它們打的是公開端點（`floodrisk.cc`）或純本地腳本。
- 每個依賴上述 5 個 secrets 的步驟都有對應的 `if: secrets.X != ''` 判斷式；secret 缺席時，該步驟會被**跳過**（不是失敗），並在 `GITHUB_STEP_SUMMARY` 寫一行「因為 `X` 未設定，所以某項證據沒有被收集」。
- 例外：若手動觸發（`workflow_dispatch`）時把 `require_admin_source_freshness` 設為 `true`，且 `ADMIN_BEARER_TOKEN` 未設定，這個步驟才會讓整個 workflow **失敗**（`exit 1`）。排程觸發（`schedule`）時這個輸入預設為 `false`，所以定時執行不會因為缺 `ADMIN_BEARER_TOKEN` 而失敗。

**2026-07-06 現況（secrets 為空清單）的結論**：這個 workflow 每小時兩次仍會「執行成功」並產生公開端點的冒煙證據，但**私有 hosted 證據（worker 落地、worker policy、monitoring、地方來源派工追蹤）完全沒有被收集**，因為對應 5 個 manifest secret 全部缺席。換句話說，README 若聲稱「hosted monitoring 已上線」，指的頂多是公開端點的健康冒煙，不是完整的私有證據鏈。

### `hosted-monitoring-schedule-watchdog.yml`（Hosted Monitoring Schedule Watchdog，排程 `17,47 * * * *`）

引用的 secrets：**無**。這個 workflow 只使用 GitHub 內建的 `${{ github.token }}`（作業階段自動核發，不是 repo secret），用來查詢 `hosted-monitoring.yml` 過去排程執行的紀錄，並在必要時用 GitHub API 手動派工重跑一次 `hosted-monitoring.yml`。

**2026-07-06 現況的結論**：不受 secrets 空清單影響，會完全正常運作——它檢查的是「`hosted-monitoring.yml` 有沒有準時跑」，而不是後者內部的私有證據是否收集完整。

### `github-actions-secret-readiness-watchdog.yml`（GitHub Actions Secret Readiness Watchdog，排程 `23 16 * * *`，每天一次）

引用的 secrets（僅檢查是否已設定，不讀取實際值）：

| Secret 名稱 | 檢查方式 |
|---|---|
| `ADMIN_BEARER_TOKEN` | `${{ secrets.ADMIN_BEARER_TOKEN != '' }}` |
| `HOSTED_WORKER_EVIDENCE_MANIFEST_B64` | `${{ secrets.HOSTED_WORKER_EVIDENCE_MANIFEST_B64 != '' }}` |
| `HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64` | `${{ secrets.HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64 != '' }}` |
| `HOSTED_MONITORING_EVIDENCE_MANIFEST_B64` | `${{ secrets.HOSTED_MONITORING_EVIDENCE_MANIFEST_B64 != '' }}` |
| `LOCAL_SOURCE_REQUEST_DISPATCH_EVIDENCE_B64` | `${{ secrets.LOCAL_SOURCE_REQUEST_DISPATCH_EVIDENCE_B64 != '' }}` |

這個 workflow 本身就是「檢查上面那組 secrets 有沒有設定」的監控器，它不消費 secret 的實際值，只把「已設定/未設定」寫成一份 public-safe 的 JSON（`scripts/github-actions-secret-readiness.py`）。

**2026-07-06 現況（secrets 為空清單）的結論**：這個 workflow 每天都會執行並產出「5 個 secrets 全部未設定」的報告。是否因此讓整個 workflow 失敗，取決於 `fail_on_completion_blockers` 這個輸入：

- 手動觸發（`workflow_dispatch`）時可以把它設為 `true`，此時若有 completion-blocking 的 secret 缺席，`scripts/github-actions-secret-readiness.py` 會回傳非零結束碼，workflow 視為失敗，並開一則 `[secret-readiness-watchdog]` 的 issue。
- 排程觸發（`schedule`）時，這個輸入沒有被設定，會 fallback 成 `'false'`（見 workflow 的 `env.FAIL_ON_COMPLETION_BLOCKERS` 運算式），對應到 `scripts/github-actions-secret-readiness.py` 的 `main()`：只有 `args.fail_on_completion_blockers` 為真且有 completion gate blocker 時才回傳 `1`；預設情況下一律回傳 `0`。也就是說，**每天的排程執行本身不會因為 secrets 缺席而失敗，只會報告**，`failure()` 觸發的「開 issue」步驟不會被啟動。

issue 的關閉判定只看 route-aware 的 `completion_gate_blocker_count` 是否為 0：
`HOSTED_MONITORING_EVIDENCE_MANIFEST_B64` 必須存在，worker 部分則可選擇
`HOSTED_WORKER_EVIDENCE_MANIFEST_B64` 單一路徑，或
`ADMIN_BEARER_TOKEN` 加上 `HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64` 的拆分路徑。
未採用路徑上的個別 secret 可以維持未設定；
`LOCAL_SOURCE_REQUEST_DISPATCH_EVIDENCE_B64` 對這張 secret-readiness issue 仍是
optional，不影響它的關閉判定；但 local-source dispatch watchdog 會使用其內容來
追蹤派工，並在其中的 reviewed accepted evidence 通過驗證後移除已完成 queue target。

### `local-source-dispatch-watchdog.yml`（Local Source Dispatch Watchdog，排程 `7 16 * * *`，每天一次）

引用的 optional secret：`LOCAL_SOURCE_REQUEST_DISPATCH_EVIDENCE_B64`。workflow 先把
base64 manifest 解碼到 runner temp，再由 `local-source-request-followups.py` 產生
public-safe sanitized overlay；原始 evidence ref、reviewer 與 correspondence 不會上傳。
其餘步驟呼叫本地 Python 腳本分析地方政府資料來源缺口，並用
`actions/github-script` 內建的預設 `GITHUB_TOKEN` 開/關 issue。

secret 未設定時仍會正常產生完整 pending queue。設定後，`request_dispatched` 只更新
追蹤狀態、不滿足 completion gate；具有非 placeholder `evidence_ref` 與
`reviewed_at` 的 accepted signal/source-contract evidence 才會移除對應 target。全部
target 移除後，strict run 會得到 `no_dispatch_required` 並關閉既有 dispatch issue。

---

## 彙總表：現況一句話結論

| Workflow | 需要的 secrets 數 | secrets 為空時的行為 |
|---|---|---|
| `hosted-monitoring.yml` | 5 個（`ADMIN_BEARER_TOKEN`、`HOSTED_WORKER_EVIDENCE_MANIFEST_B64`、`HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64`、`HOSTED_MONITORING_EVIDENCE_MANIFEST_B64`、`LOCAL_SOURCE_REQUEST_DISPATCH_EVIDENCE_B64`） | 公開端點冒煙仍執行成功；5 項私有 hosted 證據全部被跳過收集，不會讓 workflow 失敗（除非手動指定 `require_admin_source_freshness=true`）。 |
| `hosted-monitoring-schedule-watchdog.yml` | 0（僅用 `github.token`） | 不受影響，正常運作。 |
| `github-actions-secret-readiness-watchdog.yml` | 0（只檢查上面 5 個 secret 的存在與否，不消費其值） | 排程執行預設只報告、不失敗；手動觸發並指定 `fail_on_completion_blockers=true` 時才會失敗並開 issue。 |
| `local-source-dispatch-watchdog.yml` | 1 個 optional（`LOCAL_SOURCE_REQUEST_DISPATCH_EVIDENCE_B64`） | 未設定時仍正常運作並回報完整 pending queue；設定 reviewed accepted evidence 後會縮減 queue，只有派工紀錄時仍維持 pending。 |

**整體結論**：schedule watchdog 完全不需要 repo secret；secret readiness watchdog
只檢查設定狀態；local-source dispatch watchdog 可在沒有 optional secret 時正常報告，
但需要 reviewed accepted local-source evidence 才能自動縮減並最終清空 queue。
`hosted-monitoring.yml` 則需要合法 worker 與 monitoring evidence route 才能收集完整的
私有 hosted 證據。

---

## 接手者如何啟用

1. 先確認已具備 repo admin 或至少 Secrets 管理權限（見 [SUCCESSION.md](../../SUCCESSION.md) 第 1 項）。
2. 前往 repo 的 **Settings → Secrets and variables → Actions**，依合法 completion route 設定名稱完全一致的 secret：
   - worker 路徑二選一：設定 `HOSTED_WORKER_EVIDENCE_MANIFEST_B64`；或同時設定 `ADMIN_BEARER_TOKEN` 與 `HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64`。`ADMIN_BEARER_TOKEN` 應與 Zeabur 環境變數使用同一組隨機長字串（見 [docs/runbooks/zeabur-single-service-env.md](zeabur-single-service-env.md)），讓 CI 可以用同一把 token 呼叫 `/admin/v1/sources`。
   - monitoring 路徑：設定 `HOSTED_MONITORING_EVIDENCE_MANIFEST_B64`。
   - `LOCAL_SOURCE_REQUEST_DISPATCH_EVIDENCE_B64` 只在已有經私下審核的地方來源派工或 accepted completion evidence 時設定。它不是 secret-readiness completion blocker；對 local-source dispatch watchdog 而言，accepted entries 是縮減 queue 的輸入，`request_dispatched` entries 則仍是 pending。
   - 三種 `*_MANIFEST_B64` secret 都是私有證據 manifest 的 base64 編碼，欄位結構由對應的 `scripts/hosted_*_evidence.py` / `scripts/local-source-request-followups.py` 定義。先在私有 ops 環境準備未編碼 JSON，確認內容已審核且不會洩漏機密，再編碼並貼入 GitHub Secrets。
3. 設定完成後，手動觸發一次 `Hosted Monitoring` workflow（`workflow_dispatch`），確認所選 worker route 與 monitoring route 的步驟都有執行，且對應的 `*-completion-evidence.json` 產物有正確產生。未採用 worker route 或 optional local-source route 的「未設定所以跳過」訊息可以保留。
4. 同步手動觸發一次 `GitHub Actions Secret Readiness Watchdog` 並帶入 `fail_on_completion_blockers=true`，確認回報「0 個 completion gate blocker」。
5. 不要把任何 secret 的明文值寫進本 repo 的任何檔案（包含這份 runbook、issue、commit message）。

## CI 安全提醒

- 這些 workflow 建立的 issue（`[hosted-monitoring-alert]`、`[hosted-schedule-watchdog]`、`[secret-readiness-watchdog]`、`[local-source-dispatch-watchdog]`）在設計上都是 public-safe，只包含 run URL、SHA、聚合計數、public 路由細節，不含 token 或私有證據內容本身——這點已由各 workflow 的程式碼註解與
  [docs/runbooks/monitoring-freshness-alerts.md](monitoring-freshness-alerts.md) 交叉確認。
- 若未來新增更多需要 secrets 的 workflow，請同步更新本文件的盤點表，不要讓文件與實際 workflow 內容脫鉤。
