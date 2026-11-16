import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import { Empty, ErrorState, Loading } from "../components/States";
import { Severity } from "../components/Tags";
import { formatAge, formatAmount, humanizeCode, LEVELS, SEVERITIES } from "../lib/format";

const RANGES = [6, 24, 72] as const;
const cap = (s: string) => s[0].toUpperCase() + s.slice(1);
const tooltipStyle = { background: "var(--surface)", border: "none", borderRadius: 12, fontSize: 12.5, boxShadow: "0 8px 30px rgba(0,0,0,.18)" };

function Stat({ label, value, sub, spark, color = "var(--accent)" }: { label: string; value: React.ReactNode; sub?: React.ReactNode; spark?: { v: number }[]; color?: string }) {
  return (
    <div className="panel stat">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      <div className="sub">{sub ?? " "}</div>
      {spark && spark.length > 1 && (
        <div className="spark" aria-hidden>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={spark} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
              <defs><linearGradient id={`g-${label}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={color} stopOpacity={0.35} /><stop offset="100%" stopColor={color} stopOpacity={0} /></linearGradient></defs>
              <Area type="monotone" dataKey="v" stroke={color} strokeWidth={2} fill={`url(#g-${label})`} isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

function HBar({ name, value, max, color, lead }: { name: string; value: number; max: number; color?: string; lead?: React.ReactNode }) {
  return (
    <div className="hbar">
      <span className="name">{lead}{name}</span>
      <span className="num">{value.toLocaleString()}</span>
      <span className="track"><i style={{ width: `${max ? (value / max) * 100 : 0}%`, background: color }} /></span>
    </div>
  );
}

export default function Analytics() {
  const [hours, setHours] = useState<(typeof RANGES)[number]>(24);
  const stats = useQuery({ queryKey: ["stats"], queryFn: api.transactionStats, refetchInterval: 5000 });
  const cases = useQuery({ queryKey: ["case-summary"], queryFn: api.caseSummary, refetchInterval: 10_000 });
  const series = useQuery({ queryKey: ["timeseries", hours], queryFn: () => api.timeseries(hours), refetchInterval: 15_000 });
  const reasons = useQuery({ queryKey: ["reason-codes", hours], queryFn: () => api.reasonCodes(hours), refetchInterval: 15_000 });
  const urgent = useQuery({
    queryKey: ["urgent-cases"],
    queryFn: () => api.cases({ status: ["open", "investigating", "escalated"], limit: 7 }),
    refetchInterval: 10_000,
  });

  const fmtHour = (iso: string) => new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  const chartData = series.data?.map((b) => ({ hour: fmtHour(b.start), ...b.counts }));
  const totals = series.data?.reduce((n, b) => n + b.total, 0) ?? 0;
  const byLevel = LEVELS.map((l) => ({ l, n: series.data?.reduce((s, b) => s + (b.counts[l] ?? 0), 0) ?? 0 }));
  const flaggedSpark = series.data?.map((b) => ({ v: b.total ? (b.total - (b.counts.inform ?? 0)) / b.total : 0 }));
  const volumeSpark = series.data?.map((b) => ({ v: b.total }));
  const openTotal = cases.data ? Object.values(cases.data.open_by_severity).reduce((a, b) => a + b, 0) : null;
  const maxSev = cases.data ? Math.max(1, ...SEVERITIES.map((s) => cases.data.open_by_severity[s])) : 1;
  const now = Date.now();

  return (
    <>
      <div className="page-head">
        <div>
          <div className="meta" style={{ marginBottom: 6 }}><span className="live-dot" />Live</div>
          <h1>Analytics</h1>
        </div>
        <div className="chip-group" role="group" aria-label="Time range">
          {RANGES.map((r) => <button key={r} className={hours === r ? "on" : ""} aria-pressed={hours === r} onClick={() => setHours(r)}>{r}h</button>)}
        </div>
      </div>

      {stats.isError && <ErrorState error={stats.error} retry={() => stats.refetch()} />}
      <div className="grid cols-4" style={{ marginBottom: 20 }}>
        <Stat label="Transactions scored" value={stats.data ? stats.data.transactions_scored.toLocaleString() : "–"} sub={series.data ? `${totals.toLocaleString()} in ${hours}h` : undefined} spark={volumeSpark} />
        <Stat label="Flagged rate" value={stats.data ? `${(stats.data.flagged_rate * 100).toFixed(1)}%` : "–"} sub="Above inform level" spark={flaggedSpark} color="var(--lv-verify)" />
        <Stat label="Active cases" value={openTotal ?? "–"} sub={cases.data ? `${cases.data.unassigned} unassigned` : undefined} />
        <Stat label="Average fused score" value={stats.data ? stats.data.avg_fused_score.toFixed(3) : "–"} sub={cases.data ? `${cases.data.closed} cases closed` : undefined} />
      </div>

      <div className="grid main-side" style={{ marginBottom: 20 }}>
        <div className="panel">
          <div className="panel-head">Transactions by decision <span className="muted">per hour</span></div>
          {series.isPending ? <Loading rows={6} /> : series.isError ? <ErrorState error={series.error} retry={() => series.refetch()} /> :
            totals === 0 ? <Empty title={`No transactions in the last ${hours} hours`} /> : (
              <div className="panel-body" style={{ height: 320 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} margin={{ top: 8, right: 0, left: -18, bottom: 0 }} barCategoryGap="22%">
                    <CartesianGrid vertical={false} stroke="var(--border)" />
                    <XAxis dataKey="hour" tick={{ fill: "var(--text-2)", fontSize: 11 }} tickLine={false} axisLine={false} interval={Math.ceil((chartData?.length ?? 24) / 8) - 1} />
                    <YAxis tick={{ fill: "var(--text-2)", fontSize: 11 }} tickLine={false} axisLine={false} allowDecimals={false} />
                    <Tooltip cursor={{ fill: "var(--surface-2)", radius: 6 }} contentStyle={tooltipStyle} />
                    {LEVELS.map((l, i) => <Bar key={l} dataKey={l} name={cap(l)} stackId="a" fill={`var(--lv-${l})`} radius={i === LEVELS.length - 1 ? [4, 4, 0, 0] : 0} isAnimationActive={false} />)}
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
        </div>

        <div className="panel">
          <div className="panel-head">Decision mix <span className="muted">{hours}h</span></div>
          <div className="panel-body">
            <div className="seg-mix" aria-hidden>
              {byLevel.filter((x) => x.n > 0).map((x) => <i key={x.l} style={{ flex: x.n, background: `var(--lv-${x.l})` }} />)}
            </div>
            {byLevel.map(({ l, n }) => (
              <div key={l} className="hbar" style={{ gridTemplateColumns: "1fr auto auto" }}>
                <span className="name"><span className={`tag lv-${l}`}><span className="dot" />{cap(l)}</span></span>
                <span className="num">{n.toLocaleString()}</span>
                <span className="num muted" style={{ width: 52, textAlign: "right" }}>{totals ? `${((n / totals) * 100).toFixed(1)}%` : "–"}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="grid main-side">
        <div className="panel">
          <div className="panel-head">Cases needing attention <Link to="/cases" style={{ fontWeight: 400, fontSize: 13 }}>See all</Link></div>
          {urgent.isPending ? <Loading rows={5} /> : urgent.isError ? <ErrorState error={urgent.error} retry={() => urgent.refetch()} /> :
            urgent.data.items.length === 0 ? <Empty title="No active cases" /> : (
              <div className="table-wrap"><table>
                <thead><tr><th>Case</th><th>Severity</th><th className="right">Amount</th><th>Top signal</th><th className="right">Age</th></tr></thead>
                <tbody>
                  {urgent.data.items.map((c) => (
                    <tr key={c.id}>
                      <td className="num"><Link to={`/cases/${c.id}`}>#{c.id}</Link></td>
                      <td><Severity value={c.severity} /></td>
                      <td className="num right">{formatAmount(c.amount, c.currency)}</td>
                      <td className="muted trunc">{c.top_reason ? humanizeCode(c.top_reason) : ""}</td>
                      <td className="num right muted">{formatAge(c.created_at, now)}</td>
                    </tr>
                  ))}
                </tbody>
              </table></div>
            )}
        </div>

        <div className="stack" style={{ gap: 20 }}>
          <div className="panel">
            <div className="panel-head">Open cases by severity</div>
            <div className="panel-body">
              {SEVERITIES.map((s) => <HBar key={s} name={cap(s)} value={cases.data?.open_by_severity[s] ?? 0} max={maxSev} color={`var(--lv-${s === "critical" ? "escalate" : s === "high" ? "restrict" : s === "medium" ? "verify" : "inform"})`} />)}
            </div>
          </div>
          <div className="panel">
            <div className="panel-head">Top signals <span className="muted">{hours}h</span></div>
            <div className="panel-body">
              {reasons.isPending ? <Loading rows={5} /> : reasons.isError ? <ErrorState error={reasons.error} retry={() => reasons.refetch()} /> :
                reasons.data.length === 0 ? <Empty title="Nothing fired" /> :
                  reasons.data.map((r) => <HBar key={`${r.source}-${r.code}`} name={humanizeCode(r.code)} value={r.count} max={reasons.data[0].count} lead={<span className="src">{r.source}</span>} />)}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
