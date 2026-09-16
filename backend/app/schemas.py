"""Pydantic request/response models for the API layer.

Kept separate from the SQLAlchemy models in `app.models`: the DB schema and
the wire format are allowed to diverge (e.g. `TransactionScoreOut` surfaces
`sender_upi_id`/`receiver_upi_id`, which aren't columns on `Transaction`
itself -- they come from the resolved `Account` rows).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AccountType, CaseSeverity, CaseStatus, InterventionLevel, ReasonCodeSource, TransactionStatus


class AccountCreate(BaseModel):
    upi_id: str
    account_number: str
    ifsc_code: str
    owner_name: str
    bank_name: str
    account_type: AccountType = AccountType.INDIVIDUAL
    device_id: str | None = None
    true_label: str | None = None
    is_active: bool = True


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    upi_id: str
    account_number: str
    ifsc_code: str
    owner_name: str
    bank_name: str
    account_type: AccountType
    device_id: str | None
    true_label: str | None
    is_active: bool
    created_at: datetime


class TransactionCreate(BaseModel):
    sender_upi_id: str
    receiver_upi_id: str
    amount: Decimal = Field(gt=0)
    currency: str = "INR"
    device_id: str
    transaction_type: str = "P2P"
    status: TransactionStatus = TransactionStatus.COMPLETED
    # Optional pass-through so a synthetic-dataset replay (Phase 7) can keep
    # ground-truth labels attached to the live-scored rows.
    true_label: str | None = None
    scenario: str | None = None
    # Defaults to now() if omitted; a replay driving historical timestamps
    # through the API sets this explicitly instead.
    created_at: datetime | None = None


class ReasonCodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source: ReasonCodeSource
    code: str
    template: str
    details: dict
    contribution: float | None


class RiskScoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rule_score: float | None
    ml_score: float | None
    graph_score: float | None
    fused_score: float
    confidence: float
    intervention_level: InterventionLevel


class CaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: CaseStatus
    severity: CaseSeverity


class TransactionScoreOut(BaseModel):
    transaction_id: int
    sender_upi_id: str
    receiver_upi_id: str
    amount: Decimal
    currency: str
    created_at: datetime
    risk_score: RiskScoreOut
    reason_codes: list[ReasonCodeOut]
    case: CaseOut | None


class TransactionStatsOut(BaseModel):
    transactions_scored: int
    flagged_rate: float
    active_cases: int
    avg_fused_score: float


class GraphNodeOut(BaseModel):
    id: str  # upi_id -- the live graph's own node key, see app.graph.builder
    true_label: str | None
    account_type: AccountType | None
    # Which Louvain community (app.graph.analysis.detect_communities) this
    # node falls into, for cluster coloring -- not a fraud signal on its own,
    # just a stable grouping so the frontend can render mule rings etc. as
    # visually distinct clusters.
    community: int


class GraphEdgeOut(BaseModel):
    source: str
    target: str
    type: str  # matches app.models.enums.GraphEdgeType's values
    weight: float


class GraphOut(BaseModel):
    nodes: list[GraphNodeOut]
    edges: list[GraphEdgeOut]
