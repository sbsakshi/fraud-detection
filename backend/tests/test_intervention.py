import json

import pytest

from app.models.enums import InterventionLevel
from app.scoring.intervention import decide_intervention, load_intervention_ladder


def test_default_config_covers_the_full_score_range_at_zero_confidence():
    # Every score from 0 to just under 1 must resolve to *some* level even
    # at confidence=0 -- the ladder's bottom rung must have min_confidence=0.
    for score in [0.0, 0.05, 0.2, 0.4, 0.6, 0.8, 0.99]:
        assert isinstance(decide_intervention(score, confidence=0.0), InterventionLevel)


def test_low_score_is_inform():
    assert decide_intervention(0.05, confidence=1.0) == InterventionLevel.INFORM


def test_high_score_and_high_confidence_reaches_escalate():
    assert decide_intervention(0.95, confidence=0.9) == InterventionLevel.ESCALATE


def test_high_score_but_low_confidence_is_capped_below_escalate():
    level = decide_intervention(0.95, confidence=0.1)
    assert level != InterventionLevel.ESCALATE


def test_levels_are_monotonic_in_score_at_fixed_high_confidence():
    order = [InterventionLevel.INFORM, InterventionLevel.WARN, InterventionLevel.VERIFY,
             InterventionLevel.HOLD, InterventionLevel.RESTRICT, InterventionLevel.ESCALATE]
    seen = [decide_intervention(s, confidence=1.0) for s in [0.0, 0.2, 0.4, 0.6, 0.75, 0.95]]
    assert [order.index(level) for level in seen] == sorted(order.index(level) for level in seen)


def test_ladder_is_loaded_from_the_config_file_not_hardcoded(tmp_path):
    custom_path = tmp_path / "custom_ladder.json"
    custom_path.write_text(json.dumps({"levels": [{"level": "escalate", "min_score": 0.0, "min_confidence": 0.0}]}))
    ladder = load_intervention_ladder(custom_path)
    # With a custom config where even score=0 escalates, the ladder must honor it.
    assert decide_intervention(0.0, confidence=0.0, ladder=ladder) == InterventionLevel.ESCALATE


def test_malformed_level_name_in_config_raises():
    # A bad level name should raise, not silently misclassify.
    from app.scoring.intervention import InterventionLadder

    bad_ladder = InterventionLadder(levels=({"level": "not_a_real_level", "min_score": 0.0, "min_confidence": 0.0},))
    with pytest.raises(ValueError):
        decide_intervention(0.5, confidence=0.5, ladder=bad_ladder)
