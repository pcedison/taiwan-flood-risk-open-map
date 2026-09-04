# 社群／民間淹水資訊來源查證報告
查證日期：2026-09-03～04（以下每列皆標註查證日期）

合規分級定義（依 SDD）：
L1 官方開放資料｜L2 公開網站/RSS/API（守 robots、頻率、引用）｜L3 公開論壇（低頻、去識別、可關閉，V2 才可）｜L4 需授權平台（如 Meta Content Library，需 ADR）｜L5 規避登入/驗證/反爬或違反條款者永不採用

---

## 總表

| 來源 | 合規分級（理由） | 即時性 | 地點精度 | 取得方式 | 成本/門檻 | 查證 URL | 查證結果摘要 |
|---|---|---|---|---|---|---|---|
| Threads API `/keyword_search` | **L4**（技術上可行，但需 App Review 通過 `threads_keyword_search` 權限才能查「非本人」的公開貼文；未過審只能搜自己帳號的貼文；屬需授權平台，且用途審查方向是行銷/內容應用，非公共安全，建議走 ADR 個案評估） | 準即時（可查詢近期貼文） | 未見地理欄位（文件未提供 geo/location field） | 官方 REST API | 免費（無 Meta 公告的付費方案），但需 App Review／可能需商業驗證；速率限制 2,200 次/使用者/24hr（另一說法：取得 `threads_keyword_search` scope 後為 500 次/7 天） | https://developers.facebook.com/docs/threads/keyword-search/ | 未過 App Review 前只能搜自己帳號貼文；過審後可搜公開貼文但無地理欄位，條款未提及公共安全用途限制也未明文允許 |
| Facebook Graph API 公開貼文關鍵字搜尋 | **L5（死路）**（Public Post Search 自 Graph API v2.0 起已下架，Graph Search 於 2019 年基本停用；現無此功能） | 不適用 | 不適用 | 無 | 不適用 | https://en.wikipedia.org/wiki/Facebook_Graph_Search ；一般開發者討論（Quora/TechCrunch） | 確認：公開貼文關鍵字搜尋已於多年前下架，2026 年現況仍無此 API |
| Instagram Graph API Hashtag Search | **L4/受限**（僅能查「你指定的 hashtag」被標記的貼文，非任意關鍵字全文檢索；需 Business 帳號＋`instagram_basic`/`manage_pages` 權限＋商業驗證；每週僅能查 30 個不重複 hashtag） | 準即時（top/recent） | 無地點精度欄位 | 官方 REST API | 需通過商業驗證；額度極低（30 hashtag/7天），不適合「巷弄淹水」關鍵字式廣泛監測 | https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login/hashtag-search/ | 確認為 hashtag 導向而非關鍵字全文搜尋，額度過低、無地理資訊，不適合本案即時監測用途 |
| Meta Content Library／API | **L4（需 ADR，且申請資格可能不符）**（官方文件僅列「學術機構」或「非營利研究機構」為受理對象；未明文允許政府機關或以「公共安全操作」為目的的申請；且強調資料留在 Meta 的「controlled-access / secure computing platform」內分析，未明確允許匯出到自建系統做營運用途） | 「近即時」（官方宣稱） | 貼文層級（無明確地理過濾說明） | 需送申請、審核通過後於 Meta 提供的 Jupyter controlled-access 環境查詢 | 有起門檻：僅限學術/非營利研究機構身份；且據查 2026 年起 SOMAR VDE 存取加收費用（US$1,000 一次性＋US$371/月，但此為特定學術聯盟方案，非 Meta 官方統一定價，需再次確認是否適用一般申請者）；API 查詢速率上限 60 次同步查詢/分、非同步工作 1 次/分，7 天累積 500,000 筆 | https://transparency.meta.com/researchtools/meta-content-library/ ；https://socialmedialab.ca/web/2024/03/25/a-first-look-at-metas-new-content-library-and-content-library-api/ | 確認：以研究/非營利身份申請、資料只能在 Meta 受控環境內分析，未明文允許匯出做公共安全即時操作；government/operational use 未列為合格申請者類型，若要用需先個案洽詢 Meta 並走 ADR，不保證核准 |
| PTT（批踢踢） | **L3（若做）／需注意 ToS 非商業限制**（`www.ptt.cc/robots.txt` 直接回 404，即站方**未發布** robots.txt，沒有機器可讀的爬蟲政策；但官方「使用者條款 2.0.1」明文限制内容只能「非營利無償使用、修改、重製、公開播送、散布、發行、公開發表」，且引用他人文章不得作商業用途；條款未明文禁止自動化存取本身） | 幾乎即時（人工發文） | 版主/看板層級，內文常含地名但無結構化欄位，需自行 NLP 萃取 | 無官方 API；坊間有大量開源 PTT 爬蟲（走 Web 或 telnet BBS 協定），部分看板需過 18 歲同意頁 | 免費，但需自行開發解析器；若專案非商業/非營利、低頻、可下線，屬可行的 L3 路徑 | https://www.ptt.cc/robots.txt （404）；https://www.ptt.cc/index.ua.html | 確認 robots.txt 不存在（404）；使用者條款明文「非營利無償使用」限制，未提及自動化存取條款。若專案為非營利公共資訊服務、低頻爬取、可去識別、可關閉，落在 L3 範圍內，但仍應遵守非商業限制與禮貌頻率 |
| Dcard | **L5（死路，不建議）**（官方 API `dcard.tw/service/api/v2/posts` 已被鎖閉停用；站方以 Cloudflare 佈署強力反爬（CAPTCHA、IP 封鎖、Error 1020），要繞過即屬「規避反爬機制」） | 不適用 | 不適用 | 舊版 API 已失效；目前僅能透過瀏覽器/Selenium 硬爬，牴觸反爬設計 | 不適用（技術上會被封鎖） | https://www.cloudflare.com/zh-tw/case-studies/dcard/ ；https://home.gamer.com.tw/artwork.php?sn=4891061 ；社群討論（Dcard 軟體工程師版 IP 被擋討論串） | 確認官方 API 已鎖閉、站方積極用 Cloudflare 阻擋自動化存取；未找到 Dcard 服務條款是否明文禁止爬蟲的原文，但技術面已是反爬對抗狀態，符合 SDD 中「規避反爬」的 L5 排除條件 |
| Plurk API | **L2（可行但邊際效益低）**（官方公開文件化的 API，申請流程簡單：填應用名稱、開發者姓名、Email 即可核發 API Key，非審核制） | 可即時（依台灣噗浪活躍度而定） | 無標準地理欄位，需自行從內文萃取 | 官方 REST API，`plurk.com/plurkapi` 線上申請 | 免費、低門檻 | https://www.plurk.com/plurkapi ；https://blog.init.engineer/posts/PlurkAPISpecification/ | 確認申請流程存在且低門檻；但未查得 2026 年台灣活躍用戶規模數據（噗浪近年活躍度已大幅萎縮，具體人數未能查證），實務上訊號量可能過低 |
| Bluesky Jetstream / AT Protocol Firehose | **L2（技術上可行）**（Jetstream 為官方提供、免驗證的 WebSocket，可依關鍵字/語言即時過濾全站貼文流，約 850MB/天流量） | 即時（firehose 等級） | 無地理欄位，需自行 NLP／使用者自填地點萃取 | 官方公開 WebSocket（`jetstream1/2.us-*.bsky.network`），免申請免金鑰 | 免費 | https://docs.bsky.app/blog/jetstream ；https://docs.bsky.app/docs/advanced-guides/firehose | 確認 Jetstream 免費、免驗證、可關鍵字過濾；**未能查證**台灣使用者規模與淹水通報訊號密度是否足夠（一般認知 Bluesky 在台灣滲透率仍低，但無法找到具體統計佐證） |
| NCDR 民生示警公開資料平台（CAP 告警 API） | **L1**（官方開放資料，遵循國際 OASIS CAP v1.2 標準，屬「災防中心資料服務平台」正式服務） | 即時（告警發布即推送） | 依告警發布單位而定，通常為縣市/鄉鎮層級（非巷弄級） | 官方 Alert Query API（HTTP，需申請權杖） | 需申請帳號/token，但屬公開申請、非商業限制不明確（頁面內容抓取受限，僅確認為官方 CAP 標準 API，實際免費與否需人工申請確認） | https://alerts.ncdr.nat.gov.tw/alertMessageAPI.aspx ；https://datahub.ncdr.nat.gov.tw/paradigm | 確認此為官方 CAP 標準告警 API，涵蓋天氣/水文/民生/交通等 38 類警示；但頁面為前端渲染，WebFetch 未能取得完整內容細節（如是否含「淹水」告警類別、確切費用），建議實際登入平台或去信洽詢確認 |
| 經濟部水利署「水利資料開放平台」OPEN API（含災情地圖／淹水通報點位） | **L1**（官方開放資料平台，`opendata.wra.gov.tw/openapi`；災情地圖介接水利署淹水通報案件，含民眾透過「行動水情」App 通報的積淹水點位） | **每 10 分鐘**更新一次當日所有通報案件（近即時，是本次查證中即時性最佳的官方來源之一） | 含**座標**（淹水位置座標）＋災情描述＋退水狀態，精度優於行政區層級，但未必到巷弄門牌 | 官方 OPEN API（`opendata.wra.gov.tw/openapi`，Swagger 文件於 `/openapi/swagger/index.html`）；另有水資源物聯網 IoT API（`iot.wra.gov.tw`） | 需**會員註冊＋信箱驗證**取得 API 認證資訊，之後免費使用 | https://opendata.wra.gov.tw/openapi ；https://fhy.wra.gov.tw/fhyv2/monitor/disasterMap （前端頁面，JS 渲染，WebFetch 無法取得內容，以 WebSearch 交叉確認技術細節） | **本次查證中最推薦的路徑之一**：官方已將「行動水情」App 民眾通報的積淹水案件（含座標）以每 10 分鐘頻率整併進災情地圖，並透過開放資料平台 OPEN API 對外提供，只需註冊會員即可取得金鑰。建議專案負責人實際註冊確認資料集清單中是否包含此災情地圖點位資料集（原始頁面為前端渲染，未能直接摘錄逐欄位規格，需人工登入平台核對） |
| 各縣市 1999/陳情系統開放資料 | **L1（有限）**（如台北市 1999 陳情系統資料集已上架 data.gov.tw，但屬陳情案件統計/內容，非結構化「即時淹水通報」專用資料集） | 非即時（統計性質，非逐筆即時通報流） | 未見巷弄級結構化座標欄位 | data.gov.tw 開放資料下載 | 免費 | https://data.gov.tw/dataset/121715 | 確認台北市 1999 資料集存在於 data.gov.tw，但屬陳情紀錄性質，未見即時淹水專用結構化 API；其他縣市（新北、高雄）1999 開放資料**未能查證**是否有對應資料集 |
| 臺北市降雨積水模擬圖 | **L1（但非本案需求）**（data.gov.tw 官方資料集，KML 格式） | **非即時**：為每 5 年更新一次的水利模擬模型，非即時通報，官方文件明載「無法模擬單一颱風/水災事件的實際淹水情況」 | 有座標（KML/WGS84），但為「潛勢模擬」非「實際回報」 | 開放資料平台直接下載 KML 檔 | 免費，無需申請 | https://data.gov.tw/dataset/121550 | 確認為靜態模擬圖資，非群眾回報或即時感測資料，不適合作為即時淹水資訊來源，僅適合底圖疊圖參考 |
| 臺北市積水資訊網（heovcenter.gov.taipei/TpeFloodRecord） | **未能查證**（WebFetch 回傳 HTTP 500，可能為前端渲染或暫時性錯誤，未能取得頁面內容確認其資料是否即時、是否有 API） | 未能查證 | 未能查證 | 未能查證 | 未能查證 | https://heovcenter.gov.taipei/TpeFloodRecord/ | 從搜尋結果標題判斷疑似為台北市工務局水利工程處的積水地圖前端，但技術查證失敗，建議人工瀏覽器開啟確認 |
| g0v／台灣公民科技「淹水回報」類專案 | **未能查證**（多輪搜尋未找到現存、活躍、具名的「淹水回報」g0v 專案或其 API/資料授權條款；找到的多是官方水利署/NCDR 系統，並非民間協作專案） | 未能查證 | 未能查證 | 未能查證 | 未能查證 | https://g0v.tw/ ；https://github.com/g0v/awesome-g0v ；https://jothon.g0v.tw/events/ | 未能查證是否仍有活躍的 g0v 淹水回報專案；建議直接於 g0v Slack／hackmd 或近期黑客松共筆搜尋關鍵字確認，而非僅靠公開網頁搜尋引擎索引 |
| 地方政府 LINE 官方帳號／災防推播 | **L1/L2 混合**（NCDR 全民防災 LINE 官方帳號訂閱數已破 120 萬，提供 38 類分眾告警含水文類；台北市水利工程處另有專屬 LINE 帳號＋「水情訊息服務平台」可依累積雨量 40mm 門檻推播 SMS/LINE） | 即時（告警觸發即推送） | 依訂閱設定的行政區/區域，非巷弄級 | 這些屬於「訂閱式推播」而非機器可讀開放資料流；NCDR 的告警底層數據已對應到上述「民生示警公開資料平台」CAP API | 免費訂閱給一般民眾；但若要「機器讀取」需回到 CAP API 而非直接扒 LINE 訊息（LINE 官方帳號訊息內容目前無對外開放的機器讀取 API） | https://www.ncdr.nat.gov.tw/Message/MessageView?itemid=4771&mid=70 ；https://heo.gov.taipei/News_Content.aspx?n=1FE45A3FEA3D194E | 確認 LINE 為觸達民眾的推播管道，但機器可讀的規格化資料本體仍是同一份 NCDR CAP 告警 API；LINE 本身不是可程式化擷取「淹水/積水」訊息內容的來源 |
| Waze for Cities Taiwan（道路積水回報） | **未能查證**（僅查到 Waze 於 2017 年進入台灣市場的行銷新聞，以及 Waze for Cities 專案的一般性介紹頁面，未查到台灣任何政府機關與 Waze for Cities／CCP 有正式資料合作的公開證據） | 未能查證 | 未能查證 | 未能查證 | 未能查證 | https://www.waze.com/wazeforcities/ | 未能查證台灣是否已有政府單位加入 Waze for Cities Data/CCP 合作；若負責人有意採用，需直接向 Waze for Cities 團隊洽詢是否受理台灣申請 |

