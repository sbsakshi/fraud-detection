"""Legitimate look-alikes: unlabelled traffic that shares surface features with
the fraud scenarios, so a model can't get away with one-feature rules like
"large amount to a new payee is fraud" or "many senders in a few hours is a
mule collector".

Rows carry `true_label=None` (not fraud) and a `scenario` tag, so evaluation
can report a false-positive rate on each of them (see ml/train.py).

- `large_new_payee`: an established account makes a one-off large payment to
  someone it has never paid (rent deposit, a used car), occasionally from a
  new device (a new phone). Shares amount-jump + first-time-beneficiary (+
  sometimes new-device) with account_takeover.
- `group_collection`: one person collects from 8-20 friends within a few
  hours (trip, gift pool), then often pays a merchant onward. Shares fan-in
  burst + sweep with mule_network / scam_recipient.
"""

from datetime import timedelta

import numpy as np
import pandas as pd

from ml.synthetic.base_traffic import TOTAL_DAYS, sample_hours
from ml.synthetic.config import (
    GROUP_COLLECTION_SIZE_RANGE,
    HISTORY_START,
    LARGE_NEW_PAYEE_NEW_DEVICE_RATE,
    NUM_GROUP_COLLECTIONS,
    NUM_LARGE_NEW_PAYEE,
)
from ml.synthetic.helpers import new_device_id
from ml.synthetic.scenarios._util import individuals_before, make_txn_row, shortly_after

# Last moment of the data window (END_DATE is inclusive).
DATA_END = pd.Timestamp(HISTORY_START) + timedelta(days=TOTAL_DAYS, hours=23, minutes=59)

LARGE_NEW_PAYEE = "large_new_payee"
GROUP_COLLECTION = "group_collection"


def _random_ts(rng, earliest: pd.Timestamp) -> pd.Timestamp:
    start = max(pd.Timestamp(HISTORY_START), pd.Timestamp(earliest).normalize() + timedelta(days=1))
    span = max(0, (pd.Timestamp(HISTORY_START) + timedelta(days=TOTAL_DAYS) - start).days)
    day = start + timedelta(days=int(rng.integers(0, span + 1)))
    return day + timedelta(hours=int(sample_hours(rng, 1)[0]), minutes=int(rng.integers(0, 60)))


def generate(rng: np.random.Generator, accounts_df: pd.DataFrame, txn_counter) -> pd.DataFrame:
    rows = []
    device_lookup = accounts_df.set_index("upi_id")["device_id"]
    created_lookup = pd.to_datetime(accounts_df.set_index("upi_id")["created_at"])
    normal = accounts_df[accounts_df["true_label"].isna()]
    individuals = normal.loc[normal["account_type"] == "individual", "upi_id"].to_numpy()
    merchants = normal.loc[normal["account_type"] == "merchant", "upi_id"].to_numpy()
    everyone = normal["upi_id"].to_numpy()
    merchant_set = set(merchants)

    for _ in range(NUM_LARGE_NEW_PAYEE):
        sender = individuals[int(rng.integers(0, len(individuals)))]
        receiver = everyone[int(rng.integers(0, len(everyone)))]
        if receiver == sender:
            continue
        ts = _random_ts(rng, max(created_lookup[sender], created_lookup[receiver]))
        device = new_device_id(rng) if rng.random() < LARGE_NEW_PAYEE_NEW_DEVICE_RATE else device_lookup[sender]
        amount = float(np.clip(rng.lognormal(mean=9.8, sigma=0.6), 15_000, 200_000))
        rows.append(
            make_txn_row(
                txn_counter, sender, receiver, amount, device_id=device, created_at=ts,
                transaction_type="P2M" if receiver in merchant_set else "P2P", scenario=LARGE_NEW_PAYEE,
            )
        )

    for _ in range(NUM_GROUP_COLLECTIONS):
        collector = individuals[int(rng.integers(0, len(individuals)))]
        start = _random_ts(rng, created_lookup[collector])
        size = int(rng.integers(GROUP_COLLECTION_SIZE_RANGE[0], GROUP_COLLECTION_SIZE_RANGE[1] + 1))
        friends = [u for u in individuals_before(normal, start) if u != collector]
        friends = rng.choice(friends, size=min(size, len(friends)), replace=False)
        share = float(np.clip(rng.lognormal(mean=7.2, sigma=0.4), 300, 10_000))
        collected, last_ts = 0.0, start
        for friend in friends:
            ts = start + timedelta(seconds=int(rng.integers(0, 3 * 3600)))
            amount = round(share * float(rng.uniform(0.9, 1.1)), -1)
            rows.append(
                make_txn_row(
                    txn_counter, friend, collector, amount, device_id=device_lookup[friend], created_at=ts,
                    scenario=GROUP_COLLECTION,
                )
            )
            collected += amount
            last_ts = max(last_ts, ts)
        pay_ts = min(shortly_after(rng, last_ts, min_seconds=1800, max_seconds=4 * 86400), DATA_END)
        venues = [m for m in merchants if created_lookup[m] < pay_ts]
        if rng.random() < 0.6 and venues and pay_ts > last_ts:
            venue = venues[int(rng.integers(0, len(venues)))]
            rows.append(
                make_txn_row(
                    txn_counter, collector, venue, collected * float(rng.uniform(0.85, 1.0)),
                    device_id=device_lookup[collector], created_at=pay_ts,
                    transaction_type="P2M", scenario=GROUP_COLLECTION,
                )
            )

    return pd.DataFrame(rows)
