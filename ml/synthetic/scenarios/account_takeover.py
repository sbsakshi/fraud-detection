"""Account takeover: an established account (real transaction history) is
compromised. The attacker transacts from a device the account has never used
before, off-hours, draining a sum far above the account's normal payment
size to a brand-new beneficiary it has never paid.
"""

from datetime import timedelta

import numpy as np
import pandas as pd

from ml.synthetic.config import ACCOUNT_TAKEOVER_DRAIN_RANGE, END_DATE, NUM_ACCOUNT_TAKEOVERS
from ml.synthetic.helpers import new_account_row, new_device_id
from ml.synthetic.scenarios._util import late_night_timestamp, make_txn_row, shortly_after

SCENARIO = "account_takeover"


def inject(rng: np.random.Generator, faker, accounts_df: pd.DataFrame, account_counter, txn_counter):
    new_accounts = []
    new_txns = []
    account_updates: dict[str, str] = {}

    cutoff = pd.Timestamp(END_DATE) - timedelta(days=90)
    candidates = accounts_df[
        (accounts_df["account_type"] == "individual")
        & accounts_df["true_label"].isna()
        & (accounts_df["created_at"] < cutoff)
    ]["upi_id"].to_numpy()

    num_takeovers = min(NUM_ACCOUNT_TAKEOVERS, len(candidates))
    victims = rng.choice(candidates, size=num_takeovers, replace=False)

    for victim_upi in victims:
        account_updates[victim_upi] = SCENARIO

        receiver_created_at = pd.Timestamp(END_DATE) - timedelta(days=int(rng.integers(0, 5)))
        receiver = new_account_row(rng, faker, account_counter, receiver_created_at, true_label=SCENARIO)
        new_accounts.append(receiver)

        takeover_device = new_device_id(rng)
        ts = late_night_timestamp(rng, days_before_end=10)
        num_drains = int(rng.integers(ACCOUNT_TAKEOVER_DRAIN_RANGE[0], ACCOUNT_TAKEOVER_DRAIN_RANGE[1] + 1))
        total = float(np.clip(rng.lognormal(mean=10.0, sigma=0.5), 20_000, 150_000))

        for i in range(num_drains):
            share = total / num_drains * float(rng.uniform(0.8, 1.2))
            new_txns.append(
                make_txn_row(
                    txn_counter,
                    victim_upi,
                    receiver["upi_id"],
                    share,
                    device_id=takeover_device,
                    created_at=ts,
                    transaction_type="P2P",
                    true_label=SCENARIO,
                    scenario=SCENARIO,
                )
            )
            ts = shortly_after(rng, ts, min_seconds=60, max_seconds=600)

    new_accounts_df = pd.DataFrame(new_accounts)
    new_txns_df = pd.DataFrame(new_txns)
    return new_accounts_df, new_txns_df, account_updates
