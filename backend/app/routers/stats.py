"""Aggregates behind the Overview page. All windows end "now" and are in hours."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.case import Case
from app.models.enums import CaseSeverity, CaseStatus, InterventionLevel, ReasonCodeSource
from app.models.reason_code import ReasonCode
from app.models.risk_score import RiskScore
from app.models.transaction import Transaction
from app.scoring.fusion import DEFAULT_WEIGHTS
from app.scoring.intervention import get_intervention_ladder

router = APIRouter(prefix="/stats", tags=["stats"])


class TimeseriesBucket(BaseModel):
    start: datetime
    counts: dict[InterventionLevel, int]
    total: int


class ReasonCodeCount(BaseModel):
    code: str
    source: ReasonCodeSource
    count: int


class CaseSummary(BaseModel):
    open_by_severity: dict[CaseSeverity, int]
    unassigned: int
    closed: int


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.get("/timeseries", response_model=list[TimeseriesBucket])
def timeseries_endpoint(hours: int = Query(24, ge=1, le=24 * 30), db: Session = Depends(get_db)) -> list[TimeseriesBucket]:
    """One bucket per hour, oldest first, zero-filled so charts have no gaps."""
    end = _now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    start = end - timedelta(hours=hours)
    buckets = {
        start + timedelta(hours=i): {level: 0 for level in InterventionLevel} for i in range(hours)
    }
    rows = (
        db.query(Transaction.created_at, RiskScore.intervention_level)
        .join(RiskScore, RiskScore.transaction_id == Transaction.id)
        .filter(Transaction.created_at >= start, Transaction.created_at < end)
        .all()
    )
    for created_at, level in rows:
        ts = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
        buckets[ts.replace(minute=0, second=0, microsecond=0)][level] += 1
    return [TimeseriesBucket(start=s, counts=c, total=sum(c.values())) for s, c in buckets.items()]


@router.get("/reason-codes", response_model=list[ReasonCodeCount])
def reason_codes_endpoint(
    hours: int = Query(24, ge=1, le=24 * 30),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> list[ReasonCodeCount]:
    """Most frequently fired reason codes among transactions in the window."""
    since = _now() - timedelta(hours=hours)
    rows = (
        db.query(ReasonCode.code, ReasonCode.source, func.count(ReasonCode.id).label("n"))
        .join(RiskScore, RiskScore.id == ReasonCode.risk_score_id)
        .join(Transaction, Transaction.id == RiskScore.transaction_id)
        .filter(Transaction.created_at >= since)
        .group_by(ReasonCode.code, ReasonCode.source)
        .order_by(func.count(ReasonCode.id).desc(), ReasonCode.code.asc())
        .limit(limit)
        .all()
    )
    return [ReasonCodeCount(code=code, source=source, count=n) for code, source, n in rows]


@router.get("/cases", response_model=CaseSummary)
def case_summary_endpoint(db: Session = Depends(get_db)) -> CaseSummary:
    active = (CaseStatus.OPEN, CaseStatus.INVESTIGATING, CaseStatus.ESCALATED)
    by_severity = {sev: 0 for sev in CaseSeverity}
    for sev, n in db.query(Case.severity, func.count(Case.id)).filter(Case.status.in_(active)).group_by(Case.severity):
        by_severity[sev] = n
    unassigned = db.query(func.count(Case.id)).filter(Case.status.in_(active), Case.assigned_to.is_(None)).scalar() or 0
    closed = db.query(func.count(Case.id)).filter(Case.status == CaseStatus.CLOSED).scalar() or 0
    return CaseSummary(open_by_severity=by_severity, unassigned=unassigned, closed=closed)


class LadderLevel(BaseModel):
    level: InterventionLevel
    min_score: float
    min_confidence: float


class LadderOut(BaseModel):
    levels: list[LadderLevel]  # highest severity first; the first entry whose thresholds are both met wins
    weights: dict[str, float]  # how rule/ml/graph scores are blended into the fused score


@router.get("/ladder", response_model=LadderOut)
def ladder_endpoint() -> LadderOut:
    """The live decision thresholds, so the UI explains decisions with the real numbers."""
    return LadderOut(levels=[LadderLevel(**entry) for entry in get_intervention_ladder().levels], weights=DEFAULT_WEIGHTS)
