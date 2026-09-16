// Demo data. Shapes match backend/app/schemas.py's TransactionScoreOut and
// the /graph endpoint exactly, so swapping this out for real fetched data is
// a drop-in -- Dashboard.tsx and NetworkGraph.tsx fall back to this whenever
// the backend isn't reachable.

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

// Timestamps are minutes-ago offsets from "now" so the feed always looks
// freshly live, however long ago this file was loaded.
function minutesAgo(mins: number): string {
  return new Date(Date.now() - mins * 60_000).toISOString();
}

export const MOCK_TRANSACTIONS: ScoredTransaction[] = [
  {
    id: 1042,
    senderUpiId: "alice@okaxis",
    receiverUpiId: "bob@ybl",
    amount: 1500,
    currency: "INR",
    createdAt: minutesAgo(58),
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
    createdAt: minutesAgo(55),
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
    senderUpiId: "sana@okaxis",
    receiverUpiId: "dev@ybl",
    amount: 800,
    currency: "INR",
    createdAt: minutesAgo(51),
    fusedScore: 0.05,
    confidence: 0.7,
    interventionLevel: "inform",
    ruleScore: 0.0,
    mlScore: 0.06,
    graphScore: 0.0,
    reasonCodes: [],
    caseId: null,
  },
  {
    id: 1045,
    senderUpiId: "vikram@okaxis",
    receiverUpiId: "stranger882@ybl",
    amount: 80000,
    currency: "INR",
    createdAt: minutesAgo(47),
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
    id: 1046,
    senderUpiId: "meera@ibl",
    receiverUpiId: "arjun@okhdfc",
    amount: 2300,
    currency: "INR",
    createdAt: minutesAgo(43),
    fusedScore: 0.11,
    confidence: 0.65,
    interventionLevel: "inform",
    ruleScore: 0.0,
    mlScore: 0.14,
    graphScore: 0.0,
    reasonCodes: [],
    caseId: null,
  },
  {
    id: 1047,
    senderUpiId: "victim1@ibl",
    receiverUpiId: "collector7@okhdfc",
    amount: 9500,
    currency: "INR",
    createdAt: minutesAgo(39),
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
    id: 1048,
    senderUpiId: "victim2@okaxis",
    receiverUpiId: "collector7@okhdfc",
    amount: 7200,
    currency: "INR",
    createdAt: minutesAgo(36),
    fusedScore: 0.49,
    confidence: 0.9,
    interventionLevel: "verify",
    ruleScore: 0.5,
    mlScore: 0.44,
    graphScore: 0.55,
    reasonCodes: [
      { source: "rule", code: "fan_in_velocity", summary: "6 distinct senders paid this receiver within 10 minutes" },
      { source: "graph", code: "mule_collector_pattern", summary: "Receiver shows a mule-collector fan-in/fan-out shape" },
    ],
    caseId: null,
  },
  {
    id: 1049,
    senderUpiId: "bob@ybl",
    receiverUpiId: "priya@ibl",
    amount: 650,
    currency: "INR",
    createdAt: minutesAgo(33),
    fusedScore: 0.04,
    confidence: 0.68,
    interventionLevel: "inform",
    ruleScore: 0.0,
    mlScore: 0.05,
    graphScore: 0.0,
    reasonCodes: [],
    caseId: null,
  },
  {
    id: 1050,
    senderUpiId: "herder_collector4@ybl",
    receiverUpiId: "herder_cashout@okaxis",
    amount: 55000,
    currency: "INR",
    createdAt: minutesAgo(28),
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
    id: 1051,
    senderUpiId: "herder_cashout@okaxis",
    receiverUpiId: "mule_relay1@ybl",
    amount: 48000,
    currency: "INR",
    createdAt: minutesAgo(25),
    fusedScore: 0.74,
    confidence: 0.83,
    interventionLevel: "restrict",
    ruleScore: 0.2,
    mlScore: 0.9,
    graphScore: 0.95,
    reasonCodes: [
      { source: "graph", code: "shared_device_ring", summary: "Device linked to 3 other accounts" },
      { source: "graph", code: "rapid_relay", summary: "Funds forwarded within 90 seconds of receipt" },
    ],
    caseId: 1,
  },
  {
    id: 1052,
    senderUpiId: "arjun@okhdfc",
    receiverUpiId: "meera@ibl",
    amount: 1200,
    currency: "INR",
    createdAt: minutesAgo(21),
    fusedScore: 0.07,
    confidence: 0.72,
    interventionLevel: "inform",
    ruleScore: 0.0,
    mlScore: 0.09,
    graphScore: 0.0,
    reasonCodes: [],
    caseId: null,
  },
  {
    id: 1053,
    senderUpiId: "dev@ybl",
    receiverUpiId: "sana@okaxis",
    amount: 15000,
    currency: "INR",
    createdAt: minutesAgo(18),
    fusedScore: 0.28,
    confidence: 0.58,
    interventionLevel: "warn",
    ruleScore: 0.3,
    mlScore: 0.26,
    graphScore: 0.0,
    reasonCodes: [{ source: "rule", code: "amount_above_historical_average", summary: "Amount is 8.2x the account's historical average" }],
    caseId: null,
  },
  {
    id: 1054,
    senderUpiId: "unknown221@ibl",
    receiverUpiId: "known_scam_acc@ybl",
    amount: 32000,
    currency: "INR",
    createdAt: minutesAgo(14),
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
  {
    id: 1055,
    senderUpiId: "known_scam_acc@ybl",
    receiverUpiId: "fraud_ring_boss@ibl",
    amount: 29500,
    currency: "INR",
    createdAt: minutesAgo(11),
    fusedScore: 0.97,
    confidence: 0.95,
    interventionLevel: "escalate",
    ruleScore: 0.95,
    mlScore: 0.99,
    graphScore: 0.98,
    reasonCodes: [
      { source: "rule", code: "known_fraud_beneficiary", summary: "Sender is on the known-fraud watchlist" },
      { source: "graph", code: "fraud_cluster_exposure", summary: "Core node of a 5-account fraud cluster" },
      { source: "ml", code: "ml_feature:receiver_account_age_days", summary: "Brand-new receiver account" },
    ],
    caseId: 2,
  },
  {
    id: 1056,
    senderUpiId: "rahul@okhdfc",
    receiverUpiId: "alice@okaxis",
    amount: 3400,
    currency: "INR",
    createdAt: minutesAgo(7),
    fusedScore: 0.13,
    confidence: 0.66,
    interventionLevel: "inform",
    ruleScore: 0.0,
    mlScore: 0.16,
    graphScore: 0.0,
    reasonCodes: [],
    caseId: null,
  },
  {
    id: 1057,
    senderUpiId: "victim3@ibl",
    receiverUpiId: "collector7@okhdfc",
    amount: 6100,
    currency: "INR",
    createdAt: minutesAgo(4),
    fusedScore: 0.46,
    confidence: 0.88,
    interventionLevel: "verify",
    ruleScore: 0.45,
    mlScore: 0.4,
    graphScore: 0.5,
    reasonCodes: [
      { source: "rule", code: "fan_in_velocity", summary: "7 distinct senders paid this receiver within 10 minutes" },
      { source: "graph", code: "mule_collector_pattern", summary: "Receiver shows a mule-collector fan-in/fan-out shape" },
    ],
    caseId: null,
  },
  {
    id: 1058,
    senderUpiId: "alice@okaxis",
    receiverUpiId: "vikram@okaxis",
    amount: 2100,
    currency: "INR",
    createdAt: minutesAgo(1),
    fusedScore: 0.08,
    confidence: 0.71,
    interventionLevel: "inform",
    ruleScore: 0.0,
    mlScore: 0.1,
    graphScore: 0.0,
    reasonCodes: [],
    caseId: null,
  },
];

export const MOCK_STATS = {
  transactionsScored: 4218,
  flaggedRate: 0.084,
  activeCases: 2,
  avgFusedScore: 0.17,
};

export interface MockGraphNode {
  id: string;
  trueLabel: string | null;
  accountType: string | null;
  community: number;
}

export interface MockGraphEdge {
  source: string;
  target: string;
  type: string;
  weight: number;
}

export const MOCK_GRAPH: { nodes: MockGraphNode[]; edges: MockGraphEdge[] } = {
  nodes: [
    { id: "alice@okaxis", trueLabel: null, accountType: "personal", community: 0 },
    { id: "bob@ybl", trueLabel: null, accountType: "personal", community: 0 },
    { id: "priya@ibl", trueLabel: null, accountType: "personal", community: 0 },
    { id: "rahul@okhdfc", trueLabel: null, accountType: "personal", community: 0 },
    { id: "sana@okaxis", trueLabel: null, accountType: "personal", community: 0 },
    { id: "dev@ybl", trueLabel: null, accountType: "personal", community: 0 },
    { id: "meera@ibl", trueLabel: null, accountType: "personal", community: 0 },
    { id: "arjun@okhdfc", trueLabel: null, accountType: "personal", community: 0 },
    { id: "vikram@okaxis", trueLabel: null, accountType: "personal", community: 0 },
    { id: "stranger882@ybl", trueLabel: "suspicious", accountType: "personal", community: 3 },

    { id: "victim1@ibl", trueLabel: null, accountType: "personal", community: 1 },
    { id: "victim2@okaxis", trueLabel: null, accountType: "personal", community: 1 },
    { id: "victim3@ibl", trueLabel: null, accountType: "personal", community: 1 },
    { id: "collector7@okhdfc", trueLabel: "mule", accountType: "mule", community: 1 },

    { id: "herder_collector4@ybl", trueLabel: "mule", accountType: "mule", community: 2 },
    { id: "herder_cashout@okaxis", trueLabel: "mule", accountType: "mule", community: 2 },
    { id: "mule_relay1@ybl", trueLabel: "mule", accountType: "mule", community: 2 },
    { id: "mule_relay2@okaxis", trueLabel: "mule", accountType: "mule", community: 2 },

    { id: "unknown221@ibl", trueLabel: null, accountType: "personal", community: 4 },
    { id: "known_scam_acc@ybl", trueLabel: "fraud", accountType: "personal", community: 4 },
    { id: "fraud_ring_boss@ibl", trueLabel: "fraud", accountType: "personal", community: 4 },
  ],
  edges: [
    { source: "alice@okaxis", target: "bob@ybl", type: "transaction", weight: 3 },
    { source: "bob@ybl", target: "priya@ibl", type: "transaction", weight: 2 },
    { source: "priya@ibl", target: "rahul@okhdfc", type: "transaction", weight: 1 },
    { source: "sana@okaxis", target: "dev@ybl", type: "transaction", weight: 2 },
    { source: "dev@ybl", target: "sana@okaxis", type: "transaction", weight: 1 },
    { source: "meera@ibl", target: "arjun@okhdfc", type: "transaction", weight: 2 },
    { source: "arjun@okhdfc", target: "meera@ibl", type: "transaction", weight: 1 },
    { source: "rahul@okhdfc", target: "alice@okaxis", type: "transaction", weight: 1 },
    { source: "alice@okaxis", target: "vikram@okaxis", type: "transaction", weight: 1 },
    { source: "alice@okaxis", target: "priya@ibl", type: "repeated_counterparty", weight: 1 },
    { source: "vikram@okaxis", target: "stranger882@ybl", type: "transaction", weight: 1 },

    { source: "victim1@ibl", target: "collector7@okhdfc", type: "transaction", weight: 1 },
    { source: "victim2@okaxis", target: "collector7@okhdfc", type: "transaction", weight: 1 },
    { source: "victim3@ibl", target: "collector7@okhdfc", type: "transaction", weight: 1 },
    { source: "collector7@okhdfc", target: "herder_cashout@okaxis", type: "transaction", weight: 2 },
    { source: "collector7@okhdfc", target: "victim1@ibl", type: "repeated_counterparty", weight: 1 },

    { source: "herder_collector4@ybl", target: "herder_cashout@okaxis", type: "transaction", weight: 3 },
    { source: "herder_cashout@okaxis", target: "mule_relay1@ybl", type: "transaction", weight: 2 },
    { source: "mule_relay1@ybl", target: "mule_relay2@okaxis", type: "transaction", weight: 1 },
    { source: "herder_collector4@ybl", target: "herder_cashout@okaxis", type: "shared_device", weight: 1 },
    { source: "herder_cashout@okaxis", target: "mule_relay1@ybl", type: "shared_device", weight: 1 },
    { source: "mule_relay1@ybl", target: "mule_relay2@okaxis", type: "shared_device", weight: 1 },
    { source: "collector7@okhdfc", target: "herder_collector4@ybl", type: "shared_device", weight: 1 },

    { source: "unknown221@ibl", target: "known_scam_acc@ybl", type: "transaction", weight: 1 },
    { source: "known_scam_acc@ybl", target: "fraud_ring_boss@ibl", type: "transaction", weight: 2 },
    { source: "known_scam_acc@ybl", target: "fraud_ring_boss@ibl", type: "shared_device", weight: 1 },
    { source: "fraud_ring_boss@ibl", target: "collector7@okhdfc", type: "repeated_counterparty", weight: 1 },
  ],
};
