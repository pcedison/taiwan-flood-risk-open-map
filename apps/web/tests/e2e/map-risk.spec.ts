import { expect, test } from "@playwright/test";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? `http://localhost:${process.env.E2E_API_PORT ?? "8000"}`;

type MockCoverageOverrides = Partial<{
  county_level_note: string;
  limitations: string[];
  missing_signal_types: string[];
  overall_level: string;
  signal_breakdown: Array<Record<string, unknown>>;
  summary: string;
}>;

function nearbyRealtimeCoverage(overrides: MockCoverageOverrides = {}) {
  return {
    county_level_note:
      "縣市資料源目錄顯示可能有資料，但附近覆蓋仍以查詢點半徑內感測器為準。",
    evaluated_at: "2026-04-29T03:00:00Z",
    limitations: ["縣市有資料不代表查詢點附近有 fresh local sensor。"],
    missing_signal_types: ["flood_depth"],
    overall_level: "medium",
    query_radius_m: 500,
    radius_buckets_m: [500, 1000, 3000, 5000],
    signal_breakdown: [
      {
        counts_by_radius_m: { "500": 1, "1000": 2, "3000": 4, "5000": 5 },
        coverage_level: "medium",
        fresh_count: 2,
        label: "雨量",
        missing_reason: null,
        nearest_distance_m: 230.4,
        nearest_observed_at: "2026-04-29T02:55:00Z",
        nearest_source_id: "local.test.rainfall:ST-001",
        signal_type: "rainfall",
        stale_count: 0,
        status_only_count: 0,
      },
      {
        counts_by_radius_m: { "500": 0, "1000": 1, "3000": 1, "5000": 1 },
        coverage_level: "low",
        fresh_count: 1,
        label: "水位",
        missing_reason: null,
        nearest_distance_m: 1320,
        nearest_observed_at: "2026-04-29T02:48:00Z",
        nearest_source_id: "local.test.water:WL-001",
        signal_type: "water_level",
        stale_count: 1,
        status_only_count: 0,
      },
      {
        counts_by_radius_m: { "500": 0, "1000": 0, "3000": 0, "5000": 0 },
        coverage_level: "no_local_sensor",
        fresh_count: 0,
        label: "淹水深度",
        missing_reason: "查詢點半徑附近沒有 fresh local sensor。",
        nearest_distance_m: null,
        nearest_observed_at: null,
        nearest_source_id: null,
        signal_type: "flood_depth",
        stale_count: 0,
        status_only_count: 0,
      },
    ],
    summary: "查詢點 1 公里內有雨量或水位即時資料，但感測密度仍有限。",
    ...overrides,
  };
}

