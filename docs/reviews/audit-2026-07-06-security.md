# Flood Risk 安全稽核報告

- 稽核對象：repo `Flood Risk`（工作分支 `audit/sustainability-2026-07-06` 對齊最新 `origin/main`；實際檢查於 checkout `codex/right-sidebar-readability`，HEAD `62f008d`，程式內容一致）
- 稽核日期：2026-07-06
- 範圍：apps/api（FastAPI）、apps/workers（ingestion）、apps/web（Next.js）、infra、Dockerfile、docker-compose、.github/workflows
- 立場：假設有漏洞，主動找出
- Finding 總數：**9**（Critical 0 / High 2 / Medium 2 / Low 5）
- 說明：`.worktrees/` 底下有一份 repo 副本，已排除，只稽核主樹。

---

## High

### H-1　速率限制以反向代理 IP 作 key → 淹水尖峰全站自我 DoS，且無法辨識個別濫用者
**檔案:行號**
- `apps/api/app/api/routes/public.py:538-547`（`_client_signal` 預設回傳 `request.client.host`）
- `apps/api/app/api/routes/public.py:527-535`（`_public_rate_limit_client_key`）
- `Dockerfile:127`（`uvicorn app.main:app --host ... --port ...`，**未加** `--proxy-headers` / `--forwarded-allow-ips`）
- `apps/web/next.config.mjs:12-27`（`/v1/:path*` 於伺服器端 rewrite 代理到 `http://127.0.0.1:8000`）
- `apps/api/app/core/config.py:195-198,212-216`（`public_rate_limit_enabled` 在 staging/production 預設 true；risk 30/60s、geocode 60/60s）
- `Dockerfile:65`（`ENV APP_ENV=staging` 內建於映像 → hosted 判定成立、限流啟用）

**失敗情境**
瀏覽器同源呼叫 `/v1/risk/assess` → Next.js 於**伺服器端**代理到 `127.0.0.1:8000`。uvicorn 未啟用 proxy headers，且預設 `PUBLIC_RATE_LIMIT_CLIENT_HEADER` 為空，因此 API 對**所有**公開流量看到的 `request.client.host` 都是 `127.0.0.1`，全部 hash 進同一個限流 bucket。後果：
1. 淹水事件（正是服務最需要可用的時刻）大量民眾查詢時，全站被限制在「每 60 秒 30 次風險評估 / 60 次 geocode」，觸發 429 讓所有人失敗。
2. 單一攻擊者送 31 個請求即可讓全體使用者被限流（自我 DoS）。
3. 限流完全無法區分個別客戶端，等同失去濫用防護的核心價值。

**另一種設定同樣有漏洞**：若營運者為了取得真實 IP 而設 `PUBLIC_RATE_LIMIT_CLIENT_HEADER=X-Forwarded-For`，`_client_signal`（public.py:542）取的是逗號分隔的**最左值**，而最左的 XFF 由客戶端可控 → 攻擊者每次輪換 `X-Forwarded-For` 標頭即可**完全繞過**限流。

**嚴重度**：High（公益避難服務尖峰可用性 + 濫用防護失效）

**修法建議**
- uvicorn 以 `--proxy-headers --forwarded-allow-ips=127.0.0.1` 啟動，只信任 Next 這一跳；由 Next 傳遞真實客端 IP。
- 解析 XFF 時取**最右側**未受信任的一段，或改用平台提供的可信標頭（Zeabur/Cloudflare 的 `CF-Connecting-IP`）。切勿信任最左 XFF。
- 驗證方式：部署後帶入 `X-Forwarded-For: 1.2.3.4` 與省略該標頭各打 40 次 `/v1/risk/assess`，觀察 429 是否依「真實來源」而非全域計數，且偽造標頭無法重置計數。

---

### H-2　隱私：精確座標與原始搜尋文字被無限期落地，違反已核可的 ADR-0006
**檔案:行號**
- `apps/api/app/domain/evidence/repository.py:127-216`（`persist_risk_assessment` INSERT `location_queries`：`raw_input`=使用者輸入的原始地址文字、`lat`/`lng` 完整浮點精度、`geom` 精確點位）
- `apps/api/app/domain/evidence/repository.py:1197-1198`（`_privacy_bucket` 只做 2 位小數約 1km 粗化，但精確值仍與其並存寫入）
- `apps/api/app/api/routes/public.py:894-944` → `_persist_assessment`（每次 `/v1/risk/assess` 且 `evidence_repository_enabled` 時呼叫；預設 true、hosted true）
- `apps/workers/app/jobs/evidence_retention.py:150`（保留清理**只**刪 `evidence`，`location_queries` 從不清理 → 無限期保留）
- 政策：`docs/adr/0006-privacy-preserving-query-heat.md:25`（狀態 Accepted）：「Do not store raw addresses, raw query text, persistent user identifiers, or precise user-selected coordinates.」

