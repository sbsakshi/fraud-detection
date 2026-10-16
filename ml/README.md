# ml

Synthetic data generation, feature engineering, and model training for the
backend's ML layer.

```bash
# from the repo root
pip install -r ml/requirements.txt pytest
python -m ml.synthetic.generate_dataset   # -> ml/data/{accounts,transactions}.csv
python -m ml.features.build_features      # -> ml/data/features.csv (gitignored)
python -m ml.train                        # -> ml/models/*
python -m pytest ml/tests/
```

On macOS, xgboost needs an OpenMP runtime: `brew install libomp`, or point
`DYLD_LIBRARY_PATH` at the copy scikit-learn bundles
(`.../site-packages/sklearn/.dylibs`).

## Synthetic data (`synthetic/`)

Statistically generated "normal" UPI traffic, six labelled scenario injectors,
and two unlabelled look-alike patterns. Generation is seeded (`SEED` in
`synthetic/config.py`), so re-running reproduces the same dataset: 6,892
accounts and 75,001 transactions, 7.0% labelled fraud.

### Design rules (each fixes a shortcut the first version had)

| Rule | Why |
|---|---|
| A 30-day burn-in (`BURN_IN_DAYS`) of normal traffic before any fraud; training drops it | Otherwise every account starts with empty history on day 1, and "no history" stops meaning "new account" |
| 6% of normal accounts are opened inside the window (`NEW_ACCOUNT_RATE`) | Fraud accounts used to be the *only* new accounts, so "brand-new receiver" was a near-perfect label |
| 30-50% of fraud-role accounts are aged, recruited or bought accounts | Same reason; real mule herders recruit established accounts |
| No transaction predates its accounts (enforced by a check in `generate_dataset.py`) | The first version had ~1,800 rows with negative account age |
| Account takeovers are spread over the whole window, 50% at night | They used to be pinned to the last 10 days, so all of them landed in the test split |
| 20 short-lived gambling operators instead of 5 permanent ones | With 5, every test operator was also in training and the model memorized them |
| Look-alikes: `large_new_payee` (450 rows), `group_collection` (1,321 rows) | Legitimate traffic sharing surface features with fraud, so evaluation measures false positives on the hard cases |

### Layout

- `synthetic/config.py`: every tunable constant.
- `synthetic/base_traffic.py`: accounts and normal transactions from
  statistical distributions (log-normal amounts, Pareto-weighted activity, an
  hour-of-day curve).
- `synthetic/legit_patterns.py`: the unlabelled look-alikes.
- `synthetic/scenarios/`: one module per labelled pattern (`scam_recipient`,
  `mule_network`, `layering_chain`, `account_takeover`, `gambling_network`),
  plus `innocent_bystander`: an ordinary account with one normal transaction
  with a fraud-labelled account, which the system should *not* flag.
- `synthetic/generate_dataset.py`: orchestrates the above and writes `data/`.

### Output schema

`accounts.csv`: `upi_id` (natural key), `account_number`, `ifsc_code`,
`owner_name`, `bank_name`, `account_type`, `device_id`, `true_label` (the
fraud pattern the account took part in; null = normal), `is_active`,
`created_at`.

`transactions.csv`: `txn_ref` (natural key), `sender_upi_id`,
`receiver_upi_id`, `amount`, `currency`, `device_id`, `transaction_type`,
`status`, `true_label` (null unless the transaction itself is fraud),
`scenario` (which injector produced the row; set for look-alikes and
bystanders too, which carry no `true_label`), `created_at`.

## Features (`features/engineering.py`)

One chronological pass, every feature computed only from state built up by
transactions strictly *before* the one being scored. The backend reruns the
exact same code at scoring time (vendored copy, kept byte-identical by a
test), so there's no train/serve skew.

- **Base** (5): `amount`, `log_amount`, `hour_of_day`, `day_of_week`, `is_p2p`.
- **Behavioral** (32): account age, amount mean/std/z-score versus the sender's
  history, send velocity (1h/24h), first-time beneficiary, fan-in/fan-out
  counts (receiver over 1h *and* 24h), inflow/outflow totals and ratios,
  holding time, device reuse and sharing (sender's device and the receiver's
  devices), time since each account first appeared in the payment graph, and
  merchant flags.
