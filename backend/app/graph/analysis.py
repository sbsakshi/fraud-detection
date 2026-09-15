"""Read-only queries over a `TransactionGraph`.

Every function here takes the raw `networkx.MultiDiGraph` (`TransactionGraph.graph`),
not the wrapper -- these are pure graph queries, independent of how the
graph got built.
"""

from __future__ import annotations

from datetime import datetime

import networkx as nx

from app.graph.schemas import CollectorCandidate


def recent_counterparties(
    graph: nx.MultiDiGraph, account: str, direction: str, since: datetime | None = None
) -> frozenset[str]:
    """Distinct counterparties this account has received from (`"in"`) or sent to (`"out"`).

    `since`, when given, restricts this to `transaction` edges with
    `created_at >= since` -- fan-in/fan-out only means something as a fraud
    signal within a *recent* window; nearly every long-lived account
    eventually accumulates fan-in >= 3 and fan-out >= 2 over its whole
    lifetime just from ordinary use, which an unwindowed count can't tell
    apart from a tight, suspicious burst.
    """
    if account not in graph:
        return frozenset()
    edges = graph.in_edges(account, data=True) if direction == "in" else graph.out_edges(account, data=True)
    other_index = 0 if direction == "in" else 1
    return frozenset(
        e[other_index]
        for e in edges
        if e[2].get("edge_type") == "transaction" and (since is None or e[2]["created_at"] >= since)
    )


def fan_in_out(graph: nx.MultiDiGraph, account: str, since: datetime | None = None) -> tuple[int, int]:
    """Distinct counterparties this account has received from / sent to, via `transaction` edges.

    See `recent_counterparties` for what `since` does and why it matters.
    """
    fan_in = recent_counterparties(graph, account, "in", since)
    fan_out = recent_counterparties(graph, account, "out", since)
    return len(fan_in), len(fan_out)


def shared_device_neighbors(graph: nx.MultiDiGraph, account: str) -> frozenset[str]:
    """Other accounts linked to this one by a `shared_device` edge.

    Only reflects devices `account` has *already* used -- a device's first
    user has no `shared_device` edge to walk yet (nothing to connect to). To
    ask "how many accounts have used device X" for a sender about to use it
    for the first time, use `device_user_count` instead.
    """
    if account not in graph:
        return frozenset()
    return frozenset(
        v for _, v, d in graph.out_edges(account, data=True) if d.get("edge_type") == "shared_device"
    )


def device_user_count(graph: nx.MultiDiGraph, device_id: str, exclude: str | None = None) -> int:
    """How many distinct accounts have used `device_id` so far, `exclude` (typically the current sender) aside.

    Reads `TransactionGraph`'s `device_users` whole-graph index rather than
    scanning every node -- a device's *first* user has no `shared_device`
    edge yet (nothing to connect to), so this can't be answered by walking
    edges from one account's own perspective alone.
    """
    users = graph.graph.get("device_users", {}).get(device_id, set())
    return len(users - {exclude}) if exclude is not None else len(users)


def transaction_edge_count(
    graph: nx.MultiDiGraph, sender: str, receiver: str, since: datetime | None = None
) -> int:
    """How many `transaction` edges already exist sender -> receiver (optionally, only recent ones)."""
    edge_data = graph.get_edge_data(sender, receiver) or {}
    return sum(
        1
        for d in edge_data.values()
        if d.get("edge_type") == "transaction" and (since is None or d["created_at"] >= since)
    )


def _activity_span_hours(graph: nx.MultiDiGraph, account: str) -> float:
    """Hours between this account's first and last `transaction` edge (either direction)."""
    timestamps = [
        d["created_at"] for _, _, d in graph.in_edges(account, data=True) if d.get("edge_type") == "transaction"
    ] + [
        d["created_at"] for _, _, d in graph.out_edges(account, data=True) if d.get("edge_type") == "transaction"
    ]
    if len(timestamps) < 2:
        return 0.0
    return (max(timestamps) - min(timestamps)).total_seconds() / 3600.0


