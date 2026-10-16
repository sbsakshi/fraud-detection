from datetime import timedelta

import numpy as np
import pandas as pd

from ml.synthetic.config import DATE_RANGE_DAYS, END_DATE, START_DATE


def random_base_timestamp(rng, hour_low: int = 6, hour_high: int = 23, max_day_offset: int | None = None) -> pd.Timestamp:
    # hour_high may exceed 24 (e.g. a "late night" window spilling past midnight);
    # cap the day offset so the resulting timestamp never lands past END_DATE.
    overflow_days = max(0, (hour_high - 1) // 24)
    highest_day = max_day_offset if max_day_offset is not None else DATE_RANGE_DAYS - overflow_days
    day_offset = int(rng.integers(0, highest_day + 1))
    hour = int(rng.integers(hour_low, hour_high))
    minute = int(rng.integers(0, 60))
    second = int(rng.integers(0, 60))
    return pd.Timestamp(START_DATE) + timedelta(days=day_offset, hours=hour, minutes=minute, seconds=second)


def account_takeover_timestamp(rng, night_rate: float) -> pd.Timestamp:
    """Any day in the scenario window; small hours with probability `night_rate`, else daytime.

    Takeovers used to be pinned to the last 10 days between midnight and 5am,
    which put every one of them in the test split by construction.
    """
    day_offset = int(rng.integers(0, DATE_RANGE_DAYS))
    hour = int(rng.integers(0, 6)) if rng.random() < night_rate else int(rng.integers(6, 24))
    return pd.Timestamp(START_DATE) + timedelta(
        days=day_offset, hours=hour, minutes=int(rng.integers(0, 60)), seconds=int(rng.integers(0, 60))
    )


def random_timestamp_after(rng, earliest: pd.Timestamp, hour_low: int = 6, hour_high: int = 23) -> pd.Timestamp:
    """A daytime timestamp inside the scenario window, no earlier than `earliest`."""
    window_start = pd.Timestamp(START_DATE)
    first_day = max(window_start, pd.Timestamp(earliest).normalize() + timedelta(days=1))
    if first_day > pd.Timestamp(END_DATE):
        return pd.Timestamp(earliest) + timedelta(minutes=int(rng.integers(30, 600)))
    span = max(0, (pd.Timestamp(END_DATE) - first_day).days)
    day = first_day + timedelta(days=int(rng.integers(0, span + 1)))
    return day + timedelta(hours=int(rng.integers(hour_low, hour_high)), minutes=int(rng.integers(0, 60)))


def created_before(rng, ts: pd.Timestamp, min_days: int, max_days: int) -> pd.Timestamp:
    """An account-opening time `min_days`..`max_days` before `ts` (never after it)."""
    delta = timedelta(days=int(rng.integers(min_days, max_days + 1)), hours=int(rng.integers(1, 12)))
    return pd.Timestamp(ts) - delta


def individuals_before(accounts_df: pd.DataFrame, before: pd.Timestamp, unlabelled: bool = False) -> np.ndarray:
    """upi_ids of individual accounts that already existed at `before`."""
    mask = (accounts_df["account_type"] == "individual") & (pd.to_datetime(accounts_df["created_at"]) < before)
    if unlabelled:
        mask &= accounts_df["true_label"].isna()
    return accounts_df.loc[mask, "upi_id"].to_numpy()


def pick_aged_account(rng, accounts_df: pd.DataFrame, before: pd.Timestamp, taken: set[str], min_age_days: int = 90):
    """An existing, unlabelled individual account at least `min_age_days` old at `before`,
    not already used by another scenario -- a recruited or bought account. Returns its
    accounts-table row as a dict, or None if none is left."""
    pool = individuals_before(accounts_df, pd.Timestamp(before) - timedelta(days=min_age_days), unlabelled=True)
    pool = [u for u in pool if u not in taken]
    if not pool:
        return None
    upi = pool[int(rng.integers(0, len(pool)))]
    taken.add(upi)
    return accounts_df.loc[accounts_df["upi_id"] == upi].iloc[0].to_dict()


def shortly_after(rng, ts: pd.Timestamp, min_seconds: int = 30, max_seconds: int = 600) -> pd.Timestamp:
    delta = int(rng.integers(min_seconds, max_seconds + 1))
    return ts + timedelta(seconds=delta)


def make_txn_row(
    txn_counter,
    sender_upi: str,
    receiver_upi: str,
    amount: float,
    device_id: str,
    created_at: pd.Timestamp,
    transaction_type: str = "P2P",
    status: str = "completed",
    true_label: str | None = None,
    scenario: str | None = None,
) -> dict:
    return {
        "txn_ref": f"TXN{txn_counter.next():08d}",
        "sender_upi_id": sender_upi,
        "receiver_upi_id": receiver_upi,
        "amount": round(float(amount), 2),
        "currency": "INR",
        "device_id": device_id,
        "transaction_type": transaction_type,
        "status": status,
        "created_at": created_at,
        "true_label": true_label,
        "scenario": scenario,
    }
