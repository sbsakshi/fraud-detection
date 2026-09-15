import csv
from pathlib import Path

import pytest

from app.ml import explain_ml_score, get_models, score_transaction
from app.ml.model_loader import ModelsNotTrainedError, load_models
from app.models.enums import ReasonCodeSource

FEATURES_CSV = Path(__file__).resolve().parents[2] / "ml" / "data" / "features.csv"


@pytest.fixture(scope="module")
def sample_features() -> dict:
    """One real, fully-populated feature row from the Phase 4 synthetic dataset."""
    models = get_models()
    with open(FEATURES_CSV, newline="") as f:
        row = next(csv.DictReader(f))
    return {c: float(row[c]) for c in models.feature_columns}


def test_get_models_returns_the_same_cached_instance():
    assert get_models() is get_models()


def test_load_models_raises_clear_error_when_artifacts_missing(tmp_path):
    with pytest.raises(ModelsNotTrainedError, match="ml/notebooks/model_training.ipynb"):
        load_models(models_dir=tmp_path)


def test_score_transaction_returns_all_three_scores(sample_features):
    scores = score_transaction(sample_features)
    assert set(scores) == {"xgboost_score", "random_forest_score", "isolation_forest_score"}
    assert 0.0 <= scores["xgboost_score"] <= 1.0
    assert 0.0 <= scores["random_forest_score"] <= 1.0
    assert isinstance(scores["isolation_forest_score"], float)


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
        assert r.contribution > 0
        assert r.details["feature"] in sample_features


def test_explain_ml_score_ranks_by_shap_magnitude(sample_features):
    reasons = explain_ml_score(sample_features, top_k=5)
    contributions = [r.contribution for r in reasons]
    assert contributions == sorted(contributions, reverse=True)
