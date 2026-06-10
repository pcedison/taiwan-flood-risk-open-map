export const DEFAULT_API_BASE_URL = "http://localhost:8000";
export const API_REQUEST_TIMEOUT_MS = 15_000;
export const EVIDENCE_REQUEST_TIMEOUT_MS = 8_000;

export const REQUEST_ABORTED_MESSAGE = "Request aborted";
export const REQUEST_TIMEOUT_MESSAGE = "Request timed out";
export const GENERIC_API_ERROR_MESSAGE = "查詢失敗，請稍後再試。";
export const RATE_LIMITED_API_ERROR_MESSAGE = "查詢太頻繁，請稍後再試。";
export const FEATURE_DISABLED_API_ERROR_MESSAGE = "此功能目前停用。";
export const NOT_FOUND_API_ERROR_MESSAGE = "找不到符合條件的資料，請調整查詢後再試。";
export const DATA_UNAVAILABLE_API_ERROR_MESSAGE = "資料服務暫時無法使用，請稍後再試。";
export const SERVER_FAILURE_API_ERROR_MESSAGE = "服務暫時無法回應，請稍後再試。";
export const BAD_REQUEST_API_ERROR_MESSAGE = "查詢內容無法處理，請調整後再試。";

type FetchJsonOptions = {
  baseUrl?: string;
  init?: RequestInit;
  signal?: AbortSignal;
  timeoutMs?: number;
};

type StructuredApiError = {
  code: string | null;
  details: Record<string, unknown>;
  message: string | null;
};

type ApiRequestErrorOptions = {
  code?: string | null;
  details?: Record<string, unknown>;
  path: string;
  retryAfterSeconds?: number | null;
  serverMessage?: string | null;
  status: number;
};

type PublicApiErrorMessageOptions = {
  fallback?: string;
  notFoundMessage?: string;
};

const UNAVAILABLE_ERROR_CODES = new Set([
  "abuse_guard_unavailable",
  "challenge_unavailable",
  "data_unavailable",
  "repository_unavailable",
  "source_unavailable",
  "sources_unavailable",
  "stale_unavailable",
  "tiles_unavailable",
]);

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

export class ApiRequestError extends Error {
  readonly code: string | null;
  readonly details: Record<string, unknown>;
  readonly path: string;
  readonly retryAfterSeconds: number | null;
  readonly serverMessage: string | null;
  readonly status: number;

  constructor({
    code = null,
    details = {},
    path,
    retryAfterSeconds = null,
    serverMessage = null,
    status,
  }: ApiRequestErrorOptions) {
    super(`API request failed: ${status}${code ? ` (${code})` : ""}`);
    this.name = "ApiRequestError";
    this.code = code;
    this.details = details;
    this.path = path;
    this.retryAfterSeconds = retryAfterSeconds;
    this.serverMessage = serverMessage;
    this.status = status;
  }
}

export function publicApiErrorMessage(
  error: unknown,
  options: PublicApiErrorMessageOptions = {},
): string {
  const fallback = options.fallback ?? GENERIC_API_ERROR_MESSAGE;
  if (!(error instanceof ApiRequestError)) {
    return fallback;
  }

  if (error.code === "rate_limited" || error.status === 429) {
    return RATE_LIMITED_API_ERROR_MESSAGE;
  }

  if (error.code === "feature_disabled" || error.code === "layer_disabled") {
    return FEATURE_DISABLED_API_ERROR_MESSAGE;
  }

  if (error.code === "not_found" || error.status === 404) {
    return options.notFoundMessage ?? NOT_FOUND_API_ERROR_MESSAGE;
  }

  if ((error.code && UNAVAILABLE_ERROR_CODES.has(error.code)) || error.status === 503) {
    return DATA_UNAVAILABLE_API_ERROR_MESSAGE;
  }

  if (error.status >= 500) {
    return SERVER_FAILURE_API_ERROR_MESSAGE;
  }

  if (error.status === 400 || error.code === "bad_request") {
    return BAD_REQUEST_API_ERROR_MESSAGE;
  }

  return fallback;
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
      throw await apiRequestErrorFromResponse(path, response);
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

async function apiRequestErrorFromResponse(
  path: string,
  response: Response,
): Promise<ApiRequestError> {
  const structuredError = await structuredApiErrorFromResponse(response);
  return new ApiRequestError({
    code: structuredError?.code ?? null,
    details: structuredError?.details ?? {},
    path,
    retryAfterSeconds: retryAfterSeconds(response.headers, structuredError?.details),
    serverMessage: structuredError?.message ?? null,
    status: response.status,
  });
}

async function structuredApiErrorFromResponse(
  response: Response,
): Promise<StructuredApiError | null> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.toLowerCase().includes("json")) {
    return null;
  }

  try {
    const body = (await response.clone().json()) as unknown;
    return structuredApiErrorFromBody(body);
  } catch {
    return null;
  }
}

function structuredApiErrorFromBody(body: unknown): StructuredApiError | null {
  if (!isRecord(body)) return null;
  const detail = isRecord(body.detail) ? body.detail : null;
  return (
    structuredApiErrorFromValue(body.error) ??
    structuredApiErrorFromValue(detail?.error) ??
    structuredApiErrorFromValue(detail) ??
    structuredApiErrorFromValue(body)
  );
}

function structuredApiErrorFromValue(value: unknown): StructuredApiError | null {
  if (!isRecord(value)) return null;

  const code = typeof value.code === "string" && value.code.length > 0 ? value.code : null;
  const message =
    typeof value.message === "string" && value.message.length > 0 ? value.message : null;
  if (code === null && message === null) return null;

  return {
    code,
    details: isRecord(value.details) ? value.details : {},
    message,
  };
}

function retryAfterSeconds(
  headers: Headers,
  details: Record<string, unknown> | undefined,
): number | null {
  const detailRetryAfter = numericRetryAfter(details?.retry_after_seconds);
  if (detailRetryAfter !== null) {
    return detailRetryAfter;
  }

  const headerRetryAfter = headers.get("Retry-After");
  if (headerRetryAfter === null) {
    return null;
  }

  const seconds = numericRetryAfter(headerRetryAfter);
  if (seconds !== null) {
    return seconds;
  }

  const retryAt = Date.parse(headerRetryAfter);
  if (Number.isNaN(retryAt)) {
    return null;
  }

  return Math.max(0, Math.ceil((retryAt - Date.now()) / 1000));
}

function numericRetryAfter(value: unknown): number | null {
  if (typeof value !== "number" && typeof value !== "string") {
    return null;
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0) {
    return null;
  }
  return Math.ceil(parsed);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
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
