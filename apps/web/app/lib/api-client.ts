export const DEFAULT_API_BASE_URL = "http://localhost:8000";
export const API_REQUEST_TIMEOUT_MS = 15_000;
export const EVIDENCE_REQUEST_TIMEOUT_MS = 8_000;

export const REQUEST_ABORTED_MESSAGE = "Request aborted";
export const REQUEST_TIMEOUT_MESSAGE = "Request timed out";

type FetchJsonOptions = {
  baseUrl?: string;
  init?: RequestInit;
  signal?: AbortSignal;
  timeoutMs?: number;
};

export function normalizeApiBaseUrl(value: string | undefined): string {
  if (value === undefined) return DEFAULT_API_BASE_URL;
  return value.trim().replace(/\/+$/u, "");
}

export const apiBaseUrl = normalizeApiBaseUrl(process.env.NEXT_PUBLIC_API_BASE_URL);

export function buildApiUrl(path: string, baseUrl = apiBaseUrl): string {
  return `${baseUrl}${path}`;
}

export function isAbortError(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === "AbortError") ||
    (typeof error === "object" &&
      error !== null &&
      "name" in error &&
      (error as { name?: unknown }).name === "AbortError")
  );
}

export async function fetchJson<T>(
  path: string,
  {
    baseUrl = apiBaseUrl,
    init = {},
    signal,
    timeoutMs = API_REQUEST_TIMEOUT_MS,
  }: FetchJsonOptions = {},
): Promise<T> {
  const controller = new AbortController();
  let abortReason: "external" | "timeout" | null = null;
  const timeoutId = setTimeout(() => {
    abortReason = "timeout";
    controller.abort();
  }, timeoutMs);
  const abortFromExternalSignal = () => {
    abortReason ??= "external";
    controller.abort();
  };

  if (signal?.aborted) {
    abortFromExternalSignal();
  } else {
    signal?.addEventListener("abort", abortFromExternalSignal, { once: true });
  }

  try {
    const response = await fetch(buildApiUrl(path, baseUrl), {
      ...init,
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }

    return response.json() as Promise<T>;
  } catch (error) {
    if (isAbortError(error)) {
      throw new Error(
        abortReason === "timeout" ? REQUEST_TIMEOUT_MESSAGE : REQUEST_ABORTED_MESSAGE,
      );
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
    signal?.removeEventListener("abort", abortFromExternalSignal);
  }
}

export async function postJson<T>(
  path: string,
  payload: unknown,
  options: FetchJsonOptions = {},
): Promise<T> {
  const init = options.init ?? {};
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");

  return fetchJson<T>(path, {
    ...options,
    init: {
      ...init,
      body: JSON.stringify(payload),
      headers,
      method: "POST",
    },
  });
}

export async function getJson<T>(
  path: string,
  options: FetchJsonOptions = {},
): Promise<T> {
  return fetchJson<T>(path, {
    ...options,
    timeoutMs: options.timeoutMs ?? EVIDENCE_REQUEST_TIMEOUT_MS,
  });
}
