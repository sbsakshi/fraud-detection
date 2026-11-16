import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { CaseResolution, CaseStatus } from "../api/types";
import { ErrorState, Loading } from "../components/States";
import { Severity, StatusPill } from "../components/Tags";
import TransactionDetail from "../components/TransactionDetail";
import { useAnalyst } from "../lib/actor";
import { formatDateTime } from "../lib/format";

const RESOLUTIONS: { value: CaseResolution; label: string; hint: string }[] = [
  { value: "fraud_confirmed", label: "Fraud confirmed", hint: "Marks the receiver as known fraud for future scoring." },
  { value: "false_positive", label: "False positive", hint: "The system was wrong; nothing feeds back into scoring." },
  { value: "customer_verified", label: "Customer verified", hint: "The payer confirmed the payment is genuine." },
];

const EVENT_LABEL: Record<string, string> = {
  case_opened: "Case opened",
  assigned: "Assigned",
  unassigned: "Unassigned",
  status_changed: "Status changed",
  note: "Note",
  closed: "Closed",
  fraud_confirmed: "Fraud confirmed",
};

export default function CaseDetail() {
  const id = Number(useParams().caseId);
  const [analyst] = useAnalyst();
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ["case", id], queryFn: () => api.caseDetail(id), refetchInterval: 10_000 });

  const [note, setNote] = useState("");
  const [resolution, setResolution] = useState<CaseResolution>("false_positive");
  const [closeNote, setCloseNote] = useState("");

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["case", id] });
    qc.invalidateQueries({ queryKey: ["cases"] });
    qc.invalidateQueries({ queryKey: ["case-summary"] });
    qc.invalidateQueries({ queryKey: ["transactions"] });
  };
  const update = useMutation({ mutationFn: (b: Parameters<typeof api.updateCase>[1]) => api.updateCase(id, b), onSuccess: refresh });
  const addNote = useMutation({ mutationFn: () => api.addNote(id, { actor: analyst, note: note.trim() }), onSuccess: () => { setNote(""); refresh(); } });
  const close = useMutation({ mutationFn: () => api.closeCase(id, { actor: analyst, resolution, note: closeNote.trim() || undefined }), onSuccess: () => { setCloseNote(""); refresh(); } });

  if (query.isPending) return <Loading rows={10} />;
  if (query.isError) return <ErrorState error={query.error} retry={() => query.refetch()} />;
  const c = query.data;
  const isClosed = c.status === "closed";
  const noActor = !analyst;
  const error = update.error ?? addNote.error ?? close.error;

  return (
    <>
      <div className="page-head">
        <div>
          <div className="muted" style={{ fontSize: 12.5 }}><Link to="/cases">← Cases</Link></div>
          <h1>Case #{c.id}</h1>
        </div>
        <span className="meta"><Severity value={c.severity} /> · <StatusPill status={c.status} /> · opened {formatDateTime(c.created_at)}</span>
      </div>

      {noActor && !isClosed && <div className="banner">Enter your name in the sidebar ("Acting as") to take actions. It's recorded on the case timeline.</div>}
      {error && <div className="banner" role="alert" style={{ borderColor: "var(--danger)" }}>{error.message}</div>}

      <div className="grid split">
        <div className="stack" style={{ gap: 16 }}>
          {!isClosed && (
            <div className="panel">
              <div className="panel-head">Work this case</div>
              <div className="panel-body stack">
                <div className="form-row">
                  <span className="muted">Assigned to</span>
                  <strong>{c.assigned_to ?? "nobody"}</strong>
                  <button className="btn sm" disabled={noActor || c.assigned_to === analyst || update.isPending} onClick={() => update.mutate({ actor: analyst, assigned_to: analyst })}>Assign to me</button>
                  {c.assigned_to && <button className="btn sm" disabled={noActor || update.isPending} onClick={() => update.mutate({ actor: analyst, unassign: true })}>Unassign</button>}
                </div>
                <div className="form-row">
                  <span className="muted">Status</span>
                  {(["open", "investigating", "escalated"] as CaseStatus[]).map((s) => (
                    <button key={s} className={`btn sm ${c.status === s ? "primary" : ""}`} disabled={noActor || c.status === s || update.isPending} onClick={() => update.mutate({ actor: analyst, status: s })} style={{ textTransform: "capitalize" }}>{s}</button>
                  ))}
                </div>
                <div>
                  <label htmlFor="note" className="muted">Add a note</label>
                  <textarea id="note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="What did you check? Who did you contact?" />
                  <button className="btn sm" style={{ marginTop: 6 }} disabled={noActor || !note.trim() || addNote.isPending} onClick={() => addNote.mutate()}>Add note</button>
                </div>
              </div>
            </div>
          )}

          <div className="panel">
            <div className="panel-head">Timeline</div>
            <div className="panel-body">
              {c.events.length === 0 ? <p className="muted" style={{ margin: 0 }}>No activity yet. Opened automatically by the scoring pipeline.</p> : (
                <ol className="timeline">
                  {c.events.map((e) => (
                    <li key={e.id}>
                      <div><strong>{EVENT_LABEL[e.event_type] ?? e.event_type}</strong> <span className="muted">by {e.actor}</span></div>
                      {e.description && <div>{e.description}</div>}
                      <div className="when">{formatDateTime(e.created_at)}</div>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          </div>

          {!isClosed && (
            <div className="panel">
              <div className="panel-head">Close case</div>
              <div className="panel-body stack">
                <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
                  <legend className="muted" style={{ padding: 0, marginBottom: 6 }}>Resolution</legend>
                  {RESOLUTIONS.map((r) => (
                    <label key={r.value} style={{ display: "block", marginBottom: 6 }}>
                      <input type="radio" name="resolution" checked={resolution === r.value} onChange={() => setResolution(r.value)} /> <strong>{r.label}</strong>
                      <span className="muted"> — {r.hint}</span>
                    </label>
                  ))}
                </fieldset>
                <textarea rows={2} aria-label="Closing note" value={closeNote} onChange={(e) => setCloseNote(e.target.value)} placeholder="Closing note (optional)" />
                <div><button className={`btn ${resolution === "fraud_confirmed" ? "danger" : "primary"}`} disabled={noActor || close.isPending} onClick={() => close.mutate()}>Close as {RESOLUTIONS.find((r) => r.value === resolution)!.label.toLowerCase()}</button></div>
              </div>
            </div>
          )}
        </div>

        <div className="panel">
          <div className="panel-body stack" style={{ gap: 20 }}>
            <TransactionDetail txn={c.transaction} />
          </div>
        </div>
      </div>
    </>
  );
}