test("searching a Taiwan landmark moves the map and renders a risk assessment", async ({
  page,
}) => {
  await page.route(`${API_BASE_URL}/v1/geocode`, async (route) => {
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
            limitations: ["定位結果是地標座標，不代表門牌精準位置。"],
            source: "mock-geocoder",
            type: "landmark",
          },
        ],
      },
    });
  });

  await page.route(`${API_BASE_URL}/v1/risk/assess`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: {
        assessment_id: "018f3bd2-6e4a-7b10-8d21-3d7fd9676c11",
        confidence: { level: "medium" },
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
            title: "公開討論淹水線索",
          },
        ],
        evidence_url: null,
        expires_at: "2026-04-29T03:10:00Z",
        explanation: {
          main_reasons: ["查詢半徑內與淹水潛勢圖資相交。"],
          missing_sources: ["尚未接入即時雨量資料。", "尚未接入即時水位資料。"],
          summary: "即時風險為低，歷史參考風險為中，資料信心為中。",
        },
        historical: { level: "medium" },
        location: { lat: 25.04776, lng: 121.51706 },
        nearby_realtime_coverage: {
          county_level_note: "縣市級 coverage catalog 只作背景；附近 coverage 以查詢點半徑重新判斷。",
          evaluated_at: "2026-04-29T03:00:00Z",
          limitations: ["coverage 僅描述附近觀測密度與新鮮度，不直接改變風險分數。"],
          missing_signal_types: ["water_level"],
          overall_level: "medium",
          query_radius_m: 500,
          radius_buckets_m: [500, 1000, 3000, 5000],
          signal_breakdown: [
            {
              counts_by_radius_m: { "500": 1, "1000": 1, "3000": 1, "5000": 1 },
              coverage_level: "medium",
              fresh_count: 1,
              label: "雨量",
              missing_reason: null,
              nearest_distance_m: 260,
              nearest_observed_at: "2026-04-29T02:52:00Z",
              nearest_source_id: "cwa-rainfall",
              signal_type: "rainfall",
              stale_count: 0,
              status_only_count: 0,
            },
          ],
          summary: "查詢點 500 公尺內有即時雨量觀測，但缺附近水位觀測。",
        },
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
            message: "已提供本次查詢半徑的圖磚目錄。",
            name: "淹水潛勢示範圖層",
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
            message: "選取範圍內部分雨量圖層資料延遲。",
            name: "雨量受限圖層",
            observed_at: "2026-04-29T01:30:00Z",
            tile_url: null,
          },
        ],
        radius_m: 500,
        realtime: { level: "low" },
        score_version: "risk-v0.1.0",
      },
    });
  });

  await page.route(
    `${API_BASE_URL}/v1/evidence/018f3bd2-6e4a-7b10-8d21-3d7fd9676c11**`,
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
              summary: "Raw flood potential backend summary",
              title: "Raw flood potential layer title",
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
              summary: "公開討論摘要",
              title: "公開討論淹水線索",
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
              summary: "Raw CWA rainfall backend summary",
              title: "Raw CWA rainfall station title",
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
  await expect(page.getByText("Public beta 使用限制")).toBeVisible();
  await expect(page.getByText(/本服務為公開資料與歷史/)).not.toBeVisible();
  await page.getByText("Public beta 使用限制").click();
  await expect(page.getByText(/本服務為公開資料與歷史/)).toBeVisible();
  await page.getByText("Public beta 使用限制").click();
  await expect(page.getByText(/本服務為公開資料與歷史/)).not.toBeVisible();

  await page.getByLabel("輸入地標、地址或行政區").fill("台北火車站");
  await page.getByRole("button", { name: "查詢風險" }).click();

  await expect(page.getByText("已定位：台北火車站").first()).toBeVisible();
  await expect(page.locator(".map-coordinate-card")).toContainText("25.04776, 121.51706");
  await expect(page.getByText("綜合風險：中")).toBeVisible();
  await expect(page.getByText("回答：目前要看哪個風險？為什麼採這個等級？")).toBeVisible();
  await expect(page.getByText("即時：低；歷史參考：中")).toBeVisible();
  await expect(page.getByText("主導：歷史參考")).toBeVisible();
  await expect(page.getByText("取即時/歷史較高")).toBeVisible();
  await expect(page.getByText("本次採歷史參考，因歷史參考（中）高於即時（低）。")).toBeVisible();
  await expect(page.getByText("即時風險為低，歷史參考風險為中，資料信心為中。")).toBeVisible();
  await expect(page.getByTestId("nearby-sensing")).toContainText("附近觀測：中");
  await expect(page.getByTestId("nearby-sensing")).toContainText("回答：附近感測器有沒有足夠覆蓋？");
  await expect(page.getByTestId("nearby-sensing")).toContainText("附近有 雨量 1 類觀測，最近 260 公尺；仍缺 水位。");
  await expect(page.getByTestId("nearby-sensing")).toContainText("缺口");
  await expect(page.getByTestId("nearby-sensing")).toContainText("水位");
  await expect(page.getByText("資料限制")).toBeVisible();
  await expect(page.getByText("尚未接入即時雨量資料。")).not.toBeVisible();
  await page.getByTestId("evidence-limitations").getByText("資料限制").click();
  await expect(page.getByText("尚未接入即時雨量資料。")).toBeVisible();
  const evidencePanel = page.getByTestId("evidence-panel");
  await expect(evidencePanel).toContainText("回答：哪些資料支撐這次判讀？");
  await expect(evidencePanel).toContainText("淹水潛勢資料");
  await expect(evidencePanel).toContainText("官方淹水潛勢圖資與本次查詢範圍重疊，可作為地形與歷史條件參考。");
  await expect(evidencePanel).toContainText("用途：地形 / 歷史參考");
  await expect(evidencePanel).toContainText("雨量觀測");
  await expect(evidencePanel).toContainText("附近即時雨量觀測可輔助判讀當下降雨壓力。");
  await expect(evidencePanel).toContainText("用途：即時雨量");
  await expect(evidencePanel).not.toContainText("Raw flood potential layer title");
  await expect(evidencePanel).not.toContainText("Raw flood potential backend summary");
  await expect(evidencePanel).not.toContainText("Raw CWA rainfall station title");
  await expect(evidencePanel).not.toContainText("Raw CWA rainfall backend summary");
  await expect(page.getByText("官方公開資料").first()).toBeVisible();
  await expect(page.getByText("90%")).toBeVisible();
  await expect(page.getByText("0 公尺", { exact: true })).toBeVisible();
  await expect(page.getByText("3 筆來源")).toBeVisible();
  await expect(page.getByTestId("risk-summary").locator(".risk-confidence-card")).toBeVisible();
  await expect(page.getByTestId("risk-summary").locator(".risk-explanation")).toBeVisible();
  await expect(page.getByTestId("risk-summary").locator(".layer-list")).toHaveCount(0);
  await expect(page.getByTestId("evidence-panel").locator(".evidence-card")).toHaveCount(3);
  await expect(page.getByTestId("evidence-panel").locator(".freshness-strip")).toHaveCount(0);
  await expect(page.getByTestId("user-report-panel")).toBeVisible();
  await expect(page.getByText("此功能會等法律、隱私、審核與治理流程完成後再開放。")).not.toBeVisible();
  await page.getByTestId("user-report-panel").getByText("民眾通報目前停用").click();
  await expect(page.getByText("此功能會等法律、隱私、審核與治理流程完成後再開放。")).toBeVisible();
  await expect(page.getByTestId("diagnostics-panel")).toBeVisible();
  const primarySectionOrder = await page.evaluate(() => {
    const riskSummary = document.querySelector('[data-testid="risk-summary"]');
    const nearbySensing = document.querySelector('[data-testid="nearby-sensing"]');
    const evidencePanel = document.querySelector('[data-testid="evidence-panel"]');
    const userReportPanel = document.querySelector('[data-testid="user-report-panel"]');
    const diagnosticsPanel = document.querySelector('[data-testid="diagnostics-panel"]');
    const evidenceList = document.querySelector('[data-testid="evidence-panel"] .evidence-list');
    const limitations = document.querySelector('[data-testid="evidence-limitations"]');
    const comesBefore = (left: Element | null, right: Element | null) =>
      Boolean(
        left &&
          right &&
          left.compareDocumentPosition(right) & Node.DOCUMENT_POSITION_FOLLOWING,
      );
    return {
      evidenceBeforeLimitations: comesBefore(evidenceList, limitations),
      evidenceBeforeUserReport: comesBefore(evidencePanel, userReportPanel),
      nearbyBeforeEvidence: comesBefore(nearbySensing, evidencePanel),
      riskBeforeEvidence: comesBefore(riskSummary, evidencePanel),
      userReportBeforeDiagnostics: comesBefore(userReportPanel, diagnosticsPanel),
    };
  });
  expect(primarySectionOrder).toEqual({
    evidenceBeforeLimitations: true,
    evidenceBeforeUserReport: true,
    nearbyBeforeEvidence: true,
    riskBeforeEvidence: true,
    userReportBeforeDiagnostics: true,
  });
  await expect(page.getByText("來源與圖層狀態")).toBeVisible();
  await expect(page.getByText("淹水潛勢示範圖層")).not.toBeVisible();
  await page.getByTestId("diagnostics-summary").click();
  await expect(page.getByText("來源摘要：部分受限")).toBeVisible();
  await expect(page.locator(".source-health-summary .source-health-chip")).toHaveCount(4);
  await expect(page.getByText("圖層管線")).toBeVisible();
  await expect(page.getByText("部分可用", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("圖層資料合約")).toBeVisible();
  await expect(page.getByText("淹水潛勢示範圖層")).toBeVisible();
  await expect(page.getByText("點陣圖磚：可顯示")).toBeVisible();
  await expect(page.getByText("雨量受限圖層")).toBeVisible();
  await expect(page.getByText("向量圖磚：部分可用")).toBeVisible();
  await expect(page.getByText("選取範圍內部分雨量圖層資料延遲。")).toBeVisible();
  await expect(page.getByText("觀測 / 發布").first()).toBeVisible();
  await page.getByTestId("risk-method-drawer").click();
  await expect(page.getByText("地圖罩色：中（黃色，透明度 85%）")).toBeVisible();
  await expect(page.getByRole("link", { name: "開啟來源" }).first()).toHaveAttribute(
    "href",
    "https://example.test/rainfall-full",
  );
  await expect(page.getByText("公開討論淹水線索")).toBeVisible();
  await expect(page.getByText("公開討論摘要")).toBeVisible();
  await expect(page.getByText("420 公尺", { exact: true })).toBeVisible();
  await expect(page.getByText("未提供連結")).toBeVisible();
  await expect(page.getByText("淹水潛勢公開資料：正常")).toBeVisible();
  await expect(page.getByText("目前為開發環境示範資料，尚未連接正式即時圖層。")).toBeVisible();
  await expect(page.getByText("查詢關注度：低")).toBeVisible();
});

