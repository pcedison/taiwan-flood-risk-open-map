import { defineConfig, devices } from "@playwright/test";

const hostedBaseUrl = process.env.HOSTED_WEB_BASE_URL ?? "https://floodrisk.cc";

export default defineConfig({
  testDir: "./tests/hosted",
  timeout: 90_000,
  retries: 1,
  workers: 1,
  outputDir: "../../artifacts/hosted-web-ui",
  reporter: [
    ["line"],
    ["json", { outputFile: "../../artifacts/hosted-web-ui-smoke.json" }],
  ],
  use: {
    baseURL: hostedBaseUrl,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "desktop-chrome",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "mobile-chrome",
      use: { ...devices["Pixel 7"] },
    },
  ],
});
