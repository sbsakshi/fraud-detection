from datetime import timedelta

import pandas as pd

from ml.synthetic.config import DATE_RANGE_DAYS, START_DATE


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


def late_night_timestamp(rng, days_before_end: int = 10) -> pd.Timestamp:
    """A timestamp in the small hours, within the last `days_before_end` days —
    used for account-takeover drains, which tend to happen off-hours and recently."""
    day_offset = int(rng.integers(DATE_RANGE_DAYS - days_before_end, DATE_RANGE_DAYS + 1))
    hour = int(rng.integers(0, 5))
    minute = int(rng.integers(0, 60))
    second = int(rng.integers(0, 60))
    return pd.Timestamp(START_DATE) + timedelta(days=day_offset, hours=hour, minutes=minute, seconds=second)


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
