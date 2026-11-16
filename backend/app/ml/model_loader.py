"""Load the trained model artifacts once, score transactions many times.

The models are trained offline by `python -m ml.train` and exported to
`ml/models/` (see `ml/README.md`); this module's only job is loading them into
memory once, turning a feature dict into scores (`score_transaction`), and
explaining a score in the same reason-code shape rules and graph findings use
(`explain_ml_score`, `anomaly_reason`). Computing that feature dict from live
account/transaction state is `app.ml.live_features`'s job -- kept separate so
this module stays pure inference.

Artifacts:
- `xgboost.joblib` + `calibrator.joblib`: the supervised model and the
  isotonic calibration fitted on held-out validation data. `ml_score` is the
  calibrated probability, so the intervention ladder's fixed thresholds mean
  what they say.
- `isolation_forest.joblib`: a dict with the novelty-detection pipeline
  (imputer + Isolation Forest, trained on normal traffic only) and a quantile
  table of normal-traffic scores, used to report a 0-1 anomaly percentile.
- `model_metadata.json`: feature list, thresholds, library versions and data
  hashes recorded at training time. Loading checks the feature list against
  the vendored feature code so a stale artifact can't silently mis-score.
"""

from __future__ import annotations

import json
import logging
import math
import warnings
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from app.ml.feature_engineering import FEATURE_COLUMNS
from app.models.enums import ReasonCodeSource
from app.scoring.schemas import ReasonCodeResult

logger = logging.getLogger(__name__)

# backend/app/ml/model_loader.py -> repo root is four parents up.
MODELS_DIR = Path(__file__).resolve().parents[3] / "ml" / "models"
TRAIN_COMMAND = "python -m ml.features.build_features && python -m ml.train"


@dataclass
class MLModels:
    xgboost_model: Any
    calibrator: Any
    isolation_forest: dict
    feature_columns: list[str]
    metadata: dict


class ModelsNotTrainedError(RuntimeError):
    """Raised when ml/models/ artifacts are missing or don't match this code.

    Run `python -m ml.features.build_features && python -m ml.train` (see ml/README.md).
    """


_models: MLModels | None = None


def _warn_on_version_drift(trained_with: dict) -> None:
    # joblib pickles of scikit-learn/xgboost objects aren't guaranteed to
    # behave identically across library versions.
    for package in ("xgboost", "scikit-learn"):
        expected = trained_with.get(package)
        try:
            installed = version(package)
        except PackageNotFoundError:
            continue
        if expected and installed != expected:
            logger.warning("%s %s installed, models were trained with %s -- retrain or pin.", package, installed, expected)


def load_models(models_dir: Path = MODELS_DIR) -> MLModels:
    """Load every artifact fresh from disk. Prefer `get_models()` to load once."""
    try:
        with open(models_dir / "feature_columns.json") as f:
            feature_columns = json.load(f)["all_features"]
        with open(models_dir / "model_metadata.json") as f:
            metadata = json.load(f)
        models = MLModels(
            xgboost_model=joblib.load(models_dir / "xgboost.joblib"),
            calibrator=joblib.load(models_dir / "calibrator.joblib"),
            isolation_forest=joblib.load(models_dir / "isolation_forest.joblib"),
            feature_columns=feature_columns,
            metadata=metadata,
        )
    except FileNotFoundError as exc:
        raise ModelsNotTrainedError(
            f"Model artifacts not found under {models_dir}. Run `{TRAIN_COMMAND}` to train and export them."
        ) from exc

    if feature_columns != FEATURE_COLUMNS or metadata.get("feature_columns") != FEATURE_COLUMNS:
        raise ModelsNotTrainedError(
            f"Model artifacts under {models_dir} were trained on a different feature list than "
            f"app/ml/feature_engineering.py computes. Run `{TRAIN_COMMAND}` to retrain."
        )
    _warn_on_version_drift(metadata.get("library_versions", {}))
    return models


def get_models() -> MLModels:
    """Return the process-wide cached models, loading them on first call."""
    global _models
    if _models is None:
        _models = load_models()
    return _models


def model_version(models: MLModels | None = None) -> str:
    """Identifies the loaded artifacts: when `python -m ml.train` produced them."""
    return (models or get_models()).metadata.get("trained_at", "unknown")


def _row(features: dict[str, float], models: MLModels) -> np.ndarray:
    missing = [c for c in models.feature_columns if c not in features]
    if missing:
        raise ValueError(f"score_transaction missing required feature(s): {missing}")
    return np.array([[features[c] for c in models.feature_columns]], dtype=float)


