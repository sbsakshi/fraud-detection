// Wire types for the Finsight backend (app/schemas.py). snake_case is kept as-is:
// the UI reads exactly what the API sends, with no mapping layer to drift.

export type InterventionLevel = "inform" | "warn" | "verify" | "hold" | "restrict" | "escalate";
export type CaseStatus = "open" | "investigating" | "escalated" | "closed";
export type CaseSeverity = "low" | "medium" | "high" | "critical";
export type ReasonSource = "rule" | "ml" | "graph";
export type CaseResolution = "fraud_confirmed" | "false_positive" | "customer_verified";

export interface ReasonCode {
  source: ReasonSource;
  code: string;
  template: string;
  details: Record<string, unknown>;
  contribution: number | null;
}

export interface RiskScore {
  rule_score: number | null;
  ml_score: number | null;
  graph_score: number | null;
  fused_score: number;
  confidence: number;
  intervention_level: InterventionLevel;
}

export interface CaseRef {
  id: number;
  status: CaseStatus;
  severity: CaseSeverity;
}

export interface ScoredTransaction {
  transaction_id: number;
  sender_upi_id: string;
  receiver_upi_id: string;
  amount: string;
  currency: string;
  created_at: string;
  risk_score: RiskScore;
  reason_codes: ReasonCode[];
  case: CaseRef | null;
}

export interface Page<T> {
  items: T[];
  total: number;
}

export interface TransactionStats {
  transactions_scored: number;
  flagged_rate: number;
  active_cases: number;
  avg_fused_score: number;
}

export interface CaseListItem {
  id: number;
  status: CaseStatus;
  severity: CaseSeverity;
  assigned_to: string | null;
  created_at: string;
  updated_at: string;
  transaction_id: number;
  sender_upi_id: string;
  receiver_upi_id: string;
  amount: string;
  currency: string;
  fused_score: number;
  intervention_level: InterventionLevel;
  top_reason: string | null;
}

export interface CaseEvent {
  id: number;
  event_type: string;
  description: string | null;
  actor: string;
  created_at: string;
}

export interface CaseDetail {
  id: number;
  status: CaseStatus;
  severity: CaseSeverity;
  assigned_to: string | null;
  summary: string | null;
  created_at: string;
  updated_at: string;
  transaction: ScoredTransaction;
  events: CaseEvent[];
}

export interface AccountProfile {
  upi_id: string;
  owner_name: string;
  bank_name: string;
  ifsc_code: string;
  account_type: "individual" | "merchant";
  device_id: string | null;
  is_active: boolean;
  created_at: string;
  known_fraud: boolean;
  transactions_sent: number;
  transactions_received: number;
  total_sent: string;
  total_received: string;
  counterparties: number;
  max_score: number | null;
  flagged_count: number;
  open_cases: number;
  shared_device_accounts: string[];
}

export interface GraphNode {
  id: string;
  account_type: "individual" | "merchant" | null;
  community: number;
  max_score: number | null;
  known_fraud: boolean;
}

export interface GraphEdge {
  source: string;
  target: string;
  type: "transaction" | "shared_device" | "repeated_counterparty";
  weight: number;
}

export interface Graph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface TimeseriesBucket {
  start: string;
  counts: Record<InterventionLevel, number>;
  total: number;
}

export interface ReasonCodeCount {
  code: string;
  source: ReasonSource;
  count: number;
}

export interface CaseSummary {
  open_by_severity: Record<CaseSeverity, number>;
  unassigned: number;
  closed: number;
}

export interface Ladder {
  levels: { level: InterventionLevel; min_score: number; min_confidence: number }[];
  weights: Record<ReasonSource, number>;
}

export interface AccountBrief {
  upi_id: string;
  owner_name: string;
  bank_name: string;
  account_type: "individual" | "merchant";
  device_id: string | null;
}

export interface TransactionCreate {
  sender_upi_id: string;
  receiver_upi_id: string;
  amount: number;
  device_id: string;
  transaction_type?: string;
}
