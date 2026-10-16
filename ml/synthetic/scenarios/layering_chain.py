"""Layering chain: a single lump sum moves through a sequence of accounts, hop
by hop in quick succession, shedding a small "fee" at each step -- classic AML
layering, where obfuscation comes from chain depth rather than fan-in/fan-out
breadth (contrast with mule_network).

Most hops are freshly opened accounts; a share (`LAYERING_AGED_HOP_RATE`) are
aged, recruited ones, so a chain doesn't look uniformly brand-new.
"""

import numpy as np
import pandas as pd

from ml.synthetic.config import DATE_RANGE_DAYS, LAYERING_AGED_HOP_RATE, LAYERING_CHAIN_LENGTH_RANGE, NUM_LAYERING_CHAINS
from ml.synthetic.helpers import new_account_row
from ml.synthetic.scenarios._util import (
    created_before,
    individuals_before,
    make_txn_row,
    pick_aged_account,
    random_base_timestamp,
    shortly_after,
)

SCENARIO = "layering_chain"


def inject(rng: np.random.Generator, faker, accounts_df: pd.DataFrame, account_counter, txn_counter):
    new_accounts = []
    new_txns = []
    account_updates: dict[str, str] = {}
    taken: set[str] = set()

    device_lookup = accounts_df.set_index("upi_id")["device_id"]

    for _ in range(NUM_LAYERING_CHAINS):
        ts = random_base_timestamp(rng, max_day_offset=DATE_RANGE_DAYS - 1)
        chain_length = int(rng.integers(LAYERING_CHAIN_LENGTH_RANGE[0], LAYERING_CHAIN_LENGTH_RANGE[1] + 1))

        chain = []
        for _ in range(chain_length):
            aged = pick_aged_account(rng, accounts_df, ts, taken) if rng.random() < LAYERING_AGED_HOP_RATE else None
            if aged is not None:
                account_updates[aged["upi_id"]] = SCENARIO
                chain.append(aged)
            else:
                row = new_account_row(rng, faker, account_counter, created_before(rng, ts, 1, 30), true_label=SCENARIO)
                new_accounts.append(row)
                chain.append(row)

        chain_upis = {c["upi_id"] for c in chain}
        source_pool = [u for u in individuals_before(accounts_df, ts) if u not in chain_upis]
        source_upi = source_pool[int(rng.integers(0, len(source_pool)))]
        starting_amount = float(np.clip(rng.lognormal(mean=9.0, sigma=0.5), 5_000, 100_000))

        new_txns.append(
            make_txn_row(
                txn_counter,
                source_upi,
                chain[0]["upi_id"],
                starting_amount,
                device_id=device_lookup.get(source_upi),
                created_at=ts,
                transaction_type="P2P",
                true_label=SCENARIO,
                scenario=SCENARIO,
            )
        )

        current_amount = starting_amount
        for i in range(chain_length - 1):
            ts = shortly_after(rng, ts, min_seconds=60, max_seconds=900)
            fee_rate = float(rng.uniform(0.02, 0.08))
            new_txns.append(
                make_txn_row(
                    txn_counter,
                    chain[i]["upi_id"],
                    chain[i + 1]["upi_id"],
                    current_amount,
                    device_id=chain[i]["device_id"],
                    created_at=ts,
                    transaction_type="P2P",
                    true_label=SCENARIO,
                    scenario=SCENARIO,
                )
            )
            current_amount *= 1 - fee_rate

    return pd.DataFrame(new_accounts), pd.DataFrame(new_txns), account_updates
