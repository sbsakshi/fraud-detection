"""Mule network: many source accounts fan money in to a small set of collector
accounts within a tight window, which then fan it out to one or two cashout
accounts. Speed and fan-in/fan-out breadth (rather than chain depth) is what
obscures the trail.

About half the collectors (`MULE_RECRUITED_COLLECTOR_RATE`) are recruited,
established account holders rather than fresh accounts. One mule herder runs
each ring: the fresh collectors are registered on the herder's device, and the
recruited collectors' sweeps are made from it too.
"""

from datetime import timedelta

import numpy as np
import pandas as pd

from ml.synthetic.config import (
    DATE_RANGE_DAYS,
    MULE_CASHOUTS_RANGE,
    MULE_COLLECTORS_RANGE,
    MULE_FANIN_RANGE,
    MULE_RECRUITED_COLLECTOR_RATE,
    NUM_MULE_RINGS,
)
from ml.synthetic.helpers import new_account_row, new_device_id
from ml.synthetic.scenarios._util import (
    created_before,
    individuals_before,
    make_txn_row,
    pick_aged_account,
    random_base_timestamp,
    shortly_after,
)

SCENARIO = "mule_network"


def inject(rng: np.random.Generator, faker, accounts_df: pd.DataFrame, account_counter, txn_counter):
    new_accounts = []
    new_txns = []
    account_updates: dict[str, str] = {}
    taken: set[str] = set()

    device_lookup = accounts_df.set_index("upi_id")["device_id"]

    for _ in range(NUM_MULE_RINGS):
        window_start = random_base_timestamp(rng, hour_low=8, hour_high=22, max_day_offset=DATE_RANGE_DAYS - 1)
        herder_device = new_device_id(rng)
        num_collectors = int(rng.integers(MULE_COLLECTORS_RANGE[0], MULE_COLLECTORS_RANGE[1] + 1))
        num_cashouts = int(rng.integers(MULE_CASHOUTS_RANGE[0], MULE_CASHOUTS_RANGE[1] + 1))

        collectors = []  # (account row, device the sweep is made from)
        for _ in range(num_collectors):
            recruited = (
                pick_aged_account(rng, accounts_df, window_start, taken)
                if rng.random() < MULE_RECRUITED_COLLECTOR_RATE
                else None
            )
            if recruited is not None:
                account_updates[recruited["upi_id"]] = SCENARIO
                collectors.append((recruited, herder_device))
            else:
                row = new_account_row(
                    rng, faker, account_counter, created_before(rng, window_start, 1, 30),
                    true_label=SCENARIO, device_id=herder_device,
                )
                new_accounts.append(row)
                collectors.append((row, herder_device))
        cashouts = [
            new_account_row(rng, faker, account_counter, created_before(rng, window_start, 1, 30), true_label=SCENARIO)
            for _ in range(num_cashouts)
        ]
        new_accounts.extend(cashouts)

        collector_upis = {c["upi_id"] for c, _ in collectors}
        sender_pool = [u for u in individuals_before(accounts_df, window_start) if u not in collector_upis]
        num_fanin = int(rng.integers(MULE_FANIN_RANGE[0], MULE_FANIN_RANGE[1] + 1))
        sender_upis = rng.choice(sender_pool, size=num_fanin, replace=False)

        collector_totals = {c["upi_id"]: 0.0 for c, _ in collectors}
        collector_last_ts = {c["upi_id"]: window_start for c, _ in collectors}

        for sender_upi in sender_upis:
            collector, _ = collectors[int(rng.integers(0, num_collectors))]
            ts = window_start + timedelta(seconds=int(rng.integers(0, 7200)))
            amount = float(np.clip(rng.lognormal(mean=7.5, sigma=0.7), 200, 20_000))
            new_txns.append(
                make_txn_row(
                    txn_counter,
                    sender_upi,
                    collector["upi_id"],
                    amount,
                    device_id=device_lookup.get(sender_upi),
                    created_at=ts,
                    transaction_type="P2P",
                    true_label=SCENARIO,
                    scenario=SCENARIO,
                )
            )
            collector_totals[collector["upi_id"]] += amount
            collector_last_ts[collector["upi_id"]] = max(collector_last_ts[collector["upi_id"]], ts)

        for c, sweep_device in collectors:
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
                    device_id=sweep_device,
                    created_at=sweep_ts,
                    transaction_type="P2P",
                    true_label=SCENARIO,
                    scenario=SCENARIO,
                )
            )

    return pd.DataFrame(new_accounts), pd.DataFrame(new_txns), account_updates
