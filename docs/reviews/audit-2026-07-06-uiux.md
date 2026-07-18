# Flood Risk (floodrisk.cc) — apps/web UI/UX、易用性、配色稽核報告

稽核範圍：`apps/web/app/**`（頁面、元件、`lib/`、`globals.css`）。純程式碼／樣式審查，未啟動瀏覽器。
分支：`audit/sustainability-2026-07-06`（等同 `origin/main`，稽核時 working tree clean）。
視角：第一次到訪、不懂技術的一般使用者（購屋者／租屋者／長輩），評估從進站到看懂風險結果的摩擦點。

讀過的檔案：
- `app/page.tsx`, `app/layout.tsx`, `app/globals.css`
- `app/components/search-form.tsx`, `risk-summary-section.tsx`, `nearby-sensing-section.tsx`,
  `nearby-coverage-section.tsx`, `evidence-section.tsx`, `user-report-section.tsx`, `diagnostics-section.tsx`,
  `use-flood-map.ts`
- `app/lib/risk-display.ts`, `ui-text.ts`, `map-setup.ts`, `basemap-style.ts`, `api-client.ts`, `page-types.ts`

總計 **21 項 finding**：阻斷 3、摩擦 11、打磨 7。

---

## 阻斷（用不下去 / 會造成真實傷害）

### B1. 唯一的「非官方警示」被收合在英文標題的 accordion 裡，風險結果旁完全沒有重複警語
- **檔案**：`app/components/search-form.tsx:29-35`、`app/lib/ui-text.ts:16-19`（`betaLimitTitle`/`betaLimitMessage`）；
  對照 `app/components/risk-summary-section.tsx` 全檔案 — 風險結果區塊沒有任何警語。
- **情境**：長輩或首次使用者搜尋地址後，直接看到「綜合風險：高」文字＋地圖上深紅色罩色。畫面上唯一的免責聲明是
  頁面最上方一個預設**收合**的 `<details>`，標題還用了英文「Public beta 使用限制」——不懂英文的長輩很可能完全
  略過。使用者可能誤以為這是官方即時淹水通報，據此做出是否續住/購屋等重大決策。這正是題目強調的「過度信任是
  真實傷害」的核心風險點。
- **建議**：標題改成純中文且更醒目（例如「重要提醒：本工具非官方即時災防通報」）；預設展開，或至少在
  `RiskSummarySection` 的結果卡片本身重複一行簡短警語＋緊急資源連結。

### B2. 搜尋／查詢錯誤訊息沒有 ARIA live region，螢幕報讀器使用者收不到通知
- **檔案**：`app/components/search-form.tsx:68-69`
  ```tsx
  {errorMessage ? <p className="form-error">{errorMessage}</p> : null}
  {geocodeNotice ? <p className="form-notice">{geocodeNotice}</p> : null}
  ```
  同樣問題也出現在 `app/components/user-report-section.tsx:68-70`（`form-error`）。
  對照：`evidence-section.tsx:56,62,136` 和 `risk-summary-section.tsx:80` 的狀態訊息都正確加了
  `role="status"`/`role="alert"`，唯獨這兩處「查詢失敗」路徑漏掉。
- **情境**：視障使用者用螢幕報讀器打字搜尋地址、按下「查詢風險」，若地址找不到（`noGeocodeResult`）、API 逾時
  或被限流，畫面上會冒出新的 `<p>` 文字，但沒有 `aria-live`/`role="alert"`，報讀器不會自動唸出。使用者只會聽到
  按鈕從「查詢中」變回「查詢風險」，完全不知道發生了什麼事、也不知道下一步。這是核心流程（搜尋→看到結果或
  錯誤）對螢幕報讀器使用者靜默失敗。
- **建議**：`.form-error` 加 `role="alert"`；`.form-notice` 加 `role="status"`（或都用 `aria-live`）。

### B3. 全站只有一個 `<h1>`，所有區塊標題都不是語意標題
- **檔案**：`app/globals.css:507-524`（`.section-heading`/`.section-kicker` 樣式）；實際使用處：
  `risk-summary-section.tsx:46`、`nearby-sensing-section.tsx:26`、`evidence-section.tsx:36`、
  `diagnostics-section.tsx:55,71,92,158,209`、`user-report-section.tsx:37,50`、`nearby-coverage-section.tsx:26`
  ——全部是 `<strong>{...}</strong>` 包在 `<div className="section-heading">` 裡，不是 `<h2>/<h3>`。
  全頁唯一的標題元素是 `app/page.tsx:308` 的 `<h1>{text.title}</h1>`。
