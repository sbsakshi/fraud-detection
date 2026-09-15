# ml

## Phase 2 — synthetic data (done)

`synthetic/` generates the full dataset the rest of the project trains and
demos against: statistically-generated "normal" UPI traffic, plus six
scenario injectors that each add a labelled fraud pattern on top.

```bash
# from the repo root, using ml/.venv
ml/.venv/Scripts/python.exe -m ml.synthetic.generate_dataset
```

Writes `data/accounts.csv` and `data/transactions.csv`. Generation is seeded
(`SEED` in `synthetic/config.py`) so re-running reproduces the same dataset.

### Layout

- `synthetic/config.py` — every tunable constant: account/transaction counts,
  date window, per-scenario scale.
- `synthetic/base_traffic.py` — accounts and "normal" transactions, built from
  statistical distributions (log-normal amounts, Pareto-weighted per-account
  activity, an hour-of-day usage curve), not hand-authored rows.
- `synthetic/helpers.py` — shared id/identity generation (UPI ids, IFSC codes,
  device ids, account rows).
- `synthetic/scenarios/` — one module per labelled fraud pattern:
  - `scam_recipient` — a fresh account collects one-off payments from many
    unrelated victims, then sweeps the proceeds onward.
  - `mule_network` — fan-in from many source accounts to a handful of
    collectors within a tight window, then fan-out to cashout accounts; some
    collectors share a device (one mule herder, several accounts).
  - `layering_chain` — a lump sum moves hop-by-hop through a fresh account
    chain in quick succession, shedding a small "fee" each hop.
  - `account_takeover` — an established account transacts from a device it's
    never used, draining an unusually large sum to a brand-new beneficiary.
  - `gambling_network` — a small set of betting-operator merchants receive
    frequent, mostly-late-night payments from a large bettor pool.
  - `innocent_bystander` — an ordinary account has one perfectly normal
    transaction with an account that carries a fraud label elsewhere; not
    itself fraudulent, so the system is expected *not* to flag it. Runs last,
    since it needs the other scenarios' accounts to be adjacent to.
- `synthetic/generate_dataset.py` — orchestrates the above and writes `data/`.

### Output schema

`accounts.csv`: `upi_id` (natural key), `account_number`, `ifsc_code`,
`owner_name`, `bank_name`, `account_type`, `device_id`, `true_label`
(ground-truth fraud pattern, null = normal), `is_active`, `created_at`.

`transactions.csv`: `txn_ref` (natural key), `sender_upi_id`,
`receiver_upi_id`, `amount`, `currency`, `device_id`, `transaction_type`,
`status`, `true_label` (null unless the transaction itself is fraudulent —
`innocent_bystander` transactions carry a `scenario` but no `true_label`),
`scenario` (which injector produced the row, null for base traffic),
`created_at`.

Rows reference accounts by `upi_id` / transactions by natural keys rather
than the backend's integer primary keys, since those are assigned by
Postgres at insert time — a later loader/replay step resolves them.

## Phase 4 — model training (done)

`features/` turns the Phase 2 synthetic dataset into a labeled feature
table; `notebooks/model_training.ipynb` trains on it and exports the
artifacts `backend/app/ml` loads at startup.

```bash
# from the repo root, using ml/.venv (pip install -r ml/requirements-dev.txt
# for jupyter/pytest on top of ml/requirements.txt)
ml/.venv/Scripts/python.exe -m ml.features.build_features   # -> ml/data/features.csv
ml/.venv/Scripts/python.exe -m pytest ml/tests/
ml/.venv/Scripts/python.exe -m jupyter lab                  # open notebooks/model_training.ipynb
```

### Features

`features/engineering.py` does one chronological pass over
`transactions.csv`, computing every feature from account/device state built
up by transactions strictly *before* the one being scored -- the same
no-peeking-at-the-future discipline `backend/app/rules` uses, so training
data never sees information a live system wouldn't have at scoring time.
32 features split into two tiers (`BASE_FEATURES`, `BEHAVIORAL_FEATURES`),
so an ablation study can later ask "did the behavioral tier actually help":

- **Base** (5): `amount`, `log_amount`, `hour_of_day`, `day_of_week`, `is_p2p`.
- **Behavioral** (27): account age, historical amount mean/std and z-score,
  send velocity (1h/24h), first-time-beneficiary, fan-out/fan-in counts,
  inflow/outflow totals and ratio, time since last sent/received
  ("holding time"), device reuse and shared-device count, and
  `sender_is_merchant`/`receiver_is_merchant` -- added after a spot-check
  found merchant P2M fan-in swamping the mule-collector fan-in signal
  without it (see the module docstring).

### Models

Three models trained in `notebooks/model_training.ipynb` on an 80/20
**chronological** train/test split (train on the past, evaluate on the
future -- a random shuffle would leak shared account history across the
split):

- **XGBoost** and **Random Forest** — supervised, using the synthetic
  dataset's `true_label`, class-imbalance corrected (`scale_pos_weight` /
  `class_weight="balanced"`).
- **Isolation Forest** — unsupervised anomaly detection, sees only feature
  values, never the label. Included because production will eventually
  meet fraud patterns no labeled example covered; scores well behind the
  supervised models here precisely because it gets no label to calibrate
  against (see the notebook for why that gap doesn't mean it's broken).

On the held-out test set, XGBoost and Random Forest both land above 0.999
ROC-AUC / PR-AUC; Isolation Forest reaches ~0.59 ROC-AUC. The notebook
verifies this isn't the model memorizing specific accounts (fraud senders
actually repeat *less* often between train and test than normal senders
do, 80% vs 97%) and includes a genuine zero-shot result: `account_takeover`
never appears in the training window at all, yet XGBoost catches 100% of
it at test time, because the amount-jump + new-device signature it learns
from *other* scenarios generalizes. The honest caveat sits right next to
that finding in the notebook: this dataset's fraud is synthetically
distinctive on purpose, so read these numbers as "the pipeline learns the
signal that's there," not as a real-world accuracy claim.

SHAP (`TreeExplainer` on XGBoost) explains individual predictions --
per-feature contribution plots plus one worked fraud example -- and a
preliminary base-vs-behavioral ablation (not Phase 8's full study; no graph
score exists yet) shows the behavioral tier roughly doubling precision
(~0.52 → ~0.99) at slightly better recall on this run.

### Output

`ml/models/`: `xgboost.joblib`, `random_forest.joblib`,
`isolation_forest.joblib`, `feature_columns.json` (records the exact
column order each model expects -- a plain array has no column names to
check against at inference time), `model_comparison.csv`. Committed to the
repo (under 10MB total) so `backend/app/ml` has something to load without
everyone re-running the notebook first.

## Phase 5 — graph intelligence (not started)
