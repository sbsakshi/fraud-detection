# Finsight developer guide

Everything someone who owns this codebase needs to know: what each part does, why
it was built that way, how well it works, and where it is weak. It was written
from the code, the tests and measured runs, not from memory. When this guide and
the code disagree, the code wins; please fix the guide.

Numbers quoted here come from the committed model (`ml/models/`, trained
2026-10-16) and the committed ladder (`backend/app/scoring/intervention_config.json`).
If you retrain or retune, update the sections marked **(regenerate)**.

## Contents

1. [What this is](#1-what-this-is)
2. [Repository map](#2-repository-map)
3. [Architecture](#3-architecture)
4. [Running it](#4-running-it)
5. [Data model](#5-data-model)
6. [API reference](#6-api-reference)
7. [The scoring pipeline, step by step](#7-the-scoring-pipeline-step-by-step)
8. [Rules engine](#8-rules-engine)
9. [Graph engine](#9-graph-engine)
10. [Machine learning](#10-machine-learning)
11. [Fusion, confidence and the intervention ladder](#11-fusion-confidence-and-the-intervention-ladder)
12. [Cases and the investigator workflow](#12-cases-and-the-investigator-workflow)
13. [Frontend](#13-frontend)
14. [Infrastructure](#14-infrastructure)
15. [Testing](#15-testing)
16. [Accuracy: what the numbers say](#16-accuracy-what-the-numbers-say)
17. [Design decisions and the mistakes behind them](#17-design-decisions-and-the-mistakes-behind-them)
18. [Known gaps and sharp edges](#18-known-gaps-and-sharp-edges)
19. [Recipes](#19-recipes)
20. [Troubleshooting](#20-troubleshooting)
21. [Glossary](#21-glossary)

---

## 1. What this is

Finsight is a **synthetic UPI fraud-intelligence system**. For every payment it
runs three independent detectors (rules, a machine-learning model, and graph
analysis), fuses their scores into one number plus a confidence value, maps that to
one of **six graduated interventions** (inform, warn, verify, hold, restrict,
escalate), and opens an investigator **case** for the two most severe levels.
Investigators work cases through an API and a dashboard; their confirmations feed
back into scoring.

**Everything is synthetic.** The accounts, transactions and fraud patterns are
generated (`ml/synthetic/`). The numbers in this guide measure whether the pipeline
learns the signal that was planted and is evaluated honestly. They are **not** a
real-world accuracy claim.

**It recommends; it does not enforce.** `intervention_level` is returned to the
caller and stored. Nothing in the backend blocks, delays or reverses a payment: the
stored `transactions.status` stays `completed` whatever the level. The demo page
and any real integration decide what "hold" means.

### Scale of the thing

| | |
|---|---|
| Synthetic data | 6,892 accounts, 75,001 transactions (90 days: 30 burn-in + 60), 5,230 labelled fraud (6.97%) |
| ML | calibrated XGBoost on 44 features + an Isolation Forest, SHAP explanations |
| Backend | FastAPI, SQLAlchemy 2, ~8k lines of Python including tests and scripts |
| Tests | 128 backend (127 run + 1 Postgres-only), 11 ML |
| Local scoring latency (SQLite, laptop) | p50 ~11 ms typical account, ~59 ms for an account with 323 prior payments, first request ~240 ms (SHAP initialises lazily) |
| Startup with ~30k stored transactions | about 1-2 s (model load + graph rebuild) |

---

## 2. Repository map

```
fraud-detection/
├── README.md                      short overview + quick start
├── docs/DEVELOPER_GUIDE.md        this file
├── docker-compose.yml             postgres + backend + frontend (nginx)
├── docker-compose.dev.yml         override: hot-reload Vite frontend
├── .env.example                   POSTGRES_*, CORS_ORIGINS, VITE_API_BASE_URL
├── .github/workflows/ci.yml       5 jobs: ml, backend, backend-postgres, frontend, images
├── infra/README.md                compose, config surface, CI, what is not handled
│
├── ml/                            offline: data, features, training
│   ├── synthetic/
│   │   ├── config.py              EVERY generator constant (seed, counts, rates, dates)
│   │   ├── base_traffic.py        accounts + normal transactions
│   │   ├── legit_patterns.py      unlabelled look-alikes (large_new_payee, group_collection)
│   │   ├── helpers.py             ids, banks, IFSC, device ids
│   │   ├── generate_dataset.py    orchestrator -> ml/data/{accounts,transactions}.csv
│   │   └── scenarios/             one module per fraud pattern + innocent_bystander + _util
│   ├── features/
│   │   ├── engineering.py         THE feature code (44 features). Single source of truth.
│   │   └── build_features.py      -> ml/data/features.csv (gitignored)
│   ├── train.py                   split, grid search, calibrate, evaluate, export
│   ├── models/                    COMMITTED artifacts (see section 10.6)
│   ├── data/                      accounts.csv, transactions.csv (committed); features.csv,
│   │                              rule_graph_scores.csv (gitignored, regenerable)
│   └── tests/test_engineering.py  feature correctness + no-peeking tests
│
├── backend/
│   ├── app/
│   │   ├── main.py                app, lifespan (load models, rebuild graph), CORS, health
│   │   ├── config.py              Settings from env (DATABASE_URL, CORS_ORIGINS, REBUILD_GRAPH_ON_STARTUP)
│   │   ├── db.py                  engine/session; SQLite vs Postgres connect args
│   │   ├── accounts.py            lookup/create helpers (404 on unknown UPI)
│   │   ├── schemas.py             all Pydantic request/response models
│   │   ├── models/                SQLAlchemy tables + enums
│   │   ├── routers/               accounts, transactions, cases, graph, stats
│   │   ├── scoring/               pipeline, fusion, intervention, config, tuning, context_builders,
│   │   │                          intervention_config.json  (ladder + fusion weights)
│   │   ├── rules/                 engine.py (4 rules), config.py, schemas.py
│   │   ├── graph/                 builder, engine (4 graph rules), analysis, live_graph, config, schemas
│   │   └── ml/                    model_loader, live_features, feature_engineering (VENDORED copy)
│   ├── migrations/                Alembic: c190bb280894 (initial), a7d3e1f4b2c9 (score versions)
│   ├── scripts/                   dev.sh, init_local_db.py, replay_*.py, evaluate_*.py, tune_fusion.py
│   ├── tests/                     15 test files (section 15)
│   ├── Dockerfile, alembic.ini, pytest.ini, requirements*.txt
│   └── finsight.db                local SQLite dev database (gitignored)
│
└── frontend/                      Vite + React 18 + TypeScript
    ├── src/pages/                 Analytics, Transactions, Cases, CaseDetail, Account, Network, Demo
    ├── src/components/            Layout, GraphScene (canvas), Drawer, Pager, States, Tags, TransactionDetail
    ├── src/api/                   client.ts (fetch wrapper + endpoints), types.ts (mirrors backend schemas)
    ├── src/lib/                   format.ts (templates, amounts), actor.ts, useParams.ts
    ├── src/styles.css             the whole design system (Apple-style, light/dark)
    ├── Dockerfile                 stages: deps, dev, build, prod (nginx)
    └── nginx.conf                 SPA fallback, immutable /assets caching
```

Two Python virtualenvs exist side by side: `backend/.venv` and `ml/.venv` (Python 3.12).
They pin the same versions of numpy, pandas, scikit-learn, xgboost and joblib, on
purpose (section 10.7).

---

## 3. Architecture

### 3.1 Request path

```
              POST /transactions
                     │
        ┌────────────▼─────────────┐
        │ routers/transactions.py  │  resolve sender/receiver (404 if unknown)
        └────────────┬─────────────┘
                     ▼
        ┌──────────────────────────┐   all three read state STRICTLY BEFORE this payment
        │ scoring/pipeline.py      │
        │  known_fraud_upis  ◄──── cases + case_events (investigator-confirmed only)
        │  1 RULES   ◄──────────── DB history of sender and receiver
        │  2 ML      ◄──────────── DB history -> 44 live features -> XGBoost + calibrator
        │  3 GRAPH   ◄──────────── in-memory NetworkX graph (pre-transaction state)
        │  4 FUSE    rule/ml/graph -> fused_score + confidence
        │  5 DECIDE  ladder -> intervention_level
        │  6 PERSIST transaction, update graph, mirror edges, risk_score, reason_codes
        │  7 CASE    only for restrict / escalate
        └────────────┬─────────────┘   one commit at the end
                     ▼
              TransactionScoreOut (scores, reason codes, case, model_version, ladder_version)
```

### 3.2 State that lives where

| State | Where | Survives restart? |
|---|---|---|
| Accounts, transactions, scores, reason codes, cases, events, graph edges | SQL database | yes |
| The live transaction graph (NetworkX `MultiDiGraph`) | process memory (`graph/live_graph.py`) | rebuilt from `transactions` at startup (`REBUILD_GRAPH_ON_STARTUP`, default on) |
| ML models, SHAP explainer | process memory, loaded once | reloaded from `ml/models/` |
| Ladder + fusion weights | `scoring/intervention_config.json`, cached in a module global | re-read on restart |
| Frontend server state | react-query cache in the browser, polling | n/a |
| Analyst name | browser `localStorage` (`finsight.analyst`) | per browser |

Consequence: **the backend is single-instance by design.** Two replicas would each
hold a different in-memory graph and score differently (section 18).

### 3.3 Startup (`main.py` lifespan)

1. `get_models()` loads the six ML artifacts. A missing or mismatched artifact does
   not crash the app: `/health` reports `"not_trained"`, `/health/ready` returns 503
   and `POST /transactions` returns 503 until models exist.
2. If `REBUILD_GRAPH_ON_STARTUP`, replay every row of `transactions` in time order
   through `TransactionGraph.add_transaction`. Failures (DB down, not migrated) are
   logged, not fatal.

Tests set `REBUILD_GRAPH_ON_STARTUP=false` (in `conftest.py`) so they never read the
developer's database.

---

## 4. Running it

### 4.1 Native, zero-install (SQLite) - the usual dev loop

```bash
cd backend
./scripts/dev.sh              # API on http://127.0.0.1:8000 (creates tables in finsight.db)
./scripts/dev.sh --reset      # wipe finsight.db first

cd ../frontend && npm install && npm run dev      # http://localhost:5173
```

`dev.sh` sets `DYLD_FALLBACK_LIBRARY_PATH` to scikit-learn's bundled `.dylibs`,
because XGBoost on macOS needs `libomp` and this avoids needing Homebrew. **Any
command that imports xgboost on macOS needs that variable** (pytest, training, the
tuning script) unless you ran `brew install libomp`:

```bash
export DYLD_FALLBACK_LIBRARY_PATH="$(python -c 'import sklearn,os;print(os.path.join(os.path.dirname(sklearn.__file__),".dylibs"))')"
```

macOS strips `DYLD_*` variables when they pass through system binaries such as
`nohup` and `env`, so launch servers directly (`exec` or a plain background `&`).

### 4.2 Fill the dashboard with scored traffic

```bash
cd backend
python scripts/replay_dataset.py --limit 5000                       # backfill history, as fast as possible
python scripts/replay_dataset.py --offset 5000 --limit 500 --rate 5 --shift-to-now   # live trickle, 5 txn/s
python scripts/replay_synthetic.py --limit 2000                     # simpler replayer (--skip to resume)
```

Both replayers create accounts via `POST /accounts` (a 409 means it exists and is
skipped, so re-running is safe), then post transactions in timestamp order through
the **real** scoring path. `--shift-to-now` moves every timestamp by one constant so
the newest replayed transaction is "now"; relative gaps (what velocity rules and the
graph care about) are unchanged but the dashboard's "last 24h" views fill.

### 4.3 Docker

```bash
cp .env.example .env
docker compose up --build                                                    # nginx-served dashboard
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build    # hot-reload frontend
```

Ports: Postgres 5432, API 8000, dashboard 5173 (nginx listens on 80 inside). Details
and caveats in section 14. **The Docker path has not been executed on the machine this
was developed on** (no Docker installed); CI's `images` job is its first real run.

### 4.4 Tests

```bash
cd backend && python -m pytest -q tests                    # 127 pass, 1 skipped (Postgres)
cd ml && source .venv/bin/activate && cd .. && python -m pytest -q ml/tests    # 11 pass
POSTGRES_TEST_URL=postgresql://finsight:finsight@localhost:5432/finsight_test \
  python -m pytest -q -m postgres tests/test_postgres_integration.py            # needs a *_test DB
cd frontend && npm run build                               # tsc -b + vite build
```

`test_ml_model_loader` reads a real row from `ml/data/features.csv`; if it is missing
run `python -m ml.features.build_features` first (CI does).

### 4.5 Data, training and tuning (the ML loop)

```bash
python -m ml.synthetic.generate_dataset     # -> ml/data/{accounts,transactions}.csv   (seeded, reproducible)
python -m ml.features.build_features        # -> ml/data/features.csv                  (~3 s)
python -m ml.train                          # -> ml/models/*                           (~30 s)
cd backend && python scripts/tune_fusion.py [--min-weight 0.2] [--write-config] [--output report.json]
```

---

## 5. Data model

Seven tables. SQLAlchemy models are in `backend/app/models/`; the schema is created
by Alembic on Postgres and by `Base.metadata.create_all` on SQLite.

```
accounts ◄───────────────┐
  id, upi_id (unique)    │
                         │ sender_account_id / receiver_account_id
transactions ────────────┘
  id ◄─── risk_scores (1:1, unique transaction_id) ◄─── reason_codes (N)
  id ◄─── cases (N, but see 18.4)                  ◄─── case_events (N)
  id ◄─── graph_edges.transaction_id (only 'transaction' edges)
```

Notable columns:

| Table | Column | Notes |
|---|---|---|
| `accounts` | `upi_id` | natural key, unique index; all APIs address accounts by it |
| | `device_id` | the account's registered device (nullable) |
| | `true_label` | **synthetic ground truth** (e.g. `mule_network`); null = normal. Never used for scoring; shown only in the graph payload |
| | `account_type` | `individual` or `merchant` |
| `transactions` | `amount` | `Numeric(14,2)`; currency defaults INR |
| | `device_id` | device used **for this payment** (can differ from the account's) |
| | `transaction_type` | `P2P` or `P2M`; feature `is_p2p` |
| | `status` | pending/completed/failed. **Stored, not used in scoring** (failed payments are scored and enter the graph like any other) |
| | `true_label`, `scenario` | ground truth / generator tag; accepted from the client on `POST /transactions` (section 18) |
| `risk_scores` | `rule_score`, `ml_score`, `graph_score` | each 0-1 |
| | `fused_score`, `confidence` | 0-1 |
| | `intervention_level` | enum |
| | `model_version` | ML artifacts' `trained_at` timestamp; null for rows scored before migration `a7d3e1f4b2c9` |
| | `ladder_version` | first 12 hex chars of SHA-256 of `intervention_config.json` |
| `reason_codes` | `source` | rule / ml / graph |
| | `code`, `template`, `details`, `contribution` | template has `{placeholders}`; `details` (JSON) fills them; `contribution` is this reason's share of its source's score (null for `ml_anomaly`) |
| `cases` | `status`, `severity`, `assigned_to`, `summary` | `summary` is never written by any code today |
| `case_events` | `event_type`, `description`, `actor` | the audit trail; `fraud_confirmed` is the event scoring reads |
| `graph_edges` | `edge_type` | `transaction`, `shared_device`, `repeated_counterparty` |
| | `weight` | transaction edges 1.0; repeated_counterparty = pair count |

Indexes: `accounts(upi_id unique, device_id, true_label)`, `transactions(created_at,
device_id, sender_account_id, receiver_account_id, scenario, true_label)`,
`risk_scores(transaction_id unique)`, `reason_codes(risk_score_id, code)`,
`cases(transaction_id)`, `case_events(case_id)`, `graph_edges(source, target,
edge_type, transaction_id)`.

Enums: `AccountType{individual, merchant}`, `TransactionStatus{pending, completed,
failed}`, `InterventionLevel{inform, warn, verify, hold, restrict, escalate}`,
`ReasonCodeSource{rule, ml, graph}`, `GraphEdgeType`, `CaseStatus{open, investigating,
escalated, closed}`, `CaseSeverity{low, medium, high, critical}`. The database stores
the enum **names** in upper case; the API speaks lower-case values. Only `high` and
`critical` severities are ever created by the pipeline.

Timestamps: all `DateTime(timezone=True)` and normalised to aware UTC at every
boundary (`_as_utc` helpers), because SQLite returns naive datetimes for the same
column and comparing naive with aware raises.

Migrations: `c190bb280894` (initial) and `a7d3e1f4b2c9` (adds the two version
columns). `alembic check` runs in CI and fails if models and migrations diverge.
An existing SQLite file does **not** pick up new columns: reset it or `ALTER TABLE`.

---

## 6. API reference

Base URL `http://localhost:8000`. Interactive docs at `/docs`. CORS allows the origins
in `CORS_ORIGINS` and exposes `X-Total-Count`. No authentication.

### Health

| Endpoint | Behaviour |
|---|---|
| `GET /health` | DB check (503 if down) plus `ml_models: loaded \| not_trained`, always 200 otherwise. Kept for older callers. |
| `GET /health/live` | `{"status":"alive"}`. Never touches the DB or models. |
| `GET /health/ready` | 200 only if the DB answers **and** the ML artifacts are loaded, else 503. Used by the compose healthcheck. |

### Accounts

| Endpoint | Behaviour |
|---|---|
| `POST /accounts` | Create. 409 if the UPI id exists. Send `created_at` when replaying history: account-age features depend on it. |
| `GET /accounts?q=&limit=` | Search active accounts by owner name or UPI id (case-insensitive substring), `limit` 1-100 (default 20). Returns brief rows. Used by the demo's payee picker. |
| `GET /accounts/{upi}` | Profile: totals sent/received, distinct counterparties, max fused score, flagged count, open cases, accounts sharing its device (up to 50), `known_fraud`. |

### Transactions

| Endpoint | Behaviour |
|---|---|
| `POST /transactions` | Score and persist. Body: `sender_upi_id`, `receiver_upi_id`, `amount` (> 0), `device_id`, optional `currency`, `transaction_type` (default `P2P`), `status`, `created_at`, `true_label`, `scenario`. Both accounts must exist (404). Returns 201 with scores, reason codes (sorted by contribution), case, versions. 503 if models are not loaded. **Not idempotent.** |
| `GET /transactions` | Newest first. Filters: `level` (repeatable), `min_score`, `max_score`, `source` (a reason code from rule/ml/graph), `since`, `until`, `q` (substring of sender or receiver UPI), `account` (exact, either side), `has_case`. `limit` 1-200 (default 50), `offset`. `X-Total-Count` = unpaged matches. |
| `GET /transactions/stats` | `transactions_scored`, `flagged_rate` (share not at `inform`), `active_cases`, `avg_fused_score`. |
| `GET /transactions/{id}` | One scored transaction. 404 if missing. |

### Graph

`GET /graph` returns `{nodes, edges}`. With `center=<upi>` it returns that account's
neighbourhood (`depth` 1-3, `max_nodes` 2-500 default 150, nearest first; 404 if the
account isn't in the graph yet). Without `center` it returns the **whole graph**, which
grows with all traffic, so the UI always uses `center`. Nodes carry `max_score`,
`known_fraud`, `true_label`, `account_type` and a Louvain `community` id used only
for colouring. Parallel transaction edges are collapsed to one edge weighted by count.

### Cases

| Endpoint | Behaviour |
|---|---|
| `GET /cases` | Work queue: open work before closed, then severity (critical first), then oldest first. Filters `status`, `severity` (repeatable), `assigned_to`, `unassigned`; paging as above. Each row has `top_reason` (code of its highest-contribution reason). |
| `GET /cases/{id}` | Case, its transaction with full scoring, and the event timeline oldest first. |
| `PATCH /cases/{id}` | Assign / unassign / change status. Body needs `actor`. 409 if closed. 422 if you try `status: closed` (use `/close`) or send both `assigned_to` and `unassign`. |
| `POST /cases/{id}/notes` | Add a note. Allowed on closed cases. |
| `POST /cases/{id}/close` | Needs `resolution`: `fraud_confirmed`, `false_positive` or `customer_verified`. 409 if already closed. `fraud_confirmed` also records the confirmation event. |
| `POST /cases/{id}/confirm-fraud` | Records `fraud_confirmed` (idempotent). Works on closed cases too. Does not change status. |

### Stats (power the Analytics page)

| Endpoint | Behaviour |
|---|---|
| `GET /stats/timeseries?hours=24` | One bucket per hour, oldest first, **zero-filled**, counts per intervention level. `hours` 1-720. |
| `GET /stats/reason-codes?hours=24&limit=10` | Most frequent reason codes in the window. |
| `GET /stats/cases` | Active cases by severity, unassigned count, closed count. |
| `GET /stats/ladder` | The live ladder and fusion weights, so the UI explains decisions with the real numbers. |

---

## 7. The scoring pipeline, step by step

`backend/app/scoring/pipeline.py::score_and_persist_transaction`. The ordering is
the contract; do not reorder without understanding it.

1. **Normalise the timestamp** to aware UTC (default: now).
2. **Load the known-fraud set**: receivers of any case that has a `fraud_confirmed`
   event (`context_builders.get_known_fraud_upis`, one SQL query per request).
3. **Rules**: build a `RuleContext` from sender history and receiver's recent senders
   (both strictly `created_at <` this payment), run `evaluate_rules`.
4. **ML**: `compute_live_features` pulls every earlier transaction involving sender or
   receiver, rebuilds the same feature frame training used, takes the candidate row;
   `score_transaction` returns raw and calibrated probability plus anomaly percentile;
   `explain_ml_score` adds the top-3 SHAP reasons; `anomaly_reason` adds
   `ml_anomaly` above the 99th percentile.
5. **Graph**: `evaluate_graph` against the graph **as it was before** this payment.
6. **Fuse and decide**: `fuse_scores` then `decide_intervention`.
7. **Persist the transaction** and `flush()` to get its id.
8. **Update the live graph** with `add_transaction`, then mirror the returned edge
   writes into `graph_edges`.
9. **Persist the risk score** (with `model_version`, `ladder_version`) and all reason
   codes: rule reasons, then graph reasons, then ML reasons.
10. **Open a case** if the level is `restrict` (OPEN / HIGH) or `escalate`
    (ESCALATED / CRITICAL), with a `case_opened` event by actor `system`.
11. **One `commit()`** for everything.

Why this order matters: steps 3-5 must see only the past, and step 8 must come after
step 5, otherwise a payment would count toward its own fan-in or "repeated
counterparty" evidence. The graph is mutated in step 8 even though the DB commit is
in step 11; a failure between them would leave the in-memory graph ahead of the
database (section 18).

### What a response looks like (real example, benign payment)

```json
{ "rule_score": 0.15, "ml_score": 0.0097, "graph_score": 0.0,
  "fused_score": 0.0358, "confidence": 0.7983, "intervention_level": "inform",
  "model_version": "2026-10-16T06:27:18+00:00", "ladder_version": "adaa31c5efd6" }
reason codes: first_time_beneficiary, ml_feature:receiver_unique_senders_hist,
              ml_feature:sender_unique_receivers_hist, ml_feature:is_p2p
```

---

## 8. Rules engine

`backend/app/rules/`. Deterministic, DB-agnostic: the rules take plain dataclasses
(`RuleTransaction`, `RuleContext`), not ORM objects, so the identical code runs against
Postgres in production and against a CSV in the evaluation scripts. Each rule returns
a `FiredRule` (a reason code with template, details, contribution) or `None`.
`rule_score = min(1, sum(contributions))`. All thresholds are in `RuleConfig`.

| Rule | Fires when | Contribution |
|---|---|---|
| `known_fraud_beneficiary` | receiver is in the confirmed-fraud set | **0.9** |
| `amount_above_historical_average` | sender has >= 3 prior payments and `amount >= 3 x` their mean | `min(1, 0.5 x ratio/3)` (3x -> 0.5, 6x -> 1.0) |
| `first_time_beneficiary` | sender never paid this receiver | **0.15** |
| `fan_in_velocity` | >= 5 distinct senders (including this one) paid the receiver within 10 minutes | `min(1, 0.4 x count/5)` |

Behaviour worth knowing:

- `first_time_beneficiary` fires on about **97% of all payments** in the dev data
  (29,067 of ~30,000), including legitimate ones. By itself it contributes
  `0.2 x 0.15 = 0.03` to the fused score, but it makes **two engines "active"** on
  nearly every payment, which raises confidence (section 11.3).
- The average-amount rule stays silent for senders with fewer than 3 prior payments.
- The rule engine can only see one payment's neighbourhood; patterns spread across many
  payments are what ML and graph are for.

Rules-only behaviour on the synthetic data (`scripts/evaluate_rules_on_synthetic.py`,
score >= 0.5): takeover 58%, scam recipient 45%, layering 25%, mule 24%, gambling
2.7%, but also **55.8% of legitimate `large_new_payee` payments**.

---

## 9. Graph engine

`backend/app/graph/`. A NetworkX `MultiDiGraph` of accounts as nodes and payments as
edges, kept in memory and mirrored to `graph_edges`.

### 9.1 Structure (`builder.TransactionGraph`)

`add_transaction` creates, per payment:

- a **`transaction`** edge sender -> receiver (key `transaction:<txn_ref>`) carrying
  `amount`, `created_at`;
- **`shared_device`** edges, in both directions, between the sender and every other
  account previously seen paying from the same device (updated in place per device);
- one **`repeated_counterparty`** edge per sender/receiver pair once the pair has
  made >= 5 payments, its `weight` updated in place (not one row per repeat).

Graph metadata keeps `device_users: device_id -> set of senders`, so "who else used
this device" is O(that device's users). `shared_device` rows are directed in the
table but symmetric in meaning: query both `source_account_id` and `target_account_id`.

### 9.2 Graph reason codes (`engine.py`, thresholds in `GraphConfig`)

| Code | Fires when | Contribution |
|---|---|---|
| `mule_collector_pattern` | either the **sender** has recently received from >= 3 distinct senders and that burst is its *entire* inbound history (it is now sweeping onward), **or** the **receiver** has >= 3 distinct recent senders (this one included), >= 1 recent outbound destination, and the burst is its entire inbound history. Window 3 h. | 0.6 |
| `shared_device_ring` | the sender's device is linked to >= 3 *other* accounts | 0.5 |
| `repeated_counterparty` | this pair has >= 5 payments in 24 h (this one included) | 0.3 |
| `fraud_cluster_exposure` | receiver is 1-2 hops (either direction, transaction edges) from a **confirmed-fraud** account but is not one itself | `min(1, 0.7 / nearest_hop)`: 0.7 at one hop, 0.35 at two |

`graph_score = min(1, sum)`. `fraud_cluster_exposure` can never fire until an
investigator has confirmed some fraud; with an empty watchlist the BFS is skipped.

### 9.3 Analysis functions (`analysis.py`)

`recent_counterparties`, `fan_in_out`, `shared_device_neighbors`, `device_user_count`,
`transaction_edge_count`, `detect_collector_candidates` (batch, whole graph),
`detect_communities` (Louvain, seed 42), `fraud_cluster_exposure`, `trace_money_trail`
(forward-in-time simple paths up to 3 hops).

### 9.4 The false-positive trap (read this before touching fan-in logic)

Naive fan-in/fan-out counting looked fine in unit tests and was useless on real-sized
data:

1. **Unwindowed counts flag every long-lived account eventually**: 76% of ordinary
   traffic was flagged.
2. **A 24 h window still flagged 70%**, because high-throughput hub accounts
   (Pareto-weighted merchants) cross any fan-in threshold in *some* window.
3. The fix was `_is_fresh_burst`: compare the windowed count to the account's
   *all-time* count so far. A freshly created mule collector's burst **is** its whole
   history; an established hub's latest slice is not. Plus a 3 h window and
   `collector_min_fan_out = 1` (a real collector here sweeps to exactly one cashout).
   False positives fell from 76% to under 0.1%.

The cost: recruited collectors (established accounts) no longer satisfy "burst is the
whole history", so graph recall on mule transactions is only **10.4%**. That is why
detection is fused rather than graph-only. The batch Louvain pass finds 224 of 228
true mule accounts (98.2%) in 24 communities, but that is a whole-graph analysis, not
a per-payment check.

---

## 10. Machine learning

### 10.1 Synthetic data (`ml/synthetic/`)

Seeded (`SEED=42`) so a rerun reproduces the same CSVs. Every constant is in
`config.py`.

**Timeline.** `END_DATE = 2026-09-14`; the labelled window is the 60 days before it;
a **30-day burn-in** of normal traffic precedes that. Training drops the burn-in
(it exists so every account has realistic history when fraud starts).

**Base traffic.** 6,000 accounts (15% merchants, 10% of individuals have a second
device, 2% inactive, 6% opened inside the window, the rest 0-3 years old before the
burn-in). Activity weights are heavy-tailed (`pareto(1.5) + 1`, x3 for merchants),
receivers are further weighted x4 for merchants, so a few hub accounts carry most
traffic. 67,500 payments with log-normal amounts (P2P mean 5.9, P2M mean 6.5 in log
space, clipped 1-200,000), an hour-of-day curve peaking around 19:00, ~5% off-device
payments, and a 97/2/1% completed/pending/failed split. A guard rewrites any timestamp
earlier than either account's creation.

**Fraud scenarios** (generated in this order, each as `inject(...)`):

| Scenario | Count | Mechanics |
|---|---|---|
| `scam_recipient` | 40 rings | Recipient (30% aged/bought, else fresh) gets 10-30 one-off victim payments (500-50,000) spread over up to **72 h**, then sweeps 1-3 times to a fresh cashout 10 min-2 h later |
| `mule_network` | 40 rings | One herder device per ring. 3-5 collectors (50% recruited established accounts, the rest fresh on the herder's device), 10-25 senders pay collectors within **2 h**, collectors sweep to 1-2 fresh cashouts; ~2.5 h end to end |
| `layering_chain` | 150 chains | A lump sum (5k-100k) hops through 4-7 accounts (30% aged) every 1-15 minutes, shedding a 2-8% "fee" per hop |
| `account_takeover` | 180 | An account >= 90 days old, **new device**, 1-3 drains totalling 20k-150k to a never-paid beneficiary (50% aged), 50% at night (small hours) |
| `gambling_network` | 20 operators | Short-lived merchant "Gambling & Betting" accounts, active 7-20 days, 10-25 bettors each making 3-10 bets (50-15,000), 70% late night; labelled P2M |

**Unlabelled look-alikes** (legitimate; carry a `scenario` tag but no `true_label`):

| Look-alike | Count | Why it exists |
|---|---|---|
| `large_new_payee` | 450 | One-off 15k-200k payment to a never-paid payee, 25% from a new device (rent deposit, used car). Shares amount-jump + new-beneficiary (+ new device) with takeover |
| `group_collection` | 90 events / 1,321 payments | One person collects from 8-20 friends in 3 h, often pays a merchant onward. Shares fan-in burst + sweep with mule/scam |
| `innocent_bystander` | 500 | A normal account has one normal payment with a fraud-labelled account. Checks that network exposure alone doesn't flag people. Runs last, so a fraud pool exists |

**Label totals** (transactions): normal 67,500; gambling 2,294; scam 874; mule 855;
layering 841; takeover 366; group_collection 1,321; large_new_payee 450; bystander 500.

**Shortcuts that were removed** (each had inflated the model to 0.999+ AUC):

| Fix | Shortcut it removed |
|---|---|
| 30-day burn-in, dropped from training | "no history" no longer means "new account" |
| 6% of normal accounts opened in-window | fraud accounts were the *only* new accounts |
| 30-50% of fraud roles are aged/recruited | brand-new receiver was a near-perfect label |
| `_check_no_transaction_before_account` | ~1,800 rows had negative account age |
| Takeovers spread over the whole window | they were pinned to the last 10 days, so all landed in test |
| 20 short-lived gambling operators | with 5 permanent ones the model memorised them |
| Look-alike traffic | evaluation now measures false positives on hard cases |

### 10.2 Features (`ml/features/engineering.py`, 44 of them)

One chronological pass. Per-account running state (counts, sums, sums of squares,
sets, and 24 h deques) is updated **after** a row's features are computed, so a
payment never sees itself. Tiers exist so the ablation can show what each adds.

**Base (5):** `amount`, `log_amount`, `hour_of_day`, `day_of_week`, `is_p2p`.

**Behavioural (32):**

| Feature | Meaning |
|---|---|
| `sender_account_age_days`, `receiver_account_age_days` | days since account creation (NaN if creation unknown) |
| `sender_txn_count_hist` | prior payments sent |
| `sender_amount_mean_hist`, `sender_amount_std_hist` | mean / std of prior sent amounts |
| `amount_zscore_sender` | z-score vs own history (NaN under 3 prior payments or zero std) |
| `amount_to_sender_avg_ratio` | amount / own mean (NaN under 3 priors) |
| `sender_txn_count_1h`, `sender_txn_count_24h` | sender velocity |
| `is_first_time_beneficiary` | sender never paid this receiver |
| `sender_unique_receivers_hist`, `receiver_unique_senders_hist` | all-time distinct counterparties |
| `receiver_unique_senders_1h/_24h` | distinct payers in the window, **including this sender** |
| `receiver_txn_count_1h/_24h` | prior payments received in the window |
| `sender/receiver_inflow_total_hist`, `..._outflow_total_hist` | lifetime money in / out |
| `sender/receiver_inflow_outflow_ratio` | in / (out + 1); the +1 avoids divide-by-zero |
| `minutes_since_sender_last_sent`, `..._last_received` | recency / holding time (NaN if never) |
| `sender_distinct_devices_hist`, `is_new_device_for_sender` | device behaviour |
| `device_shared_account_count` | distinct senders previously seen on this payment's device |
| `receiver_device_shared_account_count` | max of that over devices the receiver has paid from |
| `sender/receiver_minutes_since_first_seen` | time since first appearing in the payment graph (NaN if first) |
| `sender_is_merchant`, `receiver_is_merchant` | exist because merchants legitimately have high fan-in; without them a model confuses a popular merchant with a mule collector |

**Graph (7), 3 h window:**

| Feature | Meaning |
|---|---|
| `sender_fan_in_3h` | distinct accounts that paid the sender in the last 3 h |
| `sender_fan_in_is_fresh_burst` | 1 if that fan-in is > 0 and equals the sender's all-time distinct payers |
| `receiver_fan_in_3h` | distinct payers to the receiver in 3 h, including this sender |
| `receiver_fan_in_is_fresh_burst` | 1 if that equals the receiver's all-time distinct payers (this one included) |
| `receiver_fan_out_3h` | distinct accounts the receiver paid in 3 h |
| `pair_txn_count_24h` | prior payments sender -> receiver in 24 h |
| `amount_to_sender_inflow_3h_ratio` | amount / sender's inflow in 3 h (sweep detection; NaN if no inflow) |

**Missing values.** 9 features are NaN when the history they summarise doesn't exist
(`NULLABLE_FEATURES`). Earlier code used `-1`, which collided with real values (a
z-score of exactly -1 is ordinary). XGBoost handles NaN with a learned default branch;
the Isolation Forest gets median imputation plus missing-indicator columns. Count and
sum features are not nullable: zero history genuinely means zero.

### 10.3 Training (`ml/train.py`)

1. **Load and label.** `label = true_label` else `scenario` else `"normal"`.
   `is_fraud = 1` iff `true_label` is set, so look-alikes and bystanders are `is_fraud=0`.
2. **Split chronologically**, after dropping burn-in (before 2026-07-16): train 60%
   (32,845 rows, 10.8% fraud), validation 20% (10,948; 9.3%), test 20% (10,949; 6.0%).
   Fraud prevalence falls over time, which matters for calibration (10.8).
3. **XGBoost grid search**: depth {3,4,6} x learning rate {0.05,0.1} x min_child_weight
   {1,5} = 12 fits; up to 1,000 trees, `subsample=0.8`, `colsample_bytree=0.8`,
   `eval_metric=aucpr`, early stopping 50 rounds on validation PR-AUC, `random_state=42`.
   **No class reweighting** (it inflates probabilities, and the ladder compares them
   to fixed thresholds). Winner: depth 3, lr 0.05, min_child_weight 1; the final model
   is **refit on train only** with `n_estimators = best_iteration + 1 = 468`.
4. **Isotonic calibration** (`IsotonicRegression`, clipped to [0,1]) fitted on the
   validation set's raw probabilities. The output is a step function, so many
   payments share identical calibrated scores.
5. **Alert threshold**: lowest calibrated score whose false-positive rate on validation
   non-fraud (normal + look-alikes) is <= 1%. Currently **0.1515**. It is a
   reporting number; **the backend never reads it** (section 11).
6. **Isolation Forest**: 300 trees on `label == "normal"` training rows only (so
   look-alikes are excluded), behind a median imputer with indicators. The raw score
   is converted to a percentile against **1,001 stored quantiles** of normal-traffic
   scores, giving the backend a 0-1 "how unusual" number.
7. **Test evaluation, once**: ROC-AUC, PR-AUC, Brier, recall/precision/FPR at the
   alert threshold, flag rate per label at the alert threshold and at 0.5, a 7-bucket
   calibration table, Isolation Forest metrics.
8. **Ablation**: retrains with base only, base + behavioural, and everything.
9. **Leave-one-scenario-out**: for each fraud pattern, retrain with it removed from
   train and validation (same params), recalibrate, set a 1%-FPR threshold, and measure
   recall on that pattern's test rows. This estimates generalisation to unseen fraud.
10. **Shortcut guards**: strongest single-feature ROC, and how many test fraud
    receivers also appeared in training.
11. **Export** artifacts and metadata.

### 10.4 Live feature computation (`app/ml/live_features.py`)

Per request: select every earlier transaction where sender or receiver appears on
either side, rebuild `transactions`/`accounts` frames, append the candidate, run the
**same** `build_features`, return the candidate row. This is deliberately slow-but-
correct: cost grows with the two accounts' history (measured 11 ms typical, 59 ms for
a 323-payment receiver on SQLite) in exchange for zero drift from the logic training
validated. A replay through the API reproduces the offline `ml_score` exactly, and a
test checks it.

### 10.5 Inference and explanations (`app/ml/model_loader.py`)

- `score_transaction(features)` returns `raw_xgboost_score`, the calibrated `ml_score`
  (this is what fuses), and `anomaly_percentile`.
- `explain_ml_score` runs a cached SHAP `TreeExplainer`, keeps the top 3 features
  that pushed the score **up**, and sets each reason's `contribution` to
  `ml_score x shap / sum(positive shap)`, so ML reasons are comparable with rule and
  graph contributions (0-1 units). The raw log-odds SHAP value stays in `details`. No
  reasons when `ml_score` rounds to 0.
- `anomaly_reason` adds `ml_anomaly` (no contribution) above the 99th percentile. It
  informs investigators and never moves the score; ~2,760 of 30k payments carry it.
- `model_version()` = the metadata's `trained_at`, stamped on every score.

### 10.6 Artifacts (`ml/models/`, committed)

| File | Contents |
|---|---|
| `xgboost.joblib` (~230 KB) | the classifier |
| `calibrator.joblib` (<1 KB) | isotonic regression |
| `isolation_forest.joblib` (~3 MB) | `{pipeline, reference_quantiles}` |
| `feature_columns.json` | `base_features`, `behavioral_features`, `graph_features`, `nullable_features`, `all_features` |
| `model_metadata.json` | `trained_at`, SHA-256 of both CSVs, library versions, `feature_columns`, XGBoost params, split sizes, `alert_threshold`, `target_fpr`, `anomaly_reason_percentile` |
| `metrics.json` | every number in the training report |

They are committed because they take real time to produce and the demo needs them
without a retrain.

### 10.7 Safety rails

- **Feature-list check at load.** If `feature_columns.json` or the metadata's list
  differs from the vendored feature code, loading raises `ModelsNotTrainedError`
  (503 on scoring) instead of silently mis-scoring.
- **Vendoring.** The backend Docker image is built from the backend directory plus
  `ml/models/`, so it cannot import `ml/features/engineering.py`. A byte-identical
  copy lives at `backend/app/ml/feature_engineering.py` below a header comment;
  `tests/test_feature_engineering_vendoring.py` fails if they drift. To change features:
  edit the `ml/` file, then copy it over the vendored one **keeping the header**
  (the recipe in section 19.3 does this).
- **Version pinning.** Joblib pickles of scikit-learn / xgboost objects aren't
  guaranteed compatible across versions, so `requirements.txt` pins
  `joblib 1.6.0`, `scikit-learn 1.9.1`, `xgboost 3.4.1`, `numpy 2.5.3`, `pandas 3.0.5`
  (plus `shap 0.52.0`, `networkx 3.6.1` in the backend) to the training versions, and
  loading logs a warning on drift.

### 10.8 Results **(regenerate)**

Held-out test split, 2026-09-04 to 2026-09-14, 10,949 rows.

| Metric | Value |
|---|---:|
| ROC-AUC / PR-AUC | 0.995 / 0.969 |
| Brier | 0.0071 |
| Alert threshold / recall / precision | 0.15 / 95.0% / 84.0% |
| Normal-traffic false-positive rate at alert threshold | 0.4% |

| Label | flagged @ alert threshold | flagged @ 0.5 | leave-one-out recall |
|---|---:|---:|---:|
| account_takeover | 96.8% | 90.5% | 84.1% |
| gambling_network | 100% | 100% | **0.0%** |
| layering_chain | 100% | 99.2% | 90.8% |
| mule_network | 80.1% | 65.8% | 70.6% |
| scam_recipient | 98.6% | 93.2% | 86.3% |
| normal *(legit)* | 0.4% | 0.1% | |
| innocent_bystander *(legit)* | 10.1% | 4.2% | |
| large_new_payee *(legit)* | **28.8%** | 7.6% | |
| group_collection *(legit)* | **21.9%** | 5.5% | |

**Ablation:**

| Features | ROC-AUC | PR-AUC |
|---|---:|---:|
| base only | 0.936 | 0.717 |
| + behavioural | 0.997 | 0.973 |
| + graph (shipped) | 0.995 | 0.969 |

The graph tier did **not** improve discrimination (slightly below the behavioural
model, within split noise) and did not improve mule recall (75.3% with, 76.0%
without, through the tuned pipeline). It was kept because it **calibrates better**:
Brier 0.0071 vs 0.0078, and the mean gap between predicted probability and observed
fraud rate in the 0.1-0.9 range fell from 0.099 to 0.036. The ladder assumes
calibrated scores.

**Calibration (test):** 0.9-1.0 bucket is 100% fraud; 0.7-0.9 is 86.6%; 0.55-0.70 is
51% (predicted 66%). The validation window has more fraud (9.3%) than test (6.0%),
and the calibrator was fitted on validation, so mid-range scores run slightly high.

**Isolation Forest:** 0.890 ROC-AUC with no labels (0.29 PR-AUC). Above its 99th
percentile it flags 40% of takeovers and 44% of layering hops against 4.8% of normal.

**Shortcut guards:** the strongest single feature, `receiver_outflow_total_hist`,
reaches 0.92 ROC alone (inverted). That is a real signal (fresh mule accounts haven't
sent money yet) but no longer decisive. Only 1.1% of test gambling receivers appeared
in training.

### 10.9 ML limitations

- **Look-alikes cost real false positives**: ~29% of legitimate large new-payee
  payments and ~22% of group collections cross the alert threshold.
- **Gambling does not generalise** (0% leave-one-out): individual bets look like merchant
  payments, so it is only learnable from labelled examples.
- **Mule is the weakest pattern** in the fused system (about 73-75% flagged at verify
  or higher, ~49% opening a case).
- One chronological split, no confidence intervals: treat one-to-two-point differences
  as noise.
- No drift monitoring and no retraining schedule; there is no model registry beyond git.

---

## 11. Fusion, confidence and the intervention ladder

### 11.1 Fusion (`scoring/fusion.py`)

```
fused_score = w_rule x rule + w_ml x ml + w_graph x graph          (rounded to 4 dp)
```

Current weights **0.2 / 0.6 / 0.2** (`fusion_weights` in `intervention_config.json`,
loaded into `DEFAULT_WEIGHTS`).

### 11.2 Confidence

"How much do we trust this number", not "how large is it":

```
active    = sources with score > 0
coverage  = len(active) / 3
agreement = 0.5                          if len(active) <= 1
            max(0, 1 - pstdev(active))   otherwise
confidence = 0.5 x coverage + 0.5 x agreement          (rounded to 4 dp)
```

Worked example from the live run above: rule 0.15, ml 0.0097, graph 0 -> two active
sources, coverage 0.667, agreement 1 - 0.0702 = 0.930, so confidence
0.5(0.667)+0.5(0.930) = **0.798**, and fused `0.2(0.15)+0.6(0.0097) = 0.0358`.
Note a benign payment can have high confidence: confidence says nothing about risk.

### 11.3 The ladder (`scoring/intervention.py`, `intervention_config.json`)

Walked top to bottom; the first level whose `min_score` **and** `min_confidence` are
both met wins. Config is cached at first use (restart to reload).

| Level | min fused | min confidence | What it triggers in the backend |
|---|---:|---:|---|
| escalate | 0.66 | 0.60 | CRITICAL case, status ESCALATED |
| restrict | 0.60 | 0.50 | HIGH case, status OPEN |
| hold | 0.43 | 0.40 | stored only |
| verify | 0.22 | 0.00 | stored only |
| warn | 0.16 | 0.00 | stored only |
| inform | 0.00 | 0.00 | stored only |

Consequences of the confidence gates, which are easy to miss:

- **One engine alone can reach at most `hold`.** A single active source gives
  confidence `0.5 x 0.333 + 0.5 x 0.5 = 0.4167`: that clears hold (0.40) but not
  restrict (0.50). Opening a case needs at least two engines to fire.
- The gate is weaker than it looks, because `first_time_beneficiary` fires on ~97% of
  payments and counts as an active engine. ML plus that rule already gives coverage 2/3.
- **A confirmed-fraud receiver is not auto-escalated.** `known_fraud_beneficiary` is
  0.9, plus first-time 0.15, capped at rule 1.0; times weight 0.2 = 0.2 fused, which is
  only `warn`. (The old weights gave 0.25, also `warn`.) This is a design gap
  (section 18.1).

### 11.4 Tuning (`backend/scripts/tune_fusion.py`, `app/scoring/tuning.py`)

Replays rules and graph over all 75k payments (no peeking at the future, empty
watchlist), scores the ML model, splits like training, then:

1. picks weights on a 0.05 grid by **validation PR-AUC of the fused score**, with a
   per-engine floor (`--min-weight`, default 0.10; **0.20 adopted**) because the offline
   replay has no confirmed fraud and so cannot value the known-fraud paths;
2. for each level top-down, picks the lowest `min_score` (0.01 grid) whose
   legitimate-traffic flag rate at-or-above that level stays under a target; rows
   already caught by a higher level count against the lower level's budget;
   `min_confidence` is held fixed. Targets: warn 5%, verify 1%, hold 0.3%, restrict
   0.1%, escalate 0.05% (product decisions about acceptable friction);
3. reports three configs on the untouched test split: A (previous), B (previous
   weights, tuned ladder), C (tuned weights, tuned ladder). `--write-config` writes C.

### 11.5 Results **(regenerate)** - test split, fused pipeline

| Tier | Before tuning: fraud caught / legit flagged | Now |
|---|---:|---:|
| fused PR-AUC | 0.940 | 0.949 |
| verify or higher | 90.7% / 0.47% | 93.2% / 1.09% |
| hold or higher | 31.5% / 0.10% | 89.0% / 0.22% |
| restrict or higher (opens a case) | 17.4% / 0.00% | 55.6% / 0.07% |
| escalate | **0.0%** / 0.00% | 30.1% / 0.06% |

Per pattern, share flagged verify-or-higher / opening a case (now): takeover 100% / 62%,
gambling 100% / 13%, layering 100% / 93%, scam 96% / 82%, mule 73% / 49%. Legitimate:
normal 0.3% / 0%, large_new_payee 62% / 4.5%, group_collection 15% / 0.4%,
bystander 4.2% / 0.8%.

Why the old config was so conservative: escalate needed fused >= 0.90, but with ML at
0.5 and graph almost never firing, fused scores top out near 0.75, so escalate was
effectively unreachable (one escalation in 30,000 payments). **Most of the gain came
from retuning the ladder, not the weights** (hold-or-higher recall 31.5% -> 88.7% with
the old weights alone).

Caveats: top-of-ladder thresholds rest on about five legitimate rows per split
(0.05% of ~9.9k); the verify tier landed at 1.09% on test against a 1% target; the
calibrator was fitted on the same validation rows used to tune, so test numbers are the
trustworthy ones.

### 11.6 Versioning

Every score stores `model_version` and `ladder_version`, so a decision can be traced
to the model and config that made it. Scores already in an existing database come from
the previous model and ladder (null versions); regenerate them by replaying into a
fresh database.

---

## 12. Cases and the investigator workflow

**Opening.** The pipeline opens a case only for `restrict` (OPEN, HIGH) and `escalate`
(ESCALATED, CRITICAL), with a `case_opened` event by `system`. There is **one case per
transaction**: nothing deduplicates by account, so a rapid sequence of risky payments
to the same receiver opens several cases (18.4).

**States.** `open -> investigating -> escalated`, any non-closed state `-> closed`.
`PATCH` may set any status except `closed`; closing requires a resolution via `/close`.
A closed case rejects `PATCH` and `/close` (409) but still accepts notes and
`confirm-fraud`.

**Audit trail.** Every mutation appends a `CaseEvent` (`assigned`, `unassigned`,
`status_changed`, `note`, `fraud_confirmed`, `closed`) with the `actor` string. There
is no authentication: the actor is whatever the client sends (the sidebar's "Acting as" field
keeps a name in `localStorage` and the dashboard sends it as `actor`). It is an audit label, not access control.

**Queue order** (`GET /cases`): open before closed, then critical > high > medium > low,
then oldest first. `top_reason` is the code of the highest-contribution reason.

**The feedback loop (important).** `get_known_fraud_upis` returns the receivers of
cases with a `fraud_confirmed` event. Those feed `rule known_fraud_beneficiary` (the
receiver itself) and `graph fraud_cluster_exposure` (one or two hops away) on every
later payment. **Automatic escalation alone does not count**: if it did, the system's
own unreviewed decisions would become its future inputs with no human in the loop.
Closing with `fraud_confirmed` records the same event, so the two paths can't
disagree, and confirmation is idempotent. This is also why the graph node payload
exposes `known_fraud`.

**Resolutions:** `fraud_confirmed`, `false_positive`, `customer_verified`. Only the
first changes scoring. Nothing learns from `false_positive` yet.

---

## 13. Frontend

Vite + React 18 + TypeScript, react-router, `@tanstack/react-query`, recharts. All
styling is one hand-written `styles.css` (Apple-style, light and dark). The API base
URL is `VITE_API_BASE_URL` (default `http://127.0.0.1:8000`), baked in at build time.
`src/api/types.ts` mirrors the backend schemas by hand; update both together.

| Route | Page | Data and refresh |
|---|---|---|
| `/` | Analytics: KPI tiles, decisions per hour, decision mix, urgent cases, top signals. Numbers only | stats 5 s, case summary 10 s, timeseries and reason codes 15 s |
| `/transactions` | Filterable, paged feed; row opens a detail drawer | 5 s on page 1 only (so rows don't shuffle under someone paging back) |
| `/cases`, `/cases/:id` | Queue and case detail (timeline, assign, notes, status, close, confirm fraud) | 8 s / 10 s |
| `/accounts/:upi` | Account profile and its transactions | 10 s / 8 s |
| `/network` | Full-screen canvas account-link graph (`GraphScene`), opens on the riskiest account; fetches `/graph?center=&depth=` (depth 1-3, default 2) with `max_nodes: 120` | on demand |
| `/demo` | Simulated phone on the left, "behind the scenes" on the right | stats 4 s |

**The demo (`pages/Demo.tsx`).** Pick a sender, pick a payee from the searchable
contact list (`GET /accounts?q=`), enter an amount, tap Pay. It calls the **real**
`POST /transactions`; the phone shows an outcome from the returned level (inform = sent;
warn = sent with a warning; verify = confirm first; hold = on hold; restrict/escalate =
blocked), while the right pane animates rules, ML, graph, fusion, decision, reason
codes and the graph around the payee. **Every demo payment writes a real scored
transaction (and possibly a case) to the connected database.** Use a scratch DB or
`dev.sh --reset` afterwards. The contact list shows no risk, like a real phone; an
optional "demo hints" toggle adds risk dots for the presenter.

`lib/format.ts` renders a reason code's `template` with its `details` and humanises
codes; if you add a reason code, check it reads well here.

---

## 14. Infrastructure

### 14.1 Compose (`docker-compose.yml`)

| Service | Build / image | Notes |
|---|---|---|
| `postgres` | `postgres:16-alpine`, volume `postgres_data` | `pg_isready` healthcheck; credentials from `.env`, local-dev fallbacks otherwise |
| `backend` | context = **repo root**, `backend/Dockerfile` | command `alembic upgrade head && uvicorn ...`; healthcheck `GET /health/ready` with a 60 s start period; waits for Postgres healthy |
| `frontend` | `frontend/Dockerfile` target `prod` | nginx serves the built bundle; waits for the backend to be healthy; port 5173 -> 80 |

The backend context is the repo root because the loader finds models at
`parents[3]/ml/models`; the image copies only `ml/models/`, and `.dockerignore`
excludes `ml/data`, `ml/synthetic`, `ml/features`, `ml/tests`, `.venv`, `.git`, `.env`.
The image installs `libgomp1` because the Linux XGBoost wheel needs OpenMP and
`python:3.12-slim` lacks it. `docker-compose.dev.yml` swaps the frontend to the `dev`
stage (Vite hot reload, `./frontend/src` mounted) and needs Compose 2.24+ for
`ports: !override`.

### 14.2 Configuration surface

| Setting | Where | Applies |
|---|---|---|
| `DATABASE_URL`, `CORS_ORIGINS`, `REBUILD_GRAPH_ON_STARTUP` | env / `backend/.env` via `app/config.py` | restart |
| Ladder and fusion weights | `scoring/intervention_config.json` | restart (cached) |
| Rule thresholds | `rules/config.py::RuleConfig` | code change |
| Graph thresholds | `graph/config.py::GraphConfig` | code change |
| Anomaly-reason percentile | `ml/models/model_metadata.json` | model reload |
| `alert_threshold` | `model_metadata.json` | **read by nothing** - training report only |
| `VITE_API_BASE_URL` | build arg / env | frontend rebuild |

### 14.3 CI (`.github/workflows/ci.yml`)

| Job | Checks |
|---|---|
| `ml` | `pytest ml/tests` |
| `backend` | rebuild `features.csv`, then the SQLite unit suite |
| `backend-postgres` | Postgres 16 service; migrations, `alembic check`, and the end-to-end test (scoring, filters, aggregates, cases, fraud feedback) |
| `frontend` | `npm ci`, `npm run build` |
| `images` | `docker compose config`, build both images, load the ML artifacts inside the backend image, and confirm nginx serves the app shell for `/` and `/cases/1` |

All versions are pinned exactly (including `pytest==9.1.1`). **The `backend-postgres`
and `images` jobs were written without a local Postgres or Docker**, so their first
CI run is their first execution there; the Postgres test body itself was validated
against SQLite through the real migrations.

### 14.4 Not handled

Secrets manager; more than one backend replica; authentication and authorization;
metrics, tracing and alerting; Postgres backups; a model registry.

---

## 15. Testing

128 backend tests (127 run; the Postgres one is skipped without `POSTGRES_TEST_URL`)
and 11 ML tests. Backend tests use an in-memory SQLite per test (`StaticPool`, so every
session shares one connection) and FastAPI's `TestClient`.

| File | What it protects |
|---|---|
| `test_rules_engine.py` (14) | each rule's thresholds, contributions and edge cases |
| `test_graph_builder.py` (6), `test_graph_analysis.py` (12), `test_graph_engine.py` (12) | edge creation, fan-in/out windows, fresh-burst gate, exposure BFS, rule firing |
| `test_live_graph_rebuild.py` (2) | restart rebuilds the same graph from stored transactions |
| `test_feature_engineering_vendoring.py` (1) | vendored copy is byte-identical below the header |
| `test_live_features.py` (4) | live feature rows equal the offline ones |
| `test_ml_model_loader.py` (10) | missing / mismatched artifacts are rejected, score shape, SHAP reasons |
| `test_fusion.py` (6), `test_intervention.py` (7) | fusion maths, confidence, ladder order and custom config |
| `test_scoring_config.py` (3) | config shape, weights sum to 1, version hash changes with any edit |
| `test_tuning.py` (4) | weight grid, vectorised ladder == `decide_intervention`, tuned thresholds respect FPR targets |
| `test_transactions_api.py` (18) | scoring end to end, filters, 404/503s, case invariant, version stamping |
| `test_case_workflow_api.py` (19) | queue order, assign, status, notes, close, 409s |
| `test_known_fraud_feedback.py` (3) | only investigator confirmation feeds scoring |
| `test_accounts_search.py` (2) | payee search |
| `test_health.py` (4) | liveness, readiness (DB down, models missing) |
| `test_postgres_integration.py` (1, Postgres/SQLite via URL) | migrations + `alembic check` + the Postgres-dialect queries + confirm-fraud loop |
| `ml/tests/test_engineering.py` (11) | no-history NaNs, no peeking, collector burst, fresh-burst, pair counts |

Gaps: nothing exercises concurrent scoring; no load or latency test; the frontend has
no tests beyond the type-check and build.

---

## 16. Accuracy: what the numbers say

A one-page summary; sections 10.8 and 11.5 have the detail.

- **ML alone (held-out test):** ROC-AUC 0.995, PR-AUC 0.969; 95% recall at 84%
  precision with 0.4% normal-traffic false positives. Weak spots: look-alike false
  positives (22-29%), gambling generalisation (0%), mule (~80% at best).
- **Fused system (held-out test):** 93% of fraud reaches verify or higher at 1.1% legit
  friction; 89% reaches hold or higher at 0.22%; 56% opens a case with 0.07% legit and
  98% case precision.
- **Per pattern, fused:** layering, takeover and gambling are flagged almost always;
  scam ~96%; **mule ~73%** and gambling opens cases for only 13% of its payments.
- **Honest evaluation controls:** chronological split, burn-in dropped, look-alike
  traffic, leave-one-scenario-out, shortcut guards, ablation, calibration table.
- **What it is not:** a real-world accuracy claim. Synthetic fraud is cleaner than real
  traffic; the model has seen the generator's patterns; one split.

---

## 17. Design decisions and the mistakes behind them

| Decision | Why | What happened without it |
|---|---|---|
| Three independent engines fused, with confidence | Each catches what the others miss; agreement is evidence | Rules alone: 55.8% false positives on large legitimate payments. Graph alone: 10% mule recall |
| Calibrated probabilities (isotonic on validation) | The ladder compares fixed thresholds | Raw scores don't mean what the thresholds assume |
| No class reweighting | Reweighting inflates probabilities | |
| Chronological split with burn-in | Fraud and prevalence drift over time; first-day accounts have no history | Random split leaks the future |
| Look-alikes and bystanders in the data | Measure false positives on hard cases | 0.999+ AUC from shortcuts |
| Same feature code at train and serve (vendored, byte-identical test) | No train/serve skew | Silent mis-scoring |
| NaN, not -1, for missing history | -1 collided with real z-scores | Model confused "no history" with "average" |
| Fresh-burst gate on graph fan-in | Distinguish a new collector from a busy hub | 76% -> 70% -> under 0.1% false positives |
| Only investigator-confirmed fraud feeds back | No self-reinforcing loop | System's own decisions would become its inputs |
| Config files for ladder, weights; hash stored per score | Retune without a deploy; trace decisions | Opaque decisions |
| Ladder tuned from FPR targets on validation, reported on test | Thresholds mean "this much friction" | Hand-set 0.90 escalate bar was unreachable |
| Per-engine weight floor 0.20 | Offline data can't value known-fraud paths | Search would zero out rules and graph |
| In-memory graph mirrored to the DB, rebuilt at startup | Fast graph algorithms; durable facts | Restart wiped graph history |
| Graph evaluated before it is updated | A payment must not count toward its own evidence | Self-confirming scores |
| Live features recomputed from history per request | Exactness over throughput | Hand-written incremental SQL drifting from training |
| Fail closed on model mismatch (503) | Never score with stale features | |
| One transaction per commit | Atomic; a request either writes everything or nothing | |
| SQLite dev path + Postgres target | Zero-install local runs | needs two schema paths (create_all vs Alembic) |

---

## 18. Known gaps and sharp edges

### 18.1 Behaviour

1. **Confirmed fraud is diluted by averaging.** A payment to a confirmed-fraud receiver
   reaches only `warn` today. A hard override ("confirmed-fraud beneficiary means at
   least hold") would fix it; it changes behaviour that offline data can't evaluate.
2. **The confidence gate is weakened by `first_time_beneficiary`** firing on ~97% of
   payments (section 11.3).
3. **Mule recall is the weakest area** and graph features did not fix it.
4. **Level is advisory**: transaction `status` is never changed by the backend.
5. **`status` (pending/failed) is ignored by scoring**; failed payments enter the graph.

### 18.2 Concurrency and consistency

6. **No locking around the in-memory graph.** Sync endpoints run on a threadpool;
   concurrent scoring can interleave evaluate-then-update on a structure that is not
   thread-safe for writes.
7. **The graph is updated before the DB commit.** An error between them leaves the
   in-memory graph ahead of the database until restart.
8. **Single replica only** (process-local graph).
9. **`POST /transactions` is not idempotent**: a retry creates a duplicate and another
   case.

### 18.3 Trust boundaries

10. **No authentication.** The case `actor` is self-declared. `POST /transactions`
    accepts `true_label` and `scenario` (synthetic ground truth) from clients, and the
    ML/graph code ignores them but they are stored and echoed in aggregates.
11. **CORS** is an allow-list of origins, not a security control for the API itself.

### 18.4 Data and workflow

12. **One case per transaction**, no dedupe by account or receiver.
13. `cases.summary` is never populated; severities `low`/`medium` are never produced.
14. **`false_positive` resolutions teach nothing.**
15. **`alert_threshold` is dead config** in `model_metadata.json`.
16. **Existing database scores are stale** relative to the current model/ladder (null
    versions); regenerate by replaying into a fresh DB.
17. SQLite files don't gain new columns automatically.

### 18.5 Performance

18. Live feature cost grows with the two accounts' history (every request re-reads it).
19. The whole-graph `GET /graph` (no `center`) grows without bound; the UI avoids it.
20. Startup rebuild is O(all transactions) with no snapshot.

---

## 19. Recipes

### 19.1 Add a rule

1. Write `rule_<name>(ctx, config) -> FiredRule | None` in `backend/app/rules/engine.py`
   and append it to `ALL_RULES`; add thresholds and contribution to `RuleConfig`.
2. Return a `template` using `{placeholders}` that `details` fills (the UI renders it).
3. Tests in `test_rules_engine.py` (fires, doesn't fire, boundary).
4. Re-run `scripts/evaluate_rules_on_synthetic.py` and **`scripts/tune_fusion.py`**: a new
   rule shifts `rule_score` and therefore the tuned ladder. Delete
   `ml/data/rule_graph_scores.csv` first (it caches rule/graph scores).

### 19.2 Add a graph rule

Same as above in `graph/engine.py` (`ALL_GRAPH_RULES`, `GraphConfig`). Evaluate it
**windowed and gated** (section 9.4) and check its false-positive rate on `normal` traffic
with `scripts/evaluate_graph_on_synthetic.py` before trusting it.

### 19.3 Add or change an ML feature

1. Edit `ml/features/engineering.py`: add the name to the right tier list (and
   `NULLABLE_FEATURES` if it can be missing), add any state to `_AccountState`, compute
   it **before** the state update, and add it to the row dict. Never let a payment see
   itself.
2. Add a test in `ml/tests/test_engineering.py`.
3. Sync the vendored copy, keeping the header:
   ```bash
   python3 - <<'EOF'
   v='backend/app/ml/feature_engineering.py'; s='ml/features/engineering.py'
   b='"""Phase 4 feature engineering.\n'
   head=open(v).read(); head=head[:head.index(b)]
   src=open(s).read(); open(v,'w').write(head+src[src.index(b):])
   EOF
   ```
4. `python -m ml.features.build_features && python -m ml.train` (with the `DYLD` variable on
   macOS). Check the ablation and the per-label table: **a feature that doesn't help
   should not ship** just because it exists.
5. `cd backend && python scripts/tune_fusion.py` and, if justified, `--write-config`.
6. Update `ml/README.md`, this guide's **(regenerate)** sections, and commit
   `ml/models/*` together with the code (the loader rejects mismatched artifacts).

### 19.4 Change the ladder or weights

Edit `intervention_config.json` by hand, or run `tune_fusion.py --write-config`.
Restart the backend. The new `ladder_version` appears on subsequent scores. Run
`test_scoring_config.py`.

### 19.5 Add a database column

Edit the model, then `cd backend && alembic revision --autogenerate -m "..."` against a
scratch database, review the file by hand, and confirm `alembic upgrade head`,
`alembic downgrade -1`, `alembic upgrade head` and `alembic check` all pass. Update the
Pydantic schema and `frontend/src/api/types.ts`. For a SQLite dev DB run `dev.sh --reset`
or `ALTER TABLE`.

### 19.6 Regenerate the synthetic data

Edit `ml/synthetic/config.py`, run the generator, rebuild features, retrain, retune,
and update the numbers in every **(regenerate)** section. Changing the seed or counts
changes every metric.

### 19.7 Reset the dev database and repopulate

```bash
cd backend && ./scripts/dev.sh --reset &        # fresh SQLite, server up
python scripts/replay_dataset.py --limit 30000 --rate 0 --shift-to-now
```

---

## 20. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `XGBoostError: libomp.dylib could not be loaded` | macOS without Homebrew libomp: export `DYLD_FALLBACK_LIBRARY_PATH` as in section 4.1. If it still fails you launched through `nohup`/`env`, which strip the variable |
| `POST /transactions` returns 503 "Model artifacts not found" / "different feature list" | artifacts missing or trained on another feature list; `python -m ml.features.build_features && python -m ml.train`, or restore `ml/models/` from git |
| `/health` says `not_trained` | same as above; `/health/ready` returns 503 |
| `no such column: risk_scores.model_version` | SQLite file predates migration `a7d3e1f4b2c9`; `dev.sh --reset` or `ALTER TABLE risk_scores ADD COLUMN model_version VARCHAR(64); ... ladder_version VARCHAR(32);` |
| `TypeError: can't compare offset-naive and offset-aware datetimes` | a timestamp skipped `_as_utc`; normalise at the boundary |
| `test_feature_engineering_vendoring` fails | you edited one feature file; copy `ml/features/engineering.py` over the vendored one keeping the header (19.3) |
| `test_ml_model_loader` can't find `features.csv` | run `python -m ml.features.build_features` |
| Everything scores `inform` after a restart on an empty DB | expected: no history yet. Replay data (section 4.2) |
| Graph looks empty / `GET /graph?center=` 404 | the account has no payments since the graph was built; check `REBUILD_GRAPH_ON_STARTUP` |
| Frontend can't reach the API | `VITE_API_BASE_URL` is wrong (it is the address the **browser** uses) or the origin isn't in `CORS_ORIGINS`; the production bundle needs a rebuild to change it |
| Case count looks inflated | one case per restrict/escalate payment (18.4) |
| Scores differ from the previous model | expected after retraining; compare `model_version` |
| `docker compose` `ports: !override` error | Compose older than 2.24; upgrade or remove the override file |
| First request after startup is slow (~240 ms) | SHAP explainer builds lazily on the first scored payment |

---

## 21. Glossary

- **UPI / VPA / IFSC**: India's instant payment system; a virtual payment address
  (`name@bank`); the bank branch code.
- **P2P / P2M**: person-to-person / person-to-merchant payment.
- **Mule account**: an account used to receive and pass on stolen money. A **collector**
  receives from many victims; a **cashout** is where money leaves the system.
- **Layering**: moving money through a chain of accounts to obscure its origin.
- **Account takeover (ATO)**: an attacker controls a victim's account, typically from a
  new device, and drains it.
- **Fan-in / fan-out**: distinct accounts paying into / paid out of an account.
- **Burn-in**: the 30 days of normal traffic generated before fraud so accounts have history.
- **Look-alike**: legitimate traffic engineered to resemble fraud, to measure false positives.
- **Calibration**: making a score mean its probability (a 0.7 is fraud about 70% of the time).
- **PR-AUC / ROC-AUC / Brier**: ranking quality on imbalanced data / overall ranking /
  mean squared probability error.
- **Leave-one-scenario-out**: retrain without one fraud pattern and test on it, to
  estimate generalisation to unseen fraud.
- **SHAP**: per-prediction feature attributions used for ML reason codes.
- **Isolation Forest**: unsupervised anomaly detector, trained on normal traffic.
- **Louvain**: community-detection algorithm used to cluster the graph.
- **Intervention ladder**: the six graduated responses, mapped from fused score and confidence.
- **Reason code**: a templated, machine-readable explanation of why a signal fired.
- **Known fraud**: a receiver of a case an investigator confirmed. The only thing that feeds back into scoring.
