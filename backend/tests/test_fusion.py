from app.scoring.fusion import fuse_scores


def test_all_zero_scores_fuse_to_zero_with_low_confidence():
    result = fuse_scores(0.0, 0.0, 0.0)
    assert result.fused_score == 0.0
    assert result.coverage == 0.0
    assert result.confidence == 0.5 * 0.0 + 0.5 * 0.5  # single/no-source default agreement of 0.5


def test_ml_is_weighted_more_heavily_than_rule_or_graph():
    ml_heavy = fuse_scores(0.0, 1.0, 0.0)
    rule_heavy = fuse_scores(1.0, 0.0, 0.0)
    assert ml_heavy.fused_score > rule_heavy.fused_score


def test_all_three_sources_agreeing_gives_high_confidence():
    result = fuse_scores(0.8, 0.8, 0.8)
    assert result.coverage == 1.0
    assert result.agreement == 1.0
    assert result.confidence == 1.0


def test_sources_disagreeing_lowers_confidence_relative_to_agreeing():
    agree = fuse_scores(0.8, 0.8, 0.8)
    disagree = fuse_scores(0.9, 0.1, 0.5)
    assert disagree.confidence < agree.confidence


def test_single_active_source_gets_the_fixed_uncorroborated_agreement():
    result = fuse_scores(0.0, 0.9, 0.0)
    assert result.coverage == 1 / 3
    assert result.agreement == 0.5


def test_fused_score_and_confidence_are_independent():
    # A high score from one lone source vs a lower score all three agree on --
    # confidence should track agreement/coverage, not just track the score.
    lone_high = fuse_scores(0.0, 1.0, 0.0)
    corroborated_lower = fuse_scores(0.4, 0.4, 0.4)
    assert lone_high.fused_score > corroborated_lower.fused_score
    assert lone_high.confidence < corroborated_lower.confidence
