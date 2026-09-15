import csv
from pathlib import Path

import pytest

from app.ml import get_models, score_transaction
from app.ml.model_loader import ModelsNotTrainedError, load_models

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
