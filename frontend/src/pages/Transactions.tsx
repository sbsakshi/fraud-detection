import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { InterventionLevel } from "../api/types";
import Drawer from "../components/Drawer";
import Pager from "../components/Pager";
import { Empty, ErrorState, Loading } from "../components/States";
import { LevelTag, Score } from "../components/Tags";
import TransactionDetail from "../components/TransactionDetail";
import { formatAmount, formatDateTime, humanizeCode, LEVELS } from "../lib/format";
import { PAGE_SIZE, sinceFromWindow, useUrlState } from "../lib/useParams";

function TransactionDrawer({ id, onClose }: { id: number; onClose: () => void }) {
  const q = useQuery({ queryKey: ["transaction", id], queryFn: () => api.transaction(id) });
  return (
    <Drawer title={<h2 style={{ fontSize: 16 }}>Transaction #{id}</h2>} onClose={onClose}>
      {q.isPending ? <Loading /> : q.isError ? <ErrorState error={q.error} retry={() => q.refetch()} /> : <TransactionDetail txn={q.data} />}
    </Drawer>
  );
}

export default function Transactions() {
  const { params, set } = useUrlState();
  const levels = params.getAll("level") as InterventionLevel[];
  const minScore = params.get("min_score") ?? "";
  const source = params.get("source") ?? "";
  const win = params.get("window") ?? "";
  const hasCase = params.get("has_case") ?? "";
  const search = params.get("q") ?? "";
  const page = Number(params.get("page") ?? 0);
  const selected = params.get("txn") ? Number(params.get("txn")) : null;

  const query = useQuery({
    queryKey: ["transactions", levels, minScore, source, win, hasCase, search, page],
    queryFn: () =>
      api.transactions({
        level: levels,
        min_score: minScore ? Number(minScore) : undefined,
        source: source || undefined,
        since: sinceFromWindow(win),
        has_case: hasCase ? hasCase === "yes" : undefined,
        q: search || undefined,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }),
    placeholderData: keepPreviousData,
    refetchInterval: page === 0 ? 5000 : false, // keep the live head fresh; don't shuffle rows under someone paging back
  });

  const toggleLevel = (l: InterventionLevel) =>
    set({ level: levels.includes(l) ? levels.filter((x) => x !== l) : [...levels, l] });
  const filtered = levels.length > 0 || minScore || source || win || hasCase || search;

  return (
    <>
      <div className="page-head">
        <h1>Transactions</h1>
        <span className="meta">
          {query.dataUpdatedAt ? `Updated ${new Date(query.dataUpdatedAt).toLocaleTimeString("en-GB")}` : ""}
          {query.isFetching && !query.isPending ? " · refreshing" : ""}
        </span>
      </div>

      <div className="filters">
        <div className="chip-group" role="group" aria-label="Intervention level">
          {LEVELS.map((l) => (
            <button key={l} className={levels.includes(l) ? "on" : ""} aria-pressed={levels.includes(l)} onClick={() => toggleLevel(l)}>
              {l[0].toUpperCase() + l.slice(1)}
            </button>
          ))}
        </div>
        <select aria-label="Minimum score" value={minScore} onChange={(e) => set({ min_score: e.target.value })}>
          <option value="">Any score</option>
          <option value="0.15">Score ≥ 0.15</option>
          <option value="0.35">Score ≥ 0.35</option>
          <option value="0.55">Score ≥ 0.55</option>
          <option value="0.70">Score ≥ 0.70</option>
          <option value="0.90">Score ≥ 0.90</option>
        </select>
        <select aria-label="Signal source" value={source} onChange={(e) => set({ source: e.target.value })}>
          <option value="">Any source</option>
          <option value="rule">Rule fired</option>
          <option value="ml">ML fired</option>
          <option value="graph">Graph fired</option>
        </select>
        <select aria-label="Time window" value={win} onChange={(e) => set({ window: e.target.value })}>
          <option value="">All time</option>
          <option value="1h">Last hour</option>
          <option value="24h">Last 24 hours</option>
          <option value="7d">Last 7 days</option>
        </select>
        <select aria-label="Case" value={hasCase} onChange={(e) => set({ has_case: e.target.value })}>
          <option value="">With or without case</option>
          <option value="yes">Has case</option>
          <option value="no">No case</option>
        </select>
        <input type="search" aria-label="Search UPI id" placeholder="Search UPI id" defaultValue={search} key={search}
          onKeyDown={(e) => e.key === "Enter" && set({ q: e.currentTarget.value.trim() })}
          onBlur={(e) => e.currentTarget.value.trim() !== search && set({ q: e.currentTarget.value.trim() })} />
        {filtered && <button className="btn sm" onClick={() => set({ level: [], min_score: "", source: "", window: "", has_case: "", q: "" })}>Clear filters</button>}
      </div>

      <div className="panel">
        {query.isPending ? (
          <Loading rows={10} />
        ) : query.isError ? (
          <ErrorState error={query.error} retry={() => query.refetch()} />
        ) : query.data.items.length === 0 ? (
          <Empty title={filtered ? "No transactions match these filters" : "No transactions scored yet"}>
            {!filtered && <p>Load data with <span className="mono">python backend/scripts/replay_dataset.py</span>, or POST to <span className="mono">/transactions</span>.</p>}
          </Empty>
        ) : (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Time</th><th>From</th><th>To</th><th className="right">Amount</th>
                    <th className="right">Score</th><th>Level</th><th>Top reason</th><th>Case</th>
                  </tr>
                </thead>
                <tbody>
                  {query.data.items.map((t) => (
                    <tr key={t.transaction_id} className={`clickable ${selected === t.transaction_id ? "selected" : ""}`}
                      tabIndex={0}
                      onClick={() => set({ txn: String(t.transaction_id) }, false)}
                      onKeyDown={(e) => e.key === "Enter" && set({ txn: String(t.transaction_id) }, false)}>
                      <td className="num">{formatDateTime(t.created_at)}</td>
                      <td className="mono trunc">{t.sender_upi_id}</td>
                      <td className="mono trunc">{t.receiver_upi_id}</td>
                      <td className="num right">{formatAmount(t.amount, t.currency)}</td>
                      <td className="right"><Score value={t.risk_score.fused_score} /></td>
                      <td><LevelTag level={t.risk_score.intervention_level} /></td>
                      <td className="trunc muted">{t.reason_codes[0] ? humanizeCode(t.reason_codes[0].code) : ""}</td>
                      <td onClick={(e) => e.stopPropagation()}>{t.case ? <Link to={`/cases/${t.case.id}`}>#{t.case.id}</Link> : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager page={page} pageSize={PAGE_SIZE} total={query.data.total} onPage={(p) => set({ page: String(p) }, false)} />
          </>
        )}
      </div>

      {selected !== null && <TransactionDrawer id={selected} onClose={() => set({ txn: null }, false)} />}
    </>
  );
}
