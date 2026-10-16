"""Investigator workflow on cases: queue, detail, assignment, notes, closing.

Every mutation appends a `CaseEvent`, so the timeline is the audit trail --
nothing changes a case without leaving a row saying who did it and why.

`POST /cases/{case_id}/confirm-fraud` is the only way a receiver becomes a
"known fraud" account for future scoring (see
`app.scoring.context_builders.get_known_fraud_upis`). Escalation alone used to
do it, which let the system's own automatic decisions feed back into its
inputs with no human in the loop. Closing a case with resolution
`fraud_confirmed` records that same event, so the two paths can't disagree.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import case as sql_case, func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.case import Case
from app.models.case_event import CaseEvent
from app.models.enums import CaseSeverity, CaseStatus
from app.models.reason_code import ReasonCode
from app.models.risk_score import RiskScore
from app.models.transaction import Transaction
from app.routers.transactions import _scored_query, build_transaction_scores
from app.schemas import (
    CaseClose,
    CaseDetailOut,
    CaseEventOut,
    CaseListItemOut,
    CaseNoteCreate,
    CaseOut,
    CaseResolution,
    CaseUpdate,
    FraudConfirmation,
)
from app.scoring.context_builders import FRAUD_CONFIRMED_EVENT

router = APIRouter(prefix="/cases", tags=["cases"])

_SEVERITY_RANK = {
    CaseSeverity.CRITICAL: 0,
    CaseSeverity.HIGH: 1,
    CaseSeverity.MEDIUM: 2,
    CaseSeverity.LOW: 3,
}


def _get_case_or_404(db: Session, case_id: int) -> Case:
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"No case with id={case_id}.")
    return case


def _require_open(case: Case) -> None:
    if case.status == CaseStatus.CLOSED:
        raise HTTPException(status_code=409, detail=f"Case {case.id} is closed.")


def _record_fraud_confirmed(db: Session, case_id: int, actor: str, note: str | None) -> None:
    """Idempotent: a second confirmation doesn't stack up duplicate events."""
    already = db.execute(
        select(CaseEvent.id).where(CaseEvent.case_id == case_id, CaseEvent.event_type == FRAUD_CONFIRMED_EVENT)
    ).first()
    if already is None:
        db.add(CaseEvent(case_id=case_id, event_type=FRAUD_CONFIRMED_EVENT, description=note, actor=actor))


