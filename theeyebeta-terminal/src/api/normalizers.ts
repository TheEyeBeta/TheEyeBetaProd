export function asArray<T = any>(value: unknown, candidateKeys: string[] = []): T[] {
  if (Array.isArray(value)) return value as T[];
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    for (const key of candidateKeys) {
      if (Array.isArray(record[key])) return record[key] as T[];
    }
    for (const key of ["items", "rows", "data", "results", "entries", "orders", "positions"]) {
      if (Array.isArray(record[key])) return record[key] as T[];
    }
  }
  return [];
}

export function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export function formatDate(value?: string | null): string {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-GB", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  }).format(date);
}

export function formatNumber(value: unknown, digits = 2): string {
  const number = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(number)) return "--";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(number);
}

export function statusTone(value?: string | boolean | null): "ok" | "warn" | "bad" | "idle" {
  if (value === true) return "ok";
  if (value === false) return "bad";
  const text = String(value ?? "").toLowerCase();
  if (["ok", "healthy", "pass", "passed", "running", "active", "up", "green"].includes(text)) {
    return "ok";
  }
  if (["warn", "warning", "stale", "degraded", "yellow"].includes(text)) return "warn";
  if (["fail", "failed", "error", "critical", "down", "red", "halted"].includes(text)) return "bad";
  return "idle";
}
