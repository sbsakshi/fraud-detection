import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import Pager from "../components/Pager";
import { Empty, ErrorState, Loading } from "../components/States";
import { LevelTag, Score } from "../components/Tags";
import { formatAmount, formatDateTime, humanizeCode } from "../lib/format";
import { PAGE_SIZE, useUrlState } from "../lib/useParams";

export default function Account() {
  const upi = decodeURIComponent(useParams().upiId ?? "");
  const navigate = useNavigate();
  const { params, set } = useUrlState();
  const page = Number(params.get("page") ?? 0);

  const profile = useQuery({ queryKey: ["account", upi], queryFn: () => api.account(upi), refetchInterval: 10_000 });
  const txns = useQuery({
    queryKey: ["account-transactions", upi, page],
    queryFn: () => api.transactions({ account: upi, limit: PAGE_SIZE, offset: page * PAGE_SIZE }),
    placeholderData: keepPreviousData,
    refetchInterval: page === 0 ? 8000 : false,
  });

  if (profile.isPending) return <Loading rows={8} />;
  if (profile.isError) return <ErrorState error={profile.error} retry={() => profile.refetch()} />;
  const a = profile.data;

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="mono" style={{ fontSize: 18 }}>{a.upi_id}</h1>
          <div className="muted">{a.owner_name} · {a.bank_name} · <span style={{ textTransform: "capitalize" }}>{a.account_type}</span></div>
        </div>
        <span className="form-row">
          {a.known_fraud && <span className="pill danger">Known fraud</span>}
          {!a.is_active && <span className="pill">Inactive</span>}
          <Link className="btn" to={`/network?account=${encodeURIComponent(a.upi_id)}`}>View network</Link>
        </span>
      </div>

      <div className="grid cols-4" style={{ marginBottom: 16 }}>
        <div className="panel stat"><div className="label">Sent</div><div className="value">{a.transactions_sent.toLocaleString()}</div><div className="sub num">{formatAmount(a.total_sent)}</div></div>
        <div className="panel stat"><div className="label">Received</div><div className="value">{a.transactions_received.toLocaleString()}</div><div className="sub num">{formatAmount(a.total_received)}</div></div>
        <div className="panel stat"><div className="label">Flagged transactions</div><div className="value">{a.flagged_count.toLocaleString()}</div><div className="sub">Highest score <Score value={a.max_score} /></div></div>
        <div className="panel stat"><div className="label">Open cases</div><div className="value">{a.open_cases}</div><div className="sub">{a.counterparties} counterparties</div></div>
      </div>

      <div className="grid split">
        <div className="panel">
          <div className="panel-head">Transactions</div>
          {txns.isPending ? <Loading rows={8} /> : txns.isError ? <ErrorState error={txns.error} retry={() => txns.refetch()} /> :
            txns.data.items.length === 0 ? <Empty title="No transactions for this account" /> : (
              <>
                <div className="table-wrap">
                  <table>
                    <thead><tr><th>Time</th><th>Direction</th><th>Counterparty</th><th className="right">Amount</th><th className="right">Score</th><th>Level</th><th>Top reason</th></tr></thead>
                    <tbody>
                      {txns.data.items.map((t) => {
                        const out = t.sender_upi_id === upi;
                        const other = out ? t.receiver_upi_id : t.sender_upi_id;
                        return (
                          <tr key={t.transaction_id} className="clickable" tabIndex={0}
                            onClick={() => navigate(`/transactions?txn=${t.transaction_id}`)}
                            onKeyDown={(e) => e.key === "Enter" && navigate(`/transactions?txn=${t.transaction_id}`)}>
                            <td className="num">{formatDateTime(t.created_at)}</td>
                            <td>{out ? "Sent" : "Received"}</td>
                            <td className="mono trunc" onClick={(e) => e.stopPropagation()}><Link to={`/accounts/${encodeURIComponent(other)}`}>{other}</Link></td>
                            <td className="num right">{formatAmount(t.amount, t.currency)}</td>
                            <td className="right"><Score value={t.risk_score.fused_score} /></td>
                            <td><LevelTag level={t.risk_score.intervention_level} /></td>
                            <td className="trunc muted">{t.reason_codes[0] ? humanizeCode(t.reason_codes[0].code) : ""}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <Pager page={page} pageSize={PAGE_SIZE} total={txns.data.total} onPage={(p) => set({ page: String(p) }, false)} />
              </>
            )}
        </div>

        <div className="stack" style={{ gap: 16 }}>
          <div className="panel"><div className="panel-head">Details</div><div className="panel-body">
            <dl className="kv">
              <dt>Owner</dt><dd>{a.owner_name}</dd>
              <dt>Bank</dt><dd>{a.bank_name}</dd>
              <dt>IFSC</dt><dd className="mono">{a.ifsc_code}</dd>
              <dt>Device</dt><dd className="mono">{a.device_id ?? "—"}</dd>
              <dt>Account opened</dt><dd>{formatDateTime(a.created_at)}</dd>
            </dl>
          </div></div>
          <div className="panel"><div className="panel-head">Shares a device with</div><div className="panel-body">
            {a.shared_device_accounts.length === 0 ? <span className="muted">No other accounts seen on this device.</span> : (
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {a.shared_device_accounts.map((u) => <li key={u}><Link className="mono" to={`/accounts/${encodeURIComponent(u)}`}>{u}</Link></li>)}
              </ul>
            )}
          </div></div>
        </div>
      </div>
    </>
  );
}