---

## 逐項說明

### 1. Meta Threads API（keyword_search）
需 App Review 通過 `threads_keyword_search` 權限才能搜尋「非本人」的公開貼文；未過審前只能搜自己帳號貼文。速率限制每使用者 2,200 次/24hr（另一資料來源稱進階權限為 500 次/7天）。**文件未提供地理欄位**，也未見任何公共安全/災防用途的明文允許或禁止條款。技術上「可以做」但要通過 App Review／可能的商業驗證，且缺地理資訊、需自行做地名 NLP，性價比中等。判為 **L4**：需要走正式審核流程，且屬第三方商業平台條款約束範圍，建議走 ADR 決策再申請，不宜視為預設可行路徑。

### 2. Facebook／Instagram Graph API
Facebook 公開貼文關鍵字搜尋已於 Graph API v2.0（約 2015 年起）永久下架，2019 年 Graph Search 全面停用，**此路已死（L5/不適用）**。Instagram Hashtag Search 仍存在，但只能查「你指定的特定 hashtag」而非任意關鍵字全文，且每週僅能查 30 個不重複 hashtag、需 Business 帳號與商業驗證，額度過低，不適合做「巷弄淹水」廣泛即時監測。

### 3. Meta Content Library／API
官方明文將受理對象限定在「學術機構」或「非營利研究機構」，**政府機關/公共安全操作用途未列為合格申請者類型**，且資料設計上是留在 Meta 提供的受控研究環境（secure computing platform）內分析，並非用來匯出做自建系統的營運用途。即使核准，也是研究導向而非災防即時系統的合適底層資料源。判定 **L4，且需先個案洽詢 Meta 確認申請資格，走 ADR，不保證核准**。

