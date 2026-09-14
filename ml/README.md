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

## Phase 4 — model training (not started)

Feature engineering, model training notebooks, and exported model artifacts
(XGBoost, Random Forest, Isolation Forest) land here.
