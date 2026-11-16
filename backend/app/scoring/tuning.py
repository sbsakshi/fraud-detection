"""Offline tuning helpers for the fusion weights and the intervention ladder.

Pure numpy, no database and no model loading, so the same functions run in
`scripts/tune_fusion.py` and under unit tests. Nothing here is used on the
request path.

The ladder is tuned the way `ml/train.py` sets its alert threshold: pick the
lowest `min_score` whose false-positive rate on legitimate traffic stays under
a target. The targets are product decisions (how much friction legitimate
users tolerate at each level), so they are inputs, not constants.
"""

from __future__ import annotations

from itertools import product

import numpy as np

# Ascending severity; the index is the "rank" returned by `apply_ladder`.
LEVEL_ORDER = ("inform", "warn", "verify", "hold", "restrict", "escalate")


def weight_grid(step: float = 0.05, min_weight: float = 0.0):
    """Every (rule, ml, graph) weight triple on the grid that sums to 1.

    `min_weight` keeps each engine in the blend. Offline data cannot value the
    known-fraud signals (no investigator has confirmed anything in synthetic
    replay), so letting the search zero out rules or graph would undervalue
    them.
    """
    n = round(1 / step)
    floor = round(min_weight / step)
    for rule, ml in product(range(floor, n + 1), repeat=2):
        graph = n - rule - ml
        if graph >= floor:
            yield (rule * step, ml * step, graph * step)


def apply_ladder(fused: np.ndarray, confidence: np.ndarray, ladder: list[dict]) -> np.ndarray:
    """Vectorised `decide_intervention`: the intervention rank (index into LEVEL_ORDER) per row.

    `ladder` is the config's `levels` list (highest severity first). A row gets
    the highest level whose min_score and min_confidence are both met.
    """
    rank = np.zeros(len(fused), dtype=int)
    for entry in reversed(ladder):  # lowest severity first, so higher levels overwrite
        met = (fused >= entry["min_score"]) & (confidence >= entry["min_confidence"])
        rank[met] = LEVEL_ORDER.index(entry["level"])
    return rank


def tune_min_scores(
    fused: np.ndarray,
    confidence: np.ndarray,
    is_legit: np.ndarray,
    min_confidence: dict[str, float],
    max_legit_fpr: dict[str, float],
    step: float = 0.01,
) -> dict[str, float]:
    """Lowest `min_score` per level keeping legit traffic flagged at-or-above that level under its target.

    Works top-down (escalate first). A row already caught by a more severe level
    counts toward the lower level's false-positive budget, which is how the
    ladder behaves at decision time. `min_confidence` is held fixed.
    """
    n_legit = int(is_legit.sum())
    grid = np.round(np.arange(0.0, 1.0 + step / 2, step), 4)
    chosen: dict[str, float] = {}
    caught = np.zeros(len(fused), dtype=bool)
    ceiling = float(grid[-1])
    for level in reversed(LEVEL_ORDER[1:]):  # escalate ... warn
        allowed = int(np.floor(max_legit_fpr[level] * n_legit))
        confident = confidence >= min_confidence[level]

        def legit_flagged(t: float) -> int:
            return int((is_legit & (caught | (confident & (fused >= t)))).sum())

        # legit_flagged is non-increasing in t: binary-search the smallest passing grid point.
        lo, hi = 0, len(grid) - 1
        if legit_flagged(grid[hi]) > allowed:
            threshold = float(grid[hi])  # even the strictest score is over budget; pin to the top
        else:
            while lo < hi:
                mid = (lo + hi) // 2
                if legit_flagged(grid[mid]) <= allowed:
                    hi = mid
                else:
                    lo = mid + 1
            threshold = float(grid[lo])
        threshold = min(threshold, ceiling)  # a lower level never needs a higher bar than the level above
        chosen[level] = threshold
        ceiling = threshold
        caught = caught | (confident & (fused >= threshold))
    return chosen


def tier_report(rank: np.ndarray, is_fraud: np.ndarray) -> dict[str, dict[str, float]]:
    """Per tier ("level or higher"): flagged count, fraud recall, legit false-positive rate, precision."""
    n_fraud = int(is_fraud.sum())
    n_legit = int((~is_fraud).sum())
    out = {}
    for level in LEVEL_ORDER[1:]:
        flagged = rank >= LEVEL_ORDER.index(level)
        tp = int((flagged & is_fraud).sum())
        fp = int((flagged & ~is_fraud).sum())
        out[level] = {
            "flagged": tp + fp,
            "recall": tp / n_fraud if n_fraud else 0.0,
            "legit_fpr": fp / n_legit if n_legit else 0.0,
            "precision": tp / (tp + fp) if tp + fp else 0.0,
        }
    return out
