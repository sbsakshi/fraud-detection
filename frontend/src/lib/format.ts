import type { CaseSeverity, CaseStatus, InterventionLevel } from "../api/types";

export const LEVELS: InterventionLevel[] = ["inform", "warn", "verify", "hold", "restrict", "escalate"];
export const SEVERITIES: CaseSeverity[] = ["critical", "high", "medium", "low"];
export const OPEN_STATUSES: CaseStatus[] = ["open", "investigating", "escalated"];

/**
 * The API's timestamps are UTC. Postgres sends an explicit offset, but SQLite
 * (local dev) drops it, and `new Date("2026-10-16T03:07:48")` would then be read
 * as local time -- hours off. Treat an offset-less string as UTC.
 */
export function parseApiDate(iso: string): Date {
  return new Date(/(Z|[+-]\d{2}:?\d{2})$/.test(iso) ? iso : `${iso}Z`);
}

export function formatAmount(amount: string | number, currency = "INR"): string {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency, maximumFractionDigits: 2 }).format(Number(amount));
}

export function formatDateTime(iso: string): string {
  return parseApiDate(iso).toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

export function formatAge(iso: string, now = Date.now()): string {
  const s = Math.max(0, Math.round((now - parseApiDate(iso).getTime()) / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

export function formatScore(score: number | null | undefined): string {
  return score === null || score === undefined ? "–" : score.toFixed(2);
}

/** "fan_in_velocity" -> "Fan in velocity"; "ml_feature:hour_of_day" -> "ML: hour of day". */
export function humanizeCode(code: string): string {
  const [prefix, rest] = code.includes(":") ? code.split(":", 2) : ["", code];
  const text = rest.replace(/_/g, " ").replace(/\bml\b/g, "ML");
  const label = text.charAt(0).toUpperCase() + text.slice(1);
  return prefix === "ml_feature" ? `ML: ${text}` : label;
}

/** Fill a reason-code template ("Amount {amount:.2f} is {ratio:.1f}x ...") from its details. */
export function renderTemplate(template: string, details: Record<string, unknown>): string {
  return template.replace(/\{(\w+)(?::([^}]+))?\}/g, (match, key: string, spec?: string) => {
    if (!(key in details)) return match;
    const value = details[key];
    const fixed = spec ? /^\.(\d+)f$/.exec(spec) : null;
    if (fixed && typeof value === "number") return value.toFixed(Number(fixed[1]));
    return String(value);
  });
}
