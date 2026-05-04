import { expect, test } from "@playwright/test";

test("searching a Taiwan landmark moves the map and renders a risk assessment", async ({
  page,
}) => {
  await page.route("http://localhost:8000/v1/geocode", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: {
        candidates: [
          {
            admin_code: "63000000",
            confidence: 0.96,
            name: "台北火車站",
            place_id: "place-test",
            point: { lat: 25.04776, lng: 121.51706 },
            precision: "poi",
            requires_confirmation: false,
            matched_query: "台北火車站",
            limitations: ["定位結果是地標或 POI 座標，不代表門牌精準位置。"],
            source: "mock-geocoder",
            type: "landmark",
          },
        ],
      },
    });
  });

  await page.route("http://localhost:8000/v1/risk/assess", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: {
        assessment_id: "018f3bd2-6e4a-7b10-8d21-3d7fd9676c11",
        confidence: { level: "中" },
        created_at: "2026-04-29T03:00:00Z",
        data_freshness: [
          {
            health_status: "healthy",
            ingested_at: "2026-04-29T02:55:00Z",
            name: "淹水潛勢公開資料",
            observed_at: "2026-04-29T02:50:00Z",
            source_id: "flood-potential",
            message: "目前為開發環境示範資料，尚未連接正式即時圖層。",
          },
        ],
        evidence: [
          {
            confidence: 0.9,
            distance_to_query_m: 0,
            event_type: "flood_potential",
            id: "018f3bd3-1b8f-7ac0-a71d-8c33f7c5073a",
            ingested_at: "2026-04-29T02:55:00Z",
            observed_at: "2026-04-29T02:50:00Z",
            occurred_at: null,
            published_at: "2026-04-29T02:45:00Z",
            source_type: "official",
            source_url: "https://example.test/flood-potential",
            summary: "查詢點位附近有官方開放資料中的淹水潛勢訊號。",
            title: "淹水潛勢公開圖資",
          },
          {
            confidence: 0.72,
            distance_to_query_m: 420,
            event_type: "discussion",
            id: "018f3bd3-1b8f-7ac0-a71d-8c33f7c5073b",
            ingested_at: "2026-04-29T02:40:00Z",
            observed_at: null,
            occurred_at: "2026-04-29T01:30:00Z",
            source_type: "forum",
            summary: "Community report summary",
            title: "Community flood report",
          },
        ],
        evidence_url: null,
        expires_at: "2026-04-29T03:10:00Z",
        explanation: {
          main_reasons: ["查詢半徑內與淹水潛勢圖資相交。"],
          missing_sources: ["尚未接入即時雨量資料。", "尚未接入即時水位資料。"],
          summary: "即時風險為低，歷史參考風險為中，資料信心為中。",
        },
        historical: { level: "中" },
        location: { lat: 25.04776, lng: 121.51706 },
        query_heat: {
          attention_level: "低",
          period: "P7D",
          query_count_bucket: "1-9",
          unique_approx_count_bucket: "1-9",
          updated_at: "2026-04-29T03:00:00Z",
        },
        map_layers: [
          {
            availability: "available",
            feature_count: 12,
            health_status: "healthy",
            kind: "raster-tile",
            layer_id: "flood-potential-demo",
            message: "Tile manifest is available for the selected radius.",
            name: "Flood potential demo layer",
            observed_at: "2026-04-29T02:50:00Z",
            tile_url: "/v1/tiles/flood-potential/{z}/{x}/{y}.png",
          },
          {
            availability: "limited",
            coverage_percent: 34,
            feature_count: 0,
            health_status: "degraded",
            kind: "vector-tile",
            layer_id: "rainfall-limited-demo",
            message: "Rainfall layer is delayed for part of the selected area.",
            name: "Rainfall limited layer",
            observed_at: "2026-04-29T01:30:00Z",
            tile_url: null,
          },
        ],
        radius_m: 500,
        realtime: { level: "低" },
        score_version: "risk-v0.1.0",
      },
    });
  });

  await page.route(
    "http://localhost:8000/v1/evidence/018f3bd2-6e4a-7b10-8d21-3d7fd9676c11",
    async (route) => {
      await route.fulfill({
        contentType: "application/json",
        json: {
          assessment_id: "018f3bd2-6e4a-7b10-8d21-3d7fd9676c11",
          items: [
            {
              confidence: 0.9,
              distance_to_query_m: 0,
              event_type: "flood_potential",
              freshness_score: 0.95,
              geometry: { type: "Point", coordinates: [121.51706, 25.04776] },
              id: "018f3bd3-1b8f-7ac0-a71d-8c33f7c5073a",
              ingested_at: "2026-04-29T02:55:00Z",
              observed_at: "2026-04-29T02:50:00Z",
              occurred_at: null,
              point: { lat: 25.04776, lng: 121.51706 },
              privacy_level: "public",
              raw_ref: "flood-potential:test",
              source_id: "flood-potential",
              source_type: "official",
              source_weight: 1,
              summary: "Full endpoint flood potential summary",
              title: "Full endpoint flood potential",
              url: "https://example.test/flood-potential-full",
            },
            {
              confidence: 0.72,
              distance_to_query_m: 420,
              event_type: "discussion",
              freshness_score: 0.72,
              geometry: null,
              id: "018f3bd3-1b8f-7ac0-a71d-8c33f7c5073b",
              ingested_at: "2026-04-29T02:40:00Z",
              observed_at: null,
              occurred_at: "2026-04-29T01:30:00Z",
              point: null,
              privacy_level: "aggregated",
              raw_ref: null,
              source_id: "community-report",
              source_type: "forum",
              source_weight: 0.7,
              summary: "Community report summary",
              title: "Community flood report",
              url: null,
            },
            {
              confidence: 0.82,
              distance_to_query_m: 260,
              event_type: "rainfall",
              freshness_score: 0.88,
              geometry: null,
              id: "018f3bd3-1b8f-7ac0-a71d-8c33f7c5073c",
              ingested_at: "2026-04-29T02:58:00Z",
              observed_at: "2026-04-29T02:52:00Z",
              occurred_at: null,
              point: { lat: 25.0481, lng: 121.519 },
              privacy_level: "public",
              raw_ref: "rainfall:test",
              source_id: "cwa-rainfall",
              source_type: "official",
              source_weight: 0.9,
              summary: "Full endpoint rainfall station summary",
              title: "Full endpoint rainfall station",
              url: "https://example.test/rainfall-full",
            },
          ],
          next_cursor: null,
        },
      });
    },
  );

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "台灣淹水風險開放地圖" })).toBeVisible();
  await expect(page.locator(".map-canvas")).toBeVisible();

  await page.getByLabel("輸入地標、地址或行政區").fill("台北火車站");
  await page.getByRole("button", { name: "查詢風險" }).click();

  await expect(page.getByText("已定位：台北火車站").first()).toBeVisible();
  await expect(page.getByText("25.04776", { exact: true })).toBeVisible();
  await expect(page.getByText("121.51706", { exact: true })).toBeVisible();
  await expect(page.getByText("低 / 中")).toBeVisible();
  await expect(page.getByText("即時風險為低，歷史參考風險為中，資料信心為中。")).toBeVisible();
  await expect(page.getByText("資料限制")).toBeVisible();
  await expect(page.getByText("Full endpoint flood potential", { exact: true })).toBeVisible();
  await expect(page.getByText("Full endpoint flood potential summary")).toBeVisible();
  await expect(page.getByText("Full endpoint rainfall station", { exact: true })).toBeVisible();
  await expect(page.getByText("Full endpoint rainfall station summary")).toBeVisible();
  await expect(page.getByText("官方公開資料").first()).toBeVisible();
  await expect(page.getByText("90%")).toBeVisible();
  await expect(page.getByText("0 m", { exact: true })).toBeVisible();
  await expect(page.getByText("3 筆來源")).toBeVisible();
  await expect(page.getByText("圖層管線")).toBeVisible();
  await expect(page.getByText("部分可用", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("API 圖層合約")).toBeVisible();
  await expect(page.getByText("Flood potential demo layer")).toBeVisible();
  await expect(page.getByText("raster-tile / 可顯示")).toBeVisible();
  await expect(page.getByText("Rainfall limited layer")).toBeVisible();
  await expect(page.getByText("vector-tile / 部分可用")).toBeVisible();
  await expect(page.getByText("Rainfall layer is delayed for part of the selected area.")).toBeVisible();
  await expect(page.getByText("觀測 / 發布").first()).toBeVisible();
  await expect(page.getByRole("link", { name: "開啟來源" }).first()).toHaveAttribute(
    "href",
    "https://example.test/flood-potential-full",
  );
  await expect(page.getByText("Community flood report")).toBeVisible();
  await expect(page.getByText("Community report summary")).toBeVisible();
  await expect(page.getByText("420 m", { exact: true })).toBeVisible();
  await expect(page.getByText("未提供連結")).toBeVisible();
  await expect(page.getByText("淹水潛勢公開資料：正常")).toBeVisible();
  await expect(page.getByText("目前為開發環境示範資料，尚未連接正式即時圖層。")).toBeVisible();
  await expect(page.getByText("查詢關注度：低")).toBeVisible();
});

