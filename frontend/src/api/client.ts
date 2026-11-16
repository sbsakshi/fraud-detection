import type {
  AccountBrief,
  AccountProfile,
  CaseDetail,
  CaseEvent,
  CaseListItem,
  CaseRef,
  CaseResolution,
  CaseStatus,
  Graph,
  Ladder,
  Page,
  CaseSummary,
  ReasonCodeCount,
  ScoredTransaction,
  TimeseriesBucket,
  TransactionCreate,
  TransactionStats,
} from "./types";

export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

type Params = Record<string, string | number | boolean | string[] | undefined | null>;

function qs(params?: Params): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params ?? {})) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => sp.append(k, x));
    else sp.append(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

async function request(path: string, init?: RequestInit): Promise<Response> {
  let resp: Response;
  try {
    resp = await fetch(`${API_BASE_URL}${path}`, init);
  } catch {
    throw new ApiError(0, `Can't reach the Finsight API at ${API_BASE_URL}. Is the backend running?`);
  }
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`;
    try {
      const body = await resp.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* non-JSON error body: keep the status line */
    }
    throw new ApiError(resp.status, detail);
  }
  return resp;
}

async function get<T>(path: string, params?: Params): Promise<T> {
  return (await request(`${path}${qs(params)}`)).json() as Promise<T>;
}

async function getPage<T>(path: string, params?: Params): Promise<Page<T>> {
  const resp = await request(`${path}${qs(params)}`);
  return { items: (await resp.json()) as T[], total: Number(resp.headers.get("X-Total-Count") ?? 0) };
}

async function send<T>(method: "POST" | "PATCH", path: string, body: unknown): Promise<T> {
  const resp = await request(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return resp.json() as Promise<T>;
}

export interface TransactionFilters {
  level?: string[];
  min_score?: number;
  source?: string;
  since?: string;
  q?: string;
  account?: string;
  has_case?: boolean;
  limit?: number;
  offset?: number;
}

export interface CaseFilters {
  status?: string[];
  severity?: string[];
  assigned_to?: string;
  unassigned?: boolean;
  limit?: number;
  offset?: number;
}

export const api = {
  transactions: (f: TransactionFilters) => getPage<ScoredTransaction>("/transactions", { ...f }),
  transaction: (id: number) => get<ScoredTransaction>(`/transactions/${id}`),
  scoreTransaction: (body: TransactionCreate) => send<ScoredTransaction>("POST", "/transactions", body),
  transactionStats: () => get<TransactionStats>("/transactions/stats"),

  cases: (f: CaseFilters) => getPage<CaseListItem>("/cases", { ...f }),
  caseDetail: (id: number) => get<CaseDetail>(`/cases/${id}`),
  updateCase: (id: number, body: { actor: string; status?: CaseStatus; assigned_to?: string; unassign?: boolean; note?: string }) =>
    send<CaseRef>("PATCH", `/cases/${id}`, body),
  addNote: (id: number, body: { actor: string; note: string }) => send<CaseEvent>("POST", `/cases/${id}/notes`, body),
  closeCase: (id: number, body: { actor: string; resolution: CaseResolution; note?: string }) =>
    send<CaseRef>("POST", `/cases/${id}/close`, body),

  searchAccounts: (q: string, limit = 20) => get<AccountBrief[]>("/accounts", { q, limit }),
  account: (upi: string) => get<AccountProfile>(`/accounts/${encodeURIComponent(upi)}`),
  graph: (center: string, depth: number) => get<Graph>("/graph", { center, depth, max_nodes: 120 }),

  timeseries: (hours: number) => get<TimeseriesBucket[]>("/stats/timeseries", { hours }),
  reasonCodes: (hours: number) => get<ReasonCodeCount[]>("/stats/reason-codes", { hours, limit: 8 }),
  caseSummary: () => get<CaseSummary>("/stats/cases"),
  ladder: () => get<Ladder>("/stats/ladder"),
};
