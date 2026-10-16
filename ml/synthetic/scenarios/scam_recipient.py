"""Scam recipient: an account collects one-off payments from many unrelated
victims (fake marketplace listings, phishing links, impersonation scams), then
sweeps the proceeds onward to a downstream cashout account.

Most recipients are freshly opened shortly before the campaign, but a share
(`SCAM_AGED_RECIPIENT_RATE`) are bought, aged accounts -- so "brand-new
receiver" is a signal, not a giveaway. Every account exists before it
transacts.
"""

from datetime import timedelta

import numpy as np
import pandas as pd

from ml.synthetic.config import DATE_RANGE_DAYS, NUM_SCAM_RINGS, SCAM_AGED_RECIPIENT_RATE, SCAM_VICTIMS_RANGE
from ml.synthetic.helpers import new_account_row
from ml.synthetic.scenarios._util import (
    created_before,
    individuals_before,
    make_txn_row,
    pick_aged_account,
    random_base_timestamp,
    shortly_after,
)

SCENARIO = "scam_recipient"


def inject(rng: np.random.Generator, faker, accounts_df: pd.DataFrame, account_counter, txn_counter):
    new_accounts = []
    new_txns = []
    account_updates: dict[str, str] = {}
    taken: set[str] = set()

    device_lookup = accounts_df.set_index("upi_id")["device_id"]

    for _ in range(NUM_SCAM_RINGS):
        campaign_start = random_base_timestamp(rng, max_day_offset=DATE_RANGE_DAYS - 4)

        aged = pick_aged_account(rng, accounts_df, campaign_start, taken) if rng.random() < SCAM_AGED_RECIPIENT_RATE else None
        if aged is not None:
            recipient = aged
            account_updates[recipient["upi_id"]] = SCENARIO
        else:
            recipient = new_account_row(
                rng, faker, account_counter, created_before(rng, campaign_start, 1, 20), true_label=SCENARIO
            )
            new_accounts.append(recipient)
        cashout = new_account_row(rng, faker, account_counter, created_before(rng, campaign_start, 1, 30), true_label=SCENARIO)
        new_accounts.append(cashout)

        num_victims = int(rng.integers(SCAM_VICTIMS_RANGE[0], SCAM_VICTIMS_RANGE[1] + 1))
        victim_pool = [u for u in individuals_before(accounts_df, campaign_start) if u != recipient["upi_id"]]
        victim_upis = rng.choice(victim_pool, size=num_victims, replace=False)

        collected = 0.0
        last_ts = campaign_start
        for victim_upi in victim_upis:
            ts = campaign_start + timedelta(hours=float(rng.uniform(0, 72)), minutes=float(rng.integers(0, 60)))
            amount = float(np.clip(rng.lognormal(mean=8.5, sigma=0.6), 500, 50_000))
            new_txns.append(
                make_txn_row(
                    txn_counter,
                    victim_upi,
                    recipient["upi_id"],
                    amount,
                    device_id=device_lookup.get(victim_upi),
                    created_at=ts,
                    transaction_type="P2P",
                    true_label=SCENARIO,
                    scenario=SCENARIO,
                )
            )
            collected += amount
            last_ts = max(last_ts, ts)

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

    return pd.DataFrame(new_accounts), pd.DataFrame(new_txns), account_updates
