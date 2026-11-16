import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { AccountBrief, InterventionLevel, ScoredTransaction } from "../api/types";
import GraphScene from "../components/GraphScene";
import { formatAmount, humanizeCode, renderTemplate } from "../lib/format";

type Step = "pay" | "amount" | "processing" | "result";
type Tone = "safe" | "caution" | "blocked";
interface LogEntry { id: number; from: string; to: string; fromName: string; toName: string; amount: number; level: InterventionLevel; to_upi: string; from_upi: string }

const TONE: Record<InterventionLevel, Tone> = { inform: "safe", warn: "caution", verify: "caution", hold: "blocked", restrict: "blocked", escalate: "blocked" };
const HEADLINE: Record<InterventionLevel, [string, string]> = {
  inform: ["Payment sent", "No risk signals found."],
  warn: ["Payment sent, with a warning", "Something looks unusual about this payee."],
  verify: ["Verify to continue", "We need extra confirmation before this goes through."],
  hold: ["Payment on hold", "This payment looks unsafe and is being reviewed."],
  restrict: ["Payment blocked", "This payee looks unsafe. The payment was stopped."],
  escalate: ["Payment blocked", "This payment was stopped and sent to the fraud team."],
};
const PHASES = ["Payment received", "Rules", "ML model", "Graph analysis", "Fusion", "Decision"];
const QUICK = [500, 5000, 25000, 100000];

const initials = (name: string) => name.split(/\s+/).map((p) => p[0]).slice(0, 2).join("").toUpperCase();
const hue = (s: string) => [...s].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);
function Avatar({ name, upi, size = 40 }: { name: string; upi: string; size?: number }) {
  return <span className="avatar" style={{ width: size, height: size, fontSize: size * 0.38, background: `hsl(${hue(upi)} 45% 38%)` }}>{initials(name)}</span>;
}

function useDebounced<T>(value: T, ms = 200): T {
  const [v, setV] = useState(value);
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t); }, [value, ms]);
  return v;
}

/* ---------------------------------------------------------------- phone */

function Phone({ children }: { children: React.ReactNode }) {
  return (
    <div className="phone" aria-label="Simulated phone">
      <div className="phone-island" />
      <div className="phone-status"><span>9:41</span><span>5G ▮▮▮</span></div>
      <div className="phone-screen">{children}</div>
      <div className="phone-home" />
    </div>
  );
}

