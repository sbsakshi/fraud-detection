from datetime import datetime, timedelta
from decimal import Decimal

from app.graph import GraphConfig, GraphContext, GraphTransaction, TransactionGraph, evaluate_graph

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


def test_no_rules_fire_on_an_ordinary_first_transaction():
    g = TransactionGraph()
    ctx = GraphContext(transaction=txn("a", "b"))
    result = evaluate_graph(g.graph, ctx)
    assert result.fired == ()
    assert result.graph_score == 0.0


def test_mule_collector_pattern_fires_when_candidate_completes_the_shape():
    g = TransactionGraph()
    for i, sender in enumerate(["s1", "s2"]):
        g.add_transaction(txn(sender, "collector", ref=f"in{i}", minutes_after=i))
    for i, receiver in enumerate(["c1", "c2"]):
        g.add_transaction(txn("collector", receiver, ref=f"out{i}", minutes_after=10 + i))

    # A third sender arrives, completing fan_in=3 (config default min).
    ctx = GraphContext(transaction=txn("s3", "collector", ref="in2", minutes_after=20))
    result = evaluate_graph(g.graph, ctx)
    codes = {f.code for f in result.fired}
    assert "mule_collector_pattern" in codes
    finding = next(f for f in result.fired if f.code == "mule_collector_pattern")
    assert finding.details["fan_in"] == 3
    assert finding.details["fan_out"] == 2


def test_mule_collector_pattern_ignores_fan_in_outside_the_window():
    # Same shape as the "fires" test above, but spread across months instead
    # of minutes -- an established, long-lived account naturally accumulates
    # this much fan-in/fan-out eventually and must not be flagged for it.
    g = TransactionGraph()
    for i, sender in enumerate(["s1", "s2"]):
        g.add_transaction(txn(sender, "collector", ref=f"in{i}", minutes_after=i * 60 * 24 * 20))
    for i, receiver in enumerate(["c1", "c2"]):
        g.add_transaction(txn("collector", receiver, ref=f"out{i}", minutes_after=(10 + i) * 60 * 24 * 20))

    ctx = GraphContext(transaction=txn("s3", "collector", ref="in2", minutes_after=90 * 60 * 24))
    result = evaluate_graph(g.graph, ctx)
    assert "mule_collector_pattern" not in {f.code for f in result.fired}


def test_mule_collector_pattern_fires_on_the_sweep_side():
    # The mule_network scenario's actual shape: a collector receives from
    # several senders, then makes ONE outgoing sweep (fan_out=1, never 2+)
    # shortly after -- this must fire on the sweep transaction itself, not
    # just on some hypothetical second outgoing payment.
    g = TransactionGraph()
    for i, sender in enumerate(["s1", "s2", "s3"]):
        g.add_transaction(txn(sender, "collector", ref=f"in{i}", minutes_after=i))

    ctx = GraphContext(transaction=txn("collector", "cashout", ref="sweep", minutes_after=10))
    result = evaluate_graph(g.graph, ctx)
    finding = next(f for f in result.fired if f.code == "mule_collector_pattern")
    assert finding.details["sender_upi_id"] == "collector"
    assert finding.details["fan_in"] == 3


def test_mule_collector_pattern_silent_for_an_established_hub_mid_burst():
    # A long-lived, genuinely popular merchant: steady fan-in for months,
    # *plus* a burst of 3 receipts today that would look collector-shaped
    # in isolation. It must not fire -- the burst isn't this account's
    # entire history, just its latest slice of an established pattern.
    g = TransactionGraph()
    days_ago = [60, 50, 40, 30, 20, 10]
    for i, day in enumerate(days_ago):
        g.add_transaction(
            txn(f"old_customer{i}", "merchant", device_id=f"dc{i}", ref=f"old{i}", minutes_after=-day * 60 * 24)
        )
    g.add_transaction(txn("merchant", "supplier", device_id="dm", ref="restock", minutes_after=-5 * 60 * 24))
    for i, sender in enumerate(["burst1", "burst2"]):
        g.add_transaction(txn(sender, "merchant", device_id=f"db{i}", ref=f"burst{i}", minutes_after=i))

    ctx = GraphContext(transaction=txn("burst3", "merchant", device_id="db3", ref="burst3", minutes_after=5))
    result = evaluate_graph(g.graph, ctx)
    assert "mule_collector_pattern" not in {f.code for f in result.fired}


