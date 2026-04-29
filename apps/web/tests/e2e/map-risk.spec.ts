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
            source_type: "official",
            summary: "查詢點位附近有官方開放資料中的淹水潛勢訊號。",
            title: "淹水潛勢公開圖資",
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
        radius_m: 500,
        realtime: { level: "低" },
        score_version: "risk-v0.1.0",
      },
    });
  });

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
  await expect(page.getByText("淹水潛勢公開圖資")).toBeVisible();
  await expect(page.getByText("官方公開資料")).toBeVisible();
  await expect(page.getByText("90%")).toBeVisible();
  await expect(page.getByText("0 m", { exact: true })).toBeVisible();
  await expect(page.getByText("淹水潛勢公開資料：正常")).toBeVisible();
  await expect(page.getByText("目前為開發環境示範資料，尚未連接正式即時圖層。")).toBeVisible();
  await expect(page.getByText("查詢關注度：低")).toBeVisible();
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

  await page.goto("/");
  await page.locator("form input").first().fill("valid-address");
  await page.getByRole("button", { name: "查詢風險" }).click();
  await expect(page.getByText("mock-risk-summary")).toBeVisible();

  await page.locator("form input").first().fill("missing-address");
  await page.getByRole("button", { name: "查詢風險" }).click();

  await expect(page.getByText("找不到這個地點，請換一個關鍵字再試。")).toBeVisible();
  await expect(page.getByText("mock-risk-summary")).not.toBeVisible();
  expect(riskCalls).toBe(1);
});
