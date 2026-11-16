"""Tune fusion weights and the intervention ladder on held-out synthetic data.

Replays `ml/data/transactions.csv` chronologically through the rules and graph
engines (history strictly before each transaction, as in the other evaluation
scripts), scores each row with the trained ML artifacts, then:

1. splits the post-burn-in rows chronologically, using the same fractions the
   model recorded in `model_metadata.json` (60% train / 20% validation / 20%
   test);
2. picks fusion weights by validation PR-AUC of the fused score;
3. picks each ladder level's `min_score` as the lowest value keeping legitimate
   traffic flagged at-or-above that level under a false-positive target;
4. reports three configurations on the untouched test split:
   A. as shipped (current weights and ladder),
   B. current weights, retuned ladder (isolates the ladder effect),
   C. tuned weights, retuned ladder.

Only validation and test rows are scored for tuning/reporting, since the ML
model trained on the first 60%. The replay has no investigator-confirmed fraud,
so `known_fraud_beneficiary` and `fraud_cluster_exposure` never fire here; the
weight search therefore keeps a minimum weight for every engine.

Usage (from backend/, backend venv active, DYLD_FALLBACK_LIBRARY_PATH set as in dev.sh):
    python scripts/tune_fusion.py
    python scripts/tune_fusion.py --models-dir /path/to/other/models --output report.json
    python scripts/tune_fusion.py --write-config      # overwrite scoring/intervention_config.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.graph import GraphContext, GraphTransaction, TransactionGraph, evaluate_graph  # noqa: E402
from app.rules import RuleContext, RuleTransaction, evaluate_rules  # noqa: E402
from app.scoring.config import CONFIG_PATH, load_config  # noqa: E402
from app.scoring.fusion import fuse_scores  # noqa: E402
from app.scoring.tuning import LEVEL_ORDER, apply_ladder, tier_report, tune_min_scores, weight_grid  # noqa: E402

REPO_ROOT = BACKEND_DIR.parent
DATA_DIR = REPO_ROOT / "ml" / "data"
DEFAULT_MODELS_DIR = REPO_ROOT / "ml" / "models"
SCORE_CACHE = DATA_DIR / "rule_graph_scores.csv"

# Max share of legitimate traffic (normal + look-alikes) flagged at-or-above each level.
# These are product choices about acceptable friction: warn is a banner, verify is
# step-up auth, hold delays the payment, restrict and escalate open investigator cases.
DEFAULT_FPR_TARGETS = {"warn": 0.05, "verify": 0.01, "hold": 0.003, "restrict": 0.001, "escalate": 0.0005}


def replay_rule_graph_scores() -> pd.DataFrame:
    """rule_score and graph_score for every transaction, with no peeking at the future."""
    if SCORE_CACHE.exists():
        return pd.read_csv(SCORE_CACHE)

    with open(DATA_DIR / "transactions.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row["created_at"] = datetime.fromisoformat(row["created_at"])
        row["amount"] = Decimal(row["amount"])
    rows.sort(key=lambda r: r["created_at"])

    sender_history: dict[str, list[RuleTransaction]] = defaultdict(list)
    receiver_senders: dict[str, list[tuple[str, datetime]]] = defaultdict(list)
    graph = TransactionGraph()
    out = []
    for i, row in enumerate(rows):
        rule_txn = RuleTransaction(
            sender_upi_id=row["sender_upi_id"],
            receiver_upi_id=row["receiver_upi_id"],
            amount=row["amount"],
            created_at=row["created_at"],
        )
        rule_result = evaluate_rules(
            RuleContext(
                transaction=rule_txn,
                sender_prior_transactions=sender_history[rule_txn.sender_upi_id],
                receiver_prior_senders=receiver_senders[rule_txn.receiver_upi_id],
            )
        )
        graph_txn = GraphTransaction(
            txn_ref=row["txn_ref"],
            sender_upi_id=row["sender_upi_id"],
            receiver_upi_id=row["receiver_upi_id"],
            amount=row["amount"],
            device_id=row["device_id"],
            created_at=row["created_at"],
        )
        graph_result = evaluate_graph(graph.graph, GraphContext(transaction=graph_txn))
        out.append((row["txn_ref"], rule_result.rule_score, graph_result.graph_score))

        sender_history[rule_txn.sender_upi_id].append(rule_txn)
        receiver_senders[rule_txn.receiver_upi_id].append((rule_txn.sender_upi_id, rule_txn.created_at))
        graph.add_transaction(graph_txn)
        if (i + 1) % 15000 == 0:
            print(f"  replayed {i + 1:,}/{len(rows):,}", file=sys.stderr)

    scores = pd.DataFrame(out, columns=["txn_ref", "rule_score", "graph_score"])
    scores.to_csv(SCORE_CACHE, index=False)
    return scores


def load_scored_frame(models_dir: Path) -> tuple[pd.DataFrame, dict]:
    metadata = json.loads((models_dir / "model_metadata.json").read_text())
    feats = pd.read_csv(DATA_DIR / "features.csv", dtype={"true_label": "string", "scenario": "string"})
    feats["created_at"] = pd.to_datetime(feats["created_at"], utc=True, format="ISO8601")
    feats = feats.sort_values("created_at", kind="stable").reset_index(drop=True)
    feats["label"] = feats["true_label"].fillna(feats["scenario"]).fillna("normal")

    cols = metadata["feature_columns"]
    xgb = joblib.load(models_dir / "xgboost.joblib")
    calibrator = joblib.load(models_dir / "calibrator.joblib")
    feats["ml_score"] = calibrator.predict(xgb.predict_proba(feats[cols])[:, 1])

    feats = feats.merge(replay_rule_graph_scores(), on="txn_ref", how="left")
    return feats, metadata


def split(df: pd.DataFrame, metadata: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    cfg = metadata["split"]
    df = df[df["created_at"] >= pd.Timestamp(cfg["burn_in_before"], tz="UTC")].reset_index(drop=True)
    n = len(df)
    a, b = int(n * cfg["train_frac"]), int(n * (cfg["train_frac"] + cfg["val_frac"]))
    return df.iloc[a:b].reset_index(drop=True), df.iloc[b:].reset_index(drop=True)


def fuse_frame(df: pd.DataFrame, weights: tuple[float, float, float]) -> tuple[np.ndarray, np.ndarray]:
    w = {"rule": weights[0], "ml": weights[1], "graph": weights[2]}
    fused, confidence = [], []
    for rule, ml, graph in zip(df["rule_score"], df["ml_score"], df["graph_score"]):
        result = fuse_scores(rule, ml, graph, w)
        fused.append(result.fused_score)
        confidence.append(result.confidence)
    return np.array(fused), np.array(confidence)


def confidence_only(df: pd.DataFrame) -> np.ndarray:
    # Confidence depends on which engines fired and how much they agree, not on the weights.
    return np.array(
        [fuse_scores(r, m, g).confidence for r, m, g in zip(df["rule_score"], df["ml_score"], df["graph_score"])]
    )


def fused_vectorised(df: pd.DataFrame, weights: tuple[float, float, float]) -> np.ndarray:
    return np.round(
        weights[0] * df["rule_score"].to_numpy() + weights[1] * df["ml_score"].to_numpy() + weights[2] * df["graph_score"].to_numpy(),
        4,
    )


def evaluate_config(df: pd.DataFrame, weights, ladder: list[dict]) -> dict:
    fused, confidence = fuse_frame(df, weights)
    rank = apply_ladder(fused, confidence, ladder)
    is_fraud = df["is_fraud"].to_numpy().astype(bool)
    report = {"tiers": tier_report(rank, is_fraud), "fused_pr_auc": float(average_precision_score(is_fraud, fused))}
    verify, restrict = LEVEL_ORDER.index("verify"), LEVEL_ORDER.index("restrict")
    per_label = {}
    for label, part in df.groupby("label"):
        r = rank[part.index.to_numpy()]
        per_label[label] = {"n": int(len(part)), "verify_plus": float((r >= verify).mean()), "restrict_plus": float((r >= restrict).mean())}
    report["per_label"] = per_label
    return report


def ladder_with(min_scores: dict[str, float], base: list[dict]) -> list[dict]:
    return [{**e, "min_score": min_scores.get(e["level"], e["min_score"])} for e in base]


def print_comparison(name_to_report: dict[str, dict], fraud_labels: list[str], lookalikes: list[str]) -> None:
    names = list(name_to_report)
    print(f"\n{'':36s}" + "".join(f"{n:>22s}" for n in names))
    print(f"{'fused PR-AUC':36s}" + "".join(f"{name_to_report[n]['fused_pr_auc']:>22.4f}" for n in names))
    for level in LEVEL_ORDER[1:]:
        cells = []
        for n in names:
            t = name_to_report[n]["tiers"][level]
            cells.append(f"{t['recall']:6.1%} rec {t['legit_fpr']:6.2%} fpr")
        print(f"{'>= ' + level + ' (recall / legit FPR)':36s}" + "".join(f"{c:>22s}" for c in cells))
    print("\nper-label share flagged verify+ / restrict+ (cases):")
    for label in fraud_labels + lookalikes + ["normal"]:
        cells = []
        for n in names:
            p = name_to_report[n]["per_label"].get(label)
            cells.append(f"{p['verify_plus']:6.1%} / {p['restrict_plus']:5.1%}" if p else "-")
        tag = "" if label in fraud_labels else " (legit)"
        print(f"  {label + tag:34s}" + "".join(f"{c:>22s}" for c in cells))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models-dir", type=Path, default=DEFAULT_MODELS_DIR)
    parser.add_argument("--min-weight", type=float, default=0.10, help="floor on each engine's fusion weight")
    parser.add_argument("--output", type=Path, help="write the full report as JSON")
    parser.add_argument("--write-config", action="store_true", help="write the tuned weights and ladder to scoring/intervention_config.json")
    args = parser.parse_args()

    df, metadata = load_scored_frame(args.models_dir)
    val, test = split(df, metadata)
    print(f"models: {args.models_dir}  |  val {len(val):,} rows ({val['is_fraud'].mean():.1%} fraud)  test {len(test):,} rows ({test['is_fraud'].mean():.1%} fraud)")

    current = load_config()
    base_ladder = current["levels"]
    current_weights_dict = current.get("fusion_weights", {"rule": 0.25, "ml": 0.5, "graph": 0.25})
    current_weights = (current_weights_dict["rule"], current_weights_dict["ml"], current_weights_dict["graph"])
    min_conf = {e["level"]: e["min_confidence"] for e in base_ladder}

    # --- 1. weights by validation PR-AUC of the fused score ---
    y_val = val["is_fraud"].to_numpy().astype(bool)
    best = None
    for weights in weight_grid(step=0.05, min_weight=args.min_weight):
        pr = average_precision_score(y_val, fused_vectorised(val, weights))
        if best is None or pr > best[0] + 1e-9:
            best = (pr, weights)
    tuned_weights = tuple(round(w, 2) for w in best[1])
    print(f"current weights {current_weights} val PR-AUC {average_precision_score(y_val, fused_vectorised(val, current_weights)):.4f}")
    print(f"tuned weights   {tuned_weights} val PR-AUC {best[0]:.4f}")

    # --- 2. ladder thresholds by legit-FPR target on validation ---
    confidence_val = confidence_only(val)
    legit_val = ~y_val

    def tuned_ladder(weights):
        scores = tune_min_scores(fused_vectorised(val, weights), confidence_val, legit_val, min_conf, DEFAULT_FPR_TARGETS)
        return ladder_with(scores, base_ladder)

    ladder_b, ladder_c = tuned_ladder(current_weights), tuned_ladder(tuned_weights)

    # --- 3. report on test ---
    reports = {
        "A shipped": evaluate_config(test, current_weights, base_ladder),
        "B shipped wts + tuned ladder": evaluate_config(test, current_weights, ladder_b),
        "C tuned wts + tuned ladder": evaluate_config(test, tuned_weights, ladder_c),
    }
    fraud_labels = sorted(l for l in test["label"].unique() if l in {"account_takeover", "gambling_network", "layering_chain", "mule_network", "scam_recipient"})
    lookalikes = sorted(l for l in test["label"].unique() if l in {"group_collection", "innocent_bystander", "large_new_payee"})
    print("\nTEST SPLIT (untouched by tuning)")
    print_comparison(reports, fraud_labels, lookalikes)
    print("\nladder B:", {e["level"]: e["min_score"] for e in ladder_b})
    print("ladder C:", {e["level"]: e["min_score"] for e in ladder_c})

    if args.output:
        args.output.write_text(
            json.dumps(
                {"models_dir": str(args.models_dir), "current_weights": current_weights, "tuned_weights": tuned_weights,
                 "ladder_b": ladder_b, "ladder_c": ladder_c, "fpr_targets": DEFAULT_FPR_TARGETS, "test_reports": reports},
                indent=2, default=float,
            )
        )
    if args.write_config:
        new = {**current, "levels": ladder_c, "fusion_weights": dict(zip(("rule", "ml", "graph"), tuned_weights))}
        CONFIG_PATH.write_text(json.dumps(new, indent=2) + "\n")
        print(f"wrote {CONFIG_PATH}")


if __name__ == "__main__":
    main()
