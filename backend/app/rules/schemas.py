"""Data shapes shared by every rule and by the engine that runs them."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Sequence

from app.models.enums import ReasonCodeSource
from app.scoring.schemas import ReasonCodeResult


@dataclass(frozen=True)
class RuleTransaction:
    """The minimal view of a transaction a rule needs.

    Deliberately not the SQLAlchemy `Transaction` model: rules run just
    as well over a CSV replay (Phase 3, before a live ingest endpoint
    exists) as over live ORM rows (from Phase 6 onward), as long as the
    caller adapts either into this shape.
    """

    sender_upi_id: str
    receiver_upi_id: str
    amount: Decimal
    created_at: datetime


@dataclass(frozen=True)
class RuleContext:
    """Everything a rule set needs to score one candidate transaction.

    `sender_prior_transactions` and `receiver_prior_senders` must only
    contain history strictly *before* `transaction` — the caller is
    responsible for not leaking the future into a rule check.
    """

    transaction: RuleTransaction
    sender_prior_transactions: Sequence[RuleTransaction] = field(default_factory=tuple)
    # (sender_upi_id, created_at) for prior transactions received by this
    # transaction's receiver; the fan-in rule applies its own time window.
    receiver_prior_senders: Sequence[tuple[str, datetime]] = field(default_factory=tuple)
    known_fraud_beneficiaries: frozenset[str] = frozenset()


@dataclass(frozen=True)
class FiredRule(ReasonCodeResult):
    """One rule's output -- a `ReasonCodeResult` defaulted to `source=RULE`.

    See `app.scoring.schemas.ReasonCodeResult` for the shape shared with
    the ML and graph signal sources.
    """

    source: ReasonCodeSource = ReasonCodeSource.RULE


@dataclass(frozen=True)
class RuleEngineResult:
    fired: tuple[FiredRule, ...]
    rule_score: float
