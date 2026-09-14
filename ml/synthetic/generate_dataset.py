"""Generate the full synthetic Finsight dataset: base "normal" traffic plus the
six labelled fraud-scenario injectors, written once to ml/data/.

Run from the repo root:
    ml/.venv/Scripts/python.exe -m ml.synthetic.generate_dataset
"""

from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker

from ml.synthetic.base_traffic import generate_accounts, generate_normal_transactions
from ml.synthetic.config import NUM_ACCOUNTS, NUM_BASE_TRANSACTIONS, OUTPUT_DIR, SEED
from ml.synthetic.helpers import Counter
from ml.synthetic.scenarios import (
    account_takeover,
    gambling_network,
    innocent_bystander,
    layering_chain,
    mule_network,
    scam_recipient,
)

# Order matters: innocent_bystander needs a pool of already-labelled accounts to
# be adjacent to, so it must run after everything that produces fraud labels.
LABELLED_SCENARIOS = [
    scam_recipient,
    mule_network,
    layering_chain,
    account_takeover,
    gambling_network,
]

ACCOUNT_COLUMNS = [
    "upi_id",
    "account_number",
    "ifsc_code",
    "owner_name",
    "bank_name",
    "account_type",
    "device_id",
    "true_label",
    "is_active",
    "created_at",
]

TRANSACTION_COLUMNS = [
    "txn_ref",
    "sender_upi_id",
    "receiver_upi_id",
    "amount",
    "currency",
    "device_id",
    "transaction_type",
    "status",
    "true_label",
    "scenario",
    "created_at",
]


def _apply_account_updates(accounts_df: pd.DataFrame, updates: dict) -> pd.DataFrame:
    if not updates:
        return accounts_df
    mapped = accounts_df["upi_id"].map(updates)
    accounts_df["true_label"] = mapped.combine_first(accounts_df["true_label"])
    return accounts_df


def generate(seed: int = SEED) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    Faker.seed(seed)
    faker = Faker("en_IN")

    account_counter = Counter()
    txn_counter = Counter()

    print(f"Generating {NUM_ACCOUNTS} base accounts...")
    accounts_df = generate_accounts(rng, faker, NUM_ACCOUNTS, account_counter)

    print(f"Generating {NUM_BASE_TRANSACTIONS} base transactions...")
    txn_frames = [generate_normal_transactions(rng, accounts_df, NUM_BASE_TRANSACTIONS, txn_counter)]

    for module in LABELLED_SCENARIOS:
        print(f"Injecting scenario: {module.SCENARIO}...")
        new_accounts_df, new_txns_df, account_updates = module.inject(
            rng, faker, accounts_df, account_counter, txn_counter
        )
        accounts_df = _apply_account_updates(accounts_df, account_updates)
        if len(new_accounts_df):
            accounts_df = pd.concat([accounts_df, new_accounts_df], ignore_index=True)
        if len(new_txns_df):
            txn_frames.append(new_txns_df)

    print(f"Injecting scenario: {innocent_bystander.SCENARIO}...")
    fraud_pool_upis = accounts_df.loc[accounts_df["true_label"].notna(), "upi_id"].to_numpy()
    bystander_txns_df, account_updates = innocent_bystander.inject(rng, accounts_df, fraud_pool_upis, txn_counter)
    accounts_df = _apply_account_updates(accounts_df, account_updates)
    if len(bystander_txns_df):
        txn_frames.append(bystander_txns_df)

    transactions_df = pd.concat(txn_frames, ignore_index=True).sort_values("created_at").reset_index(drop=True)

    accounts_df = accounts_df[ACCOUNT_COLUMNS].reset_index(drop=True)
    transactions_df = transactions_df[TRANSACTION_COLUMNS]

    return accounts_df, transactions_df


def _print_summary(accounts_df: pd.DataFrame, transactions_df: pd.DataFrame) -> None:
    print("\n=== Dataset summary ===")
    print(f"Accounts: {len(accounts_df)}")
    print(f"Transactions: {len(transactions_df)}")
    print("\nAccount true_label distribution:")
    print(accounts_df["true_label"].fillna("normal").value_counts().to_string())
    print("\nTransaction true_label distribution:")
    print(transactions_df["true_label"].fillna("normal").value_counts().to_string())
    print("\nTransaction scenario distribution:")
    print(transactions_df["scenario"].fillna("base_traffic").value_counts().to_string())


def main() -> None:
    accounts_df, transactions_df = generate()
    _print_summary(accounts_df, transactions_df)

    output_dir = Path(__file__).resolve().parent.parent / OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    accounts_path = output_dir / "accounts.csv"
    transactions_path = output_dir / "transactions.csv"
    accounts_df.to_csv(accounts_path, index=False)
    transactions_df.to_csv(transactions_path, index=False)
    print(f"\nWrote {accounts_path}")
    print(f"Wrote {transactions_path}")


if __name__ == "__main__":
    main()
