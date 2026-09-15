"""Graph-native checks, producing reason codes in the same shape as `app.rules`.

Each `graph_rule_*` takes the graph *as of just before* the candidate
transaction plus a `GraphContext`, and returns a `GraphFinding` (or `None`).
`evaluate_graph` runs the full set and fuses contributions into one
`graph_score`, the same additive-capped-at-1.0 scheme
`app.rules.engine.evaluate_rules` uses for `rule_score` -- Phase 6 combines
all three into one fused score.
"""

from __future__ import annotations

from datetime import timedelta

import networkx as nx

from app.graph.analysis import (
    device_user_count,
    fraud_cluster_exposure,
    recent_counterparties,
    transaction_edge_count,
)
from app.graph.config import GraphConfig
from app.graph.schemas import GraphContext, GraphEngineResult, GraphFinding


def _is_fresh_burst(graph: nx.MultiDiGraph, account: str, direction: str, windowed: frozenset[str], since) -> bool:
    """Is `windowed` this account's *entire* in/out history so far, not just its recent slice?

    The discriminator a plain windowed fan-in count can't express on its
    own: a long-established, genuinely high-throughput hub (a popular
    merchant, an active individual) will cross a fan-in threshold within
    *some* recent window constantly just by being long-lived, while a mule
    collector is a freshly created account whose entire history *is* the
    burst -- comparing the windowed count against the account's all-time
    count so far (both computed from state strictly before this
    transaction, so this never peeks at the future) tells them apart
    without needing account-creation metadata this graph doesn't carry.
    """
    all_time = recent_counterparties(graph, account, direction, since=None)
    return len(all_time) == len(windowed)


def graph_rule_mule_collector_pattern(
    graph: nx.MultiDiGraph, ctx: GraphContext, config: GraphConfig
) -> GraphFinding | None:
    """Either side of this transaction already looks like a mule collector, *recently*, for the first time ever.

    Checks two distinct moments the mule_network scenario produces (see
    ml/synthetic/scenarios/mule_network.py): the sweep (sender has recently
    received from several people and is now sending out -- this transaction
    itself is the fan-out) and the fan-in (receiver already has outgoing
    history and is now receiving from yet another sender). Windowed to
    `collector_window_hours` *and* gated by `_is_fresh_burst`: unwindowed, or
    without that gate, most long-lived, ordinarily active accounts
    eventually satisfy "some fan-in threshold within some recent window" --
    what actually distinguishes a mule collector is that this recent
    activity is the account's *entire* history, not a slice of an
    established pattern.
    """
    txn = ctx.transaction
    since = txn.created_at - timedelta(hours=config.collector_window_hours)

    sender_fan_in = recent_counterparties(graph, txn.sender_upi_id, "in", since)
    if len(sender_fan_in) >= config.collector_min_fan_in and _is_fresh_burst(
        graph, txn.sender_upi_id, "in", sender_fan_in, since
    ):
        sender_fan_out = recent_counterparties(graph, txn.sender_upi_id, "out", since)
        return GraphFinding(
            code="mule_collector_pattern",
            template=(
                "{sender_upi_id} received from {fan_in} distinct senders in the last "
                "{window_hours:.0f}h (its entire history) and is now sweeping funds onward -- "
                "a mule-collector shape."
            ),
            details={
                "sender_upi_id": txn.sender_upi_id,
                "fan_in": len(sender_fan_in),
                "fan_out": len(sender_fan_out) + (0 if txn.receiver_upi_id in sender_fan_out else 1),
                "window_hours": config.collector_window_hours,
            },
            contribution=config.contribution_mule_collector,
        )

    receiver_fan_in = recent_counterparties(graph, txn.receiver_upi_id, "in", since)
    fan_in = len(receiver_fan_in) + (0 if txn.sender_upi_id in receiver_fan_in else 1)
    receiver_fan_out = recent_counterparties(graph, txn.receiver_upi_id, "out", since)
    if (
        fan_in >= config.collector_min_fan_in
        and len(receiver_fan_out) >= config.collector_min_fan_out
        and _is_fresh_burst(graph, txn.receiver_upi_id, "in", receiver_fan_in, since)
    ):
        return GraphFinding(
            code="mule_collector_pattern",
            template=(
                "{receiver_upi_id} has received from {fan_in} distinct senders and sent to "
                "{fan_out} distinct receivers in the last {window_hours:.0f}h (its entire history) "
                "-- a mule-collector shape."
            ),
            details={
                "receiver_upi_id": txn.receiver_upi_id,
                "fan_in": fan_in,
                "fan_out": len(receiver_fan_out),
                "window_hours": config.collector_window_hours,
            },
            contribution=config.contribution_mule_collector,
        )
    return None


