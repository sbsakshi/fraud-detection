import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Ladder, ScoredTransaction } from "../api/types";
import { formatAmount, formatDateTime, formatScore, humanizeCode, renderTemplate } from "../lib/format";
import { LevelTag } from "./Tags";

const SOURCES: { key: "rule_score" | "ml_score" | "graph_score"; label: string }[] = [
  { key: "rule_score", label: "Rules" },
  { key: "ml_score", label: "ML" },
  { key: "graph_score", label: "Graph" },
];

/** Why the transaction got its level: the three inputs, how they blend, and which ladder rung matched. */
export function WhyThisLevel({ txn, ladder }: { txn: ScoredTransaction; ladder?: Ladder }) {
  const rs = txn.risk_score;
  return (
    <div>
      {SOURCES.map(({ key, label }) => (
        <div className="bar-row" key={key}>
          <span>{label}</span>
          <span className="bar" role="img" aria-label={`${label} score ${formatScore(rs[key])}`}>
            <i style={{ width: `${Math.round((rs[key] ?? 0) * 100)}%` }} />
          </span>
          <span className="num right">{formatScore(rs[key])}</span>
        </div>
      ))}
      <dl className="kv" style={{ marginTop: 10 }}>
        <dt>Fused score</dt>
        <dd className="num">
          {formatScore(rs.fused_score)}
          {ladder && (
            <span className="muted">
              {" "}
              = {ladder.weights.rule} × rules + {ladder.weights.ml} × ML + {ladder.weights.graph} × graph
            </span>
          )}
        </dd>
        <dt>Confidence</dt>
        <dd className="num">
          {formatScore(rs.confidence)}
          <span className="muted"> — how many sources fired, and how closely they agree</span>
        </dd>
      </dl>
      {ladder && (
        <div className="ladder" aria-label="Intervention ladder">
          {ladder.levels.map((l) => {
            const met = rs.fused_score >= l.min_score && rs.confidence >= l.min_confidence;
            const hit = l.level === rs.intervention_level;
            return (
              <div key={l.level} className={hit ? "hit" : met ? "met" : "unmet"}>
                <span style={{ textTransform: "capitalize" }}>{l.level}</span>
                <span className="num">
                  score ≥ {l.min_score.toFixed(2)}
                  {l.min_confidence > 0 && <> and confidence ≥ {l.min_confidence.toFixed(2)}</>}
                </span>
                <span>{hit ? "← applied" : ""}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function ReasonList({ txn }: { txn: ScoredTransaction }) {
  if (txn.reason_codes.length === 0) {
    return <p className="muted" style={{ margin: 0 }}>No rule, ML or graph signal fired for this transaction.</p>;
  }
  return (
    <div>
      {txn.reason_codes.map((r, i) => (
        <div className="reason" key={`${r.code}-${i}`}>
          <span className="src">{r.source}</span>
          <div>
            <div className="code">{humanizeCode(r.code)}</div>
            <div className="desc">{renderTemplate(r.template, r.details)}</div>
          </div>
          <span className="num muted">{r.contribution !== null ? `+${r.contribution.toFixed(2)}` : ""}</span>
        </div>
      ))}
    </div>
  );
}

export function TransactionSummary({ txn }: { txn: ScoredTransaction }) {
  return (
    <dl className="kv">
      <dt>Amount</dt>
      <dd className="num">{formatAmount(txn.amount, txn.currency)}</dd>
      <dt>From</dt>
      <dd><Link className="mono" to={`/accounts/${encodeURIComponent(txn.sender_upi_id)}`}>{txn.sender_upi_id}</Link></dd>
      <dt>To</dt>
      <dd><Link className="mono" to={`/accounts/${encodeURIComponent(txn.receiver_upi_id)}`}>{txn.receiver_upi_id}</Link></dd>
      <dt>When</dt>
      <dd>{formatDateTime(txn.created_at)}</dd>
      <dt>Transaction</dt>
      <dd className="mono">#{txn.transaction_id}</dd>
    </dl>
  );
}

/** Everything the transaction drawer and the case page show about one scored transaction. */
export default function TransactionDetail({ txn }: { txn: ScoredTransaction }) {
  const ladder = useQuery({ queryKey: ["ladder"], queryFn: api.ladder, staleTime: Infinity });
  return (
    <>
      <div className="section">
        <h4>Decision</h4>
        <div style={{ fontSize: 16 }}><LevelTag level={txn.risk_score.intervention_level} /></div>
        {txn.case && (
          <p style={{ margin: "6px 0 0" }}>
            <Link to={`/cases/${txn.case.id}`}>Case #{txn.case.id}</Link>{" "}
            <span className="muted">· {txn.case.status} · {txn.case.severity}</span>
          </p>
        )}
      </div>
      <div className="section"><h4>Transaction</h4><TransactionSummary txn={txn} /></div>
      <div className="section"><h4>Why this level</h4><WhyThisLevel txn={txn} ladder={ladder.data} /></div>
      <div className="section"><h4>Reason codes ({txn.reason_codes.length})</h4><ReasonList txn={txn} /></div>
    </>
  );
}
