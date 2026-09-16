// Mock data standing in for live-scored transactions until Phase 7 wires up
// the real WebSocket feed from the backend's scoring endpoint. Shapes match
// backend/app/schemas.py's TransactionScoreOut exactly, so swapping this out
// for real fetched data later is a drop-in.

export type InterventionLevel = "inform" | "warn" | "verify" | "hold" | "restrict" | "escalate";
export type ReasonSource = "rule" | "ml" | "graph";

export interface ReasonCode {
  source: ReasonSource;
  code: string;
  summary: string;
}

export interface ScoredTransaction {
  id: number;
  senderUpiId: string;
  receiverUpiId: string;
  amount: number;
  currency: string;
  createdAt: string;
  fusedScore: number;
  confidence: number;
  interventionLevel: InterventionLevel;
  ruleScore: number;
  mlScore: number;
  graphScore: number;
  reasonCodes: ReasonCode[];
  caseId: number | null;
}

export const MOCK_TRANSACTIONS: ScoredTransaction[] = [
  {
    id: 1042,
    senderUpiId: "alice@okaxis",
    receiverUpiId: "bob@ybl",
    amount: 1500,
    currency: "INR",
    createdAt: "2026-09-15T10:12:04Z",
    fusedScore: 0.09,
    confidence: 0.74,
    interventionLevel: "inform",
    ruleScore: 0.0,
    mlScore: 0.12,
    graphScore: 0.0,
    reasonCodes: [],
    caseId: null,
  },
  {
    id: 1043,
    senderUpiId: "priya@ibl",
    receiverUpiId: "rahul@okhdfc",
    amount: 4200,
    currency: "INR",
    createdAt: "2026-09-15T10:13:41Z",
    fusedScore: 0.21,
    confidence: 0.61,
    interventionLevel: "warn",
    ruleScore: 0.15,
    mlScore: 0.24,
    graphScore: 0.0,
    reasonCodes: [{ source: "rule", code: "first_time_beneficiary", summary: "First transaction between priya and rahul" }],
    caseId: null,
  },
  {
    id: 1044,
    senderUpiId: "vikram@okaxis",
    receiverUpiId: "stranger882@ybl",
    amount: 80000,
    currency: "INR",
    createdAt: "2026-09-15T10:14:02Z",
    fusedScore: 0.67,
    confidence: 0.79,
    interventionLevel: "hold",
    ruleScore: 1.0,
    mlScore: 0.83,
    graphScore: 0.0,
    reasonCodes: [
      { source: "rule", code: "amount_above_historical_average", summary: "Amount is 643.7x the account's historical average" },
      { source: "ml", code: "ml_feature:amount", summary: "Transaction amount was the top contributor to the ML score" },
      { source: "ml", code: "ml_feature:receiver_account_age_days", summary: "Brand-new receiver account" },
    ],
    caseId: null,
  },
  {
    id: 1045,
    senderUpiId: "victim1@ibl",
    receiverUpiId: "collector7@okhdfc",
    amount: 9500,
    currency: "INR",
    createdAt: "2026-09-15T10:14:19Z",
    fusedScore: 0.53,
    confidence: 0.98,
    interventionLevel: "verify",
    ruleScore: 0.55,
    mlScore: 0.49,
    graphScore: 0.6,
    reasonCodes: [
      { source: "rule", code: "fan_in_velocity", summary: "5 distinct senders paid this receiver within 10 minutes" },
      { source: "graph", code: "mule_collector_pattern", summary: "Receiver shows a mule-collector fan-in/fan-out shape" },
    ],
    caseId: null,
  },
  {
    id: 1046,
    senderUpiId: "herder_collector4@ybl",
    receiverUpiId: "herder_cashout@okaxis",
    amount: 55000,
    currency: "INR",
    createdAt: "2026-09-15T10:39:57Z",
    fusedScore: 0.79,
    confidence: 0.8,
    interventionLevel: "restrict",
    ruleScore: 0.15,
    mlScore: 1.0,
    graphScore: 1.0,
    reasonCodes: [
      { source: "graph", code: "mule_collector_pattern", summary: "Sender received from 6 distinct senders, now sweeping funds onward" },
      { source: "graph", code: "shared_device_ring", summary: "Device linked to 3 other accounts" },
      { source: "ml", code: "ml_feature:amount", summary: "Transaction amount was the top contributor to the ML score" },
    ],
    caseId: 1,
  },
  {
    id: 1047,
    senderUpiId: "unknown221@ibl",
    receiverUpiId: "known_scam_acc@ybl",
    amount: 32000,
    currency: "INR",
    createdAt: "2026-09-15T10:41:12Z",
    fusedScore: 0.94,
    confidence: 0.91,
    interventionLevel: "escalate",
    ruleScore: 0.9,
    mlScore: 0.98,
    graphScore: 0.95,
    reasonCodes: [
      { source: "rule", code: "known_fraud_beneficiary", summary: "Receiver is on the known-fraud beneficiary watchlist" },
      { source: "graph", code: "fraud_cluster_exposure", summary: "1 hop from a known-fraud account via transaction flow" },
      { source: "ml", code: "ml_feature:receiver_outflow_total_hist", summary: "Receiver has swept out everything it has ever received" },
    ],
    caseId: 2,
  },
];

export const MOCK_STATS = {
  transactionsScored: 4218,
  flaggedRate: 0.084,
  activeCases: 2,
  avgFusedScore: 0.17,
};