test("map click cancels a slow search and re-enables the query button", async ({ page }) => {
  let releaseGeocode: (() => void) | undefined;

  await page.route(`${API_BASE_URL}/v1/geocode`, async (route) => {
    await new Promise<void>((resolve) => {
      releaseGeocode = resolve;
    });
    await route
      .fulfill({
        contentType: "application/json",
        json: { candidates: [] },
      })
      .catch(() => undefined);
  });

  try {
    await page.goto("/");
    const canvas = page.locator(".map-canvas");
    await expect(canvas).toBeVisible();
    const box = await canvas.boundingBox();
    expect(box).not.toBeNull();

    const searchInput = page.locator("form input").first();
    const submitButton = page.locator('form button[type="submit"]').first();
    await searchInput.fill("slow-address");
    await submitButton.click();
    await expect(submitButton).toBeDisabled();

    await canvas.click({
      position: { x: Math.round(box!.width / 2), y: Math.round(box!.height / 2) },
    });

    await expect(searchInput).toHaveValue("");
    await expect(submitButton).toBeEnabled();
  } finally {
    releaseGeocode?.();
  }
});

test("structured API failures render localized public-safe messages", async ({ page }) => {
  await page.route(`${API_BASE_URL}/v1/geocode`, async (route) => {
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
            limitations: [],
            source: "mock-geocoder",
            type: "landmark",
          },
        ],
      },
    });
  });

  await page.route(`${API_BASE_URL}/v1/risk/assess`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: {
        error: {
          code: "repository_unavailable",
          details: {},
          message: "database host failed over",
        },
      },
      status: 503,
    });
  });

  await page.goto("/");
  await page.getByLabel("輸入地標、地址或行政區").fill("台北火車站");
  await page.getByRole("button", { name: "查詢風險" }).click();

  await expect(page.getByText("資料服務暫時無法使用，請稍後再試。")).toBeVisible();
  await expect(page.getByText("database host failed over")).not.toBeVisible();
  await expect(page.getByTestId("evidence-panel").locator(".evidence-card")).toHaveCount(0);
});

