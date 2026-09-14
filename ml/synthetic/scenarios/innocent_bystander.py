"""Innocent bystander: an ordinary, otherwise-uninvolved account has one
perfectly normal transaction with an account that happens to carry a fraud
label elsewhere in the graph (sold something secondhand to someone who turns
out to run a scam, split a bill with a since-compromised friend, ...). The
transaction itself is not fraudulent — this scenario exists to test that
network-exposure alone doesn't get an innocent account flagged.

Must run after the other labelled scenarios so there is a pool of fraud
accounts to be adjacent to.
"""

import numpy as np
import pandas as pd

from ml.synthetic.config import NUM_INNOCENT_BYSTANDERS
from ml.synthetic.scenarios._util import make_txn_row, random_base_timestamp

SCENARIO = "innocent_bystander"


def inject(rng: np.random.Generator, accounts_df: pd.DataFrame, fraud_pool_upis, txn_counter):
    new_txns = []
    account_updates: dict[str, str] = {}

    candidates = accounts_df[
        (accounts_df["account_type"] == "individual") & accounts_df["true_label"].isna()
    ]["upi_id"].to_numpy()
    num_bystanders = min(NUM_INNOCENT_BYSTANDERS, len(candidates), len(fraud_pool_upis))
    bystanders = rng.choice(candidates, size=num_bystanders, replace=False)
    counterparties = rng.choice(fraud_pool_upis, size=num_bystanders, replace=True)

    device_lookup = accounts_df.set_index("upi_id")["device_id"]

    for bystander_upi, fraud_upi in zip(bystanders, counterparties):
        account_updates[bystander_upi] = SCENARIO
        ts = random_base_timestamp(rng)
        amount = float(np.clip(rng.lognormal(mean=5.9, sigma=1.0), 10, 20_000))
        bystander_pays = rng.random() < 0.5
        sender, receiver = (bystander_upi, fraud_upi) if bystander_pays else (fraud_upi, bystander_upi)
        device_id = device_lookup.get(sender)
        new_txns.append(
            make_txn_row(
                txn_counter,
                sender,
                receiver,
                amount,
                device_id=device_id,
                created_at=ts,
                transaction_type="P2P",
                true_label=None,
                scenario=SCENARIO,
            )
        )

    new_txns_df = pd.DataFrame(new_txns)
    return new_txns_df, account_updates
