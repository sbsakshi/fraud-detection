# backend

FastAPI service. Currently exposes only a health check (`GET /health`); the
scoring endpoint lands in Phase 6, once the rules, ML, and graph layers all
exist to fuse together.

## Phase 3 — rule engine (done)

`app/rules/` is a deterministic, DB-agnostic rules module: give it a
candidate transaction plus the history needed to evaluate it, and it
returns which rules fired as reason codes (template + filled values), not
bare booleans, in the same shape the `reason_codes` table stores.

```bash
backend/.venv/Scripts/python.exe -m pytest tests/
backend/.venv/Scripts/python.exe scripts/evaluate_rules_on_synthetic.py
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
query (once Phase 6 wires this into a scoring endpoint) or against a CSV
replay (used today by `scripts/evaluate_rules_on_synthetic.py`, since
there's no ingest endpoint yet to load the Phase 2 synthetic dataset
through).

### Sanity-checked against the Phase 2 synthetic dataset

`scripts/evaluate_rules_on_synthetic.py` replays `ml/data/transactions.csv`
chronologically (only ever looking at history strictly before each
transaction) and reports, per ground-truth label, how often the rules
fire at all vs. how often the combined score clears a would-actually-escalate
bar (`rule_score >= 0.5`):

| label               | any rule | >= 0.5 | total | any rate | thresh rate |
|---------------------|---------:|-------:|------:|---------:|------------:|
| account_takeover     |      243 |    157 |   348 |    69.8% |       45.1% |
| gambling_network     |      326 |     86 |  2310 |    14.1% |        3.7% |
| innocent_bystander   |      500 |      7 |   500 |   100.0% |        1.4% |
| layering_chain       |      819 |     47 |   819 |   100.0% |        5.7% |
| mule_network         |      823 |     63 |   823 |   100.0% |        7.7% |
| normal               |    26936 |   3481 | 45000 |    59.9% |        7.7% |
| scam_recipient       |      830 |    189 |   869 |    95.5% |       21.7% |

Read at the `>= 0.5` bar (the "any rule fired" column is dominated by the
low-weight `first_time_beneficiary` rule and overstates how often the
engine would actually escalate anything): rules alone catch `account_takeover`
reasonably well (an out-of-character device + amount jump is exactly what
`amount_above_historical_average` is built for) but are weak on
network-structured fraud (`mule_network`, `layering_chain`) — those show up
as fan-in/chain *patterns* across many transactions, which a rule looking at
one transaction at a time can only partially see. `innocent_bystander`
staying close to the `normal` baseline (1.4% vs 7.7%) confirms the rules
aren't mistaking "adjacent to a fraud account" for "fraudulent" on their
own. This is the expected shape of a rules-only baseline — it's exactly the
gap Phase 4 (ML) and Phase 5 (graph) exist to close, and this table is the
"before" half of the Phase 8 ablation story.

## Phase 4 — ML models loaded at startup (done)

`app/ml/` loads the artifacts `ml/notebooks/model_training.ipynb` trains
(see [../ml/README.md](../ml/README.md) for how they're built and what
they score) once at process startup via a FastAPI `lifespan` handler, and
exposes `score_transaction(features: dict) -> dict` for inference. Missing
artifacts don't crash the app -- `GET /health` reports
`"ml_models": "not_trained"` instead -- since there's no scoring endpoint
calling this yet; that wiring, including computing `features` from live
account/transaction state (reusing `ml.features.engineering`'s logic rather
than duplicating it, to avoid train/serve skew), is Phase 6.

`joblib`/`scikit-learn`/`xgboost` in `requirements.txt` are pinned to
exactly what trained the committed artifacts -- a joblib pickle of a
scikit-learn/xgboost object isn't guaranteed to unpickle cleanly across
library versions, so bumping either side without the other risks a load
failure that only shows up at runtime.

## Phase 5 — graph intelligence (done)

`app/graph/` maintains the money-movement graph and turns a handful of
queries over it into reason codes, the same `ReasonCodeResult` shape
`app/rules` produces (now shared at `app/scoring/schemas.py` so rules, ML,
and graph findings all fuse identically in Phase 6).

```bash
backend/.venv/Scripts/python.exe -m pytest tests/
backend/.venv/Scripts/python.exe scripts/evaluate_graph_on_synthetic.py
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
  `rules.known_fraud_beneficiary`'s job).

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

### Sanity-checked against the Phase 2 synthetic dataset

Per-transaction, replayed chronologically like Phase 3's script
(`rule_score >= 0.5` there; `graph_score >= 0.5` here):

| label               | any rule | >= 0.5 | total | any rate | thresh rate |
|---------------------|---------:|-------:|------:|---------:|------------:|
| account_takeover     |        0 |      0 |   348 |     0.0% |        0.0% |
| gambling_network     |        0 |      0 |  2310 |     0.0% |        0.0% |
| innocent_bystander   |        0 |      0 |   500 |     0.0% |        0.0% |
| layering_chain       |        0 |      0 |   819 |     0.0% |        0.0% |
| mule_network         |      113 |    113 |   823 |    13.7% |       13.7% |
| normal               |      967 |      6 | 45000 |     2.1% |        0.0% |
| scam_recipient       |        0 |      0 |   869 |     0.0% |        0.0% |

`scam_recipient` reads as a miss (0%), but it isn't a bug: that scenario
spreads its 10-30 victims' payments across up to 72 hours, well outside the
3h window tuned for `mule_network`'s much faster ~2.5h cycle. Widening the
window to 96h recovers 8.2% recall on `scam_recipient` but costs precision
elsewhere (normal's false-positive rate rises to 5.6%) -- a real
precision/recall dial, not a bug to chase to zero with one window size.
This is exactly why Phase 6 fuses multiple signal sources rather than
asking graph analysis alone to catch everything.

Whole-graph batch analysis (`detect_collector_candidates`, run once on the
fully-built graph rather than per-transaction) against the 223 accounts the
generator actually labeled `mule_network` (collectors + cashouts --
cashouts only ever *receive*, so a fan-in-*and*-fan-out heuristic can't and
shouldn't catch them; see `ml/synthetic/scenarios/mule_network.py`):

| variant                        | flagged | true positives | precision | recall* |
|---------------------------------|--------:|----------------:|----------:|--------:|
| unwindowed (any span)           |    1900 |             129 |      6.8% |   57.8% |
| span-limited (`<= 6h`)          |      90 |              90 |    100.0% |   40.4% |

\* recall against *all* mule_network accounts including the structurally
undetectable cashouts -- against collectors alone it's meaningfully higher.
`detect_communities` (Louvain, no fan-in/fan-out assumption at all) is the
better tool for *breadth*: 52 communities found, covering 219/223 (98.2%)
of true mule accounts including the cashouts the fan-in/fan-out heuristic
structurally can't see.