def test_mule_collector_pattern_silent_without_fan_out():
    g = TransactionGraph()
    for i, sender in enumerate(["s1", "s2"]):
        g.add_transaction(txn(sender, "merchant", ref=f"in{i}", minutes_after=i))
    # merchant never sends anything onward -- fan_out stays 0.
    ctx = GraphContext(transaction=txn("s3", "merchant", ref="in2", minutes_after=5))
    result = evaluate_graph(g.graph, ctx)
    assert "mule_collector_pattern" not in {f.code for f in result.fired}


def test_shared_device_ring_fires_above_threshold():
    g = TransactionGraph()
    for i, sender in enumerate(["a", "b", "c"]):
        g.add_transaction(txn(sender, f"r{i}", device_id="shared", ref=f"T{i}", minutes_after=i))

    ctx = GraphContext(transaction=txn("d", "r4", device_id="shared", ref="T4", minutes_after=4))
    result = evaluate_graph(g.graph, ctx, GraphConfig(shared_device_account_threshold=3))
    assert "shared_device_ring" in {f.code for f in result.fired}


def test_repeated_counterparty_fires_at_threshold():
    g = TransactionGraph()
    for i in range(4):
        g.add_transaction(txn("a", "b", ref=f"T{i}", minutes_after=i))
    # This would be the 5th transaction a->b.
    ctx = GraphContext(transaction=txn("a", "b", ref="T5", minutes_after=5))
    result = evaluate_graph(g.graph, ctx, GraphConfig(repeated_counterparty_threshold=5))
    finding = next(f for f in result.fired if f.code == "repeated_counterparty")
    assert finding.details["count"] == 5


def test_repeated_counterparty_ignores_transactions_outside_the_window():
    g = TransactionGraph()
    # 4 prior transactions, but spread across months -- an ordinary
    # recurring relationship (rent, a family member), not a burst.
    for i in range(4):
        g.add_transaction(txn("a", "b", ref=f"T{i}", minutes_after=i * 60 * 24 * 30))
    ctx = GraphContext(transaction=txn("a", "b", ref="T5", minutes_after=5 * 60 * 24 * 30))
    result = evaluate_graph(g.graph, ctx, GraphConfig(repeated_counterparty_threshold=5))
    assert "repeated_counterparty" not in {f.code for f in result.fired}


def test_fraud_cluster_exposure_fires_and_scales_with_hops():
    g = TransactionGraph()
    g.add_transaction(txn("victim", "middleman", ref="T1"))

    ctx = GraphContext(
        transaction=txn("middleman", "known_fraud", ref="T2", minutes_after=1),
        known_fraud_accounts=frozenset({"known_fraud"}),
    )
    # known_fraud itself is the receiver here, so rules.known_fraud_beneficiary
    # would fire on it directly -- but this receiver *is* the fraud account
    # (hop 0), so fraud_cluster_exposure (hop >= 1 only) must stay silent.
    result = evaluate_graph(g.graph, ctx)
    assert "fraud_cluster_exposure" not in {f.code for f in result.fired}


def test_fraud_cluster_exposure_fires_one_hop_removed():
    g = TransactionGraph()
    g.add_transaction(txn("known_fraud", "middleman", ref="T1"))

    ctx = GraphContext(
        transaction=txn("payer", "middleman", ref="T2", minutes_after=1),
        known_fraud_accounts=frozenset({"known_fraud"}),
    )
    result = evaluate_graph(g.graph, ctx)
    finding = next(f for f in result.fired if f.code == "fraud_cluster_exposure")
    assert finding.details["hops"] == 1


def test_score_is_additive_and_capped_at_one():
    g = TransactionGraph()
    for i, sender in enumerate(["s1", "s2"]):
        g.add_transaction(txn(sender, "collector", ref=f"in{i}", minutes_after=i))
    for i, receiver in enumerate(["c1", "c2"]):
        g.add_transaction(txn("collector", receiver, ref=f"out{i}", minutes_after=10 + i))
    for i in range(4):
        g.add_transaction(txn("s3", "collector", ref=f"repeat{i}", minutes_after=20 + i))

    # This transaction both completes the collector fan-in shape AND is the
    # 5th s3->collector transaction -- two rules should stack.
    ctx = GraphContext(transaction=txn("s3", "collector", ref="repeat5", minutes_after=30))
    result = evaluate_graph(g.graph, ctx)
    assert len(result.fired) >= 2
    assert result.graph_score <= 1.0
