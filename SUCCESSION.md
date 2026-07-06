# 傳承檔案（SUCCESSION.md）

本檔案回答一個問題：**如果原作者（pcedison）明天無法再聯絡，這個服務還能不能被別人接手？**

它記錄八個目前只有原作者一人持有的「傳承單點」（single point of failure）：這個東西是什麼、目前由誰持有、若中斷會發生什麼事、如何重新取得或重建，以及目前的備援安排現況。

**本檔案不放任何機密值**——不放金鑰、token、密碼、帳號 ID、DNS 記錄細節。所有機密值只存在原作者本機、Zeabur 環境變數、或 GitHub Actions Secrets（現況見
[docs/runbooks/github-actions-secrets.md](docs/runbooks/github-actions-secrets.md)）。本檔案只回答「去哪裡拿」與「怎麼重建」，實際操作步驟見對應 runbook。

來源稽核：`docs/reviews/audit-2026-07-06-open-source-sustainability.md`（finding F2、F3）、`docs/reviews/sustainability-master-plan-2026-07-06.md`（第四節、P1-2、P1-7）。

---

## 1. GitHub repo admin 權限

- **這是什麼**：`github.com/pcedison/taiwan-flood-risk-open-map` 的 repo 擁有者/admin 權限，控制分支保護、Secrets、Settings、合併權限。
- **目前由誰持有**：僅 `pcedison`（GitHub 帳號），是唯一的 collaborator，也是 `.github/CODEOWNERS` 中唯一列出的 reviewer。
- **服務中斷影響**：無法合併 PR、無法更新 Secrets、無法變更部署設定；若帳號遺失且未啟用復原機制，repo 有被鎖死的風險。
- **如何重新取得或重建**：
  - 若原作者的 GitHub 帳號仍可存取：直接在 Settings → Collaborators and teams 新增第二位 admin。
  - 若原作者完全無法聯絡：需透過 GitHub Support 的帳號復原/所有權轉移流程處理，這是 GitHub 官方帳號救援程序，不在本專案文件範圍內。
  - 長期建議：將 repo 轉移到 GitHub organization（例如 `taiwan-flood-risk`），organization 天然支援多 owner，可避免單一個人帳號變成單點（見 `docs/reviews/sustainability-master-plan-2026-07-06.md` 第三節「第 3~12 個月」）。
- **備援安排現況**：目前無。`SECURITY.md`/`CODE_OF_CONDUCT.md`/`CODEOWNERS` 已建立（P0-4 已完成），但 `CODEOWNERS` 只列出 `@pcedison` 一人，尚未有第二位 collaborator。

## 2. Zeabur 帳號與專案

- **這是什麼**：正式環境部署在 Zeabur 平台的專案（`docs/runbooks/production-beta-ops-evidence-2026-05-06.md:4` 記載為 `flood_risk`），綁定 GitHub repo 自動部署，並持有所有正式環境的環境變數（含資料庫連線字串、API 金鑰）。
- **目前由誰持有**：原作者的 Zeabur 帳號（透過 GitHub 登入建立）。
- **服務中斷影響**：若 Zeabur 帳號或專案遺失，正式站（floodrisk.cc 背後的服務）會直接下線，且所有已設定的環境變數需要重新輸入。
- **如何重新取得或重建**：完整步驟見 [docs/runbooks/infrastructure-rebuild.md](docs/runbooks/infrastructure-rebuild.md) 的「(b) Zeabur 專案建立」一節，該節引用既有的
  [docs/runbooks/deploy-zeabur.md](docs/runbooks/deploy-zeabur.md) 與
  [docs/runbooks/zeabur-single-service-env.md](docs/runbooks/zeabur-single-service-env.md) 補齊環境變數清單。
- **備援安排現況**：目前無團隊帳號、無第二位有權限存取 Zeabur 專案的人。

## 3. 網域 floodrisk.cc（註冊商與 DNS）

