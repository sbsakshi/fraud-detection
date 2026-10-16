"""The in-memory graph survives a restart: rebuilding it from the transactions
table must reproduce exactly what live scoring built incrementally."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.graph.live_graph import get_transaction_graph, rebuild_transaction_graph, reset_transaction_graph
from app.scoring.pipeline import score_and_persist_transaction

T0 = datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc)


def _snapshot(graph) -> tuple:
    edges = sorted(
        (u, v, k, data.get("edge_type"), data.get("amount"), data.get("weight"))
        for u, v, k, data in graph.edges(keys=True, data=True)
    )
    devices = {d: frozenset(users) for d, users in graph.graph["device_users"].items()}
    return edges, devices


def test_rebuild_matches_incremental_graph(db_session, make_account):
    reset_transaction_graph()
    try:
        accounts = {
            name: make_account(f"{name}@bank", device_id=f"dev-{name}", created_at=T0 - timedelta(days=400))
            for name in ("alice", "bob", "carol", "mule")
        }
        payments = [
            ("alice", "bob", "120.00", "dev-alice"),
            ("bob", "carol", "80.00", "dev-bob"),
            ("carol", "mule", "500.00", "dev-carol"),
            ("alice", "mule", "700.00", "dev-shared"),
            ("bob", "mule", "650.00", "dev-shared"),  # second account on one device
        ] + [("alice", "bob", "10.00", "dev-alice")] * 5  # crosses the repeated-counterparty threshold
        for i, (s, r, amount, device) in enumerate(payments):
            score_and_persist_transaction(
                db_session, sender=accounts[s], receiver=accounts[r], amount=Decimal(amount), currency="INR",
                device_id=device, transaction_type="P2P", created_at=T0 + timedelta(minutes=10 * i),
            )
        live = _snapshot(get_transaction_graph().graph)

        reset_transaction_graph()  # simulate a restart
        assert get_transaction_graph().graph.number_of_edges() == 0

        replayed = rebuild_transaction_graph(db_session)
        assert replayed == len(payments)
        assert _snapshot(get_transaction_graph().graph) == live
    finally:
        reset_transaction_graph()


def test_rebuild_on_empty_database(db_session):
    reset_transaction_graph()
    try:
        assert rebuild_transaction_graph(db_session) == 0
        assert get_transaction_graph().graph.number_of_nodes() == 0
    finally:
        reset_transaction_graph()