test("live local unknown-address flow assesses precise fixtures and coarse admin geocodes", async ({
  page,
}) => {
  let riskCalls = 0;
  await page.route(`${API_BASE_URL}/v1/risk/assess`, async (route) => {
    riskCalls += 1;
    await route.continue();
  });

  await page.goto("/");

  await page.getByLabel("輸入地標、地址或行政區").fill("台南市安南區長溪路二段410巷16弄1號");
  await page.getByRole("button", { name: "查詢風險" }).click();

  await expect(page.getByText(/定位精度：門牌/)).toBeVisible();
  await expect(page.getByText("已定位：台南市安南區長溪路二段410巷16弄1號").first()).toBeVisible();
  await expect(page.getByText(/歷史與淹水潛勢參考為中/)).toBeVisible({ timeout: 20_000 });
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

  await page.route(`${API_BASE_URL}/v1/geocode`, async (route) => {
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

  await page.route(`${API_BASE_URL}/v1/risk/assess`, async (route) => {
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
        nearby_realtime_coverage: nearbyRealtimeCoverage(),
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
    `${API_BASE_URL}/v1/evidence/018f3bd2-6e4a-7b10-8d21-3d7fd9676c11**`,
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
  await page.getByTestId("diagnostics-summary").click();
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

  await page.route(`${API_BASE_URL}/v1/geocode`, async (route) => {
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

  await page.route(`${API_BASE_URL}/v1/risk/assess`, async (route) => {
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
        nearby_realtime_coverage: nearbyRealtimeCoverage(
          isAdminFallback
            ? {
                county_level_note:
                  "縣市資料源目錄顯示可能有資料，但查詢點半徑附近沒有新鮮在地感測資料。",
                limitations: ["半徑內沒有 fresh local sensor，不能代表縣市沒有感測器。"],
                missing_signal_types: ["rainfall", "water_level", "flood_depth"],
                overall_level: "no_local_sensor",
                signal_breakdown: [],
                summary: "查詢點半徑內沒有新鮮在地感測資料；縣市或資料源仍可能有資料。",
              }
            : {},
        ),
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
    `${API_BASE_URL}/v1/evidence/018f3bd2-6e4a-7b10-8d21-3d7fd9676c11**`,
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