export default function Demo() {
  const qc = useQueryClient();
  const [sender, setSender] = useState<AccountBrief | null>(null);
  const [receiver, setReceiver] = useState<AccountBrief | null>(null);
  const [choosingSender, setChoosingSender] = useState(false);
  const [q, setQ] = useState("");
  const [amount, setAmount] = useState("");
  const [step, setStep] = useState<Step>("pay");
  const [result, setResult] = useState<ScoredTransaction | null>(null);
  const [phase, setPhase] = useState(-1);
  const [hints, setHints] = useState(false);
  const [log, setLog] = useState<LogEntry[]>([]);
  const timers = useRef<number[]>([]);
  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  const dq = useDebounced(q.trim());
  const contacts = useQuery({ queryKey: ["contacts", dq], queryFn: () => api.searchAccounts(dq, 30), placeholderData: (p) => p });
  const flagged = useQuery({ queryKey: ["flagged-receivers"], queryFn: () => api.transactions({ min_score: 0.7, limit: 200 }), staleTime: 60_000 });
  const flaggedSet = useMemo(() => new Set(flagged.data?.items.map((t) => t.receiver_upi_id) ?? []), [flagged.data]);

  // Default payer: the first account, so the phone is usable straight away.
  useEffect(() => { if (!sender && contacts.data?.length) setSender(contacts.data[0]); }, [contacts.data, sender]);

  const stats = useQuery({ queryKey: ["stats"], queryFn: api.transactionStats, refetchInterval: 4000 });
  const cases = useQuery({ queryKey: ["case-summary"], queryFn: api.caseSummary, refetchInterval: 4000 });
  const openCases = cases.data ? Object.values(cases.data.open_by_severity).reduce((a, b) => a + b, 0) : null;

  const graph = useQuery({
    queryKey: ["demo-graph", receiver?.upi_id, result?.transaction_id],
    queryFn: () => api.graph(receiver!.upi_id, 2),
    enabled: !!receiver && (step === "result" || step === "processing" || phase >= 0),
    placeholderData: (p) => p,
  });

  const pay = useMutation({ mutationFn: api.scoreTransaction });

  function pickReceiver(a: AccountBrief) { setReceiver(a); setAmount(""); setStep("amount"); }
  async function suggest(kind: "flagged" | "normal") {
    const pool = kind === "flagged" ? [...flaggedSet] : (contacts.data ?? []).map((c) => c.upi_id).filter((u) => !flaggedSet.has(u) && u !== sender?.upi_id);
    const upi = pool[Math.floor(Math.random() * pool.length)];
    if (!upi) return;
    const [a] = await api.searchAccounts(upi, 1);
    if (a) pickReceiver(a);
  }

  const value = Number(amount);
  function send() {
    if (!sender || !receiver || !(value > 0)) return;
    timers.current.forEach(clearTimeout); timers.current = [];
    setStep("processing"); setPhase(0); setResult(null);
    pay.mutate(
      { sender_upi_id: sender.upi_id, receiver_upi_id: receiver.upi_id, amount: value, device_id: sender.device_id ?? "dev-demo", transaction_type: "P2P" },
      {
        onSuccess: (res) => {
          setResult(res);
          PHASES.forEach((_, i) => { if (i > 0) timers.current.push(window.setTimeout(() => setPhase(i), i * 480)); });
          timers.current.push(window.setTimeout(() => {
            setStep("result");
            setLog((l) => [{ id: res.transaction_id, from_upi: sender.upi_id, to_upi: receiver.upi_id, fromName: sender.owner_name, toName: receiver.owner_name, amount: value, level: res.risk_score.intervention_level, from: sender.upi_id, to: receiver.upi_id }, ...l]);
            for (const k of ["stats", "case-summary", "timeseries", "urgent-cases", "reason-codes"]) qc.invalidateQueries({ queryKey: [k] });
          }, PHASES.length * 480));
        },
        onError: () => { setStep("amount"); setPhase(-1); },
      },
    );
  }
  function again() { setStep("pay"); setReceiver(null); setResult(null); setPhase(-1); setAmount(""); setQ(""); pay.reset(); }

  const level = result?.risk_score.intervention_level;
  const tone = level ? TONE[level] : null;
  const rs = result?.risk_score;
  const topReason = result?.reason_codes[0];
  const payment = result && sender && receiver ? { from: sender.upi_id, to: receiver.upi_id } : null;

  return (
    <div className="demo">
      <section className="demo-phone">
        <Phone>
          {choosingSender ? (
            <div className="app">
              <div className="app-top"><button className="link" onClick={() => setChoosingSender(false)}>Cancel</button><b>Pay from</b><span /></div>
              <input autoFocus type="search" placeholder="Search accounts" value={q} onChange={(e) => setQ(e.target.value)} />
              <ContactList items={contacts.data} hints={false} flagged={flaggedSet} onPick={(a) => { setSender(a); setChoosingSender(false); setQ(""); }} />
            </div>
          ) : step === "pay" ? (
            <div className="app">
              <div className="app-top"><b>Pay</b><button className="chip-from" onClick={() => { setQ(""); setChoosingSender(true); }}>
                {sender ? <><Avatar name={sender.owner_name} upi={sender.upi_id} size={22} /> {sender.owner_name.split(" ")[0]} ▾</> : "…"}
              </button></div>
              <input type="search" placeholder="Search name or UPI id" value={q} onChange={(e) => setQ(e.target.value)} />
              <div className="suggest">
                <button className="link" onClick={() => suggest("normal")}>Try a regular contact</button>
                <button className="link" onClick={() => suggest("flagged")}>Try a flagged account</button>
              </div>
              <div className="app-sub">People</div>
              <ContactList items={contacts.data?.filter((c) => c.upi_id !== sender?.upi_id)} hints={hints} flagged={flaggedSet} onPick={pickReceiver} />
            </div>
          ) : step === "amount" && receiver ? (
            <div className="app center">
              <div className="app-top"><button className="link" onClick={() => setStep("pay")}>‹ Back</button><span /><span /></div>
              <Avatar name={receiver.owner_name} upi={receiver.upi_id} size={72} />
              <h2>{receiver.owner_name}</h2>
              <div className="muted mono">{receiver.upi_id}</div>
              <div className="muted" style={{ fontSize: 12 }}>{receiver.bank_name}</div>
              <div className="amount"><span>₹</span><input inputMode="numeric" autoFocus placeholder="0" value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^\d]/g, "").slice(0, 8))} /></div>
              <div className="quick">{QUICK.map((n) => <button key={n} onClick={() => setAmount(String(n))}>₹{n.toLocaleString("en-IN")}</button>)}</div>
              {pay.isError && <div className="phone-error">Couldn't reach the server. Try again.</div>}
              <button className="pay-btn" disabled={!(value > 0)} onClick={send}>Pay {value > 0 ? formatAmount(value) : ""}</button>
            </div>
          ) : step === "processing" ? (
            <div className="app center"><div className="spinner" /><h2>Checking this payment…</h2><div className="muted">Paying {receiver?.owner_name}</div></div>
          ) : (
            <div className={`app center result ${tone}`}>
              <div className="result-icon">{tone === "safe" ? "✓" : tone === "caution" ? "!" : "✕"}</div>
              <h2>{level && HEADLINE[level][0]}</h2>
              <div className="muted">{level && HEADLINE[level][1]}</div>
              {tone !== "safe" && topReason && <div className="why">{renderTemplate(topReason.template, topReason.details)}</div>}
              <div className="receipt">
                <div><span>To</span><b>{receiver?.owner_name}</b></div>
                <div><span>Amount</span><b>{formatAmount(value)}</b></div>
              </div>
              <button className="pay-btn" onClick={again}>Done</button>
            </div>
          )}
        </Phone>
        <label className="hints"><input type="checkbox" checked={hints} onChange={(e) => setHints(e.target.checked)} /> Presenter hints: mark flagged payees</label>
      </section>

      <section className="demo-back">
        <header className="back-head">
          <div><div className="meta"><span className="live-dot" />Behind the scenes</div><h1>What Finsight sees</h1></div>
          <div className="mini-stats">
            <div><b className="num">{stats.data?.transactions_scored.toLocaleString() ?? "–"}</b><span>scored</span></div>
            <div><b className="num">{openCases ?? "–"}</b><span>active cases</span></div>
          </div>
        </header>

        <div className="panel pipeline">
          {PHASES.map((name, i) => {
            const active = phase >= i && phase >= 0;
            const score = i === 1 ? rs?.rule_score : i === 2 ? rs?.ml_score : i === 3 ? rs?.graph_score : i === 4 ? rs?.fused_score : null;
            return (
              <div key={name} className={`stage ${active ? "on" : ""} ${phase === i && step === "processing" ? "now" : ""}`}>
                <div className="stage-name">{name}</div>
                {i >= 1 && i <= 4 ? (
                  <>
                    <div className="stage-bar"><i style={{ width: active && score != null ? `${Math.max(2, score * 100)}%` : "0%", background: i === 4 ? `var(--lv-${level ?? "inform"})` : undefined }} /></div>
                    <div className="stage-val num">{active ? (score == null ? "n/a" : score.toFixed(2)) : "–"}</div>
                  </>
                ) : i === 5 ? (
                  <div className={`stage-val decision ${active && level ? `lv-${level}` : ""}`}>{active && level ? level : "–"}</div>
                ) : <div className="stage-val">{active && result ? formatAmount(result.amount) : "–"}</div>}
              </div>
            );
          })}
        </div>

        <div className="demo-grid">
          <div className="panel graph-card">
            <div className="panel-head" style={{ position: "absolute", zIndex: 2, left: 0, right: 0 }}>
              <span>{receiver ? `Network around ${receiver.owner_name}` : "Account network"}</span>
              {graph.data && <span className="muted">{graph.data.nodes.length} accounts · {graph.data.edges.length} links</span>}
            </div>
            {graph.data && receiver && graph.data.nodes.length > 1
              ? <GraphScene compact graph={graph.data} center={receiver.upi_id} selected={sender?.upi_id ?? receiver.upi_id} payment={payment} onSelect={() => {}} onRecenter={() => {}} />
              : <div className="center-msg">{receiver ? (graph.isPending ? "Mapping the network…" : "No links yet") : "Choose a payee on the phone to see who they're connected to."}</div>}
          </div>

          <div className="stack" style={{ gap: 20 }}>
            <div className="panel">
              <div className="panel-head">Why <span className="muted">{result ? `txn #${result.transaction_id}` : ""}</span></div>
              <div className="panel-body">
                {phase < 5 || !result ? <div className="muted">Waiting for a payment…</div> : result.reason_codes.length === 0 ? <div className="muted">No signals fired.</div> : result.reason_codes.slice(0, 5).map((r) => (
                  <div className="reason" key={`${r.source}-${r.code}`}>
                    <span className="src">{r.source}</span>
                    <div><div className="code">{humanizeCode(r.code)}</div><div className="desc">{renderTemplate(r.template, r.details)}</div></div>
                  </div>
                ))}
                {result?.case && phase >= 5 && <Link className="btn sm" style={{ marginTop: 12 }} to={`/cases/${result.case.id}`}>Case #{result.case.id} opened →</Link>}
              </div>
            </div>
            <div className="panel">
              <div className="panel-head">This session</div>
              <div className="panel-body">
                {log.length === 0 ? <div className="muted">No payments yet.</div> : log.slice(0, 6).map((e) => (
                  <div className="log-row" key={e.id}>
                    <span className="truncate">{e.fromName.split(" ")[0]} → {e.toName.split(" ")[0]}</span>
                    <span className="num">{formatAmount(e.amount)}</span>
                    <span className={`tag lv-${e.level}`}><span className="dot" />{e.level}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}

function ContactList({ items, hints, flagged, onPick }: { items?: AccountBrief[]; hints: boolean; flagged: Set<string>; onPick: (a: AccountBrief) => void }) {
  if (!items) return <div className="muted" style={{ padding: 16 }}>Loading…</div>;
  if (items.length === 0) return <div className="muted" style={{ padding: 16 }}>No one found.</div>;
  return (
    <ul className="contacts">
      {items.map((a) => (
        <li key={a.upi_id}>
          <button onClick={() => onPick(a)}>
            <Avatar name={a.owner_name} upi={a.upi_id} />
            <span className="who"><b>{a.owner_name}</b><small>{a.upi_id}</small></span>
            {hints && flagged.has(a.upi_id) && <span className="risk-dot" title="Flagged by Finsight" />}
          </button>
        </li>
      ))}
    </ul>
  );
}
