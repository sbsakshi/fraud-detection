import type { CaseSeverity, CaseStatus, InterventionLevel } from "../api/types";
import { formatScore } from "../lib/format";

export function LevelTag({ level }: { level: InterventionLevel }) {
  const strong = level === "hold" || level === "restrict" || level === "escalate";
  return (
    <span className={`tag lv-${level} ${strong ? "strong" : ""}`}>
      <span className="dot" aria-hidden />
      {level}
    </span>
  );
}

/** Plain number; only coloured once it's high enough to need attention (the hold threshold). */
export function Score({ value }: { value: number | null | undefined }) {
  return <span className={`num ${value !== null && value !== undefined && value >= 0.55 ? "score-hot" : ""}`}>{formatScore(value)}</span>;
}

export function Severity({ value }: { value: CaseSeverity }) {
  return <span className={`sev-${value}`} style={{ textTransform: "capitalize" }}>{value}</span>;
}

export function StatusPill({ status }: { status: CaseStatus }) {
  return <span className="pill">{status}</span>;
}
