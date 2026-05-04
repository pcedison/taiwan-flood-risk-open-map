import { expect, type Locator, type Page, test } from "@playwright/test";

const BASEMAP_ATTRIBUTION = "Example Open Basemap Attribution";
const BASEMAP_TILE_HOST = "https://basemap.example.test";
const OSM_TILE_HOST = "https://tile.openstreetmap.org";
const API_BASE_URL = "http://localhost:8000";

const TILE_PNG_BASE64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR42mP8z8BQDwAFgwJ/lCw9WQAAAABJRU5ErkJggg==";

async function mockBasemapTiles(page: Page) {
  const requests = {
    basemapTiles: 0,
    osmTiles: 0,
    tgos: 0,
  };

  page.on("request", (request) => {
    const url = request.url().toLowerCase();
    if (url.startsWith(BASEMAP_TILE_HOST)) requests.basemapTiles += 1;
    if (url.startsWith(OSM_TILE_HOST)) requests.osmTiles += 1;
    if (url.includes("tgos")) requests.tgos += 1;
  });

  await page.route(`${BASEMAP_TILE_HOST}/**`, async (route) => {
    await route.fulfill({
      body: Buffer.from(TILE_PNG_BASE64, "base64"),
      contentType: "image/png",
      headers: {
        "access-control-allow-origin": "*",
        "cache-control": "no-store",
      },
    });
  });

  await page.route(`${OSM_TILE_HOST}/**`, async (route) => {
    await route.fulfill({
      body: Buffer.from(TILE_PNG_BASE64, "base64"),
      contentType: "image/png",
      status: 200,
    });
  });

  return requests;
}

async function mockRiskApi(page: Page) {
  await page.route(`${API_BASE_URL}/v1/geocode`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: {
        candidates: [
          {
            admin_code: "63000000",
            confidence: 0.98,
            name: "Taipei Main Station",
            place_id: "place-open-basemap-smoke",
            point: { lat: 25.04776, lng: 121.51706 },
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
        assessment_id: "018f3bd2-6e4a-7b10-8d21-open-basemap",
        confidence: { level: "medium" },
        created_at: "2026-04-29T03:00:00Z",
        data_freshness: [
          {
            health_status: "healthy",
            ingested_at: "2026-04-29T02:55:00Z",
            message: "Open basemap smoke freshness signal is healthy.",
            name: "Open basemap smoke source",
            observed_at: "2026-04-29T02:50:00Z",
            source_id: "open-basemap-smoke-source",
          },
        ],
        evidence: [
          {
            confidence: 0.91,
            distance_to_query_m: 0,
            event_type: "flood_potential",
            id: "018f3bd3-1b8f-7ac0-a71d-open-basemap-a",
            ingested_at: "2026-04-29T02:55:00Z",
            observed_at: "2026-04-29T02:50:00Z",
            occurred_at: null,
            published_at: "2026-04-29T02:45:00Z",
            source_type: "official",
            source_url: "https://example.test/open-basemap-evidence",
            summary: "Open basemap smoke preview evidence summary",
            title: "Open basemap smoke preview evidence",
          },
        ],
        evidence_url: null,
        expires_at: "2026-04-29T03:10:00Z",
        explanation: {
          main_reasons: ["Mock evidence keeps the risk overlay flow active."],
          missing_sources: [],
          summary: "Open basemap smoke risk summary",
        },
        historical: { level: "medium" },
        location: { lat: 25.04776, lng: 121.51706 },
        map_layers: [
          {
            availability: "available",
            feature_count: 12,
            health_status: "healthy",
            kind: "raster-tile",
            layer_id: "open-basemap-smoke-layer",
            message: "Open basemap smoke tile contract is available.",
            name: "Open basemap smoke layer",
            observed_at: "2026-04-29T02:50:00Z",
            tile_url: "/v1/tiles/open-basemap-smoke/{z}/{x}/{y}.png",
          },
        ],
        radius_m: 500,
        query_heat: {
          attention_level: "low",
          period: "P7D",
          query_count_bucket: "1-9",
          unique_approx_count_bucket: "1-9",
          updated_at: "2026-04-29T03:00:00Z",
        },
        realtime: { level: "low" },
        score_version: "risk-v0.1.0",
      },
    });
  });

  await page.route(
    `${API_BASE_URL}/v1/evidence/018f3bd2-6e4a-7b10-8d21-open-basemap`,
    async (route) => {
      await route.fulfill({
        contentType: "application/json",
        json: {
          assessment_id: "018f3bd2-6e4a-7b10-8d21-open-basemap",
          items: [
            {
              confidence: 0.91,
              distance_to_query_m: 0,
              event_type: "flood_potential",
              freshness_score: 0.95,
              geometry: { type: "Point", coordinates: [121.51706, 25.04776] },
              id: "018f3bd3-1b8f-7ac0-a71d-open-basemap-a",
              ingested_at: "2026-04-29T02:55:00Z",
              observed_at: "2026-04-29T02:50:00Z",
              occurred_at: null,
              point: { lat: 25.04776, lng: 121.51706 },
              privacy_level: "public",
              raw_ref: "open-basemap-smoke:test",
              source_id: "open-basemap-smoke-source",
              source_type: "official",
              source_weight: 1,
              summary: "Open basemap smoke full evidence summary",
              title: "Open basemap smoke full evidence",
              url: "https://example.test/open-basemap-evidence-full",
            },
          ],
          next_cursor: null,
        },
      });
    },
  );
}

async function expectVisibleMapCanvas(page: Page): Promise<Locator> {
  const mapCanvas = page.locator(".map-canvas");
  await expect(mapCanvas).toBeVisible();

  const canvas = mapCanvas.locator("canvas").first();
  await expect(canvas).toBeVisible();

  const box = await canvas.boundingBox();
  expect(box?.width).toBeGreaterThan(0);
  expect(box?.height).toBeGreaterThan(0);

  return canvas;
}

async function expectBasemapAttributionVisible(page: Page) {
  const attribution = page.getByText(BASEMAP_ATTRIBUTION);
  if (!(await attribution.first().isVisible().catch(() => false))) {
    await page.locator(".maplibregl-ctrl-attrib-button").first().click();
  }

  await expect(attribution).toBeVisible();
}

test("production-like open raster basemap renders without OSM or TGOS tiles", async ({
  page,
}) => {
  const basemapRequests = await mockBasemapTiles(page);
  await mockRiskApi(page);

  await page.goto("/");

  const canvas = await expectVisibleMapCanvas(page);
  await expect(page.locator(".map-marker")).toBeVisible();
  await expectBasemapAttributionVisible(page);
  await expect.poll(() => basemapRequests.basemapTiles).toBeGreaterThan(0);

  await page.locator("form input").first().fill("Taipei Main Station");
  await page.locator('form button[type="submit"]').first().click();

  await expect(page.getByText("Open basemap smoke risk summary")).toBeVisible();
  await expect(page.getByText("Open basemap smoke full evidence", { exact: true })).toBeVisible();
  await expect(page.getByText("Open basemap smoke layer")).toBeVisible();
  await expect(page.locator(".map-marker")).toBeVisible();
  await expect(canvas).toBeVisible();

  expect(basemapRequests.osmTiles).toBe(0);
  expect(basemapRequests.tgos).toBe(0);
});
