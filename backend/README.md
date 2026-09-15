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
