export function formatCoordinate(value: number) {
  return value.toFixed(5);
}

export function formatConfidence(value: number) {
  return `${Math.round(value * 100)}%`;
}

export function formatDistance(value: number | null) {
  return value === null ? "未提供" : `${Math.round(value).toLocaleString("zh-TW")} 公尺`;
}

export function formatDistanceMeters(value: number | null): string {
  if (value === null) {
    return "半徑內無新鮮感測";
  }

  const normalized = Math.max(0, value);
  if (normalized < 1000) {
    return `${Math.round(normalized).toLocaleString("zh-TW")} 公尺`;
  }

  return `${new Intl.NumberFormat("zh-TW", {
    maximumFractionDigits: 1,
  }).format(normalized / 1000)} 公里`;
}

export function formatDateTime(value: string | null, options?: { timeZone?: string }) {
  if (!value) return "未提供";
  return new Intl.DateTimeFormat("zh-TW", {
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: options?.timeZone,
  }).format(new Date(value));
}