### 4. PTT
`www.ptt.cc/robots.txt` 直接查證回傳 **404**（站方未發布 robots.txt），代表沒有機器可讀的爬蟲排除協議可依循，但官方「使用者條款 2.0.1」（ptt.cc/index.ua.html）明文將內容使用限制在「非營利無償使用、修改、重製、公開播送、散布、發行、公開發表」，且引用他人文章不得作商業用途。條款本身未特別針對「自動化程式存取」表態。若專案定位為非營利公共資訊服務、維持低頻、可去識別、可隨時關閉，落在 SDD 的 **L3**（公開論壇、低頻、可關閉）合理範圍內，但需留意「非商業」限制與部分看板的 18 歲同意門檻。

### 5. Dcard
確認官方 API（v2/posts）已被鎖閉停用，且站方用 Cloudflare 積極部署反爬機制（CAPTCHA、IP 封鎖、Error 1020）。任何形式的自動化擷取都是在對抗站方明確設置的反爬防線，直接落入 SDD 定義的 **L5「規避反爬」永不採用**類別。

### 6. Plurk API／Bluesky Jetstream
兩者技術上都合規、免費、低門檻（Plurk 線上申請即發 Key；Bluesky Jetstream 免驗證直接連 WebSocket），可歸類 **L2**。但兩者共同弱點是**台灣活躍用戶規模與淹水通報訊號密度均未能查證到具體數據**，實務上可能訊號稀疏、CP 值偏低，建議僅作為候選觀察源，不宜優先投入開發資源。

