import type { DataFreshnessItem, EvidencePreview, ProfileBasisText, ProfilePreviewState } from "./types";

export function getProfilePreviewState(input: {
  data_freshness?: DataFreshnessItem[] | null;
  explanation?: {
    summary?: string | null;
  } | null;
} | null | undefined): ProfilePreviewState {
  const profileFreshness = input?.data_freshness?.find(
    (item) => item.source_id === "precomputed-risk-profile",
  );
  if (!profileFreshness) {
    return {
      isProfilePreview: false,
      label: null,
      message: null,
    };
  }

  return {
    isProfilePreview: true,
    label: "區域概略估計",
    message:
      profileFreshness.message ??
      input?.explanation?.summary ??
      "這是本區域的概略估計，系統稍後會自動補齊更精確範圍的資料。",
  };
}

export function getProfileBasisText(input: {
  data_freshness?: DataFreshnessItem[] | null;
  explanation?: {
    main_reasons?: string[] | null;
  } | null;
  evidence?: EvidencePreview[] | null;
} | null | undefined): ProfileBasisText {
  const profileFreshness = input?.data_freshness?.find(
    (item) => item.source_id === "precomputed-risk-profile",
  );
  if (!profileFreshness) {
    return {
      historicalNote: null,
      confidenceNote: null,
      limitationLead: null,
    };
  }

  const reasons = input?.explanation?.main_reasons ?? [];
  const evidenceCount = input?.evidence?.length ?? 0;
  const evidenceReason =
    reasons.find((reason) => reason.includes("歷史參考來自")) ??
    reasons.find((reason) => reason.includes("彙整")) ??
    null;
  // Backend-authored reasons may still spell out the internal "profile" term;
  // swap it for the same plain-language phrasing used elsewhere on this page.
  const plainEvidenceReason = evidenceReason?.replace(/\s*profile\s*/gi, "區域概略估計") ?? null;

  return {
    historicalNote:
      plainEvidenceReason ??
      (evidenceCount > 0
        ? `這次區域概略估計已提供 ${evidenceCount} 筆摘要證據。`
        : "這次區域概略估計還沒有逐筆列出的摘要證據。"),
    confidenceNote:
      "依資料來源類型、資料筆數、時間新鮮度與覆蓋缺口推估而來；描述的是證據可靠度，不代表淹水機率。",
    limitationLead:
      "這不是系統錯誤，而是這次區域概略估計還沒有涵蓋到的資料來源；即時雨量或水位資料不足時，會限制即時判斷的準確度。",
  };
}
