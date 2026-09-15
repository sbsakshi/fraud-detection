from datetime import datetime, timedelta
from decimal import Decimal

from app.graph import GraphTransaction, TransactionGraph
from app.graph.analysis import (
    detect_collector_candidates,
    detect_communities,
    fan_in_out,
    fraud_cluster_exposure,
    shared_device_neighbors,
    trace_money_trail,
    transaction_edge_count,
)

NOW = datetime(2026, 1, 1, 12, 0, 0)


def txn(sender, receiver, device_id="d1", ref=None, minutes_after=0.0) -> GraphTransaction:
    return GraphTransaction(
        txn_ref=ref or f"{sender}->{receiver}@{minutes_after}",
        sender_upi_id=sender,
        receiver_upi_id=receiver,
        amount=Decimal("100.00"),
        device_id=device_id,
        created_at=NOW + timedelta(minutes=minutes_after),
    )


def test_fan_in_out_counts_distinct_counterparties():
    g = TransactionGraph()
    for i, sender in enumerate(["s1", "s2", "s3"]):
        g.add_transaction(txn(sender, "collector", ref=f"in{i}", minutes_after=i))
    for i, receiver in enumerate(["c1", "c2"]):
        g.add_transaction(txn("collector", receiver, ref=f"out{i}", minutes_after=10 + i))

    fan_in, fan_out = fan_in_out(g.graph, "collector")
    assert fan_in == 3
    assert fan_out == 2


def test_fan_in_out_unknown_account_is_zero():
    g = TransactionGraph()
    assert fan_in_out(g.graph, "nobody") == (0, 0)


def test_shared_device_neighbors():
    g = TransactionGraph()
    g.add_transaction(txn("a", "x", device_id="shared", ref="T1"))
    g.add_transaction(txn("b", "y", device_id="shared", ref="T2"))
    g.add_transaction(txn("c", "z", device_id="shared", ref="T3"))
    assert shared_device_neighbors(g.graph, "c") == frozenset({"a", "b"})


def test_transaction_edge_count():
    g = TransactionGraph()
    for i in range(3):
        g.add_transaction(txn("a", "b", ref=f"T{i}", minutes_after=i))
    assert transaction_edge_count(g.graph, "a", "b") == 3
    assert transaction_edge_count(g.graph, "b", "a") == 0


def test_detect_collector_candidates_finds_the_mule_shape():
    g = TransactionGraph()
    for i, sender in enumerate(["s1", "s2", "s3", "s4"]):
        g.add_transaction(txn(sender, "collector", ref=f"in{i}", minutes_after=i))
    for i, receiver in enumerate(["c1", "c2"]):
        g.add_transaction(txn("collector", receiver, ref=f"out{i}", minutes_after=10 + i))
    # A plain merchant: lots of fan-in, no fan-out at all -- must not qualify.
    for i, sender in enumerate(["m1", "m2", "m3", "m4", "m5"]):
        g.add_transaction(txn(sender, "merchant", ref=f"m{i}", minutes_after=i))

    candidates = detect_collector_candidates(g.graph, min_fan_in=3, min_fan_out=2)
    accounts = {c.account for c in candidates}
    assert "collector" in accounts


def test_detect_collector_candidates_max_span_excludes_a_long_lived_hub():
    g = TransactionGraph()
    # A collector-shaped account, but its fan-in and fan-out are spread
    # across months -- an established hub, not a fresh mule ring.
    for i, sender in enumerate(["s1", "s2", "s3"]):
        g.add_transaction(txn(sender, "hub", device_id=f"dh{i}", ref=f"in{i}", minutes_after=i * 60 * 24 * 30))
    g.add_transaction(txn("hub", "somewhere", device_id="do", ref="out0", minutes_after=200 * 60 * 24))

    unwindowed = detect_collector_candidates(g.graph, min_fan_in=3, min_fan_out=1)
    assert "hub" in {c.account for c in unwindowed}

    span_limited = detect_collector_candidates(g.graph, min_fan_in=3, min_fan_out=1, max_span_hours=6.0)
    assert "hub" not in {c.account for c in span_limited}


def test_detect_communities_groups_a_tightly_connected_ring_together():
    g = TransactionGraph()
    ring = ["h1", "h2", "h3", "h4"]
    # Every pair in the ring transacts with every other -- densely connected,
    # unlike a bare cycle/path (which louvain can legitimately split in half).
    i = 0
    for a in ring:
        for b in ring:
            if a != b:
                g.add_transaction(txn(a, b, ref=f"hop{i}", minutes_after=i))
                i += 1
    # An unrelated pair, isolated from the ring.
    g.add_transaction(txn("x", "y", ref="unrelated", minutes_after=100))

    communities = detect_communities(g.graph, min_size=3)
    assert any(set(ring) <= community for community in communities)


def test_fraud_cluster_exposure_finds_nearest_hop():
    g = TransactionGraph()
    g.add_transaction(txn("victim", "middleman", ref="T1"))
    g.add_transaction(txn("middleman", "known_fraud", ref="T2", minutes_after=1))

    exposure = fraud_cluster_exposure(g.graph, "middleman", frozenset({"known_fraud"}), max_hops=2)
    assert exposure["nearest_hop"] == 1

    exposure_far = fraud_cluster_exposure(g.graph, "victim", frozenset({"known_fraud"}), max_hops=2)
    assert exposure_far["nearest_hop"] == 2


def test_fraud_cluster_exposure_none_when_out_of_range():
    g = TransactionGraph()
    g.add_transaction(txn("a", "b", ref="T1"))
    exposure = fraud_cluster_exposure(g.graph, "a", frozenset({"far_away_fraud"}), max_hops=1)
    assert exposure["nearest_hop"] is None


def test_fraud_cluster_exposure_excludes_hop_zero():
    g = TransactionGraph()
    g.add_transaction(txn("a", "known_fraud", ref="T1"))
    # "known_fraud" itself is on the list -- that's rules.known_fraud_beneficiary's
    # job (hop 0), not this function's.
    exposure = fraud_cluster_exposure(g.graph, "known_fraud", frozenset({"known_fraud"}), max_hops=2)
    assert exposure["nearest_hop"] is None


def test_trace_money_trail_follows_forward_time_only():
    g = TransactionGraph()
    g.add_transaction(txn("a", "b", ref="T1", minutes_after=0))
    g.add_transaction(txn("b", "c", ref="T2", minutes_after=5))
    # This one happens *before* a->b, so it must not appear as a downstream hop of a->b.
    g.add_transaction(txn("b", "d", ref="T3", minutes_after=-10))

    paths = trace_money_trail(g.graph, "a", after=NOW, max_hops=3)
    flattened = {tuple(p) for p in paths}
    assert ("a", "b") in flattened
    assert ("a", "b", "c") in flattened
    assert not any("d" in p for p in paths)


def test_trace_money_trail_respects_max_hops():
    g = TransactionGraph()
    for i in range(5):
        g.add_transaction(txn(f"n{i}", f"n{i+1}", ref=f"T{i}", minutes_after=i))
    paths = trace_money_trail(g.graph, "n0", after=NOW, max_hops=2)
    assert max(len(p) - 1 for p in paths) == 2
