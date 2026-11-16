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

Features are split into three tiers so the ablation study can show what each
one adds:

- `BASE_FEATURES` — raw transaction attributes only (amount, timing). A
  model trained on just these is the "ML alone" baseline.
- `BEHAVIORAL_FEATURES` — everything derived from account/device history
  (velocity, historical-average deviation, beneficiary novelty,
  inflow/outflow shape, device reuse). Adding these is the "ML + behavioural
  features" variant.

- `GRAPH_FEATURES` — short-window money-flow shape (3h fan-in/fan-out, whether
  a fan-in burst is an account's entire history, repeated payments between a
  pair, how much of recent inflow this payment sweeps onward). These are the
  patterns the backend's graph engine checks by rule, given to the model as
  numbers so it can weigh them against everything else.

`sender_is_merchant`/`receiver_is_merchant` exist because merchants
legitimately receive from many distinct customers -- a spot-check while
building this found `receiver_unique_senders_1h` averaging *higher* for
ordinary traffic than for `mule_network`, purely because merchant P2M fan-in
dwarfs a mule collector's. Without an account-type signal, a model has no
way to tell "popular merchant" apart from "mule collector" using fan-in
alone.

Missing history is `NaN` (`NO_HISTORY`), listed in `NULLABLE_FEATURES`:
continuous features that need prior activity to mean anything (an average,
a z-score, a "time since") have no honest value without it. An earlier
version used `-1`, which collided with real observations (a z-score of
exactly -1 is ordinary). XGBoost learns a default branch for missing values
natively; ml/train.py imputes them (with missing-indicator columns) only for
the Isolation Forest, which can't. Count/sum features have no such gap: zero
history genuinely means zero.

Graph-flavoured features computed in the same pass:
`receiver_unique_senders_24h`/`receiver_txn_count_24h` (fan-in burst over a
day, not just an hour), `*_minutes_since_first_seen` (how long an account has
been active in the payment graph -- unlike account age it doesn't depend on
a `created_at` the bank supplies), and `receiver_device_shared_account_count`
(the most accounts sharing any device the receiver has sent from -- a mule
herder running several accounts from one phone).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import timedelta
from math import log1p, sqrt

import pandas as pd

ONE_HOUR = timedelta(hours=1)
# Matches `GraphConfig.collector_window_hours` in the backend's graph engine: the
# mule_network scenario compresses its fan-in-then-sweep cycle into ~2.5 hours.
THREE_HOURS = timedelta(hours=3)
TWENTY_FOUR_HOURS = timedelta(hours=24)
NO_HISTORY = float("nan")
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
    "receiver_unique_senders_24h",
    "receiver_txn_count_24h",
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
    "receiver_device_shared_account_count",
    "sender_minutes_since_first_seen",
    "receiver_minutes_since_first_seen",
    "sender_is_merchant",
    "receiver_is_merchant",
]

# Money-flow shape over a short window: the signals the backend's graph engine
# looks for (mule collectors, repeated counterparties), given to the model as
# numbers instead of a separate rule score. Same no-peeking discipline as the
# rest: every value is computed from transactions strictly before this one.
GRAPH_FEATURES = [
    "sender_fan_in_3h",
    "sender_fan_in_is_fresh_burst",
    "receiver_fan_in_3h",
    "receiver_fan_in_is_fresh_burst",
    "receiver_fan_out_3h",
    "pair_txn_count_24h",
    "amount_to_sender_inflow_3h_ratio",
]

FEATURE_COLUMNS = BASE_FEATURES + BEHAVIORAL_FEATURES + GRAPH_FEATURES

# Features that are NaN when the history they summarize doesn't exist yet.
NULLABLE_FEATURES = [
    "amount_to_sender_inflow_3h_ratio",
    "sender_account_age_days",
    "receiver_account_age_days",
    "amount_zscore_sender",
    "amount_to_sender_avg_ratio",
    "minutes_since_sender_last_sent",
    "minutes_since_sender_last_received",
    "sender_minutes_since_first_seen",
    "receiver_minutes_since_first_seen",
]

# Carried alongside the features for evaluation/analysis, never fed to a model.
METADATA_COLUMNS = ["txn_ref", "sender_upi_id", "receiver_upi_id", "created_at", "true_label", "scenario"]


@dataclass
class _AccountState:
    created_at: pd.Timestamp | None = None
    first_seen_at: pd.Timestamp | None = None
    # As sender.
    sent_count: int = 0
    sent_sum: float = 0.0
    sent_sumsq: float = 0.0
    sent_receivers: set[str] = field(default_factory=set)
    sent_devices: set[str] = field(default_factory=set)
    last_sent_at: pd.Timestamp | None = None
    sent_window: deque = field(default_factory=deque)  # (ts, amount), pruned to 24h
    sent_to_window: deque = field(default_factory=deque)  # (ts, receiver_upi_id), pruned to 24h
    # As receiver.
    received_count: int = 0
    received_sum: float = 0.0
    received_senders: set[str] = field(default_factory=set)
    last_received_at: pd.Timestamp | None = None
    received_window: deque = field(default_factory=deque)  # (ts, sender_upi_id), pruned to 24h
    received_amount_window: deque = field(default_factory=deque)  # (ts, amount), pruned to 24h


def _minutes_since(ts: pd.Timestamp, earlier: pd.Timestamp | None) -> float:
    return (ts - earlier).total_seconds() / 60.0 if earlier is not None else NO_HISTORY


