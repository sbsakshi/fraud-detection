# backend

FastAPI service: rules + ML + graph scoring for every transaction, fused into
one score and a proportionate intervention.

| Endpoint | What it does |
|---|---|
| `GET /health` | DB check + whether ML artifacts loaded |
| `POST /accounts` | Create an account (send `created_at` when replaying history -- account-age features depend on it) |
| `POST /transactions` | Score + persist one transaction (rules, ML, graph, fusion, intervention, case) |
| `GET /transactions`, `GET /transactions/stats` | Dashboard feed and summary tiles |
| `GET /graph` | Live money-movement graph for the network view |
| `POST /cases/{id}/confirm-fraud` | Investigator confirmation; the only way a receiver becomes "known fraud" for future scoring |

Configuration comes from environment variables (`backend/app/config.py`):
`DATABASE_URL`, `CORS_ORIGINS` (comma-separated) and
`REBUILD_GRAPH_ON_STARTUP` (default on). At startup the in-memory transaction
graph is rebuilt from the `transactions` table, so a restart keeps every
account's graph history.

```bash
# from backend/
pip install -r requirements-dev.txt
python -m pytest tests/
python scripts/replay_synthetic.py --limit 2000   # populate a running backend from ml/data/
```

## Phase 3 — rule engine (done)

`app/rules/` is a deterministic, DB-agnostic rules module: give it a
candidate transaction plus the history needed to evaluate it, and it
returns which rules fired as reason codes (template + filled values), not
bare booleans, in the same shape the `reason_codes` table stores.

```bash
python scripts/evaluate_rules_on_synthetic.py
```

### Rules

- `known_fraud_beneficiary` — receiver is on an (injected) fraud watchlist.
- `amount_above_historical_average` — amount is `>= 3x` the sender's own
  average, once the sender has enough history (`>= 3` prior transactions)
  to trust an average at all.
- `first_time_beneficiary` — sender has never paid this receiver before.
  Common on legitimate transactions too, so it carries a small
  contribution on its own; it mainly matters stacked with another rule.
- `fan_in_velocity` — `>= 5` distinct senders paid one receiver within a
  10-minute window.

Each rule's contribution is additive and the combined `rule_score` is
capped at `1.0`. Thresholds live in `app/rules/config.py::RuleConfig`, not
hardcoded in the rule bodies, so they can be swept later (Phase 8's
ablation study) without touching rule logic.

### Why it's DB-agnostic

`RuleContext`/`RuleTransaction` are plain dataclasses, not the SQLAlchemy
models — so the exact same rule functions run against a live Postgres
query (`POST /transactions`) or against a CSV replay
(`scripts/evaluate_rules_on_synthetic.py`).

### Sanity-checked against the Phase 2 synthetic dataset

`scripts/evaluate_rules_on_synthetic.py` replays `ml/data/transactions.csv`
chronologically (only ever looking at history strictly before each
transaction) and reports, per ground-truth label, how often the rules
fire at all vs. how often the combined score clears a would-actually-escalate
bar (`rule_score >= 0.5`):

| label | any rule | >= 0.5 | total | any rate | thresh rate |
|---|---:|---:|---:|---:|---:|
| account_takeover | 272 | 213 | 366 | 74.3% | 58.2% |
| gambling_network | 400 | 63 | 2294 | 17.4% | 2.7% |
| layering_chain | 841 | 213 | 841 | 100.0% | 25.3% |
| mule_network | 855 | 201 | 855 | 100.0% | 23.5% |
| scam_recipient | 838 | 397 | 874 | 95.9% | 45.4% |
| normal | 64183 | 3507 | 67500 | 95.1% | 5.2% |
| innocent_bystander *(not fraud)* | 500 | 13 | 500 | 100.0% | 2.6% |
| large_new_payee *(not fraud)* | 450 | 251 | 450 | 100.0% | 55.8% |
| group_collection *(not fraud)* | 1321 | 120 | 1321 | 100.0% | 9.1% |