- **情境**：螢幕報讀器使用者慣用「跳到下一個標題」快速掃過頁面結構（NVDA/VoiceOver 的核心導覽方式），但這個
  資訊量很大的側欄（風險摘要／附近即時感測／資料證據／民眾通報／診斷資訊）完全沒有次級標題，視障使用者必須
  從頭到尾逐字聽完整個側欄，才能找到「風險摘要」在哪裡。
- **建議**：把 `.section-heading strong` 改成 `<h2>`（或 `<h3>`），可保留現有視覺樣式，只換標籤。

---

## 摩擦（會困惑 / 誤導）

### F1. 搜尋欄位可視標籤「搜尋地點」被 `aria-label` 覆蓋成完全不同的文字（WCAG 2.5.3 Label in Name 失敗）
- **檔案**：`app/components/search-form.tsx:37-44`
  ```tsx
  <label className="field">
    <span>{text.searchPlace}</span>          {/* "搜尋地點" */}
    <input ... aria-label={text.searchPlaceholder} />  {/* "輸入地標、地址或行政區" */}
  </label>
  ```
- **情境**：`aria-label` 會覆蓋原生 `<label>` 包裹產生的可及名稱。畫面上寫「搜尋地點」，但這個欄位對輔助
  科技（含語音操控）而言的名稱其實是「輸入地標、地址或行政區」，兩者完全不同字串。用語音下指令「點選搜尋
  地點」的使用者會對不上目標而操作失敗。
- **建議**：拿掉 `aria-label`，讓可視 `<span>` 自然成為可及名稱；`placeholder` 已足夠提示格式。

### F2. 所有時間戳記都不顯示年份，可能誤導使用者以為資料很新
- **檔案**：`app/lib/risk-display.ts:448-457`
  ```ts
  export function formatDateTime(value, options) {
    ...
    return new Intl.DateTimeFormat("zh-TW", {
      day: "2-digit", hour: "2-digit", minute: "2-digit", month: "2-digit", timeZone: options?.timeZone,
    }).format(new Date(value));
  }
  ```
  此函式驅動證據卡片「觀測」時間（`evidence-section.tsx:100`）、資料新鮮度「最後同步」
  （`diagnostics-section.tsx:183,216`）、附近觀測「最近觀測」（`diagnostics-section.tsx:130`）等**全站所有**
  時間顯示，全部只有 `MM/DD HH:mm`，沒有年份。
- **情境**：使用者看到證據卡片寫「觀測 07/06 14:32」會直覺當作「今年」的資料。但淹水潛勢圖資、歷史事件、
  甚至某些即時來源退化後的殘留紀錄常常掛著好幾年沒更新，系統完全沒有告知年份，使用者無從分辨這是剛剛的
  觀測還是三年前的存檔——這正是題目點名的「資料新鮮度可能誤導」核心情境，而且是一個公開資料淹水風險工具
  最不該出錯的地方。
- **建議**：一律附加年份（跨年份時顯示、或永遠顯示 `yyyy/MM/dd HH:mm`）。

### F3. 風險等級的紅／綠配色在紅綠色盲使用者眼中幾乎等亮度，地圖本身沒有替代編碼
- **檔案**：`app/lib/risk-display.ts:219-248`（`riskOverlayByLevel`）、`app/globals.css:708-714`（`.risk-meter`
  漸層 `linear-gradient(90deg, #4b9e71, #e0b54d, #c85d35)`）。
- **實測色值與相對亮度（WCAG relative luminance）**：
  - 低風險 `#2f8f5b`（綠）→ 相對亮度 ≈ **0.210**
  - 高風險 `#cf4f35`（紅橙）→ 相對亮度 ≈ **0.191**
  - 兩者亮度差僅 **ΔL ≈ 0.02**，且色相剛好落在紅綠色盲（deuteranopia/protanopia，約 8% 男性）最難分辨的軸線上。
