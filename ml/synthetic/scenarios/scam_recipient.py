"""Scam recipient: a freshly-created account collects one-off payments from many
unrelated victims (fake marketplace listings, phishing links, impersonation
scams), then sweeps the proceeds onward to a downstream cashout account.
"""

from datetime import timedelta

import numpy as np
import pandas as pd

from ml.synthetic.config import DATE_RANGE_DAYS, END_DATE, NUM_SCAM_RINGS, SCAM_VICTIMS_RANGE
from ml.synthetic.helpers import new_account_row
from ml.synthetic.scenarios._util import make_txn_row, random_base_timestamp, shortly_after

SCENARIO = "scam_recipient"


def inject(rng: np.random.Generator, faker, accounts_df: pd.DataFrame, account_counter, txn_counter):
    new_accounts = []
    new_txns = []

    individual_upis = accounts_df.loc[accounts_df["account_type"] == "individual", "upi_id"].to_numpy()

    for _ in range(NUM_SCAM_RINGS):
        # Scam-collection accounts are typically opened a few days before the
        # campaign runs, not established accounts with history.
        created_at = pd.Timestamp(END_DATE) - timedelta(days=int(rng.integers(3, 20)))
        recipient = new_account_row(rng, faker, account_counter, created_at, true_label=SCENARIO)
        cashout = new_account_row(rng, faker, account_counter, created_at, true_label=SCENARIO)
        new_accounts.extend([recipient, cashout])

        num_victims = int(rng.integers(SCAM_VICTIMS_RANGE[0], SCAM_VICTIMS_RANGE[1] + 1))
        victim_upis = rng.choice(individual_upis, size=num_victims, replace=False)

        # Leave a buffer for the 72h victim spread plus sweep delays that follow,
        # so campaign activity can't spill past the dataset's END_DATE.
        campaign_start = random_base_timestamp(rng, max_day_offset=DATE_RANGE_DAYS - 4)
        collected = 0.0
        last_ts = campaign_start
        for victim_upi in victim_upis:
            ts = campaign_start + timedelta(
                hours=float(rng.uniform(0, 72)), minutes=float(rng.integers(0, 60))
            )
            amount = float(np.clip(rng.lognormal(mean=8.5, sigma=0.6), 500, 50_000))
            new_txns.append(
                make_txn_row(
                    txn_counter,
                    victim_upi,
                    recipient["upi_id"],
                    amount,
                    device_id=None,  # filled in below once we know the victim's own device
                    created_at=ts,
                    transaction_type="P2P",
                    true_label=SCENARIO,
                    scenario=SCENARIO,
                )
            )
            collected += amount
            last_ts = max(last_ts, ts)

        # Sweep the collected funds onward in 1-3 large transfers shortly after
        # the bulk of the money has landed.
        num_sweeps = int(rng.integers(1, 4))
        remaining = collected
        sweep_ts = shortly_after(rng, last_ts, min_seconds=600, max_seconds=7200)
        for i in range(num_sweeps):
            share = remaining if i == num_sweeps - 1 else remaining * float(rng.uniform(0.3, 0.6))
            remaining -= share
            new_txns.append(
                make_txn_row(
                    txn_counter,
                    recipient["upi_id"],
                    cashout["upi_id"],
                    share,
                    device_id=recipient["device_id"],
                    created_at=sweep_ts,
                    transaction_type="P2P",
                    true_label=SCENARIO,
                    scenario=SCENARIO,
                )
            )
            sweep_ts = shortly_after(rng, sweep_ts, min_seconds=60, max_seconds=900)

    new_accounts_df = pd.DataFrame(new_accounts)
    new_txns_df = pd.DataFrame(new_txns)

    # Fill victim-side device_id from the accounts table now that both frames exist.
    device_lookup = accounts_df.set_index("upi_id")["device_id"]
    missing = new_txns_df["device_id"].isna()
    new_txns_df.loc[missing, "device_id"] = new_txns_df.loc[missing, "sender_upi_id"].map(device_lookup)

    return new_accounts_df, new_txns_df, {}