def detect_collector_candidates(
    graph: nx.MultiDiGraph,
    min_fan_in: int = 3,
    min_fan_out: int = 2,
    since: datetime | None = None,
    max_span_hours: float | None = None,
) -> list[CollectorCandidate]:
    """Nodes whose fan-in *and* fan-out both cross the given thresholds.

    Directly mirrors the mule_network scenario's own definition (fan-in
    from many sources to a collector, then fan-out to cashout accounts) --
    a targeted heuristic rather than generic community detection, so a
    result is immediately interpretable as "this looks like a collector,"
    not just "this cluster is unusually dense."

    Fan-in/fan-out alone, unwindowed, sweeps up any long-lived account that
    eventually accumulates enough activity. `max_span_hours`, when given,
    additionally requires that account's *entire* transaction history (first
    edge to last) fit within that span -- a genuinely long-lived hub won't,
    the way `app.graph.engine`'s per-transaction rule uses `_is_fresh_burst`
    for the same reason. `since` restricts which edges count in the first
    place, for "only within this window, was there a burst" instead of
    "ever."
    """
    candidates = []
    for account in graph.nodes:
        sources = recent_counterparties(graph, account, "in", since)
        destinations = recent_counterparties(graph, account, "out", since)
        if len(sources) < min_fan_in or len(destinations) < min_fan_out:
            continue
        if max_span_hours is not None and _activity_span_hours(graph, account) > max_span_hours:
            continue
        candidates.append(
            CollectorCandidate(
                account=account,
                fan_in=len(sources),
                fan_out=len(destinations),
                sources=sources,
                destinations=destinations,
            )
        )
    return candidates


def detect_communities(graph: nx.MultiDiGraph, min_size: int = 3) -> list[frozenset[str]]:
    """Broader mule-*ring* clustering via community detection on transaction flow.

    Complements `detect_collector_candidates` (which finds one node with a
    distinctive shape) with looser groupings -- a layering chain, for
    instance, has no single high-fan-in/fan-out hub but is still a tight
    community of accounts that mostly only transact with each other.
    """
    txn_edges = [(u, v) for u, v, d in graph.edges(data=True) if d.get("edge_type") == "transaction"]
    undirected = nx.Graph()
    undirected.add_edges_from(txn_edges)
    communities = nx.algorithms.community.louvain_communities(undirected, seed=42)
    return [frozenset(c) for c in communities if len(c) >= min_size]


def fraud_cluster_exposure(
    graph: nx.MultiDiGraph, account: str, known_fraud_accounts: frozenset[str], max_hops: int = 2
) -> dict:
    """How close `account` is to a known-fraud account, via `transaction` edges either direction.

    Deliberately excludes hop 0 (`account` itself being on the list) -- that
    exact case is `app.rules.engine.rule_known_fraud_beneficiary`'s job;
    this is the complementary "paid someone who paid a known bad actor"
    signal a single-transaction rule can't see at all.
    """
    if not known_fraud_accounts or account not in graph or account in known_fraud_accounts:
        # No watchlist means this can never find anything -- skip the BFS
        # entirely rather than walking the whole neighborhood for nothing.
        return {"nearest_hop": None, "fraud_accounts_within_range": frozenset()}

    visited = {account}
    frontier = [account]
    found: dict[str, int] = {}
    for hop in range(1, max_hops + 1):
        next_frontier = []
        for node in frontier:
            neighbors = {u for u, _, d in graph.in_edges(node, data=True) if d.get("edge_type") == "transaction"}
            neighbors |= {v for _, v, d in graph.out_edges(node, data=True) if d.get("edge_type") == "transaction"}
            for n in neighbors - visited:
                visited.add(n)
                next_frontier.append(n)
                if n in known_fraud_accounts:
                    found[n] = hop
        if found:
            # BFS explores hop by hop, so the first hop where anything
            # turns up is necessarily the nearest one -- no need to keep
            # expanding past it just to enumerate every farther match too.
            break
        frontier = next_frontier
        if not frontier:
            break

    nearest_hop = min(found.values()) if found else None
    return {"nearest_hop": nearest_hop, "fraud_accounts_within_range": frozenset(found)}


def trace_money_trail(
    graph: nx.MultiDiGraph, start_account: str, after: datetime, max_hops: int = 3
) -> list[list[str]]:
    """Downstream paths money sent to/from `start_account` could have followed.

    Follows `transaction` edges forward in time only (`created_at >= after`,
    strictly increasing hop to hop) -- money can't legally arrive somewhere
    before it left the previous hop, so a path that goes backward in time is
    not a real money trail. Returns every simple path up to `max_hops`
    forward hops, `start_account` included.
    """
    paths: list[list[str]] = []

    def dfs(node: str, since: datetime, path: list[str]) -> None:
        if len(path) - 1 >= max_hops:
            return
        out_edges = [
            (v, d["created_at"])
            for _, v, d in graph.out_edges(node, data=True)
            if d.get("edge_type") == "transaction" and d["created_at"] >= since
        ]
        for next_node, sent_at in sorted(out_edges, key=lambda x: x[1]):
            if next_node in path:  # keep paths simple, no cycles
                continue
            new_path = path + [next_node]
            paths.append(new_path)
            dfs(next_node, sent_at, new_path)

    if start_account in graph:
        dfs(start_account, after, [start_account])
    return paths