test("live local unknown-address flow assesses precise fixtures and coarse admin geocodes", async ({
  page,
}) => {
  let riskCalls = 0;
  await page.route("http://localhost:8000/v1/risk/assess", async (route) => {
    riskCalls += 1;
    await route.continue();
  });

  await page.goto("/");

  await page.getByLabel("輸入地標、地址或行政區").fill("台南市安南區長溪路二段410巷16弄1號");
  await page.getByRole("button", { name: "查詢風險" }).click();

  await expect(page.getByText(/定位精度：門牌/)).toBeVisible();
  await expect(page.getByText("已定位：台南市安南區長溪路二段410巷16弄1號").first()).toBeVisible();
  await expect(page.getByText(/歷史參考風險為高/)).toBeVisible({ timeout: 20_000 });
  await expect.poll(() => riskCalls).toBe(1);

  await page.getByLabel("輸入地標、地址或行政區").fill("宜蘭縣礁溪鄉");
  await page.getByRole("button", { name: "查詢風險" }).click();

  await expect(page.getByText(/定位精度：行政區/)).toBeVisible();
  await expect(page.getByText(/系統會以代表點查詢/)).toBeVisible();
  await expect(page.getByText(/資料不足/).first()).toBeVisible();
  await expect.poll(() => riskCalls).toBe(2);
});