@router.get("", response_model=list[CaseListItemOut])
def list_cases_endpoint(
    response: Response,
    status: list[CaseStatus] | None = Query(None, description="repeat to match several statuses"),
    severity: list[CaseSeverity] | None = Query(None),
    assigned_to: str | None = None,
    unassigned: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[CaseListItemOut]:
    """The work queue: open work before closed, then most severe, then oldest first."""
    query = (
        db.query(Case, Transaction, RiskScore)
        .join(Transaction, Transaction.id == Case.transaction_id)
        .join(RiskScore, RiskScore.transaction_id == Transaction.id)
    )
    if status:
        query = query.filter(Case.status.in_(status))
    if severity:
        query = query.filter(Case.severity.in_(severity))
    if assigned_to:
        query = query.filter(Case.assigned_to == assigned_to)
    if unassigned:
        query = query.filter(Case.assigned_to.is_(None))

    response.headers["X-Total-Count"] = str(query.with_entities(func.count(Case.id)).scalar() or 0)

    severity_rank = sql_case(*[(Case.severity == sev, rank) for sev, rank in _SEVERITY_RANK.items()], else_=len(_SEVERITY_RANK))
    closed_last = sql_case((Case.status == CaseStatus.CLOSED, 1), else_=0)
    rows = (
        query.order_by(closed_last, severity_rank, Case.created_at.asc(), Case.id.asc()).offset(offset).limit(limit).all()
    )
    if not rows:
        return []

    risk_score_ids = [rs.id for _, _, rs in rows]
    top_reason: dict[int, str] = {}
    for rc in (
        db.query(ReasonCode)
        .filter(ReasonCode.risk_score_id.in_(risk_score_ids))
        .order_by(ReasonCode.contribution.desc().nulls_last(), ReasonCode.id.asc())
        .all()
    ):
        top_reason.setdefault(rc.risk_score_id, rc.code)  # first seen = highest contribution

    return [
        CaseListItemOut(
            id=case.id,
            status=case.status,
            severity=case.severity,
            assigned_to=case.assigned_to,
            created_at=case.created_at,
            updated_at=case.updated_at,
            transaction_id=txn.id,
            sender_upi_id=txn.sender.upi_id,
            receiver_upi_id=txn.receiver.upi_id,
            amount=txn.amount,
            currency=txn.currency,
            fused_score=rs.fused_score,
            intervention_level=rs.intervention_level,
            top_reason=top_reason.get(rs.id),
        )
        for case, txn, rs in rows
    ]


@router.get("/{case_id}", response_model=CaseDetailOut)
def get_case_endpoint(case_id: int, db: Session = Depends(get_db)) -> CaseDetailOut:
    case = _get_case_or_404(db, case_id)
    row = _scored_query(db).filter(Transaction.id == case.transaction_id).first()
    events = db.execute(
        select(CaseEvent).where(CaseEvent.case_id == case_id).order_by(CaseEvent.created_at.asc(), CaseEvent.id.asc())
    ).scalars()
    return CaseDetailOut(
        id=case.id,
        status=case.status,
        severity=case.severity,
        assigned_to=case.assigned_to,
        summary=case.summary,
        created_at=case.created_at,
        updated_at=case.updated_at,
        transaction=build_transaction_scores(db, [row])[0],
        events=[CaseEventOut.model_validate(e) for e in events],
    )


@router.patch("/{case_id}", response_model=CaseOut)
def update_case_endpoint(case_id: int, payload: CaseUpdate, db: Session = Depends(get_db)) -> CaseOut:
    case = _get_case_or_404(db, case_id)
    _require_open(case)
    if payload.status == CaseStatus.CLOSED:
        raise HTTPException(status_code=422, detail="Close a case with POST /cases/{id}/close, which records a resolution.")
    if payload.assigned_to and payload.unassign:
        raise HTTPException(status_code=422, detail="Pass either assigned_to or unassign, not both.")

    if payload.assigned_to and payload.assigned_to != case.assigned_to:
        db.add(CaseEvent(case_id=case.id, event_type="assigned", description=f"Assigned to {payload.assigned_to}", actor=payload.actor))
        case.assigned_to = payload.assigned_to
    elif payload.unassign and case.assigned_to is not None:
        db.add(CaseEvent(case_id=case.id, event_type="unassigned", description=f"Unassigned from {case.assigned_to}", actor=payload.actor))
        case.assigned_to = None

    if payload.status is not None and payload.status != case.status:
        db.add(
            CaseEvent(
                case_id=case.id,
                event_type="status_changed",
                description=f"{case.status.value} -> {payload.status.value}" + (f": {payload.note}" if payload.note else ""),
                actor=payload.actor,
            )
        )
        case.status = payload.status
    elif payload.note:
        db.add(CaseEvent(case_id=case.id, event_type="note", description=payload.note, actor=payload.actor))

    db.commit()
    db.refresh(case)
    return CaseOut.model_validate(case)


@router.post("/{case_id}/notes", response_model=CaseEventOut, status_code=201)
def add_note_endpoint(case_id: int, payload: CaseNoteCreate, db: Session = Depends(get_db)) -> CaseEventOut:
    _get_case_or_404(db, case_id)  # notes stay allowed on closed cases -- follow-up context is still useful
    event = CaseEvent(case_id=case_id, event_type="note", description=payload.note, actor=payload.actor)
    db.add(event)
    db.commit()
    db.refresh(event)
    return CaseEventOut.model_validate(event)


@router.post("/{case_id}/close", response_model=CaseOut)
def close_case_endpoint(case_id: int, payload: CaseClose, db: Session = Depends(get_db)) -> CaseOut:
    case = _get_case_or_404(db, case_id)
    _require_open(case)
    if payload.resolution == CaseResolution.FRAUD_CONFIRMED:
        _record_fraud_confirmed(db, case.id, payload.actor, payload.note)
    db.add(
        CaseEvent(
            case_id=case.id,
            event_type="closed",
            description=payload.resolution.value + (f": {payload.note}" if payload.note else ""),
            actor=payload.actor,
        )
    )
    case.status = CaseStatus.CLOSED
    db.commit()
    db.refresh(case)
    return CaseOut.model_validate(case)


@router.post("/{case_id}/confirm-fraud", response_model=CaseOut)
def confirm_fraud_endpoint(case_id: int, payload: FraudConfirmation, db: Session = Depends(get_db)) -> CaseOut:
    case = _get_case_or_404(db, case_id)
    _record_fraud_confirmed(db, case_id, payload.actor, payload.note)
    db.commit()
    return CaseOut.model_validate(case)
