import { expect, test } from "@playwright/test";

// Defense-in-depth headers from next.config.mjs (audit finding SEC M-1).
// The map page loading successfully in the other specs is the proof that the
// CSP does not break MapLibre; this spec pins the headers themselves.
test("home page responds with the security header set", async ({ page }) => {
  const response = await page.goto("/");
  expect(response).not.toBeNull();
  const headers = response!.headers();

  const csp = headers["content-security-policy"];
  expect(csp).toBeTruthy();
  expect(csp).toContain("default-src 'self'");
  expect(csp).toContain("frame-ancestors 'none'");
  expect(csp).toContain("worker-src 'self' blob:");
  expect(csp).toContain("object-src 'none'");

  expect(headers["x-content-type-options"]).toBe("nosniff");
  expect(headers["referrer-policy"]).toBe("strict-origin-when-cross-origin");
  expect(headers["strict-transport-security"]).toContain("max-age=");
  expect(headers["permissions-policy"]).toContain("geolocation=()");
});