Read at the `>= 0.5` bar (the "any rule fired" column is dominated by the
low-weight `first_time_beneficiary` rule). Rules catch `account_takeover`
best, since an amount jump is exactly what `amount_above_historical_average`
targets, but the `large_new_payee` row shows the cost: a legitimate one-off
large payment trips the same rule 55.8% of the time. Network-structured fraud
(`mule_network`, `layering_chain`) shows up as patterns across many
transactions, which a rule looking at one transaction at a time only partly
sees. That's the gap the ML and graph layers exist to close.

## ML layer (`app/ml/`)

`app/ml/model_loader.py` loads the artifacts `python -m ml.train` exports
(see [../ml/README.md](../ml/README.md) for how they're built and evaluated)
once at startup via a FastAPI `lifespan` handler. Missing or mismatched
artifacts don't crash the app -- `GET /health` reports
`"ml_models": "not_trained"` and `POST /transactions` returns 503.

- `ml_score` is the **calibrated** XGBoost probability (isotonic, fitted on
  held-out validation data), so the intervention ladder's fixed thresholds
  mean what they say.
- The Isolation Forest (trained on normal traffic only) is reported as an
  anomaly percentile and surfaces as an informational `ml_anomaly` reason
  code above the 99th percentile; it never moves the fused score.
- `explain_ml_score` turns per-prediction SHAP values into reason codes. Each
  `contribution` is that feature's share of `ml_score` (0-1 units, comparable
  with rule/graph contributions); the raw log-odds SHAP value stays in
  `details`.
- Live features come from `app/ml/live_features.py`, which reruns the exact
  training feature code (vendored at `app/ml/feature_engineering.py`, kept
  byte-identical by `tests/test_feature_engineering_vendoring.py`) over the
  sender's and receiver's history. A replay through the API reproduces the
  offline `ml_score` exactly.
- Loading checks `model_metadata.json`: the feature list must match the
  vendored code (else the artifacts are rejected), and a scikit-learn /
  xgboost version different from training logs a warning. `joblib`,
  `scikit-learn` and `xgboost` in `requirements.txt` are pinned to the
  training versions for that reason.

## Phase 5 — graph intelligence (done)

`app/graph/` maintains the money-movement graph and turns a handful of
queries over it into reason codes, the same `ReasonCodeResult` shape
`app/rules` produces (shared at `app/scoring/schemas.py` so rules, ML, and
graph findings all fuse identically).

```bash
python scripts/evaluate_graph_on_synthetic.py
```

### `builder.TransactionGraph`

Writes the three edge types the `graph_edges` table expects
(`GraphEdgeType`): a `transaction` edge per payment, `shared_device` edges
linking accounts that reuse a device, and one `repeated_counterparty` edge
per pair once they cross a repeat threshold (its `weight` updates in place
rather than adding a row per repeat, which would grow unbounded for a
heavily-repeated pair).

### `analysis.py` — read-only graph queries

`fan_in_out`/`recent_counterparties` (windowed distinct counterparties),
`device_user_count`, `transaction_edge_count`, `detect_collector_candidates`
(mule-collector shape: fan-in *and* fan-out both cross a threshold),
`detect_communities` (broader ring clustering via Louvain, for patterns
with no single hub node), `fraud_cluster_exposure` (BFS hop-distance to a
known-fraud account), `trace_money_trail` (forward-in-time paths out of an
account).

### `engine.py` — four graph-native reason codes

- `mule_collector_pattern` — fan-in *and* fan-out both cross a threshold,
  *and* it's this account's entire history so far, within a
  `collector_window_hours` window (default 3h).
- `shared_device_ring` — sender's device is already linked to
  `>= shared_device_account_threshold` other accounts.
- `repeated_counterparty` — this sender/receiver pair has transacted
  `>= repeated_counterparty_threshold` times within
  `repeated_counterparty_window_hours` (default 24h).
