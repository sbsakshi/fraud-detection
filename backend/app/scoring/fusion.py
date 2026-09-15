"""Combine rule/ML/graph scores into one fused score and a confidence value.

`fused_score` is a weighted average -- ML weighted highest since Phase 4
found it the strongest individual signal, rules and graph equal behind it.
`confidence` is deliberately not "how big is fused_score" (that's what
fused_score itself already says) but "how much do we trust this number":
built from two things multiple independent signals can tell you that one
alone can't -- how many of the three sources actually said anything at all
(`coverage`), and, among the ones that did, how much they agree
(`agreement`). A transaction only one source flags, or where the sources
that fired disagree sharply, gets a real score but a lower confidence --
exactly the situation `app.scoring.intervention`'s ladder should hesitate
to act on with certainty.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import pstdev

DEFAULT_WEIGHTS = {"rule": 0.25, "ml": 0.5, "graph": 0.25}


@dataclass(frozen=True)
class FusionResult:
    fused_score: float
    confidence: float
    coverage: float  # fraction of the 3 sources that produced a nonzero score
    agreement: float  # 1.0 = sources that fired agree exactly; 0.0 = maximally spread out


def fuse_scores(
    rule_score: float, ml_score: float, graph_score: float, weights: dict[str, float] = DEFAULT_WEIGHTS
) -> FusionResult:
    scores = {"rule": rule_score, "ml": ml_score, "graph": graph_score}
    fused_score = sum(weights[k] * scores[k] for k in scores)

    active = [s for s in scores.values() if s > 0]
    coverage = len(active) / len(scores)
    if len(active) <= 1:
        # A single source (or none) firing has nothing to corroborate
        # against -- neither strong agreement nor strong disagreement is
        # meaningful yet, so this stays a fixed, deliberately middling value.
        agreement = 0.5
    else:
        agreement = max(0.0, 1.0 - pstdev(active))

    confidence = round(0.5 * coverage + 0.5 * agreement, 4)
    return FusionResult(
        fused_score=round(fused_score, 4), confidence=confidence, coverage=coverage, agreement=round(agreement, 4)
    )