- Missing history is `NaN` (`NULLABLE_FEATURES`), not a `-1` sentinel that
  collided with real values. XGBoost handles NaN natively; the Isolation
  Forest gets median imputation plus missing-indicator columns.

## Training (`train.py`)

1. Drop the burn-in, then split chronologically: train 60% / validation 20% /
   test 20% (32,845 / 10,948 / 10,949 rows).
2. XGBoost: grid search over depth, learning rate and min child weight, with
   early stopping on validation PR-AUC. No class reweighting, which would
   inflate probabilities.
3. Isotonic calibration on validation, so scores are probabilities.
4. Alert threshold = lowest calibrated score that keeps validation non-fraud
   false positives at or under 1%.
5. Isolation Forest on normal training traffic only, reported as a percentile
   of normal-traffic anomaly scores.
6. Evaluate once on test, and run leave-one-scenario-out retraining.

Artifacts in `ml/models/`: `xgboost.joblib`, `calibrator.joblib`,
`isolation_forest.joblib`, `feature_columns.json`, `model_metadata.json` (data
hashes, library versions, parameters, thresholds; checked by the backend at
load) and `metrics.json` (everything below). They're committed, so the backend
works without retraining.

## Results (test split, 2026-09-04 .. 2026-09-14)

| Metric | Value |
|---|---:|
| ROC-AUC | 0.997 |
| PR-AUC | 0.970 |
| Brier score | 0.008 |
| Alert threshold (calibrated) | 0.10 |
| Recall / precision at alert threshold | 93.9% / 85.0% |
| Normal-traffic false-positive rate at alert threshold | 0.3% |

Flag rate per label: recall for fraud, false-positive rate for the rest.

| Label | at alert threshold (0.10) | at 0.5 | Leave-one-scenario-out recall |
|---|---:|---:|---:|
| account_takeover | 95.2% | 90.5% | 84.1% |
| gambling_network | 100.0% | 100.0% | 0.0% |
| layering_chain | 100.0% | 99.2% | 92.5% |
| mule_network | 77.4% | 69.2% | 73.3% |
| scam_recipient | 97.3% | 94.5% | 82.9% |
| normal *(not fraud)* | 0.3% | 0.1% | |
| innocent_bystander *(not fraud)* | 7.6% | 4.2% | |
| large_new_payee *(not fraud)* | 28.8% | 9.1% | |
| group_collection *(not fraud)* | 21.4% | 13.5% | |

How to read it:

- **The original 0.999+ numbers were inflated** by the generator shortcuts in
  the table above. On the regenerated data, the same model family scores 0.997
  ROC-AUC with honest per-scenario recall, and its weak spots are visible.
- **Look-alikes are the real cost.** A legitimate large payment to a new payee
  is flagged 28.8% of the time at the alert threshold, and a group collection
  21.4%. These rates are what to watch as the model or features change.
- **Leave-one-scenario-out** (trained without a pattern, tested on it)
  measures generalization to fraud the model never saw. Takeover, layering and
  scam stay at 83-93%. Gambling drops to 0%: individual bets look like
  ordinary merchant payments, so it can only be learned from labelled
  examples.
- **Calibration** is good where it matters: the 0.9-1.0 bucket is 100% fraud
  and 0.7-0.9 is 76%. The mid buckets run high, because the test window has
  less fraud (6.0%) than validation (9.3%), where the calibrator was fitted.
- **Ablation:** base features alone reach 0.936 ROC / 0.717 PR-AUC; adding the
  behavioral tier lifts that to 0.997 / 0.970.
- **Isolation Forest:** 0.895 ROC-AUC with no labels. Above its 99th
  percentile it flags 56% of takeovers and 49% of layering hops, versus 3.8%
  of normal traffic.
- **Shortcut guards** (in `metrics.json`): the strongest single feature,
  receiver outflow history, reaches 0.92 ROC on its own (inverted). That's a
  real but no longer decisive signal: fresh mule accounts genuinely haven't
  sent money yet. Only 1.1% of test gambling receivers appeared in training.

The fraud here is still synthetic and cleaner than real traffic. Treat these
numbers as a check that the pipeline learns the signal that's there and is
measured honestly, not as a real-world accuracy claim.
