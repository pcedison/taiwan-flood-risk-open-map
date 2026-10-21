import { expect, test, type Page } from "@playwright/test";
import type { Map as MapLibreMap } from "maplibre-gl";
import { writeFile } from "node:fs/promises";

const LABEL_LAYERS = ["base-place-labels", "base-poi-labels", "base-road-labels"];
const POINT = { lat: 25.04776, lng: 121.51706 };

async function mapSnapshot(page: Page) {
  return page.evaluate(({ labelLayers, point }) => {
    // Inspect the existing mapRef only inside the test. This keeps diagnostics
    // out of the shipped app and lets us assert real rendered vector features.
    type Hook = { memoizedState?: { current?: unknown }; next?: Hook };
    type Fiber = { memoizedState?: Hook; return?: Fiber };
    const container = document.querySelector<HTMLElement>(".map-canvas");
    if (!container) throw new Error("Map container is missing");
    const fiberKey = Object.keys(container).find((key) => key.startsWith("__reactFiber$"));
    if (!fiberKey) throw new Error("React mapRef diagnostics need review after this React update");
    let fiber = (container as unknown as Record<string, Fiber>)[fiberKey];
    let map: MapLibreMap | undefined;
    while (fiber && !map) {
      let hook = fiber.memoizedState;
      while (hook) {
        const candidate = hook.memoizedState?.current as Partial<MapLibreMap> | undefined;
        if (candidate?.getContainer?.() === container && candidate?.queryRenderedFeatures) {
          map = candidate as MapLibreMap;
          break;
        }
        hook = hook.next;
      }
      fiber = fiber.return as Fiber;
    }
    if (!map) throw new Error("Map has not mounted");
    const style = map.getStyle();
    const roadLayers = style.layers.filter((layer) => /road/.test(layer.id) && layer.type === "line");
    const labels = map.queryRenderedFeatures({ layers: labelLayers });
    const markerBox = container.querySelector(".map-marker")?.getBoundingClientRect();
    const mapBox = container.getBoundingClientRect();
    const projected = map.project([point.lng, point.lat]);
    return {
      loaded: map.loaded(),
      tilesLoaded: map.areTilesLoaded(),
      sourceLoaded: map.isSourceLoaded("basemap"),
      roads: map.queryRenderedFeatures({ layers: roadLayers.map((layer) => layer.id) }).length,
      labels: labels.map((feature) => feature.properties.name ?? feature.properties["name:zh"] ?? ""),
      zoom: map.getZoom(),
      center: map.getCenter().toArray(),
      layerIds: style.layers.map((layer) => layer.id),
      fillOpacity: map.getPaintProperty("query-radius-fill", "fill-opacity"),
      fillColor: map.getPaintProperty("query-radius-fill", "fill-color"),
      radiusSource: style.sources["query-radius"],
      markerError: markerBox ? Math.hypot(
        markerBox.x + markerBox.width / 2 - mapBox.x - projected.x,
        markerBox.y + markerBox.height / 2 - mapBox.y - projected.y,
      ) : null,
    };
  }, { labelLayers: LABEL_LAYERS, point: POINT });
}

async function mockRiskApi(page: Page) {
  await page.route("**/v1/geocode", (route) => route.fulfill({
    json: { candidates: [{
      name: "Taipei Main Station", place_id: "vector-test", admin_code: "63000000",
      confidence: 0.98, point: POINT, type: "landmark", source: "test-geocoder",
      precision: "poi", requires_confirmation: false,
    }] },
  }));
  await page.route("**/v1/risk/assess", (route) => route.fulfill({
    json: {
      assessment_id: "vector-test-assessment", created_at: "2026-10-01T00:00:00Z",
      expires_at: "2026-10-01T00:10:00Z", confidence: { level: "medium" },
      realtime: { level: "low" }, historical: { level: "medium" },
      location: POINT, radius_m: 500, score_version: "risk-v0.3.0",
      explanation: { summary: "Vector regression risk summary", main_reasons: [], missing_sources: [] },
      data_freshness: [], evidence: [], map_layers: [],
      query_heat: { attention_level: "low", period: "P7D", query_count_bucket: "1-9",
        unique_approx_count_bucket: "1-9", updated_at: "2026-10-01T00:00:00Z" },
    },
  }));
  await page.route("**/v1/evidence/**", (route) => route.fulfill({
    json: { assessment_id: "vector-test-assessment", items: [], next_cursor: null },
  }));
}

