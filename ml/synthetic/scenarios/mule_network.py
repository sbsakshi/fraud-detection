"""Mule network: many compromised/recruited source accounts fan money in to a
small set of collector accounts within a tight window, which then fan it out
to one or two cashout accounts. Speed and fan-in/fan-out breadth (rather than
chain depth) is what obscures the trail. A couple of collectors in each ring
share a device, modelling one mule herder operating several accounts.
"""

from datetime import timedelta

import numpy as np
import pandas as pd

from ml.synthetic.config import (
    DATE_RANGE_DAYS,
    END_DATE,
    MULE_CASHOUTS_RANGE,
    MULE_COLLECTORS_RANGE,
    MULE_FANIN_RANGE,
    NUM_MULE_RINGS,
)
from ml.synthetic.helpers import new_account_row
from ml.synthetic.scenarios._util import make_txn_row, random_base_timestamp, shortly_after

SCENARIO = "mule_network"


def inject(rng: np.random.Generator, faker, accounts_df: pd.DataFrame, account_counter, txn_counter):
    new_accounts = []
    new_txns = []

    individual_upis = accounts_df.loc[accounts_df["account_type"] == "individual", "upi_id"].to_numpy()

    for _ in range(NUM_MULE_RINGS):
        created_at = pd.Timestamp(END_DATE) - timedelta(days=int(rng.integers(5, 60)))
        num_collectors = int(rng.integers(MULE_COLLECTORS_RANGE[0], MULE_COLLECTORS_RANGE[1] + 1))
        num_cashouts = int(rng.integers(MULE_CASHOUTS_RANGE[0], MULE_CASHOUTS_RANGE[1] + 1))

        collectors = [new_account_row(rng, faker, account_counter, created_at, true_label=SCENARIO) for _ in range(num_collectors)]
        # Two of the collectors (or one, if the ring is small) share a device: one
        # mule herder running several accounts off a single phone.
        shared_device = collectors[0]["device_id"]
        for c in collectors[: min(2, num_collectors)]:
            c["device_id"] = shared_device
        cashouts = [new_account_row(rng, faker, account_counter, created_at, true_label=SCENARIO) for _ in range(num_cashouts)]
        new_accounts.extend(collectors + cashouts)

        # Small buffer so the fan-in window plus sweep delays can't spill past END_DATE.
        window_start = random_base_timestamp(rng, hour_low=8, hour_high=22, max_day_offset=DATE_RANGE_DAYS - 1)
        num_fanin = int(rng.integers(MULE_FANIN_RANGE[0], MULE_FANIN_RANGE[1] + 1))
        sender_upis = rng.choice(individual_upis, size=num_fanin, replace=False)

        collector_totals = {c["upi_id"]: 0.0 for c in collectors}
        collector_last_ts = {c["upi_id"]: window_start for c in collectors}
        device_lookup_partial = accounts_df.set_index("upi_id")["device_id"]

        for sender_upi in sender_upis:
            collector = collectors[int(rng.integers(0, num_collectors))]
            ts = window_start + timedelta(seconds=int(rng.integers(0, 7200)))
            amount = float(np.clip(rng.lognormal(mean=7.5, sigma=0.7), 200, 20_000))
            sender_device = device_lookup_partial.get(sender_upi)
            new_txns.append(
                make_txn_row(
                    txn_counter,
                    sender_upi,
                    collector["upi_id"],
                    amount,
                    device_id=sender_device,
                    created_at=ts,
                    transaction_type="P2P",
                    true_label=SCENARIO,
                    scenario=SCENARIO,
                )
            )
            collector_totals[collector["upi_id"]] += amount
            collector_last_ts[collector["upi_id"]] = max(collector_last_ts[collector["upi_id"]], ts)

        # Each collector sweeps ~95% of what it received onward to a cashout
        # account shortly after its last incoming payment.
        for c in collectors:
            total = collector_totals[c["upi_id"]]
            if total <= 0:
                continue
            cashout = cashouts[int(rng.integers(0, num_cashouts))]
            sweep_ts = shortly_after(rng, collector_last_ts[c["upi_id"]], min_seconds=120, max_seconds=1800)
            new_txns.append(
                make_txn_row(
                    txn_counter,
                    c["upi_id"],
                    cashout["upi_id"],
                    total * float(rng.uniform(0.90, 0.97)),
                    device_id=c["device_id"],
                    created_at=sweep_ts,
                    transaction_type="P2P",
                    true_label=SCENARIO,
                    scenario=SCENARIO,
                )
            )

    new_accounts_df = pd.DataFrame(new_accounts)
    new_txns_df = pd.DataFrame(new_txns)
    return new_accounts_df, new_txns_df, {}
