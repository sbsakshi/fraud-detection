"""Phase 6's scoring endpoint: one POST, rules + ML + graph, one fused result.

Both sender and receiver must already exist (`POST /accounts` first) --
see `app.accounts.get_account_or_404`.

Phase 7 adds the two read endpoints the dashboard polls: `GET /transactions`
(most recently scored, newest first) and `GET /transactions/stats` (the
summary tiles). Neither `Transaction`, `RiskScore`, `ReasonCode`, nor `Case`
declare ORM relationships to each other (each module only needed its own
FK), so these join by hand with plain `IN` lookups keyed off the page of
transaction/risk-score ids already fetched, rather than per-row queries.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.accounts import get_account_or_404
from app.db import get_db
from app.models.case import Case
from app.models.enums import CaseStatus, InterventionLevel
from app.models.reason_code import ReasonCode
from app.models.risk_score import RiskScore
from app.models.transaction import Transaction
from app.schemas import (
    CaseOut,
    ReasonCodeOut,
    RiskScoreOut,
    TransactionCreate,
    TransactionScoreOut,
    TransactionStatsOut,
)
from app.scoring.pipeline import score_and_persist_transaction

router = APIRouter(prefix="/transactions", tags=["transactions"])

# Cases severe enough to count as "active" for the stats tile -- CLOSED cases
# are done, so they don't belong in a count meant to show current workload.
ACTIVE_CASE_STATUSES = (CaseStatus.OPEN, CaseStatus.INVESTIGATING, CaseStatus.ESCALATED)


@router.post("", response_model=TransactionScoreOut, status_code=201)
def score_transaction_endpoint(payload: TransactionCreate, db: Session = Depends(get_db)) -> TransactionScoreOut:
    sender = get_account_or_404(db, payload.sender_upi_id)
    receiver = get_account_or_404(db, payload.receiver_upi_id)

    result = score_and_persist_transaction(
        db,
        sender=sender,
        receiver=receiver,
        amount=payload.amount,
        currency=payload.currency,
        device_id=payload.device_id,
        transaction_type=payload.transaction_type,
        status=payload.status,
        true_label=payload.true_label,
        scenario=payload.scenario,
        created_at=payload.created_at,
    )

    return TransactionScoreOut(
        transaction_id=result.transaction.id,
        sender_upi_id=sender.upi_id,
        receiver_upi_id=receiver.upi_id,
        amount=result.transaction.amount,
        currency=result.transaction.currency,
        created_at=result.transaction.created_at,
        risk_score=RiskScoreOut.model_validate(result.risk_score),
        reason_codes=[ReasonCodeOut.model_validate(rc) for rc in result.reason_codes],
        case=CaseOut.model_validate(result.case) if result.case else None,
    )


@router.get("", response_model=list[TransactionScoreOut])
def list_transactions_endpoint(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[TransactionScoreOut]:
    rows = (
        db.query(Transaction, RiskScore)
        .join(RiskScore, RiskScore.transaction_id == Transaction.id)
        .options(joinedload(Transaction.sender), joinedload(Transaction.receiver))
        .order_by(Transaction.created_at.desc())
        .limit(limit)
        .all()
    )
    if not rows:
        return []

    risk_score_ids = [risk_score.id for _, risk_score in rows]
    transaction_ids = [transaction.id for transaction, _ in rows]

    reason_codes_by_risk_score: dict[int, list[ReasonCode]] = {}
    for rc in db.query(ReasonCode).filter(ReasonCode.risk_score_id.in_(risk_score_ids)).all():
        reason_codes_by_risk_score.setdefault(rc.risk_score_id, []).append(rc)

    case_by_transaction: dict[int, Case] = {
        case.transaction_id: case
        for case in db.query(Case).filter(Case.transaction_id.in_(transaction_ids)).all()
    }

    return [
        TransactionScoreOut(
            transaction_id=transaction.id,
            sender_upi_id=transaction.sender.upi_id,
            receiver_upi_id=transaction.receiver.upi_id,
            amount=transaction.amount,
            currency=transaction.currency,
            created_at=transaction.created_at,
            risk_score=RiskScoreOut.model_validate(risk_score),
            reason_codes=[ReasonCodeOut.model_validate(rc) for rc in reason_codes_by_risk_score.get(risk_score.id, [])],
            case=CaseOut.model_validate(case_by_transaction[transaction.id]) if transaction.id in case_by_transaction else None,
        )
        for transaction, risk_score in rows
    ]


@router.get("/stats", response_model=TransactionStatsOut)
def transaction_stats_endpoint(db: Session = Depends(get_db)) -> TransactionStatsOut:
    total = db.query(func.count(RiskScore.id)).scalar() or 0
    if total == 0:
        return TransactionStatsOut(transactions_scored=0, flagged_rate=0.0, active_cases=0, avg_fused_score=0.0)

    flagged = (
        db.query(func.count(RiskScore.id)).filter(RiskScore.intervention_level != InterventionLevel.INFORM).scalar() or 0
    )
    avg_fused_score = db.query(func.avg(RiskScore.fused_score)).scalar() or 0.0
    active_cases = db.query(func.count(Case.id)).filter(Case.status.in_(ACTIVE_CASE_STATUSES)).scalar() or 0

    return TransactionStatsOut(
        transactions_scored=total,
        flagged_rate=flagged / total,
        active_cases=active_cases,
        avg_fused_score=float(avg_fused_score),
    )
