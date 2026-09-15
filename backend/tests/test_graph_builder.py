from datetime import datetime, timedelta
from decimal import Decimal

from app.graph import GraphTransaction, TransactionGraph

NOW = datetime(2026, 1, 1, 12, 0, 0)


def txn(sender, receiver, device_id="d1", ref=None, minutes_after=0.0, amount="100.00") -> GraphTransaction:
    return GraphTransaction(
        txn_ref=ref or f"{sender}->{receiver}@{minutes_after}",
        sender_upi_id=sender,
        receiver_upi_id=receiver,
        amount=Decimal(amount),
        device_id=device_id,
        created_at=NOW + timedelta(minutes=minutes_after),
    )


def test_transaction_edge_recorded():
    g = TransactionGraph()
    g.add_transaction(txn("a", "b", ref="T1"))
    data = g.graph.get_edge_data("a", "b")
    assert "transaction:T1" in data
    assert data["transaction:T1"]["edge_type"] == "transaction"
    assert data["transaction:T1"]["amount"] == 100.0


def test_shared_device_edge_created_between_accounts_using_same_device():
    g = TransactionGraph()
    g.add_transaction(txn("a", "x", device_id="shared", ref="T1"))
    g.add_transaction(txn("b", "y", device_id="shared", ref="T2"))

    data_ab = g.graph.get_edge_data("a", "b") or {}
    data_ba = g.graph.get_edge_data("b", "a") or {}
    assert "shared_device:shared" in data_ab
    assert "shared_device:shared" in data_ba  # both directions


def test_no_shared_device_edge_for_first_use():
    g = TransactionGraph()
    g.add_transaction(txn("a", "x", device_id="d1", ref="T1"))
    assert g.graph.get_edge_data("a", "x") is not None
    # "a" has no shared_device neighbors yet -- it's the only account to have used d1.
    assert not any(
        d.get("edge_type") == "shared_device" for _, _, d in g.graph.out_edges("a", data=True)
    )


def test_repeated_counterparty_edge_appears_only_after_threshold():
    g = TransactionGraph()
    for i in range(4):
        g.add_transaction(txn("a", "b", ref=f"T{i}", minutes_after=i))
    data = g.graph.get_edge_data("a", "b") or {}
    assert "repeated_counterparty" not in data

    g.add_transaction(txn("a", "b", ref="T5", minutes_after=5))  # 5th transaction crosses the threshold
    data = g.graph.get_edge_data("a", "b") or {}
    assert "repeated_counterparty" in data
    assert data["repeated_counterparty"]["weight"] == 5.0


def test_add_transaction_reports_which_edges_it_wrote():
    g = TransactionGraph()
    writes = g.add_transaction(txn("a", "b", ref="T1"))
    assert len(writes) == 1
    assert writes[0].edge_type == "transaction"
    assert writes[0].source_upi_id == "a"
    assert writes[0].target_upi_id == "b"

    # First use of a device reports no shared_device write (nothing to connect to yet)...
    first_use_writes = g.add_transaction(txn("c", "x", device_id="shared", ref="T2"))
    assert not any(w.edge_type == "shared_device" for w in first_use_writes)

    # ...but the second distinct account using the same device does.
    second_use_writes = g.add_transaction(txn("d", "y", device_id="shared", ref="T3"))
    shared = [w for w in second_use_writes if w.edge_type == "shared_device"]
    assert len(shared) == 1
    assert {shared[0].source_upi_id, shared[0].target_upi_id} == {"c", "d"}


def test_repeated_counterparty_edge_updates_weight_not_duplicated():
    g = TransactionGraph()
    for i in range(7):
        g.add_transaction(txn("a", "b", ref=f"T{i}", minutes_after=i))
    data = g.graph.get_edge_data("a", "b") or {}
    assert data["repeated_counterparty"]["weight"] == 7.0
    # Still exactly one repeated_counterparty key, not seven.
    assert list(data.keys()).count("repeated_counterparty") == 1
