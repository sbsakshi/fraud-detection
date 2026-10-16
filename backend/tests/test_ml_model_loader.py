import csv
import json
import math
import shutil
from pathlib import Path

import pytest

from app.ml import anomaly_reason, explain_ml_score, get_models, score_transaction
from app.ml.model_loader import MODELS_DIR, ModelsNotTrainedError, load_models
from app.models.enums import ReasonCodeSource

FEATURES_CSV = Path(__file__).resolve().parents[2] / "ml" / "data" / "features.csv"


def _parse(value: str) -> float:
    return float(value) if value != "" else math.nan


@pytest.fixture(scope="module")
def sample_features() -> dict:
    """One real labelled-fraud feature row from the synthetic dataset (so there is something to explain)."""
    models = get_models()
    with open(FEATURES_CSV, newline="") as f:
        row = next(r for r in csv.DictReader(f) if r["is_fraud"] == "1" and r["true_label"] == "layering_chain")
    return {c: _parse(row[c]) for c in models.feature_columns}


def test_get_models_returns_the_same_cached_instance():
    assert get_models() is get_models()


def test_load_models_raises_clear_error_when_artifacts_missing(tmp_path):
    with pytest.raises(ModelsNotTrainedError, match="python -m ml.train"):
        load_models(models_dir=tmp_path)


def test_load_models_rejects_artifacts_trained_on_other_features(tmp_path):
    for p in MODELS_DIR.iterdir():
        shutil.copy(p, tmp_path / p.name)
    meta = json.loads((tmp_path / "model_metadata.json").read_text())
    meta["feature_columns"] = meta["feature_columns"][:-1]
    (tmp_path / "model_metadata.json").write_text(json.dumps(meta))
    with pytest.raises(ModelsNotTrainedError, match="different feature list"):
        load_models(models_dir=tmp_path)


def test_score_transaction_returns_calibrated_and_anomaly_scores(sample_features):
    scores = score_transaction(sample_features)
    assert set(scores) == {"raw_xgboost_score", "ml_score", "anomaly_percentile"}
    assert 0.0 <= scores["ml_score"] <= 1.0
    assert 0.0 <= scores["anomaly_percentile"] <= 1.0
    assert scores["ml_score"] > 0.5  # a labelled layering-chain hop


def test_score_transaction_accepts_missing_history_as_nan(sample_features):
    features = {**sample_features, "amount_zscore_sender": math.nan, "minutes_since_sender_last_sent": math.nan}
    scores = score_transaction(features)
    assert not math.isnan(scores["ml_score"])


def test_score_transaction_rejects_incomplete_features(sample_features):
    incomplete = dict(list(sample_features.items())[:-1])  # drop one required key
    with pytest.raises(ValueError, match="missing required feature"):
        score_transaction(incomplete)


def test_explain_ml_score_returns_only_positive_contributions(sample_features):
    reasons = explain_ml_score(sample_features, top_k=3)
    assert len(reasons) <= 3
    for r in reasons:
        assert r.source == ReasonCodeSource.ML
        assert r.code.startswith("ml_feature:")
        assert 0 < r.contribution <= 1
        assert r.details["feature"] in sample_features
    # Contributions are shares of ml_score, so they never sum past it.
    assert sum(r.contribution for r in reasons) <= score_transaction(sample_features)["ml_score"] + 1e-6


def test_explain_ml_score_ranks_by_shap_magnitude(sample_features):
    reasons = explain_ml_score(sample_features, top_k=5)
    contributions = [r.contribution for r in reasons]
    assert reasons
    assert contributions == sorted(contributions, reverse=True)


def test_explain_ml_score_has_no_nan_in_details(sample_features):
    features = {c: math.nan if c in ("amount_zscore_sender", "sender_minutes_since_first_seen") else v
                for c, v in sample_features.items()}
    for r in explain_ml_score(features, top_k=10):
        assert r.details["feature_value"] is None or not math.isnan(r.details["feature_value"])


def test_anomaly_reason_only_above_threshold():
    assert anomaly_reason({"anomaly_percentile": 0.5}) is None
    reason = anomaly_reason({"anomaly_percentile": 0.999})
    assert reason is not None and reason.code == "ml_anomaly" and reason.contribution is None
