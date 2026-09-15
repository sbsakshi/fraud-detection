"""Compute live ML features for one candidate transaction from the database.

Pulls just the transaction history involving the sender and/or receiver,
shapes it into the same frames `ml/features/engineering.py` expects (a
replay of the Phase 2 synthetic dataset), and reuses that exact logic via
the vendored copy at `app.ml.feature_engineering` -- see that file's header
for why it's vendored rather than imported across the backend/ml package
boundary.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pandas as pd
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.ml.feature_engineering import FEATURE_COLUMNS, build_features
from app.models.account import Account
from app.models.transaction import Transaction

_CANDIDATE_REF = "__live_candidate__"


def compute_live_features(
    db: Session,
    sender: Account,
    receiver: Account,
    amount: Decimal,
    device_id: str,
    transaction_type: str,
    created_at: datetime,
) -> dict[str, float]:
    """Feature dict for a not-yet-persisted candidate transaction.

    Pulls every transaction where the sender or receiver appears, on either
    side, strictly before `created_at`, runs the same batch feature
    computation Phase 4 trained against over that slice plus the candidate,
    and returns just the candidate's row.

    Correctness over throughput, deliberately: a very active account
    re-pulls its whole relevant history on every transaction rather than
    maintaining incremental state across requests. That's the right trade
    for this project's scale (a research/demo system, not a high-QPS
    production one) -- it keeps this the exact logic Phase 4 validated
    instead of a hand-rolled incremental SQL version that could quietly
    drift from it.
    """
    account_ids = {sender.id, receiver.id}
    history_stmt = (
        select(Transaction)
        .where(
            or_(Transaction.sender_account_id.in_(account_ids), Transaction.receiver_account_id.in_(account_ids)),
            Transaction.created_at < created_at,
        )
        .order_by(Transaction.created_at)
    )
    history = db.execute(history_stmt).scalars().all()

    involved_account_ids = (
        account_ids | {t.sender_account_id for t in history} | {t.receiver_account_id for t in history}
    )
    accounts = db.execute(select(Account).where(Account.id.in_(involved_account_ids))).scalars().all()
    upi_by_account_id = {a.id: a.upi_id for a in accounts}

    accounts_df = pd.DataFrame(
        [{"upi_id": a.upi_id, "created_at": a.created_at, "account_type": a.account_type.value} for a in accounts]
    )

    txn_rows = [
        {
            "txn_ref": f"live-history:{t.id}",
            "sender_upi_id": upi_by_account_id[t.sender_account_id],
            "receiver_upi_id": upi_by_account_id[t.receiver_account_id],
            "amount": float(t.amount),
            "device_id": t.device_id,
            "transaction_type": t.transaction_type,
            "true_label": t.true_label,
            "scenario": t.scenario,
            "created_at": t.created_at,
        }
        for t in history
    ]
    txn_rows.append(
        {
            "txn_ref": _CANDIDATE_REF,
            "sender_upi_id": sender.upi_id,
            "receiver_upi_id": receiver.upi_id,
            "amount": float(amount),
            "device_id": device_id,
            "transaction_type": transaction_type,
            "true_label": None,
            "scenario": None,
            "created_at": created_at,
        }
    )
    txns_df = pd.DataFrame(txn_rows)

    features_df = build_features(txns_df, accounts_df)
    candidate_row = features_df.loc[features_df["txn_ref"] == _CANDIDATE_REF].iloc[0]
    return {col: float(candidate_row[col]) for col in FEATURE_COLUMNS}
