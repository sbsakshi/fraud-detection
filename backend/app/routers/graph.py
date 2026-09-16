"""Phase 7's read-only view into the live money-movement graph, for the
frontend's network visualization.

Reads the same process-wide `TransactionGraph` `app.scoring.pipeline`
already builds up as it scores transactions (see `app.graph.live_graph`'s
module docstring for why that graph lives in memory rather than being
reconstructed from `graph_edges` on every request) -- this endpoint never
touches the database for graph structure, only to enrich each node with its
account's `true_label`/`account_type`.
"""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.graph.analysis import detect_communities
from app.graph.live_graph import get_transaction_graph
from app.models.account import Account
from app.schemas import GraphEdgeOut, GraphNodeOut, GraphOut

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("", response_model=GraphOut)
def get_graph_snapshot(db: Session = Depends(get_db)) -> GraphOut:
    graph = get_transaction_graph().graph
    upi_ids = list(graph.nodes)
    if not upi_ids:
        return GraphOut(nodes=[], edges=[])

    accounts_by_upi = {
        a.upi_id: a for a in db.query(Account).filter(Account.upi_id.in_(upi_ids)).all()
    }

    # min_size=1 (rather than detect_communities' fraud-hunting default of 3)
    # so every node gets a community id, including singletons -- this is
    # purely a stable coloring key for the frontend's clusters, not a
    # "this is a suspicious ring" claim the way Phase 5's use of it is.
    community_of: dict[str, int] = {}
    for i, community in enumerate(detect_communities(graph, min_size=1)):
        for upi_id in community:
            community_of[upi_id] = i

    nodes = [
        GraphNodeOut(
            id=upi_id,
            true_label=accounts_by_upi[upi_id].true_label if upi_id in accounts_by_upi else None,
            account_type=accounts_by_upi[upi_id].account_type if upi_id in accounts_by_upi else None,
            community=community_of.get(upi_id, -1),
        )
        for upi_id in upi_ids
    ]

    # Collapse parallel `transaction` edges (one per payment, so a
    # frequently-traded pair has many) into a single edge weighted by count --
    # the frontend renders one line per (source, target, type), not a stack
    # of overlapping duplicates. `shared_device`/`repeated_counterparty`
    # edges are already deduplicated at the source (app.graph.builder keys
    # them per device / per pair), so max() here is just a safe no-op for them.
    edge_weight: dict[tuple[str, str, str], float] = defaultdict(float)
    for u, v, data in graph.edges(data=True):
        edge_type = data.get("edge_type", "transaction")
        key = (u, v, edge_type)
        if edge_type == "transaction":
            edge_weight[key] += 1.0
        else:
            edge_weight[key] = max(edge_weight[key], float(data.get("weight", 1.0)))

    edges = [
        GraphEdgeOut(source=u, target=v, type=edge_type, weight=weight)
        for (u, v, edge_type), weight in edge_weight.items()
    ]

    return GraphOut(nodes=nodes, edges=edges)
