"""Sanity-check the Phase 3 rules engine against the Phase 2 synthetic dataset.

Replays `ml/data/transactions.csv` chronologically, evaluating each
transaction against only the history strictly before it (no peeking at
the future), and reports how often the rules flag each ground-truth
scenario. Not the Phase 8 ablation study itself -- there's no ML or
graph score to compare against yet -- just evidence the rules module
has real signal before wiring it into anything live.

Usage (from backend/, with the backend venv active):
    python scripts/evaluate_rules_on_synthetic.py
"""

import csv
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.rules import RuleConfig, RuleContext, RuleTransaction, evaluate_rules  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "ml" / "data"


def load_transactions() -> list[dict]:
    with open(DATA_DIR / "transactions.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row["created_at"] = datetime.fromisoformat(row["created_at"])
        row["amount"] = Decimal(row["amount"])
    rows.sort(key=lambda r: r["created_at"])
    return rows


def main() -> None:
    rows = load_transactions()
    print(f"Loaded {len(rows)} transactions from {DATA_DIR / 'transactions.csv'}\n")

    config = RuleConfig()
    sender_history: dict[str, list[RuleTransaction]] = defaultdict(list)
    receiver_senders: dict[str, list[tuple[str, datetime]]] = defaultdict(list)

    # A single rule firing (e.g. first_time_beneficiary alone, contribution
    # 0.15) isn't a meaningful flag on its own -- report both "any rule
    # fired at all" and "score crossed a would-actually-escalate bar", since
    # the two tell very different stories about false-positive rate.
    ESCALATION_THRESHOLD = 0.5

    # label -> [any_fired, above_threshold, total]. "" (empty true_label)
    # covers both plain normal traffic and innocent_bystander rows (which
    # carry a scenario but no true_label, since the transaction itself isn't
    # fraud).
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    fired_code_counts: dict[str, int] = defaultdict(int)

    for row in rows:
        candidate = RuleTransaction(
            sender_upi_id=row["sender_upi_id"],
            receiver_upi_id=row["receiver_upi_id"],
            amount=row["amount"],
            created_at=row["created_at"],
        )
        ctx = RuleContext(
            transaction=candidate,
            sender_prior_transactions=sender_history[candidate.sender_upi_id],
            receiver_prior_senders=receiver_senders[candidate.receiver_upi_id],
            # No live case system yet to source a real watchlist from (that's
            # Phase 6+) -- known_fraud_beneficiary is exercised by its unit
            # tests instead, so it's left empty here.
        )
        result = evaluate_rules(ctx, config)

        label = row["true_label"] or (row["scenario"] or "normal")
        bucket = counts[label]
        bucket[2] += 1
        if result.fired:
            bucket[0] += 1
            for r in result.fired:
                fired_code_counts[r.code] += 1
        if result.rule_score >= ESCALATION_THRESHOLD:
            bucket[1] += 1

        sender_history[candidate.sender_upi_id].append(candidate)
        receiver_senders[candidate.receiver_upi_id].append((candidate.sender_upi_id, candidate.created_at))

    print(
        f"{'label':<24}{'any rule':>10}{'>= ' + str(ESCALATION_THRESHOLD):>10}{'total':>8}"
        f"{'any rate':>11}{'thresh rate':>13}"
    )
    for label, (any_fired, above_threshold, total) in sorted(counts.items(), key=lambda kv: kv[0]):
        any_rate = any_fired / total if total else 0.0
        thresh_rate = above_threshold / total if total else 0.0
        print(
            f"{label:<24}{any_fired:>10}{above_threshold:>10}{total:>8}"
            f"{any_rate:>10.1%}{thresh_rate:>13.1%}"
        )

    print("\nReason codes fired, by rule:")
    for code, count in sorted(fired_code_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {code:<32}{count:>8}")


if __name__ == "__main__":
    main()