test("real production PMTiles, labels, search, overlay and safe attribution work", async ({ page }, testInfo) => {
  const errors: string[] = [];
  const rangeResponses: Array<{ status: number; range: string | undefined }> = [];
  const moduleResponses = new Set<string>();
  let glyphResponses = 0;
  let cancelledTileRequests = 0;
  let exerciseAttribution = false;
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
  page.on("requestfailed", (request) => {
    // flyTo cancels out-of-view PMTiles ranges. Require the final visible tiles
    // below; preserve every other transport failure as a test error.
    if (request.url().endsWith(".pmtiles") && request.failure()?.errorText === "net::ERR_ABORTED") {
      cancelledTileRequests++;
      return;
    }
    errors.push(`${request.url()}: ${request.failure()?.errorText}`);
  });
  page.on("response", (response) => {
    if (response.url().endsWith(".pmtiles")) rangeResponses.push({ status: response.status(), range: response.request().headers().range });
    if (response.url().includes("/maplibre/") && response.status() === 200) moduleResponses.add(new URL(response.url()).pathname);
    if (response.url().endsWith(".pbf") && response.status() === 200) glyphResponses++;
  });

  await page.route("**/basemap-config", async (route) => {
    const response = await route.fetch();
    const config = await response.json();
    expect(config.kind).toBe("style-url");
    expect(config.style.sources.basemap.type).toBe("vector");
    expect(config.style.sources.basemap.url).toMatch(/^pmtiles:\/\/https:\/\//);
    if (exerciseAttribution) {
      config.style.sources.basemap.attribution +=
        '<details open onload="window.__attributionExecuted=true" ontoggle="window.__attributionExecuted=true">Attribution regression</details>';
    }
    await route.fulfill({ response, json: config });
  });
  // The public CDN permits its production origin. Relay the unchanged real
  // archive Range responses for loopback testing; no raster/vector tile mock.
  await page.route("https://**/*.pmtiles", async (route) => {
    const response = await route.fetch();
    await route.fulfill({ response, headers: {
      ...response.headers(), "access-control-allow-origin": "*",
      "access-control-expose-headers": "Content-Length,Content-Range,ETag",
    } });
  });
  await mockRiskApi(page);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".status-pill")).toHaveText("\u4e92\u52d5\u5730\u5716", { timeout: 45_000 });
  await expect(page.locator(".map-marker")).toBeVisible();
  await expect.poll(async () => (await mapSnapshot(page)).roads).toBeGreaterThan(0);
  await expect.poll(async () => (await mapSnapshot(page)).labels.length).toBeGreaterThan(0);
  const overview = await mapSnapshot(page);
  expect(overview.zoom).toBeCloseTo(7.2, 1);
  expect(overview.fillOpacity).toBe(0.18);
  await page.locator(".map-shell").screenshot({ path: testInfo.outputPath("taiwan-vector-overview.png") });

  await page.locator("form input").first().fill("Taipei Main Station");
  await page.locator('form button[type="submit"]').first().click();
  await expect(page.getByText("Vector regression risk summary")).toBeVisible();
  await expect.poll(async () => (await mapSnapshot(page)).zoom).toBeCloseTo(15.2, 1);
  await expect.poll(async () => (await mapSnapshot(page)).tilesLoaded, { timeout: 30_000 }).toBe(true);
  await expect.poll(async () => (await mapSnapshot(page)).loaded, { timeout: 30_000 }).toBe(true);
  const searched = await mapSnapshot(page);
  expect(searched.sourceLoaded).toBe(true);
  expect(searched.loaded).toBe(true);
  expect(searched.center[0]).toBeCloseTo(POINT.lng, 4);
  expect(searched.center[1]).toBeCloseTo(POINT.lat, 4);
  expect(searched.roads).toBeGreaterThan(0);
  expect(searched.labels.length).toBeGreaterThan(0);
  expect(searched.labels.some((name) => /[\u3400-\u9fff]/u.test(String(name)))).toBe(true);
  expect(searched.markerError).not.toBeNull();
  expect(searched.markerError!).toBeLessThan(3);
  expect(searched.fillOpacity).toBe(0.85);
  expect(searched.fillColor).not.toBe(overview.fillColor);
  for (const label of LABEL_LAYERS) {
    expect(searched.layerIds.indexOf("query-radius-fill")).toBeLessThan(searched.layerIds.indexOf(label));
    expect(searched.layerIds.indexOf("query-radius-line")).toBeLessThan(searched.layerIds.indexOf(label));
  }
  await page.locator(".map-shell").screenshot({ path: testInfo.outputPath("taipei-vector-search.png") });
  const diagnosticsPath = testInfo.outputPath("rendered-map-state.json");
  await writeFile(diagnosticsPath, JSON.stringify({ overview, searched, rangeResponses, glyphResponses, cancelledTileRequests }, null, 2));
  await testInfo.attach("rendered-map-state", { path: diagnosticsPath, contentType: "application/json" });

  exerciseAttribution = true;
  await page.reload();
  await expect(page.locator(".status-pill")).toHaveText("\u4e92\u52d5\u5730\u5716", { timeout: 45_000 });
  const attribution = page.locator(".maplibregl-ctrl-attrib");
  await expect(attribution).toHaveCount(1);
  await expect(attribution).toContainText("Attribution regression");
  await expect(attribution.locator('[onload], [ontoggle]')).toHaveCount(0);
  await expect(attribution.locator('a[href="https://www.openstreetmap.org/copyright"]')).toHaveCount(1);
  expect(await page.evaluate(() => (window as unknown as Record<string, unknown>).__attributionExecuted)).toBeUndefined();
  expect(rangeResponses.length).toBeGreaterThan(1);
  expect(rangeResponses.every((response) => response.status === 206 && response.range?.startsWith("bytes="))).toBe(true);
  expect(glyphResponses).toBeGreaterThan(0);
  expect(moduleResponses.has("/maplibre/maplibre-gl-worker.mjs")).toBe(true);
  expect(moduleResponses.has("/maplibre/maplibre-gl-shared.mjs")).toBe(true);
  expect(errors).toEqual([]);

  // Exercise teardown/remount: no duplicate controls or stale protocol owner.
  // Unload the map document without introducing an intentional HTTP 404.
  await page.goto("about:blank");
  await expect(page.locator(".map-canvas")).toHaveCount(0);
  await page.goto("/");
  await expect(page.locator(".status-pill")).toHaveText("\u4e92\u52d5\u5730\u5716", { timeout: 45_000 });
  await expect(page.locator(".maplibregl-ctrl-attrib")).toHaveCount(1);
  await expect(page.locator(".map-marker")).toHaveCount(1);
  await expect.poll(async () => {
    const remounted = await mapSnapshot(page);
    return remounted.sourceLoaded && remounted.tilesLoaded && remounted.roads > 0;
  }).toBe(true);
  expect(errors).toEqual([]);
});
