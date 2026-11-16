"""Pydantic request/response models for the API layer.

Kept separate from the SQLAlchemy models in `app.models`: the DB schema and
the wire format are allowed to diverge (e.g. `TransactionScoreOut` surfaces
`sender_upi_id`/`receiver_upi_id`, which aren't columns on `Transaction`
itself -- they come from the resolved `Account` rows).
"""

from __future__ import annotations

import enum
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
    # When the account was opened at the bank. Account-age features depend on
    # it, so a replay of historical data must send it; omitted = now.
    created_at: datetime | None = None


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


class AccountBrief(BaseModel):
    """What a contact picker needs. Deliberately omits `true_label`, the synthetic ground truth."""

    model_config = ConfigDict(from_attributes=True)

    upi_id: str
    owner_name: str
    bank_name: str
    account_type: AccountType
    device_id: str | None


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
    # `model_version` starts with pydantic's reserved `model_` prefix; it is a plain data field here.
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    rule_score: float | None
    ml_score: float | None
    graph_score: float | None
    fused_score: float
    confidence: float
    intervention_level: InterventionLevel
    model_version: str | None = None
    ladder_version: str | None = None


class CaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: CaseStatus
    severity: CaseSeverity


class FraudConfirmation(BaseModel):
    actor: str = Field(min_length=1, max_length=128)  # the investigator confirming it
    note: str | None = None


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
    # Observable signals only -- unlike `true_label` (synthetic ground truth an
    # analyst would never have), these come from scoring and investigator action.
    max_score: float | None = None  # highest fused score on any transaction touching this account
    known_fraud: bool = False  # receiver of a case an investigator confirmed as fraud


class GraphEdgeOut(BaseModel):
    source: str
    target: str
    type: str  # matches app.models.enums.GraphEdgeType's values
    weight: float


class GraphOut(BaseModel):
    nodes: list[GraphNodeOut]
    edges: list[GraphEdgeOut]


# --- Case workflow ----------------------------------------------------------


class CaseResolution(str, enum.Enum):
    """Why an investigator closed a case. Recorded on the closing event."""

    FRAUD_CONFIRMED = "fraud_confirmed"
    FALSE_POSITIVE = "false_positive"
    CUSTOMER_VERIFIED = "customer_verified"


class CaseEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    description: str | None
    actor: str
    created_at: datetime


class CaseListItemOut(BaseModel):
    id: int
    status: CaseStatus
    severity: CaseSeverity
    assigned_to: str | None
    created_at: datetime
    updated_at: datetime
    transaction_id: int
    sender_upi_id: str
    receiver_upi_id: str
    amount: Decimal
    currency: str
    fused_score: float
    intervention_level: InterventionLevel
    top_reason: str | None  # rendered later by the client from code/template; here just the code


class CaseDetailOut(BaseModel):
    id: int
    status: CaseStatus
    severity: CaseSeverity
    assigned_to: str | None
    summary: str | None
    created_at: datetime
    updated_at: datetime
    transaction: TransactionScoreOut
    events: list[CaseEventOut]


class CaseUpdate(BaseModel):
    """Assign and/or move a case. Closing goes through POST /cases/{id}/close, which needs a resolution."""

    actor: str = Field(min_length=1, max_length=128)
    status: CaseStatus | None = None
    assigned_to: str | None = Field(default=None, max_length=128)
    unassign: bool = False
    note: str | None = None


class CaseNoteCreate(BaseModel):
    actor: str = Field(min_length=1, max_length=128)
    note: str = Field(min_length=1)


class CaseClose(BaseModel):
    actor: str = Field(min_length=1, max_length=128)
    resolution: CaseResolution
    note: str | None = None


# --- Account profile ----------------------------------------------------------


class AccountProfileOut(BaseModel):
    upi_id: str
    owner_name: str
    bank_name: str
    ifsc_code: str
    account_type: AccountType
    device_id: str | None
    is_active: bool
    created_at: datetime
    known_fraud: bool
    transactions_sent: int
    transactions_received: int
    total_sent: Decimal
    total_received: Decimal
    counterparties: int
    max_score: float | None
    flagged_count: int  # transactions above `inform` that involve this account
    open_cases: int
    shared_device_accounts: list[str]  # other accounts seen on the same device_id
