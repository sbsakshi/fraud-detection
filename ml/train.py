"""Train, calibrate and evaluate the ML layer, and export what the backend loads.

Replaces the Phase 4 notebook with one reproducible command:

    python -m ml.features.build_features   # -> ml/data/features.csv
    python -m ml.train                     # -> ml/models/*

What it does, and why each step exists (see ml/README.md for the results):

1. Drops the burn-in period (`synthetic.config.BURN_IN_DAYS`): before it,
   every account has artificially empty history.
2. Splits the rest chronologically into train / validation / test (60/20/20).
   Validation picks hyperparameters, fits the calibrator and sets the alert
   threshold; test is touched once, for the report.
3. XGBoost, small grid search with early stopping on validation PR-AUC. No
   class reweighting: reweighting inflates probabilities, and the backend's
   intervention ladder compares scores against fixed thresholds.
4. Isotonic calibration on validation, so a score of 0.7 means ~70% of such
   transactions are fraud.
5. Isolation Forest trained on *normal* training traffic only (novelty
   detection), with median imputation + missing-indicator columns for the
   NaN "no history" features. Its raw score is turned into a percentile of
   the normal-traffic score distribution, so the backend gets a 0-1 number.
6. Honest evaluation on test: per-scenario recall, false-positive rate on each
   legitimate look-alike pattern, recall at a fixed false-positive rate,
   calibration table, leave-one-scenario-out recall, base-vs-full ablation,
   and two shortcut guards (strongest single feature, receiver overlap).
"""

from __future__ import annotations

import hashlib
import itertools
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
import xgboost
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from xgboost import XGBClassifier

from ml.features.engineering import (
    BASE_FEATURES,
    BEHAVIORAL_FEATURES,
    FEATURE_COLUMNS,
    GRAPH_FEATURES,
    NULLABLE_FEATURES,
)
from ml.synthetic.config import START_DATE

ML_DIR = Path(__file__).resolve().parent
DATA_DIR = ML_DIR / "data"
MODELS_DIR = ML_DIR / "models"

RANDOM_STATE = 42
TRAIN_FRAC, VAL_FRAC = 0.6, 0.2
# The alert threshold is the lowest calibrated score whose false-positive rate
# on validation non-fraud traffic (normal + look-alikes) stays at or under this.
TARGET_FPR = 0.01
# Isolation Forest percentile above which the backend adds an "unusual
# transaction" reason code.
ANOMALY_REASON_PERCENTILE = 0.99

PARAM_GRID = {
    "max_depth": [3, 4, 6],
    "learning_rate": [0.05, 0.1],
    "min_child_weight": [1, 5],
}

FRAUD_SCENARIOS = ["account_takeover", "gambling_network", "layering_chain", "mule_network", "scam_recipient"]
LOOKALIKE_SCENARIOS = ["innocent_bystander", "large_new_payee", "group_collection"]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_features() -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / "features.csv", dtype={"true_label": "string", "scenario": "string"})
    df["created_at"] = pd.to_datetime(df["created_at"], utc=True, format="ISO8601")
    df = df.sort_values("created_at", kind="stable").reset_index(drop=True)
    df["label"] = df["true_label"].fillna(df["scenario"]).fillna("normal")
    return df


def chronological_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    df = df[df["created_at"] >= pd.Timestamp(START_DATE, tz="UTC")].reset_index(drop=True)
    n = len(df)
    a, b = int(n * TRAIN_FRAC), int(n * (TRAIN_FRAC + VAL_FRAC))
    return df.iloc[:a], df.iloc[a:b], df.iloc[b:]


def make_xgb(params: dict, n_estimators: int = 1000, early_stopping: bool = True) -> XGBClassifier:
    return XGBClassifier(
        n_estimators=n_estimators,
        subsample=0.8,
        colsample_bytree=0.8,
        eval_metric="aucpr",
        early_stopping_rounds=50 if early_stopping else None,
        random_state=RANDOM_STATE,
        n_jobs=4,
        **params,
    )


def search_xgb(train: pd.DataFrame, val: pd.DataFrame, cols: list[str]) -> tuple[XGBClassifier, dict, float]:
    best = None
    for values in itertools.product(*PARAM_GRID.values()):
        params = dict(zip(PARAM_GRID, values))
        model = make_xgb(params).fit(train[cols], train["is_fraud"], eval_set=[(val[cols], val["is_fraud"])], verbose=False)
        score = average_precision_score(val["is_fraud"], model.predict_proba(val[cols])[:, 1])
        if best is None or score > best[2]:
            best = (model, params, score)
    return best


def fit_fixed(train: pd.DataFrame, cols: list[str], params: dict, n_estimators: int) -> XGBClassifier:
    return make_xgb(params, n_estimators=n_estimators, early_stopping=False).fit(train[cols], train["is_fraud"])


