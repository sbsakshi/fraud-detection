"""Sanity-check the Phase 5 graph engine against the Phase 2 synthetic dataset.

Two parts:
1. Per-transaction reason codes, replayed chronologically exactly like
   `evaluate_rules_on_synthetic.py` -- same "only history strictly before
   this transaction" discipline.
2. Whole-graph mule-cluster detection on the fully-built graph: how many of
   the accounts the synthetic generator actually labeled `mule_network`
   (collectors + cashouts -- see ml/synthetic/scenarios/mule_network.py) does
   `detect_collector_candidates`/`detect_communities` find?

Usage (from backend/, with the backend venv active):
    python scripts/evaluate_graph_on_synthetic.py
"""

import csv
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.graph import GraphConfig, GraphContext, GraphTransaction, TransactionGraph, evaluate_graph  # noqa: E402
from app.graph.analysis import detect_collector_candidates, detect_communities  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "ml" / "data"
ESCALATION_THRESHOLD = 0.5


def load_transactions() -> list[dict]:
    with open(DATA_DIR / "transactions.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row["created_at"] = datetime.fromisoformat(row["created_at"])
        row["amount"] = Decimal(row["amount"])
    rows.sort(key=lambda r: r["created_at"])
    return rows


def load_account_labels() -> dict[str, str]:
    with open(DATA_DIR / "accounts.csv", newline="", encoding="utf-8") as f:
        return {row["upi_id"]: row["true_label"] for row in csv.DictReader(f)}


def replay(rows: list[dict], config: GraphConfig) -> TransactionGraph:
    tg = TransactionGraph()
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    fired_code_counts: dict[str, int] = defaultdict(int)

    for row in rows:
        candidate = GraphTransaction(
            txn_ref=row["txn_ref"],
            sender_upi_id=row["sender_upi_id"],
            receiver_upi_id=row["receiver_upi_id"],
            amount=row["amount"],
            device_id=row["device_id"],
            created_at=row["created_at"],
        )
        # No live case system yet to source a real fraud watchlist from
        # (that's Phase 6+) -- fraud_cluster_exposure is exercised by its
        # unit tests instead, so it's left empty here.
        result = evaluate_graph(tg.graph, GraphContext(transaction=candidate), config)

        label = row["true_label"] or (row["scenario"] or "normal")
        bucket = counts[label]
        bucket[2] += 1
        if result.fired:
            bucket[0] += 1
            for r in result.fired:
                fired_code_counts[r.code] += 1
        if result.graph_score >= ESCALATION_THRESHOLD:
            bucket[1] += 1

        tg.add_transaction(candidate)

    print(
        f"{'label':<24}{'any rule':>10}{'>= ' + str(ESCALATION_THRESHOLD):>10}{'total':>8}"
        f"{'any rate':>11}{'thresh rate':>13}"
    )
    for label, (any_fired, above_threshold, total) in sorted(counts.items(), key=lambda kv: kv[0]):
        any_rate = any_fired / total if total else 0.0
        thresh_rate = above_threshold / total if total else 0.0
        print(f"{label:<24}{any_fired:>10}{above_threshold:>10}{total:>8}{any_rate:>10.1%}{thresh_rate:>13.1%}")

    print("\nReason codes fired, by rule:")
    for code, count in sorted(fired_code_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {code:<32}{count:>8}")

    return tg


def evaluate_mule_cluster_detection(tg: TransactionGraph, account_labels: dict[str, str], config: GraphConfig) -> None:
    true_mule_accounts = {upi for upi, label in account_labels.items() if label == "mule_network"}
    print(f"\n=== Mule-cluster detection ({len(true_mule_accounts)} true mule_network accounts) ===")

    for label, span_hours in [("unwindowed (any span)", None), ("tight-span (<= 6h)", 6.0)]:
        candidates = detect_collector_candidates(
            tg.graph,
            min_fan_in=config.collector_min_fan_in,
            min_fan_out=config.collector_min_fan_out,
            max_span_hours=span_hours,
        )
        detected = {c.account for c in candidates}
        true_positives = detected & true_mule_accounts
        precision = len(true_positives) / len(detected) if detected else 0.0
        recall = len(true_positives) / len(true_mule_accounts) if true_mule_accounts else 0.0
        print(f"detect_collector_candidates [{label}]: {len(detected)} flagged, "
              f"{len(true_positives)} true mule accounts among them")
        print(f"  precision={precision:.1%}  recall={recall:.1%}  (recall is against ALL mule_network "
              f"accounts, collectors *and* cashouts -- see note below)")

    communities = detect_communities(tg.graph, min_size=3)
    covered = set()
    for community in communities:
        if community & true_mule_accounts:
            covered |= community & true_mule_accounts
    print(f"detect_communities: {len(communities)} communities found (size >= 3); "
          f"{len(covered)}/{len(true_mule_accounts)} true mule accounts land in one")


def main() -> None:
    rows = load_transactions()
    account_labels = load_account_labels()
    print(f"Loaded {len(rows)} transactions from {DATA_DIR / 'transactions.csv'}\n")

    config = GraphConfig()
    tg = replay(rows, config)
    evaluate_mule_cluster_detection(tg, account_labels, config)
    print(
        "\nNote: mule_network's cashout accounts (see "
        "ml/synthetic/scenarios/mule_network.py) only ever *receive* -- they "
        "have no fan-out at all, so detect_collector_candidates (which needs "
        "both fan-in and fan-out) can't and shouldn't catch them; only the "
        "collectors are structurally detectable this way."
    )


if __name__ == "__main__":
    main()
