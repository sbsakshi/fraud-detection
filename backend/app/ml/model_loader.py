"""Phase 4/6 — load the trained model artifacts once, score transactions many times.

The models themselves are trained offline in `ml/notebooks/model_training.ipynb`
and exported to `ml/models/*.joblib` (see `ml/README.md`); this module's only
job is loading them into memory once, turning a feature dict into scores
(`score_transaction`), and explaining a score in the same reason-code shape
rules and graph findings use (`explain_ml_score`, via SHAP). Computing that
feature dict from live account/transaction state is `app.ml.live_features`'s
job -- kept separate so this module stays pure inference.
"""

from __future__ import annotations

import json
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib

from app.models.enums import ReasonCodeSource
from app.scoring.schemas import ReasonCodeResult

# backend/app/ml/model_loader.py -> repo root is four parents up.
MODELS_DIR = Path(__file__).resolve().parents[3] / "ml" / "models"


@dataclass
class MLModels:
    xgboost_model: Any
    random_forest_model: Any
    isolation_forest_model: Any
    feature_columns: list[str]


class ModelsNotTrainedError(RuntimeError):
    """Raised when ml/models/*.joblib don't exist yet.

    Run ml/notebooks/model_training.ipynb (see ml/README.md) to produce them.
    """


_models: MLModels | None = None


def load_models(models_dir: Path = MODELS_DIR) -> MLModels:
    """Load every artifact fresh from disk. Prefer `get_models()` to load once."""
    try:
        with open(models_dir / "feature_columns.json") as f:
            feature_columns = json.load(f)["all_features"]
        return MLModels(
            xgboost_model=joblib.load(models_dir / "xgboost.joblib"),
            random_forest_model=joblib.load(models_dir / "random_forest.joblib"),
            isolation_forest_model=joblib.load(models_dir / "isolation_forest.joblib"),
            feature_columns=feature_columns,
        )
    except FileNotFoundError as exc:
        raise ModelsNotTrainedError(
            f"Model artifacts not found under {models_dir}. "
            "Run ml/notebooks/model_training.ipynb to train and export them."
        ) from exc


def get_models() -> MLModels:
    """Return the process-wide cached models, loading them on first call."""
    global _models
    if _models is None:
        _models = load_models()
    return _models


def score_transaction(features: dict[str, float], models: MLModels | None = None) -> dict[str, float]:
    """Score one transaction's already-computed feature dict.

    `features` must have a value for every name in `models.feature_columns`
    (see `ml.features.engineering.FEATURE_COLUMNS` for what those are and how
    they're computed) -- this function only does inference, never feature
    computation.
    """
    models = models or get_models()
    missing = [c for c in models.feature_columns if c not in features]
    if missing:
        raise ValueError(f"score_transaction missing required feature(s): {missing}")
    row = [[features[c] for c in models.feature_columns]]

    # A plain list-of-lists (not a DataFrame) has no column names to check --
    # sklearn/xgboost warn about that on every call, which is expected here
    # since building a one-row DataFrame just to silence it isn't worth the ceremony.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="X does not have valid feature names")
        return {
            "xgboost_score": float(models.xgboost_model.predict_proba(row)[0][1]),
            "random_forest_score": float(models.random_forest_model.predict_proba(row)[0][1]),
            # Higher = more anomalous, to match the other two scores' "higher = more suspicious" direction.
            "isolation_forest_score": float(-models.isolation_forest_model.score_samples(row)[0]),
        }


_shap_explainer: Any = None


def _get_shap_explainer(models: MLModels):
    global _shap_explainer
    if _shap_explainer is None:
        import shap

        _shap_explainer = shap.TreeExplainer(models.xgboost_model)
    return _shap_explainer


def explain_ml_score(
    features: dict[str, float], models: MLModels | None = None, top_k: int = 3
) -> list[ReasonCodeResult]:
    """The `top_k` features that pushed the XGBoost score up the most for this transaction.

    Per-prediction SHAP values on the model Phase 4 found strongest, turned
    into the same reason-code shape `app.rules`/`app.graph` produce -- this
    is what makes an ML score explainable to an investigator rather than a
    bare number, same idea Phase 4's notebook used to sanity-check the
    model, now run at scoring time instead of only in a notebook. Only
    positive-contribution features are returned (ones that pushed *toward*
    fraud) -- a feature that pushed the score down isn't a reason to flag
    the transaction.
    """
    models = models or get_models()
    explainer = _get_shap_explainer(models)
    row = [[features[c] for c in models.feature_columns]]

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="X does not have valid feature names")
        shap_values = explainer.shap_values(row)[0]

    contributions = sorted(zip(models.feature_columns, shap_values), key=lambda c: -c[1])
    return [
        ReasonCodeResult(
            code=f"ml_feature:{feature_name}",
            template="{feature} (value={feature_value:.2f}) was the top contributor to the ML fraud score.",
            details={
                "feature": feature_name,
                "feature_value": round(features[feature_name], 4),
                "shap_value": round(float(value), 4),
            },
            contribution=round(float(value), 4),
            source=ReasonCodeSource.ML,
        )
        for feature_name, value in contributions[:top_k]
        if value > 0
    ]