def graph_rule_shared_device_ring(
    graph: nx.MultiDiGraph, ctx: GraphContext, config: GraphConfig
) -> GraphFinding | None:
    """Sender's device is already linked to several other accounts -- a mule-herder signature."""
    txn = ctx.transaction
    other_users = device_user_count(graph, txn.device_id, exclude=txn.sender_upi_id)
    if other_users < config.shared_device_account_threshold:
        return None
    return GraphFinding(
        code="shared_device_ring",
        template="Device {device_id} is linked to {count} other accounts besides {sender_upi_id}.",
        details={"device_id": txn.device_id, "count": other_users, "sender_upi_id": txn.sender_upi_id},
        contribution=config.contribution_shared_device_ring,
    )


def graph_rule_repeated_counterparty(
    graph: nx.MultiDiGraph, ctx: GraphContext, config: GraphConfig
) -> GraphFinding | None:
    """This sender/receiver pair has transacted unusually often *recently*.

    Windowed for the same reason as the collector pattern: 5 transactions
    between the same pair over 2 months is an ordinary recurring
    relationship (rent, a family member); 5 in a day is not.
    """
    txn = ctx.transaction
    since = txn.created_at - timedelta(hours=config.repeated_counterparty_window_hours)
    prior_count = transaction_edge_count(graph, txn.sender_upi_id, txn.receiver_upi_id, since=since)
    count = prior_count + 1  # this transaction included
    if count < config.repeated_counterparty_threshold:
        return None
    return GraphFinding(
        code="repeated_counterparty",
        template="{sender_upi_id} has sent to {receiver_upi_id} {count} times in the last {window_hours:.0f}h.",
        details={
            "sender_upi_id": txn.sender_upi_id,
            "receiver_upi_id": txn.receiver_upi_id,
            "count": count,
            "window_hours": config.repeated_counterparty_window_hours,
        },
        contribution=config.contribution_repeated_counterparty,
    )


def graph_rule_fraud_cluster_exposure(
    graph: nx.MultiDiGraph, ctx: GraphContext, config: GraphConfig
) -> GraphFinding | None:
    """Receiver is a short hop away from a known-fraud account (not *is* one -- see rules.known_fraud_beneficiary)."""
    txn = ctx.transaction
    exposure = fraud_cluster_exposure(
        graph, txn.receiver_upi_id, ctx.known_fraud_accounts, max_hops=config.fraud_exposure_max_hops
    )
    nearest_hop = exposure["nearest_hop"]
    if nearest_hop is None:
        return None
    contribution = min(1.0, config.contribution_fraud_exposure_base / nearest_hop)
    return GraphFinding(
        code="fraud_cluster_exposure",
        template="{receiver_upi_id} is {hops} hop(s) from a known-fraud account via transaction flow.",
        details={
            "receiver_upi_id": txn.receiver_upi_id,
            "hops": nearest_hop,
            "fraud_accounts": sorted(exposure["fraud_accounts_within_range"]),
        },
        contribution=contribution,
    )


ALL_GRAPH_RULES = (
    graph_rule_mule_collector_pattern,
    graph_rule_shared_device_ring,
    graph_rule_repeated_counterparty,
    graph_rule_fraud_cluster_exposure,
)


def evaluate_graph(
    graph: nx.MultiDiGraph, ctx: GraphContext, config: GraphConfig | None = None
) -> GraphEngineResult:
    """Run every graph check against `ctx` and fuse the results into one score."""
    config = config or GraphConfig()
    fired = tuple(result for rule in ALL_GRAPH_RULES if (result := rule(graph, ctx, config)) is not None)
    graph_score = min(1.0, sum(r.contribution for r in fired)) if fired else 0.0
    return GraphEngineResult(fired=fired, graph_score=graph_score)
