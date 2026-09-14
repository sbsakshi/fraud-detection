"""High-risk gambling network: a small set of betting-operator merchant
accounts receive frequent, repeated, mostly-late-night payments from a large
pool of bettor accounts. Individually each payment looks like an ordinary P2M
purchase; the fan-in frequency and the operator's category are the signal.
"""

from datetime import timedelta

import numpy as np
import pandas as pd

from ml.synthetic.config import (
    END_DATE,
    GAMBLING_BETS_RANGE,
    GAMBLING_BETTORS_RANGE,
    NUM_GAMBLING_OPERATORS,
)
from ml.synthetic.helpers import new_account_row
from ml.synthetic.scenarios._util import make_txn_row, random_base_timestamp

SCENARIO = "gambling_network"


def inject(rng: np.random.Generator, faker, accounts_df: pd.DataFrame, account_counter, txn_counter):
    new_accounts = []
    new_txns = []
    account_updates: dict[str, str] = {}

    device_lookup = accounts_df.set_index("upi_id")["device_id"]

    for _ in range(NUM_GAMBLING_OPERATORS):
        created_at = pd.Timestamp(END_DATE) - timedelta(days=int(rng.integers(60, 730)))
        operator = new_account_row(
            rng, faker, account_counter, created_at,
            account_type="merchant", true_label=SCENARIO, category="Gambling & Betting",
        )
        new_accounts.append(operator)

        candidates = accounts_df[
            (accounts_df["account_type"] == "individual") & accounts_df["true_label"].isna()
        ]["upi_id"].to_numpy()
        num_bettors = min(int(rng.integers(GAMBLING_BETTORS_RANGE[0], GAMBLING_BETTORS_RANGE[1] + 1)), len(candidates))
        bettors = rng.choice(candidates, size=num_bettors, replace=False)

        for bettor_upi in bettors:
            account_updates[bettor_upi] = SCENARIO
            num_bets = int(rng.integers(GAMBLING_BETS_RANGE[0], GAMBLING_BETS_RANGE[1] + 1))
            bettor_device = device_lookup.get(bettor_upi)
            for _ in range(num_bets):
                ts = random_base_timestamp(rng, hour_low=20, hour_high=27)
                amount = float(np.clip(rng.lognormal(mean=6.0, sigma=0.8), 50, 15_000))
                new_txns.append(
                    make_txn_row(
                        txn_counter,
                        bettor_upi,
                        operator["upi_id"],
                        amount,
                        device_id=bettor_device,
                        created_at=ts,
                        transaction_type="P2M",
                        true_label=SCENARIO,
                        scenario=SCENARIO,
                    )
                )

    new_accounts_df = pd.DataFrame(new_accounts)
    new_txns_df = pd.DataFrame(new_txns)
    return new_accounts_df, new_txns_df, account_updates
