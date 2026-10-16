"""Account takeover: an established account (real transaction history) is
compromised. The attacker transacts from a device the account has never used
before, draining a sum far above the account's normal payment size to a
beneficiary it has never paid.

Takeovers are spread across the whole scenario window (skewed toward, but not
limited to, the small hours -- `ACCOUNT_TAKEOVER_NIGHT_RATE`), and half the
beneficiaries are aged, recruited accounts rather than freshly opened ones.
"""

import numpy as np
import pandas as pd

from ml.synthetic.config import (
    ACCOUNT_TAKEOVER_AGED_RECEIVER_RATE,
    ACCOUNT_TAKEOVER_DRAIN_RANGE,
    ACCOUNT_TAKEOVER_NIGHT_RATE,
    NUM_ACCOUNT_TAKEOVERS,
)
from ml.synthetic.helpers import new_account_row, new_device_id
from ml.synthetic.scenarios._util import (
    account_takeover_timestamp,
    created_before,
    individuals_before,
    make_txn_row,
    pick_aged_account,
    shortly_after,
)

SCENARIO = "account_takeover"


def inject(rng: np.random.Generator, faker, accounts_df: pd.DataFrame, account_counter, txn_counter):
    new_accounts = []
    new_txns = []
    account_updates: dict[str, str] = {}
    taken: set[str] = set()

    for _ in range(NUM_ACCOUNT_TAKEOVERS):
        ts = account_takeover_timestamp(rng, ACCOUNT_TAKEOVER_NIGHT_RATE)

        # Victim: an established account, at least 90 days old when it's taken over.
        victims = [u for u in individuals_before(accounts_df, ts - pd.Timedelta(days=90), unlabelled=True) if u not in taken]
        if not victims:
            break
        victim_upi = victims[int(rng.integers(0, len(victims)))]
        taken.add(victim_upi)
        account_updates[victim_upi] = SCENARIO

        receiver = (
            pick_aged_account(rng, accounts_df, ts, taken) if rng.random() < ACCOUNT_TAKEOVER_AGED_RECEIVER_RATE else None
        )
        if receiver is not None:
            account_updates[receiver["upi_id"]] = SCENARIO
        else:
            receiver = new_account_row(rng, faker, account_counter, created_before(rng, ts, 0, 5), true_label=SCENARIO)
            new_accounts.append(receiver)

        takeover_device = new_device_id(rng)
        num_drains = int(rng.integers(ACCOUNT_TAKEOVER_DRAIN_RANGE[0], ACCOUNT_TAKEOVER_DRAIN_RANGE[1] + 1))
        total = float(np.clip(rng.lognormal(mean=10.0, sigma=0.5), 20_000, 150_000))

        for _ in range(num_drains):
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

    return pd.DataFrame(new_accounts), pd.DataFrame(new_txns), account_updates