### 7. 台灣官方群眾通報／開放資料（本次查證最有價值的發現）
最關鍵的正向發現：**經濟部水利署「水利資料開放平台」OPEN API**（`opendata.wra.gov.tw/openapi`）背後已將「行動水情」App 的**民眾通報積淹水案件**（含座標、災情描述、退水狀態）整併進「防災資訊網」災情地圖，且**每 10 分鐘更新一次**。取得方式是官方會員註冊＋信箱驗證換取 API 金鑰，屬**L1 官方開放資料**，即時性與地點精度都優於本次查證的其他選項。惟原始頁面為前端 JS 渲染，WebFetch 無法直接取得逐欄位規格與資料集正式名稱，**建議專案負責人或工程side 實際登入 opendata.wra.gov.tw 註冊帳號、查詢資料集清單以核實**這份「災情地圖/淹水通報點位」資料集是否包含在對外開放的 API 目錄中（有可能只在防災資訊網內部使用，未必公開在 OPEN API 目錄）。

另外，**NCDR 民生示警公開資料平台**提供符合國際 OASIS CAP v1.2 標準的告警 Query API，屬官方 L1 資料源，但頁面同樣前端渲染，未能查證是否含「淹水/積水」告警分類與確切費用/頻率限制，需人工申請確認。

