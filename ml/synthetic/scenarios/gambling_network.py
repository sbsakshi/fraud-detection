"""High-risk gambling network: betting-operator merchant accounts receive
frequent, repeated, mostly-late-night payments from a pool of bettor accounts.
Individually each payment looks like an ordinary P2M purchase; the fan-in
frequency, the timing and the bettors' repeat pattern are the signal.

Operators are many and short-lived (each active for
`GAMBLING_ACTIVE_DAYS_RANGE` days, then gone -- the usual "new domain, new
merchant ID" churn), so a model can't score this scenario by memorizing a
handful of receivers it saw in training.
"""

from datetime import timedelta

import numpy as np
import pandas as pd

from ml.synthetic.config import (
    DATE_RANGE_DAYS,
    GAMBLING_ACTIVE_DAYS_RANGE,
    GAMBLING_BETS_RANGE,
    GAMBLING_BETTORS_RANGE,
    GAMBLING_LATE_NIGHT_RATE,
    NUM_GAMBLING_OPERATORS,
    START_DATE,
)
from ml.synthetic.helpers import new_account_row
from ml.synthetic.scenarios._util import created_before, individuals_before, make_txn_row

SCENARIO = "gambling_network"


def _bet_timestamp(rng, active_start: pd.Timestamp, active_days: int) -> pd.Timestamp:
    day = active_start.normalize() + timedelta(days=int(rng.integers(0, active_days)))
    if rng.random() < GAMBLING_LATE_NIGHT_RATE:
        hour = int(rng.integers(20, 27))  # 20:00 .. 02:59, may spill into the next day
    else:
        hour = int(rng.integers(10, 20))
    ts = day + timedelta(hours=hour, minutes=int(rng.integers(0, 60)), seconds=int(rng.integers(0, 60)))
    return max(ts, active_start)


def inject(rng: np.random.Generator, faker, accounts_df: pd.DataFrame, account_counter, txn_counter):
    new_accounts = []
    new_txns = []
    account_updates: dict[str, str] = {}
    used_bettors: set[str] = set()

    device_lookup = accounts_df.set_index("upi_id")["device_id"]

    for _ in range(NUM_GAMBLING_OPERATORS):
        active_days = int(rng.integers(GAMBLING_ACTIVE_DAYS_RANGE[0], GAMBLING_ACTIVE_DAYS_RANGE[1] + 1))
        start_offset = int(rng.integers(0, max(1, DATE_RANGE_DAYS - active_days)))
        active_start = pd.Timestamp(START_DATE) + timedelta(days=start_offset, hours=int(rng.integers(0, 24)))

        operator = new_account_row(
            rng, faker, account_counter, created_before(rng, active_start, 2, 60),
            account_type="merchant", true_label=SCENARIO, category="Gambling & Betting",
        )
        new_accounts.append(operator)

        candidates = [u for u in individuals_before(accounts_df, active_start, unlabelled=True) if u not in used_bettors]
        num_bettors = min(int(rng.integers(GAMBLING_BETTORS_RANGE[0], GAMBLING_BETTORS_RANGE[1] + 1)), len(candidates))
        bettors = rng.choice(candidates, size=num_bettors, replace=False)

        for bettor_upi in bettors:
            used_bettors.add(bettor_upi)
            account_updates[bettor_upi] = SCENARIO
            num_bets = int(rng.integers(GAMBLING_BETS_RANGE[0], GAMBLING_BETS_RANGE[1] + 1))
            for _ in range(num_bets):
                amount = float(np.clip(rng.lognormal(mean=6.0, sigma=0.8), 50, 15_000))
                new_txns.append(
                    make_txn_row(
                        txn_counter,
                        bettor_upi,
                        operator["upi_id"],
                        amount,
                        device_id=device_lookup.get(bettor_upi),
                        created_at=_bet_timestamp(rng, active_start, active_days),
                        transaction_type="P2M",
                        true_label=SCENARIO,
                        scenario=SCENARIO,
                    )
                )

    return pd.DataFrame(new_accounts), pd.DataFrame(new_txns), account_updates