**失敗情境**
使用者查詢自家住址時，`location_queries` 永久保存其「精確經緯度 + 原始輸入地址字串 + 時間戳」。這正是 ADR-0006 明文要避免的「敏感搜尋歷史／居住利益資料庫」。雖然對外的 query-heat 端點只輸出粗化桶與門檻（未直接外洩），但此持久化資料在資料外洩、內部濫用或司法調取時即暴露高度敏感資訊，且與已核可的隱私決策直接牴觸——對公益服務是重大公眾信任風險。

**嚴重度**：High（公眾信任 + 直接違反已核可隱私 ADR；資料無保存上限）

**修法建議**
- `location_queries` 只保存 `privacy_bucket`/`h3_index`（粗化）供 query-heat 使用；移除 `raw_input` 與精確 `lat`/`lng`/`geom`，或至少座標粗化並加短 TTL 清理。
- 為 `location_queries` 加入保留清理（比照 evidence retention job）。
- 驗證方式：本機 `APP_ENV=production` 跑一次 `/v1/risk/assess`，`SELECT raw_input, lat, lng FROM location_queries` 確認不再有精確值；並確認 retention job 會清理逾期列。

---

## Medium

### M-1　Web 與 API 皆未輸出安全性標頭 / CSP
**檔案:行號**
- `apps/web/next.config.mjs:8-30`（無 `headers()`；缺 CSP、`X-Frame-Options`/`frame-ancestors`、`X-Content-Type-Options`、`Referrer-Policy`、HSTS）
- `apps/api/app/main.py:33-40`（僅加 CORS，無安全標頭）
- 已 grep 確認 web 全樹無任何 CSP/X-Frame/HSTS 設定。

**失敗情境**：頁面可被任意站點 iframe（clickjacking）；瀏覽器 MIME sniffing；一旦有任何注入點無 CSP 兜底。對外公開地圖 + 外部連結場景，屬縱深防禦缺口。

**嚴重度**：Medium

**修法建議**：在 `next.config.mjs` 加 `headers()`：`Content-Security-Policy`（`script-src 'self'`、`frame-ancestors 'none'`、明列 basemap/tile 來源）、`X-Content-Type-Options: nosniff`、`Referrer-Policy: strict-origin-when-cross-origin`、`Strict-Transport-Security`。

### M-2　容器以 root 執行
**檔案:行號**：`Dockerfile:44-213`（runtime stage 無 `USER` 指令；uvicorn/next/scheduler 全部以 uid 0 執行）

**失敗情境**：應用層任何 RCE 或任意檔案寫入將以容器內 root 身分執行，爆炸半徑更大，且應用檔可被覆寫。

**嚴重度**：Medium

**修法建議**：新增非 root 使用者（`useradd`），`chown` 應用目錄後 `USER app`；確認 `/opt/venv`、`.next` 權限相容。

---

## Low

### L-1　證據「開啟原始出處」連結渲染前未驗證 URL scheme
**檔案:行號**：`apps/web/app/components/evidence-section.tsx:80-89`（`href={sourceUrl}`）；`apps/web/app/lib/risk-display.ts:459-460`（原封回傳 `item.url ?? item.source_url`）。URL 來源含新聞 RSS `<link>`。
**說明**：React 不會過濾 `javascript:`/`data:` href。目前 feed 為 Google/Bing/Wikipedia（https，可信），非直接可利用故列 Low。已使用 `rel="noreferrer"`（無反向 tabnabbing）。
**修法**：渲染前檢查 scheme ∈ {http,https}，並補 `rel="noopener"`。

### L-2　static challenge 驗證使用非常數時間比較
**檔案:行號**：`apps/api/app/domain/reports/challenge.py:58`（`token != self.expected_token`）。static provider 非生產路徑（生產預設 turnstile），故 Low。
**修法**：改用 `secrets.compare_digest`；並確保 static provider 不用於生產。

### L-3　GitHub Actions 釘在可變的大版本 tag 而非 commit SHA
**檔案:行號**：`.github/workflows/ci.yml:16,19,63,66,71,118`、`hosted-monitoring.yml:40,43,279,289,366` 等使用 `actions/checkout@v5`、`setup-python@v6`、`github-script@v8`、`upload-artifact@v6`。
**說明**：`hosted-monitoring.yml:31` 的 job env 帶有 `ADMIN_BEARER_TOKEN`；若上游 action 被重新打 tag/被入侵可在該 workflow 執行。**緩解已存在**：CI 使用 `pull_request`（非 `pull_request_target`），且各 workflow 有最小權限 `permissions:` 區塊、無 fork PR 觸發密鑰路徑。
**修法**：將 actions 釘到完整 commit SHA。

