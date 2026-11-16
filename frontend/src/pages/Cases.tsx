import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { CaseStatus } from "../api/types";
import Pager from "../components/Pager";
import { Empty, ErrorState, Loading } from "../components/States";
import { LevelTag, Score, Severity, StatusPill } from "../components/Tags";
import { useAnalyst } from "../lib/actor";
import { formatAge, formatAmount, humanizeCode } from "../lib/format";
import { PAGE_SIZE, useUrlState } from "../lib/useParams";

const STATUS_TABS: { key: string; label: string; statuses: CaseStatus[] }[] = [
  { key: "active", label: "Active", statuses: ["open", "investigating", "escalated"] },
  { key: "closed", label: "Closed", statuses: ["closed"] },
  { key: "all", label: "All", statuses: [] },
];

export default function Cases() {
  const { params, set } = useUrlState();
  const [analyst] = useAnalyst();
  const navigate = useNavigate();
  const tab = params.get("tab") ?? "active";
  const severity = params.get("severity") ?? "";
  const assignee = params.get("assignee") ?? ""; // "", "me", "none"
  const page = Number(params.get("page") ?? 0);
  const statuses = STATUS_TABS.find((t) => t.key === tab)?.statuses ?? [];

  const query = useQuery({
    queryKey: ["cases", tab, severity, assignee, analyst, page],
    queryFn: () =>
      api.cases({
        status: statuses,
        severity: severity ? [severity] : undefined,
        assigned_to: assignee === "me" ? analyst || "\u0000" : undefined,
        unassigned: assignee === "none" || undefined,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }),
    placeholderData: keepPreviousData,
    refetchInterval: 8000,
  });
  const now = Date.now();

  return (
    <>
      <div className="page-head">
        <h1>Cases</h1>
        <span className="meta">Open work first, most severe, then oldest.</span>
      </div>
      <div className="filters">
        <div className="chip-group" role="group" aria-label="Case state">
          {STATUS_TABS.map((t) => (
            <button key={t.key} className={tab === t.key ? "on" : ""} aria-pressed={tab === t.key} onClick={() => set({ tab: t.key })}>{t.label}</button>
          ))}
        </div>
        <select aria-label="Severity" value={severity} onChange={(e) => set({ severity: e.target.value })}>
          <option value="">Any severity</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
        <select aria-label="Assignee" value={assignee} onChange={(e) => set({ assignee: e.target.value })}>
          <option value="">Anyone</option>
          <option value="me" disabled={!analyst}>Assigned to me{analyst ? "" : " (set your name first)"}</option>
          <option value="none">Unassigned</option>
        </select>
      </div>

      <div className="panel">
        {query.isPending ? <Loading rows={8} /> : query.isError ? <ErrorState error={query.error} retry={() => query.refetch()} /> :
          query.data.items.length === 0 ? (
            <Empty title={tab === "active" && !severity && !assignee ? "No active cases" : "No cases match"}>
              <p>Cases open automatically when a transaction scores at restrict or escalate.</p>
            </Empty>
          ) : (
            <>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th>Case</th><th>Severity</th><th>Status</th><th>Level</th><th className="right">Score</th><th>From → To</th><th className="right">Amount</th><th>Top reason</th><th>Assigned</th><th className="right">Age</th></tr>
                  </thead>
                  <tbody>
                    {query.data.items.map((c) => (
                      <tr key={c.id} className="clickable" tabIndex={0} onClick={() => navigate(`/cases/${c.id}`)} onKeyDown={(e) => e.key === "Enter" && navigate(`/cases/${c.id}`)}>
                        <td className="num">#{c.id}</td>
                        <td><Severity value={c.severity} /></td>
                        <td><StatusPill status={c.status} /></td>
                        <td><LevelTag level={c.intervention_level} /></td>
                        <td className="right"><Score value={c.fused_score} /></td>
                        <td className="mono trunc wide" title={`${c.sender_upi_id} → ${c.receiver_upi_id}`}>{c.sender_upi_id} → {c.receiver_upi_id}</td>
                        <td className="num right">{formatAmount(c.amount, c.currency)}</td>
                        <td className="muted">{c.top_reason ? humanizeCode(c.top_reason) : ""}</td>
                        <td>{c.assigned_to ?? <span className="muted">—</span>}</td>
                        <td className="num right">{formatAge(c.created_at, now)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Pager page={page} pageSize={PAGE_SIZE} total={query.data.total} onPage={(p) => set({ page: String(p) }, false)} />
            </>
          )}
      </div>
    </>
  );
}
