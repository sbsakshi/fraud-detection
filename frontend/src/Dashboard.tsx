import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchStats, fetchTransactions, type Stats } from "./api";
import "./dashboard.css";
import { MOCK_STATS, MOCK_TRANSACTIONS, type InterventionLevel, type ScoredTransaction } from "./mockData";
import NetworkGraph from "./NetworkGraph";

const POLL_INTERVAL_MS = 3000;

const LEVEL_COLOR: Record<InterventionLevel, string> = {
  inform: "var(--inform)",
  warn: "var(--warn)",
  verify: "var(--verify)",
  hold: "var(--hold)",
  restrict: "var(--restrict)",
  escalate: "var(--escalate)",
};

const ROLES = ["Payer / Receiver", "Bank", "Investigator"] as const;
type Role = (typeof ROLES)[number];

function formatAmount(amount: number, currency: string): string {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency, maximumFractionDigits: 0 }).format(amount);
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function ScoreBar({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const color = score >= 0.7 ? "var(--restrict)" : score >= 0.35 ? "var(--warn)" : "#3aa66b";
  return (
    <div className="score-bar-wrap">
      <div className="score-bar-track">
        <div className="score-bar-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="mono">{score.toFixed(2)}</span>
    </div>
  );
}

function Badge({ level }: { level: InterventionLevel }) {
  return (
    <span className="badge" style={{ background: LEVEL_COLOR[level] }}>
      {level}
    </span>
  );
}

function ReasonDetail({ txn }: { txn: ScoredTransaction }) {
  if (txn.reasonCodes.length === 0) {
    return (
      <div className="detail-panel">
        <p className="empty-reasons">No rules, ML features, or graph patterns fired for this transaction.</p>
      </div>
    );
  }
  return (
    <div className="detail-panel">
      <h4>Reason codes ({txn.reasonCodes.length})</h4>
      {txn.reasonCodes.map((r, i) => (
        <div className="reason-row" key={i}>
          <span className={`source-chip source-${r.source}`}>{r.source}</span>
          <span>{r.summary}</span>
        </div>
      ))}
      {txn.caseId !== null && (
        <p style={{ marginTop: 10, marginBottom: 0, color: "var(--muted)", fontSize: "0.8rem" }}>
          Opened case #{txn.caseId} for investigation.
        </p>
      )}
    </div>
  );
}

export default function Dashboard() {
  const [role, setRole] = useState<Role>("Investigator");
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [focusUpiId, setFocusUpiId] = useState<string | null>(null);

  // `liveTransactions`/`liveStats` stay `null` until the backend has actually
  // scored something -- that's the only signal used to fall back to mock
  // data, so a reachable-but-empty backend (e.g. freshly started, nothing
  // scored yet) still shows the demo data instead of a blank table/graph. A
  // transient failure after a good poll keeps showing the last known feed
  // (with `connected` flipped off) instead of yanking the UI back to mocks.
  const [liveTransactions, setLiveTransactions] = useState<ScoredTransaction[] | null>(null);
  const [liveStats, setLiveStats] = useState<Stats | null>(null);
  const [connected, setConnected] = useState(false);
  const pollHandle = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const [txns, stats] = await Promise.all([fetchTransactions(), fetchStats()]);
        if (cancelled) return;
        if (txns.length > 0) {
          setLiveTransactions(txns);
          setLiveStats(stats);
        }
        setConnected(true);
      } catch {
        if (cancelled) return;
        setConnected(false);
      }
    }

    poll();
    pollHandle.current = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      if (pollHandle.current) clearInterval(pollHandle.current);
    };
  }, []);

  const usingLiveData = liveTransactions !== null;
  const allTransactions = usingLiveData ? liveTransactions : MOCK_TRANSACTIONS;
  const stats = liveStats ?? MOCK_STATS;
  // No auth in this demo, so "my" identity for the payer/receiver view is
  // just whoever sent the newest transaction in the feed currently shown.
  const selfUpiId = allTransactions[0]?.senderUpiId ?? "alice@okaxis";

  const transactions = useMemo(() => {
    let rows = allTransactions;
    if (role === "Payer / Receiver") {
      // A payer only ever sees their own transactions, and never the
      // internal score breakdown -- just whether they should be worried.
      rows = rows.filter((t) => t.senderUpiId === selfUpiId || t.receiverUpiId === selfUpiId);
    }
    if (focusUpiId) {
      rows = rows.filter((t) => t.senderUpiId === focusUpiId || t.receiverUpiId === focusUpiId);
    }
    return rows;
  }, [role, allTransactions, selfUpiId, focusUpiId]);

  // Stable identity so NetworkGraph's mouse/animation-loop effect (which
  // depends on this callback) doesn't tear down and rebuild on every render.
  const handleSelectAccount = useCallback((upiId: string | null) => setFocusUpiId(upiId), []);

  return (
    <div className="app">
      <div className="app-inner">
        <div className="header">
          <div>
            <h1>Finsight</h1>
            <p className="tagline">
              <span className="live-dot" />
              UPI fraud intelligence — rules + ML + graph, fused in real time
            </p>
          </div>
        </div>

        {usingLiveData && !connected && (
          <div className="mock-banner">
            Lost the connection to the backend — showing the last data received. Retrying every{" "}
            {POLL_INTERVAL_MS / 1000}s.
          </div>
        )}

        <div className="role-tabs">
          {ROLES.map((r) => (
            <button key={r} className={`role-tab ${role === r ? "active" : ""}`} onClick={() => setRole(r)}>
              {r}
            </button>
          ))}
        </div>

        <div className="stat-grid">
          <div className="stat-tile">
            <div className="label">Transactions scored</div>
            <div className="value">{stats.transactionsScored.toLocaleString()}</div>
          </div>
          <div className="stat-tile">
            <div className="label">Flagged rate</div>
            <div className="value">{(stats.flaggedRate * 100).toFixed(1)}%</div>
          </div>
          <div className="stat-tile">
            <div className="label">Active cases</div>
            <div className="value">{stats.activeCases}</div>
          </div>
          <div className="stat-tile">
            <div className="label">Avg fused score</div>
            <div className="value">{stats.avgFusedScore.toFixed(2)}</div>
          </div>
        </div>

        {role !== "Payer / Receiver" && (
          <div className="panel graph-panel">
            <div className="panel-header">
              <span>Money-movement graph</span>
              <span style={{ color: "var(--muted)", fontWeight: 400, fontSize: "0.75rem" }}>
                accounts as nodes, transactions/shared devices as edges
              </span>
            </div>
            <NetworkGraph selectedUpiId={focusUpiId} onSelectAccount={handleSelectAccount} />
          </div>
        )}

        <div className="panel">
          <div className="panel-header">
            <span>Live transaction feed</span>
            <span className="panel-header-right">
              {focusUpiId && (
                <button className="focus-chip" onClick={() => setFocusUpiId(null)}>
                  Focused on <span className="mono">{focusUpiId}</span> &times;
                </button>
              )}
              <span style={{ color: "var(--muted)", fontWeight: 400, fontSize: "0.75rem" }}>
                {transactions.length} shown
              </span>
            </span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Sender</th>
                  <th>Receiver</th>
                  <th>Amount</th>
                  {role !== "Payer / Receiver" && <th>Fused score</th>}
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {transactions.map((t) => (
                  <Fragment key={t.id}>
                    <tr onClick={() => setExpandedId(expandedId === t.id ? null : t.id)}>
                      <td className="mono">{formatTime(t.createdAt)}</td>
                      <td className="mono">{t.senderUpiId}</td>
                      <td className="mono">{t.receiverUpiId}</td>
                      <td>{formatAmount(t.amount, t.currency)}</td>
                      {role !== "Payer / Receiver" && (
                        <td>
                          <ScoreBar score={t.fusedScore} />
                        </td>
                      )}
                      <td>
                        <Badge level={t.interventionLevel} />
                      </td>
                    </tr>
                    {expandedId === t.id && role !== "Payer / Receiver" && (
                      <tr>
                        <td colSpan={6} style={{ padding: 0 }}>
                          <ReasonDetail txn={t} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <footer className="note">
          Finsight — synthetic UPI fraud intelligence. Click a row to see its reason codes.
        </footer>
      </div>
    </div>
  );
}
