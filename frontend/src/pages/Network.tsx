import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import GraphScene, { scoreColor } from "../components/GraphScene";
import { formatScore } from "../lib/format";
import { useUrlState } from "../lib/useParams";

/* ------------------------------------------------------------------ page */

export default function Network() {
  const { params, set } = useUrlState();
  const depth = Number(params.get("depth") ?? 2);
  const urlAccount = params.get("account") ?? "";

  // With no account chosen, open on the most suspicious one instead of an empty form.
  const starting = useQuery({ queryKey: ["network-starting-points"], queryFn: () => api.transactions({ min_score: 0.55, limit: 1 }), enabled: !urlAccount });
  const account = urlAccount || starting.data?.items[0]?.receiver_upi_id || "";

  const [picked, setPicked] = useState<string | null>(null);
  useEffect(() => setPicked(null), [account]);
  const selected = picked ?? account;

  const graph = useQuery({ queryKey: ["graph", account, depth], queryFn: () => api.graph(account, depth), enabled: !!account });
  const profile = useQuery({ queryKey: ["account", selected], queryFn: () => api.account(selected), enabled: !!selected });

  const hasGraph = !!graph.data && graph.data.nodes.length > 1;
  const p = profile.data;

  return (
    <div className="neural">
      {hasGraph && <GraphScene graph={graph.data!} center={account} selected={selected} onSelect={setPicked} onRecenter={(id) => set({ account: id })} />}

      <div className="center-msg">
        {!hasGraph && (
          graph.isError ? "Couldn't load this network." : graph.isSuccess ? "This account has no links yet." : starting.isSuccess && !account ? "No high-risk accounts yet. Search for one above." : "Mapping the network…"
        )}
      </div>

      <div className="glass bar-top">
        <h1>Network</h1>
        <input type="search" aria-label="Account UPI id" placeholder="Search a UPI id" defaultValue={urlAccount} key={account}
          onKeyDown={(e) => e.key === "Enter" && set({ account: e.currentTarget.value.trim() })} />
        <div className="chip-group" role="group" aria-label="Hops">
          {[1, 2, 3].map((d) => <button key={d} className={depth === d ? "on" : ""} aria-pressed={depth === d} onClick={() => set({ depth: String(d) })}>{d} hop{d > 1 ? "s" : ""}</button>)}
        </div>
        <span className="spacer" />
        {graph.data && <span style={{ fontSize: 12.5, opacity: 0.6 }}>{graph.data.nodes.length} accounts · {graph.data.edges.length} links</span>}
      </div>

      {hasGraph && (
        <>
          <aside className="glass inspector" aria-label="Selected account">
            <div className="muted" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: "0.05em", color: "rgba(245,245,247,.5)", marginBottom: 6 }}>{selected === account ? "Centre account" : "Selected"}</div>
            <h3 className="mono" style={{ fontSize: 14 }}>{selected}</h3>
            {p ? (
              <>
                <div style={{ fontSize: 44, fontWeight: 700, letterSpacing: "-0.04em", lineHeight: 1.1, margin: "10px 0 2px", color: scoreColor(p.max_score) }} className="num">{formatScore(p.max_score)}</div>
                <div style={{ fontSize: 12, opacity: 0.55, marginBottom: 14 }}>Highest risk score</div>
                <dl className="kv">
                  <dt>Owner</dt><dd>{p.owner_name}</dd>
                  <dt>Type</dt><dd style={{ textTransform: "capitalize" }}>{p.account_type}</dd>
                  <dt>Counterparties</dt><dd className="num">{p.counterparties}</dd>
                  <dt>Flagged</dt><dd className="num">{p.flagged_count}</dd>
                  <dt>Open cases</dt><dd className="num">{p.open_cases}</dd>
                  <dt>Known fraud</dt><dd style={{ color: p.known_fraud ? "#e0436f" : undefined, fontWeight: p.known_fraud ? 600 : 400 }}>{p.known_fraud ? "Yes" : "No"}</dd>
                </dl>
                <div className="form-row" style={{ marginTop: 16 }}>
                  {selected !== account && <button className="btn sm" onClick={() => set({ account: selected })}>Centre here</button>}
                  <Link className="btn sm" to={`/accounts/${encodeURIComponent(selected)}`}>Open profile</Link>
                </div>
              </>
            ) : <div style={{ opacity: 0.55, marginTop: 12 }}>{profile.isError ? "No profile for this account." : "Loading…"}</div>}
          </aside>
          <div className="glass legend-glass">
            <span><b style={{ background: "#6c8fc7" }} />Low</span>
            <span><b style={{ background: "#f5a524" }} />Medium</span>
            <span><b style={{ background: "#f0524d" }} />High score</span>
            <span><b style={{ background: "transparent", border: "2px dashed #e0436f" }} />Known fraud</span>
            <span>Moving dots: payments, sender → receiver</span>
            <span>Dashed: shared device</span>
          </div>
          <div className="glass hint">Scroll to zoom · Drag to pan · Double-click to re-centre</div>
        </>
      )}
    </div>
  );
}