def fit_calibrator(raw_scores: np.ndarray, y: np.ndarray) -> IsotonicRegression:
    return IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(raw_scores, y)


def threshold_at_fpr(scores: np.ndarray, y: np.ndarray, target_fpr: float) -> float:
    negatives = np.sort(scores[y == 0])
    # Smallest threshold t with mean(negatives >= t) <= target_fpr.
    k = int(np.floor(target_fpr * len(negatives)))
    candidate = negatives[len(negatives) - k] if k > 0 else np.nextafter(negatives[-1], np.inf)
    return float(min(max(candidate, 1e-6), 1.0))


def flag_rates(df: pd.DataFrame, flagged: np.ndarray) -> dict[str, float]:
    return {lbl: round(float(flagged[(df["label"] == lbl).to_numpy()].mean()), 4) for lbl in sorted(df["label"].unique())}


def reliability(scores: np.ndarray, y: np.ndarray) -> list[dict]:
    edges = [0, 0.05, 0.15, 0.35, 0.55, 0.7, 0.9, 1.0000001]
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (scores >= lo) & (scores < hi)
        if m.any():
            out.append({"bucket": f"[{lo:.2f}, {min(hi, 1):.2f})", "n": int(m.sum()),
                        "mean_score": round(float(scores[m].mean()), 4), "fraud_rate": round(float(y[m].mean()), 4)})
    return out


def train_isolation_forest(train: pd.DataFrame) -> dict:
    normal = train[train["label"] == "normal"]
    pipeline = make_pipeline(
        SimpleImputer(strategy="median", add_indicator=True),
        IsolationForest(n_estimators=300, random_state=RANDOM_STATE, n_jobs=4),
    ).fit(normal[FEATURE_COLUMNS])
    reference = -pipeline.score_samples(normal[FEATURE_COLUMNS])
    return {
        "pipeline": pipeline,
        # 1,001 quantiles of normal-traffic anomaly scores: percentile lookup table.
        "reference_quantiles": np.quantile(reference, np.linspace(0, 1, 1001)).tolist(),
    }


def anomaly_percentile(iso: dict, X: pd.DataFrame) -> np.ndarray:
    raw = -iso["pipeline"].score_samples(X)
    return np.searchsorted(np.asarray(iso["reference_quantiles"]), raw, side="right") / len(iso["reference_quantiles"])