def score_transaction(features: dict[str, float], models: MLModels | None = None) -> dict[str, float]:
    """Score one transaction's already-computed feature dict.

    `features` must have a value for every name in `models.feature_columns`
    (NaN where the history a feature summarizes doesn't exist yet -- see
    `app.ml.feature_engineering.NULLABLE_FEATURES`). Returns:

    - `raw_xgboost_score`: the uncalibrated model output.
    - `ml_score`: the calibrated fraud probability -- what the pipeline fuses.
    - `anomaly_percentile`: where this transaction's Isolation Forest score sits
      in the normal-traffic distribution (0.99 = more unusual than 99% of it).
    """
    models = models or get_models()
    row = _row(features, models)

    # A plain array (not a DataFrame) has no column names to check -- the
    # models warn about that on every call, which is expected here.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="X does not have valid feature names")
        raw = float(models.xgboost_model.predict_proba(row)[0][1])
        ml_score = float(models.calibrator.predict([raw])[0])
        anomaly_raw = float(-models.isolation_forest["pipeline"].score_samples(row)[0])

    quantiles = models.isolation_forest["reference_quantiles"]
    anomaly_percentile = float(np.searchsorted(quantiles, anomaly_raw, side="right") / len(quantiles))
    return {"raw_xgboost_score": raw, "ml_score": ml_score, "anomaly_percentile": anomaly_percentile}


_shap_explainer: Any = None


def _get_shap_explainer(models: MLModels):
    global _shap_explainer
    if _shap_explainer is None:
        import shap

        _shap_explainer = shap.TreeExplainer(models.xgboost_model)
    return _shap_explainer


def _json_number(value: float) -> float | None:
    # NaN isn't valid JSON (Postgres JSON columns and FastAPI responses both reject it).
    return None if value is None or math.isnan(value) else round(float(value), 4)


def explain_ml_score(
    features: dict[str, float], models: MLModels | None = None, top_k: int = 3, ml_score: float | None = None
) -> list[ReasonCodeResult]:
    """The `top_k` features that pushed the XGBoost score up the most for this transaction.

    Per-prediction SHAP values, turned into the same reason-code shape
    `app.rules`/`app.graph` produce. SHAP values are in log-odds, which aren't
    comparable with rule/graph contributions (0-1 score units), so each
    reason's `contribution` is its share of `ml_score`, split in proportion to
    the positive SHAP values; the raw SHAP value stays in `details`. Only
    features that pushed *toward* fraud are returned, and none when `ml_score`
    rounds to zero -- nothing then needs explaining.
    """
    models = models or get_models()
    if ml_score is None:
        ml_score = score_transaction(features, models)["ml_score"]
    explainer = _get_shap_explainer(models)
    row = _row(features, models)

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="X does not have valid feature names")
        shap_values = explainer.shap_values(row)[0]

    positive_total = float(sum(v for v in shap_values if v > 0))
    contributions = sorted(zip(models.feature_columns, shap_values), key=lambda c: -c[1])
    reasons = []
    for feature_name, value in contributions[:top_k]:
        if value <= 0 or positive_total <= 0:
            continue
        contribution = round(ml_score * float(value) / positive_total, 4)
        if contribution <= 0:
            continue
        feature_value = _json_number(features[feature_name])
        reasons.append(
            ReasonCodeResult(
                code=f"ml_feature:{feature_name}",
                template=(
                    "{feature} (value={feature_value}) was a top contributor to the ML fraud score."
                    if feature_value is None
                    else "{feature} (value={feature_value:.2f}) was a top contributor to the ML fraud score."
                ),
                details={"feature": feature_name, "feature_value": feature_value, "shap_value": round(float(value), 4)},
                contribution=contribution,
                source=ReasonCodeSource.ML,
            )
        )
    return reasons


def anomaly_reason(scores: dict[str, float], models: MLModels | None = None) -> ReasonCodeResult | None:
    """An informational reason code when the transaction is unusual versus normal traffic.

    The Isolation Forest isn't blended into `ml_score` (it was trained without
    labels and isn't a probability); it surfaces patterns no labelled example
    covered, for an investigator to look at. No `contribution`, so it never
    moves the fused score by itself.
    """
    models = models or get_models()
    threshold = models.metadata.get("anomaly_reason_percentile", 0.99)
    percentile = scores["anomaly_percentile"]
    if percentile < threshold:
        return None
    return ReasonCodeResult(
        code="ml_anomaly",
        template="Transaction is more unusual than {percentile:.1%} of normal traffic (Isolation Forest).",
        details={"percentile": round(percentile, 4)},
        contribution=None,
        source=ReasonCodeSource.ML,
    )