def _prune(window: deque, cutoff: pd.Timestamp) -> None:
    while window and window[0][0] < cutoff:
        window.popleft()


def build_features(transactions: pd.DataFrame, accounts: pd.DataFrame) -> pd.DataFrame:
    """Return one row per transaction: `METADATA_COLUMNS` + `FEATURE_COLUMNS` + `is_fraud`.

    `transactions`/`accounts` are the raw Phase 2 synthetic-dataset frames
    (i.e. `pd.read_csv("ml/data/transactions.csv")` and `accounts.csv`).
    """
    account_created_at = dict(zip(accounts["upi_id"], pd.to_datetime(accounts["created_at"], utc=True, format="ISO8601")))
    account_is_merchant = dict(zip(accounts["upi_id"], accounts["account_type"] == "merchant"))

    txns = transactions.copy()
    txns["created_at"] = pd.to_datetime(txns["created_at"], utc=True, format="ISO8601")
    txns = txns.sort_values("created_at", kind="stable").reset_index(drop=True)

    states: dict[str, _AccountState] = {}
    # device_id -> set of sender upi_ids seen using it, for the shared-device signal.
    device_users: dict[str, set[str]] = {}
    # (sender, receiver) -> timestamps of their payments in the last 24h.
    pair_window: dict[tuple[str, str], deque] = {}

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
        _prune(r.received_window, ts - TWENTY_FOUR_HOURS)
        _prune(s.sent_to_window, ts - TWENTY_FOUR_HOURS)
        _prune(s.received_window, ts - TWENTY_FOUR_HOURS)
        _prune(s.received_amount_window, ts - TWENTY_FOUR_HOURS)
        _prune(r.sent_to_window, ts - TWENTY_FOUR_HOURS)
        pair = pair_window.setdefault((sender, receiver), deque())
        while pair and pair[0] < ts - TWENTY_FOUR_HOURS:
            pair.popleft()

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
        hour_ago = ts - ONE_HOUR
        receiver_senders_1h = {snd for t, snd in r.received_window if t >= hour_ago}
        receiver_unique_senders_1h = len(receiver_senders_1h | {sender})
        receiver_txn_count_1h = sum(1 for t, _ in r.received_window if t >= hour_ago)
        receiver_unique_senders_24h = len({snd for _, snd in r.received_window} | {sender})

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
        receiver_device_shared_account_count = max(
            (len(device_users.get(d, ())) for d in r.sent_devices), default=0
        )

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
            "receiver_txn_count_1h": receiver_txn_count_1h,
            "receiver_unique_senders_24h": receiver_unique_senders_24h,
            "receiver_txn_count_24h": len(r.received_window),
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
            "receiver_device_shared_account_count": receiver_device_shared_account_count,
            "sender_minutes_since_first_seen": _minutes_since(ts, s.first_seen_at),
            "receiver_minutes_since_first_seen": _minutes_since(ts, r.first_seen_at),
            "sender_is_merchant": int(account_is_merchant.get(sender, False)),
            "receiver_is_merchant": int(account_is_merchant.get(receiver, False)),
        }

        # --- graph: short-window money-flow shape ---
        three_hours_ago = ts - THREE_HOURS
        sender_fan_in_3h = len({snd for t, snd in s.received_window if t >= three_hours_ago})
        receiver_fan_in_3h = len({snd for t, snd in r.received_window if t >= three_hours_ago} | {sender})
        # "Fresh burst": the windowed fan-in is the account's *entire* inbound history,
        # which separates a just-opened collector from an established, busy hub.
        sender_inflow_3h = sum(a for t, a in s.received_amount_window if t >= three_hours_ago)
        graph = {
            "sender_fan_in_3h": sender_fan_in_3h,
            "sender_fan_in_is_fresh_burst": int(sender_fan_in_3h > 0 and sender_fan_in_3h == len(s.received_senders)),
            "receiver_fan_in_3h": receiver_fan_in_3h,
            "receiver_fan_in_is_fresh_burst": int(receiver_fan_in_3h == len(r.received_senders | {sender})),
            "receiver_fan_out_3h": len({rcv for t, rcv in r.sent_to_window if t >= three_hours_ago}),
            "pair_txn_count_24h": len(pair),
            "amount_to_sender_inflow_3h_ratio": amount / sender_inflow_3h if sender_inflow_3h > 1e-9 else NO_HISTORY,
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

        rows.append({**metadata, **base, **behavioral, **graph, "is_fraud": is_fraud})

        # Update state AFTER computing this row's features -- never let a
        # transaction see itself in its own history.
        if s.first_seen_at is None:
            s.first_seen_at = ts
        if r.first_seen_at is None:
            r.first_seen_at = ts
        s.sent_count += 1
        s.sent_sum += amount
        s.sent_sumsq += amount * amount
        s.sent_receivers.add(receiver)
        s.sent_devices.add(device_id)
        s.last_sent_at = ts
        s.sent_window.append((ts, amount))
        s.sent_to_window.append((ts, receiver))
        pair.append(ts)

        r.received_count += 1
        r.received_sum += amount
        r.received_senders.add(sender)
        r.last_received_at = ts
        r.received_window.append((ts, sender))
        r.received_amount_window.append((ts, amount))

        device_users.setdefault(device_id, set()).add(sender)

    return pd.DataFrame(rows, columns=METADATA_COLUMNS + FEATURE_COLUMNS + ["is_fraud"])
