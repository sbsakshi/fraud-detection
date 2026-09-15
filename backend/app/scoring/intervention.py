"""The six-level intervention ladder, read from a config file rather than hardcoded.

`decide_intervention` is a pure function of `(fused_score, confidence)` --
tuning what counts as HOLD vs. RESTRICT is a config-file edit, not a code
change, which is what lets this be swept during evaluation (Phase 8) or
adjusted operationally without a deploy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.models.enums import InterventionLevel

CONFIG_PATH = Path(__file__).resolve().parent / "intervention_config.json"


@dataclass(frozen=True)
class InterventionLadder:
    # Highest-severity first; each entry: {"level": str, "min_score": float, "min_confidence": float}.
    levels: tuple[dict, ...]


def load_intervention_ladder(path: Path = CONFIG_PATH) -> InterventionLadder:
    with open(path) as f:
        data = json.load(f)
    return InterventionLadder(levels=tuple(data["levels"]))


_ladder: InterventionLadder | None = None


def get_intervention_ladder() -> InterventionLadder:
    global _ladder
    if _ladder is None:
        _ladder = load_intervention_ladder()
    return _ladder


def decide_intervention(
    fused_score: float, confidence: float, ladder: InterventionLadder | None = None
) -> InterventionLevel:
    ladder = ladder or get_intervention_ladder()
    for entry in ladder.levels:
        if fused_score >= entry["min_score"] and confidence >= entry["min_confidence"]:
            return InterventionLevel(entry["level"])
    # Unreachable as long as the config's last entry has min_score=0 and
    # min_confidence=0 -- INFORM is the deliberate, safe fallback if it isn't.
    return InterventionLevel.INFORM
