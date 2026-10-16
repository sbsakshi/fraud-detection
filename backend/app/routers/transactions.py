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

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import exists, func, or_
from sqlalchemy.orm import Session, joinedload

from app.accounts import get_account_or_404
from app.db import get_db
from app.models.account import Account
from app.models.case import Case
from app.models.enums import CaseStatus, InterventionLevel, ReasonCodeSource
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
def _as_utc(value: datetime) -> datetime:
    # Query-string timestamps without an offset parse as naive; every stored
    # timestamp is aware UTC, and mixing the two raises on comparison.
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


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


def build_transaction_scores(db: Session, rows: list[tuple[Transaction, RiskScore]]) -> list[TransactionScoreOut]:
    """Assemble wire-format results for already-fetched (transaction, risk score) pairs.

    Shared with the cases router so a case's transaction renders identically to
    the same transaction in the feed.
    """
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
            reason_codes=sorted(
                (ReasonCodeOut.model_validate(rc) for rc in reason_codes_by_risk_score.get(risk_score.id, [])),
                key=lambda rc: rc.contribution or 0.0,
                reverse=True,
            ),
            case=CaseOut.model_validate(case_by_transaction[transaction.id]) if transaction.id in case_by_transaction else None,
        )
        for transaction, risk_score in rows
    ]


def _scored_query(db: Session):
    return (
        db.query(Transaction, RiskScore)
        .join(RiskScore, RiskScore.transaction_id == Transaction.id)
        .options(joinedload(Transaction.sender), joinedload(Transaction.receiver))
    )


@router.get("", response_model=list[TransactionScoreOut])
def list_transactions_endpoint(
    response: Response,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    level: list[InterventionLevel] | None = Query(None, description="repeat to match several levels"),
    min_score: float | None = Query(None, ge=0, le=1),
    max_score: float | None = Query(None, ge=0, le=1),
    source: ReasonCodeSource | None = Query(None, description="only transactions with a reason code from this source"),
    since: datetime | None = None,
    until: datetime | None = None,
    q: str | None = Query(None, min_length=1, description="substring of sender or receiver UPI id"),
    account: str | None = Query(None, description="exact UPI id, as sender or receiver"),
    has_case: bool | None = None,
    db: Session = Depends(get_db),
) -> list[TransactionScoreOut]:
    """Most recently created first. `X-Total-Count` carries the unpaged match count."""
    query = _scored_query(db)
    if level:
        query = query.filter(RiskScore.intervention_level.in_(level))
    if min_score is not None:
        query = query.filter(RiskScore.fused_score >= min_score)
    if max_score is not None:
        query = query.filter(RiskScore.fused_score <= max_score)
    if source is not None:
        query = query.filter(
            exists().where(ReasonCode.risk_score_id == RiskScore.id, ReasonCode.source == source)
        )
    if since is not None:
        query = query.filter(Transaction.created_at >= _as_utc(since))
    if until is not None:
        query = query.filter(Transaction.created_at <= _as_utc(until))
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(
            or_(
                Transaction.sender.has(func.lower(Account.upi_id).like(like)),
                Transaction.receiver.has(func.lower(Account.upi_id).like(like)),
            )
        )
    if account:
        query = query.filter(or_(Transaction.sender.has(Account.upi_id == account), Transaction.receiver.has(Account.upi_id == account)))
    if has_case is not None:
        case_exists = exists().where(Case.transaction_id == Transaction.id)
        query = query.filter(case_exists if has_case else ~case_exists)

    response.headers["X-Total-Count"] = str(query.with_entities(func.count(Transaction.id)).scalar() or 0)
    rows = query.order_by(Transaction.created_at.desc(), Transaction.id.desc()).offset(offset).limit(limit).all()
    return build_transaction_scores(db, rows)


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


@router.get("/{transaction_id}", response_model=TransactionScoreOut)
def get_transaction_endpoint(transaction_id: int, db: Session = Depends(get_db)) -> TransactionScoreOut:
    row = _scored_query(db).filter(Transaction.id == transaction_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"No scored transaction with id={transaction_id}.")
    return build_transaction_scores(db, [row])[0]