### L-4　FastAPI 互動式文件與 OpenAPI schema 對外公開
**檔案:行號**：`apps/api/app/main.py:28-32`（未關閉 `/docs`、`/redoc`、`/openapi.json`）；`apps/api/app/api/routes/admin.py:54`（admin 端點 `tags=["Admin"]` 出現在 schema）。
**說明**：完整 API 面（含 admin 路由路徑）被揭露，惟 admin 端點仍受 bearer 保護；屬資訊揭露。
**修法**：生產環境關閉或加保護 docs/openapi。

### L-5　外部 XML 以 `xml.etree.ElementTree` 解析（billion-laughs DoS 理論風險）
**檔案:行號**：`apps/api/app/domain/history/news_enrichment.py:921`、`apps/workers/app/adapters/ncdr/cap_alerts.py:285`、`apps/workers/app/adapters/local_kinmen/kwis.py:365`、`.../local_nantou/water.py:130`、`.../local_taoyuan/water.py:352,560`。
**說明**：ElementTree 對 XXE／外部實體／SSRF 本身安全（Python 不解析外部實體），但對實體展開（billion laughs）DoS 有理論脆弱性。來源多為政府/新聞可信端點，故 Low。
**修法**：對外部抓取的 XML 改用 `defusedxml` 作縱深防禦。

---

## 零 Finding 面向之檢查覆蓋聲明

**機密管理（無 finding）**：檢查 `.env.example`（全為 `change-me-local`/空白佔位，無真值）；`git grep` 掃描 AKIA/ghp_/xox/PEM/password=/secret=/token= 等樣式（僅命中 `CWA-DEMO-*` 站台 ID，非密鑰）；`git ls-files` 確認唯一追蹤的 env 檔為 `.env.example`；`.gitignore:12-14` 已忽略 `.env` / `.env.*`。無 hardcoded secret。

**AuthN/AuthZ（無 finding）**：`apps/api/app/api/routes/admin.py:580-601` `_require_admin` 使用 `secrets.compare_digest`（常數時間）；缺 token 回 401；`ADMIN_BEARER_TOKEN` 未設定時 fail-closed 回 403（admin.py:590-594）；所有 admin 路由都經 `Depends(_require_admin)`（admin.py:278-577）。實作正確。

**SQL 注入（無 finding）**：`git grep` 未發現任何以 f-string/`.format`/`%`/字串拼接把使用者輸入帶入 `execute()`。逐一檢視 `admin.py:615-760`（`%s` 參數化）、`evidence/repository.py:127-343,862-964`（`%s` + PostGIS `ST_*` 參數化）、`geocoding/providers.py:781-788`（named params）、`geocoding/postgis_bootstrap.py`（參數化）、`tiles/repository.py:130-205`（欄位/子查詢皆為 `_LAYER_SPECS` 硬編碼常數，`layer_id` 以 `%s` 帶入）。

**SSRF（無 finding）**：`public_geocoding.py:27-28,64-82,146-181` 抓取端點為固定 host（Nominatim/Wikimedia），使用者查詢僅經 `urlencode` 當 query 參數；`news_enrichment.py:26-36` 端點為固定 host（Google News/Bing/Wikipedia/GDELT）；`challenge.py:87-92` verify_url 為營運者設定；worker adapters URL 皆來自 `os.getenv`（`config.py:561-594`）由營運者控制，非使用者輸入。無使用者可操縱之抓取 URL。輸入邊界：`schemas.py:411-419,529-533` `radius_m` 限 50-2000、`query`/`location_text` ≤300、`limit` 1-10、lat/lng 值域受限。

**前端 XSS（除 L-1 外無 finding）**：`git grep` 確認 apps/web 全樹無 `dangerouslySetInnerHTML`/`innerHTML`/`eval`/`document.write`。使用者提供之報告 summary 僅回給 admin 檢視、經 React 文字節點轉義。

**供應鏈/CI（除 L-3 外無 finding）**：全部 workflow 使用 `on: pull_request`（非 `pull_request_target`），無 fork PR 觸發密鑰之風險；各 job 有最小權限 `permissions:`；`hosted-monitoring.yml` 僅 `workflow_dispatch`/`schedule` 觸發，密鑰以 env 傳入 Python 腳本而非命令列。Docker base image 為官方 `node:22-bookworm-slim` / `python:3.12-slim`（pinned major）。
