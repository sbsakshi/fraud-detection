"""Phase 5 — graph intelligence.

`builder.TransactionGraph` maintains the money-movement graph (transaction,
shared-device, and repeated-counterparty edges); `analysis.py` has read-only
queries over it (fan-in/fan-out, mule-collector candidates, community
detection, fraud-cluster exposure, money-trail tracing); `engine.py` turns
a handful of those queries into reason codes, the same shape
`app.rules.engine` produces, fused into one `graph_score`.
"""

from app.graph.builder import TransactionGraph
from app.graph.config import GraphConfig
from app.graph.engine import evaluate_graph
from app.graph.schemas import (
    CollectorCandidate,
    EdgeWrite,
    GraphContext,
    GraphEngineResult,
    GraphFinding,
    GraphTransaction,
)

__all__ = [
    "TransactionGraph",
    "GraphConfig",
    "GraphContext",
    "GraphTransaction",
    "GraphFinding",
    "GraphEngineResult",
    "CollectorCandidate",
    "EdgeWrite",
    "evaluate_graph",
]
