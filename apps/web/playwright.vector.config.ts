import { defineConfig, devices } from "@playwright/test";

const styleUrl = process.env.VECTOR_BASEMAP_STYLE_URL ??
  "https://basemap.floodrisk.cc/styles/taiwan-open/2026-05-11/style.json";
const webPort = process.env.E2E_VECTOR_WEB_PORT ?? "3310";
// A prebuilt local Docker web server can use the exact same vector checks.
const externalBaseURL = process.env.E2E_VECTOR_BASE_URL;
if (externalBaseURL && !/^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/.test(externalBaseURL)) {
  throw new Error("E2E_VECTOR_BASE_URL must be a local loopback HTTP origin");
}
const baseURL = externalBaseURL ?? `http://127.0.0.1:${webPort}`;

export default defineConfig({
  testDir: "./tests/vector",
  timeout: 90_000,
  workers: 1,
  use: {
    baseURL,
    trace: "retain-on-failure",
    launchOptions: {
      args: ["--enable-webgl", "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
    },
  },
  webServer: externalBaseURL ? undefined : {
    command: `npm run clean:next && npm run build && npm run start -- --hostname 127.0.0.1 --port ${webPort}`,
    env: {
      BASEMAP_STYLE_URL: styleUrl,
      NEXT_PUBLIC_BASEMAP_STYLE_URL: "",
      NEXT_PUBLIC_API_BASE_URL: "",
      CSP_EXTRA_ORIGINS: new URL(styleUrl).origin,
      NEXT_TELEMETRY_DISABLED: "1",
    },
    reuseExistingServer: false,
    timeout: 240_000,
    url: baseURL,
  },
  projects: [
    { name: "desktop-vector", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1000 } } },
    { name: "mobile-vector", use: { ...devices["Pixel 7"] } },
  ],
});
