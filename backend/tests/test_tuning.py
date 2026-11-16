import numpy as np

from app.scoring.intervention import decide_intervention, get_intervention_ladder
from app.scoring.tuning import LEVEL_ORDER, apply_ladder, tier_report, tune_min_scores, weight_grid

MIN_CONF = {"escalate": 0.6, "restrict": 0.5, "hold": 0.4, "verify": 0.0, "warn": 0.0}
TARGETS = {"warn": 0.5, "verify": 0.2, "hold": 0.1, "restrict": 0.05, "escalate": 0.02}


def test_weight_grid_sums_to_one_and_respects_the_floor():
    triples = list(weight_grid(step=0.05, min_weight=0.2))
    assert triples
    for rule, ml, graph in triples:
        assert abs(rule + ml + graph - 1.0) < 1e-9
        assert min(rule, ml, graph) >= 0.2 - 1e-9
    assert (0.2, 0.6, 0.2) in {tuple(round(w, 2) for w in t) for t in triples}
    # A 0.25 floor leaves 0.25 free to split, and the shipped 0.25 / 0.5 / 0.25 blend is on the grid.
    floored = {tuple(round(w, 2) for w in t) for t in weight_grid(0.05, 0.25)}
    assert (0.25, 0.5, 0.25) in floored
    assert all(min(t) >= 0.25 for t in floored)


def test_apply_ladder_matches_decide_intervention():
    ladder = get_intervention_ladder()
    rng = np.random.default_rng(0)
    fused, confidence = rng.random(500), rng.random(500)
    ranks = apply_ladder(fused, confidence, list(ladder.levels))
    for f, c, r in zip(fused, confidence, ranks):
        assert LEVEL_ORDER[r] == decide_intervention(float(f), float(c)).value


def test_tuned_thresholds_keep_legit_flag_rate_within_each_target():
    rng = np.random.default_rng(1)
    n = 20000
    is_legit = rng.random(n) > 0.08
    fused = np.where(is_legit, rng.beta(1, 12, n), rng.beta(5, 2, n))
    confidence = rng.random(n)
    chosen = tune_min_scores(fused, confidence, is_legit, MIN_CONF, TARGETS)

    ladder = [{"level": lvl, "min_score": chosen.get(lvl, 0.0), "min_confidence": MIN_CONF.get(lvl, 0.0)} for lvl in reversed(LEVEL_ORDER)]
    rank = apply_ladder(fused, confidence, ladder)
    report = tier_report(rank, ~is_legit)
    for level, target in TARGETS.items():
        assert report[level]["legit_fpr"] <= target + 1e-9, (level, report[level])
    # Thresholds never rise as severity falls.
    ordered = [chosen[lvl] for lvl in reversed(LEVEL_ORDER[1:])]
    assert ordered == sorted(ordered, reverse=True)
    # And the tuning is not vacuous: it still catches most fraud at the loosest tier.
    assert report["warn"]["recall"] > 0.8


def test_tier_report_counts_each_tier_as_level_or_higher():
    rank = np.array([0, 1, 2, 5, 3])
    is_fraud = np.array([False, False, True, True, False])
    report = tier_report(rank, is_fraud)
    assert report["warn"]["flagged"] == 4
    assert report["verify"]["recall"] == 1.0
    assert report["hold"]["flagged"] == 2 and report["hold"]["legit_fpr"] == 1 / 3
    assert report["escalate"]["precision"] == 1.0
