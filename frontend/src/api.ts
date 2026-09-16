// Thin client for the Phase 6/7 backend endpoints. Converts the backend's
// snake_case wire format (app/schemas.py's TransactionScoreOut/TransactionStatsOut)
// into the camelCase shapes Dashboard.tsx already renders, so mockData.ts's
// types double as the live-data types too.

import type { InterventionLevel, ReasonSource, ScoredTransaction } from "./mockData";

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export interface Stats {
  transactionsScored: number;
  flaggedRate: number;
  activeCases: number;
  avgFusedScore: number;
}

interface ReasonCodeApi {
  source: ReasonSource;
  code: string;
  template: string;
  details: Record<string, unknown>;
  contribution: number | null;
}

interface CaseApi {
  id: number;
  status: string;
  severity: string;
}

interface TransactionScoreApi {
  transaction_id: number;
  sender_upi_id: string;
  receiver_upi_id: string;
  amount: string;
  currency: string;
  created_at: string;
  risk_score: {
    rule_score: number | null;
    ml_score: number | null;
    graph_score: number | null;
    fused_score: number;
    confidence: number;
    intervention_level: InterventionLevel;
  };
  reason_codes: ReasonCodeApi[];
  case: CaseApi | null;
}

interface TransactionStatsApi {
  transactions_scored: number;
  flagged_rate: number;
  active_cases: number;
  avg_fused_score: number;
}

// Reason codes carry a filled-in `template` + `details` on the backend, e.g.
// "Amount {amount:.2f} is {ratio:.1f}x the historical average" + {amount, ratio}
// (app/rules/engine.py, app/graph/engine.py, app/ml/model_loader.py all use
// Python's `str.format` mini-language, including the `:.Nf` fixed-decimal
// spec) -- the dashboard just wants one rendered string, so interpolate here
// rather than teaching every render site the placeholder syntax.
function renderTemplate(template: string, details: Record<string, unknown>): string {
  return template.replace(/\{(\w+)(?::([^}]+))?\}/g, (match, key: string, spec: string | undefined) => {
    if (!(key in details)) return match;
    const value = details[key];
    const fixedDecimals = spec ? /^\.(\d+)f$/.exec(spec) : null;
    if (fixedDecimals && typeof value === "number") {
      return value.toFixed(Number(fixedDecimals[1]));
    }
    return String(value);
  });
}

function toScoredTransaction(t: TransactionScoreApi): ScoredTransaction {
  return {
    id: t.transaction_id,
    senderUpiId: t.sender_upi_id,
    receiverUpiId: t.receiver_upi_id,
    amount: Number(t.amount),
    currency: t.currency,
    createdAt: t.created_at,
    fusedScore: t.risk_score.fused_score,
    confidence: t.risk_score.confidence,
    interventionLevel: t.risk_score.intervention_level,
    ruleScore: t.risk_score.rule_score ?? 0,
    mlScore: t.risk_score.ml_score ?? 0,
    graphScore: t.risk_score.graph_score ?? 0,
    reasonCodes: t.reason_codes.map((rc) => ({
      source: rc.source,
      code: rc.code,
      summary: renderTemplate(rc.template, rc.details),
    })),
    caseId: t.case?.id ?? null,
  };
}

async function getJson<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_BASE_URL}${path}`);
  if (!resp.ok) {
    throw new Error(`${path} responded ${resp.status}`);
  }
  return resp.json() as Promise<T>;
}

export async function fetchTransactions(limit = 50): Promise<ScoredTransaction[]> {
  const rows = await getJson<TransactionScoreApi[]>(`/transactions?limit=${limit}`);
  return rows.map(toScoredTransaction);
}

interface GraphNodeApi {
  id: string;
  true_label: string | null;
  account_type: string | null;
  community: number;
}

interface GraphEdgeApi {
  source: string;
  target: string;
  type: string;
  weight: number;
}

interface GraphOutApi {
  nodes: GraphNodeApi[];
  edges: GraphEdgeApi[];
}

export interface GraphNode {
  id: string;
  trueLabel: string | null;
  accountType: string | null;
  community: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  type: string;
  weight: number;
}

export interface GraphSnapshot {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export async function fetchGraph(): Promise<GraphSnapshot> {
  const data = await getJson<GraphOutApi>("/graph");
  return {
    nodes: data.nodes.map((n) => ({
      id: n.id,
      trueLabel: n.true_label,
      accountType: n.account_type,
      community: n.community,
    })),
    edges: data.edges.map((e) => ({ source: e.source, target: e.target, type: e.type, weight: e.weight })),
  };
}

export async function fetchStats(): Promise<Stats> {
  const stats = await getJson<TransactionStatsApi>("/transactions/stats");
  return {
    transactionsScored: stats.transactions_scored,
    flaggedRate: stats.flagged_rate,
    activeCases: stats.active_cases,
    avgFusedScore: stats.avg_fused_score,
  };
}