test("a failed address lookup clears stale risk results and does not assess old coordinates", async ({
  page,
}) => {
  let riskCalls = 0;

  await page.route("http://localhost:8000/v1/geocode", async (route) => {
    const body = route.request().postDataJSON() as { query?: string };
    await route.fulfill({
      contentType: "application/json",
      json:
        body.query === "valid-address"
          ? {
              candidates: [
                {
                  admin_code: "67000000",
                  confidence: 0.96,
                  name: "valid-address",
                  place_id: "place-valid",
                  point: { lat: 23.038818, lng: 120.213493 },
                  precision: "exact_address",
                  requires_confirmation: false,
                  matched_query: "valid-address",
                  limitations: [],
                  source: "mock-geocoder",
                  type: "address",
                },
              ],
            }
          : { candidates: [] },
    });
  });

  await page.route("http://localhost:8000/v1/risk/assess", async (route) => {
    riskCalls += 1;
    await route.fulfill({
      contentType: "application/json",
      json: {
        assessment_id: "018f3bd2-6e4a-7b10-8d21-3d7fd9676c11",
        confidence: { level: "高" },
        created_at: "2026-04-29T03:00:00Z",
        data_freshness: [],
        evidence: [],
        expires_at: "2026-04-29T03:10:00Z",
        explanation: {
          main_reasons: ["mock reason"],
          missing_sources: [],
          summary: "mock-risk-summary",
        },
        historical: { level: "高" },
        location: { lat: 23.038818, lng: 120.213493 },
        query_heat: {
          attention_level: "低",
          period: "P7D",
          query_count_bucket: "1-9",
          unique_approx_count_bucket: "1-9",
          updated_at: "2026-04-29T03:00:00Z",
        },
        radius_m: 300,
        realtime: { level: "低" },
        score_version: "risk-v0.1.0",
      },
    });
  });

  await page.route(
    "http://localhost:8000/v1/evidence/018f3bd2-6e4a-7b10-8d21-3d7fd9676c11",
    async (route) => {
      await route.fulfill({
        contentType: "application/json",
        json: {
          assessment_id: "018f3bd2-6e4a-7b10-8d21-3d7fd9676c11",
          items: [],
          next_cursor: null,
        },
      });
    },
  );

  await page.goto("/");
  await page.locator("form input").first().fill("valid-address");
  await page.getByRole("button", { name: "查詢風險" }).click();
  await expect(page.getByText("mock-risk-summary")).toBeVisible();
  await expect(page.getByText("無圖層資料")).toBeVisible();
  await expect(page.getByText("本次查詢未回傳可展示的圖層或資料來源。")).toBeVisible();

  await page.locator("form input").first().fill("missing-address");
  await page.getByRole("button", { name: "查詢風險" }).click();

  await expect(page.getByText("找不到這個地點，請換一個關鍵字再試。")).toBeVisible();
  await expect(page.getByText("mock-risk-summary")).not.toBeVisible();
  expect(riskCalls).toBe(1);
});