- `fraud_cluster_exposure` — receiver is 1-2 hops from a known-fraud
  account via transaction flow (not *is* one -- that's
  `rules.known_fraud_beneficiary`'s job). "Known fraud" means the receiver of
  a case an investigator confirmed via `POST /cases/{id}/confirm-fraud`;
  automatic escalation alone doesn't count, so the system's own unreviewed
  decisions can't feed back into its inputs.

### The false-positive trap this module fell into, twice

Naive fan-in/fan-out counting looked plausible in testing but was nearly
useless against the full synthetic dataset -- worth recording since both
mistakes are easy to reintroduce:

1. **Unwindowed counts flag every long-lived account eventually.** A
   first pass with no time window at all flagged **76% of ordinary
   traffic** -- almost any account active for two months eventually
   accumulates fan-in >= 3 and fan-out >= 2 just from normal life, so
   "ever had this shape" carries no signal.
2. **A window alone isn't enough.** Adding a 24h window only dropped the
   false-positive rate to 70%, because a handful of genuinely
   high-throughput hub accounts (this dataset's Pareto-weighted "popular
   merchant" accounts) cross a fan-in/fan-out threshold within *some*
   recent window constantly, just by being busy. The fix was
   `_is_fresh_burst`/`max_span_hours`: compare the windowed count against
   the account's *entire* history so far -- a mule collector's burst
   *is* its whole history (it's a freshly created, single-use account); an
   established hub's latest slice is not. That, plus tightening the
   window to `3h` (matching this scenario's actual ~2.5h fan-in-then-sweep
   cycle) and correcting `collector_min_fan_out` from `2` to `1` (a real
   collector here sweeps to exactly *one* cashout, not several), took the
   per-transaction false-positive rate from 76% to under 0.1% at a
   real-escalation threshold, while still catching 13.7% of `mule_network`
   transactions directly.

### Sanity-checked against the synthetic dataset

Per-transaction, replayed chronologically like the rules script
(`graph_score >= 0.5`). These numbers come from the regenerated dataset, where
about half the mule collectors are recruited, established accounts and
`group_collection` is a legitimate fan-in look-alike:

| label | any rule | >= 0.5 | total | any rate | thresh rate |
|---|---:|---:|---:|---:|---:|
| mule_network | 89 | 89 | 855 | 10.4% | 10.4% |
| gambling_network | 10 | 0 | 2294 | 0.4% | 0.0% |
| account_takeover, layering_chain, scam_recipient | 0 | 0 | 2081 | 0.0% | 0.0% |
| normal | 11 | 11 | 67500 | 0.0% | 0.0% |
| group_collection *(not fraud)* | 24 | 24 | 1321 | 1.8% | 1.8% |
| innocent_bystander *(not fraud)* | 4 | 4 | 500 | 0.8% | 0.8% |
| large_new_payee *(not fraud)* | 0 | 0 | 450 | 0.0% | 0.0% |

Mule recall fell from 13.7% (old dataset) to 10.4%. That's expected: a
recruited collector already has history, so its burst is no longer "its whole
history", which is what `_is_fresh_burst` keys on. `scam_recipient` stays at 0%
because victims' payments spread over up to 72 hours, outside the 3h window.
Widening the window trades precision elsewhere -- which is why the scoring
pipeline fuses several signal sources rather than asking graph analysis alone
to catch everything.

Whole-graph batch analysis against the 228 accounts labelled `mule_network`
(collectors + cashouts; cashouts only ever *receive*, so a fan-in-*and*-fan-out
heuristic can't and shouldn't catch them):

| variant | flagged | true positives | precision | recall* |
|---|---:|---:|---:|---:|
| unwindowed (any span) | 4024 | 155 | 3.9% | 68.0% |
| span-limited (`<= 6h`) | 48 | 48 | 100.0% | 21.1% |

\* recall against *all* mule_network accounts including the structurally
undetectable cashouts. `detect_communities` (Louvain, no fan-in/fan-out
assumption) is the better tool for breadth: 24 communities found, covering
224/228 (98.2%) of true mule accounts.
