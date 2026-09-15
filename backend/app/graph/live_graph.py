"""The process-wide, in-memory `TransactionGraph`, mirrored into `graph_edges`.

One `TransactionGraph` per running backend process, built up as transactions
are scored -- `app.graph.analysis`'s queries (fan-in/fan-out,
`fraud_cluster_exposure`, etc.) need an actual graph structure to walk, not
just rows in a table, so keeping this in memory is what makes them fast.
The `graph_edges` table is still written on every transaction (via
`persist_edge_writes`) so the facts survive a restart and other consumers
(a future dashboard, an ad-hoc SQL query) can read them without needing to
talk to this process -- rebuilding the in-memory graph from that table on
startup, so a restart doesn't silently reset every account's history, is a
known gap this phase doesn't close (see backend/README.md).

`shared_device` edges are inherently symmetric (two accounts share a
device) but `graph_edges` rows are directed (`source_account_id` ->
`target_account_id`); only one direction is persisted per relationship, so
a query for "who does account X share a device with" needs to check both
`source_account_id = X` and `target_account_id = X`.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.accounts import get_account_by_upi
from app.graph.builder import TransactionGraph
from app.graph.schemas import EdgeWrite
from app.models.enums import GraphEdgeType
from app.models.graph_edge import GraphEdge

_graph: TransactionGraph | None = None


def get_transaction_graph() -> TransactionGraph:
    global _graph
    if _graph is None:
        _graph = TransactionGraph()
    return _graph


def reset_transaction_graph() -> None:
    """Drop the in-memory graph. Test-only -- production has no reason to call this."""
    global _graph
    _graph = None


def persist_edge_writes(db: Session, writes: list[EdgeWrite], transaction_id: int | None) -> None:
    """Mirror `TransactionGraph.add_transaction`'s return value into `graph_edges`."""
    for write in writes:
        source = get_account_by_upi(db, write.source_upi_id)
        target = get_account_by_upi(db, write.target_upi_id)
        if source is None or target is None:
            continue  # shouldn't happen -- both accounts must already exist to have transacted
        db.add(
            GraphEdge(
                source_account_id=source.id,
                target_account_id=target.id,
                edge_type=GraphEdgeType(write.edge_type),
                transaction_id=transaction_id if write.edge_type == "transaction" else None,
                weight=write.weight,
            )
        )
