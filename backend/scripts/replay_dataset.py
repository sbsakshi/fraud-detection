"""Replay the synthetic dataset through the live API.

Seeds every account via POST /accounts, then sends transactions in timestamp
order through POST /transactions, so each one is scored by the real rules,
ML models and graph and gets real reason codes and cases -- the same path a
production transaction would take. Nothing here writes to the database
directly.

    python scripts/replay_dataset.py --limit 5000              # backfill history
    python scripts/replay_dataset.py --limit 500 --rate 5      # trickle: 5 txn/s
    python scripts/replay_dataset.py --offset 5000 --limit 500 --rate 5 --shift-to-now

--shift-to-now moves every timestamp by one constant so the newest replayed
transaction is "now"; relative gaps (what velocity rules and the graph care
about) are unchanged, but the dashboard's recent-activity views are populated.
Re-running is safe: accounts that already exist (409) are skipped.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

DATA_DIR = Path(__file__).resolve().parents[2] / "ml" / "data"


def parse_ts(raw: str) -> datetime:
    return datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)


def seed_accounts(client: httpx.Client, used_upis: set[str] | None) -> None:
    with open(DATA_DIR / "accounts.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    if used_upis is not None:
        rows = [r for r in rows if r["upi_id"] in used_upis]
    created = existing = 0
    for r in rows:
        resp = client.post(
            "/accounts",
            json={
                "upi_id": r["upi_id"],
                "account_number": r["account_number"],
                "ifsc_code": r["ifsc_code"],
                "owner_name": r["owner_name"],
                "bank_name": r["bank_name"],
                "account_type": r["account_type"],
                "device_id": r["device_id"] or None,
                "true_label": r["true_label"] or None,
                "is_active": r["is_active"] == "True",
                "created_at": parse_ts(r["created_at"]).isoformat(),
            },
        )
        if resp.status_code == 201:
            created += 1
        elif resp.status_code == 409:
            existing += 1
        else:
            sys.exit(f"POST /accounts failed for {r['upi_id']}: {resp.status_code} {resp.text}")
    print(f"accounts: {created} created, {existing} already present")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--offset", type=int, default=0, help="skip this many transactions (in time order)")
    ap.add_argument("--limit", type=int, default=1000, help="how many transactions to send")
    ap.add_argument("--rate", type=float, default=0, help="transactions per second; 0 = as fast as possible")
    ap.add_argument("--shift-to-now", action="store_true")
    args = ap.parse_args()

    with open(DATA_DIR / "transactions.csv", newline="") as f:
        txns = sorted(csv.DictReader(f), key=lambda r: r["created_at"])
    txns = txns[args.offset : args.offset + args.limit]
    if not txns:
        sys.exit("no transactions in that range")

    shift = timedelta(0)
    if args.shift_to_now:
        shift = datetime.now(timezone.utc) - parse_ts(txns[-1]["created_at"])

    with httpx.Client(base_url=args.api, timeout=60) as client:
        client.get("/health").raise_for_status()
        # Only seed accounts this slice touches -- 7k POSTs for a 200-txn demo is wasted time.
        used = {t["sender_upi_id"] for t in txns} | {t["receiver_upi_id"] for t in txns}
        seed_accounts(client, used)

        levels: dict[str, int] = {}
        started = time.monotonic()
        for i, t in enumerate(txns, 1):
            resp = client.post(
                "/transactions",
                json={
                    "sender_upi_id": t["sender_upi_id"],
                    "receiver_upi_id": t["receiver_upi_id"],
                    "amount": t["amount"],
                    "currency": t["currency"],
                    "device_id": t["device_id"],
                    "transaction_type": t["transaction_type"],
                    "status": t["status"],
                    "true_label": t["true_label"] or None,
                    "scenario": t["scenario"] or None,
                    "created_at": (parse_ts(t["created_at"]) + shift).isoformat(),
                },
            )
            if resp.status_code != 201:
                sys.exit(f"POST /transactions failed at #{i}: {resp.status_code} {resp.text}")
            level = resp.json()["risk_score"]["intervention_level"]
            levels[level] = levels.get(level, 0) + 1
            if args.rate > 0:
                time.sleep(max(0.0, started + i / args.rate - time.monotonic()))
            if i % 250 == 0 or i == len(txns):
                rate = i / (time.monotonic() - started)
                print(f"  {i}/{len(txns)} sent ({rate:.0f}/s)")

    print("intervention levels:", dict(sorted(levels.items())))


if __name__ == "__main__":
    main()
