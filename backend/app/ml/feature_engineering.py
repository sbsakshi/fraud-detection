# Vendored, verbatim, from ml/features/engineering.py -- Docker builds the
# backend image from the backend/ directory alone (see backend/Dockerfile),
# so it can't reach a sibling ml/ package at runtime the way a native dev
# checkout can. `live_features.py` calls `build_features` from here to
# compute live scores with the exact same logic Phase 4 trained against,
# without a cross-package import that would work locally by directory-layout
# accident but break in the actual deployed container.
#
# Everything from the next line down is byte-identical to the source file --
# tests/test_feature_engineering_vendoring.py enforces that, so a change to
# the canonical ml/ version and a forgotten re-sync here fails CI loudly
# instead of silently causing train/serve skew. Copy the whole file over
# (keeping this header) rather than hand-editing a diff between them.
"""Phase 4 feature engineering.

One forward pass over `transactions.csv` in chronological order, mirroring
the no-peeking-at-the-future discipline `backend/app/rules` already uses:
every feature for a transaction is computed only from account/device state
built up by transactions strictly before it, then the state is updated.

Features are split into two tiers so later phases can run the ablation
study the project needs:

- `BASE_FEATURES` — raw transaction attributes only (amount, timing). A
  model trained on just these is the "ML alone" baseline.
- `BEHAVIORAL_FEATURES` — everything derived from account/device history
  (velocity, historical-average deviation, beneficiary novelty,
  inflow/outflow shape, device reuse). Adding these is the "ML + behavioural
  features" variant.

Phase 5 graph features are a separate, later addition on top of both.

`sender_is_merchant`/`receiver_is_merchant` exist because merchants
legitimately receive from many distinct customers -- a spot-check while
building this found `receiver_unique_senders_1h` averaging *higher* for
ordinary traffic than for `mule_network`, purely because merchant P2M fan-in
dwarfs a mule collector's. Without an account-type signal, a model has no
way to tell "popular merchant" apart from "mule collector" using fan-in
alone.

Missing-history sentinel: continuous features that need prior activity to
mean anything (an average, a "time since", an account age) use `-1.0` when
that history doesn't exist yet, rather than `NaN` -- scikit-learn's
`RandomForestClassifier`/`IsolationForest` reject `NaN` outright, and `-1`
is a value below every real observation in these features, so trees can
still carve it into its own split instead of it silently corrupting a mean.
Count/sum features have no such gap: zero history genuinely means zero.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import timedelta
from math import log1p, sqrt

import pandas as pd

ONE_HOUR = timedelta(hours=1)
TWENTY_FOUR_HOURS = timedelta(hours=24)
NO_HISTORY = -1.0
# Below this many prior transactions, a sender's own "average"/"std" isn't
# trustworthy enough to compare the current amount against.
MIN_HISTORY_FOR_AMOUNT_STATS = 3

BASE_FEATURES = [
    "amount",
    "log_amount",
    "hour_of_day",
    "day_of_week",
    "is_p2p",
]

BEHAVIORAL_FEATURES = [
    "sender_account_age_days",
    "receiver_account_age_days",
    "sender_txn_count_hist",
    "sender_amount_mean_hist",
    "sender_amount_std_hist",
    "amount_zscore_sender",
    "amount_to_sender_avg_ratio",
    "sender_txn_count_1h",
    "sender_txn_count_24h",
    "is_first_time_beneficiary",
    "sender_unique_receivers_hist",
    "receiver_unique_senders_hist",
    "receiver_unique_senders_1h",
    "receiver_txn_count_1h",
    "sender_inflow_total_hist",
    "sender_outflow_total_hist",
    "sender_inflow_outflow_ratio",
    "receiver_inflow_total_hist",
    "receiver_outflow_total_hist",
    "receiver_inflow_outflow_ratio",
    "minutes_since_sender_last_sent",
    "minutes_since_sender_last_received",
    "sender_distinct_devices_hist",
    "is_new_device_for_sender",
    "device_shared_account_count",
    "sender_is_merchant",
    "receiver_is_merchant",
]

FEATURE_COLUMNS = BASE_FEATURES + BEHAVIORAL_FEATURES

# Carried alongside the features for evaluation/analysis, never fed to a model.
METADATA_COLUMNS = ["txn_ref", "sender_upi_id", "receiver_upi_id", "created_at", "true_label", "scenario"]


@dataclass
class _AccountState:
    created_at: pd.Timestamp | None = None
    # As sender.
    sent_count: int = 0
    sent_sum: float = 0.0
    sent_sumsq: float = 0.0
    sent_receivers: set[str] = field(default_factory=set)
    sent_devices: set[str] = field(default_factory=set)
    last_sent_at: pd.Timestamp | None = None
    sent_window: deque = field(default_factory=deque)  # (ts, amount), pruned to 24h
    # As receiver.
    received_count: int = 0
    received_sum: float = 0.0
    received_senders: set[str] = field(default_factory=set)
    last_received_at: pd.Timestamp | None = None
    received_window: deque = field(default_factory=deque)  # (ts, sender_upi_id), pruned to 1h


def _prune(window: deque, cutoff: pd.Timestamp) -> None:
    while window and window[0][0] < cutoff:
        window.popleft()


def build_features(transactions: pd.DataFrame, accounts: pd.DataFrame) -> pd.DataFrame:
    """Return one row per transaction: `METADATA_COLUMNS` + `FEATURE_COLUMNS` + `is_fraud`.

    `transactions`/`accounts` are the raw Phase 2 synthetic-dataset frames
    (i.e. `pd.read_csv("ml/data/transactions.csv")` and `accounts.csv`).
    """
    account_created_at = dict(zip(accounts["upi_id"], pd.to_datetime(accounts["created_at"], utc=True)))
    account_is_merchant = dict(zip(accounts["upi_id"], accounts["account_type"] == "merchant"))

    txns = transactions.copy()
    txns["created_at"] = pd.to_datetime(txns["created_at"], utc=True)
    txns = txns.sort_values("created_at", kind="stable").reset_index(drop=True)

    states: dict[str, _AccountState] = {}
    # device_id -> set of sender upi_ids seen using it, for the shared-device signal.
    device_users: dict[str, set[str]] = {}

    def state_for(upi_id: str) -> _AccountState:
        state = states.get(upi_id)
        if state is None:
            state = _AccountState(created_at=account_created_at.get(upi_id))
            states[upi_id] = state
        return state

    rows: list[dict] = []

    for row in txns.itertuples(index=False):
        sender = row.sender_upi_id
        receiver = row.receiver_upi_id
        amount = float(row.amount)
        ts = row.created_at
        device_id = row.device_id

        s = state_for(sender)
        r = state_for(receiver)

        _prune(s.sent_window, ts - TWENTY_FOUR_HOURS)
        _prune(r.received_window, ts - ONE_HOUR)

        # --- base ---
        base = {
            "amount": amount,
            "log_amount": log1p(amount),
            "hour_of_day": ts.hour,
            "day_of_week": ts.dayofweek,
            "is_p2p": int(row.transaction_type == "P2P"),
        }

        # --- amount-vs-history ---
        has_amount_history = s.sent_count >= MIN_HISTORY_FOR_AMOUNT_STATS
        sender_amount_mean_hist = (s.sent_sum / s.sent_count) if s.sent_count else 0.0
        sender_amount_var_hist = (
            max(s.sent_sumsq / s.sent_count - sender_amount_mean_hist**2, 0.0) if s.sent_count else 0.0
        )
        sender_amount_std_hist = sqrt(sender_amount_var_hist)
        if has_amount_history and sender_amount_std_hist > 1e-9:
            amount_zscore_sender = (amount - sender_amount_mean_hist) / sender_amount_std_hist
        else:
            amount_zscore_sender = NO_HISTORY
        amount_to_sender_avg_ratio = (
            amount / sender_amount_mean_hist if has_amount_history and sender_amount_mean_hist > 1e-9 else NO_HISTORY
        )

        # --- velocity ---
        sender_txn_count_1h = sum(1 for t, _ in s.sent_window if t >= ts - ONE_HOUR)
        sender_txn_count_24h = len(s.sent_window)

        # --- beneficiary novelty / counterparty spread ---
        is_first_time_beneficiary = int(receiver not in s.sent_receivers)
        receiver_window_senders = {snd for _, snd in r.received_window}
        receiver_unique_senders_1h = len(receiver_window_senders | {sender})

        # --- inflow/outflow shape ---
        # +1 smoothing avoids a divide-by-zero when an account has never sent/received yet.
        sender_inflow_outflow_ratio = s.received_sum / (s.sent_sum + 1.0)
        receiver_inflow_outflow_ratio = r.received_sum / (r.sent_sum + 1.0)

        # --- recency / holding time ---
        minutes_since_sender_last_sent = (
            (ts - s.last_sent_at).total_seconds() / 60.0 if s.last_sent_at is not None else NO_HISTORY
        )
        minutes_since_sender_last_received = (
            (ts - s.last_received_at).total_seconds() / 60.0 if s.last_received_at is not None else NO_HISTORY
        )

        # --- device ---
        is_new_device_for_sender = int(device_id not in s.sent_devices)
        device_shared_account_count = len(device_users.get(device_id, ()))

        behavioral = {
            "sender_account_age_days": (
                (ts - s.created_at).total_seconds() / 86400.0 if s.created_at is not None else NO_HISTORY
            ),
            "receiver_account_age_days": (
                (ts - r.created_at).total_seconds() / 86400.0 if r.created_at is not None else NO_HISTORY
            ),
            "sender_txn_count_hist": s.sent_count,
            "sender_amount_mean_hist": sender_amount_mean_hist,
            "sender_amount_std_hist": sender_amount_std_hist,
            "amount_zscore_sender": amount_zscore_sender,
            "amount_to_sender_avg_ratio": amount_to_sender_avg_ratio,
            "sender_txn_count_1h": sender_txn_count_1h,
            "sender_txn_count_24h": sender_txn_count_24h,
            "is_first_time_beneficiary": is_first_time_beneficiary,
            "sender_unique_receivers_hist": len(s.sent_receivers),
            "receiver_unique_senders_hist": len(r.received_senders),
            "receiver_unique_senders_1h": receiver_unique_senders_1h,
            "receiver_txn_count_1h": len(r.received_window),
            "sender_inflow_total_hist": s.received_sum,
            "sender_outflow_total_hist": s.sent_sum,
            "sender_inflow_outflow_ratio": sender_inflow_outflow_ratio,
            "receiver_inflow_total_hist": r.received_sum,
            "receiver_outflow_total_hist": r.sent_sum,
            "receiver_inflow_outflow_ratio": receiver_inflow_outflow_ratio,
            "minutes_since_sender_last_sent": minutes_since_sender_last_sent,
            "minutes_since_sender_last_received": minutes_since_sender_last_received,
            "sender_distinct_devices_hist": len(s.sent_devices),
            "is_new_device_for_sender": is_new_device_for_sender,
            "device_shared_account_count": device_shared_account_count,
            "sender_is_merchant": int(account_is_merchant.get(sender, False)),
            "receiver_is_merchant": int(account_is_merchant.get(receiver, False)),
        }

        metadata = {
            "txn_ref": row.txn_ref,
            "sender_upi_id": sender,
            "receiver_upi_id": receiver,
            "created_at": ts,
            "true_label": row.true_label if isinstance(row.true_label, str) else None,
            "scenario": row.scenario if isinstance(row.scenario, str) else None,
        }
        is_fraud = int(isinstance(row.true_label, str) and row.true_label != "")

        rows.append({**metadata, **base, **behavioral, "is_fraud": is_fraud})

        # Update state AFTER computing this row's features -- never let a
        # transaction see itself in its own history.
        s.sent_count += 1
        s.sent_sum += amount
        s.sent_sumsq += amount * amount
        s.sent_receivers.add(receiver)
        s.sent_devices.add(device_id)
        s.last_sent_at = ts
        s.sent_window.append((ts, amount))

        r.received_count += 1
        r.received_sum += amount
        r.received_senders.add(sender)
        r.last_received_at = ts
        r.received_window.append((ts, sender))

        device_users.setdefault(device_id, set()).add(sender)

    return pd.DataFrame(rows, columns=METADATA_COLUMNS + FEATURE_COLUMNS + ["is_fraud"])
