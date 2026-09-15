"""Build `RuleContext` from live database state.

`app.graph`'s `GraphContext` needs no DB-query equivalent of this: the
process-wide graph (`app.graph.live_graph`) is already incrementally
maintained in memory as transactions are scored, so building it fresh from
the database per request the way rules need isn't necessary.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.case import Case
from app.models.enums import CaseStatus
from app.models.transaction import Transaction
from app.rules import RuleContext, RuleTransaction


def _as_utc(dt: datetime) -> datetime:
    """Postgres round-trips `DateTime(timezone=True)` as aware; SQLite (this
    project's test DB, see tests/conftest.py) hands back naive datetimes for
    the same column. Comparing an aware and a naive datetime raises, so every
    timestamp crossing the DB boundary into a RuleTransaction gets normalized
    here regardless of which database produced it."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def get_known_fraud_upis(db: Session) -> frozenset[str]:
    """Receivers of escalated cases -- confirmed fraud beneficiaries fed back into scoring.

    A real feedback loop: once a transaction is escalated into a case (see
    `app.scoring.pipeline`), its receiver becomes a known-fraud beneficiary
    for every transaction scored after that, both for
    `rules.known_fraud_beneficiary` (direct hit) and
    `graph.fraud_cluster_exposure` (one or two hops away).
    """
    stmt = (
        select(Account.upi_id)
        .join(Transaction, Transaction.receiver_account_id == Account.id)
        .join(Case, Case.transaction_id == Transaction.id)
        .where(Case.status == CaseStatus.ESCALATED)
        .distinct()
    )
    return frozenset(db.execute(stmt).scalars().all())


def build_rule_context(
    db: Session,
    sender: Account,
    receiver: Account,
    amount: Decimal,
    created_at: datetime,
    known_fraud_upis: frozenset[str],
) -> RuleContext:
    sender_prior_rows = db.execute(
        select(Transaction)
        .where(Transaction.sender_account_id == sender.id, Transaction.created_at < created_at)
        .order_by(Transaction.created_at)
    ).scalars().all()
    sender_prior_receiver_ids = {t.receiver_account_id for t in sender_prior_rows}
    receiver_upi_by_id = {
        a.id: a.upi_id
        for a in db.execute(select(Account).where(Account.id.in_(sender_prior_receiver_ids))).scalars().all()
    }
    sender_prior_transactions = [
        RuleTransaction(
            sender_upi_id=sender.upi_id,
            receiver_upi_id=receiver_upi_by_id[t.receiver_account_id],
            amount=t.amount,
            created_at=_as_utc(t.created_at),
        )
        for t in sender_prior_rows
    ]

    receiver_prior_rows = db.execute(
        select(Transaction)
        .where(Transaction.receiver_account_id == receiver.id, Transaction.created_at < created_at)
        .order_by(Transaction.created_at)
    ).scalars().all()
    receiver_prior_sender_ids = {t.sender_account_id for t in receiver_prior_rows}
    sender_upi_by_id = {
        a.id: a.upi_id
        for a in db.execute(select(Account).where(Account.id.in_(receiver_prior_sender_ids))).scalars().all()
    }
    receiver_prior_senders = [
        (sender_upi_by_id[t.sender_account_id], _as_utc(t.created_at)) for t in receiver_prior_rows
    ]

    return RuleContext(
        transaction=RuleTransaction(
            sender_upi_id=sender.upi_id, receiver_upi_id=receiver.upi_id, amount=amount, created_at=created_at
        ),
        sender_prior_transactions=sender_prior_transactions,
        receiver_prior_senders=receiver_prior_senders,
        known_fraud_beneficiaries=known_fraud_upis,
    )
