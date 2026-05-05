import { defineConfig, devices } from "@playwright/test";

const basemapSmokeEnv = {
  NEXT_PUBLIC_BASEMAP_ATTRIBUTION: "Example Open Basemap Attribution",
  NEXT_PUBLIC_BASEMAP_KIND: "raster",
  NEXT_PUBLIC_BASEMAP_RASTER_TILES: "https://basemap.example.test/{z}/{x}/{y}.png",
  NEXT_PUBLIC_BASEMAP_STYLE_URL: "",
  NEXT_PUBLIC_TGOS_ENABLED: "false",
};
const apiPort = process.env.E2E_API_PORT ?? "8000";
const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? `http://localhost:${apiPort}`;

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  use: {
    baseURL: "http://127.0.0.1:3100",
    trace: "on-first-retry",
  },
  webServer: [
    {
      command: `cd ../api && python -m uvicorn app.main:app --host 127.0.0.1 --port ${apiPort}`,
      env: {
        APP_ENV: "local",
        CORS_ORIGINS: "http://127.0.0.1:3100,http://localhost:3100",
        EVIDENCE_REPOSITORY_ENABLED: "false",
        HISTORICAL_NEWS_ON_DEMAND_ENABLED: "false",
        REALTIME_OFFICIAL_ENABLED: "false",
        SOURCE_NEWS_ENABLED: "false",
      },
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      url: `http://127.0.0.1:${apiPort}/health`,
    },
    {
      command: "npm run clean:next && npm run dev -- --hostname 127.0.0.1 --port 3100",
      env: {
        ...basemapSmokeEnv,
        INTERNAL_API_BASE_URL: apiBaseUrl,
        NEXT_PUBLIC_API_BASE_URL: apiBaseUrl,
      },
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      url: "http://127.0.0.1:3100",
    },
  ],
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "mobile-chrome",
      use: { ...devices["Pixel 7"] },
    },
  ],
});