- **情境**：地圖上圈選範圍的罩色（`riskOverlayPresentation`）與 `.risk-meter` 進度條都是綠→黃→紅漸層。紅綠色盲
  使用者在**地圖本身**（此產品最核心的互動介面）幾乎無法單靠顏色分辨「安全」與「危險」，因為兩端顏色亮度
  幾乎相同、色相又是最容易混淆的一對。側欄雖有文字「低/高」可補救，但地圖是產品定位的「map-first」入口，
  地圖本身缺乏色相以外的編碼。
- **建議**：地圖圈選邊框依等級改變線型（實線/虛線/點狀）或加上等級圖示，不要只靠 fill 色相。

### F4. 側欄「即時／歷史參考／資料信心」數值永遠是同一種黑色文字，沒有沿用地圖的風險配色
- **檔案**：`app/globals.css:804-816`
  ```css
  .risk-levels dd { margin: 0; color: var(--foreground); font-size: 1.15rem; font-weight: 900; }
  ```
  無論值是「低」「中」「高」「極高」，`dd` 顏色都是同一個 `--foreground`（`#17201d`）。
- **情境**：使用者想快速對照地圖顏色跟側欄數字是否一致，但側欄「高」跟「低」文字看起來一模一樣（都是黑色
  粗體），只能靠讀字辨認，對急著判斷或識字較慢的長輩不夠直覺，也和地圖的顏色語言不一致。
- **建議**：用既有的 `riskOverlayPresentation` 色票替 `dd` 依等級上色。

### F5. 風險判讀說明文字夾雜未翻譯英文詞與分析師口吻
- **檔案**：`app/lib/risk-display.ts:926-970`（`getProfilePreviewState`/`getProfileBasisText`，字串內含
  「區域 **profile** 初步結果」「精準半徑資料會由**背景工作**更新」「這不是系統錯誤，而是本次 **profile**
  未納入的資料來源」）；`app/lib/risk-display.ts:293-312`（`riskSummaryDecisionText`：「資料信心（X）只描述
  證據可靠度，不會單獨拉高風險」）。
- **情境**：一般購屋者、長輩看到「profile」「背景工作」這類工程詞彙不知所云；「資料信心只描述證據可靠度，
  不會單獨拉高風險」這種統計/分析語氣的句子，對非技術讀者而言即使逐字讀完也很難建立正確心智模型。
- **建議**：全面改寫成白話文，例如「這是本區域的概略估計，詳細範圍資料還在補齊」。

### F6. 手機版搜尋框（最容易上手的查詢方式）被壓在整版地圖下方，首屏沒有提示
- **檔案**：`app/globals.css:1594-1610`（`@media (max-width: 800px)`：`.map-shell { min-height: 360px;
  max-height: 52vh; }`）；DOM 順序見 `app/page.tsx:304-390`（`map-workspace` 在前、`aside`/`SearchForm` 在後）。
- **情境**：長輩用手機打開網站，第一屏只看到標題＋一大塊地圖，直覺以為只能用手指精準點地圖查詢（小螢幕上
  精準點擊本來就困難），並不知道往下滑就有更容易、更不會出錯的文字搜尋框。`map-hint`
  （`text.mapHint`＝「可拖曳縮放，也可以直接點選地圖更新查詢座標」）只提到地圖操作，沒提到「或往下滑輸入
  地址」。
- **建議**：手機斷點下把搜尋框移到地圖之前，或在地圖提示文字加一句「也可以往下滑輸入地址查詢」。

### F7. 地址找不到時是硬性失敗，沒有候選清單
- **檔案**：`app/page.tsx:182-197`
  ```ts
  const geocode = await postJson<GeocodeResponse>("/v1/geocode", { input_type: "address", limit: 1, query: normalized }, ...);
  const candidate = geocode.candidates[0];
  if (!candidate || candidate.confidence < MIN_GEOCODE_CONFIDENCE) { ...; setErrorMessage(text.noGeocodeResult); return; }
  ```
  `GeocodeResponse.candidates` 型別本身支援多筆（`page-types.ts:16-30`），但前端只請求 `limit: 1` 且只用
  `candidates[0]`。
