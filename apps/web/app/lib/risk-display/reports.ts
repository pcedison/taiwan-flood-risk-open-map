import type {
  Coordinate,
  UserReportPayloadState,
  UserReportSubmissionDisplayState,
  UserReportSubmissionStatus,
} from "./types";

export function buildRiskAssessmentPayload(
  coordinate: Coordinate,
  radius: number,
  locationText: string | null,
) {
  return {
    point: {
      lat: coordinate.lat,
      lng: coordinate.lng,
    },
    radius_m: radius,
    time_context: "now",
    location_text: locationText,
  };
}

export function buildUserReportPayload(
  coordinate: Coordinate,
  summary: string,
): UserReportPayloadState {
  const trimmedSummary = summary.trim();
  if (!trimmedSummary) {
    return {
      isValid: false,
      payload: null,
      summary: trimmedSummary,
      validationMessage: "summary_required",
    };
  }

  return {
    isValid: true,
    payload: {
      point: {
        lat: coordinate.lat,
        lng: coordinate.lng,
      },
      summary: trimmedSummary,
    },
    summary: trimmedSummary,
    validationMessage: null,
  };
}

export function getUserReportSubmissionDisplayState(
  status: UserReportSubmissionStatus,
): UserReportSubmissionDisplayState {
  if (status === "loading") {
    return {
      kind: "loading",
      message: "正在送出通報。",
      submitLabel: "送出中",
    };
  }

  if (status === "success") {
    return {
      kind: "success",
      message: "通報已收到，等待審核。",
      submitLabel: "送出通報",
    };
  }

  if (status === "feature_disabled") {
    return {
      kind: "warning",
      message: "此環境目前停用民眾通報功能。",
      submitLabel: "送出通報",
    };
  }

  if (status === "repository_unavailable") {
    return {
      kind: "error",
      message: "通報收件暫時無法使用。",
      submitLabel: "送出通報",
    };
  }

  if (status === "rate_limited") {
    return {
      kind: "warning",
      message: "通報送出太頻繁，請稍後再試。",
      submitLabel: "送出通報",
    };
  }

  if (status === "error") {
    return {
      kind: "error",
      message: "通報送出失敗。",
      submitLabel: "送出通報",
    };
  }

  return {
    kind: "neutral",
    message: null,
    submitLabel: "送出通報",
  };
}
