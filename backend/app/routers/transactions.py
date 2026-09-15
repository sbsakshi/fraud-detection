"""Phase 6's scoring endpoint: one POST, rules + ML + graph, one fused result.

Both sender and receiver must already exist (`POST /accounts` first) --
see `app.accounts.get_account_or_404`.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.accounts import get_account_or_404
from app.db import get_db
from app.schemas import CaseOut, ReasonCodeOut, RiskScoreOut, TransactionCreate, TransactionScoreOut
from app.scoring.pipeline import score_and_persist_transaction

router = APIRouter(prefix="/transactions", tags=["transactions"])


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
