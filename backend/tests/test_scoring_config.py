import json

from app.scoring import config
from app.scoring.fusion import DEFAULT_WEIGHTS
from app.scoring.intervention import load_intervention_ladder


def test_shipped_config_has_a_complete_ladder_and_weights_that_sum_to_one():
    cfg = config.load_config()
    levels = [e["level"] for e in cfg["levels"]]
    assert levels == ["escalate", "restrict", "hold", "verify", "warn", "inform"]
    scores = [e["min_score"] for e in cfg["levels"]]
    assert scores == sorted(scores, reverse=True), "min_score must not increase as severity decreases"
    assert cfg["levels"][-1]["min_score"] == 0 and cfg["levels"][-1]["min_confidence"] == 0
    assert set(cfg["fusion_weights"]) == {"rule", "ml", "graph"}
    assert abs(sum(cfg["fusion_weights"].values()) - 1.0) < 1e-9
    assert DEFAULT_WEIGHTS == cfg["fusion_weights"]


def test_config_version_changes_with_any_threshold_or_weight(tmp_path):
    path = tmp_path / "cfg.json"
    cfg = config.load_config()
    path.write_text(json.dumps(cfg))
    before = config.config_version(path)
    assert before == config.config_version(path)  # stable for identical content

    cfg["fusion_weights"]["ml"] += 0.01
    path.write_text(json.dumps(cfg))
    assert config.config_version(path) != before

    cfg["fusion_weights"]["ml"] -= 0.01
    cfg["levels"][0]["min_score"] += 0.01
    path.write_text(json.dumps(cfg))
    assert config.config_version(path) != before


def test_weights_fall_back_when_config_has_none(tmp_path):
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps({"levels": [{"level": "inform", "min_score": 0, "min_confidence": 0}]}))
    assert config.load_weights(path) == config.FALLBACK_WEIGHTS
    assert load_intervention_ladder(path).levels[0]["level"] == "inform"
