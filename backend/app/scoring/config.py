"""The scoring config file: intervention ladder + fusion weights, and its version.

One JSON file holds both because they are tuned together (`scripts/tune_fusion.py`)
and a score only means something relative to the pair. `config_version()` is a
short content hash of the file, stored on every `RiskScore` so a decision can be
traced back to the exact thresholds and weights that produced it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "intervention_config.json"

# Used only if the file has no "fusion_weights" key (e.g. a custom test config).
FALLBACK_WEIGHTS = {"rule": 0.25, "ml": 0.5, "graph": 0.25}


def load_config(path: Path = CONFIG_PATH) -> dict:
    with open(path) as f:
        return json.load(f)


def load_weights(path: Path = CONFIG_PATH) -> dict[str, float]:
    return dict(load_config(path).get("fusion_weights", FALLBACK_WEIGHTS))


def config_version(path: Path = CONFIG_PATH) -> str:
    """First 12 hex chars of the file's SHA-256: changes whenever any threshold or weight does."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]