- **這是什麼**：正式站使用的網域 `floodrisk.cc`，包含網域註冊商帳號、續約設定，以及指向 Zeabur 服務的 DNS 記錄（CNAME/A）。
- **目前由誰持有**：原作者名下的網域註冊帳號；repo 內沒有任何檔案記載註冊商是誰、續約日期、或 DNS 供應商（`docs/reviews/audit-2026-07-06-open-source-sustainability.md` F2 已確認 repo 內無此文件）。
- **服務中斷影響**：網域到期未續約會導致 `floodrisk.cc` 完全無法解析，即使 Zeabur 服務本身仍在運行；DNS 記錄遺失會讓網域無法指向服務。
- **如何重新取得或重建**：若原作者帳號可存取，登入原註冊商續約或轉移；若完全無法聯絡，需等網域到期後重新註冊（服務會有一段離線期），或透過註冊商的帳號復原機制處理（各註冊商流程不同，不在本專案文件範圍內）。重新指向新服務的 DNS 設定步驟見
  [docs/runbooks/infrastructure-rebuild.md](docs/runbooks/infrastructure-rebuild.md) 的「(d) 網域與 DNS」一節。
- **備援安排現況**：目前無。註冊商名稱、續約日期、DNS 供應商均未文件化，也沒有備援聯絡人。**這是本清單中優先度最高的缺口之一**——建議原作者近期至少把「註冊商名稱＋續約到期日」記錄在私人的 ops 交接文件中（不需要放進本公開 repo）。

## 4. CWA（中央氣象署）開放資料平台金鑰

- **這是什麼**：`CWA_API_AUTHORIZATION` 環境變數，用於呼叫中央氣象署開放資料平台（雨量、潮位等即時觀測）。
- **目前由誰持有**：原作者以個人身份在 `opendata.cwa.gov.tw` 註冊取得的授權碼。
- **服務中斷影響**：金鑰失效或到期，CWA 相關的即時觀測（rainfall、tide_level）會降級為 `degraded`/`stale`，但服務本身不會整體下線（四態新鮮度模型會誠實降級，不會硬崩潰）。
- **如何重新取得或重建**：任何人都可以到 `opendata.cwa.gov.tw` 免費註冊會員並自行申請新的授權碼，不需要聯絡原作者。詳細申請入口見
  [docs/runbooks/infrastructure-rebuild.md](docs/runbooks/infrastructure-rebuild.md) 的「(a) 前置帳號註冊」一節。
- **備援安排現況**：目前無備援金鑰或第二個已註冊帳號，但因為申請門檻低（免費、公開註冊），實際重建風險低於「帳號/網域」類項目。

## 5. WRA（水利署）/ Civil IoT 會員金鑰

- **這是什麼**：WRA 開放資料平台的（選用）token，以及 Civil IoT SensorThings API 存取所需的會員帳號；用於水位、感測器、抽水站等資料來源。
- **目前由誰持有**：原作者的 `ci.taiwan.gov.tw` 會員帳號；WRA 部分目前多數端點屬公開資料，不一定需要 token（見 `.env.example` 中 `WRA_API_TOKEN` 為選填）。
- **服務中斷影響**：Civil IoT 相關來源（flood sensor、sewer/pump/gate water level）若帳號失效會降級為 `degraded`/`stale`；WRA 公開端點若本身無需 token，通常不受影響。
- **如何重新取得或重建**：到 `ci.taiwan.gov.tw` 重新註冊會員帳號即可，公開流程，不需要聯絡原作者。詳細申請入口見
  [docs/runbooks/infrastructure-rebuild.md](docs/runbooks/infrastructure-rebuild.md) 的「(a) 前置帳號註冊」一節；啟用細節見既有的
  [docs/runbooks/civil-iot-live-enablement.md](docs/runbooks/civil-iot-live-enablement.md)。
- **備援安排現況**：目前無。此為 `docs/reviews/audit-2026-07-06-open-source-sustainability.md` F2 明確點名「比 CWA 更沒有文件」的項目。

## 6. Cloudflare Turnstile secret（公民回報功能）

