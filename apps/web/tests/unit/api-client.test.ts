import assert from "node:assert/strict";
import test from "node:test";

const apiClientModulePath = "../../app/lib/api-client.ts";
const {
  REQUEST_ABORTED_MESSAGE,
  REQUEST_TIMEOUT_MESSAGE,
  buildApiUrl,
  fetchJson,
  normalizeApiBaseUrl,
} = (await import(apiClientModulePath)) as typeof import("../../app/lib/api-client");

test("normalizeApiBaseUrl keeps empty same-origin deployments and trims explicit origins", () => {
  assert.equal(normalizeApiBaseUrl(undefined), "http://localhost:8000");
  assert.equal(normalizeApiBaseUrl(""), "");
  assert.equal(normalizeApiBaseUrl("  https://api.example.test///  "), "https://api.example.test");
  assert.equal(buildApiUrl("/v1/risk/assess", ""), "/v1/risk/assess");
});

test("fetchJson aborts when a caller supersedes an in-flight request", async () => {
  const originalFetch = globalThis.fetch;
  const requestController = new AbortController();
  let forwardedSignal: AbortSignal | undefined;

  globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
    forwardedSignal = init?.signal ?? undefined;
    return new Promise<Response>((_resolve, reject) => {
      forwardedSignal?.addEventListener("abort", () => {
        reject(new DOMException("Aborted", "AbortError"));
      });
    });
  }) as typeof fetch;

  try {
    const pending = fetchJson("/v1/geocode", {
      baseUrl: "",
      signal: requestController.signal,
      timeoutMs: 10_000,
    });
    requestController.abort();

    await assert.rejects(pending, new RegExp(REQUEST_ABORTED_MESSAGE));
    assert.equal(forwardedSignal?.aborted, true);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("fetchJson reports timeout separately from external cancellation", async () => {
  const originalFetch = globalThis.fetch;

  globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
    return new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => {
        reject(new DOMException("Aborted", "AbortError"));
      });
    });
  }) as typeof fetch;

  try {
    await assert.rejects(
      fetchJson("/v1/risk/assess", {
        baseUrl: "",
        timeoutMs: 1,
      }),
      new RegExp(REQUEST_TIMEOUT_MESSAGE),
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
