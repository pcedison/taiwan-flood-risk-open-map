import type { UserReportPayload } from "./risk-display";

export type UserReportCreateResponse = {
  report_id: string;
  status: "pending";
};

export type UserReportSubmitErrorCode =
  | "feature_disabled"
  | "repository_unavailable"
  | "report_submit_failed";

type ApiErrorEnvelope = {
  error?: {
    code?: string;
    message?: string;
  };
};

export class UserReportSubmitError extends Error {
  code: UserReportSubmitErrorCode;

  constructor(code: UserReportSubmitErrorCode) {
    super(code);
    this.name = "UserReportSubmitError";
    this.code = code;
  }
}

export async function postUserReport(
  apiBaseUrl: string,
  payload: UserReportPayload,
  fetcher: typeof fetch = fetch,
): Promise<UserReportCreateResponse> {
  const response = await fetcher(`${apiBaseUrl}/v1/reports`, {
    body: JSON.stringify(payload),
    headers: {
      "Content-Type": "application/json",
    },
    method: "POST",
  });

  if (response.status === 202) {
    return response.json() as Promise<UserReportCreateResponse>;
  }

  const errorCode = await errorCodeFromResponse(response);
  if (response.status === 404 && errorCode === "feature_disabled") {
    throw new UserReportSubmitError("feature_disabled");
  }

  if (response.status === 503 && errorCode === "repository_unavailable") {
    throw new UserReportSubmitError("repository_unavailable");
  }

  throw new UserReportSubmitError("report_submit_failed");
}

async function errorCodeFromResponse(response: Response): Promise<string | undefined> {
  try {
    const body = (await response.json()) as ApiErrorEnvelope;
    return body.error?.code;
  } catch {
    return undefined;
  }
}
