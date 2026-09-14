from datetime import timedelta

import numpy as np
import pandas as pd

from ml.synthetic.config import (
    DATE_RANGE_DAYS,
    MERCHANT_ACCOUNT_RATE,
    MERCHANT_CATEGORIES,
    START_DATE,
)
from ml.synthetic.helpers import new_account_number, new_device_id, new_ifsc, new_upi_id, pick_bank, slugify

# Hour-of-day weights for a rough Indian daytime usage curve: low overnight,
# rising through the morning, a lunch bump, and an evening peak.
_HOURLY_WEIGHTS = np.array(
    [
        0.4, 0.3, 0.2, 0.2, 0.3, 0.5,  # 00-05
        1.0, 2.0, 3.0, 3.5, 3.5, 4.0,  # 06-11
        4.5, 4.0, 3.5, 3.2, 3.2, 3.5,  # 12-17
        4.5, 5.0, 4.5, 3.5, 2.0, 1.0,  # 18-23
    ]
)
_HOURLY_PROBS = _HOURLY_WEIGHTS / _HOURLY_WEIGHTS.sum()


def _random_timestamps(rng: np.random.Generator, n: int) -> pd.Series:
    day_offsets = rng.integers(0, DATE_RANGE_DAYS + 1, size=n)
    hours = rng.choice(24, size=n, p=_HOURLY_PROBS)
    minutes = rng.integers(0, 60, size=n)
    seconds = rng.integers(0, 60, size=n)
    base = pd.Timestamp(START_DATE)
    return pd.to_datetime(
        [
            base + timedelta(days=int(d), hours=int(h), minutes=int(mi), seconds=int(s))
            for d, h, mi, s in zip(day_offsets, hours, minutes, seconds)
        ]
    )


def generate_accounts(rng: np.random.Generator, faker, n: int, account_counter) -> pd.DataFrame:
    rows = []
    account_age_start = START_DATE - timedelta(days=3 * 365)
    max_created_offset = (pd.Timestamp(START_DATE) - pd.Timestamp(account_age_start)).days

    for _ in range(n):
        is_merchant = rng.random() < MERCHANT_ACCOUNT_RATE
        bank_name, ifsc_prefix, handle = pick_bank(rng)

        if is_merchant:
            category = MERCHANT_CATEGORIES[rng.integers(0, len(MERCHANT_CATEGORIES))]
            owner_name = f"{faker.company()} {category}"
            account_type = "merchant"
            slug = slugify(owner_name.split()[0])
        else:
            owner_name = faker.name()
            account_type = "individual"
            slug = slugify(owner_name.split()[0])

        created_offset = int(rng.integers(0, max_created_offset + 1))
        created_at = pd.Timestamp(account_age_start) + timedelta(days=created_offset)

        # Heavy-tailed activity level: most accounts transact rarely, a few (mostly
        # merchants) transact constantly. This is what makes velocity/fan-in features
        # meaningful downstream instead of every account looking identical.
        activity_weight = float(rng.pareto(1.5) + 1.0)
        if is_merchant:
            activity_weight *= 3.0

        rows.append(
            {
                "upi_id": new_upi_id(rng, slug, handle, account_counter.next()),
                "account_number": new_account_number(rng),
                "ifsc_code": new_ifsc(rng, ifsc_prefix),
                "owner_name": owner_name,
                "bank_name": bank_name,
                "account_type": account_type,
                "device_id": new_device_id(rng),
                "activity_weight": activity_weight,
                "created_at": created_at,
                "is_active": rng.random() > 0.02,
                "true_label": None,
            }
        )

    return pd.DataFrame(rows)


def generate_normal_transactions(rng: np.random.Generator, accounts_df: pd.DataFrame, n: int, txn_counter) -> pd.DataFrame:
    m = len(accounts_df)

    is_merchant = (accounts_df["account_type"] == "merchant").to_numpy()
    sender_weights = accounts_df["activity_weight"].to_numpy()
    sender_probs = sender_weights / sender_weights.sum()

    receiver_weights = accounts_df["activity_weight"].to_numpy() * np.where(is_merchant, 4.0, 1.0)
    receiver_probs = receiver_weights / receiver_weights.sum()

    sender_idx = rng.choice(m, size=n, p=sender_probs)
    receiver_idx = rng.choice(m, size=n, p=receiver_probs)
    collisions = sender_idx == receiver_idx
    while collisions.any():
        receiver_idx[collisions] = rng.choice(m, size=collisions.sum(), p=receiver_probs)
        collisions = sender_idx == receiver_idx

    receiver_is_merchant = is_merchant[receiver_idx]

    p2m_amounts = rng.lognormal(mean=6.5, sigma=0.9, size=n)
    p2p_amounts = rng.lognormal(mean=5.9, sigma=1.0, size=n)
    amounts = np.where(receiver_is_merchant, p2m_amounts, p2p_amounts)
    amounts = np.clip(amounts, 1.0, 200_000.0).round(2)

    timestamps = _random_timestamps(rng, n)

    sender_upi = accounts_df["upi_id"].to_numpy()[sender_idx]
    receiver_upi = accounts_df["upi_id"].to_numpy()[receiver_idx]
    sender_device = accounts_df["device_id"].to_numpy()[sender_idx]

    # ~5% of the time the payer uses an unregistered device (a browser, a borrowed
    # phone) — ordinary behaviour, kept rare enough that it doesn't swamp the
    # device-anomaly signal the account-takeover scenario relies on.
    off_device_mask = rng.random(n) < 0.05
    device_ids = sender_device.copy()
    off_device_count = int(off_device_mask.sum())
    if off_device_count:
        device_ids[off_device_mask] = [new_device_id(rng) for _ in range(off_device_count)]

    status = rng.choice(["completed", "pending", "failed"], size=n, p=[0.97, 0.02, 0.01])
    transaction_type = np.where(receiver_is_merchant, "P2M", "P2P")
    txn_refs = [f"TXN{txn_counter.next():08d}" for _ in range(n)]

    df = pd.DataFrame(
        {
            "txn_ref": txn_refs,
            "sender_upi_id": sender_upi,
            "receiver_upi_id": receiver_upi,
            "amount": amounts,
            "currency": "INR",
            "device_id": device_ids,
            "transaction_type": transaction_type,
            "status": status,
            "created_at": timestamps,
            "true_label": None,
            "scenario": None,
        }
    )
    return df.sort_values("created_at").reset_index(drop=True)