- **這是什麼**：`USER_REPORTS_CHALLENGE_SECRET_KEY` 環境變數，用於驗證公民回報表單的 Cloudflare Turnstile 挑戰 token（防機器人）。驗證邏輯見 `apps/api/app/domain/reports/challenge.py`。
- **目前由誰持有**：原作者的 Cloudflare 帳號下建立的 Turnstile site 與對應的 secret key。
- **服務中斷影響**：目前 `USER_REPORTS_ENABLED=false`（`.env.example:265`），公民回報功能本身尚未對外開放，所以這個金鑰目前不影響正式站的公開功能；但若未來要開放回報功能，沒有這把 secret 就無法通過挑戰驗證。
- **如何重新取得或重建**：到 `dash.cloudflare.com` 免費建立新的 Turnstile site 取得新的 sitekey/secret key 即可，不需要聯絡原作者。詳細入口見
  [docs/runbooks/infrastructure-rebuild.md](docs/runbooks/infrastructure-rebuild.md) 的「(a) 前置帳號註冊」一節。
- **備援安排現況**：目前無，但因功能尚未上線且重建門檻低（免費、公開自助），實際急迫性低於帳號/網域類項目。

## 7. GitHub Actions secrets

- **這是什麼**：`hosted-monitoring.yml` 等 workflow 使用的一組 repo-level secrets（`ADMIN_BEARER_TOKEN`、`HOSTED_WORKER_EVIDENCE_MANIFEST_B64` 等），詳細清單與現況見
  [docs/runbooks/github-actions-secrets.md](docs/runbooks/github-actions-secrets.md)。
- **目前由誰持有**：原作者的 GitHub repo admin 權限（Secrets 只能由有寫入權限的人設定，設定後任何人都無法讀回明文）。
- **服務中斷影響**：2026-07-06 稽核當下這組 secrets 為空清單；影響範圍與現況已在
  [docs/runbooks/github-actions-secrets.md](docs/runbooks/github-actions-secrets.md) 逐一列出（哪些 workflow 步驟因此被跳過、哪些仍會正常執行）。
- **如何重新取得或重建**：需要先完成本清單第 1 項（取得 repo admin 權限），才能到 repo Settings → Secrets and variables → Actions 設定。實際值的來源（如 `ADMIN_BEARER_TOKEN`）是接手者自行產生的隨機長字串，不是需要向原作者索取的外部憑證。
- **備援安排現況**：目前無任何第二人有權限設定或檢視這些 secrets 的存在狀態（`gh secret list` 需要 repo 權限）。

## 8. 資料庫備份的存放位置與還原程序

- **這是什麼**：PostgreSQL/PostGIS 正式資料的備份，包含本機/CI 可執行的邏輯備份流程與 Zeabur 平台代管的離站備份。
- **目前由誰持有**：邏輯備份流程（`pg_dump`/`pg_restore`）已文件化且可由任何人執行，見
  [docs/runbooks/backup-restore-drill.md](docs/runbooks/backup-restore-drill.md)；但 Zeabur 平台代管的離站備份本身位於原作者的 Zeabur 帳號下（見本清單第 2 項），且該 runbook 明確記載「production-complete 證據仍需要私有的 Zeabur 代管離站備份證據」。
- **服務中斷影響**：若資料庫損毀且原作者的 Zeabur 帳號無法存取，Zeabur 平台代管的離站備份也一併不可及；本機/CI 的邏輯備份流程若未曾實際針對正式資料執行過，接手者無法確定是否有可用的正式資料備份存在。
- **如何重新取得或重建**：還原流程與安全規則見
  [docs/runbooks/backup-restore-drill.md](docs/runbooks/backup-restore-drill.md)（含 scratch 還原演練、事故還原大綱）；取得 Zeabur 平台代管備份需要先完成本清單第 2 項。
- **備援安排現況**：目前無獨立於 Zeabur 帳號之外的備份存放位置；`docs/reviews/sustainability-master-plan-2026-07-06.md` 第三節建議「每年一次備份還原演練」，目前尚未有第二人執行過這個演練的紀錄。

---

## 使用建議

- 這份檔案應該每年至少更新一次，理想情況下搭配一次實際的傳承演練（讓第二位維護者實際走過取得/重建流程）。
- 若任何一項的「備援安排現況」欄位從「目前無」變成「已有第二人」，請直接更新這一項，不要另開新檔案。
- 機密值一律不進本檔案、不進 git 歷史；需要交接機密值時，使用密碼管理工具或加密管道，並在此檔案的對應項目補一行「交接紀錄：YYYY-MM-DD 已交接給 X」（不含機密值本身）。