- **情境**：使用者打錯字、用口語地名（例如「後火車站那邊」）或地址不夠精確時，系統只回「找不到這個地點，
  請換一個關鍵字再試。」，不給任何「你是不是要找…」的候選建議，非技術使用者不知道該怎麼修改關鍵字，容易
  直接放棄。
- **建議**：把 `limit` 提高（例如 5），信心不足時列出候選地點讓使用者選，而不是直接判失敗。

### F8. 最長可達 25 秒的查詢過程中沒有任何進度/等待回饋
- **檔案**：`app/lib/api-client.ts:2`（`API_REQUEST_TIMEOUT_MS = 25_000`）；
  `app/components/search-form.tsx:65-66`（唯一回饋是按鈕文字變成「查詢中」+ `opacity: 0.72`，見
  `app/globals.css:355-358`）。
- **情境**：公開資料查詢在網路狀況不佳或後端負載高時可能要等好幾秒到二十幾秒，畫面上除了按鈕文字外沒有
  spinner、沒有進度說明，使用者很容易以為當機而重新整理頁面或連續點擊，反而中斷原本的請求
  （`page.tsx:167-169` 會 `abort()` 前一個請求）。
- **建議**：加入簡單的載入動畫，或提示文字「公開資料查詢可能需要幾秒，請稍候」。

### F9. 被限流時的訊息不告知使用者要等多久（即使後端已回傳 `Retry-After`）
- **檔案**：`app/lib/api-client.ts:328-353`（`retryAfterSeconds()` 已正確解析 `Retry-After` header／
  `retry_after_seconds`），但 `app/lib/api-client.ts:105-138`（`publicApiErrorMessage`）從未把這個數字放進
  回傳字串，只回固定文案 `RATE_LIMITED_API_ERROR_MESSAGE = "查詢太頻繁，請稍後再試。"`。
- **情境**：被限流的使用者不知道要等 5 秒還是 5 分鐘，容易一直重試而再次被限流。
- **建議**：把 `error.retryAfterSeconds` 插入訊息，例如「請於 30 秒後再試」。

### F10. 次要說明文字的灰色（`--muted`）在最常用的背景上僅勉強壓線 WCAG AA
- **檔案**：`app/globals.css:8`（`--muted: #65736d`），大量使用於說明性內文，例如
  `app/globals.css:553-558`（`.nearby-coverage p`）、`625-631`（`.risk-summary p` 等）、多處 `dt`/`small`/`span`。
- **實測對比度**：
  - `#65736d` on 白底 `#ffffff` → **≈4.97 : 1**（AA 一般文字門檻為 4.5 : 1，剛好壓線）
  - `#65736d` on `--surface-soft` `#f6f8f2` → **≈4.64 : 1**（同樣壓線）
- **情境**：這個顏色用在解釋風險判讀邏輯、資料限制等「內容本身很重要」的說明文字上（不是裝飾性小字），
  字級多在 0.76–0.88rem。對比敏感度隨年齡下降的長輩讀起來會偏灰、吃力，即使自動化對比檢測「勉強過關」，
  實際可讀性仍不理想。
- **建議**：加深到例如 `#52605a`，讓常用內文對比拉開到 6:1 以上。

### F11. 完全沒有指向官方即時災防資源的出口
- **範圍**：檢查了 `app/page.tsx`、所有 section 元件、`ui-text.ts`，全站沒有任何連結指向
  水利署防災資訊網、消防署、112/119 等官方即時管道，也沒有頁尾/關於頁。免責聲明只說「不可視為即時災害通報」，
  卻沒有接著說「那真的遇到淹水該去哪裡查、打給誰」。
- **情境**：真的在下雨天緊張地查這個網站的使用者，看完「不可視為官方通報」的警語後不知道下一步該去哪裡找
  真正即時的官方資訊；如果真的有生命危險，把時間耗在一個非即時工具上，警語本身反而變成沒有出口的死路。
- **建議**：在免責聲明旁或頁尾加上「如遇緊急淹水請撥打 119 / 查詢水利署OO」等連結。

---

## 打磨（更好）

