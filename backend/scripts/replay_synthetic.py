"""Replay the synthetic dataset through the live API, so the dashboard has real scores.

Creates every account in `ml/data/accounts.csv` (with its real `created_at`,
which the account-age features depend on) via `POST /accounts`, then posts
`ml/data/transactions.csv` in chronological order to `POST /transactions`.

    python scripts/replay_synthetic.py                       # against http://localhost:8000
    python scripts/replay_synthetic.py --limit 2000          # first 2,000 transactions only
    python scripts/replay_synthetic.py --base-url http://backend:8000

Accounts that already exist (409) are skipped, so a partial replay can be
resumed with `--skip N`. Scoring is per-request and pulls each account's full
history, so a full 75k-row replay takes a while; `--limit` is the usual way
to get a populated dashboard quickly.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import httpx

DATA_DIR = Path(__file__).resolve().parents[2] / "ml" / "data"


def _iso(ts: str) -> str:
    return ts.replace(" ", "T") + ("" if ts.endswith("Z") or "+" in ts else "Z")


def account_payload(row: dict) -> dict:
    return {
        "upi_id": row["upi_id"],
        "account_number": row["account_number"],
        "ifsc_code": row["ifsc_code"],
        "owner_name": row["owner_name"],
        "bank_name": row["bank_name"],
        "account_type": row["account_type"],
        "device_id": row["device_id"] or None,
        "true_label": row["true_label"] or None,
        "is_active": row["is_active"] == "True",
        "created_at": _iso(row["created_at"]),
    }


def transaction_payload(row: dict) -> dict:
    return {
        "sender_upi_id": row["sender_upi_id"],
        "receiver_upi_id": row["receiver_upi_id"],
        "amount": row["amount"],
        "currency": row["currency"],
        "device_id": row["device_id"],
        "transaction_type": row["transaction_type"],
        "status": row["status"],
        "true_label": row["true_label"] or None,
        "scenario": row["scenario"] or None,
        "created_at": _iso(row["created_at"]),
    }


def load_transactions(skip: int, limit: int | None) -> list[dict]:
    with open(DATA_DIR / "transactions.csv", newline="", encoding="utf-8") as f:
        rows = sorted(csv.DictReader(f), key=lambda r: r["created_at"])
    rows = rows[skip:]
    return rows[:limit] if limit is not None else rows


def replay(client: httpx.Client, skip: int = 0, limit: int | None = None, progress_every: int = 500) -> list[dict]:
    with open(DATA_DIR / "accounts.csv", newline="", encoding="utf-8") as f:
        accounts = list(csv.DictReader(f))
    created = 0
    for row in accounts:
        resp = client.post("/accounts", json=account_payload(row))
        if resp.status_code == 201:
            created += 1
        elif resp.status_code != 409:
            raise RuntimeError(f"POST /accounts failed for {row['upi_id']}: {resp.status_code} {resp.text}")
    print(f"Accounts: {created} created, {len(accounts) - created} already present")

    results = []
    transactions = load_transactions(skip, limit)
    for i, row in enumerate(transactions, 1):
        resp = client.post("/transactions", json=transaction_payload(row))
        if resp.status_code != 201:
            raise RuntimeError(f"POST /transactions failed for {row['txn_ref']}: {resp.status_code} {resp.text}")
        results.append({"txn_ref": row["txn_ref"], **resp.json()})
        if i % progress_every == 0:
            print(f"  scored {i}/{len(transactions)}")
    print(f"Transactions: {len(results)} scored")
    return results


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--skip", type=int, default=0, help="skip the first N transactions (resume)")
    parser.add_argument("--limit", type=int, default=None, help="replay at most N transactions")
    args = parser.parse_args(argv)
    with httpx.Client(base_url=args.base_url, timeout=60) as client:
        replay(client, skip=args.skip, limit=args.limit)


if __name__ == "__main__":
    sys.exit(main())
