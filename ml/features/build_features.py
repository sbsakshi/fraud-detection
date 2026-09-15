"""CLI: build the Phase 4 feature table from the Phase 2 synthetic dataset.

Usage (from the repo root, using ml/.venv):
    ml/.venv/Scripts/python.exe -m ml.features.build_features

Reads ml/data/{accounts,transactions}.csv, writes ml/data/features.csv.
"""

from pathlib import Path

import pandas as pd

from ml.features.engineering import build_features

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def main() -> None:
    accounts = pd.read_csv(DATA_DIR / "accounts.csv")
    transactions = pd.read_csv(DATA_DIR / "transactions.csv")

    features = build_features(transactions, accounts)

    out_path = DATA_DIR / "features.csv"
    features.to_csv(out_path, index=False)

    print(f"Wrote {len(features)} rows x {len(features.columns)} columns to {out_path}")
    print(f"Fraud rate: {features['is_fraud'].mean():.2%} ({features['is_fraud'].sum()} / {len(features)})")


if __name__ == "__main__":
    main()
