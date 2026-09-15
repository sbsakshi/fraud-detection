"""Data shapes for the graph module."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.models.enums import ReasonCodeSource
from app.scoring.schemas import ReasonCodeResult


@dataclass(frozen=True)
class GraphTransaction:
    """The minimal view of a transaction the graph builder needs.

    Same DB-agnostic idea as `app.rules.schemas.RuleTransaction`: works
    identically over a CSV replay (Phase 5, no ingest endpoint yet) or over
    live ORM rows the moment Phase 6 wires this into a scoring endpoint.
    """

    txn_ref: str
    sender_upi_id: str
    receiver_upi_id: str
    amount: Decimal
    device_id: str
    created_at: datetime


@dataclass(frozen=True)
class GraphFinding(ReasonCodeResult):
    """One graph check's output -- a `ReasonCodeResult` defaulted to `source=GRAPH`."""

    source: ReasonCodeSource = ReasonCodeSource.GRAPH


@dataclass(frozen=True)
class GraphContext:
    """Everything the graph engine needs to score one candidate transaction.

    `graph` must reflect state strictly *before* `transaction` -- call
    `TransactionGraph.add_transaction` only after evaluating, same
    no-peeking-at-the-future discipline as `app.rules.RuleContext`.
    """

    transaction: GraphTransaction
    known_fraud_accounts: frozenset[str] = frozenset()


@dataclass(frozen=True)
class GraphEngineResult:
    fired: tuple[GraphFinding, ...]
    graph_score: float


@dataclass(frozen=True)
class EdgeWrite:
    """One edge `TransactionGraph.add_transaction` created or updated in-memory.

    Returned so a caller with DB access (`app.graph.live_graph`) can mirror
    the same edge into the `graph_edges` table -- the in-memory graph and
    the table are two views of the same facts, not two sources of truth.
    """

    edge_type: str  # matches app.models.enums.GraphEdgeType's values
    source_upi_id: str
    target_upi_id: str
    weight: float
    transaction_ref: str | None = None  # set only for edge_type="transaction"


@dataclass(frozen=True)
class CollectorCandidate:
    """A node whose fan-in and fan-out both cross the mule-collector thresholds."""

    account: str
    fan_in: int
    fan_out: int
    sources: frozenset[str]
    destinations: frozenset[str]