test("an admin-area geocode warns and still assesses with data limits", async ({
  page,
}) => {
  let riskCalls = 0;

  await page.route("http://localhost:8000/v1/geocode", async (route) => {
    const body = route.request().postDataJSON() as { query?: string };
    await route.fulfill({
      contentType: "application/json",
      json:
        body.query === "valid-address"
          ? {
              candidates: [
                {
                  admin_code: "67000000",
                  confidence: 0.96,
                  limitations: [],
                  matched_query: "valid-address",
                  name: "valid-address",
                  place_id: "place-valid",
                  point: { lat: 23.038818, lng: 120.213493 },
                  precision: "exact_address",
                  requires_confirmation: false,
                  source: "mock-geocoder",
                  type: "address",
                },
              ],
            }
          : {
              candidates: [
                {
                  admin_code: "10002000",
                  confidence: 0.72,
                  limitations: [
                    "定位只到行政區代表點，不能直接解讀為該行政區內任一地址風險。",
                  ],
                  matched_query: "宜蘭縣礁溪鄉",
                  name: "宜蘭縣礁溪鄉",
                  place_id: "admin-area",
                  point: { lat: 24.827, lng: 121.7706 },
                  precision: "admin_area",
                  requires_confirmation: true,
                  source: "local-taiwan-admin-centroid",
                  type: "admin_area",
                },
              ],
            },
    });
  });

  await page.route("http://localhost:8000/v1/risk/assess", async (route) => {
    riskCalls += 1;
    const body = route.request().postDataJSON() as { point?: { lat?: number } };
    const isAdminFallback = body.point?.lat === 24.827;
    await route.fulfill({
      contentType: "application/json",
      json: {
        assessment_id: "018f3bd2-6e4a-7b10-8d21-3d7fd9676c11",
        confidence: { level: isAdminFallback ? "未知" : "高" },
        created_at: "2026-04-29T03:00:00Z",
        data_freshness: [],
        evidence: [],
        expires_at: "2026-04-29T03:10:00Z",
        explanation: {
          main_reasons: [isAdminFallback ? "目前缺少可採用資料。" : "mock reason"],
          missing_sources: isAdminFallback ? ["目前資料不足，不能標記為低風險。"] : [],
          summary: isAdminFallback ? "目前資料不足，無法判定即時或歷史淹水風險。" : "mock-risk-summary",
        },
        historical: { level: isAdminFallback ? "未知" : "高" },
        location: body.point ?? { lat: 23.038818, lng: 120.213493 },
        query_heat: {
          attention_level: "低",
          period: "P7D",
          query_count_bucket: "1-9",
          unique_approx_count_bucket: "1-9",
          updated_at: "2026-04-29T03:00:00Z",
        },
        radius_m: 300,
        realtime: { level: isAdminFallback ? "未知" : "低" },
        score_version: "risk-v0.1.0",
      },
    });
  });

  await page.route(
    "http://localhost:8000/v1/evidence/018f3bd2-6e4a-7b10-8d21-3d7fd9676c11",
    async (route) => {
      await route.fulfill({
        contentType: "application/json",
        json: {
          assessment_id: "018f3bd2-6e4a-7b10-8d21-3d7fd9676c11",
          items: [],
          next_cursor: null,
        },
      });
    },
  );

  await page.goto("/");
  await page.locator("form input").first().fill("valid-address");
  await page.getByRole("button", { name: "查詢風險" }).click();
  await expect(page.getByText("mock-risk-summary")).toBeVisible();

  await page.locator("form input").first().fill("宜蘭縣礁溪鄉");
  await page.getByRole("button", { name: "查詢風險" }).click();

  await expect(page.getByText(/定位精度：行政區/)).toBeVisible();
  await expect(page.getByText(/系統會以代表點查詢/)).toBeVisible();
  await expect(page.getByText("資料不足").first()).toBeVisible();
  await expect(page.getByText(/無法判定即時或歷史淹水風險/)).toBeVisible();
  expect(riskCalls).toBe(2);
});
