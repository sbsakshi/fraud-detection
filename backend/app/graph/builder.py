"""Incrementally build the money-movement graph, one transaction at a time.

`TransactionGraph.add_transaction` writes the three edge types the schema's
`graph_edges` table expects (`GraphEdgeType`): a `transaction` edge for the
payment itself, `shared_device` edges linking any accounts that have used
the same device, and a `repeated_counterparty` edge once a sender/receiver
pair crosses a repeat threshold. Call `analysis.py` functions *before*
`add_transaction` for a given transaction if the check must only see prior
history -- same no-peeking-at-the-future discipline as `app.rules` and
`ml.features.engineering`.
"""

from __future__ import annotations

import networkx as nx

from app.graph.schemas import EdgeWrite, GraphTransaction

# When to materialize a `repeated_counterparty` *edge* in the graph
# structure itself -- independent of `GraphConfig.repeated_counterparty_threshold`,
# which governs when `engine.py` fires a reason code (a scoring decision, not
# a schema one). They default to the same number by coincidence, not by contract.
REPEATED_COUNTERPARTY_THRESHOLD = 5


class TransactionGraph:
    def __init__(self) -> None:
        self.graph = nx.MultiDiGraph()
        # device_id -> accounts seen using it, stored as whole-graph metadata
        # (not a node attribute) so `analysis.device_user_count` can answer
        # "who else has used this device" in O(device's own users), not by
        # scanning every node in the graph.
        self.graph.graph["device_users"] = {}
        self._pair_txn_count: dict[tuple[str, str], int] = {}

    def add_transaction(self, txn: GraphTransaction) -> list[EdgeWrite]:
        """Apply `txn` to the graph; return every edge created or updated by it.

        The return value is what `app.graph.live_graph` mirrors into the
        `graph_edges` table -- callers that don't need DB persistence (tests,
        the CSV-replay evaluation scripts) can just ignore it.
        """
        writes = [
            EdgeWrite(
                edge_type="transaction",
                source_upi_id=txn.sender_upi_id,
                target_upi_id=txn.receiver_upi_id,
                weight=1.0,
                transaction_ref=txn.txn_ref,
            )
        ]
        self.graph.add_edge(
            txn.sender_upi_id,
            txn.receiver_upi_id,
            key=f"transaction:{txn.txn_ref}",
            edge_type="transaction",
            txn_ref=txn.txn_ref,
            amount=float(txn.amount),
            created_at=txn.created_at,
        )

        device_users = self.graph.graph["device_users"]
        prior_device_users = device_users.get(txn.device_id, set())
        for other in prior_device_users - {txn.sender_upi_id}:
            # Undirected relationship, stored as edges both ways; keyed by
            # device so accounts sharing >1 device don't collide, but reusing
            # the same device again updates rather than duplicates the edge.
            self.graph.add_edge(
                txn.sender_upi_id, other, key=f"shared_device:{txn.device_id}",
                edge_type="shared_device", device_id=txn.device_id,
            )
            self.graph.add_edge(
                other, txn.sender_upi_id, key=f"shared_device:{txn.device_id}",
                edge_type="shared_device", device_id=txn.device_id,
            )
            writes.append(
                EdgeWrite(edge_type="shared_device", source_upi_id=txn.sender_upi_id, target_upi_id=other, weight=1.0)
            )
        device_users.setdefault(txn.device_id, set()).add(txn.sender_upi_id)

        pair = (txn.sender_upi_id, txn.receiver_upi_id)
        count = self._pair_txn_count.get(pair, 0) + 1
        self._pair_txn_count[pair] = count
        if count >= REPEATED_COUNTERPARTY_THRESHOLD:
            # One materialized edge per pair, weight updated in place --
            # not one row per repeat, which would grow unbounded for a
            # heavily-repeated pair.
            self.graph.add_edge(
                txn.sender_upi_id, txn.receiver_upi_id, key="repeated_counterparty",
                edge_type="repeated_counterparty", weight=float(count),
            )
            writes.append(
                EdgeWrite(
                    edge_type="repeated_counterparty",
                    source_upi_id=txn.sender_upi_id,
                    target_upi_id=txn.receiver_upi_id,
                    weight=float(count),
                )
            )
        return writes