def main() -> None:
    df = load_features()
    train, val, test = chronological_split(df)
    print(f"Train {len(train):,} | val {len(val):,} | test {len(test):,} (burn-in before {START_DATE} dropped)")
    for name, part in [("train", train), ("val", val), ("test", test)]:
        print(f"  {name:5s} {part['created_at'].min():%Y-%m-%d} .. {part['created_at'].max():%Y-%m-%d}  fraud {part['is_fraud'].mean():.2%}")

    # --- XGBoost ---
    searched, best_params, best_val_pr = search_xgb(train, val, FEATURE_COLUMNS)
    n_estimators = int(searched.best_iteration) + 1
    model = fit_fixed(train, FEATURE_COLUMNS, best_params, n_estimators)
    print(f"Best params {best_params}, {n_estimators} trees, val PR-AUC {best_val_pr:.4f}")

    calibrator = fit_calibrator(model.predict_proba(val[FEATURE_COLUMNS])[:, 1], val["is_fraud"].to_numpy())
    calibrate = lambda X: calibrator.predict(model.predict_proba(X)[:, 1])  # noqa: E731

    val_scores = calibrate(val[FEATURE_COLUMNS])
    alert_threshold = threshold_at_fpr(val_scores, val["is_fraud"].to_numpy(), TARGET_FPR)

    # --- Test evaluation ---
    y_test = test["is_fraud"].to_numpy()
    test_scores = calibrate(test[FEATURE_COLUMNS])
    flagged = test_scores >= alert_threshold
    normal_mask = (test["label"] == "normal").to_numpy()
    rates = flag_rates(test, flagged)
    metrics = {
        "roc_auc": round(roc_auc_score(y_test, test_scores), 4),
        "pr_auc": round(average_precision_score(y_test, test_scores), 4),
        "brier": round(brier_score_loss(y_test, test_scores), 4),
        "alert_threshold": round(alert_threshold, 4),
        "recall_at_alert_threshold": round(float(flagged[y_test == 1].mean()), 4),
        "precision_at_alert_threshold": round(float(y_test[flagged].mean()) if flagged.any() else 0.0, 4),
        "normal_fpr_at_alert_threshold": round(float(flagged[normal_mask].mean()), 4),
        "per_label_flag_rate": rates,
        "per_label_flag_rate_at_0.5": flag_rates(test, test_scores >= 0.5),
        "calibration": reliability(test_scores, y_test),
    }

    # --- Isolation Forest ---
    iso = train_isolation_forest(train)
    test_anomaly = anomaly_percentile(iso, test[FEATURE_COLUMNS])
    metrics["isolation_forest"] = {
        "roc_auc": round(roc_auc_score(y_test, test_anomaly), 4),
        "pr_auc": round(average_precision_score(y_test, test_anomaly), 4),
        "flag_rate_above_reason_percentile": flag_rates(test, test_anomaly >= ANOMALY_REASON_PERCENTILE),
    }

    # --- Ablation: what each feature tier adds ---
    def tier_metrics(cols: list[str]) -> dict:
        m, _, _ = search_xgb(train, val, cols)
        s = m.predict_proba(test[cols])[:, 1]
        return {"roc_auc": round(roc_auc_score(y_test, s), 4), "pr_auc": round(average_precision_score(y_test, s), 4)}

    metrics["ablation"] = {
        "base_only": tier_metrics(BASE_FEATURES),
        "base_plus_behavioral": tier_metrics(BASE_FEATURES + BEHAVIORAL_FEATURES),
        "base_plus_behavioral_plus_graph": {"roc_auc": metrics["roc_auc"], "pr_auc": metrics["pr_auc"]},
    }

    # --- Leave-one-scenario-out: can it catch a fraud pattern it never saw? ---
    loso = {}
    for held in FRAUD_SCENARIOS:
        tr, va = train[train["label"] != held], val[val["label"] != held]
        m = fit_fixed(tr, FEATURE_COLUMNS, best_params, n_estimators)
        cal = fit_calibrator(m.predict_proba(va[FEATURE_COLUMNS])[:, 1], va["is_fraud"].to_numpy())
        va_s = cal.predict(m.predict_proba(va[FEATURE_COLUMNS])[:, 1])
        thr = threshold_at_fpr(va_s, va["is_fraud"].to_numpy(), TARGET_FPR)
        held_rows = test[test["label"] == held]
        s = cal.predict(m.predict_proba(held_rows[FEATURE_COLUMNS])[:, 1])
        loso[held] = {"recall": round(float((s >= thr).mean()), 4), "n_test": int(len(held_rows))}
    metrics["leave_one_scenario_out"] = loso

    # --- Shortcut guards ---
    single = {c: roc_auc_score(y_test, test[c].fillna(test[c].median())) for c in FEATURE_COLUMNS}
    strongest = sorted(single.items(), key=lambda kv: -abs(kv[1] - 0.5))[:5]
    metrics["strongest_single_features_test_roc"] = {c: round(v, 4) for c, v in strongest}
    seen_receivers = set(train["receiver_upi_id"])
    metrics["test_fraud_receivers_seen_in_train"] = {
        lbl: round(float(test.loc[test["label"] == lbl, "receiver_upi_id"].isin(seen_receivers).mean()), 4)
        for lbl in FRAUD_SCENARIOS
    }

    # --- Export ---
    MODELS_DIR.mkdir(exist_ok=True)
    for stale in ("random_forest.joblib", "model_comparison.csv"):
        (MODELS_DIR / stale).unlink(missing_ok=True)
    joblib.dump(model, MODELS_DIR / "xgboost.joblib")
    joblib.dump(calibrator, MODELS_DIR / "calibrator.joblib")
    joblib.dump(iso, MODELS_DIR / "isolation_forest.joblib")
    with open(MODELS_DIR / "feature_columns.json", "w") as f:
        json.dump({"base_features": BASE_FEATURES, "behavioral_features": BEHAVIORAL_FEATURES,
                   "graph_features": GRAPH_FEATURES, "nullable_features": NULLABLE_FEATURES, "all_features": FEATURE_COLUMNS}, f, indent=2)
    metadata = {
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_sha256": {name: _sha256(DATA_DIR / name) for name in ("accounts.csv", "transactions.csv")},
        "library_versions": {"python": platform.python_version(), "xgboost": xgboost.__version__,
                             "scikit-learn": sklearn.__version__, "pandas": pd.__version__, "numpy": np.__version__},
        "feature_columns": FEATURE_COLUMNS,
        "xgboost_params": {**best_params, "n_estimators": n_estimators},
        "split": {"burn_in_before": str(START_DATE), "train_frac": TRAIN_FRAC, "val_frac": VAL_FRAC,
                  "rows": {"train": len(train), "val": len(val), "test": len(test)}},
        "alert_threshold": round(alert_threshold, 4),
        "target_fpr": TARGET_FPR,
        "anomaly_reason_percentile": ANOMALY_REASON_PERCENTILE,
    }
    with open(MODELS_DIR / "model_metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)
    with open(MODELS_DIR / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)

    print(json.dumps(metrics, indent=2))
    print(f"\nWrote artifacts to {MODELS_DIR}")


if __name__ == "__main__":
    main()