### P1. `--ink` CSS 變數從未定義，`.beta-limit-notice` 的 `color` 宣告是死碼
- **檔案**：`app/globals.css:237`（`color: var(--ink);`）。全專案 grep `--ink` 只有這一處，`:root`
  （`globals.css:1-15`）沒有宣告。該宣告會被忽略、回退成繼承值，不會造成可見錯誤，但屬於誤導性死碼。

### P2. 完全沒有 dark mode
- `:root { color-scheme: light; }`（`globals.css:2`），整份 `globals.css` 沒有任何
  `prefers-color-scheme: dark` 規則。非阻斷，但現代公開網站的常見期待缺席。

### P3. 地圖縮放按鈕（MapLibre `NavigationControl`）預設英文 title/aria-label 未在地化
- **檔案**：`app/components/use-flood-map.ts:80`
  ```ts
  map.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), "top-left");
  ```
  未覆寫按鈕的 `title`/`aria-label`，MapLibre 內建預設是英文（"Zoom in"/"Zoom out"）。中文介面中混入英文
  按鈕提示，對螢幕報讀器或滑鼠停留提示都不一致。

### P4. 瀏覽器分頁標題與頁面 `<h1>` 文字不一致
- `app/layout.tsx:5`：`title: "台灣淹水風險檢視"` → 解碼為
  「台灣淹水風險檢視」；`app/lib/ui-text.ts:7`：`title: "台灣淹水風險開放地圖"`。使用者在瀏覽器分頁/書籤
  看到的名稱跟頁面標題不同，屬小瑕疵。

### P5. 自訂「分析半徑」單選鈕的鍵盤焦點完全不可見
- **檔案**：`app/globals.css:316-320`
  ```css
  .radius-options input { position: absolute; opacity: 0; pointer-events: none; }
  ```
  全份 `globals.css` grep `:focus` 沒有任何一處規則，沒有針對相鄰 `<span>` 補上
  `:focus`/`:focus-visible` 樣式。視力正常但只用鍵盤（含部分肢體障礙、開關裝置）的使用者按 Tab
  切換「分析半徑」選項時，完全看不到目前焦點在哪一個選項上。

### P6. 地圖座標卡片把原始經緯度視覺權重放得比人類可讀地名更高
- **檔案**：`app/globals.css:189-213`（`.map-coordinate-card strong` 承襲較大字重，`span` 只有
  `font-size: 0.8rem`）；對照 `app/page.tsx:323-328`。經緯度（`formatCoordinate`，小數 5 位）用
  `<strong>` 呈現，人類可讀地名（`currentSummary`，例如「已定位：台北火車站」）用較小的 `<span>`。
  對一般使用者而言，地名才是有用資訊，經緯度反而是最沒用但視覺最搶眼的部分。

### P7. 部分行動裝置觸控目標偏小
- 證據卡片「開啟來源」連結（`app/globals.css:1295-1307`，padding `5px 8px`、字級 `0.76rem`，實際高度
  約 24–28px）；`evidence-drawer`/`diagnostics-drawer`/`report-disabled-drawer` 的展開圖示
  （`app/globals.css:401-414`、`1060-1074`，固定 `28px × 28px`）。雖仍高於 WCAG 2.5.8 的 24px 底線，
  但對長輩/肢體操作較不精準的使用者在小螢幕上仍偏緊繃，接近舒適下限。

---

## 覆蓋聲明

本次稽核為純程式碼／樣式閱讀，**未啟動瀏覽器實際操作**，因此：
- 對比度數字為手算 WCAG relative luminance 公式所得（色值均取自原始碼），未用瀏覽器 DevTools 二次驗證。
- 未驗證 MapLibre `NavigationControl` 在實際執行環境下的按鈕文字是否被其他機制（例如全域 i18n polyfill）
  覆寫；程式碼中未找到任何覆寫證據。
- 未實測螢幕報讀器（NVDA/VoiceOver）實際唸出結果，發現皆基於 ARIA/語意 HTML 規範推導。
- 後端 API（`/v1/geocode`、`/v1/risk/assess`）行為以型別定義與前端呼叫方式推斷，未讀後端程式碼，故無法確認
  `candidates` 陣列在 `limit` 提高後是否真的會回傳多筆。
- 未檢查 `apps/web/app/basemap-config/route.ts`、`playwright.config.ts`、測試檔案，以及非 `apps/web` 的其他
  package（如行動端／後端）。
