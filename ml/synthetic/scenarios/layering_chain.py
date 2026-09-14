"""Layering chain: a single lump sum moves through a sequence of freshly-created
accounts, hop by hop in quick succession, shedding a small "fee" at each step —
classic AML layering, where obfuscation comes from chain depth rather than
fan-in/fan-out breadth (contrast with mule_network).
"""

from datetime import timedelta

import numpy as np
import pandas as pd

from ml.synthetic.config import DATE_RANGE_DAYS, END_DATE, LAYERING_CHAIN_LENGTH_RANGE, NUM_LAYERING_CHAINS
from ml.synthetic.helpers import new_account_row
from ml.synthetic.scenarios._util import make_txn_row, random_base_timestamp, shortly_after

SCENARIO = "layering_chain"


def inject(rng: np.random.Generator, faker, accounts_df: pd.DataFrame, account_counter, txn_counter):
    new_accounts = []
    new_txns = []

    individual_upis = accounts_df.loc[accounts_df["account_type"] == "individual", "upi_id"].to_numpy()
    device_lookup = accounts_df.set_index("upi_id")["device_id"]

    for _ in range(NUM_LAYERING_CHAINS):
        created_at = pd.Timestamp(END_DATE) - timedelta(days=int(rng.integers(1, 45)))
        chain_length = int(rng.integers(LAYERING_CHAIN_LENGTH_RANGE[0], LAYERING_CHAIN_LENGTH_RANGE[1] + 1))
        chain = [new_account_row(rng, faker, account_counter, created_at, true_label=SCENARIO) for _ in range(chain_length)]
        new_accounts.extend(chain)

        starting_amount = float(np.clip(rng.lognormal(mean=9.0, sigma=0.5), 5_000, 100_000))
        source_upi = rng.choice(individual_upis)

        # Small buffer so the chain's hop-by-hop delays can't spill past END_DATE.
        ts = random_base_timestamp(rng, max_day_offset=DATE_RANGE_DAYS - 1)
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

    new_accounts_df = pd.DataFrame(new_accounts)
    new_txns_df = pd.DataFrame(new_txns)
    return new_accounts_df, new_txns_df, {}
