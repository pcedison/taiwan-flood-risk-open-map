import assert from "node:assert/strict";
import test from "node:test";

const apiClientModulePath = "../../app/lib/api-client.ts";
const {
  ApiRequestError,
  DATA_UNAVAILABLE_API_ERROR_MESSAGE,
  REQUEST_ABORTED_MESSAGE,
  REQUEST_TIMEOUT_MESSAGE,
  RATE_LIMITED_API_ERROR_MESSAGE,
  SERVER_FAILURE_API_ERROR_MESSAGE,
  buildApiUrl,
  fetchJson,
  normalizeApiBaseUrl,
  publicApiErrorMessage,
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

test("fetchJson preserves structured API error metadata for public-safe mapping", async () => {
  const originalFetch = globalThis.fetch;
  let calls = 0;

  globalThis.fetch = (async () => {
    calls += 1;
    return jsonResponse(
      {
        error: {
          code: "rate_limited",
          details: {
            retry_after_seconds: 42,
            window_seconds: 60,
          },
          message: "Internal policy detail should not be rendered directly.",
        },
      },
      429,
      { "Retry-After": "60" },
    );
  }) as typeof fetch;

  try {
    await assert.rejects(
      fetchJson("/v1/geocode", {
        baseUrl: "",
        timeoutMs: 10_000,
      }),
      (error) => {
        assert.ok(error instanceof ApiRequestError);
        assert.equal(error.status, 429);
        assert.equal(error.code, "rate_limited");
        assert.equal(error.retryAfterSeconds, 42);
        assert.equal(error.serverMessage, "Internal policy detail should not be rendered directly.");
        assert.equal(publicApiErrorMessage(error), RATE_LIMITED_API_ERROR_MESSAGE);
        assert.equal(calls, 1);
        return true;
      },
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("fetchJson parses nested FastAPI detail errors", async () => {
  const originalFetch = globalThis.fetch;

  globalThis.fetch = (async () =>
    jsonResponse(
      {
        detail: {
          error: {
            code: "repository_unavailable",
            message: "database hostname",
          },
        },
      },
      503,
    )) as typeof fetch;

  try {
    await assert.rejects(
      fetchJson("/v1/risk/assess", {
        baseUrl: "",
        timeoutMs: 10_000,
      }),
      (error) => {
        assert.ok(error instanceof ApiRequestError);
        assert.equal(error.status, 503);
        assert.equal(error.code, "repository_unavailable");
        assert.equal(publicApiErrorMessage(error), DATA_UNAVAILABLE_API_ERROR_MESSAGE);
        return true;
      },
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("fetchJson retries transient proxy failures once", async () => {
  const originalFetch = globalThis.fetch;
  let calls = 0;

  globalThis.fetch = (async () => {
    calls += 1;
    if (calls === 1) {
      return new Response("temporary gateway failure", {
        headers: { "Content-Type": "text/plain" },
        status: 502,
      });
    }
    return jsonResponse({ ok: true }, 200);
  }) as typeof fetch;

  try {
    const response = await fetchJson<{ ok: boolean }>("/v1/risk/assess", {
      baseUrl: "",
      retryDelayMs: 0,
      timeoutMs: 10_000,
    });

    assert.deepEqual(response, { ok: true });
    assert.equal(calls, 2);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("fetchJson parses direct structured errors and supports not-found overrides", async () => {
  const originalFetch = globalThis.fetch;

  globalThis.fetch = (async () =>
    jsonResponse(
      {
        code: "not_found",
        message: "No matching geocode candidate.",
      },
      404,
    )) as typeof fetch;

  try {
    await assert.rejects(
      fetchJson("/v1/geocode", {
        baseUrl: "",
        timeoutMs: 10_000,
      }),
      (error) => {
        assert.ok(error instanceof ApiRequestError);
        assert.equal(error.status, 404);
        assert.equal(error.code, "not_found");
        assert.equal(
          publicApiErrorMessage(error, { notFoundMessage: "找不到這個地點，請換一個關鍵字再試。" }),
          "找不到這個地點，請換一個關鍵字再試。",
        );
        return true;
      },
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("fetchJson maps non-JSON server failures without leaking response bodies", async () => {
  const originalFetch = globalThis.fetch;

  globalThis.fetch = (async () =>
    new Response("stack trace from upstream", {
      headers: { "Content-Type": "text/plain" },
      status: 500,
    })) as typeof fetch;

  try {
    await assert.rejects(
      fetchJson("/v1/risk/assess", {
        baseUrl: "",
        timeoutMs: 10_000,
      }),
      (error) => {
        assert.ok(error instanceof ApiRequestError);
        assert.equal(error.status, 500);
        assert.equal(error.code, null);
        assert.equal(error.serverMessage, null);
        assert.equal(publicApiErrorMessage(error), SERVER_FAILURE_API_ERROR_MESSAGE);
        return true;
      },
    );
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

function jsonResponse(
  body: unknown,
  status: number,
  headers: Record<string, string> = {},
): Response {
  return new Response(JSON.stringify(body), {
    headers: {
      "Content-Type": "application/json",
      ...headers,
    },
    status,
  });
}