台北市 1999 陳情系統與各縣市開放資料平台，目前只查到**陳情案件統計/內容**資料集，非結構化即時淹水通報專用格式；台北市「降雨積水模擬圖」是**每 5 年**更新的靜態水利模型，官方明文聲明不能反映單一颱風/水災的實際情況，不適合作為即時來源。

### 8. g0v／公民科技淹水回報專案、臺北市積水資訊網、Waze for Cities Taiwan
三項均**未能查證**：多輪搜尋未能找到現存、活躍且具名的 g0v 淹水回報協作專案；臺北市積水資訊網頁面回傳 HTTP 500（可能是前端渲染或暫時性錯誤）；Waze for Cities 僅查到 2017 年市場行銷新聞，未查到台灣政府與其資料合作的公開證據。三者都建議另行人工查證（分別是：直接搜尋 g0v Slack/hackmd 近期黑客松紀錄、用瀏覽器人工開啟積水資訊網頁面、直接去信 Waze for Cities 團隊詢問台灣受理狀況），不應僅憑本次搜尋引擎查詢結果判定為死路。

---

## 查證侷限
- 本次共使用約 30 次 WebSearch/WebFetch 工具呼叫，多個官方頁面為前端 JS 渲染（NCDR CAP API 頁、水利署災情地圖頁、臺北市積水資訊網），WebFetch 只能拿到部分或空白內容，這些項目的細節（是否含「淹水」分類、確切費用、資料集正式名稱）需要人工登入或用瀏覽器實測才能補完，已在表格中逐一標註。
- Bluesky／Plurk 的台灣活躍用戶規模、g0v 專案現況、Waze for Cities 台灣合作狀態，均未查得具體證據，列為「未能查證」而非臆測。
