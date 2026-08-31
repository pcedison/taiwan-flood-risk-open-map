import { expect, test } from "@playwright/test";

test("production basemap and public risk query remain usable", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });

  const mapState = page.getByLabel("地圖狀態");
  await expect(mapState).toContainText("互動地圖", { timeout: 45_000 });

  const canvas = page.locator(".map-canvas canvas").first();
  await expect(canvas).toBeVisible();
  const canvasBox = await canvas.boundingBox();
  expect(canvasBox?.width).toBeGreaterThan(250);
  expect(canvasBox?.height).toBeGreaterThan(250);

  await page.getByRole("textbox", { name: "搜尋地點" }).fill("台南市北區北安路一段");
  const queryButton = page.getByRole("button", { name: "查詢風險" });
  await expect(queryButton).toBeEnabled();
  await queryButton.click();

  await expect(
    page.getByRole("heading", {
      name: /^綜合風險：(低|中|高|極高|未知)$/,
    }),
  ).toBeVisible({ timeout: 45_000 });
  const riskSummary = page.getByTestId("risk-summary");
  await expect(riskSummary).toContainText(/即時\s*(低|中|高|極高|未知)/);
  await expect(riskSummary).toContainText(/歷史參考\s*(低|中|高|極高|未知)/);
  await expect(riskSummary).toContainText(/資料可信度\s*(低|中|高|極高|未知)/);

  const evidencePanel = page.getByTestId("evidence-panel");
  await expect(evidencePanel.getByText("判讀依據", { exact: true })).toBeVisible();
  await expect(evidencePanel.locator(".evidence-card").first()).not.toBeVisible();
});
