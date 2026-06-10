import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import test from "node:test";

type RewriteRoute = {
  destination: string;
  source: string;
};

type NextConfigWithRewrites = {
  rewrites: () => Promise<RewriteRoute[]> | RewriteRoute[];
};

test("next rewrites fall back to the local API when INTERNAL_API_BASE_URL is blank", async () => {
  const rewrites = await loadRewritesWithInternalApiBaseUrl("   ");

  assertRewrite(rewrites, "/v1/:path*", "http://127.0.0.1:8000/v1/:path*");
  assertRewrite(rewrites, "/health", "http://127.0.0.1:8000/health");
  assertRewrite(rewrites, "/ready", "http://127.0.0.1:8000/ready");
});

test("next rewrites trim explicit INTERNAL_API_BASE_URL values", async () => {
  const rewrites = await loadRewritesWithInternalApiBaseUrl("  https://api.example.test///  ");

  assertRewrite(rewrites, "/health", "https://api.example.test/health");
});

async function loadRewritesWithInternalApiBaseUrl(value: string | undefined): Promise<RewriteRoute[]> {
  const previousValue = process.env.INTERNAL_API_BASE_URL;

  if (value === undefined) {
    delete process.env.INTERNAL_API_BASE_URL;
  } else {
    process.env.INTERNAL_API_BASE_URL = value;
  }

  try {
    const configUrl = new URL(`../../next.config.mjs?test=${randomUUID()}`, import.meta.url);
    const configModule = (await import(configUrl.href)) as { default: NextConfigWithRewrites };

    return await configModule.default.rewrites();
  } finally {
    if (previousValue === undefined) {
      delete process.env.INTERNAL_API_BASE_URL;
    } else {
      process.env.INTERNAL_API_BASE_URL = previousValue;
    }
  }
}

function assertRewrite(rewrites: RewriteRoute[], source: string, destination: string): void {
  assert.equal(
    rewrites.find((rewrite) => rewrite.source === source)?.destination,
    destination,
  );
}
