"""Investigator actions on cases.

`POST /cases/{case_id}/confirm-fraud` is the only way a receiver becomes a
"known fraud" account for future scoring (see
`app.scoring.context_builders.get_known_fraud_upis`). Escalation alone used to
do it, which let the system's own automatic decisions feed back into its
inputs with no human in the loop.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.case import Case
from app.models.case_event import CaseEvent
from app.schemas import CaseOut, FraudConfirmation
from app.scoring.context_builders import FRAUD_CONFIRMED_EVENT

router = APIRouter(prefix="/cases", tags=["cases"])


@router.post("/{case_id}/confirm-fraud", response_model=CaseOut)
def confirm_fraud_endpoint(case_id: int, payload: FraudConfirmation, db: Session = Depends(get_db)) -> CaseOut:
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"No case with id={case_id}.")
    already = db.execute(
        select(CaseEvent.id).where(CaseEvent.case_id == case_id, CaseEvent.event_type == FRAUD_CONFIRMED_EVENT)
    ).first()
    if already is None:
        db.add(CaseEvent(case_id=case_id, event_type=FRAUD_CONFIRMED_EVENT, description=payload.note, actor=payload.actor))
        db.commit()
    return CaseOut.model_validate(case)
