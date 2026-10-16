"""Account provisioning -- create the accounts a transaction can then reference.

Phase 7's replay script seeds every synthetic account through this
(from `ml/data/accounts.csv`) before replaying `ml/data/transactions.csv`
through `POST /transactions`; `POST /transactions` itself never creates an
account implicitly (see `app.accounts.get_account_or_404`) so a typo'd
`upi_id` fails loudly instead of silently fabricating an account.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app.accounts import create_account, get_account_or_404
from app.db import get_db
from app.models.account import Account
from app.models.case import Case
from app.models.enums import CaseStatus, InterventionLevel
from app.models.risk_score import RiskScore
from app.models.transaction import Transaction
from app.schemas import AccountCreate, AccountOut, AccountProfileOut
from app.scoring.context_builders import get_known_fraud_upis

_ACTIVE_CASE_STATUSES = (CaseStatus.OPEN, CaseStatus.INVESTIGATING, CaseStatus.ESCALATED)

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.post("", response_model=AccountOut, status_code=201)
def create_account_endpoint(payload: AccountCreate, db: Session = Depends(get_db)) -> AccountOut:
    account = create_account(
        db,
        upi_id=payload.upi_id,
        account_number=payload.account_number,
        ifsc_code=payload.ifsc_code,
        owner_name=payload.owner_name,
        bank_name=payload.bank_name,
        account_type=payload.account_type,
        device_id=payload.device_id,
        true_label=payload.true_label,
        is_active=payload.is_active,
        created_at=payload.created_at,
    )
    return AccountOut.model_validate(account)


@router.get("/{upi_id}", response_model=AccountProfileOut)
def get_account_profile_endpoint(upi_id: str, db: Session = Depends(get_db)) -> AccountProfileOut:
    account = get_account_or_404(db, upi_id)

    sent = (
        db.query(func.count(Transaction.id), func.coalesce(func.sum(Transaction.amount), 0))
        .filter(Transaction.sender_account_id == account.id)
        .one()
    )
    received = (
        db.query(func.count(Transaction.id), func.coalesce(func.sum(Transaction.amount), 0))
        .filter(Transaction.receiver_account_id == account.id)
        .one()
    )

    involves = or_(Transaction.sender_account_id == account.id, Transaction.receiver_account_id == account.id)
    max_score, flagged = (
        db.query(
            func.max(RiskScore.fused_score),
            func.coalesce(func.sum(case((RiskScore.intervention_level != InterventionLevel.INFORM, 1), else_=0)), 0),
        )
        .join(Transaction, Transaction.id == RiskScore.transaction_id)
        .filter(involves)
        .one()
    )

    open_cases = (
        db.query(func.count(Case.id))
        .join(Transaction, Transaction.id == Case.transaction_id)
        .filter(involves, Case.status.in_(_ACTIVE_CASE_STATUSES))
        .scalar()
    )

    paid_to = {r for (r,) in db.query(Transaction.receiver_account_id).filter(Transaction.sender_account_id == account.id)}
    paid_by = {s for (s,) in db.query(Transaction.sender_account_id).filter(Transaction.receiver_account_id == account.id)}
    counterparties = len(paid_to | paid_by)

    shared = []
    if account.device_id:
        shared = [
            u
            for (u,) in db.query(Account.upi_id)
            .filter(Account.device_id == account.device_id, Account.id != account.id)
            .order_by(Account.upi_id)
            .limit(50)
        ]

    return AccountProfileOut(
        upi_id=account.upi_id,
        owner_name=account.owner_name,
        bank_name=account.bank_name,
        ifsc_code=account.ifsc_code,
        account_type=account.account_type,
        device_id=account.device_id,
        is_active=account.is_active,
        created_at=account.created_at,
        known_fraud=account.upi_id in get_known_fraud_upis(db),
        transactions_sent=sent[0],
        transactions_received=received[0],
        total_sent=sent[1],
        total_received=received[1],
        counterparties=counterparties,
        max_score=max_score,
        flagged_count=int(flagged or 0),
        open_cases=open_cases or 0,
        shared_device_accounts=shared,
    )
